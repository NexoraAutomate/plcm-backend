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

MAINTENANCE_WORKFLOW_PERMISSIONS = [
    "maintenance.occurrence_report",
    "maintenance.replacement_request",
    "maintenance.replacement_approve",
    "maintenance.assign_me",
    "maintenance.request_issue",
    "maintenance.im_issue",
    "maintenance.ait_upload",
    "maintenance.ait_approve",
    "maintenance.reception",
    "maintenance.assign_ie",
    "maintenance.im_issue_to_ie",
    "maintenance.inspection_disposition",
    "maintenance.repair_approve",
    "maintenance.confirm_discard",
    "maintenance.case_close",
]

ROLE_PRIMARY_PERMS = {
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD]: [
        "project.create_draft",
        "project.approve",
        "project.assign_hm",
        "project.cancel",
        "hierarchy_config.manage",
        "config_change.request",
        "config_change.approve",
    ],
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.HM]: [
        "project.create_draft",
        "hierarchy.generate",
        "inventory.reserve",
        "item.verify",
        "maintenance.assign_me",
        "maintenance.assign_ie",
        "view_my_assignments",
        "view_notifications",
    ],
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM]: [
        "inventory.receive",
        "inventory.issue",
        "item.inspect",
        "maintenance.im_issue",
        "maintenance.reception",
        "maintenance.im_issue_to_ie",
        "maintenance.confirm_discard",
    ],
    WORKFLOW_ROLE_DB_NAMES[WorkflowRole.DEV]: [
        "item.request",
        "item.install_test",
        "view_my_assignments",
        "view_notifications",
    ],
}


def _role_perms(name: str) -> set[str]:
    for role in DEFAULT_ROLES:
        if role["name"] == name:
            return set(role["permissions"])
    raise AssertionError(f"Role {name!r} missing from DEFAULT_ROLES")


class TestWorkflowPermissionSeed:
    def test_all_spec_permissions_registered(self):
        names = {p["name"] for p in DEFAULT_PERMISSIONS}
        for key in SPEC_00_PERMISSIONS + MAINTENANCE_WORKFLOW_PERMISSIONS:
            assert key in names, f"Missing permission stub: {key}"

    def test_eight_workflow_roles_present(self):
        """UT-RL-001 — WorkflowRole includes ME, FSE, IE (and full 8-role set)."""
        role_names = {r["name"] for r in DEFAULT_ROLES}
        assert len(list(WorkflowRole)) == 8
        assert WorkflowRole.ME in WorkflowRole
        assert WorkflowRole.FSE in WorkflowRole
        assert WorkflowRole.IE in WorkflowRole
        for role in WorkflowRole:
            assert WORKFLOW_ROLE_DB_NAMES[role] in role_names, (
                f"Missing role: {WORKFLOW_ROLE_DB_NAMES[role]}"
            )

    def test_legacy_maintenance_role_resolvable_as_notify_target(self):
        """UT-RL-004 — Legacy Maintenance remains a notify target with ME."""
        from app.services.app_notification_service import MAINTENANCE_ROLE_NAMES
        from app.services.workflow_demo_users import WORKFLOW_DEMO_USERS

        assert "Maintenance" in MAINTENANCE_ROLE_NAMES
        assert WORKFLOW_ROLE_DB_NAMES[WorkflowRole.ME] in MAINTENANCE_ROLE_NAMES
        demo_roles = {u["role"] for u in WORKFLOW_DEMO_USERS}
        assert "Maintenance" in demo_roles
        role_names = {r["name"] for r in DEFAULT_ROLES}
        assert "Maintenance" in role_names

    def test_admin_has_all_workflow_permissions(self):
        admin = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.ADMIN])
        for key in SPEC_00_PERMISSIONS + MAINTENANCE_WORKFLOW_PERMISSIONS:
            assert key in admin

    def test_maintenance_permissions_mapped_to_roles(self):
        """UT-RL-002 — ME/FSE/IE/PD/HM/IM grants for granular maintenance.* gates."""
        me = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.ME])
        fse = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.FSE])
        ie = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IE])
        pd = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD])
        hm = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.HM])
        im = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM])
        assert "maintenance.occurrence_report" in me
        assert "maintenance.replacement_request" in me
        assert "maintenance.request_issue" in me
        assert "maintenance.ait_upload" in me
        assert "maintenance.case_close" in me
        assert "maintenance.replacement_approve" not in me
        assert "maintenance.assign_me" not in me
        assert "maintenance.im_issue" not in me
        assert "maintenance.reception" not in me
        assert "maintenance.occurrence_report" in fse
        assert "maintenance.inspection_disposition" in ie
        assert "maintenance.replacement_approve" in pd
        assert "maintenance.assign_me" in pd
        assert "maintenance.ait_approve" in pd
        assert "maintenance.assign_ie" in pd
        assert "maintenance.repair_approve" in pd
        assert "maintenance.replacement_request" not in pd
        assert "maintenance.assign_me" in hm
        assert "maintenance.assign_ie" in hm
        assert "maintenance.replacement_request" not in hm
        assert "maintenance.im_issue" in im
        assert "maintenance.reception" in im
        assert "maintenance.im_issue_to_ie" in im
        assert "maintenance.confirm_discard" in im

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

    def test_hierarchy_config_manage_admin_and_pd_among_workflow(self):
        assert "hierarchy_config.manage" in _role_perms(
            WORKFLOW_ROLE_DB_NAMES[WorkflowRole.ADMIN]
        )
        assert "hierarchy_config.manage" in _role_perms(
            WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD]
        )
        for role in (WorkflowRole.HM, WorkflowRole.IM, WorkflowRole.DEV):
            assert "hierarchy_config.manage" not in _role_perms(
                WORKFLOW_ROLE_DB_NAMES[role]
            )

    def test_project_director_has_definitions_and_config_change_permissions(self):
        """Definitions Labels/Entity List/Configurations + Config Change (request+approve)."""
        pd = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD])
        assert {
            "view_hierarchy",
            "create_hierarchy",
            "edit_hierarchy",
            "delete_hierarchy",
            "hierarchy_config.manage",
            "config_change.request",
            "config_change.approve",
        } <= pd

    def test_hierarchy_manager_has_full_entity_list_and_labels_permissions(self):
        """Definitions → Entity List (CRUD); Labels & Templates via create_hierarchy."""
        hm = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.HM])
        assert {
            "view_hierarchy",
            "create_hierarchy",
            "edit_hierarchy",
            "delete_hierarchy",
        } <= hm
        assert "hierarchy_config.manage" not in hm

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

    def test_project_director_can_create_customers_and_orders(self):
        """Project Director can access and create customers and orders."""
        pd_permissions = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD])
        required_permissions = {
            "view_customers",
            "create_customers",
            "view_orders",
            "create_orders",
        }
        assert required_permissions <= pd_permissions

    def test_inventory_manager_can_view_entity_list(self):
        """Add-inventory category dropdown reads Settings → Entity List via /hierarchies/."""
        im = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM])
        assert "view_hierarchy" in im
        assert "create_inventory" in im

    def test_inventory_manager_has_full_entity_list_and_labels_permissions(self):
        """Definitions → Entity List (CRUD); Labels & Templates via edit_inventory."""
        im = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM])
        assert {
            "view_hierarchy",
            "create_hierarchy",
            "edit_hierarchy",
            "delete_hierarchy",
            "edit_inventory",
        } <= im

    def test_inventory_manager_can_manage_attachments(self):
        """Inventory create/edit Attachments tab uploads against inventory owners."""
        im = _role_perms(WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM])
        assert "upload_attachments" in im
        assert "download_attachments" in im
        assert "delete_attachments" in im
