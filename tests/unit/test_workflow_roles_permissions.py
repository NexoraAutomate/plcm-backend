"""Unit tests: Spec 00 workflow roles + permission seed keys."""

from app.auth import DEFAULT_PERMISSIONS, DEFAULT_ROLES
from app.domain.workflow_roles import WORKFLOW_ROLE_DB_NAMES, WorkflowRole

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
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD]: [
        "project.create_draft",
        "project.approve",
        "project.assign_hm",
        "project.cancel",
    ],
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.HM]: [
        "project.create_draft",
        "hierarchy.generate",
        "inventory.reserve",
        "item.verify",
    ],
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM]: [
        "inventory.receive",
        "inventory.issue",
        "item.inspect",
    ],
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.DEV]: ["item.request", "item.install_test"],
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
            assert WORKFLOW_ROLE_DB_NAMES[role] in role_names, (
                f"Missing role: {WORKFLOW_ROLE_DB_NAMES[role]}"
            )

    def test_admin_has_all_workflow_permissions(self):
        admin = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.ADMIN])
        for key in SPEC_00_PERMISSIONS:
            assert key in admin

    def test_primary_role_permission_matrix(self):
        for role_name, keys in ROLE_PRIMARY_PERMS.items():
            perms = _role_perms(role_name)
            for key in keys:
                assert key in perms, f"{role_name} missing {key}"

    def test_project_approve_is_admin_and_pd_not_hm(self):
        assert "project.approve" in _role_perms(
            WORKFLOW_ROLE_DB_NAMES[WorkflowRole.ADMIN]
        )
        assert "project.approve" in _role_perms(
            WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD]
        )
        assert "project.approve" not in _role_perms(
            WORKFLOW_ROLE_DB_NAMES[WorkflowRole.HM]
        )
        assert "create_projects" in _role_perms(
            WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD]
        )
        assert "project.create_draft" in _role_perms(
            WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD]
        )

    def test_hierarchy_config_manage_admin_only_among_workflow(self):
        assert "hierarchy_config.manage" in _role_perms(
            WORKFLOW_ROLE_DB_NAMES[WorkflowRole.ADMIN]
        )
        for role in (WorkflowRole.PD, WorkflowRole.HM, WorkflowRole.IM, WorkflowRole.DEV):
            assert "hierarchy_config.manage" not in _role_perms(
                WORKFLOW_ROLE_DB_NAMES[role]
            )

    def test_workflow_roles_can_view_generated_hierarchy_shells(self):
        """Spec 03 shells are listed via /systems|/subsystems|… — not Admin-only."""
        hierarchy_views = {
            "view_systems",
            "view_subsystems",
            "view_modules",
            "view_units",
            "view_components",
        }
        for role in (WorkflowRole.PD, WorkflowRole.HM, WorkflowRole.IM, WorkflowRole.DEV):
            perms = _role_perms(WORKFLOW_ROLE_DB_NAMES[role])
            missing = hierarchy_views - perms
            assert not missing, f"{WORKFLOW_ROLE_DB_NAMES[role]} missing {missing}"

    def test_workflow_roles_can_view_statuses_for_project_pages(self):
        """Project detail loads system statuses; all workflow actors need view_statuses."""
        for role in (WorkflowRole.PD, WorkflowRole.HM, WorkflowRole.IM, WorkflowRole.DEV):
            assert "view_statuses" in _role_perms(WORKFLOW_ROLE_DB_NAMES[role]), (
                f"{WORKFLOW_ROLE_DB_NAMES[role]} missing view_statuses"
            )

    def test_hm_and_pd_can_view_orders_for_project_create(self):
        """Project create form lists order numbers via /orders/."""
        for role in (WorkflowRole.PD, WorkflowRole.HM):
            assert "view_orders" in _role_perms(WORKFLOW_ROLE_DB_NAMES[role]), (
                f"{WORKFLOW_ROLE_DB_NAMES[role]} missing view_orders"
            )

    def test_inventory_manager_can_view_entity_list(self):
        """Add-inventory category dropdown reads Settings → Entity List via /hierarchies/."""
        im = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM])
        assert "view_hierarchy" in im
        assert "create_inventory" in im
