"""Spec 11 — inventory recall when a project is cancelled.

Cancel cascade: close shortages, auto-release never-issued RESERVED stock to
AVAILABLE, and open recall tasks for issued / in-progress / testing / verified
units. Developers confirm physical return (or Admin/PD/HM force-return if the
developer is unresponsive). IM inspects and dispositions reusable → AVAILABLE,
repairable → REPAIRABLE, or scrapped → SCRAPPED.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, col, select

from app.domain.status_transitions import assert_transition
from app.domain.workflow_roles import WorkflowRole, has_workflow_role
from app.domain.workflow_status import ItemStatus, ProjectWorkflowStatus
from app.models.base import (
    IssuanceEventType,
    IssuanceStatus,
    ItemRequestStatus,
    PROJECT_CANCELLED_RELEASE_REASON,
    RecallDisposition,
    RecallStage,
    RecallTaskStatus,
    ReworkCaseStatus,
)
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryIssuance,
    InventoryItemRequest,
    InventoryRecallTask,
    InventoryReworkCase,
    Project,
    User,
)
from app.services.hierarchy_developer_service import _load_entity
from app.services.inventory_issuance_service import record_issuance_event
from app.services.inventory_reservation_service import (
    get_item_status_id,
    item_status_name,
    list_project_reservations,
    release_reservation,
)
from app.services.inventory_shortage_service import (
    ACTIVE_SHORTAGE_STATUSES,
    cancel_shortage,
    list_shortages,
)
from app.services.project_workflow_service import (
    _actor_workflow_role,
    get_project_status_id,
    project_status_name,
)


class InventoryRecallError(ValueError):
    pass


RECALL_FROM_DEV = frozenset(
    {
        ItemStatus.ISSUED.value,
        ItemStatus.INSTALLATION_IN_PROGRESS.value,
        ItemStatus.UNDER_TESTING_REVIEW.value,
        ItemStatus.INSTALLED_VERIFIED.value,
    }
)

DISPOSITION_STATUSES = {
    RecallDisposition.REUSABLE.value: ItemStatus.REUSABLE.value,
    RecallDisposition.REPAIRABLE.value: ItemStatus.REPAIRABLE.value,
    RecallDisposition.SCRAPPED.value: ItemStatus.SCRAPPED.value,
}

OPEN_ISSUANCE_STATUSES = frozenset(
    {
        IssuanceStatus.ISSUED.value,
        IssuanceStatus.RETURN_PENDING.value,
        IssuanceStatus.INSTALLED.value,
        IssuanceStatus.RETURNED.value,
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role_names(user: User) -> list[str]:
    return [r.name for r in (user.roles or []) if r.name]


def _actor_role(user: User) -> str | None:
    names = _role_names(user)
    if has_workflow_role(names, WorkflowRole.ADMIN):
        return WorkflowRole.ADMIN.value
    if has_workflow_role(names, WorkflowRole.IM):
        return WorkflowRole.IM.value
    if has_workflow_role(names, WorkflowRole.DEV):
        return WorkflowRole.DEV.value
    if has_workflow_role(names, WorkflowRole.HM):
        return WorkflowRole.HM.value
    if has_workflow_role(names, WorkflowRole.PD):
        return WorkflowRole.PD.value
    return names[0] if names else None


def _can_force_return(user: User) -> bool:
    names = _role_names(user)
    return (
        has_workflow_role(names, WorkflowRole.ADMIN)
        or has_workflow_role(names, WorkflowRole.PD)
        or has_workflow_role(names, WorkflowRole.HM)
    )


def _lifecycle(session: Session, issuance: InventoryIssuance) -> str:
    if issuance.inventory_instance_id:
        instance = session.get(InventoryInstance, issuance.inventory_instance_id)
        if instance is not None:
            name = item_status_name(session, instance.status_id)
            if name:
                return name.strip().upper()
    inventory = session.get(Inventory, issuance.inventory_id)
    if inventory is not None:
        name = item_status_name(session, inventory.status_id)
        if name:
            return name.strip().upper()
    if issuance.item_lifecycle_status:
        return issuance.item_lifecycle_status.strip().upper()
    return ItemStatus.ISSUED.value


def _advance_unit_status(
    session: Session,
    task: InventoryRecallTask,
    to_status: str,
    *,
    actor: User,
) -> None:
    current = None
    instance = (
        session.get(InventoryInstance, task.inventory_instance_id)
        if task.inventory_instance_id
        else None
    )
    inventory = session.get(Inventory, task.inventory_id)
    if instance is not None:
        current = item_status_name(session, instance.status_id)
    if not current and inventory is not None:
        current = item_status_name(session, inventory.status_id)
    issuance = session.get(InventoryIssuance, task.issuance_id) if task.issuance_id else None
    if not current and issuance is not None and issuance.item_lifecycle_status:
        current = issuance.item_lifecycle_status
    current = (current or ItemStatus.ISSUED.value).strip().upper()
    if current == to_status:
        return
    try:
        assert_transition("item", current, to_status, actor_role=_actor_role(actor))
    except ValueError as exc:
        raise InventoryRecallError(str(exc)) from exc
    status_id = get_item_status_id(session, to_status)
    now = _now()
    if instance is not None:
        instance.status_id = status_id
        instance.updated_at = now
        session.add(instance)
    if inventory is not None:
        inventory.status_id = status_id
        inventory.updated_at = now
        session.add(inventory)
    if issuance is not None:
        issuance.item_lifecycle_status = to_status
        session.add(issuance)


def _record(
    session: Session,
    task: InventoryRecallTask,
    event_type: str,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> None:
    if not task.issuance_id:
        return
    issuance = session.get(InventoryIssuance, task.issuance_id)
    if issuance is None:
        return
    record_issuance_event(
        session,
        issuance,
        event_type=event_type,
        actor=actor,
        notes=notes,
    )


def _require_open_task(session: Session, recall_id: int) -> InventoryRecallTask:
    task = session.get(InventoryRecallTask, recall_id)
    if task is None:
        raise InventoryRecallError("Recall task not found")
    if task.status != RecallTaskStatus.OPEN.value:
        raise InventoryRecallError("Recall task is already closed")
    return task


def _open_task_for_issuance(
    session: Session, issuance_id: int
) -> Optional[InventoryRecallTask]:
    return session.exec(
        select(InventoryRecallTask).where(
            InventoryRecallTask.issuance_id == int(issuance_id),
            InventoryRecallTask.status == RecallTaskStatus.OPEN.value,
        )
    ).first()


def project_cancel_preview(session: Session, project_id: int) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if project is None:
        raise InventoryRecallError("Project not found")
    status = project_status_name(project) or ""
    reserved = list_project_reservations(session, project_id, active_only=True)
    shortages = list_shortages(
        session, project_id=project_id, statuses=list(ACTIVE_SHORTAGE_STATUSES)
    )
    pending_requests = list(
        session.exec(
            select(InventoryItemRequest).where(
                InventoryItemRequest.project_id == project_id,
                InventoryItemRequest.status == ItemRequestStatus.PENDING.value,
            )
        ).all()
    )
    open_rework = list(
        session.exec(
            select(InventoryReworkCase).where(
                InventoryReworkCase.project_id == project_id,
                InventoryReworkCase.status == ReworkCaseStatus.OPEN.value,
            )
        ).all()
    )
    counts = {
        ItemStatus.ISSUED.value: 0,
        ItemStatus.INSTALLATION_IN_PROGRESS.value: 0,
        ItemStatus.UNDER_TESTING_REVIEW.value: 0,
        ItemStatus.INSTALLED_VERIFIED.value: 0,
        ItemStatus.RETURNED.value: 0,
        ItemStatus.INSPECTION.value: 0,
    }
    for issuance in _project_issuances(session, project_id):
        life = _lifecycle(session, issuance)
        if life in counts:
            counts[life] += 1
    issued = counts[ItemStatus.ISSUED.value]
    in_progress = counts[ItemStatus.INSTALLATION_IN_PROGRESS.value]
    testing = counts[ItemStatus.UNDER_TESTING_REVIEW.value]
    verified = counts[ItemStatus.INSTALLED_VERIFIED.value]
    returned_pending = (
        counts[ItemStatus.RETURNED.value] + counts[ItemStatus.INSPECTION.value]
    )
    recall_units = issued + in_progress + testing + verified + returned_pending
    progress = int(project.progress or 0)
    return {
        "project_id": int(project.id),
        "project_name": project.name,
        "project_status": status,
        "progress_pct": progress,
        "critical_path_unfinished": progress < 100
        and status != ProjectWorkflowStatus.COMPLETED.value,
        "reserved_count": len(reserved),
        "issued_count": issued,
        "in_progress_count": in_progress,
        "testing_count": testing,
        "verified_count": verified,
        "returned_pending_count": returned_pending,
        "shortage_count": len(shortages),
        "pending_request_count": len(pending_requests),
        "open_rework_count": len(open_rework),
        "recall_units_total": recall_units,
    }


def _project_issuances(session: Session, project_id: int) -> list[InventoryIssuance]:
    return list(
        session.exec(
            select(InventoryIssuance).where(
                InventoryIssuance.project_id == project_id,
                col(InventoryIssuance.status).in_(list(OPEN_ISSUANCE_STATUSES)),
            )
        ).all()
    )


def _stage_for_lifecycle(life: str) -> Optional[str]:
    if life in RECALL_FROM_DEV:
        return RecallStage.REQUESTED.value
    if life == ItemStatus.RETURNED.value:
        return RecallStage.RETURNED.value
    if life == ItemStatus.INSPECTION.value:
        return RecallStage.INSPECTION.value
    return None


def _create_recall_task(
    session: Session,
    issuance: InventoryIssuance,
    *,
    actor: User,
    stage: str,
) -> InventoryRecallTask:
    existing = _open_task_for_issuance(session, int(issuance.id))
    if existing is not None:
        return existing
    now = _now()
    task = InventoryRecallTask(
        project_id=int(issuance.project_id or 0),
        flight_id=issuance.flight_id,
        sdls_id=issuance.sdls_id,
        target_entity_type=(issuance.target_entity_type or "").strip().lower() or None,
        target_entity_id=issuance.target_entity_id,
        inventory_id=int(issuance.inventory_id),
        inventory_instance_id=issuance.inventory_instance_id,
        issuance_id=issuance.id,
        assigned_developer_id=issuance.issued_to_user_id,
        status=RecallTaskStatus.OPEN.value,
        stage=stage,
        opened_at=now,
        opened_by_id=int(actor.id) if actor.id else None,
        created_at=now,
        updated_at=now,
        notes="Opened by project cancel",
    )
    if not task.project_id:
        raise InventoryRecallError("Issuance is not bound to a project")
    session.add(task)
    session.flush()
    record_issuance_event(
        session,
        issuance,
        event_type=IssuanceEventType.RECALL_OPENED.value,
        actor=actor,
        notes="Project cancelled — recall opened",
    )
    return task


def _close_open_rework(
    session: Session, project_id: int, *, actor: User
) -> int:
    rows = list(
        session.exec(
            select(InventoryReworkCase).where(
                InventoryReworkCase.project_id == project_id,
                InventoryReworkCase.status == ReworkCaseStatus.OPEN.value,
            )
        ).all()
    )
    now = _now()
    for case in rows:
        case.status = ReworkCaseStatus.CLOSED.value
        case.closed_at = now
        case.closed_by_id = int(actor.id) if actor.id else None
        case.updated_at = now
        case.notes = (case.notes or "").strip()
        suffix = "Closed because project was cancelled (Spec 11 recall)."
        case.notes = f"{case.notes}\n{suffix}".strip() if case.notes else suffix
        session.add(case)
        if case.current_issuance_id:
            issuance = session.get(InventoryIssuance, case.current_issuance_id)
            if issuance is not None:
                record_issuance_event(
                    session,
                    issuance,
                    event_type=IssuanceEventType.REWORK_CLOSED.value,
                    actor=actor,
                    notes="Rework closed on project cancel",
                )
    return len(rows)


def cancel_project(
    session: Session,
    project_id: int,
    *,
    actor: User,
    confirm: bool,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    """Cancel the project, release reserved stock, and open recall tasks.

    ``notes`` is accepted for API compatibility and is not appended to
    ``project.description``.
    """
    if not confirm:
        raise InventoryRecallError("Cancellation requires explicit confirmation")

    project = session.get(Project, project_id)
    if project is None:
        raise InventoryRecallError("Project not found")

    current = project_status_name(project) or ProjectWorkflowStatus.DRAFT.value
    role = _actor_workflow_role(actor)
    try:
        assert_transition(
            "project",
            current,
            ProjectWorkflowStatus.CANCELLED.value,
            actor_role=role,
        )
    except ValueError as exc:
        raise InventoryRecallError(str(exc)) from exc

    preview = project_cancel_preview(session, project_id)

    project.status_id = get_project_status_id(
        session, ProjectWorkflowStatus.CANCELLED.value
    )
    project.updated_at = _now()
    session.add(project)
    session.flush()

    shortages = list_shortages(
        session, project_id=project_id, statuses=list(ACTIVE_SHORTAGE_STATUSES)
    )
    shortages_cancelled = 0
    for row in shortages:
        cancel_shortage(session, int(row.id), actor=actor, commit=False)
        shortages_cancelled += 1

    pending_requests = list(
        session.exec(
            select(InventoryItemRequest).where(
                InventoryItemRequest.project_id == project_id,
                InventoryItemRequest.status == ItemRequestStatus.PENDING.value,
            )
        ).all()
    )
    now = _now()
    for row in pending_requests:
        row.status = ItemRequestStatus.CANCELLED.value
        row.updated_at = now
        session.add(row)

    reserved = list_project_reservations(session, project_id, active_only=True)
    reserved_released = 0
    for reservation in reserved:
        release_reservation(
            session,
            project_id,
            int(reservation.id),
            actor=actor,
            reason=PROJECT_CANCELLED_RELEASE_REASON,
            commit=False,
        )
        reserved_released += 1

    rework_closed = _close_open_rework(session, project_id, actor=actor)

    recall_created = 0
    for issuance in _project_issuances(session, project_id):
        life = _lifecycle(session, issuance)
        stage = _stage_for_lifecycle(life)
        if stage is None:
            continue
        before = _open_task_for_issuance(session, int(issuance.id))
        _create_recall_task(session, issuance, actor=actor, stage=stage)
        if before is None:
            recall_created += 1

    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, project_id)
    session.commit()
    session.expire(project, ["status"])
    session.refresh(project)

    return {
        "project_id": int(project.id),
        "project_status": ProjectWorkflowStatus.CANCELLED.value,
        "critical_path_unfinished": preview["critical_path_unfinished"],
        "reserved_released": reserved_released,
        "shortages_cancelled": shortages_cancelled,
        "pending_requests_cancelled": len(pending_requests),
        "rework_closed": rework_closed,
        "recall_tasks_created": recall_created,
        "preview": preview,
    }


def list_recall_tasks(
    session: Session,
    *,
    project_id: Optional[int] = None,
    stage: Optional[str] = None,
    status_filter: Optional[str] = None,
    assigned_developer_id: Optional[int] = None,
) -> list[InventoryRecallTask]:
    stmt = select(InventoryRecallTask)
    if status_filter:
        stmt = stmt.where(InventoryRecallTask.status == status_filter.strip().lower())
    else:
        stmt = stmt.where(InventoryRecallTask.status == RecallTaskStatus.OPEN.value)
    if project_id is not None:
        stmt = stmt.where(InventoryRecallTask.project_id == int(project_id))
    if stage:
        stmt = stmt.where(InventoryRecallTask.stage == stage.strip().lower())
    if assigned_developer_id is not None:
        stmt = stmt.where(
            InventoryRecallTask.assigned_developer_id == int(assigned_developer_id)
        )
    stmt = stmt.order_by(col(InventoryRecallTask.updated_at).desc())
    return list(session.exec(stmt).all())


def _confirm_return(
    session: Session,
    task: InventoryRecallTask,
    *,
    actor: User,
    notes: Optional[str] = None,
    forced: bool = False,
) -> InventoryRecallTask:
    if task.stage != RecallStage.REQUESTED.value:
        raise InventoryRecallError(
            f"Return is only for requested recall (current: {task.stage})"
        )
    _advance_unit_status(session, task, ItemStatus.RETURNED.value, actor=actor)
    now = _now()
    if task.issuance_id:
        issuance = session.get(InventoryIssuance, task.issuance_id)
        if issuance is not None:
            issuance.status = IssuanceStatus.RETURNED.value
            issuance.closed_at = now
            issuance.closed_by_id = int(actor.id) if actor.id else None
            issuance.item_lifecycle_status = ItemStatus.RETURNED.value
            session.add(issuance)
    task.stage = RecallStage.RETURNED.value
    task.returned_at = now
    task.returned_by_id = int(actor.id) if actor.id else None
    task.forced_return = forced
    if forced:
        task.forced_by_id = int(actor.id) if actor.id else None
    task.updated_at = now
    if notes:
        task.notes = notes
    session.add(task)
    event = (
        IssuanceEventType.RECALL_FORCED_RETURN.value
        if forced
        else IssuanceEventType.ITEM_RETURNED.value
    )
    _record(session, task, event, actor=actor, notes=notes)
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, task.project_id)
    session.commit()
    session.refresh(task)
    return task


def confirm_developer_return(
    session: Session,
    recall_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryRecallTask:
    task = _require_open_task(session, recall_id)
    names = _role_names(actor)
    is_admin = has_workflow_role(names, WorkflowRole.ADMIN)
    if (
        task.assigned_developer_id is not None
        and int(task.assigned_developer_id) != int(actor.id)
        and not is_admin
    ):
        raise InventoryRecallError(
            "Only the assigned developer can confirm this return"
        )
    return _confirm_return(session, task, actor=actor, notes=notes, forced=False)


def force_admin_return(
    session: Session,
    recall_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryRecallTask:
    """Recovery when the developer is unresponsive.

    Admin / PD / HM attest that custody of the unit has been recovered.
    Inspection and disposition still follow; this does not skip IM review.
    """
    if not _can_force_return(actor):
        raise InventoryRecallError(
            "Only Admin, Project Director, or Hierarchy Manager can force-return"
        )
    task = _require_open_task(session, recall_id)
    return _confirm_return(
        session,
        task,
        actor=actor,
        notes=notes or "Force-returned after unresponsive developer",
        forced=True,
    )


def start_recall_inspection(
    session: Session,
    recall_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryRecallTask:
    task = _require_open_task(session, recall_id)
    if task.stage != RecallStage.RETURNED.value:
        raise InventoryRecallError(
            f"Inspection starts from returned (current: {task.stage})"
        )
    _advance_unit_status(session, task, ItemStatus.INSPECTION.value, actor=actor)
    now = _now()
    task.stage = RecallStage.INSPECTION.value
    task.inspected_at = now
    task.inspected_by_id = int(actor.id) if actor.id else None
    task.updated_at = now
    if notes:
        task.notes = notes
    session.add(task)
    _record(
        session,
        task,
        IssuanceEventType.INSPECTION_STARTED.value,
        actor=actor,
        notes=notes,
    )
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, task.project_id)
    session.commit()
    session.refresh(task)
    return task


def disposition_recall(
    session: Session,
    recall_id: int,
    *,
    actor: User,
    outcome: str,
    notes: Optional[str] = None,
) -> InventoryRecallTask:
    task = _require_open_task(session, recall_id)
    if task.stage != RecallStage.INSPECTION.value:
        raise InventoryRecallError(
            f"Disposition requires inspection stage (current: {task.stage})"
        )
    key = (outcome or "").strip().lower()
    to_status = DISPOSITION_STATUSES.get(key)
    if to_status is None:
        raise InventoryRecallError(
            "Disposition must be reusable, repairable, or scrapped"
        )
    _advance_unit_status(session, task, to_status, actor=actor)
    if key == RecallDisposition.REUSABLE.value:
        _advance_unit_status(
            session, task, ItemStatus.AVAILABLE.value, actor=actor
        )
    now = _now()
    task.disposition = key
    task.stage = key
    task.status = RecallTaskStatus.CLOSED.value
    task.closed_at = now
    task.closed_by_id = int(actor.id) if actor.id else None
    task.updated_at = now
    if notes:
        task.notes = notes
    session.add(task)
    _record(
        session,
        task,
        IssuanceEventType.DISPOSITIONED.value,
        actor=actor,
        notes=notes or key,
    )
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, task.project_id)
    session.commit()
    session.refresh(task)
    return task


def recall_task_to_dict(session: Session, task: InventoryRecallTask) -> dict[str, Any]:
    project = session.get(Project, task.project_id)
    developer = (
        session.get(User, task.assigned_developer_id)
        if task.assigned_developer_id
        else None
    )
    inventory = session.get(Inventory, task.inventory_id)
    instance = (
        session.get(InventoryInstance, task.inventory_instance_id)
        if task.inventory_instance_id
        else None
    )
    issuance = session.get(InventoryIssuance, task.issuance_id) if task.issuance_id else None
    entity_name = None
    if task.target_entity_type and task.target_entity_id:
        try:
            entity = _load_entity(
                session, task.target_entity_type, int(task.target_entity_id)
            )
            entity_name = getattr(entity, "name", None)
        except Exception:
            entity_name = None
    item_status = None
    if instance is not None:
        item_status = item_status_name(session, instance.status_id)
    elif inventory is not None:
        item_status = item_status_name(session, inventory.status_id)
    elif issuance is not None:
        item_status = issuance.item_lifecycle_status
    return {
        "id": task.id,
        "project_id": task.project_id,
        "project_name": project.name if project else None,
        "flight_id": task.flight_id,
        "sdls_id": task.sdls_id,
        "target_entity_type": task.target_entity_type,
        "target_entity_id": task.target_entity_id,
        "target_entity_name": entity_name,
        "inventory_id": task.inventory_id,
        "inventory_name": inventory.name if inventory else None,
        "part_number": (
            (issuance.part_number if issuance else None)
            or (inventory.part_number if inventory else None)
        ),
        "serial_number": (
            (instance.serial_number if instance else None)
            or (issuance.serial_number if issuance else None)
        ),
        "inventory_instance_id": task.inventory_instance_id,
        "issuance_id": task.issuance_id,
        "assigned_developer_id": task.assigned_developer_id,
        "assigned_developer_name": (
            (developer.full_name or developer.username) if developer else None
        ),
        "status": task.status,
        "stage": task.stage,
        "disposition": task.disposition,
        "forced_return": bool(task.forced_return),
        "item_status": item_status,
        "opened_at": task.opened_at,
        "returned_at": task.returned_at,
        "inspected_at": task.inspected_at,
        "closed_at": task.closed_at,
        "notes": task.notes,
        "updated_at": task.updated_at,
        "can_return": (
            task.status == RecallTaskStatus.OPEN.value
            and task.stage == RecallStage.REQUESTED.value
        ),
        "can_inspect": (
            task.status == RecallTaskStatus.OPEN.value
            and task.stage == RecallStage.RETURNED.value
        ),
        "can_disposition": (
            task.status == RecallTaskStatus.OPEN.value
            and task.stage == RecallStage.INSPECTION.value
        ),
    }
