"""Unit tests for Spec 00 status transition matrix."""

from __future__ import annotations

import pytest

from app.domain.status_transitions import assert_transition, can_transition
from app.domain.workflow_roles import WorkflowRole
from app.domain.workflow_status import ItemStatus, ProjectWorkflowStatus


class TestItemHappyPath:
    def test_full_chain(self):
        chain = [
            ItemStatus.AVAILABLE,
            ItemStatus.RESERVED,
            ItemStatus.ISSUED,
            ItemStatus.INSTALLATION_IN_PROGRESS,
            ItemStatus.UNDER_TESTING_REVIEW,
            ItemStatus.INSTALLED_VERIFIED,
        ]
        for frm, to in zip(chain, chain[1:]):
            assert can_transition("item", frm, to)

    def test_skip_ahead_illegal(self):
        assert not can_transition(
            "item", ItemStatus.AVAILABLE, ItemStatus.ISSUED
        )
        assert not can_transition(
            "item",
            ItemStatus.RESERVED,
            ItemStatus.INSTALLED_VERIFIED,
        )

    def test_terminal_blocks(self):
        assert not can_transition(
            "item",
            ItemStatus.INSTALLED_VERIFIED,
            ItemStatus.AVAILABLE,
        )


class TestItemReturnPath:
    @pytest.mark.parametrize(
        "frm",
        [
            ItemStatus.ISSUED,
            ItemStatus.INSTALLATION_IN_PROGRESS,
            ItemStatus.UNDER_TESTING_REVIEW,
        ],
    )
    def test_mid_lifecycle_to_returned(self, frm):
        assert can_transition("item", frm, ItemStatus.RETURNED)

    def test_inspection_outcomes(self):
        assert can_transition("item", ItemStatus.RETURNED, ItemStatus.INSPECTION)
        for outcome in (
            ItemStatus.REUSABLE,
            ItemStatus.REPAIRABLE,
            ItemStatus.SCRAPPED,
        ):
            assert can_transition("item", ItemStatus.INSPECTION, outcome)
        assert can_transition("item", ItemStatus.REUSABLE, ItemStatus.AVAILABLE)

    def test_release_reserved_to_available(self):
        assert can_transition("item", ItemStatus.RESERVED, ItemStatus.AVAILABLE)


class TestProjectTransitions:
    def test_foundation_chain(self):
        chain = [
            ProjectWorkflowStatus.DRAFT,
            ProjectWorkflowStatus.APPROVED,
            ProjectWorkflowStatus.HIERARCHY_GENERATED,
            ProjectWorkflowStatus.READY_FOR_INVENTORY,
        ]
        for frm, to in zip(chain, chain[1:]):
            assert can_transition("project", frm, to)

    def test_cancel_from_ready(self):
        assert can_transition(
            "project",
            ProjectWorkflowStatus.READY_FOR_INVENTORY,
            ProjectWorkflowStatus.CANCELLED,
            actor_role=WorkflowRole.PD,
        )

    def test_illegal_project_skip(self):
        assert not can_transition(
            "project",
            ProjectWorkflowStatus.DRAFT,
            ProjectWorkflowStatus.READY_FOR_INVENTORY,
        )

    def test_approve_role_gate(self):
        assert can_transition(
            "project",
            ProjectWorkflowStatus.DRAFT,
            ProjectWorkflowStatus.APPROVED,
            actor_role=WorkflowRole.ADMIN,
        )
        assert not can_transition(
            "project",
            ProjectWorkflowStatus.DRAFT,
            ProjectWorkflowStatus.APPROVED,
            actor_role=WorkflowRole.DEV,
        )


class TestAssertTransition:
    def test_raises_on_illegal(self):
        with pytest.raises(ValueError, match="Illegal"):
            assert_transition(
                "item",
                ItemStatus.AVAILABLE,
                ItemStatus.INSTALLED_VERIFIED,
            )

    def test_string_codes_accepted(self):
        assert can_transition("item", "AVAILABLE", "RESERVED")
        assert can_transition("project", "DRAFT", "APPROVED")


class TestItemRoleGates:
    def test_system_skips_role_gate(self):
        assert can_transition(
            "item",
            ItemStatus.ISSUED,
            ItemStatus.INSTALLATION_IN_PROGRESS,
            actor_role=None,
        )

    def test_dev_can_start_install_and_test(self):
        assert can_transition(
            "item",
            ItemStatus.ISSUED,
            ItemStatus.INSTALLATION_IN_PROGRESS,
            actor_role=WorkflowRole.DEV,
        )
        assert can_transition(
            "item",
            ItemStatus.INSTALLATION_IN_PROGRESS,
            ItemStatus.UNDER_TESTING_REVIEW,
            actor_role=WorkflowRole.DEV,
        )

    def test_dev_cannot_verify(self):
        assert not can_transition(
            "item",
            ItemStatus.UNDER_TESTING_REVIEW,
            ItemStatus.INSTALLED_VERIFIED,
            actor_role=WorkflowRole.DEV,
        )

    def test_hm_can_verify(self):
        assert can_transition(
            "item",
            ItemStatus.UNDER_TESTING_REVIEW,
            ItemStatus.INSTALLED_VERIFIED,
            actor_role=WorkflowRole.HM,
        )
