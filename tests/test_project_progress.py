"""Spec 09 — weighted project progress, lifecycle events, completion gate."""

from datetime import datetime, timezone
import uuid

import pytest
from sqlmodel import Session, select

from app.auth import hash_password
from app.database import engine
from app.domain.workflow_status import ProjectWorkflowStatus
from app.models.tables import Project, Role, Subsystem, System, User
from app.services.hierarchy_config_service import create_configuration
from app.services.hierarchy_developer_service import assign_developer
from app.services.hierarchy_generation_service import generate_project_hierarchy
from app.services.inventory_reservation_service import reserve_inventory
from app.services.item_install_verify_service import (
    report_complete,
    start_install,
    submit_test,
    verify_issuance,
)
from app.services.item_request_service import create_item_request, issue_item_request
from app.services.project_progress_service import (
    ProjectProgressError,
    assert_completion_allowed,
    compute_project_progress,
    sync_project_progress,
)
from app.services.project_workflow_service import approve_project, create_draft_project
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.workflow_foundation_seed import ensure_workflow_statuses
from tests.test_install_test_verify import _issue_to_developer
from tests.test_issue_to_developer import _cleanup, _ready_project, _stock_for_system


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
def developer_user(session: Session):
    role = session.exec(select(Role).where(Role.name == "Developer")).first()
    if not role:
        pytest.skip("Developer role required")
    username = f"dev_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name="Spec09 Developer",
        is_active=True,
        password=hash_password("Dev@Test1"),
        updated_at=datetime.now(timezone.utc),
    )
    user.roles = [role]
    session.add(user)
    session.commit()
    session.refresh(user)
    yield user
    session.delete(user)
    session.commit()


def _ready_single_sdls(session: Session, admin: User, *, system_name: str):
    code = f"R9-{uuid.uuid4().hex[:8].upper()}"
    cfg = create_configuration(
        session,
        {
            "code": code,
            "name": code,
            "is_available": True,
            "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
            "nodes": [
                {"client_key": "s1", "level": "system", "name": system_name},
                {
                    "client_key": "sub1",
                    "parent_client_key": "s1",
                    "level": "subsystem",
                    "name": "RF",
                },
            ],
        },
    )
    project = create_draft_project(
        session,
        {
            "name": f"Prog-{code}",
            "hierarchy_config_id": cfg.id,
            "product_type": "SSDLS-1",
            "flight_count": 1,
            "sdls_per_flight": 1,
            "start_date": datetime.now(timezone.utc),
        },
        actor=admin,
    )
    approve_project(session, project.id, actor=admin)
    generate_project_hierarchy(session, project.id, actor=admin)
    session.refresh(project)
    return project, cfg


def _issue_single(
    session: Session, admin: User, developer: User, serial: str
):
    sys_name = f"Gate-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_single_sdls(session, admin, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=[serial])
    target = session.exec(select(System).where(System.project_id == project.id)).first()
    assign_developer(
        session, "system", int(target.id), int(developer.id), actor=admin
    )
    reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target.id),
            "serial_number": serial,
        },
        actor=admin,
    )
    req = create_item_request(
        session, entity_type="system", entity_id=int(target.id), actor=developer
    )
    issued = issue_item_request(
        session,
        int(req.id),
        actor=admin,
        signature_type="DIGITAL",
        signature_payload="data:image/png;base64,aaa",
    )
    return project, cfg, inv, target, issued


def test_empty_generated_tree_is_zero(session: Session, admin_user: User):
    project, cfg = _ready_project(
        session, admin_user, system_name=f"P0-{uuid.uuid4().hex[:6]}"
    )
    try:
        snapshot = compute_project_progress(session, int(project.id))
        assert snapshot["progress_pct"] == 0
        assert snapshot["weight"] >= 1
        assert snapshot["verified_leaves"] == 0
        assert snapshot["can_complete"] is False
        with pytest.raises(ProjectProgressError, match="unverified"):
            assert_completion_allowed(session, project)
    finally:
        _cleanup(session, project, cfg)


def test_lifecycle_events_increment_progress_and_partial_is_not_complete(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-P09-1"
    )
    try:
        systems = session.exec(
            select(System).where(System.project_id == project.id)
        ).all()
        assert len(systems) == 2

        after_issue = compute_project_progress(session, int(project.id))
        assert after_issue["progress_pct"] == 15
        assert after_issue["can_complete"] is False

        start_install(session, "system", int(target.id), actor=developer_user)
        assert compute_project_progress(session, int(project.id))["progress_pct"] == 25

        submit_test(
            session, "system", int(target.id), result="pass", actor=developer_user
        )
        assert compute_project_progress(session, int(project.id))["progress_pct"] == 38

        report_complete(session, "system", int(target.id), actor=developer_user)
        verify_issuance(session, int(issued.issued_issuance_id), actor=admin_user)
        half = compute_project_progress(session, int(project.id))
        assert half["progress_pct"] == 50
        assert half["verified_leaves"] == 1
        assert half["can_complete"] is False
        session.refresh(project)
        assert project.status.status_name != ProjectWorkflowStatus.COMPLETED.value
    finally:
        _cleanup(session, project, cfg, inv)


def test_all_required_verified_completes_project(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, issued = _issue_single(
        session, admin_user, developer_user, "SN-P09-C"
    )
    try:
        start_install(session, "system", int(target.id), actor=developer_user)
        submit_test(
            session, "system", int(target.id), result="pass", actor=developer_user
        )
        report_complete(session, "system", int(target.id), actor=developer_user)
        verify_issuance(session, int(issued.issued_issuance_id), actor=admin_user)
        done = compute_project_progress(session, int(project.id))
        assert done["progress_pct"] == 100
        assert done["can_complete"] is True
        session.refresh(project)
        assert project.progress == 100
        assert project.status.status_name == ProjectWorkflowStatus.COMPLETED.value
    finally:
        _cleanup(session, project, cfg, inv)


def test_uneven_tree_is_not_naive_average(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-P09-U"
    )
    try:
        extra = Subsystem(name="Extra-RF", system_id=int(target.id))
        session.add(extra)
        session.commit()

        snapshot = compute_project_progress(session, int(project.id))
        assert snapshot["weight"] == 3

        start_install(session, "system", int(target.id), actor=developer_user)
        submit_test(
            session, "system", int(target.id), result="pass", actor=developer_user
        )
        report_complete(session, "system", int(target.id), actor=developer_user)
        verify_issuance(session, int(issued.issued_issuance_id), actor=admin_user)

        after = compute_project_progress(session, int(project.id))
        assert after["weight"] == 3
        assert after["verified_leaves"] == 2
        assert after["progress_pct"] == 67
        assert after["can_complete"] is False
        assert after["progress_pct"] != 50
    finally:
        _cleanup(session, project, cfg, inv)


def test_fail_does_not_count_as_verified(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-P09-F"
    )
    try:
        start_install(session, "system", int(target.id), actor=developer_user)
        submit_test(
            session, "system", int(target.id), result="fail", actor=developer_user
        )
        snapshot = compute_project_progress(session, int(project.id))
        assert snapshot["verified_leaves"] == 0
        assert snapshot["can_complete"] is False
        assert snapshot["progress_pct"] < 100
        assert any(row["reason"] == "fail_loop" for row in snapshot["bottlenecks"])
        session.refresh(project)
        assert project.status.status_name != ProjectWorkflowStatus.COMPLETED.value
    finally:
        _cleanup(session, project, cfg, inv)


def test_sync_overwrites_manual_progress(session: Session, admin_user: User):
    project, cfg = _ready_project(
        session, admin_user, system_name=f"Pman-{uuid.uuid4().hex[:6]}"
    )
    try:
        project.progress = 88
        session.add(project)
        session.commit()
        snapshot = sync_project_progress(session, int(project.id))
        session.commit()
        session.refresh(project)
        assert snapshot["progress_pct"] == 0
        assert project.progress == 0
    finally:
        _cleanup(session, project, cfg)
