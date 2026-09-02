"""Hard-delete a project with inventory release rules.

Allowed through reservation / HM assign-to-developer: reserved stock is released
back to AVAILABLE and ledger rows that block FK delete are removed.

Blocked once any unit has progressed past that stage (issued, installing,
testing, verified, return/inspection, rework, or recall).
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, col, select

from app.domain.workflow_audit import WorkflowAuditAction
from app.models.base import (
    InventoryReservationStatus,
    ItemRequestStatus,
)
from app.models.tables import (
    AssembledInventory,
    ConfigChangeRequest,
    InventoryItemRequest,
    InventoryIssuance,
    InventoryRecallTask,
    InventoryReservation,
    InventoryReservationExpiryNotice,
    InventoryReworkCase,
    InventoryShortage,
    InventoryShortageNotice,
    Project,
    User,
)
from app.services.inventory_recall_service import (
    InventoryRecallError,
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
from app.services.workflow_audit_service import write_workflow_audit

PROJECT_DELETED_RELEASE_REASON = "PROJECT_DELETED"

PROJECT_DELETE_BLOCKED_MESSAGE = (
    "Project cannot be deleted because inventory has progressed past the "
    "reservation / assign to developer stage."
)


class ProjectDeleteError(ValueError):
    pass


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
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
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
    }


def delete_project(
    session: Session,
    project_id: int,
    *,
    actor: User,
    commit: bool = True,
) -> dict[str, Any]:
    """Release reserved stock (if any), then hard-delete the project.

    Raises ProjectDeleteError when inventory has moved past reserve/assign-to-dev.
    """
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectDeleteError("Project not found")

    try:
        if _project_has_progressed_past_reserve_or_assign(session, project_id):
            raise ProjectDeleteError(PROJECT_DELETE_BLOCKED_MESSAGE)
    except InventoryRecallError as exc:
        raise ProjectDeleteError(str(exc)) from exc

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

    purge = _purge_inventory_ledger(session, project_id)
    _detach_project_links(session, project_id)

    write_workflow_audit(
        session,
        action=WorkflowAuditAction.DELETED,
        entity_type="project",
        entity_id=int(project_id),
        actor=actor,
        project_id=int(project_id),
        old_value={"name": project.name},
        new_value={
            "deleted": True,
            "reserved_released": reserved_released,
            "shortages_cancelled": shortages_cancelled,
            "pending_requests_cancelled": pending_cancelled,
        },
        remarks=PROJECT_DELETED_RELEASE_REASON,
    )

    session.delete(project)
    if commit:
        session.commit()

    return {
        "ok": True,
        "project_id": project_id,
        "reserved_released": reserved_released,
        "shortages_cancelled": shortages_cancelled,
        "pending_requests_cancelled": pending_cancelled,
        **purge,
    }
