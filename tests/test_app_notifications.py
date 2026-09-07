"""Spec 14 — unified AppNotification targeting, skip existing inventory channels."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.auth import hash_password
from app.database import engine
from app.domain.workflow_audit import WorkflowAuditAction
from app.main import app
from app.models.tables import AppNotification, Project, Role, User
from app.services.app_notification_service import (
    EXISTING_EVENT_TYPES,
    list_app_notifications,
    notify,
    notify_from_audit,
)
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.workflow_audit_service import write_workflow_audit
from app.services.workflow_foundation_seed import ensure_workflow_statuses


ADMIN_USER = "admin"
ADMIN_PASS = "password@82768243"


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    ensure_user_management_schema()
    with Session(engine) as session:
        ensure_workflow_statuses(session)
        session.commit()


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s


@pytest.fixture()
def admin_user(session: Session):
    user = session.exec(select(User).where(User.username == ADMIN_USER)).first()
    if not user:
        pytest.skip("admin user required")
    return user


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _login(client: TestClient) -> dict:
    res = client.post(
        "/api/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _make_role_user(session: Session, *, role_name: str) -> User:
    role = session.exec(select(Role).where(Role.name == role_name)).first()
    if not role:
        pytest.skip(f"{role_name} role required")
    username = f"n_{role_name[:3].lower()}_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=f"Spec14 {role_name}",
        is_active=True,
        password=hash_password("Notif@Test1"),
        updated_at=datetime.now(timezone.utc),
    )
    user.roles = [role]
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _cleanup_user(session: Session, user: User) -> None:
    notices = session.exec(
        select(AppNotification).where(AppNotification.user_id == user.id)
    ).all()
    for row in notices:
        session.delete(row)
    session.delete(user)
    session.commit()


def test_notify_skips_existing_inventory_event_types(session: Session, admin_user: User):
    for event_type in (
        "inventory_issued",
        "issued",
        "inventory_returned",
        "inventory_shortage",
        "reservation_idle_reminder",
        "reservation_auto_released",
    ):
        assert event_type in EXISTING_EVENT_TYPES
        rows = notify(
            session,
            event_type=event_type,
            title="should not persist",
            message="duplicate of specialized table",
            extra_user_ids=[int(admin_user.id)],
            exclude_actor=False,
        )
        assert rows == []


def test_notify_from_audit_skips_existing_issue_and_shortage(
    session: Session, admin_user: User
):
    for action in (
        WorkflowAuditAction.ISSUED,
        WorkflowAuditAction.RE_ISSUED,
        WorkflowAuditAction.SHORTAGE_CREATED,
        WorkflowAuditAction.SHORTAGE_PARTIAL,
        WorkflowAuditAction.SHORTAGE_FULFILLED,
        WorkflowAuditAction.AUTO_RELEASE_EXPIRY,
    ):
        rows = notify_from_audit(
            session,
            SimpleNamespace(
                action=action,
                entity_type="inventory",
                entity_id=1,
                project_id=None,
                new_value={},
                old_value={},
                remarks=None,
            ),
            actor=admin_user,
        )
        assert rows == []


def test_write_issued_audit_does_not_create_app_notification(
    session: Session, admin_user: User
):
    before = session.exec(select(AppNotification)).all()
    before_ids = {row.id for row in before}
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.ISSUED,
        entity_type="inventory_issuance",
        entity_id=uuid.uuid4().hex[:8],
        actor=admin_user,
        remarks="spec14 skip issued",
    )
    session.commit()
    after = session.exec(select(AppNotification)).all()
    new_rows = [row for row in after if row.id not in before_ids]
    assert new_rows == []


def test_notify_excludes_actor_and_targets_assigned_hm(session: Session, admin_user: User):
    hm = _make_role_user(session, role_name="HierarchyManager")
    project = None
    try:
        project = Project(
            name=f"notif-{uuid.uuid4().hex[:8]}",
            start_date=datetime.now(timezone.utc),
            owner_id=int(admin_user.id),
            assigned_hm_id=int(hm.id),
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        rows = notify(
            session,
            event_type="project_approved",
            title="Project approved",
            message="unit test approve",
            actor=admin_user,
            include_assigned_hm=True,
            include_admin=True,
            project=project,
        )
        session.commit()
        recipient_ids = {int(r.user_id) for r in rows}
        assert int(hm.id) in recipient_ids
        assert int(admin_user.id) not in recipient_ids

        hm_list = list_app_notifications(session, int(hm.id))
        assert any(r.event_type == "project_approved" and r.project_id == project.id for r in hm_list)
        admin_list = list_app_notifications(session, int(admin_user.id), search="unit test approve")
        assert not any(r.event_type == "project_approved" and r.project_id == project.id for r in admin_list)
    finally:
        if project is not None and project.id is not None:
            leftover = session.exec(
                select(AppNotification).where(AppNotification.project_id == project.id)
            ).all()
            for row in leftover:
                session.delete(row)
            session.delete(project)
            session.commit()
        _cleanup_user(session, hm)


def test_list_app_notifications_is_scoped_to_current_user(session: Session, admin_user: User):
    hm = _make_role_user(session, role_name="HierarchyManager")
    marker = uuid.uuid4().hex[:8]
    try:
        rows = notify(
            session,
            event_type="developer_assigned",
            title=f"Work assigned {marker}",
            message="only the developer/hm extra recipient",
            actor=admin_user,
            extra_user_ids=[int(hm.id)],
        )
        session.commit()
        assert len(rows) == 1
        assert rows[0].user_id == hm.id

        hm_rows = list_app_notifications(session, int(hm.id), search=marker)
        admin_rows = list_app_notifications(session, int(admin_user.id), search=marker)
        assert len(hm_rows) == 1
        assert admin_rows == []
    finally:
        leftover = session.exec(
            select(AppNotification).where(AppNotification.user_id == hm.id)
        ).all()
        for row in leftover:
            session.delete(row)
        session.commit()
        _cleanup_user(session, hm)


def test_http_list_is_scoped_to_logged_in_user(
    session: Session, admin_user: User, client: TestClient
):
    marker = uuid.uuid4().hex[:8]
    rows = notify(
        session,
        event_type="signup_pending",
        title=f"Signup pending {marker}",
        message="awaiting activation",
        actor=None,
        include_admin=True,
        extra_user_ids=[int(admin_user.id)],
        exclude_actor=False,
    )
    session.commit()
    assert rows
    headers = _login(client)
    res = client.get("/api/notifications/", headers=headers, params={"search": marker})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert any(item.get("title") == f"Signup pending {marker}" for item in payload)
    assert all(item.get("user_id") == admin_user.id for item in payload)

    notice_id = next(item["id"] for item in payload if item.get("title") == f"Signup pending {marker}")
    read = client.post(f"/api/notifications/{notice_id}/read/", headers=headers)
    assert read.status_code == 200, read.text
    assert read.json().get("read_at") is not None

    leftover = session.exec(
        select(AppNotification).where(AppNotification.title == f"Signup pending {marker}")
    ).all()
    for row in leftover:
        session.delete(row)
    session.commit()
