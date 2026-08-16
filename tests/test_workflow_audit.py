"""Spec 13 — immutable workflow audit trail."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app.database import engine
from app.domain.workflow_audit import SYSTEM_ACTOR_ROLE, WorkflowAuditAction
from app.main import app
from app.models.tables import User
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.workflow_audit_service import (
    ensure_system_user,
    list_workflow_audits,
    write_workflow_audit,
)
from app.services.workflow_foundation_seed import ensure_workflow_statuses


ADMIN_USER = "admin"
ADMIN_PASS = "password@82768243"


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    ensure_user_management_schema()
    with Session(engine) as session:
        ensure_workflow_statuses(session)
        ensure_system_user(session)
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


def test_write_workflow_audit_envelope(session: Session, admin_user: User):
    event = write_workflow_audit(
        session,
        action=WorkflowAuditAction.RESERVED,
        entity_type="inventory_reservation",
        entity_id="42",
        actor=admin_user,
        project_id=None,
        old_value={"status": "AVAILABLE"},
        new_value={"status": "RESERVED"},
        remarks="unit test reserve",
    )
    session.commit()
    session.refresh(event)

    assert event.id
    assert event.occurred_at is not None
    assert event.actor_user_id == admin_user.id
    assert event.actor_role == "ADMIN"
    assert event.action == WorkflowAuditAction.RESERVED
    assert event.entity_type == "inventory_reservation"
    assert event.entity_id == "42"
    assert event.old_value == {"status": "AVAILABLE"}
    assert event.new_value == {"status": "RESERVED"}
    assert event.remarks == "unit test reserve"


def test_system_actor_for_jobs(session: Session):
    event = write_workflow_audit(
        session,
        action=WorkflowAuditAction.AUTO_RELEASE_EXPIRY,
        entity_type="inventory_reservation",
        entity_id="99",
        system=True,
        remarks="job",
    )
    session.commit()
    assert event.actor_role == SYSTEM_ACTOR_ROLE
    system = ensure_system_user(session)
    assert event.actor_user_id == system.id


def test_list_filters_by_action_and_entity(session: Session, admin_user: User):
    marker = uuid.uuid4().hex[:8]
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.ISSUED,
        entity_type="inventory_issuance",
        entity_id=marker,
        actor=admin_user,
        remarks="filter-me",
    )
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.RELEASED,
        entity_type="inventory_reservation",
        entity_id=marker,
        actor=admin_user,
    )
    session.commit()
    rows, total = list_workflow_audits(
        session,
        action=WorkflowAuditAction.ISSUED,
        entity_id=marker,
    )
    assert total >= 1
    assert all(row.action == WorkflowAuditAction.ISSUED for row in rows)
    assert all(row.entity_id == marker for row in rows)


def test_audit_rows_are_append_only(session: Session, admin_user: User):
    event = write_workflow_audit(
        session,
        action=WorkflowAuditAction.MODIFIED,
        entity_type="project",
        entity_id="1",
        actor=admin_user,
    )
    session.commit()
    with pytest.raises(Exception):
        session.execute(
            text("UPDATE workflowauditevent SET remarks = 'tamper' WHERE id = :id"),
            {"id": event.id},
        )
        session.commit()
    session.rollback()
    with pytest.raises(Exception):
        session.execute(
            text("DELETE FROM workflowauditevent WHERE id = :id"),
            {"id": event.id},
        )
        session.commit()
    session.rollback()


def test_api_cannot_update_or_delete_audit(client: TestClient, session: Session, admin_user: User):
    event = write_workflow_audit(
        session,
        action=WorkflowAuditAction.PROJECT_CREATED,
        entity_type="project",
        entity_id="7",
        actor=admin_user,
    )
    session.commit()
    headers = _login(client)
    deleted = client.delete(f"/api/audit/{event.id}", headers=headers)
    assert deleted.status_code == 405
    updated = client.put(f"/api/audit/{event.id}", json={}, headers=headers)
    assert updated.status_code == 405
    patched = client.patch(f"/api/audit/{event.id}", json={}, headers=headers)
    assert patched.status_code == 405


def test_admin_can_list_and_filter_audit_api(client: TestClient, session: Session, admin_user: User):
    marker = f"api-{uuid.uuid4().hex[:8]}"
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.HIERARCHY_GENERATED,
        entity_type="project",
        entity_id=marker,
        actor=admin_user,
        remarks="api-list",
        old_value={"status": "APPROVED"},
        new_value={"status": "READY_FOR_INVENTORY"},
    )
    session.commit()
    headers = _login(client)
    res = client.get(
        "/api/audit/",
        headers=headers,
        params={"action": WorkflowAuditAction.HIERARCHY_GENERATED, "entity_id": marker},
    )
    assert res.status_code == 200, res.text
    assert res.headers.get("x-total-count")
    body = res.json()
    assert body
    assert body[0]["action"] == WorkflowAuditAction.HIERARCHY_GENERATED
    assert body[0]["action_label"]
    assert "occurred_at" in body[0]
    assert body[0]["actor_role"] == "ADMIN"

    csv_res = client.get(
        "/api/audit/export.csv",
        headers=headers,
        params={"entity_id": marker},
    )
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers.get("content-type", "")
    assert WorkflowAuditAction.HIERARCHY_GENERATED in csv_res.text
    assert "APPROVED" in csv_res.text
    assert "READY_FOR_INVENTORY" in csv_res.text
    assert "{'status'" not in csv_res.text

    by_actor = client.get(
        "/api/audit/",
        headers=headers,
        params={"actor_user_id": admin_user.id, "entity_id": marker},
    )
    assert by_actor.status_code == 200
    assert by_actor.json()


def test_sample_flow_leaves_ordered_history(session: Session, admin_user: User):
    """Config → draft → approve → generate → reserve leaves reconstructable audits."""
    from app.models.tables import System
    from app.services.inventory_reservation_service import reserve_inventory
    from tests.test_inventory_reservation import (
        _cleanup,
        _ready_project,
        _stock_for_system,
    )

    sys_name = f"Audit-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(
        session, admin_user, flights=1, sdls=1, system_name=sys_name
    )
    inv = _stock_for_system(session, name=sys_name, serials=["SN-AUDIT-1"])
    try:
        target = session.exec(select(System).where(System.project_id == project.id)).first()
        assert target and target.id
        reserve_inventory(
            session,
            int(project.id),
            {
                "target_entity_type": "system",
                "target_entity_id": int(target.id),
                "inventory_id": inv.id,
            },
            actor=admin_user,
        )
        rows, _total = list_workflow_audits(
            session, project_id=int(project.id), skip=0, limit=50
        )
        chronological = list(reversed(rows))
        actions = [row.action for row in chronological]
        required = [
            WorkflowAuditAction.PROJECT_CREATED,
            WorkflowAuditAction.PROJECT_APPROVED,
            WorkflowAuditAction.HIERARCHY_GENERATED,
            WorkflowAuditAction.RESERVED,
        ]
        positions = []
        for code in required:
            assert code in actions, f"missing {code} in {actions}"
            positions.append(actions.index(code))
        assert positions == sorted(positions)
    finally:
        _cleanup(session, project, cfg, inv)
