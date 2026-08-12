"""
Spec 00 — workflow role codes and RBAC display-name mapping.

DB `Role.name` stays human-readable; Spec codes (`ADMIN`, `PD`, …) are the
stable identifiers used by later workflow specs and `can_transition`.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable, Optional


class WorkflowRole(str, Enum):
    ADMIN = "ADMIN"
    PD = "PD"
    HM = "HM"
    IM = "IM"
    DEV = "DEV"


# Spec code → Role.name stored in DB (additive; legacy roles unchanged)
WORKFLOW_ROLE_DB_NAMES: dict[WorkflowRole, str] = {
    WorkflowRole.ADMIN: "Admin",
    WorkflowRole.PD: "ProjectDirector",
    WorkflowRole.HM: "HierarchyManager",
    WorkflowRole.IM: "InventoryManager",
    WorkflowRole.DEV: "Developer",
}

WORKFLOW_ROLE_LABELS: dict[WorkflowRole, str] = {
    WorkflowRole.ADMIN: "Administrator",
    WorkflowRole.PD: "Project Director",
    WorkflowRole.HM: "Hierarchy Manager",
    WorkflowRole.IM: "Inventory Manager",
    WorkflowRole.DEV: "Developer",
}

# Reverse lookup: Role.name → Spec code
DB_NAME_TO_WORKFLOW_ROLE: dict[str, WorkflowRole] = {
    name: code for code, name in WORKFLOW_ROLE_DB_NAMES.items()
}

# Also accept Spec codes and common aliases as Role.name inputs
_ROLE_ALIASES: dict[str, WorkflowRole] = {
    **{code.value: code for code in WorkflowRole},
    **{code.value.lower(): code for code in WorkflowRole},
    **{name.lower(): code for name, code in DB_NAME_TO_WORKFLOW_ROLE.items()},
    "administrator": WorkflowRole.ADMIN,
    "project director": WorkflowRole.PD,
    "hierarchy manager": WorkflowRole.HM,
    "inventory manager": WorkflowRole.IM,
}


def normalize_workflow_role(role: str | WorkflowRole | None) -> Optional[WorkflowRole]:
    if role is None:
        return None
    if isinstance(role, WorkflowRole):
        return role
    key = role.strip()
    if key in DB_NAME_TO_WORKFLOW_ROLE:
        return DB_NAME_TO_WORKFLOW_ROLE[key]
    return _ROLE_ALIASES.get(key.lower())


def resolve_workflow_roles(role_names: Iterable[str]) -> set[WorkflowRole]:
    found: set[WorkflowRole] = set()
    for name in role_names:
        code = normalize_workflow_role(name)
        if code:
            found.add(code)
    return found


def has_workflow_role(role_names: Iterable[str], required: WorkflowRole | str) -> bool:
    want = normalize_workflow_role(required)
    if want is None:
        return False
    return want in resolve_workflow_roles(role_names)
