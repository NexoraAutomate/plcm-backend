"""Spec 13 — workflow audit action catalog and actor role constants."""

from __future__ import annotations


SYSTEM_ACTOR_ROLE = "SYSTEM"
SYSTEM_USERNAME = "system"


class WorkflowAuditAction:
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    ISSUED = "ISSUED"
    INSTALLATION_IN_PROGRESS = "INSTALLATION_IN_PROGRESS"
    UNDER_TESTING = "UNDER_TESTING"
    INSTALLED_VERIFIED = "INSTALLED_VERIFIED"
    RETURNED = "RETURNED"
    RE_ISSUED = "RE_ISSUED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    PROJECT_CREATED = "PROJECT_CREATED"
    PROJECT_APPROVED = "PROJECT_APPROVED"
    HIERARCHY_GENERATED = "HIERARCHY_GENERATED"
    PROJECT_CANCELLED = "PROJECT_CANCELLED"
    CONFIG_CHANGE_REQUESTED = "CONFIG_CHANGE_REQUESTED"
    CONFIG_CHANGE_INVENTORY_RETURNED = "CONFIG_CHANGE_INVENTORY_RETURNED"
    CONFIG_CHANGE_SUBMITTED = "CONFIG_CHANGE_SUBMITTED"
    CONFIG_CHANGE_APPROVED = "CONFIG_CHANGE_APPROVED"
    CONFIG_CHANGE_NEW_PROJECT = "CONFIG_CHANGE_NEW_PROJECT"
    CONFIG_CHANGE_CANCELLED = "CONFIG_CHANGE_CANCELLED"
    SHORTAGE_CREATED = "SHORTAGE_CREATED"
    SHORTAGE_PARTIAL = "SHORTAGE_PARTIAL"
    SHORTAGE_FULFILLED = "SHORTAGE_FULFILLED"
    AUTO_RESERVE = "AUTO_RESERVE"
    AUTO_RELEASE_EXPIRY = "AUTO_RELEASE_EXPIRY"


WORKFLOW_AUDIT_ACTIONS: tuple[str, ...] = tuple(
    value
    for key, value in vars(WorkflowAuditAction).items()
    if not key.startswith("_") and isinstance(value, str)
)

WORKFLOW_AUDIT_ACTION_LABELS: dict[str, str] = {
    WorkflowAuditAction.RESERVED: "Reserved",
    WorkflowAuditAction.RELEASED: "Released",
    WorkflowAuditAction.ISSUED: "Issued",
    WorkflowAuditAction.INSTALLATION_IN_PROGRESS: "Installation in Progress",
    WorkflowAuditAction.UNDER_TESTING: "Under Testing",
    WorkflowAuditAction.INSTALLED_VERIFIED: "Installed Verified",
    WorkflowAuditAction.RETURNED: "Returned",
    WorkflowAuditAction.RE_ISSUED: "Re-Issued",
    WorkflowAuditAction.MODIFIED: "Modified",
    WorkflowAuditAction.DELETED: "Deleted",
    WorkflowAuditAction.PROJECT_CREATED: "Project Created",
    WorkflowAuditAction.PROJECT_APPROVED: "Project Approved",
    WorkflowAuditAction.HIERARCHY_GENERATED: "Hierarchy Generated",
    WorkflowAuditAction.PROJECT_CANCELLED: "Project Cancelled",
    WorkflowAuditAction.CONFIG_CHANGE_REQUESTED: "Config Change Requested",
    WorkflowAuditAction.CONFIG_CHANGE_INVENTORY_RETURNED: "Config Change Inventory Returned",
    WorkflowAuditAction.CONFIG_CHANGE_SUBMITTED: "Config Change Submitted",
    WorkflowAuditAction.CONFIG_CHANGE_APPROVED: "Config Change Approved",
    WorkflowAuditAction.CONFIG_CHANGE_NEW_PROJECT: "Config Change New Project",
    WorkflowAuditAction.CONFIG_CHANGE_CANCELLED: "Config Change Cancelled",
    WorkflowAuditAction.SHORTAGE_CREATED: "Shortage Created",
    WorkflowAuditAction.SHORTAGE_PARTIAL: "Shortage Partial",
    WorkflowAuditAction.SHORTAGE_FULFILLED: "Shortage Fulfilled",
    WorkflowAuditAction.AUTO_RESERVE: "Auto-Reserve",
    WorkflowAuditAction.AUTO_RELEASE_EXPIRY: "Auto-Release (Expiry)",
}

WORKFLOW_AUDIT_ROLE_LABELS: dict[str, str] = {
    "ADMIN": "Administrator",
    "PD": "Project Director",
    "HM": "Hierarchy Manager",
    "IM": "Inventory Manager",
    "DEV": "Developer",
    SYSTEM_ACTOR_ROLE: "System",
}
