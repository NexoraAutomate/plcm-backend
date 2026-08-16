"""Unit tests: Spec 00 item + project status transition matrix."""

import pytest

from app.models.base import ItemStatus, ProjectWorkflowStatus
from app.services.status_transitions import (
    InvalidStatusTransition,
    assert_transition,
    can_transition,
    get_allowed_item_transitions,
)


class TestItemHappyPath:
    def test_stepwise_happy_path(self):
        chain = [
            ItemStatus.AVAILABLE,
            ItemStatus.RESERVED,
            ItemStatus.ISSUED,
            ItemStatus.INSTALLATION_IN_PROGRESS,
            ItemStatus.UNDER_TESTING_REVIEW,
            ItemStatus.INSTALLED_VERIFIED,
        ]
        for src, dst in zip(chain, chain[1:]):
            assert can_transition("item", src.value, dst.value)
            assert_transition("item", src.value, dst.value)

    def test_skip_ahead_disallowed(self):
        assert not can_transition("item", "AVAILABLE", "ISSUED")
        assert not can_transition("item", "AVAILABLE", "INSTALLED_VERIFIED")
        assert not can_transition("item", "RESERVED", "INSTALLATION_IN_PROGRESS")

    def test_terminal_installed_verified(self):
        assert get_allowed_item_transitions(ItemStatus.INSTALLED_VERIFIED) == {
            ItemStatus.RETURNED
        }
        assert not can_transition("item", "INSTALLED_VERIFIED", "AVAILABLE")
        assert not can_transition("item", "INSTALLED_VERIFIED", "RESERVED")
        assert can_transition("item", "INSTALLED_VERIFIED", "RETURNED")

    def test_release_reserved_to_available(self):
        assert can_transition("item", "RESERVED", "AVAILABLE")


class TestItemReturnPath:
    @pytest.mark.parametrize(
        "from_status",
        [
            "ISSUED",
            "INSTALLATION_IN_PROGRESS",
            "UNDER_TESTING_REVIEW",
        ],
    )
    def test_mid_lifecycle_to_returned(self, from_status):
        assert can_transition("item", from_status, "RETURNED")

    def test_return_inspection_dispositions(self):
        assert can_transition("item", "RETURNED", "INSPECTION")
        assert can_transition("item", "INSPECTION", "REUSABLE")
        assert can_transition("item", "INSPECTION", "REPAIRABLE")
        assert can_transition("item", "INSPECTION", "SCRAPPED")
        assert can_transition("item", "REUSABLE", "AVAILABLE")
        assert can_transition("item", "REPAIRABLE", "ISSUED")

    def test_scrapped_terminal(self):
        assert not can_transition("item", "SCRAPPED", "AVAILABLE")
        assert not can_transition("item", "SCRAPPED", "REUSABLE")

    def test_case_insensitive_codes(self):
        assert can_transition("item", "available", "reserved")
        assert can_transition("item", "Available", "Reserved")
        assert can_transition("inventory", "AVAILABLE", "RESERVED")


class TestProjectTransitions:
    def test_foundation_chain(self):
        chain = [
            ProjectWorkflowStatus.DRAFT,
            ProjectWorkflowStatus.APPROVED,
            ProjectWorkflowStatus.HIERARCHY_GENERATED,
            ProjectWorkflowStatus.READY_FOR_INVENTORY,
        ]
        for src, dst in zip(chain, chain[1:]):
            assert can_transition("project", src.value, dst.value)

    def test_skip_disallowed(self):
        assert not can_transition("project", "DRAFT", "READY_FOR_INVENTORY")
        assert not can_transition("project", "DRAFT", "HIERARCHY_GENERATED")
        assert not can_transition("project", "APPROVED", "READY_FOR_INVENTORY")

    def test_cancel_from_mid_life(self):
        for status in (
            "DRAFT",
            "APPROVED",
            "HIERARCHY_GENERATED",
            "READY_FOR_INVENTORY",
        ):
            assert can_transition("project", status, "CANCELLED")

    def test_cancelled_terminal(self):
        assert not can_transition("project", "CANCELLED", "DRAFT")
        assert not can_transition("project", "CANCELLED", "APPROVED")

    def test_supersede_from_ready(self):
        assert can_transition("project", "READY_FOR_INVENTORY", "SUPERSEDED")
        assert not can_transition("project", "SUPERSEDED", "DRAFT")

    def test_noop_same_status(self):
        assert can_transition("project", "DRAFT", "DRAFT")
        assert can_transition("item", "AVAILABLE", "AVAILABLE")


class TestAssertTransition:
    def test_raises_on_illegal(self):
        with pytest.raises(InvalidStatusTransition) as exc_info:
            assert_transition("item", "AVAILABLE", "SCRAPPED")
        assert exc_info.value.from_status == "AVAILABLE"
        assert exc_info.value.to_status == "SCRAPPED"

    def test_unknown_entity_type(self):
        assert not can_transition("unknown", "A", "B")
