"""Unit tests: Spec 00 workflow roles + permission seed keys."""

from app.auth import DEFAULT_PERMISSIONS, DEFAULT_ROLES
from app.models.base import WorkflowRole

SPEC_00_PERMISSIONS = [
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
]

ROLE_PRIMARY_PERMS = {
    WorkflowRole.PD.value: ["project.assign_hm", "project.cancel"],
    WorkflowRole.HM.value: [
        "project.create_draft",
        "hierarchy.generate",
        "inventory.reserve",
        "item.verify",
    ],
    WorkflowRole.IM.value: ["inventory.receive", "inventory.issue", "item.inspect"],
    WorkflowRole.DEV.value: ["item.request", "item.install_test"],
}


def _role_perms(name: str) -> set[str]:
    for role in DEFAULT_ROLES:
        if role["name"] == name:
            return set(role["permissions"])
    raise AssertionError(f"Role {name!r} missing from DEFAULT_ROLES")


class TestWorkflowPermissionSeed:
    def test_all_spec_permissions_registered(self):
        names = {p["name"] for p in DEFAULT_PERMISSIONS}
        for key in SPEC_00_PERMISSIONS:
            assert key in names, f"Missing permission stub: {key}"

    def test_five_workflow_roles_present(self):
        role_names = {r["name"] for r in DEFAULT_ROLES}
        for role in WorkflowRole:
            assert role.value in role_names, f"Missing role: {role.value}"

    def test_admin_has_all_workflow_permissions(self):
        admin = _role_perms(WorkflowRole.ADMIN.value)
        for key in SPEC_00_PERMISSIONS:
            assert key in admin

    def test_primary_role_permission_matrix(self):
        for role_name, keys in ROLE_PRIMARY_PERMS.items():
            perms = _role_perms(role_name)
            for key in keys:
                assert key in perms, f"{role_name} missing {key}"

    def test_project_approve_is_admin_not_hm(self):
        assert "project.approve" in _role_perms(WorkflowRole.ADMIN.value)
        assert "project.approve" not in _role_perms(WorkflowRole.HM.value)
        assert "project.approve" not in _role_perms(WorkflowRole.PD.value)

    def test_hierarchy_config_manage_admin_only_among_workflow(self):
        assert "hierarchy_config.manage" in _role_perms(WorkflowRole.ADMIN.value)
        for role in (WorkflowRole.PD, WorkflowRole.HM, WorkflowRole.IM, WorkflowRole.DEV):
            assert "hierarchy_config.manage" not in _role_perms(role.value)
