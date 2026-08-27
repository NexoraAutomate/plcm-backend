"""
Spec 04 — reserve AVAILABLE inventory against Flight → SDLS → hierarchy nodes.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, NoReturn, Optional

from sqlmodel import Session, col, select

from app.domain.status_transitions import assert_transition
from app.domain.workflow_status import ItemStatus, ProjectWorkflowStatus
from app.domain.hierarchy_config import (
    InventorySource,
    is_build_from_children,
    normalize_inventory_source,
)
from app.models.base import (
    AUTO_RELEASE_EXPIRY_REASON,
    InventoryReservationStatus,
    IssuanceStatus,
)
from app.models.helpers import _ENTITY_MODEL_MAP
from app.models.tables import (
    Flight,
    HierarchyConfigNode,
    Inventory,
    InventoryInstance,
    InventoryIssuance,
    InventoryReservation,
    Module,
    Project,
    Sdls,
    Status,
    Subsystem,
    System,
    Unit,
    User,
)
from app.services.inventory_issuance_service import (
    open_issuance_for_instance,
)
from app.services.inventory_service import (
    find_inventory_group,
    is_component_inventory,
)
from app.services.project_workflow_service import project_status_name
from app.domain.workflow_audit import WorkflowAuditAction
from app.services.workflow_audit_service import write_workflow_audit

DEFAULT_RESERVATION_DAYS = 30
DEFAULT_RESERVATION_GRACE_DAYS = 7


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def reservation_idle_days() -> int:
    """Days of idle RESERVED stock before the Spec 06 reminder (env: RESERVATION_IDLE_DAYS)."""
    return max(1, _env_int("RESERVATION_IDLE_DAYS", DEFAULT_RESERVATION_DAYS))


def reservation_grace_days() -> int:
    """Days after idle reminder before auto-release (env: RESERVATION_GRACE_DAYS)."""
    return max(0, _env_int("RESERVATION_GRACE_DAYS", DEFAULT_RESERVATION_GRACE_DAYS))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

RESERVABLE_ENTITY_TYPES = frozenset(
    {"system", "subsystem", "module", "unit", "component"}
)


class InventoryReservationError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_item_status_id(session: Session, status_name: str) -> int:
    status = session.exec(
        select(Status).where(
            Status.status_name == status_name,
            Status.status_type == "inventory",
        )
    ).first()
    if not status or status.id is None:
        raise InventoryReservationError(
            f"Required inventory status '{status_name}' is not seeded"
        )
    return int(status.id)


def item_status_name(session: Session, status_id: Optional[int]) -> Optional[str]:
    if status_id is None:
        return None
    status = session.get(Status, status_id)
    return status.status_name if status else None


def assert_project_can_reserve(project: Project) -> None:
    status = project_status_name(project)
    if status != ProjectWorkflowStatus.READY_FOR_INVENTORY.value:
        raise InventoryReservationError(
            "Project must be READY_FOR_INVENTORY to reserve inventory "
            f"(current: {status or 'unknown'})"
        )


def assert_no_open_config_change_for_reserve(session: Session, project_id: int) -> None:
    from app.services.config_change_service import (
        ConfigChangeError,
        assert_no_open_config_change,
    )

    try:
        assert_no_open_config_change(session, project_id, action="reservation")
    except ConfigChangeError as exc:
        raise InventoryReservationError(str(exc)) from exc


def active_reservation_for_instance(
    session: Session, instance_id: int
) -> Optional[InventoryReservation]:
    return session.exec(
        select(InventoryReservation).where(
            InventoryReservation.inventory_instance_id == instance_id,
            InventoryReservation.status == InventoryReservationStatus.ACTIVE.value,
        )
    ).first()


def active_reservations_for_inventory(
    session: Session, inventory_id: int
) -> list[InventoryReservation]:
    return list(
        session.exec(
            select(InventoryReservation).where(
                InventoryReservation.inventory_id == inventory_id,
                InventoryReservation.status == InventoryReservationStatus.ACTIVE.value,
            )
        ).all()
    )


def project_hold_to_dict(
    session: Session, reservation: InventoryReservation
) -> dict[str, Any]:
    """Compact HM reservation payload for inventory serial status / dialog."""
    project = reservation.project or session.get(Project, reservation.project_id)
    target_name = None
    try:
        entity = _load_hierarchy_entity(
            session, reservation.target_entity_type, reservation.target_entity_id
        )
        target_name = getattr(entity, "name", None)
    except InventoryReservationError:
        target_name = None
    return {
        "id": reservation.id,
        "project_id": reservation.project_id,
        "project_name": project.name if project else None,
        "flight_id": reservation.flight_id,
        "flight_code": reservation.flight.code if reservation.flight else None,
        "flight_name": reservation.flight.name if reservation.flight else None,
        "sdls_id": reservation.sdls_id,
        "sdls_code": reservation.sdls.code if reservation.sdls else None,
        "sdls_name": reservation.sdls.name if reservation.sdls else None,
        "target_entity_type": reservation.target_entity_type,
        "target_entity_id": reservation.target_entity_id,
        "target_entity_name": target_name,
        "reserved_by_user_id": reservation.reserved_by_user_id,
        "reserved_by_name": (
            (reservation.reserved_by.full_name or reservation.reserved_by.username)
            if reservation.reserved_by
            else None
        ),
        "reserved_at": reservation.reserved_at,
        "expires_at": reservation.expires_at,
        "last_reminder_at": reservation.last_reminder_at,
        "serial_number": reservation.serial_number,
        "part_number": reservation.part_number,
        "inventory_name": reservation.inventory.name if reservation.inventory else None,
    }


def project_holds_by_instance_id(
    session: Session, inventory_id: int
) -> dict[int, dict[str, Any]]:
    rows = active_reservations_for_inventory(session, inventory_id)
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.inventory_instance_id is None:
            continue
        out[int(row.inventory_instance_id)] = project_hold_to_dict(session, row)
    return out


def project_reserved_quantity(session: Session, inventory_id: int) -> int:
    """Count of active Spec 04 reservations for an inventory group."""
    rows = active_reservations_for_inventory(session, inventory_id)
    return len(rows)


def is_instance_free_for_project_reserve(
    session: Session, instance: InventoryInstance
) -> bool:
    if instance.id is None:
        return False
    if active_reservation_for_instance(session, int(instance.id)):
        return False
    if open_issuance_for_instance(session, int(instance.id)):
        return False
    current = item_status_name(session, instance.status_id)
    if current in {
        ItemStatus.RESERVED.value,
        ItemStatus.ISSUED.value,
        ItemStatus.INSTALLATION_IN_PROGRESS.value,
        ItemStatus.UNDER_TESTING_REVIEW.value,
        ItemStatus.INSTALLED_VERIFIED.value,
        ItemStatus.RETURNED.value,
        ItemStatus.INSPECTION.value,
        ItemStatus.REPAIRABLE.value,
        ItemStatus.REUSABLE.value,
        ItemStatus.SCRAPPED.value,
    }:
        return False
    return True


def _load_hierarchy_entity(
    session: Session, entity_type: str, entity_id: int
) -> Any:
    key = entity_type.strip().lower()
    entry = _ENTITY_MODEL_MAP.get(key)
    if not entry:
        raise InventoryReservationError(f"Unsupported entity type: {entity_type}")
    model, _pk, _label = entry
    entity = session.get(model, entity_id)
    if not entity:
        raise InventoryReservationError(
            f"{entity_type} {entity_id} not found"
        )
    return entity


def _config_source_for_entity(
    session: Session,
    *,
    project_id: int,
    entity_type: str,
    entity_name: str,
) -> Optional[str]:
    """Look up inventory_source from the project's hierarchy configuration template."""
    project = session.get(Project, project_id)
    if project is None or project.hierarchy_config_id is None:
        return None
    et = entity_type.strip().lower()
    name = (entity_name or "").strip()
    if not name:
        return None
    node = session.exec(
        select(HierarchyConfigNode).where(
            HierarchyConfigNode.configuration_id == project.hierarchy_config_id,
            HierarchyConfigNode.level == et,
            col(HierarchyConfigNode.name).ilike(name),
        )
    ).first()
    if node is None:
        return None
    try:
        return normalize_inventory_source(getattr(node, "inventory_source", None))
    except ValueError:
        return None


def effective_inventory_source(
    session: Session,
    *,
    entity: Any,
    entity_type: str,
    project_id: int,
    heal: bool = True,
) -> str:
    """
    Resolve TURNKEY vs BUILD for a hierarchy shell.

    Priority: runtime children (structural parent) → entity snapshot →
    project config template (level+name) → turnkey.
    Parents with generated child shells are always BUILD regardless of stale
    turnkey flags or warehouse stock.
    """
    et = entity_type.strip().lower()
    eid = getattr(entity, "id", None)
    if eid is not None:
        from app.services.inventory_assembly_service import _direct_children

        if _direct_children(session, et, int(eid)):
            resolved = InventorySource.BUILD_FROM_CHILDREN.value
            if heal and hasattr(entity, "inventory_source"):
                current = getattr(entity, "inventory_source", None)
                try:
                    current_norm = (
                        normalize_inventory_source(current) if current else None
                    )
                except ValueError:
                    current_norm = None
                if current_norm != resolved:
                    entity.inventory_source = resolved
                    session.add(entity)
                    session.flush()
            return resolved

    raw = getattr(entity, "inventory_source", None)
    if raw is not None and str(raw).strip():
        try:
            return normalize_inventory_source(raw)
        except ValueError:
            pass

    from_config = _config_source_for_entity(
        session,
        project_id=project_id,
        entity_type=entity_type,
        entity_name=str(getattr(entity, "name", "") or ""),
    )
    resolved = from_config or InventorySource.TURNKEY.value

    if heal and hasattr(entity, "inventory_source"):
        current = getattr(entity, "inventory_source", None)
        if current is None or not str(current).strip():
            entity.inventory_source = resolved
            session.add(entity)
            session.flush()

    return resolved


def _resolve_flight_sdls_for_entity(
    session: Session, entity_type: str, entity: Any
) -> tuple[Flight, Sdls, System]:
    """Walk hierarchy up to System → SDLS → Flight."""
    et = entity_type.strip().lower()
    system: Optional[System] = None

    if et == "system":
        system = entity
    elif et == "subsystem":
        system = session.get(System, entity.system_id)
    elif et == "module":
        sub = session.get(Subsystem, entity.subsystem_id)
        if not sub:
            raise InventoryReservationError("Subsystem parent not found")
        system = session.get(System, sub.system_id)
    elif et == "unit":
        mod = session.get(Module, entity.module_id)
        if not mod:
            raise InventoryReservationError("Module parent not found")
        sub = session.get(Subsystem, mod.subsystem_id)
        if not sub:
            raise InventoryReservationError("Subsystem parent not found")
        system = session.get(System, sub.system_id)
    elif et == "component":
        unit = session.get(Unit, entity.unit_id)
        if not unit:
            raise InventoryReservationError("Unit parent not found")
        mod = session.get(Module, unit.module_id)
        if not mod:
            raise InventoryReservationError("Module parent not found")
        sub = session.get(Subsystem, mod.subsystem_id)
        if not sub:
            raise InventoryReservationError("Subsystem parent not found")
        system = session.get(System, sub.system_id)
    else:
        raise InventoryReservationError(f"Unsupported entity type: {entity_type}")

    if not system:
        raise InventoryReservationError("Could not resolve System parent")
    if not system.sdls_id:
        raise InventoryReservationError(
            "Hierarchy entity is not linked to an SDLS (generate hierarchy first)"
        )
    sdls = session.get(Sdls, system.sdls_id)
    if not sdls:
        raise InventoryReservationError("SDLS not found for hierarchy entity")
    flight = session.get(Flight, sdls.flight_id)
    if not flight:
        raise InventoryReservationError("Flight not found for hierarchy entity")
    return flight, sdls, system


def resolve_inventory_for_entity(
    session: Session,
    *,
    entity_type: str,
    entity: Any,
    part_number: Optional[str] = None,
) -> Inventory:
    name = getattr(entity, "name", None) or ""
    pn = part_number
    if pn is None:
        pn = getattr(entity, "part_number", None)
    group = find_inventory_group(
        session,
        name=str(name),
        inventory_type=entity_type.strip().lower(),
        part_number=pn,
    )
    if not group:
        # Fallback: match by name+type ignoring empty PN on stock that has PN
        group = session.exec(
            select(Inventory).where(
                Inventory.inventory_type == entity_type.strip().lower(),
                col(Inventory.name).ilike(str(name).strip()),
            )
        ).first()
    if not group:
        raise InventoryReservationError(
            f"No inventory stock found for {entity_type} '{name}'"
            + (f" (PN {pn})" if pn else "")
        )
    return group


def pick_free_instance(
    session: Session,
    inventory: Inventory,
    *,
    serial_number: Optional[str] = None,
    instance_id: Optional[int] = None,
) -> Optional[InventoryInstance]:
    if is_component_inventory(inventory.inventory_type):
        return None

    if instance_id is not None:
        inst = session.get(InventoryInstance, instance_id)
        if not inst or inst.inventory_id != inventory.id:
            raise InventoryReservationError("Inventory instance not found in group")
        if not is_instance_free_for_project_reserve(session, inst):
            raise InventoryReservationError(
                "Inventory instance is not available for reservation"
            )
        if serial_number and (inst.serial_number or "").strip().lower() != serial_number.strip().lower():
            raise InventoryReservationError("Serial number does not match instance")
        return inst

    instances = list(
        session.exec(
            select(InventoryInstance).where(
                InventoryInstance.inventory_id == inventory.id
            )
        ).all()
    )
    if serial_number:
        sn = serial_number.strip().lower()
        match = next(
            (i for i in instances if (i.serial_number or "").strip().lower() == sn),
            None,
        )
        if not match:
            raise InventoryReservationError(
                f"Serial '{serial_number}' not found in inventory"
            )
        if not is_instance_free_for_project_reserve(session, match):
            raise InventoryReservationError(
                f"Serial '{serial_number}' is not available for reservation"
            )
        return match

    for inst in instances:
        if is_instance_free_for_project_reserve(session, inst):
            return inst
    return None


_LIFECYCLE_PLAN_STATUS: dict[str, str] = {
    ItemStatus.RESERVED.value: "reserved",
    ItemStatus.ISSUED.value: "issued",
    ItemStatus.INSTALLATION_IN_PROGRESS.value: "installing",
    ItemStatus.UNDER_TESTING_REVIEW.value: "testing",
    ItemStatus.INSTALLED_VERIFIED.value: "verified",
    ItemStatus.RETURNED.value: "returned",
    ItemStatus.INSPECTION.value: "inspection",
    ItemStatus.REUSABLE.value: "reusable",
    ItemStatus.REPAIRABLE.value: "repairable",
    ItemStatus.SCRAPPED.value: "scrapped",
}

_LIFECYCLE_REASONS: dict[str, str] = {
    ItemStatus.RESERVED.value: "Reserved for this hierarchy node",
    ItemStatus.ISSUED.value: "Issued to developer — installation not started",
    ItemStatus.INSTALLATION_IN_PROGRESS.value: "Installation in progress",
    ItemStatus.UNDER_TESTING_REVIEW.value: "Under testing / review — awaiting HM verification",
    ItemStatus.INSTALLED_VERIFIED.value: "Installed and verified",
    ItemStatus.RETURNED.value: "Returned — awaiting IM disposition",
    ItemStatus.INSPECTION.value: "Under IM inspection",
    ItemStatus.REUSABLE.value: "Inspection complete — reusable",
    ItemStatus.REPAIRABLE.value: "Marked repairable",
    ItemStatus.SCRAPPED.value: "Scrapped",
}


def _plan_status_for_item_lifecycle(item_status: str) -> str:
    normalized = (item_status or "").strip().upper()
    return _LIFECYCLE_PLAN_STATUS.get(normalized, "in_progress")


def _lifecycle_reason(item_status: str) -> str:
    normalized = (item_status or "").strip().upper()
    return _LIFECYCLE_REASONS.get(
        normalized, "Already committed to this hierarchy node"
    )


def _entity_commitment_state(
    session: Session,
    *,
    project_id: int,
    entity_type: str,
    entity_id: int,
    flight_id: int,
    sdls_id: int,
    system_id: int,
    inventory_source: str,
) -> Optional[dict[str, Any]]:
    """
    Return plan/availability payload when a node is already reserved, issued,
    installing, testing, or verified — so HM cannot pick warehouse stock again.
    """
    et = entity_type.strip().lower()
    eid = int(entity_id)

    from app.services.item_install_verify_service import (
        current_item_status,
        install_progress_payload,
        open_issuance_for_entity,
    )

    issuance = open_issuance_for_entity(session, et, eid)
    if issuance is not None and int(issuance.project_id or 0) == int(project_id):
        progress = install_progress_payload(session, et, eid, issuance=issuance)
        item_status = str(progress.get("item_status") or ItemStatus.ISSUED.value)
        plan_status = _plan_status_for_item_lifecycle(item_status)
        return {
            "available": False,
            "assemble": False,
            "plan_status": plan_status,
            "item_status": item_status,
            "reason": _lifecycle_reason(item_status),
            "free_quantity": 0,
            "inventory_id": issuance.inventory_id,
            "inventory_name": (
                issuance.inventory.name if issuance.inventory else None
            ),
            "part_number": issuance.part_number or (
                issuance.inventory.part_number if issuance.inventory else None
            ),
            "serial_numbers": [issuance.serial_number]
            if issuance.serial_number
            else [],
            "suggested_serial": issuance.serial_number,
            "reservation_id": None,
            "issuance_id": issuance.id,
            "flight_id": flight_id,
            "sdls_id": sdls_id,
            "system_id": system_id,
            "inventory_source": inventory_source,
        }

    active = session.exec(
        select(InventoryReservation).where(
            InventoryReservation.project_id == project_id,
            InventoryReservation.target_entity_type == et,
            InventoryReservation.target_entity_id == eid,
            InventoryReservation.status == InventoryReservationStatus.ACTIVE.value,
        )
    ).first()
    if active:
        item_status = ItemStatus.RESERVED.value
        return {
            "available": False,
            "assemble": False,
            "plan_status": "reserved",
            "item_status": item_status,
            "reason": _lifecycle_reason(item_status),
            "free_quantity": 0,
            "inventory_id": active.inventory_id,
            "inventory_name": active.inventory.name if active.inventory else None,
            "part_number": active.part_number,
            "serial_numbers": [active.serial_number] if active.serial_number else [],
            "suggested_serial": active.serial_number,
            "reservation_id": active.id,
            "issuance_id": None,
            "flight_id": flight.id if (flight := active.flight) else flight_id,
            "sdls_id": sdls.id if (sdls := active.sdls) else sdls_id,
            "system_id": system_id,
            "inventory_source": inventory_source,
        }

    consumed = session.exec(
        select(InventoryReservation)
        .where(
            InventoryReservation.project_id == project_id,
            InventoryReservation.target_entity_type == et,
            InventoryReservation.target_entity_id == eid,
            InventoryReservation.status == InventoryReservationStatus.CONSUMED.value,
        )
        .order_by(col(InventoryReservation.reserved_at).desc())
    ).first()
    if consumed:
        item_status = ItemStatus.ISSUED.value
        return {
            "available": False,
            "assemble": False,
            "plan_status": _plan_status_for_item_lifecycle(item_status),
            "item_status": item_status,
            "reason": "Previously reserved and issued to this hierarchy node",
            "free_quantity": 0,
            "inventory_id": consumed.inventory_id,
            "inventory_name": consumed.inventory.name if consumed.inventory else None,
            "part_number": consumed.part_number,
            "serial_numbers": [consumed.serial_number]
            if consumed.serial_number
            else [],
            "suggested_serial": consumed.serial_number,
            "reservation_id": consumed.id,
            "issuance_id": None,
            "flight_id": flight_id,
            "sdls_id": sdls_id,
            "system_id": system_id,
            "inventory_source": inventory_source,
        }

    verified_issuance = session.exec(
        select(InventoryIssuance)
        .where(
            InventoryIssuance.project_id == project_id,
            InventoryIssuance.target_entity_type == et,
            InventoryIssuance.target_entity_id == eid,
            InventoryIssuance.verified_at.is_not(None),
            InventoryIssuance.status != IssuanceStatus.REVERTED.value,
            InventoryIssuance.status != IssuanceStatus.RETURNED.value,
        )
        .order_by(col(InventoryIssuance.verified_at).desc())
    ).first()
    if verified_issuance:
        item_status = current_item_status(session, verified_issuance)
        plan_status = _plan_status_for_item_lifecycle(item_status)
        return {
            "available": False,
            "assemble": False,
            "plan_status": plan_status,
            "item_status": item_status,
            "reason": _lifecycle_reason(item_status),
            "free_quantity": 0,
            "inventory_id": verified_issuance.inventory_id,
            "inventory_name": (
                verified_issuance.inventory.name
                if verified_issuance.inventory
                else None
            ),
            "part_number": verified_issuance.part_number,
            "serial_numbers": [verified_issuance.serial_number]
            if verified_issuance.serial_number
            else [],
            "suggested_serial": verified_issuance.serial_number,
            "reservation_id": None,
            "issuance_id": verified_issuance.id,
            "flight_id": flight_id,
            "sdls_id": sdls_id,
            "system_id": system_id,
            "inventory_source": inventory_source,
        }

    return None


def check_availability(
    session: Session,
    *,
    project_id: int,
    target_entity_type: str,
    target_entity_id: int,
    part_number: Optional[str] = None,
    require_reserve_window: bool = True,
) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if not project:
        raise InventoryReservationError("Project not found")
    if require_reserve_window:
        assert_project_can_reserve(project)
        assert_no_open_config_change_for_reserve(session, project_id)

    et = target_entity_type.strip().lower()
    if et not in RESERVABLE_ENTITY_TYPES:
        raise InventoryReservationError(f"Unsupported target entity type: {et}")

    entity = _load_hierarchy_entity(session, et, target_entity_id)
    if et == "system" and getattr(entity, "project_id", None) != project_id:
        raise InventoryReservationError("System does not belong to this project")

    flight, sdls, system = _resolve_flight_sdls_for_entity(session, et, entity)
    if flight.project_id != project_id:
        raise InventoryReservationError("Hierarchy entity is not under this project")

    source = effective_inventory_source(
        session,
        entity=entity,
        entity_type=et,
        project_id=project_id,
    )

    committed = _entity_commitment_state(
        session,
        project_id=project_id,
        entity_type=et,
        entity_id=target_entity_id,
        flight_id=flight.id,
        sdls_id=sdls.id,
        system_id=system.id,
        inventory_source=source,
    )
    if committed:
        return committed

    if is_build_from_children(source):
        return {
            "available": False,
            "reason": (
                "This item is automatically created in inventory when its "
                "required child items are installed and verified"
            ),
            "assemble": True,
            "free_quantity": 0,
            "inventory_id": None,
            "inventory_name": None,
            "part_number": None,
            "flight_id": flight.id,
            "sdls_id": sdls.id,
            "system_id": system.id,
            "inventory_source": source,
        }

    inventory = resolve_inventory_for_entity(
        session, entity_type=et, entity=entity, part_number=part_number
    )

    if is_component_inventory(inventory.inventory_type):
        from app.services.inventory_issuance_service import reserved_quantity

        free = max(
            0,
            int(inventory.quantity or 0)
            - reserved_quantity(session, int(inventory.id))
            - project_reserved_quantity(session, int(inventory.id)),
        )
        return {
            "available": free >= 1,
            "free_quantity": free,
            "inventory_id": inventory.id,
            "inventory_name": inventory.name,
            "part_number": inventory.part_number,
            "flight_id": flight.id,
            "sdls_id": sdls.id,
            "system_id": system.id,
            "inventory_source": source,
            "assemble": False,
            "reason": None if free >= 1 else "No available quantity in stock",
        }

    free_instances = [
        i
        for i in session.exec(
            select(InventoryInstance).where(
                InventoryInstance.inventory_id == inventory.id
            )
        ).all()
        if is_instance_free_for_project_reserve(session, i)
    ]
    return {
        "available": len(free_instances) >= 1,
        "free_quantity": len(free_instances),
        "inventory_id": inventory.id,
        "inventory_name": inventory.name,
        "part_number": inventory.part_number,
        "serial_numbers": [i.serial_number for i in free_instances if i.serial_number],
        "flight_id": flight.id,
        "sdls_id": sdls.id,
        "system_id": system.id,
        "inventory_source": source,
        "assemble": False,
        "reason": None if free_instances else "No available serialized units in stock",
    }


def _raise_or_record_shortage(
    session: Session,
    *,
    create_shortage: bool,
    project: Project,
    flight: Flight,
    sdls: Sdls,
    entity: Any,
    entity_type: str,
    entity_id: int,
    actor: User,
    inventory: Optional[Inventory],
    message: str,
) -> NoReturn:
    if not create_shortage:
        raise InventoryReservationError(message)
    from app.services.inventory_shortage_service import (
        InventoryShortageCreated,
        record_shortage_for_reserve,
    )

    shortage = record_shortage_for_reserve(
        session,
        project=project,
        flight=flight,
        sdls=sdls,
        entity=entity,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        inventory=inventory,
    )
    raise InventoryShortageCreated(shortage, message)


def reserve_inventory(
    session: Session,
    project_id: int,
    payload: dict[str, Any],
    *,
    actor: User,
    create_shortage_if_unavailable: bool = True,
    commit: bool = True,
    allow_assembled: bool = False,
) -> InventoryReservation:
    project = session.get(Project, project_id)
    if not project:
        raise InventoryReservationError("Project not found")
    # Auto-assembly may run after the last child verify, which can already
    # mark the project COMPLETED. Skip the HM reserve-window check.
    if not allow_assembled:
        assert_project_can_reserve(project)
    assert_no_open_config_change_for_reserve(session, project_id)

    et = str(payload.get("target_entity_type") or "").strip().lower()
    try:
        eid = int(payload["target_entity_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InventoryReservationError(
            "target_entity_type and target_entity_id are required"
        ) from exc
    if et not in RESERVABLE_ENTITY_TYPES:
        raise InventoryReservationError(f"Unsupported target entity type: {et}")

    entity = _load_hierarchy_entity(session, et, eid)
    source = effective_inventory_source(
        session,
        entity=entity,
        entity_type=et,
        project_id=project_id,
    )
    if is_build_from_children(source) and not allow_assembled:
        raise InventoryReservationError(
            "This hierarchy node is configured as build-from-children and "
            "cannot be reserved from procured inventory"
        )
    flight, sdls, system = _resolve_flight_sdls_for_entity(session, et, entity)
    if flight.project_id != project_id:
        raise InventoryReservationError("Hierarchy entity is not under this project")

    if not allow_assembled:
        committed = _entity_commitment_state(
            session,
            project_id=project_id,
            entity_type=et,
            entity_id=eid,
            flight_id=flight.id,
            sdls_id=sdls.id,
            system_id=system.id,
            inventory_source=source,
        )
        if committed:
            raise InventoryReservationError(
                committed.get("reason") or "Hierarchy node is not open for reservation"
            )

    # Optional explicit flight/sdls must match resolved
    if payload.get("flight_id") is not None and int(payload["flight_id"]) != flight.id:
        raise InventoryReservationError("flight_id does not match hierarchy entity")
    if payload.get("sdls_id") is not None and int(payload["sdls_id"]) != sdls.id:
        raise InventoryReservationError("sdls_id does not match hierarchy entity")

    existing_node = session.exec(
        select(InventoryReservation).where(
            InventoryReservation.project_id == project_id,
            InventoryReservation.target_entity_type == et,
            InventoryReservation.target_entity_id == eid,
            InventoryReservation.status == InventoryReservationStatus.ACTIVE.value,
        )
    ).first()
    if existing_node:
        raise InventoryReservationError(
            "Hierarchy node already has an active reservation"
        )

    part_number = payload.get("part_number")
    inventory: Optional[Inventory] = None
    if payload.get("inventory_id"):
        inventory = session.get(Inventory, int(payload["inventory_id"]))
        if not inventory:
            raise InventoryReservationError("Inventory not found")
    else:
        try:
            inventory = resolve_inventory_for_entity(
                session, entity_type=et, entity=entity, part_number=part_number
            )
        except InventoryReservationError as exc:
            if "No inventory stock found" in str(exc):
                _raise_or_record_shortage(
                    session,
                    create_shortage=create_shortage_if_unavailable,
                    project=project,
                    flight=flight,
                    sdls=sdls,
                    entity=entity,
                    entity_type=et,
                    entity_id=eid,
                    actor=actor,
                    inventory=None,
                    message=str(exc),
                )
            raise

    serial_number = payload.get("serial_number")
    instance_id = payload.get("inventory_instance_id")
    instance: Optional[InventoryInstance] = None

    if is_component_inventory(inventory.inventory_type):
        avail = check_availability(
            session,
            project_id=project_id,
            target_entity_type=et,
            target_entity_id=eid,
            part_number=inventory.part_number,
        )
        if not avail["available"]:
            _raise_or_record_shortage(
                session,
                create_shortage=create_shortage_if_unavailable,
                project=project,
                flight=flight,
                sdls=sdls,
                entity=entity,
                entity_type=et,
                entity_id=eid,
                actor=actor,
                inventory=inventory,
                message=avail.get("reason") or "Stock not available",
            )
    else:
        instance = pick_free_instance(
            session,
            inventory,
            serial_number=serial_number,
            instance_id=int(instance_id) if instance_id is not None else None,
        )
        if instance is None:
            _raise_or_record_shortage(
                session,
                create_shortage=create_shortage_if_unavailable,
                project=project,
                flight=flight,
                sdls=sdls,
                entity=entity,
                entity_type=et,
                entity_id=eid,
                actor=actor,
                inventory=inventory,
                message="No available inventory unit to reserve",
            )
        # Double-check no other project holds this instance
        if active_reservation_for_instance(session, int(instance.id)):
            raise InventoryReservationError(
                "Unit is already reserved by another project"
            )

    # Status transition AVAILABLE → RESERVED (treat missing as AVAILABLE)
    available_id = get_item_status_id(session, ItemStatus.AVAILABLE.value)
    reserved_id = get_item_status_id(session, ItemStatus.RESERVED.value)

    if instance is not None:
        current = item_status_name(session, instance.status_id) or ItemStatus.AVAILABLE.value
        try:
            assert_transition("item", current, ItemStatus.RESERVED.value)
        except ValueError as exc:
            raise InventoryReservationError(str(exc)) from exc
        instance.status_id = reserved_id
        instance.updated_at = _now()
        session.add(instance)
    else:
        current = item_status_name(session, inventory.status_id) or ItemStatus.AVAILABLE.value
        try:
            assert_transition("item", current, ItemStatus.RESERVED.value)
        except ValueError as exc:
            # Component qty groups may already be AVAILABLE with partial reserves
            if current != ItemStatus.AVAILABLE.value and current != ItemStatus.RESERVED.value:
                raise InventoryReservationError(str(exc)) from exc
        if current == ItemStatus.AVAILABLE.value or inventory.status_id is None:
            inventory.status_id = reserved_id
            inventory.updated_at = _now()
            session.add(inventory)

    expires_at = payload.get("expires_at")
    if expires_at is None:
        expires_at = _now() + timedelta(days=reservation_idle_days())
    elif isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))

    reservation = InventoryReservation(
        project_id=project_id,
        flight_id=int(flight.id),
        sdls_id=int(sdls.id),
        target_entity_type=et,
        target_entity_id=eid,
        inventory_id=int(inventory.id),
        inventory_instance_id=int(instance.id) if instance else None,
        reserved_by_user_id=int(actor.id),
        reserved_at=_now(),
        expires_at=expires_at,
        extension_count=0,
        part_number=inventory.part_number
        or getattr(entity, "part_number", None),
        serial_number=(instance.serial_number if instance else serial_number),
        status=InventoryReservationStatus.ACTIVE.value,
        notes=payload.get("notes"),
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(reservation)
    session.flush()
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, project_id)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.RESERVED,
        entity_type="inventory_reservation",
        entity_id=int(reservation.id),
        actor=actor,
        project_id=project_id,
        old_value={"status": ItemStatus.AVAILABLE.value},
        new_value={
            "status": ItemStatus.RESERVED.value,
            "inventory_id": inventory.id,
            "inventory_instance_id": instance.id if instance else None,
            "target_entity_type": et,
            "target_entity_id": eid,
        },
        remarks=payload.get("notes"),
    )
    if commit:
        session.commit()
        session.refresh(reservation)
    return reservation


def release_reservation(
    session: Session,
    project_id: int,
    reservation_id: int,
    *,
    actor: Optional[User] = None,
    reason: Optional[str] = None,
    commit: bool = True,
) -> InventoryReservation:
    reservation = session.get(InventoryReservation, reservation_id)
    if not reservation or reservation.project_id != project_id:
        raise InventoryReservationError("Reservation not found")
    if reservation.status != InventoryReservationStatus.ACTIVE.value:
        raise InventoryReservationError("Reservation is not active")

    available_id = get_item_status_id(session, ItemStatus.AVAILABLE.value)

    if reservation.inventory_instance_id:
        instance = session.get(InventoryInstance, reservation.inventory_instance_id)
        if instance:
            current = (
                item_status_name(session, instance.status_id)
                or ItemStatus.RESERVED.value
            )
            try:
                assert_transition(
                    "item", current, ItemStatus.AVAILABLE.value
                )
            except ValueError as exc:
                raise InventoryReservationError(str(exc)) from exc
            instance.status_id = available_id
            instance.updated_at = _now()
            session.add(instance)
    else:
        inventory = session.get(Inventory, reservation.inventory_id)
        if inventory:
            # Only flip group back to AVAILABLE if no other active reservations
            others = [
                r
                for r in active_reservations_for_inventory(session, int(inventory.id))
                if r.id != reservation.id
            ]
            if not others:
                current = (
                    item_status_name(session, inventory.status_id)
                    or ItemStatus.RESERVED.value
                )
                if current == ItemStatus.RESERVED.value:
                    try:
                        assert_transition(
                            "item", current, ItemStatus.AVAILABLE.value
                        )
                    except ValueError as exc:
                        raise InventoryReservationError(str(exc)) from exc
                    inventory.status_id = available_id
                    inventory.updated_at = _now()
                    session.add(inventory)

    reservation.status = InventoryReservationStatus.RELEASED.value
    reservation.released_at = _now()
    reservation.released_by_user_id = int(actor.id) if actor and actor.id else None
    if reason:
        tag = str(reason).strip()
        if tag:
            existing = (reservation.notes or "").strip()
            reservation.notes = f"{existing}\n{tag}".strip() if existing else tag
    reservation.updated_at = _now()
    session.add(reservation)

    from app.services.hierarchy_developer_service import (
        clear_developer_assignment_if_unissued,
    )

    clear_developer_assignment_if_unissued(
        session,
        reservation.target_entity_type,
        int(reservation.target_entity_id),
    )

    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, reservation.project_id)
    expiry = (reason or "").strip() == AUTO_RELEASE_EXPIRY_REASON
    write_workflow_audit(
        session,
        action=(
            WorkflowAuditAction.AUTO_RELEASE_EXPIRY
            if expiry
            else WorkflowAuditAction.RELEASED
        ),
        entity_type="inventory_reservation",
        entity_id=int(reservation.id),
        actor=None if expiry else actor,
        system=expiry,
        project_id=int(reservation.project_id),
        old_value={"status": InventoryReservationStatus.ACTIVE.value},
        new_value={"status": InventoryReservationStatus.RELEASED.value},
        remarks=reason,
    )
    if commit:
        session.commit()
        session.refresh(reservation)
    else:
        session.flush()
    return reservation


def consume_reservation(
    session: Session,
    reservation: InventoryReservation,
    *,
    actor: Optional[User] = None,
) -> InventoryReservation:
    """Mark an active reservation consumed by issue. Does not flip item status or commit."""
    if reservation.status != InventoryReservationStatus.ACTIVE.value:
        raise InventoryReservationError("Reservation is not active")
    reservation.status = InventoryReservationStatus.CONSUMED.value
    reservation.released_at = _now()
    reservation.released_by_user_id = int(actor.id) if actor and actor.id else None
    existing = (reservation.notes or "").strip()
    tag = "CONSUMED_ON_ISSUE"
    reservation.notes = f"{existing}\n{tag}".strip() if existing else tag
    reservation.updated_at = _now()
    session.add(reservation)
    return reservation


def active_reservation_for_entity(
    session: Session,
    target_entity_type: str,
    target_entity_id: int,
) -> Optional[InventoryReservation]:
    et = target_entity_type.strip().lower()
    return session.exec(
        select(InventoryReservation).where(
            InventoryReservation.target_entity_type == et,
            InventoryReservation.target_entity_id == int(target_entity_id),
            InventoryReservation.status == InventoryReservationStatus.ACTIVE.value,
        )
    ).first()


def extend_reservation(
    session: Session,
    project_id: int,
    reservation_id: int,
    *,
    actor: User,
) -> InventoryReservation:
    """Spec 06 optional: increment Extension Count and delay the idle/expiry clock."""
    reservation = session.get(InventoryReservation, reservation_id)
    if not reservation or reservation.project_id != project_id:
        raise InventoryReservationError("Reservation not found")
    if reservation.status != InventoryReservationStatus.ACTIVE.value:
        raise InventoryReservationError("Reservation is not active")
    reservation.extension_count = int(reservation.extension_count or 0) + 1
    reservation.last_reminder_at = None
    reserved_at = _aware(reservation.reserved_at)
    idle = reservation_idle_days()
    reservation.expires_at = reserved_at + timedelta(
        days=idle * (1 + reservation.extension_count)
    )
    reservation.updated_at = _now()
    session.add(reservation)
    session.commit()
    session.refresh(reservation)
    return reservation


def list_project_reservations(
    session: Session,
    project_id: int,
    *,
    active_only: bool = False,
) -> list[InventoryReservation]:
    query = select(InventoryReservation).where(
        InventoryReservation.project_id == project_id
    )
    if active_only:
        query = query.where(
            InventoryReservation.status == InventoryReservationStatus.ACTIVE.value
        )
    query = query.order_by(
        InventoryReservation.reserved_at.desc(), InventoryReservation.id.desc()
    )
    return list(session.exec(query).all())


def reservation_to_dict(reservation: InventoryReservation) -> dict[str, Any]:
    expires_at = reservation.expires_at
    auto_release_at = None
    if expires_at is not None:
        auto_release_at = _aware(expires_at) + timedelta(days=reservation_grace_days())
    return {
        "id": reservation.id,
        "project_id": reservation.project_id,
        "flight_id": reservation.flight_id,
        "sdls_id": reservation.sdls_id,
        "target_entity_type": reservation.target_entity_type,
        "target_entity_id": reservation.target_entity_id,
        "inventory_id": reservation.inventory_id,
        "inventory_instance_id": reservation.inventory_instance_id,
        "reserved_by_user_id": reservation.reserved_by_user_id,
        "reserved_at": reservation.reserved_at,
        "expires_at": reservation.expires_at,
        "auto_release_at": auto_release_at,
        "last_reminder_at": reservation.last_reminder_at,
        "extension_count": reservation.extension_count,
        "part_number": reservation.part_number,
        "serial_number": reservation.serial_number,
        "status": reservation.status,
        "released_at": reservation.released_at,
        "released_by_user_id": reservation.released_by_user_id,
        "notes": reservation.notes,
        "flight_code": reservation.flight.code if reservation.flight else None,
        "flight_name": reservation.flight.name if reservation.flight else None,
        "sdls_code": reservation.sdls.code if reservation.sdls else None,
        "sdls_name": reservation.sdls.name if reservation.sdls else None,
        "inventory_name": reservation.inventory.name if reservation.inventory else None,
        "reserved_by_name": (
            (reservation.reserved_by.full_name or reservation.reserved_by.username)
            if reservation.reserved_by
            else None
        ),
    }


def _plan_assignment_fields(
    session: Session,
    *,
    entity_type: str,
    entity: Any,
    entity_id: int,
    status_code: str,
) -> dict[str, Any]:
    from app.services.hierarchy_developer_service import (
        assigned_developer_payload,
        entity_is_physically_issued,
    )
    from app.services.inventory_assembly_service import get_assembled_inventory

    et = entity_type.strip().lower()
    eid = int(entity_id)
    payload = assigned_developer_payload(session, entity, et)
    issued = entity_is_physically_issued(session, et, eid)
    assembled = get_assembled_inventory(session, et, eid) is not None
    can_assign = status_code == "reserved" and not issued
    return {
        "assigned_developer_id": payload.get("assigned_developer_id"),
        "assigned_developer_name": payload.get("assigned_developer_name"),
        "can_assign_developer": can_assign,
        "assembled": assembled,
        "issued": issued,
    }


def _plan_row_for_entity(
    session: Session,
    *,
    project_id: int,
    entity_type: str,
    entity: Any,
    path_parts: list[str],
) -> dict[str, Any]:
    name = str(getattr(entity, "name", "") or "")
    eid = int(entity.id)
    source = effective_inventory_source(
        session,
        entity=entity,
        entity_type=entity_type,
        project_id=project_id,
    )
    base = {
        "target_entity_type": entity_type,
        "target_entity_id": eid,
        "entity_name": name,
        "path": " / ".join(path_parts),
        "depth": max(0, len(path_parts) - 2),
        "inventory_source": source,
    }
    try:
        avail = check_availability(
            session,
            project_id=project_id,
            target_entity_type=entity_type,
            target_entity_id=eid,
            require_reserve_window=False,
        )
    except InventoryReservationError as exc:
        return {
            **base,
            "status": "short",
            "available": False,
            "reason": str(exc),
            "free_quantity": 0,
            "inventory_id": None,
            "inventory_name": None,
            "part_number": None,
            "serial_numbers": [],
            "suggested_serial": None,
            "reservation_id": None,
            "flight_id": None,
            "sdls_id": None,
            "system_id": None,
            "inventory_source": source,
            "children_total": None,
            "children_complete": None,
        }

    if avail.get("plan_status"):
        status_code = str(avail["plan_status"])
    elif avail.get("reservation_id"):
        status_code = "reserved"
    elif avail.get("assemble"):
        status_code = "assemble"
    elif avail.get("available"):
        status_code = "available"
    else:
        status_code = "short"

    children_total: Optional[int] = None
    children_complete: Optional[int] = None
    if status_code == "assemble":
        children_total, children_complete = _assemble_children_progress(
            session, entity_type, eid
        )

    serials = list(avail.get("serial_numbers") or [])
    assignment = _plan_assignment_fields(
        session,
        entity_type=entity_type,
        entity=entity,
        entity_id=eid,
        status_code=status_code,
    )
    reason = avail.get("reason")
    if assignment.get("assembled") and status_code == "reserved":
        reason = (
            "Automatically assembled from verified children — "
            "assign a developer for IM to issue and install"
        )
    return {
        **base,
        "status": status_code,
        "available": bool(avail.get("available")),
        "reason": reason,
        "free_quantity": avail.get("free_quantity"),
        "inventory_id": avail.get("inventory_id"),
        "inventory_name": avail.get("inventory_name"),
        "part_number": avail.get("part_number"),
        "serial_numbers": serials,
        "suggested_serial": avail.get("suggested_serial") or (serials[0] if serials else None),
        "reservation_id": avail.get("reservation_id"),
        "issuance_id": avail.get("issuance_id"),
        "item_status": avail.get("item_status"),
        "flight_id": avail.get("flight_id"),
        "sdls_id": avail.get("sdls_id"),
        "system_id": avail.get("system_id"),
        "inventory_source": avail.get("inventory_source") or source,
        "children_total": children_total,
        "children_complete": children_complete,
        **assignment,
    }


def _assemble_children_progress(
    session: Session, entity_type: str, entity_id: int
) -> tuple[int, int]:
    """Return (total, complete) for immediate children of a BUILD node."""
    from app.services.inventory_assembly_service import (
        _direct_children,
        child_is_complete,
    )

    children = _direct_children(session, entity_type, int(entity_id))
    total = len(children)
    complete = sum(
        1
        for child_type, child in children
        if child_is_complete(session, child_type, child)
    )
    return total, complete


def build_reservation_plan(session: Session, project_id: int) -> dict[str, Any]:
    """
    Spec 04 UI — every reservable hierarchy shell under the project with a
    matched AVAILABLE stock suggestion (or short / already-reserved).
    """
    from app.services.entity_replacement_service import filter_current_installs

    project = session.get(Project, project_id)
    if not project:
        raise InventoryReservationError("Project not found")

    flights = session.exec(
        select(Flight)
        .where(Flight.project_id == project_id)
        .order_by(Flight.sequence, Flight.id)
    ).all()

    items: list[dict[str, Any]] = []
    for flight in flights:
        flight_label = flight.name or flight.code or f"Flight-{flight.id}"
        sdls_rows = session.exec(
            select(Sdls)
            .where(Sdls.flight_id == flight.id)
            .order_by(Sdls.sequence, Sdls.id)
        ).all()
        for sdls in sdls_rows:
            sdls_label = sdls.name or sdls.code or f"SDLS-{sdls.id}"
            systems = filter_current_installs(
                [
                    s
                    for s in (project.systems or [])
                    if s.sdls_id == sdls.id
                ]
            )
            systems = sorted(systems, key=lambda s: (s.name or "", int(s.id or 0)))
            for system in systems:
                sys_path = [flight_label, sdls_label, system.name]
                items.append(
                    _plan_row_for_entity(
                        session,
                        project_id=project_id,
                        entity_type="system",
                        entity=system,
                        path_parts=sys_path,
                    )
                )
                subsystems = filter_current_installs(list(system.subsystems or []))
                subsystems = sorted(
                    subsystems, key=lambda s: (s.name or "", int(s.id or 0))
                )
                for subsystem in subsystems:
                    sub_path = [*sys_path, subsystem.name]
                    items.append(
                        _plan_row_for_entity(
                            session,
                            project_id=project_id,
                            entity_type="subsystem",
                            entity=subsystem,
                            path_parts=sub_path,
                        )
                    )
                    modules = filter_current_installs(list(subsystem.modules or []))
                    modules = sorted(
                        modules, key=lambda m: (m.name or "", int(m.id or 0))
                    )
                    for module in modules:
                        mod_path = [*sub_path, module.name]
                        items.append(
                            _plan_row_for_entity(
                                session,
                                project_id=project_id,
                                entity_type="module",
                                entity=module,
                                path_parts=mod_path,
                            )
                        )
                        units = filter_current_installs(list(module.units or []))
                        units = sorted(
                            units, key=lambda u: (u.name or "", int(u.id or 0))
                        )
                        for unit in units:
                            unit_path = [*mod_path, unit.name]
                            items.append(
                                _plan_row_for_entity(
                                    session,
                                    project_id=project_id,
                                    entity_type="unit",
                                    entity=unit,
                                    path_parts=unit_path,
                                )
                            )
                            components = filter_current_installs(
                                list(unit.components or [])
                            )
                            components = sorted(
                                components,
                                key=lambda c: (c.name or "", int(c.id or 0)),
                            )
                            for component in components:
                                items.append(
                                    _plan_row_for_entity(
                                        session,
                                        project_id=project_id,
                                        entity_type="component",
                                        entity=component,
                                        path_parts=[*unit_path, component.name],
                                    )
                                )

    available = sum(1 for row in items if row["status"] == "available")
    short = sum(1 for row in items if row["status"] == "short")
    reserved = sum(1 for row in items if row["status"] == "reserved")
    assemble = sum(1 for row in items if row["status"] == "assemble")
    return {
        "project_id": project_id,
        "project_status": project_status_name(project),
        "total": len(items),
        "available_count": available,
        "short_count": short,
        "reserved_count": reserved,
        "assemble_count": assemble,
        "items": items,
    }
