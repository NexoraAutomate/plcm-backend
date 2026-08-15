"""Spec 07 — assign a Developer to a hierarchy node."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.domain.workflow_roles import WorkflowRole, has_workflow_role
from app.models.base import ItemRequestStatus, IssuanceStatus
from app.models.helpers import _ENTITY_MODEL_MAP
from app.models.tables import (
    Component,
    InventoryIssuance,
    InventoryItemRequest,
    Module,
    Subsystem,
    System,
    Unit,
    User,
)
from app.services.inventory_reservation_service import RESERVABLE_ENTITY_TYPES

ASSIGNABLE_ENTITY_TYPES = RESERVABLE_ENTITY_TYPES


class HierarchyDeveloperError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role_names(user: User) -> list[str]:
    return [r.name for r in (user.roles or []) if r.name]


def _load_entity(session: Session, entity_type: str, entity_id: int) -> Any:
    key = (entity_type or "").strip().lower()
    if key not in ASSIGNABLE_ENTITY_TYPES:
        raise HierarchyDeveloperError(f"Unsupported entity type: {entity_type}")
    entry = _ENTITY_MODEL_MAP.get(key)
    if not entry:
        raise HierarchyDeveloperError(f"Unsupported entity type: {entity_type}")
    model, _pk, _label = entry
    entity = session.get(model, entity_id)
    if not entity:
        raise HierarchyDeveloperError(f"{entity_type} {entity_id} not found")
    return entity


def _assert_developer_user(user: User) -> None:
    names = _role_names(user)
    if not names:
        raise HierarchyDeveloperError("Assigned user must have Developer role")
    if has_workflow_role(names, WorkflowRole.DEV) or has_workflow_role(
        names, WorkflowRole.ADMIN
    ):
        return
    if any(n.lower() in ("developer", "dev") for n in names):
        return
    raise HierarchyDeveloperError("Assigned user must have Developer (or Admin) role")


PHYSICAL_ISSUE_STATUSES = (
    IssuanceStatus.ISSUED.value,
    IssuanceStatus.RETURN_PENDING.value,
    IssuanceStatus.INSTALLED.value,
)


def entity_is_physically_issued(
    session: Session, entity_type: str, entity_id: int
) -> bool:
    """True once IM has handed the reserved unit to the developer."""
    et = (entity_type or "").strip().lower()
    issuance = session.exec(
        select(InventoryIssuance).where(
            InventoryIssuance.target_entity_type == et,
            InventoryIssuance.target_entity_id == int(entity_id),
            InventoryIssuance.status.in_(PHYSICAL_ISSUE_STATUSES),
        )
    ).first()
    if issuance:
        return True
    issued_req = session.exec(
        select(InventoryItemRequest).where(
            InventoryItemRequest.target_entity_type == et,
            InventoryItemRequest.target_entity_id == int(entity_id),
            InventoryItemRequest.status == ItemRequestStatus.ISSUED.value,
        )
    ).first()
    return issued_req is not None


def clear_developer_assignment_if_unissued(
    session: Session,
    entity_type: str,
    entity_id: int,
    *,
    commit: bool = False,
) -> bool:
    """Drop HM assignment and pending requests unless IM has already issued the unit."""
    try:
        entity = _load_entity(session, entity_type, entity_id)
    except HierarchyDeveloperError:
        return False
    if entity_is_physically_issued(session, entity_type, entity_id):
        return False
    had_assignment = getattr(entity, "assigned_developer_id", None) is not None
    if had_assignment:
        entity.assigned_developer_id = None
        session.add(entity)
    _cancel_pending_requests(session, entity_type, entity_id)
    if commit:
        session.commit()
        if had_assignment:
            session.refresh(entity)
    return had_assignment


def assigned_developer_payload(session: Session, entity: Any, entity_type: str) -> dict:
    developer_id = getattr(entity, "assigned_developer_id", None)
    name = None
    if developer_id:
        user = session.get(User, int(developer_id))
        if user:
            name = user.full_name or user.username
    return {
        "entity_type": entity_type.strip().lower(),
        "id": getattr(entity, "id", None),
        "name": getattr(entity, "name", None),
        "assigned_developer_id": developer_id,
        "assigned_developer_name": name,
    }


def assignment_status_map(
    session: Session, entity_type: str, entity_ids: list[int]
) -> dict[int, dict]:
    et = (entity_type or "").strip().lower()
    out: dict[int, dict] = {}
    for eid in entity_ids:
        try:
            entity = _load_entity(session, et, int(eid))
        except HierarchyDeveloperError:
            continue
        payload = assigned_developer_payload(session, entity, et)
        payload["issued"] = entity_is_physically_issued(session, et, int(eid))
        out[int(eid)] = payload
    return out


def _cancel_pending_requests(
    session: Session, entity_type: str, entity_id: int
) -> None:
    pending = session.exec(
        select(InventoryItemRequest).where(
            InventoryItemRequest.target_entity_type == entity_type.strip().lower(),
            InventoryItemRequest.target_entity_id == int(entity_id),
            InventoryItemRequest.status == ItemRequestStatus.PENDING.value,
        )
    ).all()
    for row in pending:
        row.status = ItemRequestStatus.CANCELLED.value
        row.updated_at = _now()
        session.add(row)


def assign_developer(
    session: Session,
    entity_type: str,
    entity_id: int,
    developer_user_id: Optional[int],
    *,
    actor: User,
) -> Any:
    entity = _load_entity(session, entity_type, entity_id)
    if entity_is_physically_issued(session, entity_type, entity_id):
        raise HierarchyDeveloperError(
            "Assignment cannot be changed after the item has been issued to the developer"
        )

    previous_id = getattr(entity, "assigned_developer_id", None)
    if developer_user_id is None:
        entity.assigned_developer_id = None
        session.add(entity)
        _cancel_pending_requests(session, entity_type, entity_id)
        session.commit()
        session.refresh(entity)
        return entity

    developer = session.get(User, developer_user_id)
    if not developer:
        raise HierarchyDeveloperError("Developer user not found")
    _assert_developer_user(developer)

    entity.assigned_developer_id = int(developer_user_id)
    session.add(entity)

    if previous_id and int(previous_id) != int(developer_user_id):
        _cancel_pending_requests(session, entity_type, entity_id)

    session.commit()
    session.refresh(entity)
    return entity


_ASSIGNMENT_MODELS: tuple[tuple[str, Any], ...] = (
    ("system", System),
    ("subsystem", Subsystem),
    ("module", Module),
    ("unit", Unit),
    ("component", Component),
)


def _project_id_for_entity(session: Session, entity_type: str, entity: Any) -> Optional[int]:
    et = entity_type.strip().lower()
    if et == "system":
        return getattr(entity, "project_id", None)
    if et == "subsystem":
        system = session.get(System, entity.system_id)
        return system.project_id if system else None
    if et == "module":
        sub = session.get(Subsystem, entity.subsystem_id)
        if not sub:
            return None
        system = session.get(System, sub.system_id)
        return system.project_id if system else None
    if et == "unit":
        mod = session.get(Module, entity.module_id)
        if not mod:
            return None
        sub = session.get(Subsystem, mod.subsystem_id)
        if not sub:
            return None
        system = session.get(System, sub.system_id)
        return system.project_id if system else None
    if et == "component":
        unit = session.get(Unit, entity.unit_id)
        if not unit:
            return None
        mod = session.get(Module, unit.module_id)
        if not mod:
            return None
        sub = session.get(Subsystem, mod.subsystem_id)
        if not sub:
            return None
        system = session.get(System, sub.system_id)
        return system.project_id if system else None
    return None


def list_assigned_work(session: Session, developer_id: int) -> list[dict]:
    """Hierarchy nodes assigned to this developer (HM assignment, not IM issue)."""
    from app.models.tables import Project
    from app.services.inventory_reservation_service import active_reservation_for_entity

    rows: list[dict] = []
    for et, model in _ASSIGNMENT_MODELS:
        entities = session.exec(
            select(model).where(model.assigned_developer_id == int(developer_id))
        ).all()
        for entity in entities:
            eid = int(entity.id)
            reservation = active_reservation_for_entity(session, et, eid)
            issued = entity_is_physically_issued(session, et, eid)
            pending = session.exec(
                select(InventoryItemRequest).where(
                    InventoryItemRequest.target_entity_type == et,
                    InventoryItemRequest.target_entity_id == eid,
                    InventoryItemRequest.status == ItemRequestStatus.PENDING.value,
                )
            ).first()
            project_id = _project_id_for_entity(session, et, entity)
            project_name = None
            if project_id:
                project = session.get(Project, int(project_id))
                project_name = project.name if project else None
            reserved = reservation is not None
            rows.append(
                {
                    "entity_type": et,
                    "entity_id": eid,
                    "name": getattr(entity, "name", None),
                    "part_number": getattr(entity, "part_number", None),
                    "serial_number": (
                        reservation.serial_number
                        if reservation
                        else getattr(entity, "serial_number", None)
                    ),
                    "project_id": project_id,
                    "project_name": project_name,
                    "assigned_developer_id": int(developer_id),
                    "reserved": reserved,
                    "reservation_id": reservation.id if reservation else None,
                    "request_status": (
                        "issued"
                        if issued
                        else ("pending" if pending else "none")
                    ),
                    "issued": issued,
                    "can_request": reserved and not issued and pending is None,
                    "pending_request_id": pending.id if pending else None,
                }
            )
    rows.sort(key=lambda r: ((r.get("project_name") or ""), (r.get("name") or "")))
    return rows
