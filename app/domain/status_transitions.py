"""
Spec 00 — single domain helper for item + project status transitions.

Later specs must call `can_transition` / `assert_transition` instead of
ad-hoc status updates.
"""

from __future__ import annotations

from typing import Optional, Union

from app.domain.workflow_roles import WorkflowRole, normalize_workflow_role
from app.domain.workflow_status import ItemStatus, ProjectWorkflowStatus

StatusLike = Union[str, ItemStatus, ProjectWorkflowStatus]

# Allowed edges only (from → frozenset of to)
ITEM_TRANSITIONS: dict[str, frozenset[str]] = {
    # Happy path
    ItemStatus.AVAILABLE.value: frozenset({ItemStatus.RESERVED.value}),
    ItemStatus.RESERVED.value: frozenset(
        {ItemStatus.ISSUED.value, ItemStatus.AVAILABLE.value}
    ),
    ItemStatus.ISSUED.value: frozenset(
        {
            ItemStatus.INSTALLATION_IN_PROGRESS.value,
            ItemStatus.RETURNED.value,
        }
    ),
    ItemStatus.INSTALLATION_IN_PROGRESS.value: frozenset(
        {
            ItemStatus.UNDER_TESTING_REVIEW.value,
            ItemStatus.RETURNED.value,
        }
    ),
    ItemStatus.UNDER_TESTING_REVIEW.value: frozenset(
        {
            ItemStatus.INSTALLED_VERIFIED.value,
            ItemStatus.RETURNED.value,
        }
    ),
    # Return / inspection branch
    ItemStatus.RETURNED.value: frozenset({ItemStatus.INSPECTION.value}),
    ItemStatus.INSPECTION.value: frozenset(
        {
            ItemStatus.REUSABLE.value,
            ItemStatus.REPAIRABLE.value,
            ItemStatus.SCRAPPED.value,
        }
    ),
    ItemStatus.REUSABLE.value: frozenset({ItemStatus.AVAILABLE.value}),
    # Terminal / parked until later specs extend
    ItemStatus.REPAIRABLE.value: frozenset(),
    ItemStatus.SCRAPPED.value: frozenset(),
    ItemStatus.INSTALLED_VERIFIED.value: frozenset(),
}

PROJECT_TRANSITIONS: dict[str, frozenset[str]] = {
    ProjectWorkflowStatus.DRAFT.value: frozenset({ProjectWorkflowStatus.APPROVED.value}),
    ProjectWorkflowStatus.APPROVED.value: frozenset(
        {ProjectWorkflowStatus.HIERARCHY_GENERATED.value}
    ),
    ProjectWorkflowStatus.HIERARCHY_GENERATED.value: frozenset(
        {ProjectWorkflowStatus.READY_FOR_INVENTORY.value}
    ),
    ProjectWorkflowStatus.READY_FOR_INVENTORY.value: frozenset(
        {
            ProjectWorkflowStatus.CANCELLED.value,
            ProjectWorkflowStatus.COMPLETED.value,
            ProjectWorkflowStatus.READY_TO_DELIVER.value,
        }
    ),
    ProjectWorkflowStatus.CANCELLED.value: frozenset(),
    ProjectWorkflowStatus.COMPLETED.value: frozenset(
        {ProjectWorkflowStatus.READY_TO_DELIVER.value}
    ),
    ProjectWorkflowStatus.READY_TO_DELIVER.value: frozenset(),
}

# Optional role gates for transitions (None = any authenticated actor / System)
RoleGate = Optional[frozenset[WorkflowRole]]

ITEM_TRANSITION_ROLES: dict[tuple[str, str], RoleGate] = {
    (
        ItemStatus.ISSUED.value,
        ItemStatus.INSTALLATION_IN_PROGRESS.value,
    ): frozenset({WorkflowRole.DEV}),
    (
        ItemStatus.INSTALLATION_IN_PROGRESS.value,
        ItemStatus.UNDER_TESTING_REVIEW.value,
    ): frozenset({WorkflowRole.DEV}),
    (
        ItemStatus.UNDER_TESTING_REVIEW.value,
        ItemStatus.INSTALLED_VERIFIED.value,
    ): frozenset({WorkflowRole.HM}),
}

PROJECT_TRANSITION_ROLES: dict[tuple[str, str], RoleGate] = {
    (
        ProjectWorkflowStatus.DRAFT.value,
        ProjectWorkflowStatus.APPROVED.value,
    ): frozenset({WorkflowRole.ADMIN}),
    (
        ProjectWorkflowStatus.APPROVED.value,
        ProjectWorkflowStatus.HIERARCHY_GENERATED.value,
    ): frozenset({WorkflowRole.HM, WorkflowRole.ADMIN}),
    (
        ProjectWorkflowStatus.HIERARCHY_GENERATED.value,
        ProjectWorkflowStatus.READY_FOR_INVENTORY.value,
    ): frozenset({WorkflowRole.HM, WorkflowRole.ADMIN}),
    (
        ProjectWorkflowStatus.READY_FOR_INVENTORY.value,
        ProjectWorkflowStatus.CANCELLED.value,
    ): frozenset({WorkflowRole.PD, WorkflowRole.HM, WorkflowRole.ADMIN}),
    # Spec 09 — completion is system-calculated; System actor skips this gate.
    (
        ProjectWorkflowStatus.READY_FOR_INVENTORY.value,
        ProjectWorkflowStatus.COMPLETED.value,
    ): frozenset({WorkflowRole.PD, WorkflowRole.ADMIN}),
    (
        ProjectWorkflowStatus.READY_FOR_INVENTORY.value,
        ProjectWorkflowStatus.READY_TO_DELIVER.value,
    ): frozenset({WorkflowRole.PD, WorkflowRole.ADMIN}),
    (
        ProjectWorkflowStatus.COMPLETED.value,
        ProjectWorkflowStatus.READY_TO_DELIVER.value,
    ): frozenset({WorkflowRole.PD, WorkflowRole.ADMIN}),
}


def normalize_status_code(value: StatusLike) -> str:
    if isinstance(value, (ItemStatus, ProjectWorkflowStatus)):
        return value.value
    raw = str(value).strip()
    return raw.upper().replace(" ", "_").replace("/", "_").replace("__", "_")


def _matrix_for(entity_type: str) -> dict[str, frozenset[str]]:
    key = entity_type.strip().lower()
    if key in ("item", "inventory", "inventory_item"):
        return ITEM_TRANSITIONS
    if key in ("project", "projects"):
        return PROJECT_TRANSITIONS
    raise ValueError(f"Unknown entity_type for status transition: {entity_type!r}")


def _role_gates_for(entity_type: str) -> dict[tuple[str, str], RoleGate]:
    key = entity_type.strip().lower()
    if key in ("item", "inventory", "inventory_item"):
        return ITEM_TRANSITION_ROLES
    if key in ("project", "projects"):
        return PROJECT_TRANSITION_ROLES
    raise ValueError(f"Unknown entity_type for status transition: {entity_type!r}")


def can_transition(
    entity_type: str,
    from_status: StatusLike,
    to_status: StatusLike,
    actor_role: str | WorkflowRole | None = None,
) -> bool:
    """
    Return True if the edge is allowed by the Spec 00 matrix.

    When a role gate exists for the edge and a role is provided, the actor must
    match (ADMIN always allowed). Pass actor_role=None or "System" to skip
    role gating (jobs / system actions).
    """
    matrix = _matrix_for(entity_type)
    frm = normalize_status_code(from_status)
    to = normalize_status_code(to_status)
    if to not in matrix.get(frm, frozenset()):
        return False

    gates = _role_gates_for(entity_type)
    allowed_roles = gates.get((frm, to))
    if allowed_roles is None:
        return True

    if actor_role is None:
        return True
    if isinstance(actor_role, str) and actor_role.strip().lower() in ("system", ""):
        return True

    role = normalize_workflow_role(actor_role)
    if role is None:
        return False
    if role == WorkflowRole.ADMIN:
        return True
    return role in allowed_roles


def assert_transition(
    entity_type: str,
    from_status: StatusLike,
    to_status: StatusLike,
    actor_role: str | WorkflowRole | None = None,
) -> None:
    """Raise ValueError when the transition is illegal."""
    if can_transition(entity_type, from_status, to_status, actor_role):
        return
    raise ValueError(
        f"Illegal {entity_type} status transition: "
        f"{normalize_status_code(from_status)} → {normalize_status_code(to_status)}"
        + (f" for role {actor_role}" if actor_role is not None else "")
    )
