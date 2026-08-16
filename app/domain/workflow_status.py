"""
Spec 00 — canonical inventory/item and project workflow status codes.

These are stable API / domain codes. Seeded into Status master data as
`status_name` with `status_type` of `inventory` or `projects`.
"""

from __future__ import annotations

from enum import Enum


class ItemStatus(str, Enum):
    """Inventory / item lifecycle (happy path + return branch)."""

    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    INSTALLATION_IN_PROGRESS = "INSTALLATION_IN_PROGRESS"
    UNDER_TESTING_REVIEW = "UNDER_TESTING_REVIEW"
    INSTALLED_VERIFIED = "INSTALLED_VERIFIED"
    RETURNED = "RETURNED"
    INSPECTION = "INSPECTION"
    REUSABLE = "REUSABLE"
    REPAIRABLE = "REPAIRABLE"
    SCRAPPED = "SCRAPPED"


class ProjectWorkflowStatus(str, Enum):
    """Project statuses through hierarchy generation (+ reserved later states)."""

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    HIERARCHY_GENERATED = "HIERARCHY_GENERATED"
    READY_FOR_INVENTORY = "READY_FOR_INVENTORY"
    # Reserved for later specs
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    READY_TO_DELIVER = "READY_TO_DELIVER"
    SUPERSEDED = "SUPERSEDED"


ITEM_STATUS_TYPE = "inventory"
PROJECT_STATUS_TYPE = "projects"

ITEM_STATUS_META: dict[ItemStatus, str] = {
    ItemStatus.AVAILABLE: "In stock, free for reservation",
    ItemStatus.RESERVED: "Locked to a Flight → SDLS / hierarchy node",
    ItemStatus.ISSUED: "Physically issued to a Developer",
    ItemStatus.INSTALLATION_IN_PROGRESS: "Active install work or post-issue dwell",
    ItemStatus.UNDER_TESTING_REVIEW: "Installed and under test / review",
    ItemStatus.INSTALLED_VERIFIED: "Pass + HM verification complete",
    ItemStatus.RETURNED: "Back to IM; not yet dispositioned",
    ItemStatus.INSPECTION: "IM is inspecting returned item",
    ItemStatus.REUSABLE: "Inspection outcome; may return to stock",
    ItemStatus.REPAIRABLE: "Needs repair before reuse",
    ItemStatus.SCRAPPED: "Not usable; permanently out of stock for that unit",
}

PROJECT_STATUS_META: dict[ProjectWorkflowStatus, str] = {
    ProjectWorkflowStatus.DRAFT: "HM created project; waiting Admin approval",
    ProjectWorkflowStatus.APPROVED: "Admin approved; Generate Hierarchy enabled",
    ProjectWorkflowStatus.HIERARCHY_GENERATED: "Tree materialised from configuration",
    ProjectWorkflowStatus.READY_FOR_INVENTORY: "May reserve / assign inventory",
    ProjectWorkflowStatus.CANCELLED: "Project cancelled (Spec 11)",
    ProjectWorkflowStatus.COMPLETED: "Project completed (Spec 09)",
    ProjectWorkflowStatus.READY_TO_DELIVER: "Ready to deliver (Spec 09)",
    ProjectWorkflowStatus.SUPERSEDED: "Replaced by a successor after configuration change (Spec 12)",
}

# Display labels — same vocabulary as codes (no parallel names like "In Stock")
ITEM_STATUS_LABELS: dict[ItemStatus, str] = {
    ItemStatus.AVAILABLE: "Available",
    ItemStatus.RESERVED: "Reserved",
    ItemStatus.ISSUED: "Issued",
    ItemStatus.INSTALLATION_IN_PROGRESS: "Installation In Progress",
    ItemStatus.UNDER_TESTING_REVIEW: "Under Testing / Review",
    ItemStatus.INSTALLED_VERIFIED: "Installed Verified",
    ItemStatus.RETURNED: "Returned",
    ItemStatus.INSPECTION: "Inspection",
    ItemStatus.REUSABLE: "Reusable",
    ItemStatus.REPAIRABLE: "Repairable",
    ItemStatus.SCRAPPED: "Scrapped",
}

PROJECT_STATUS_LABELS: dict[ProjectWorkflowStatus, str] = {
    ProjectWorkflowStatus.DRAFT: "Draft",
    ProjectWorkflowStatus.APPROVED: "Approved",
    ProjectWorkflowStatus.HIERARCHY_GENERATED: "Hierarchy Generated",
    ProjectWorkflowStatus.READY_FOR_INVENTORY: "Ready For Inventory",
    ProjectWorkflowStatus.CANCELLED: "Cancelled",
    ProjectWorkflowStatus.COMPLETED: "Completed",
    ProjectWorkflowStatus.READY_TO_DELIVER: "Ready To Deliver",
    ProjectWorkflowStatus.SUPERSEDED: "Superseded",
}

# Default badge colors (hex) for seed + UI fallbacks
ITEM_STATUS_COLORS: dict[ItemStatus, str] = {
    ItemStatus.AVAILABLE: "#548235",
    ItemStatus.RESERVED: "#2E75B6",
    ItemStatus.ISSUED: "#0070C0",
    ItemStatus.INSTALLATION_IN_PROGRESS: "#C55A11",
    ItemStatus.UNDER_TESTING_REVIEW: "#BF9000",
    ItemStatus.INSTALLED_VERIFIED: "#00B050",
    ItemStatus.RETURNED: "#7030A0",
    ItemStatus.INSPECTION: "#ED7D31",
    ItemStatus.REUSABLE: "#70AD47",
    ItemStatus.REPAIRABLE: "#C55A11",
    ItemStatus.SCRAPPED: "#595959",
}

PROJECT_STATUS_COLORS: dict[ProjectWorkflowStatus, str] = {
    ProjectWorkflowStatus.DRAFT: "#7F7F7F",
    ProjectWorkflowStatus.APPROVED: "#00B050",
    ProjectWorkflowStatus.HIERARCHY_GENERATED: "#2E75B6",
    ProjectWorkflowStatus.READY_FOR_INVENTORY: "#548235",
    ProjectWorkflowStatus.CANCELLED: "#C00000",
    ProjectWorkflowStatus.COMPLETED: "#375623",
    ProjectWorkflowStatus.READY_TO_DELIVER: "#2F5496",
    ProjectWorkflowStatus.SUPERSEDED: "#7030A0",
}
