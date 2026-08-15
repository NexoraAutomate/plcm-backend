"""
Central status transition matrix for inventory items and projects (Spec 00).

Later workflow specs MUST call can_transition / assert_transition before
mutating status — do not scatter allowed-edge checks across routers.
"""

from __future__ import annotations

from typing import Optional, Set

from app.models.base import ItemStatus, ProjectWorkflowStatus

# entity_type values accepted by can_transition
ENTITY_ITEM = "item"
ENTITY_PROJECT = "project"

ITEM_TRANSITIONS: dict[ItemStatus, Set[ItemStatus]] = {
    ItemStatus.AVAILABLE: {ItemStatus.RESERVED},
    # Release / auto-release (Specs 04–06) returns stock to AVAILABLE
    ItemStatus.RESERVED: {ItemStatus.ISSUED, ItemStatus.AVAILABLE},
    ItemStatus.ISSUED: {
        ItemStatus.INSTALLATION_IN_PROGRESS,
        ItemStatus.RETURNED,
    },
    ItemStatus.INSTALLATION_IN_PROGRESS: {
        ItemStatus.UNDER_TESTING_REVIEW,
        ItemStatus.RETURNED,
    },
    ItemStatus.UNDER_TESTING_REVIEW: {
        ItemStatus.INSTALLED_VERIFIED,
        ItemStatus.RETURNED,
    },
    ItemStatus.INSTALLED_VERIFIED: set(),  # terminal happy path
    ItemStatus.RETURNED: {ItemStatus.INSPECTION},
    ItemStatus.INSPECTION: {
        ItemStatus.REUSABLE,
        ItemStatus.REPAIRABLE,
        ItemStatus.SCRAPPED,
    },
    ItemStatus.REUSABLE: {ItemStatus.AVAILABLE},
    # Spec 10 — repaired serial re-enters issue
    ItemStatus.REPAIRABLE: {ItemStatus.ISSUED},
    ItemStatus.SCRAPPED: set(),  # terminal
}

PROJECT_TRANSITIONS: dict[ProjectWorkflowStatus, Set[ProjectWorkflowStatus]] = {
    ProjectWorkflowStatus.DRAFT: {
        ProjectWorkflowStatus.APPROVED,
        ProjectWorkflowStatus.CANCELLED,
    },
    ProjectWorkflowStatus.APPROVED: {
        ProjectWorkflowStatus.HIERARCHY_GENERATED,
        ProjectWorkflowStatus.CANCELLED,
    },
    ProjectWorkflowStatus.HIERARCHY_GENERATED: {
        ProjectWorkflowStatus.READY_FOR_INVENTORY,
        ProjectWorkflowStatus.CANCELLED,
    },
    ProjectWorkflowStatus.READY_FOR_INVENTORY: {
        ProjectWorkflowStatus.CANCELLED,
        ProjectWorkflowStatus.COMPLETED,
        ProjectWorkflowStatus.READY_TO_DELIVER,
    },
    ProjectWorkflowStatus.CANCELLED: set(),
    ProjectWorkflowStatus.COMPLETED: {
        ProjectWorkflowStatus.READY_TO_DELIVER,
    },
    ProjectWorkflowStatus.READY_TO_DELIVER: set(),
}


class InvalidStatusTransition(ValueError):
    """Raised when a status change is not in the foundation matrix."""

    def __init__(
        self,
        entity_type: str,
        from_status: str,
        to_status: str,
        detail: Optional[str] = None,
    ):
        self.entity_type = entity_type
        self.from_status = from_status
        self.to_status = to_status
        message = detail or (
            f"Illegal {entity_type} status transition: "
            f"{from_status!r} → {to_status!r}"
        )
        super().__init__(message)


def _parse_item_status(value: str | ItemStatus) -> ItemStatus:
    if isinstance(value, ItemStatus):
        return value
    try:
        return ItemStatus(str(value).strip().upper())
    except ValueError as exc:
        raise InvalidStatusTransition(
            ENTITY_ITEM, str(value), "", f"Unknown item status: {value!r}"
        ) from exc


def _parse_project_status(value: str | ProjectWorkflowStatus) -> ProjectWorkflowStatus:
    if isinstance(value, ProjectWorkflowStatus):
        return value
    try:
        return ProjectWorkflowStatus(str(value).strip().upper())
    except ValueError as exc:
        raise InvalidStatusTransition(
            ENTITY_PROJECT, str(value), "", f"Unknown project status: {value!r}"
        ) from exc


def get_allowed_item_transitions(from_status: str | ItemStatus) -> Set[ItemStatus]:
    current = _parse_item_status(from_status)
    return set(ITEM_TRANSITIONS.get(current, set()))


def get_allowed_project_transitions(
    from_status: str | ProjectWorkflowStatus,
) -> Set[ProjectWorkflowStatus]:
    current = _parse_project_status(from_status)
    return set(PROJECT_TRANSITIONS.get(current, set()))


def can_transition(
    entity_type: str,
    from_status: str,
    to_status: str,
    actor_role: Optional[str] = None,
) -> bool:
    """
    Return True if the transition is allowed by the foundation matrix.

    actor_role is reserved for Spec 02+ role-gated edges; Spec 00 is role-blind.
    Same-status is treated as allowed (no-op).
    """
    _ = actor_role  # reserved for later specs
    kind = (entity_type or "").strip().lower()
    if kind in ("item", "inventory", "inventory_item"):
        try:
            src = _parse_item_status(from_status)
            dst = _parse_item_status(to_status)
        except InvalidStatusTransition:
            return False
        if src == dst:
            return True
        return dst in ITEM_TRANSITIONS.get(src, set())
    if kind in ("project", "projects"):
        try:
            src = _parse_project_status(from_status)
            dst = _parse_project_status(to_status)
        except InvalidStatusTransition:
            return False
        if src == dst:
            return True
        return dst in PROJECT_TRANSITIONS.get(src, set())
    return False


def assert_transition(
    entity_type: str,
    from_status: str,
    to_status: str,
    actor_role: Optional[str] = None,
) -> None:
    """Raise InvalidStatusTransition when the edge is not allowed."""
    if can_transition(entity_type, from_status, to_status, actor_role):
        return
    raise InvalidStatusTransition(entity_type, str(from_status), str(to_status))
