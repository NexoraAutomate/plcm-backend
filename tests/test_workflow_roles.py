"""Spec 00 — workflow role mapping smoke tests."""

from app.domain.workflow_roles import (
    WORKFLOW_ROLE_DB_NAMES,
    WorkflowRole,
    has_workflow_role,
    normalize_workflow_role,
)
from app.domain.workflow_permissions import WORKFLOW_PERMISSION_NAMES, WORKFLOW_ROLE_PERMISSIONS


def test_all_five_roles_mapped():
    assert set(WORKFLOW_ROLE_DB_NAMES) == set(WorkflowRole)
    assert WORKFLOW_ROLE_DB_NAMES[WorkflowRole.ADMIN] == "Admin"
    assert WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD] == "ProjectDirector"
    assert WORKFLOW_ROLE_DB_NAMES[WorkflowRole.HM] == "HierarchyManager"
    assert WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM] == "InventoryManager"
    assert WORKFLOW_ROLE_DB_NAMES[WorkflowRole.DEV] == "Developer"


def test_normalize_accepts_code_and_db_name():
    assert normalize_workflow_role("HM") == WorkflowRole.HM
    assert normalize_workflow_role("HierarchyManager") == WorkflowRole.HM
    assert normalize_workflow_role("admin") == WorkflowRole.ADMIN


def test_has_workflow_role_matrix():
    roles = ["HierarchyManager", "Developer"]
    assert has_workflow_role(roles, WorkflowRole.HM)
    assert has_workflow_role(roles, "DEV")
    assert not has_workflow_role(roles, WorkflowRole.PD)


def test_permission_stubs_cover_spec_list():
    expected = {
        "hierarchy_config.manage",
        "project.assign_hm",
        "project.create_draft",
        "project.approve",
        "hierarchy.generate",
        "inventory.reserve",
        "inventory.release",
        "inventory.receive",
        "inventory.issue",
        "hierarchy.assign_developer",
        "item.request",
        "item.install_test",
        "item.verify",
        "item.inspect",
        "project.cancel",
        "config_change.request",
        "config_change.approve",
        "audit.read",
    }
    assert set(WORKFLOW_PERMISSION_NAMES) == expected
    for role in WorkflowRole:
        assert role in WORKFLOW_ROLE_PERMISSIONS
        assert WORKFLOW_ROLE_PERMISSIONS[role]
