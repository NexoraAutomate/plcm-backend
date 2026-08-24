"""
Idempotent seed of Spec 00 inventory-item and project workflow statuses.

Uses stable codes as status_name (AVAILABLE, DRAFT, …) so APIs and UI
never invent parallel labels like "In Stock" vs AVAILABLE.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.models.base import (
    ItemStatus,
    ProjectWorkflowStatus,
    STATUS_TYPE_INVENTORY_ITEM,
    STATUS_TYPE_PROJECT_WORKFLOW,
)
from app.models.tables import Status

ITEM_STATUS_META: dict[ItemStatus, dict[str, str]] = {
    ItemStatus.AVAILABLE: {
        "description": "In stock, free for reservation",
        "color": "#548235",
    },
    ItemStatus.RESERVED: {
        "description": "Locked to a Flight → SDLS / hierarchy node",
        "color": "#2E75B6",
    },
    ItemStatus.ISSUED: {
        "description": "Physically issued to a Developer",
        "color": "#0070C0",
    },
    ItemStatus.INSTALLATION_IN_PROGRESS: {
        "description": "Auto after issue dwell, or active install work",
        "color": "#ED7D31",
    },
    ItemStatus.UNDER_TESTING_REVIEW: {
        "description": "Installed and under test / review",
        "color": "#BF9000",
    },
    ItemStatus.INSTALLED_VERIFIED: {
        "description": "Pass + HM verification complete (terminal happy path)",
        "color": "#00B050",
    },
    ItemStatus.RETURNED: {
        "description": "Back to IM from Dev / project (not yet dispositioned)",
        "color": "#7030A0",
    },
    ItemStatus.INSPECTION: {
        "description": "IM is inspecting returned item",
        "color": "#C55A11",
    },
    ItemStatus.REUSABLE: {
        "description": "Inspection outcome; may return to stock",
        "color": "#009F4D",
    },
    ItemStatus.REPAIRABLE: {
        "description": "Needs repair before any reuse",
        "color": "#C00000",
    },
    ItemStatus.SCRAPPED: {
        "description": "Not usable; permanently out of stock for that unit",
        "color": "#404040",
    },
}

PROJECT_STATUS_META: dict[ProjectWorkflowStatus, dict[str, str]] = {
    ProjectWorkflowStatus.DRAFT: {
        "description": "HM created project/flight; waiting Admin approval",
        "color": "#A6A6A6",
    },
    ProjectWorkflowStatus.APPROVED: {
        "description": "Approved; Generate Hierarchy enabled",
        "color": "#00B050",
    },
    ProjectWorkflowStatus.HIERARCHY_GENERATED: {
        "description": "Tree materialised from selected configuration",
        "color": "#2E75B6",
    },
    ProjectWorkflowStatus.READY_FOR_INVENTORY: {
        "description": "May reserve / assign inventory",
        "color": "#0070C0",
    },
    ProjectWorkflowStatus.CANCELLED: {
        "description": "Project cancelled (Spec 11)",
        "color": "#C00000",
    },
    ProjectWorkflowStatus.COMPLETED: {
        "description": "Project completed (Spec 09)",
        "color": "#548235",
    },
    ProjectWorkflowStatus.READY_TO_DELIVER: {
        "description": "Ready to deliver (Spec 09)",
        "color": "#1F4E79",
    },
}


def _upsert_status(
    session: Session,
    *,
    name: str,
    status_type: str,
    description: str,
    color: str,
) -> None:
    existing = session.exec(
        select(Status).where(
            Status.status_name == name,
            Status.status_type == status_type,
        )
    ).first()
    if existing:
        # Keep codes stable; refresh description/color if still empty
        changed = False
        if not existing.description and description:
            existing.description = description
            changed = True
        if not existing.color and color:
            existing.color = color
            changed = True
        if changed:
            session.add(existing)
        return

    session.add(
        Status(
            status_name=name,
            status_type=status_type,
            description=description,
            color=color,
        )
    )


def seed_workflow_statuses(session: Session) -> None:
    """Insert missing Spec 00 item + project workflow status rows."""
    for status, meta in ITEM_STATUS_META.items():
        _upsert_status(
            session,
            name=status.value,
            status_type=STATUS_TYPE_INVENTORY_ITEM,
            description=meta["description"],
            color=meta["color"],
        )
    for status, meta in PROJECT_STATUS_META.items():
        _upsert_status(
            session,
            name=status.value,
            status_type=STATUS_TYPE_PROJECT_WORKFLOW,
            description=meta["description"],
            color=meta["color"],
        )
    session.commit()
