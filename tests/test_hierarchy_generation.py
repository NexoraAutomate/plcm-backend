"""Spec 03 — hierarchy generation for approved projects."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.database import engine
from app.domain.workflow_status import ProjectWorkflowStatus
from app.models.tables import (
    Flight,
    HierarchyConfiguration,
    Project,
    Sdls,
    System,
    User,
)
from app.services.hierarchy_config_service import (
    create_configuration,
    delete_configuration,
)
from app.services.hierarchy_generation_service import (
    assert_can_generate_hierarchy,
    generate_project_hierarchy,
)
from app.services.project_workflow_service import (
    ProjectWorkflowError,
    approve_project,
    create_draft_project,
    create_draft_projects_by_flight,
)
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.workflow_foundation_seed import ensure_workflow_statuses


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    ensure_user_management_schema()
    with Session(engine) as session:
        ensure_workflow_statuses(session)


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s


@pytest.fixture()
def admin_user(session: Session):
    user = session.exec(select(User).where(User.username == "admin")).first()
    if not user:
        pytest.skip("admin user required")
    return user


@pytest.fixture()
def rich_config(session: Session):
    code = f"P3-{uuid.uuid4().hex[:8].upper()}"
    cfg = create_configuration(
        session,
        {
            "code": code,
            "name": f"Spec03 {code}",
            "is_available": True,
            "product_types": [
                {"code": "SSDLS-1", "name": "High Data Rate"},
                {"code": "SSDLS-2", "name": "Low Data Rate"},
            ],
            "nodes": [
                {"client_key": "sys1", "level": "system", "name": "Comm"},
                {
                    "client_key": "sub1",
                    "parent_client_key": "sys1",
                    "level": "subsystem",
                    "name": "RF",
                },
                {
                    "client_key": "mod1",
                    "parent_client_key": "sub1",
                    "level": "module",
                    "name": "Modem",
                },
                {
                    "client_key": "unit1",
                    "parent_client_key": "mod1",
                    "level": "unit",
                    "name": "Board",
                },
                {
                    "client_key": "cmp1",
                    "parent_client_key": "unit1",
                    "level": "component",
                    "name": "Chip",
                },
            ],
        },
    )
    yield cfg
    projects = session.exec(
        select(Project).where(Project.hierarchy_config_id == cfg.id)
    ).all()
    for p in projects:
        session.delete(p)
    session.commit()
    delete_configuration(session, cfg.id, hard=True)


def _draft_and_approve(
    session: Session,
    admin: User,
    config: HierarchyConfiguration,
    *,
    flights: int,
    sdls: int,
    product_type: str = "SSDLS-1",
) -> Project:
    project = create_draft_project(
        session,
        {
            "name": f"Gen-{uuid.uuid4().hex[:6]}",
            "hierarchy_config_id": config.id,
            "product_type": product_type,
            "flight_count": flights,
            "sdls_per_flight": sdls,
            "start_date": datetime.now(timezone.utc),
        },
        actor=admin,
    )
    return approve_project(session, project.id, actor=admin)


def test_generate_blocked_for_draft(
    session: Session, admin_user: User, rich_config: HierarchyConfiguration
):
    project = create_draft_project(
        session,
        {
            "name": f"DraftGate-{uuid.uuid4().hex[:6]}",
            "hierarchy_config_id": rich_config.id,
            "product_type": "SSDLS-1",
            "flight_count": 1,
            "sdls_per_flight": 1,
        },
        actor=admin_user,
    )
    with pytest.raises(ProjectWorkflowError, match="APPROVED"):
        assert_can_generate_hierarchy(project, session)
    session.delete(project)
    session.commit()


def test_generate_creates_full_tree_counts(
    session: Session, admin_user: User, rich_config: HierarchyConfiguration
):
    approved = _draft_and_approve(
        session, admin_user, rich_config, flights=2, sdls=3
    )
    result = generate_project_hierarchy(session, approved.id, actor=admin_user)

    assert result["status"] == ProjectWorkflowStatus.READY_FOR_INVENTORY.value
    assert result["counts"]["flights"] == 2
    assert result["counts"]["sdls"] == 6
    # 1 system template × 6 SDLS
    assert result["counts"]["systems"] == 6
    assert result["counts"]["subsystems"] == 6
    assert result["counts"]["modules"] == 6
    assert result["counts"]["units"] == 6
    assert result["counts"]["components"] == 6

    flights = session.exec(
        select(Flight).where(Flight.project_id == approved.id)
    ).all()
    assert len(flights) == 2
    sdls_rows = session.exec(
        select(Sdls).where(Sdls.flight_id.in_([f.id for f in flights]))
    ).all()
    assert len(sdls_rows) == 6

    systems = session.exec(
        select(System).where(System.project_id == approved.id)
    ).all()
    assert len(systems) == 6
    assert all(s.sdls_id is not None for s in systems)
    assert {s.name for s in systems} == {"Comm"}

    # Each SDLS has the same lower template
    for sdls in sdls_rows:
        sdls_systems = [s for s in systems if s.sdls_id == sdls.id]
        assert len(sdls_systems) == 1
        system = sdls_systems[0]
        session.refresh(system)
        assert len(system.subsystems or []) == 1
        sub = system.subsystems[0]
        assert sub.name == "RF"
        assert len(sub.modules or []) == 1
        mod = sub.modules[0]
        assert mod.name == "Modem"
        assert len(mod.units or []) == 1
        unit = mod.units[0]
        assert unit.name == "Board"
        assert len(unit.components or []) == 1
        assert unit.components[0].name == "Chip"

    session.refresh(approved)
    assert (
        approved.status.status_name
        == ProjectWorkflowStatus.READY_FOR_INVENTORY.value
    )


def test_second_generate_blocked(
    session: Session, admin_user: User, rich_config: HierarchyConfiguration
):
    approved = _draft_and_approve(
        session, admin_user, rich_config, flights=1, sdls=1
    )
    generate_project_hierarchy(session, approved.id, actor=admin_user)
    with pytest.raises(ProjectWorkflowError, match="already been generated"):
        generate_project_hierarchy(session, approved.id, actor=admin_user)


def test_product_type_appears_on_sdls(
    session: Session, admin_user: User, rich_config: HierarchyConfiguration
):
    approved = _draft_and_approve(
        session,
        admin_user,
        rich_config,
        flights=1,
        sdls=2,
        product_type="SSDLS-2",
    )
    generate_project_hierarchy(session, approved.id, actor=admin_user)
    flights = session.exec(
        select(Flight).where(Flight.project_id == approved.id)
    ).all()
    sdls_rows = session.exec(
        select(Sdls).where(Sdls.flight_id == flights[0].id)
    ).all()
    assert len(sdls_rows) == 2
    assert all(s.product_type == "SSDLS-2" for s in sdls_rows)
    assert {s.name for s in sdls_rows} == {"SDLS-1", "SDLS-2"}


def test_non_hm_without_permission_role_still_domain_ok_for_admin(
    session: Session, admin_user: User, rich_config: HierarchyConfiguration
):
    # Admin is allowed by transition matrix; API permission is separate.
    approved = _draft_and_approve(
        session, admin_user, rich_config, flights=1, sdls=1
    )
    result = generate_project_hierarchy(session, approved.id, actor=admin_user)
    assert result["ok"] is True


def test_split_flight_project_uses_name_suffix_for_flight_number(
    session: Session, admin_user: User, rich_config: HierarchyConfiguration
):
    """Per-flight projects from bulk draft must not all generate as Flight-1."""
    projects = create_draft_projects_by_flight(
        session,
        {
            "name": "Shopper-II MAV",
            "hierarchy_config_id": rich_config.id,
            "product_type": "SSDLS-1",
            "flight_count": 2,
            "sdls_counts_by_flight": [1, 1],
            "start_date": datetime.now(timezone.utc),
        },
        actor=admin_user,
    )
    flight_two = next(p for p in projects if p.name.endswith("Flight 2"))
    approved = approve_project(session, flight_two.id, actor=admin_user)

    generate_project_hierarchy(session, approved.id, actor=admin_user)

    flights = session.exec(
        select(Flight).where(Flight.project_id == approved.id)
    ).all()
    assert len(flights) == 1
    assert flights[0].name == "Flight-2"
    assert flights[0].sequence == 2
    assert flights[0].code == "F02"

    for project in projects:
        session.delete(project)
    session.commit()
