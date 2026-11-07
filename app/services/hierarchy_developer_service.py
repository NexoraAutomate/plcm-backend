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
    InventoryInstance,
    InventoryIssuance,
    InventoryItemRequest,
    Module,
    Subsystem,
    System,
    Unit,
    User,
)
from app.domain.workflow_audit import WorkflowAuditAction
from app.services.workflow_audit_service import write_workflow_audit
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
        from app.services.item_install_verify_service import install_progress_payload

        payload.update(install_progress_payload(session, et, int(eid)))
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
    from app.services.project_workflow_service import (
        assert_project_not_cancelled,
        ProjectWorkflowError,
    )
    from app.models.tables import Project as ProjectModel

    project_id = _project_id_for_entity(session, entity_type, entity)
    if project_id is not None:
        try:
            assert_project_not_cancelled(
                session.get(ProjectModel, int(project_id)),
                action="developer assignment",
            )
        except ProjectWorkflowError as exc:
            raise HierarchyDeveloperError(str(exc)) from exc
    if entity_is_physically_issued(session, entity_type, entity_id):
        raise HierarchyDeveloperError(
            "Assignment cannot be changed after the item has been issued to the developer"
        )

    previous_id = getattr(entity, "assigned_developer_id", None)
    if developer_user_id is None:
        entity.assigned_developer_id = None
        session.add(entity)
        _cancel_pending_requests(session, entity_type, entity_id)
        write_workflow_audit(
            session,
            action=WorkflowAuditAction.UNASSIGNED,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            project_id=project_id,
            old_value={"assigned_developer_id": previous_id},
            new_value={"assigned_developer_id": None},
        )
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

    write_workflow_audit(
        session,
        action=WorkflowAuditAction.ASSIGNED,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        project_id=project_id,
        old_value={"assigned_developer_id": previous_id},
        new_value={
            "assigned_developer_id": int(developer_user_id),
            "assigned_developer_name": developer.full_name or developer.username,
        },
    )
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


def _assignment_context(
    session: Session, entity_type: str, entity: Any, project_id: Optional[int]
) -> dict[str, Any]:
    """Customer / flight / system / HM labels for My Assignments table columns."""
    from app.models.tables import Customer, Order, Project
    from app.services.inventory_reservation_service import (
        InventoryReservationError,
        _resolve_flight_sdls_for_entity,
    )

    customer_name = None
    flight_name = None
    system_name = None
    assigned_hm_id = None
    assigned_hm_name = None

    if project_id is not None:
        project = session.get(Project, int(project_id))
        if project is not None:
            assigned_hm_id = project.assigned_hm_id
            if assigned_hm_id:
                hm = session.get(User, int(assigned_hm_id))
                if hm is not None:
                    assigned_hm_name = hm.full_name or hm.username
            if project.order_id:
                order = session.get(Order, int(project.order_id))
                if order is not None and order.customer_id:
                    customer = session.get(Customer, int(order.customer_id))
                    if customer is not None:
                        customer_name = customer.name

    try:
        flight, _sdls, system = _resolve_flight_sdls_for_entity(
            session, entity_type, entity
        )
        flight_name = getattr(flight, "name", None)
        system_name = getattr(system, "name", None)
    except InventoryReservationError:
        if (entity_type or "").strip().lower() == "system":
            system_name = getattr(entity, "name", None)

    return {
        "customer_name": customer_name,
        "flight_name": flight_name,
        "system_name": system_name,
        "assigned_hm_id": int(assigned_hm_id) if assigned_hm_id else None,
        "assigned_hm_name": assigned_hm_name,
    }


def list_assigned_work(
    session: Session,
    developer_id: Optional[int] = None,
    *,
    viewer_id: Optional[int] = None,
) -> list[dict]:
    """Hierarchy nodes with an HM developer assignment (not IM issue).

    When ``developer_id`` is set, only that developer's work is returned.
    When omitted, every assigned node is returned (Admin cleanup view).
    Action flags (``can_request`` / install / test) are only true when the
    ``viewer_id`` (or ``developer_id``) matches the assigned developer.
    """
    from app.models.tables import Project
    from app.services.inventory_reservation_service import active_reservation_for_entity
    from app.services.item_install_verify_service import install_progress_payload

    action_user_id = viewer_id if viewer_id is not None else developer_id
    rows: list[dict] = []
    for et, model in _ASSIGNMENT_MODELS:
        query = select(model).where(model.assigned_developer_id.is_not(None))
        if developer_id is not None:
            query = query.where(model.assigned_developer_id == int(developer_id))
        entities = session.exec(query).all()
        for entity in entities:
            eid = int(entity.id)
            assigned_id = int(entity.assigned_developer_id)
            is_assignee = (
                action_user_id is not None and int(assigned_id) == int(action_user_id)
            )
            reservation = active_reservation_for_entity(session, et, eid)
            issued = entity_is_physically_issued(session, et, eid)
            pending = session.exec(
                select(InventoryItemRequest).where(
                    InventoryItemRequest.target_entity_type == et,
                    InventoryItemRequest.target_entity_id == eid,
                    InventoryItemRequest.status == ItemRequestStatus.PENDING.value,
                )
            ).first()
            last_mark_back = session.exec(
                select(InventoryItemRequest)
                .where(
                    InventoryItemRequest.target_entity_type == et,
                    InventoryItemRequest.target_entity_id == eid,
                    InventoryItemRequest.status == ItemRequestStatus.MARKED_BACK.value,
                )
                .order_by(
                    InventoryItemRequest.marked_back_at.desc(),
                    InventoryItemRequest.id.desc(),
                )
            ).first()
            project_id = _project_id_for_entity(session, et, entity)
            project_name = None
            if project_id:
                project = session.get(Project, int(project_id))
                project_name = project.name if project else None
            context = _assignment_context(session, et, entity, project_id)
            reserved = reservation is not None
            progress = install_progress_payload(session, et, eid)
            if not is_assignee:
                progress = {
                    **progress,
                    "can_install": False,
                    "can_test": False,
                    "can_report_complete": False,
                    "can_remove": False,
                    "can_return": False,
                }
            serial_number = (
                reservation.serial_number
                if reservation
                else getattr(entity, "serial_number", None)
            )
            if not serial_number and progress.get("issuance_id"):
                issuance = session.get(InventoryIssuance, progress["issuance_id"])
                if issuance is not None:
                    serial_number = issuance.serial_number
            if not serial_number and progress.get("rework_id"):
                from app.models.tables import InventoryReworkCase

                case = session.get(InventoryReworkCase, progress["rework_id"])
                if case and case.current_instance_id:
                    inst = session.get(InventoryInstance, case.current_instance_id)
                    if inst is not None:
                        serial_number = inst.serial_number
            # Show mark-back reason only while the developer can re-request
            # (no open pending request and item not yet issued).
            show_mark_back = (
                last_mark_back is not None
                and not issued
                and pending is None
            )
            rows.append(
                {
                    "entity_type": et,
                    "entity_id": eid,
                    "name": getattr(entity, "name", None),
                    "part_number": getattr(entity, "part_number", None),
                    "serial_number": serial_number,
                    "project_id": project_id,
                    "project_name": project_name,
                    "assigned_developer_id": assigned_id,
                    "reserved": reserved,
                    "reservation_id": reservation.id if reservation else None,
                    "request_status": (
                        "issued"
                        if issued
                        else ("pending" if pending else "none")
                    ),
                    "issued": issued,
                    "can_request": bool(
                        is_assignee and reserved and not issued and pending is None
                    ),
                    "pending_request_id": pending.id if pending else None,
                    "last_mark_back_reason": (
                        last_mark_back.mark_back_reason if show_mark_back else None
                    ),
                    "last_mark_back_at": (
                        last_mark_back.marked_back_at if show_mark_back else None
                    ),
                    **context,
                    **progress,
                }
            )
    rows.sort(key=lambda r: ((r.get("project_name") or ""), (r.get("name") or "")))
    return rows


def delete_completed_assignment(
    session: Session,
    entity_type: str,
    entity_id: int,
    *,
    actor: User,
) -> dict:
    """Permanently remove a verified assignment from My Assignments (Admin only).

    Clears ``assigned_developer_id`` after HM verification. Does not undo install
    or issuance history. New / in-progress assignments cannot be deleted this way.
    """
    from app.domain.workflow_roles import WorkflowRole, has_workflow_role
    from app.services.item_install_verify_service import install_progress_payload

    role_names = _role_names(actor)
    if not has_workflow_role(role_names, WorkflowRole.ADMIN) and not any(
        (n or "").lower() == "admin" for n in role_names
    ):
        raise HierarchyDeveloperError(
            "Only Admin can permanently delete completed assignments"
        )

    entity = _load_entity(session, entity_type, entity_id)
    previous_id = getattr(entity, "assigned_developer_id", None)
    if previous_id is None:
        raise HierarchyDeveloperError("No developer assignment to delete")

    progress = install_progress_payload(session, entity_type, int(entity_id))
    if not progress.get("verified"):
        raise HierarchyDeveloperError(
            "Only completed (verified) assignments can be deleted; "
            "new or in-progress tasks cannot be deleted"
        )

    project_id = _project_id_for_entity(session, entity_type, entity)
    entity.assigned_developer_id = None
    session.add(entity)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.UNASSIGNED,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        project_id=project_id,
        old_value={
            "assigned_developer_id": previous_id,
            "reason": "admin_delete_completed_assignment",
        },
        new_value={"assigned_developer_id": None},
    )
    session.commit()
    session.refresh(entity)
    return assigned_developer_payload(session, entity, entity_type)
