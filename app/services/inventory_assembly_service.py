"""
Automatic inventory creation for BUILD-FROM-CHILDREN hierarchy nodes.

Triggered after a child is INSTALLED_VERIFIED (or after a parent is itself
assembled). Walks upward generically — no hard-coded SDLS/LRU/DPU names.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app.domain.hierarchy_config import is_build_from_children
from app.domain.workflow_audit import WorkflowAuditAction
from app.domain.workflow_status import ItemStatus
from app.models.base import IssuanceStatus
from app.models.helpers import _CHILD_MAP, _ENTITY_MODEL_MAP, _PARENT_MAP
from app.models.tables import (
    AssembledInventory,
    AppDefinitions,
    Inventory,
    InventoryChildLink,
    InventoryInstance,
    InventoryIssuance,
    Project,
    User,
)
from app.services.app_definitions_service import (
    DEFAULT_APP_DEFINITIONS,
    build_entity_identifiers,
)
from app.services.entity_replacement_service import filter_current_installs
from app.services.inventory_reservation_service import (
    RESERVABLE_ENTITY_TYPES,
    InventoryReservationError,
    _load_hierarchy_entity,
    _resolve_flight_sdls_for_entity,
    effective_inventory_source,
    get_item_status_id,
    reserve_inventory,
)
from app.services.inventory_service import create_inventory_instance
from app.services.workflow_audit_service import write_workflow_audit

MAX_ASSEMBLY_DEPTH = 16
ASSEMBLED_LOCATION = "Assembled"


class InventoryAssemblyError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entity_type_key(value: Any) -> str:
    """Canonical lowercase entity-type string.

    ``str(EntityType.SYSTEM)`` is ``'EntityType.SYSTEM'`` for ``str, Enum``
    mixins, so callers must use ``.value`` rather than ``str(enum)``.
    """
    if value is None:
        return ""
    raw = getattr(value, "value", value)
    return str(raw).strip().lower()


def get_assembled_inventory(
    session: Session, entity_type: str, entity_id: int
) -> Optional[AssembledInventory]:
    et = _entity_type_key(entity_type)
    return session.exec(
        select(AssembledInventory).where(
            AssembledInventory.target_entity_type == et,
            AssembledInventory.target_entity_id == int(entity_id),
        )
    ).first()


def _lock_entity(session: Session, entity_type: str, entity_id: int) -> Any:
    et = _entity_type_key(entity_type)
    entry = _ENTITY_MODEL_MAP.get(et)
    if not entry:
        raise InventoryAssemblyError(f"Unsupported entity type: {entity_type}")
    model = entry[0]
    entity = session.exec(
        select(model).where(model.id == int(entity_id)).with_for_update()
    ).first()
    if entity is None:
        raise InventoryAssemblyError(f"{entity_type} {entity_id} not found")
    return entity


def _immediate_parent(
    session: Session, entity_type: str, entity_id: int
) -> Optional[tuple[str, Any]]:
    et = _entity_type_key(entity_type)
    if et not in RESERVABLE_ENTITY_TYPES or et == "system":
        return None
    mapping = _PARENT_MAP.get(et)
    if not mapping:
        return None
    parent_type, current_model, fk_attr = mapping
    parent_type = _entity_type_key(parent_type)
    if parent_type not in RESERVABLE_ENTITY_TYPES:
        return None
    entity = session.get(current_model, int(entity_id))
    if entity is None:
        return None
    parent_id = getattr(entity, fk_attr, None)
    if parent_id is None:
        return None
    parent_model = _ENTITY_MODEL_MAP[parent_type][0]
    parent = session.get(parent_model, int(parent_id))
    if parent is None:
        return None
    return parent_type, parent


def _direct_children(
    session: Session, parent_type: str, parent_id: int
) -> list[tuple[str, Any]]:
    mapping = _CHILD_MAP.get(_entity_type_key(parent_type))
    if not mapping:
        return []
    child_type, child_model, fk_attr = mapping
    child_type = _entity_type_key(child_type)
    if child_type not in RESERVABLE_ENTITY_TYPES:
        return []
    rows = list(
        session.exec(
            select(child_model).where(getattr(child_model, fk_attr) == int(parent_id))
        ).all()
    )
    return [(child_type, row) for row in filter_current_installs(rows)]


def _has_verified_issuance(session: Session, entity_type: str, entity_id: int) -> bool:
    et = _entity_type_key(entity_type)
    row = session.exec(
        select(InventoryIssuance).where(
            InventoryIssuance.target_entity_type == et,
            InventoryIssuance.target_entity_id == int(entity_id),
            InventoryIssuance.verified_at.is_not(None),
            InventoryIssuance.status != IssuanceStatus.RETURNED.value,
            InventoryIssuance.status != IssuanceStatus.REVERTED.value,
        )
    ).first()
    return row is not None


def _project_id_for_entity(
    session: Session, entity_type: str, entity: Any
) -> Optional[int]:
    try:
        flight, _sdls, _system = _resolve_flight_sdls_for_entity(
            session, entity_type, entity
        )
    except InventoryReservationError:
        return None
    return int(flight.project_id) if flight.project_id is not None else None


def child_is_complete(session: Session, entity_type: str, entity: Any) -> bool:
    if entity is None or getattr(entity, "id", None) is None:
        return False
    project_id = _project_id_for_entity(session, entity_type, entity)
    if project_id is not None:
        source = effective_inventory_source(
            session,
            entity=entity,
            entity_type=entity_type,
            project_id=project_id,
        )
    else:
        source = getattr(entity, "inventory_source", None)
    if is_build_from_children(source):
        return (
            get_assembled_inventory(session, entity_type, int(entity.id)) is not None
        )
    return _has_verified_issuance(session, entity_type, int(entity.id))


def _all_children_complete(session: Session, parent_type: str, parent: Any) -> bool:
    children = _direct_children(session, parent_type, int(parent.id))
    if not children:
        return False
    return all(
        child_is_complete(session, child_type, child)
        for child_type, child in children
    )


def _child_trace_rows(
    session: Session, parent_type: str, parent_id: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child_type, child in _direct_children(session, parent_type, parent_id):
        assembled = get_assembled_inventory(session, child_type, int(child.id))
        issuance = session.exec(
            select(InventoryIssuance)
            .where(
                InventoryIssuance.target_entity_type == child_type,
                InventoryIssuance.target_entity_id == int(child.id),
                InventoryIssuance.verified_at.is_not(None),
            )
            .order_by(col(InventoryIssuance.verified_at).desc())
        ).first()
        inventory_id = None
        instance_id = None
        serial = getattr(child, "serial_number", None)
        if assembled is not None:
            inventory_id = assembled.inventory_id
            instance_id = assembled.inventory_instance_id
        elif issuance is not None:
            inventory_id = issuance.inventory_id
            instance_id = issuance.inventory_instance_id
            serial = issuance.serial_number or serial
        rows.append(
            {
                "entity_type": child_type,
                "entity_id": int(child.id),
                "name": getattr(child, "name", None),
                "inventory_id": inventory_id,
                "inventory_instance_id": instance_id,
                "serial_number": serial,
                "issuance_id": issuance.id if issuance is not None else None,
                "assembled_id": assembled.id if assembled is not None else None,
            }
        )
    return rows


def _next_identifier_state(
    session: Session, *, name: str, inventory_type: str
) -> tuple[Optional[Inventory], int, int]:
    groups = list(
        session.exec(
            select(Inventory).where(
                Inventory.inventory_type == inventory_type,
                func.lower(Inventory.name) == name.strip().lower(),
            )
        ).all()
    )
    if not groups:
        return None, 1, 1
    group = groups[0]
    count = session.exec(
        select(func.count())
        .select_from(InventoryInstance)
        .where(InventoryInstance.inventory_id == group.id)
    ).one()
    return group, 1, int(count) + 1


def _allocate_identifiers(
    session: Session,
    *,
    name: str,
    inventory_type: str,
    project_name: str,
) -> tuple[Optional[Inventory], dict[str, str]]:
    group, pn_seq, sn_seq = _next_identifier_state(
        session, name=name, inventory_type=inventory_type
    )
    definitions = session.exec(select(AppDefinitions).limit(1)).first()
    if definitions is None:
        definitions = AppDefinitions(**DEFAULT_APP_DEFINITIONS)
    cleaned = "".join(ch for ch in name if ch.isalnum())
    entity_abbr = (cleaned[:4] or inventory_type[:4]).upper()
    ident = build_entity_identifiers(
        definitions,
        project=project_name or "",
        name=name,
        seq=sn_seq,
        pn_seq=pn_seq,
        level=inventory_type,
        entity_abbr=entity_abbr,
        vendor="",
    )
    if group is not None and (group.part_number or "").strip():
        ident["part_number"] = group.part_number
        if not (ident.get("configuration_item") or "").strip():
            ident["configuration_item"] = group.part_number
    return group, ident


def _create_assembled_inventory(
    session: Session,
    *,
    parent_type: str,
    parent: Any,
    actor: User,
) -> AssembledInventory:
    flight, sdls, _system = _resolve_flight_sdls_for_entity(
        session, parent_type, parent
    )
    project = session.get(Project, flight.project_id)
    if project is None:
        raise InventoryAssemblyError("Project not found for assembled inventory")
    name = str(getattr(parent, "name", "") or "").strip()
    if not name:
        raise InventoryAssemblyError("Parent entity is missing a name")

    group, ident = _allocate_identifiers(
        session,
        name=name,
        inventory_type=parent_type,
        project_name=str(project.name or ""),
    )
    available_id = get_item_status_id(session, ItemStatus.AVAILABLE.value)
    if group is None:
        group = Inventory(
            name=name,
            inventory_type=parent_type,
            quantity=0,
            part_number=ident["part_number"],
            configuration_item=ident.get("configuration_item") or ident["part_number"],
            sku=ident.get("sku"),
            status_id=available_id,
            description="Automatically assembled from verified children",
        )
        session.add(group)
        session.flush()

    instance = create_inventory_instance(
        session,
        group,
        serial_number=ident["serial_number"],
        configuration_item=ident.get("configuration_item") or ident["part_number"],
        status_id=available_id,
        location=ASSEMBLED_LOCATION,
    )

    parent.part_number = ident["part_number"]
    parent.serial_number = ident["serial_number"]
    if hasattr(parent, "configuration_item"):
        parent.configuration_item = ident.get("configuration_item") or ident["part_number"]
    session.add(parent)

    child_rows = _child_trace_rows(session, parent_type, int(parent.id))
    for child in child_rows:
        if not child.get("inventory_id"):
            continue
        session.add(
            InventoryChildLink(
                parent_inventory_id=int(group.id),
                parent_instance_id=int(instance.id) if instance.id else None,
                child_category_name=str(child["entity_type"]),
                child_inventory_id=int(child["inventory_id"]),
                child_instance_id=child.get("inventory_instance_id"),
                parent_instance_serial=ident["serial_number"],
                child_instance_serial=child.get("serial_number"),
                stock_consumed=False,
            )
        )

    summary = {
        "children": child_rows,
        "flight_id": flight.id,
        "flight_code": flight.code,
        "sdls_id": sdls.id,
        "sdls_code": sdls.code,
        "configuration_id": project.hierarchy_config_id,
        "part_number": ident["part_number"],
        "serial_number": ident["serial_number"],
    }
    assembled = AssembledInventory(
        target_entity_type=parent_type,
        target_entity_id=int(parent.id),
        inventory_id=int(group.id),
        inventory_instance_id=int(instance.id) if instance.id else None,
        project_id=int(project.id) if project.id else None,
        flight_id=int(flight.id) if flight.id else None,
        sdls_id=int(sdls.id) if sdls.id else None,
        configuration_id=project.hierarchy_config_id,
        created_by_user_id=int(actor.id) if actor.id else None,
        source_summary=json.dumps(summary, default=str),
        created_at=_now(),
    )
    session.add(assembled)
    session.flush()

    try:
        reserve_inventory(
            session,
            int(project.id),
            {
                "target_entity_type": parent_type,
                "target_entity_id": int(parent.id),
                "inventory_id": int(group.id),
                "inventory_instance_id": int(instance.id) if instance.id else None,
                "serial_number": ident["serial_number"],
                "flight_id": int(flight.id),
                "sdls_id": int(sdls.id),
                "notes": "Automatically assembled from verified children",
            },
            actor=actor,
            create_shortage_if_unavailable=False,
            commit=False,
            allow_assembled=True,
        )
    except InventoryReservationError as exc:
        raise InventoryAssemblyError(str(exc)) from exc

    write_workflow_audit(
        session,
        action=WorkflowAuditAction.ASSEMBLED_INVENTORY,
        entity_type=parent_type,
        entity_id=int(parent.id),
        actor=actor,
        project_id=int(project.id) if project.id else None,
        new_value={
            "inventory_id": group.id,
            "inventory_instance_id": instance.id,
            "part_number": ident["part_number"],
            "serial_number": ident["serial_number"],
            "flight_id": flight.id,
            "sdls_id": sdls.id,
            "children": child_rows,
            "created_automatically": True,
        },
        remarks=(
            f"Automatically created {parent_type} '{name}' from verified children "
            f"for {flight.code or flight.name}/{sdls.code or sdls.name}"
        ),
    )
    return assembled


def evaluate_parent_assembly(
    session: Session,
    child_entity_type: str,
    child_entity_id: int,
    *,
    actor: User,
    _depth: int = 0,
) -> list[AssembledInventory]:
    """If the child's parent is BUILD and all siblings are complete, assemble it."""
    if _depth > MAX_ASSEMBLY_DEPTH:
        return []
    parent_info = _immediate_parent(session, child_entity_type, int(child_entity_id))
    if parent_info is None:
        return []
    parent_type, parent = parent_info
    project_id = _project_id_for_entity(session, parent_type, parent)
    if project_id is not None:
        parent_source = effective_inventory_source(
            session,
            entity=parent,
            entity_type=parent_type,
            project_id=project_id,
        )
    else:
        parent_source = getattr(parent, "inventory_source", None)
    if not is_build_from_children(parent_source):
        return []

    parent = _lock_entity(session, parent_type, int(parent.id))
    created: list[AssembledInventory] = []
    existing = get_assembled_inventory(session, parent_type, int(parent.id))
    if existing is None:
        if not _all_children_complete(session, parent_type, parent):
            return []
        try:
            with session.begin_nested():
                existing = _create_assembled_inventory(
                    session,
                    parent_type=parent_type,
                    parent=parent,
                    actor=actor,
                )
        except IntegrityError as exc:
            existing = get_assembled_inventory(session, parent_type, int(parent.id))
            if existing is None:
                raise InventoryAssemblyError(
                    f"Could not assemble {parent_type} {parent.id}"
                ) from exc
    if existing is None:
        return created
    created.append(existing)
    created.extend(
        evaluate_parent_assembly(
            session,
            parent_type,
            int(parent.id),
            actor=actor,
            _depth=_depth + 1,
        )
    )
    return created


def evaluate_assembly_after_verification(
    session: Session,
    issuance: InventoryIssuance,
    *,
    actor: User,
) -> list[AssembledInventory]:
    et = _entity_type_key(issuance.target_entity_type)
    eid = issuance.target_entity_id
    if not et or eid is None:
        return []
    try:
        _load_hierarchy_entity(session, et, int(eid))
    except InventoryReservationError:
        return []
    return evaluate_parent_assembly(session, et, int(eid), actor=actor)
