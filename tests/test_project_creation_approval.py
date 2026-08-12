"""Spec 02 — project draft creation and approval tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.database import engine
from app.domain.workflow_status import ProjectWorkflowStatus
from app.models.tables import HierarchyConfiguration, Project, Role, User
from app.services.hierarchy_config_service import (
    create_configuration,
    delete_configuration,
    set_available,
)
from app.services.project_workflow_service import (
    ProjectWorkflowError,
    assert_can_generate_hierarchy,
    approve_project,
    assign_hm,
    create_draft_project,
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
def config(session: Session):
    code = f"P2-{uuid.uuid4().hex[:8].upper()}"
    cfg = create_configuration(
        session,
        {
            "code": code,
            "name": f"Spec02 {code}",
            "is_available": True,
            "product_types": [
                {"code": "SSDLS-1", "name": "High Data Rate"},
                {"code": "SSDLS-2", "name": "Low Data Rate"},
            ],
            "nodes": [{"client_key": "s1", "level": "system", "name": "Comm"}],
        },
    )
    yield cfg
    delete_configuration(session, cfg.id, hard=True)


def test_hm_creates_draft(session: Session, admin_user: User, config: HierarchyConfiguration):
    project = create_draft_project(
        session,
        {
            "name": f"Draft-{uuid.uuid4().hex[:6]}",
            "hierarchy_config_id": config.id,
            "product_type": "SSDLS-1",
            "flight_count": 2,
            "sdls_per_flight": 3,
            "start_date": datetime.now(timezone.utc),
        },
        actor=admin_user,
    )
    assert project.status.status_name == ProjectWorkflowStatus.DRAFT.value
    assert project.hierarchy_config_id == config.id
    assert project.flight_count == 2
    assert project.sdls_per_flight == 3
    assert project.assigned_hm_id == admin_user.id
    session.delete(project)
    session.commit()


def test_create_requires_config(session: Session, admin_user: User):
    with pytest.raises(ProjectWorkflowError, match="hierarchy_config_id"):
        create_draft_project(
            session,
            {
                "name": "NoConfig",
                "product_type": "SSDLS-1",
                "flight_count": 1,
                "sdls_per_flight": 1,
            },
            actor=admin_user,
        )


def test_create_rejects_unavailable_config(
    session: Session, admin_user: User, config: HierarchyConfiguration
):
    set_available(session, config.id, False)
    with pytest.raises(ProjectWorkflowError, match="not available"):
        create_draft_project(
            session,
            {
                "name": "BadConfig",
                "hierarchy_config_id": config.id,
                "product_type": "SSDLS-1",
                "flight_count": 1,
                "sdls_per_flight": 1,
            },
            actor=admin_user,
        )
    set_available(session, config.id, True)


def test_generate_blocked_for_draft(
    session: Session, admin_user: User, config: HierarchyConfiguration
):
    project = create_draft_project(
        session,
        {
            "name": f"Blocked-{uuid.uuid4().hex[:6]}",
            "hierarchy_config_id": config.id,
            "product_type": "SSDLS-1",
            "flight_count": 1,
            "sdls_per_flight": 1,
        },
        actor=admin_user,
    )
    with pytest.raises(ProjectWorkflowError, match="APPROVED"):
        assert_can_generate_hierarchy(project)
    session.delete(project)
    session.commit()


def test_admin_approve_then_generate_still_deferred(
    session: Session, admin_user: User, config: HierarchyConfiguration
):
    project = create_draft_project(
        session,
        {
            "name": f"Approve-{uuid.uuid4().hex[:6]}",
            "hierarchy_config_id": config.id,
            "product_type": "SSDLS-2",
            "flight_count": 1,
            "sdls_per_flight": 2,
        },
        actor=admin_user,
    )
    approved = approve_project(session, project.id, actor=admin_user)
    assert approved.status.status_name == ProjectWorkflowStatus.APPROVED.value
    assert approved.approved_by_id == admin_user.id
    assert approved.approved_at is not None
    with pytest.raises(ProjectWorkflowError, match="Spec 03"):
        assert_can_generate_hierarchy(approved)
    session.delete(approved)
    session.commit()


def test_non_admin_cannot_approve_domain(
    session: Session, admin_user: User, config: HierarchyConfiguration
):
    # Build a synthetic non-admin actor with no Admin role
    hm_role = session.exec(select(Role).where(Role.name == "HierarchyManager")).first()
    if not hm_role:
        pytest.skip("HierarchyManager role required")
    actor = User(
        username=f"hm_{uuid.uuid4().hex[:6]}",
        email=f"hm_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Temp HM",
        password="x",
        is_active=True,
    )
    actor.roles = [hm_role]
    session.add(actor)
    session.commit()
    session.refresh(actor)

    project = create_draft_project(
        session,
        {
            "name": f"NoApprove-{uuid.uuid4().hex[:6]}",
            "hierarchy_config_id": config.id,
            "product_type": "SSDLS-1",
            "flight_count": 1,
            "sdls_per_flight": 1,
        },
        actor=admin_user,
    )
    with pytest.raises(ProjectWorkflowError, match="Only Admin"):
        approve_project(session, project.id, actor=actor)

    session.delete(project)
    session.delete(actor)
    session.commit()
