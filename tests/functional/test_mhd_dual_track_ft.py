"""
FT-DT-* — Dual-track board & ReplacementRequest functional tests (P2).
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.models.tables import AppNotification, Role, User
from app.auth import hash_password
from datetime import datetime, timezone
import uuid

from tests.mhd_fixtures import (
    admin_headers,  # noqa: F401
    admin_user,  # noqa: F401
    cleanup_project,
    client,  # noqa: F401
    create_project_and_case,
    fault_identified_payload,
    session,  # noqa: F401
    _bootstrap_mhd,  # noqa: F401
)


def _ensure_me_user(session: Session) -> User:
    role = session.exec(select(Role).where(Role.name == "MaintenanceEngineer")).first()
    if not role:
        # fall back to Admin-capable user for assign-me id existence
        admin = session.exec(select(User).where(User.username == "admin")).first()
        assert admin
        return admin
    existing = session.exec(
        select(User).where(User.username == "demo-me")
    ).first()
    if existing:
        return existing
    username = f"me_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name="FT ME",
        is_active=True,
        password=hash_password("Demo@me123"),
        updated_at=datetime.now(timezone.utc),
    )
    user.roles = [role]
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _seed_fault_and_request(client, admin_headers, case_id: int) -> dict:
    res = client.post(
        f"/api/maintenance-cases/{case_id}/onsite-outcome/",
        headers=admin_headers,
        json=fault_identified_payload(),
    )
    assert res.status_code == 200, res.text
    rr = client.post(
        f"/api/maintenance-cases/{case_id}/replacement-requests/",
        headers=admin_headers,
        json={},
    )
    assert rr.status_code == 200, rr.text
    return rr.json()


def test_ft_dt_001_dual_track_board_after_request(
    client, admin_headers, session: Session, admin_user
):
    """FT-DT-001 — Dual-track board shows Track A started; Track B idle/awaiting."""
    project, case = create_project_and_case(session, admin_user)
    try:
        _seed_fault_and_request(client, admin_headers, int(case.id))
        board = client.get(
            f"/api/maintenance-cases/{case.id}/dual-track/",
            headers=admin_headers,
        )
        assert board.status_code == 200, board.text
        data = board.json()
        assert data["track_a_status"] == "replacement_requested"
        assert data["track_a"] is not None
        assert data["track_b_status"] in ("idle", "awaiting_faulty_arrival")
    finally:
        cleanup_project(session, project)


def test_ft_dt_002_create_request_notifies_pd(
    client, admin_headers, session: Session, admin_user
):
    """FT-DT-002 — Create Replacement Request → replacement_requested; PD notified high."""
    project, case = create_project_and_case(session, admin_user)
    try:
        req = _seed_fault_and_request(client, admin_headers, int(case.id))
        assert req["status"] == "replacement_requested"
        session.expire_all()
        notices = session.exec(
            select(AppNotification).where(
                AppNotification.event_type == "replacement_requested",
                AppNotification.entity_id == case.id,
            )
        ).all()
        assert notices
        assert any(n.priority == "high" for n in notices)
    finally:
        cleanup_project(session, project)


def test_ft_dt_003_hm_assigns_me(
    client, admin_headers, session: Session, admin_user
):
    """FT-DT-003 — HM assigns ME (reserve covered by UT-RA-002; API assign verified here)."""
    project, case = create_project_and_case(session, admin_user)
    me = _ensure_me_user(session)
    try:
        req = _seed_fault_and_request(client, admin_headers, int(case.id))
        assign = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/assign-me/",
            headers=admin_headers,
            json={"assigned_me_id": int(me.id)},
        )
        assert assign.status_code == 200, assign.text
        assert assign.json()["assigned_me_id"] == int(me.id)
    finally:
        cleanup_project(session, project)


def test_ft_dt_004_track_a_without_faulty_reception(
    client, admin_headers, session: Session, admin_user
):
    """FT-DT-004 — Track A advances (PD approve) without requiring faulty reception."""
    project, case = create_project_and_case(session, admin_user)
    try:
        req = _seed_fault_and_request(client, admin_headers, int(case.id))
        decide = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/pd-decision/",
            headers=admin_headers,
            json={"decision": "approve"},
        )
        assert decide.status_code == 200, decide.text
        body = decide.json()
        assert body["status"] == "im_issue_pending"
        assert body["pd_decision"] == "approve"
        board = client.get(
            f"/api/maintenance-cases/{case.id}/dual-track/",
            headers=admin_headers,
        )
        assert board.status_code == 200
        data = board.json()
        assert data["track_a_status"] == "im_issue_pending"
        # Track B may be awaiting if rework could be created; else idle is acceptable
        # when no inventory match exists for the case entity (NR-003 retained).
        assert data["track_b_status"] in ("awaiting_faulty_arrival", "idle")
    finally:
        cleanup_project(session, project)
