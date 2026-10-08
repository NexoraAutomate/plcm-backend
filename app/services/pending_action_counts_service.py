"""Role-scoped pending-action counts for sidebar nav badges."""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import Session, select

from app.auth import check_permission
from app.domain.workflow_status import ProjectWorkflowStatus
from app.models.base import ConfigChangeRequestStatus, IssuanceStatus, ShortageStatus
from app.models.tables import (
    AppNotification,
    ConfigChangeRequest,
    InventoryIssuance,
    Project,
    Status,
    User,
)
from app.services.hierarchy_developer_service import list_assigned_work
from app.services.inventory_shortage_service import list_shortages
from app.services.item_install_verify_service import list_verification_queue
from app.services.item_request_service import list_item_requests
from app.services.item_rework_service import list_rework_cases


def _count(session: Session, stmt) -> int:
    value = session.exec(stmt).one()
    return int(value or 0)


def _assignment_needs_action(row: dict) -> bool:
    return bool(
        row.get("can_request")
        or row.get("can_install")
        or row.get("can_test")
        or row.get("can_report_complete")
        or row.get("can_remove")
        or row.get("can_return")
    )


def build_pending_action_counts(session: Session, current_user: User) -> dict[str, int]:
    """Return pending counts gated by the actor's permissions (0 when not applicable)."""
    counts: dict[str, int] = {
        "verify_queue": 0,
        "my_assignments": 0,
        "issue_queue": 0,
        "inspect_queue": 0,
        "issuances": 0,
        "projects": 0,
        "config_changes": 0,
        "shortages": 0,
        "notifications": 0,
    }

    if check_permission(current_user, "item.verify"):
        counts["verify_queue"] = len(list_verification_queue(session, current_user))

    if (
        check_permission(current_user, "view_my_assignments")
        or check_permission(current_user, "item.request")
        or check_permission(current_user, "item.install_test")
    ):
        work = list_assigned_work(session, int(current_user.id))
        counts["my_assignments"] = sum(1 for row in work if _assignment_needs_action(row))

    # Issue queue is an IM action; developers with item.request must not badge it.
    if check_permission(current_user, "inventory.issue") or check_permission(
        current_user, "issue_inventory"
    ):
        counts["issue_queue"] = len(
            list_item_requests(session, actor=current_user, status="pending")
        )

    if check_permission(current_user, "item.inspect"):
        counts["inspect_queue"] = len(list_rework_cases(session))

    if check_permission(current_user, "view_inventory_issuances"):
        counts["issuances"] = _count(
            session,
            select(func.count())
            .select_from(InventoryIssuance)
            .where(InventoryIssuance.status == IssuanceStatus.RETURN_PENDING.value),
        )

    if check_permission(current_user, "project.approve"):
        draft_status = session.exec(
            select(Status).where(
                Status.status_name == ProjectWorkflowStatus.DRAFT.value,
                Status.status_type == "projects",
            )
        ).first()
        if draft_status is not None and draft_status.id is not None:
            counts["projects"] = _count(
                session,
                select(func.count())
                .select_from(Project)
                .where(Project.status_id == int(draft_status.id)),
            )

    if check_permission(current_user, "config_change.approve"):
        counts["config_changes"] = _count(
            session,
            select(func.count())
            .select_from(ConfigChangeRequest)
            .where(
                ConfigChangeRequest.status
                == ConfigChangeRequestStatus.SUBMITTED.value
            ),
        )

    if check_permission(current_user, "inventory.receive"):
        shortages = list_shortages(
            session,
            statuses=[ShortageStatus.OPEN.value, ShortageStatus.PARTIAL.value],
        )
        counts["shortages"] = len(shortages)

    if check_permission(current_user, "view_notifications"):
        counts["notifications"] = _count(
            session,
            select(func.count())
            .select_from(AppNotification)
            .where(
                AppNotification.user_id == int(current_user.id),
                AppNotification.read_at.is_(None),
            ),
        )

    return counts
