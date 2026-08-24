"""
Spec 00 — workflow permission stubs for Spec 01+.

Keys match the Spec 00 seed list exactly (dotted form). Enforcement of
business rules lands in later specs; these exist so RBAC can gate UI/API early.
"""

from __future__ import annotations

from app.domain.workflow_roles import WorkflowRole

# permission key → description
WORKFLOW_PERMISSION_DEFS: list[dict[str, str]] = [
    {"name": "hierarchy_config.manage", "description": "Manage hierarchy configurations (Spec 01)"},
    {"name": "project.assign_hm", "description": "Assign Hierarchy Manager to a project (Spec 02)"},
    {"name": "project.create_draft", "description": "Create draft projects (Spec 02)"},
    {"name": "project.approve", "description": "Approve draft projects (Spec 02)"},
    {"name": "hierarchy.generate", "description": "Generate project hierarchy from config (Spec 03)"},
    {"name": "inventory.reserve", "description": "Reserve inventory against hierarchy (Spec 04–05)"},
    {"name": "inventory.release", "description": "Release unused reservations (Spec 04–06)"},
    {"name": "inventory.receive", "description": "Receive stock / shortage fulfillment (Spec 05)"},
    {"name": "inventory.issue", "description": "Issue inventory to developer with signature (Spec 07)"},
    {"name": "hierarchy.assign_developer", "description": "Assign developer to hierarchy work (Spec 07)"},
    {"name": "item.request", "description": "Developer requests reserved item (Spec 07)"},
    {"name": "item.install_test", "description": "Install and test issued item (Spec 08)"},
    {"name": "item.verify", "description": "HM verify installation (Spec 08–10)"},
    {"name": "item.inspect", "description": "IM inspect returned items (Spec 10–12)"},
    {"name": "project.cancel", "description": "Cancel project / trigger recall (Spec 11)"},
    {"name": "config_change.request", "description": "Request configuration change (Spec 12)"},
    {"name": "config_change.approve", "description": "Approve configuration change (Spec 12)"},
    {"name": "audit.read", "description": "Read audit trail (Spec 13)"},
]

WORKFLOW_PERMISSION_NAMES: list[str] = [p["name"] for p in WORKFLOW_PERMISSION_DEFS]

# Primary role grants (stubs — Admin also receives all via DEFAULT_ROLES sync)
WORKFLOW_ROLE_PERMISSIONS: dict[WorkflowRole, list[str]] = {
    WorkflowRole.ADMIN: list(WORKFLOW_PERMISSION_NAMES),
    WorkflowRole.PD: [
        "project.create_draft",
        "project.approve",
        "project.assign_hm",
        "project.cancel",
        "audit.read",
    ],
    WorkflowRole.HM: [
        "project.create_draft",
        "hierarchy.generate",
        "inventory.reserve",
        "inventory.release",
        "hierarchy.assign_developer",
        "item.verify",
        "project.cancel",
        "config_change.request",
        "audit.read",
    ],
    WorkflowRole.IM: [
        "inventory.receive",
        "inventory.issue",
        "item.inspect",
        "audit.read",
    ],
    WorkflowRole.DEV: [
        "item.request",
        "item.install_test",
    ],
}
