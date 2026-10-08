"""Hard-delete a project with inventory release / revert / discard rules.

Disposition modes:
- auto: release reserved + delete when not past reserve/assign; or hard-delete
  when inventory is cleared after a delete request / cancel recall cycle.
- revert: release reserved, open recall tasks, mark delete_requested; do not
  hard-delete while stock is out. When cleared, hard-delete.
- discard: purge project inventory ledger and hard-delete without changing
  InventoryItem / instance statuses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from sqlmodel import Session, col, select

from app.domain.status_transitions import assert_transition
from app.domain.workflow_audit import WorkflowAuditAction
from app.domain.workflow_status import ProjectWorkflowStatus
from app.models.base import (
    InventoryReservationStatus,
    ItemRequestStatus,
    RecallTaskStatus,
)
from app.models.tables import (
    AssembledInventory,
    ConfigChangeRequest,
    InventoryInstallerNotice,
    InventoryIssuance,
    InventoryIssuanceEvent,
    InventoryItemRequest,
    InventoryRecallTask,
    InventoryReservation,
    InventoryReservationExpiryNotice,
    InventoryReturnNotice,
    InventoryReworkCase,
    InventoryShortage,
    InventoryShortageNotice,
    Project,
    User,
)
from app.services.inventory_recall_service import (
    InventoryRecallError,
    clear_project_inventory,
    inventory_is_cleared,
    list_recall_tasks,
    project_cancel_preview,
)
from app.services.inventory_reservation_service import (
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
from app.services.workflow_audit_service import write_workflow_audit

PROJECT_DELETED_RELEASE_REASON = "PROJECT_DELETED"
PROJECT_DELETE_REQUESTED_RELEASE_REASON = "PROJECT_DELETE_REQUESTED"

InventoryDisposition = Literal["auto", "revert", "discard"]

PROJECT_DELETE_BLOCKED_MESSAGE = (
    "Project cannot be deleted because inventory has progressed past the "
    "reservation / assign to developer stage. Choose revert (recall inventory) "
    "or discard (permanent data loss)."
)

PROJECT_DELETE_WAITING_RECALL_MESSAGE = (
    "Project delete is waiting for Inventory Manager to complete all recalls. "
    "Try again once inventory is cleared, or choose discard."
)


class ProjectDeleteError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _project_has_progressed_past_reserve_or_assign(
    session: Session, project_id: int
) -> bool:
    preview = project_cancel_preview(session, project_id)
    if int(preview.get("recall_units_total") or 0) > 0:
        return True
    if int(preview.get("open_rework_count") or 0) > 0:
        return True

    if session.exec(
        select(InventoryIssuance.id)
        .where(InventoryIssuance.project_id == project_id)
        .limit(1)
    ).first():
        return True

    if session.exec(
        select(InventoryReservation.id)
        .where(
            InventoryReservation.project_id == project_id,
            InventoryReservation.status == InventoryReservationStatus.CONSUMED.value,
        )
        .limit(1)
    ).first():
        return True

    if session.exec(
        select(InventoryRecallTask.id)
        .where(InventoryRecallTask.project_id == project_id)
        .limit(1)
    ).first():
        return True

    if session.exec(
        select(InventoryReworkCase.id)
        .where(InventoryReworkCase.project_id == project_id)
        .limit(1)
    ).first():
        return True

    if session.exec(
        select(InventoryItemRequest.id)
        .where(
            InventoryItemRequest.project_id == project_id,
            InventoryItemRequest.status == ItemRequestStatus.ISSUED.value,
        )
        .limit(1)
    ).first():
        return True

    return False


def _cancel_pending_requests(session: Session, project_id: int) -> int:
    rows = list(
        session.exec(
            select(InventoryItemRequest).where(
                InventoryItemRequest.project_id == project_id,
                InventoryItemRequest.status == ItemRequestStatus.PENDING.value,
            )
        ).all()
    )
    now = _now()
    for row in rows:
        row.status = ItemRequestStatus.CANCELLED.value
        row.updated_at = now
        session.add(row)
    return len(rows)


def _detach_project_links(session: Session, project_id: int) -> None:
    """Clear successor/predecessor and config-change FKs that point at this project."""
    for row in session.exec(
        select(Project).where(Project.successor_project_id == project_id)
    ).all():
        row.successor_project_id = None
        session.add(row)
    for row in session.exec(
        select(Project).where(Project.predecessor_project_id == project_id)
    ).all():
        row.predecessor_project_id = None
        session.add(row)

    for row in session.exec(
        select(ConfigChangeRequest).where(
            (ConfigChangeRequest.source_project_id == project_id)
            | (ConfigChangeRequest.successor_project_id == project_id)
        )
    ).all():
        if row.source_project_id == project_id:
            session.delete(row)
        else:
            row.successor_project_id = None
            session.add(row)


def _purge_issuance_graph(session: Session, project_id: int) -> dict[str, int]:
    """Remove issuances, events, notices, recalls, and rework for the project."""
    issuances = list(
        session.exec(
            select(InventoryIssuance).where(InventoryIssuance.project_id == project_id)
        ).all()
    )
    issuance_ids = [int(row.id) for row in issuances if row.id is not None]

    recalls = list(
        session.exec(
            select(InventoryRecallTask).where(
                InventoryRecallTask.project_id == project_id
            )
        ).all()
    )
    for row in recalls:
        session.delete(row)
    session.flush()

    rework = list(
        session.exec(
            select(InventoryReworkCase).where(
                InventoryReworkCase.project_id == project_id
            )
        ).all()
    )
    for row in rework:
        row.current_issuance_id = None
        session.add(row)
    session.flush()
    for row in rework:
        session.delete(row)
    session.flush()

    events_removed = 0
    notices_removed = 0
    return_notices_removed = 0
    if issuance_ids:
        events = list(
            session.exec(
                select(InventoryIssuanceEvent).where(
                    col(InventoryIssuanceEvent.issuance_id).in_(issuance_ids)
                )
            ).all()
        )
        for row in events:
            session.delete(row)
        events_removed = len(events)

        notices = list(
            session.exec(
                select(InventoryInstallerNotice).where(
                    col(InventoryInstallerNotice.issuance_id).in_(issuance_ids)
                )
            ).all()
        )
        for row in notices:
            session.delete(row)
        notices_removed = len(notices)

        return_notices = list(
            session.exec(
                select(InventoryReturnNotice).where(
                    col(InventoryReturnNotice.issuance_id).in_(issuance_ids)
                )
            ).all()
        )
        for row in return_notices:
            session.delete(row)
        return_notices_removed = len(return_notices)
        session.flush()

        for row in issuances:
            session.delete(row)
        session.flush()

    return {
        "issuances_removed": len(issuances),
        "issuance_events_removed": events_removed,
        "installer_notices_removed": notices_removed,
        "return_notices_removed": return_notices_removed,
        "recalls_removed": len(recalls),
        "rework_removed": len(rework),
    }


def inventory_cleared_for_delete(session: Session, project_id: int) -> bool:
    """True when no reserved stock, open recalls, or outstanding issued units remain."""
    if not inventory_is_cleared(session, project_id):
        return False
    preview = project_cancel_preview(session, project_id)
    if int(preview.get("recall_units_total") or 0) > 0:
        return False
    if int(preview.get("open_rework_count") or 0) > 0:
        return False
    return True


def _purge_inventory_ledger(session: Session, project_id: int) -> dict[str, int]:
    """Remove project-scoped inventory rows that would block hard delete."""
    requests = list(
        session.exec(
            select(InventoryItemRequest).where(
                InventoryItemRequest.project_id == project_id
            )
        ).all()
    )
    for row in requests:
        session.delete(row)
    session.flush()

    issuance_purge = _purge_issuance_graph(session, project_id)

    shortages = list(
        session.exec(
            select(InventoryShortage).where(InventoryShortage.project_id == project_id)
        ).all()
    )
    shortage_ids = [int(row.id) for row in shortages if row.id is not None]
    if shortage_ids:
        notices = list(
            session.exec(
                select(InventoryShortageNotice).where(
                    col(InventoryShortageNotice.shortage_id).in_(shortage_ids)
                )
            ).all()
        )
        for notice in notices:
            session.delete(notice)
        session.flush()
        for row in shortages:
            row.fulfilled_reservation_id = None
            session.add(row)
        session.flush()
        for row in shortages:
            session.delete(row)
        session.flush()

    reservations = list_project_reservations(session, project_id, active_only=False)
    reservation_ids = [int(row.id) for row in reservations if row.id is not None]
    if reservation_ids:
        expiry_notices = list(
            session.exec(
                select(InventoryReservationExpiryNotice).where(
                    col(InventoryReservationExpiryNotice.reservation_id).in_(
                        reservation_ids
                    )
                )
            ).all()
        )
        for notice in expiry_notices:
            session.delete(notice)
        session.flush()
        for row in reservations:
            session.delete(row)
        session.flush()

    assembled = list(
        session.exec(
            select(AssembledInventory).where(AssembledInventory.project_id == project_id)
        ).all()
    )
    for row in assembled:
        session.delete(row)
    session.flush()

    return {
        "requests_removed": len(requests),
        "shortages_removed": len(shortages),
        "reservations_removed": len(reservations),
        "assembled_removed": len(assembled),
        **issuance_purge,
    }


def project_delete_preview(session: Session, project_id: int) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectDeleteError("Project not found")

    try:
        preview = project_cancel_preview(session, project_id)
        progressed = _project_has_progressed_past_reserve_or_assign(session, project_id)
        cleared = inventory_cleared_for_delete(session, project_id)
    except InventoryRecallError as exc:
        raise ProjectDeleteError(str(exc)) from exc

    open_recalls = list_recall_tasks(
        session, project_id=project_id, status_filter=RecallTaskStatus.OPEN.value
    )
    reserved = list_project_reservations(session, project_id, active_only=True)

    return {
        "project_id": int(project_id),
        "project_name": project.name,
        "project_status": project_status_name(project),
        "progressed_past_reserve_or_assign": progressed,
        "inventory_is_cleared": cleared,
        "delete_requested_at": project.delete_requested_at,
        "delete_requested_by_id": project.delete_requested_by_id,
        "open_recall_count": len(open_recalls),
        "reserved_count": len(reserved),
        "can_hard_delete": (not progressed) or cleared,
        "preview": preview,
    }


def _hard_delete_project(
    session: Session,
    project: Project,
    *,
    actor: User,
    inventory_disposition: str,
    reserved_released: int = 0,
    shortages_cancelled: int = 0,
    pending_requests_cancelled: int = 0,
    extra_new_value: Optional[dict[str, Any]] = None,
    commit: bool = True,
) -> dict[str, Any]:
    project_id = int(project.id)
    delete_requested_at = project.delete_requested_at
    delete_requested_by_id = project.delete_requested_by_id
    project_name = project.name

    purge = _purge_inventory_ledger(session, project_id)
    _detach_project_links(session, project_id)

    new_value: dict[str, Any] = {
        "deleted": True,
        "inventory_disposition": inventory_disposition,
        "delete_requested_at": (
            delete_requested_at.isoformat() if delete_requested_at else None
        ),
        "delete_requested_by_id": delete_requested_by_id,
        "reserved_released": reserved_released,
        "shortages_cancelled": shortages_cancelled,
        "pending_requests_cancelled": pending_requests_cancelled,
        **purge,
    }
    if extra_new_value:
        new_value.update(extra_new_value)

    write_workflow_audit(
        session,
        action=WorkflowAuditAction.DELETED,
        entity_type="project",
        entity_id=project_id,
        actor=actor,
        project_id=project_id,
        old_value={"name": project_name},
        new_value=new_value,
        remarks=f"PROJECT_DELETED:{inventory_disposition}",
    )

    session.delete(project)
    if commit:
        session.commit()

    return {
        "ok": True,
        "status": "deleted",
        "project_id": project_id,
        "inventory_disposition": inventory_disposition,
        "reserved_released": reserved_released,
        "shortages_cancelled": shortages_cancelled,
        "pending_requests_cancelled": pending_requests_cancelled,
        **purge,
    }


def _release_active_and_cancel_pending(
    session: Session, project_id: int, *, actor: User
) -> dict[str, int]:
    pending_cancelled = _cancel_pending_requests(session, project_id)

    shortages = list_shortages(
        session, project_id=project_id, statuses=list(ACTIVE_SHORTAGE_STATUSES)
    )
    shortages_cancelled = 0
    for row in shortages:
        cancel_shortage(session, int(row.id), actor=actor, commit=False)
        shortages_cancelled += 1

    reserved = list_project_reservations(session, project_id, active_only=True)
    reserved_released = 0
    for reservation in reserved:
        release_reservation(
            session,
            project_id,
            int(reservation.id),
            actor=actor,
            reason=PROJECT_DELETED_RELEASE_REASON,
            commit=False,
        )
        reserved_released += 1

    return {
        "reserved_released": reserved_released,
        "shortages_cancelled": shortages_cancelled,
        "pending_requests_cancelled": pending_cancelled,
    }


def _request_delete_with_revert(
    session: Session,
    project: Project,
    *,
    actor: User,
    commit: bool = True,
) -> dict[str, Any]:
    project_id = int(project.id)
    current = project_status_name(project) or ProjectWorkflowStatus.DRAFT.value
    role = _actor_workflow_role(actor)

    if current != ProjectWorkflowStatus.CANCELLED.value:
        try:
            assert_transition(
                "project",
                current,
                ProjectWorkflowStatus.CANCELLED.value,
                actor_role=role,
            )
        except ValueError as exc:
            raise ProjectDeleteError(str(exc)) from exc
        project.status_id = get_project_status_id(
            session, ProjectWorkflowStatus.CANCELLED.value
        )

    now = _now()
    if project.delete_requested_at is None:
        project.delete_requested_at = now
        project.delete_requested_by_id = int(actor.id) if actor.id else None
    project.updated_at = now
    session.add(project)
    session.flush()

    cascade = clear_project_inventory(
        session,
        project_id,
        actor=actor,
        release_reason=PROJECT_DELETE_REQUESTED_RELEASE_REASON,
        recall_notes="Opened by project delete request (revert inventory)",
        recall_event_notes="Project delete requested — recall opened",
        rework_close_suffix="Closed because project delete was requested (revert).",
        rework_event_notes="Rework closed on project delete request",
        commit=False,
    )

    write_workflow_audit(
        session,
        action=WorkflowAuditAction.PROJECT_DELETE_REQUESTED,
        entity_type="project",
        entity_id=project_id,
        actor=actor,
        project_id=project_id,
        old_value={"status": current},
        new_value={
            "status": ProjectWorkflowStatus.CANCELLED.value,
            "inventory_disposition": "revert",
            "delete_requested_at": project.delete_requested_at.isoformat()
            if project.delete_requested_at
            else None,
            "delete_requested_by_id": project.delete_requested_by_id,
            "reserved_released": cascade["reserved_released"],
            "recall_tasks_created": cascade["recall_tasks_created"],
            "shortages_cancelled": cascade["shortages_cancelled"],
            "pending_requests_cancelled": cascade["pending_requests_cancelled"],
            "rework_closed": cascade["rework_closed"],
        },
        remarks=PROJECT_DELETE_REQUESTED_RELEASE_REASON,
    )

    if commit:
        session.commit()
        session.expire(project, ["status"])
        session.refresh(project)

    return {
        "ok": True,
        "status": "delete_requested",
        "project_id": project_id,
        "inventory_disposition": "revert",
        "project_status": ProjectWorkflowStatus.CANCELLED.value,
        "delete_requested_at": project.delete_requested_at,
        "delete_requested_by_id": project.delete_requested_by_id,
        **cascade,
    }


def maybe_notify_delete_ready(session: Session, project_id: int) -> None:
    """Best-effort notify when a delete-requested project becomes inventory-cleared."""
    project = session.get(Project, project_id)
    if project is None or project.delete_requested_at is None:
        return
    if not inventory_cleared_for_delete(session, project_id):
        return

    from app.services.app_notification_service import notify

    requester_ids = (
        [int(project.delete_requested_by_id)]
        if project.delete_requested_by_id
        else None
    )
    notify(
        session,
        event_type="project_delete_ready",
        title="Project ready to delete",
        message=(
            f"{project.name} inventory has been recalled and cleared. "
            "You can permanently delete the project."
        ),
        href="/projects",
        priority="high",
        include_im=True,
        include_admin=True,
        extra_user_ids=requester_ids,
        project=project,
        project_id=project_id,
        entity_type="project",
        entity_id=project_id,
        dedupe_key=f"project_delete_ready:{project_id}",
    )


def delete_project(
    session: Session,
    project_id: int,
    *,
    actor: User,
    inventory_disposition: InventoryDisposition = "auto",
    confirm: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    """Delete or request deletion of a project based on inventory disposition."""
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectDeleteError("Project not found")

    disposition = (inventory_disposition or "auto").strip().lower()
    if disposition not in {"auto", "revert", "discard"}:
        raise ProjectDeleteError(
            "inventory_disposition must be auto, revert, or discard"
        )

    try:
        progressed = _project_has_progressed_past_reserve_or_assign(session, project_id)
        cleared = inventory_cleared_for_delete(session, project_id)
    except InventoryRecallError as exc:
        raise ProjectDeleteError(str(exc)) from exc

    if disposition == "discard":
        if not confirm:
            raise ProjectDeleteError("Discard requires explicit confirmation")
        return _hard_delete_project(
            session,
            project,
            actor=actor,
            inventory_disposition="discarded",
            commit=commit,
        )

    if disposition == "revert":
        if progressed and not cleared:
            if not confirm:
                raise ProjectDeleteError("Revert requires explicit confirmation")
            return _request_delete_with_revert(
                session, project, actor=actor, commit=commit
            )
        if not progressed:
            counts = _release_active_and_cancel_pending(
                session, project_id, actor=actor
            )
            return _hard_delete_project(
                session,
                project,
                actor=actor,
                inventory_disposition=(
                    "reverted" if project.delete_requested_at else "released"
                ),
                commit=commit,
                **counts,
            )
        return _hard_delete_project(
            session,
            project,
            actor=actor,
            inventory_disposition="reverted",
            commit=commit,
        )

    # auto
    if not progressed:
        counts = _release_active_and_cancel_pending(session, project_id, actor=actor)
        return _hard_delete_project(
            session,
            project,
            actor=actor,
            inventory_disposition=(
                "reverted" if project.delete_requested_at else "released"
            ),
            commit=commit,
            **counts,
        )

    if cleared:
        return _hard_delete_project(
            session,
            project,
            actor=actor,
            inventory_disposition="reverted",
            commit=commit,
        )

    if project.delete_requested_at is not None:
        raise ProjectDeleteError(PROJECT_DELETE_WAITING_RECALL_MESSAGE)
    raise ProjectDeleteError(PROJECT_DELETE_BLOCKED_MESSAGE)
