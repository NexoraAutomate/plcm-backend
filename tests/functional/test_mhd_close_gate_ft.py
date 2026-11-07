"""
FT-CG-* — Dual-track close gate & clear RED (P5).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.base import (
    CaseStatus,
    ReplacementRequestStatus,
    ReworkCaseStatus,
    ReworkStage,
)
from app.models.tables import AppNotification, ReplacementRequest
from tests.functional.test_mhd_dual_track_ft import _seed_fault_and_request
from tests.functional.test_mhd_track_b_ft import _seed_track_b_rework
from tests.mhd_fixtures import (
    admin_headers,  # noqa: F401
    admin_user,  # noqa: F401
    cleanup_project,
    client,  # noqa: F401
    create_project_and_case,
    session,  # noqa: F401
    _bootstrap_mhd,  # noqa: F401
)


def test_ft_cg_001_close_blocked_track_a_only_incomplete(
    client, admin_headers, session: Session, admin_user
):
    """FT-CG-001 — Attempt close with only Track A started → blocked."""
    project, case = create_project_and_case(session, admin_user)
    try:
        _seed_fault_and_request(client, admin_headers, int(case.id))
        res = client.put(
            f"/api/maintenance-cases/{case.id}/",
            headers=admin_headers,
            json={"status": "closed", "resolution_notes": "too early"},
        )
        assert res.status_code == 409, res.text
        assert "Track A incomplete" in res.text or "dual-track" in res.text.lower()
    finally:
        cleanup_project(session, project)


def test_ft_cg_002_close_blocked_track_b_only(
    client, admin_headers, session: Session, admin_user
):
    """FT-CG-002 — Track B terminal but Track A incomplete → blocked."""
    project, case = create_project_and_case(session, admin_user)
    try:
        req = _seed_fault_and_request(client, admin_headers, int(case.id))
        rework = _seed_track_b_rework(session, case, stage=ReworkStage.RESTOCKED.value)
        rework.status = ReworkCaseStatus.CLOSED.value
        session.add(rework)
        session.commit()

        res = client.put(
            f"/api/maintenance-cases/{case.id}/",
            headers=admin_headers,
            json={"status": "closed"},
        )
        assert res.status_code == 409, res.text
        assert "Track A incomplete" in res.text
    finally:
        cleanup_project(session, project)


def test_ft_cg_003_both_terminal_closes_with_case_closed_notify(
    client, admin_headers, session: Session, admin_user
):
    """FT-CG-003 — Both terminal → close succeeds; case_closed notify."""
    project, case = create_project_and_case(session, admin_user)
    try:
        req = _seed_fault_and_request(client, admin_headers, int(case.id))
        row = session.get(ReplacementRequest, int(req["id"]))
        assert row
        row.status = ReplacementRequestStatus.PATCH_DELIVERED.value
        row.red_notified_at = datetime.now(timezone.utc)
        session.add(row)
        rework = _seed_track_b_rework(session, case, stage=ReworkStage.DISCARDED.value)
        rework.status = ReworkCaseStatus.CLOSED.value
        session.add(rework)
        session.commit()

        res = client.put(
            f"/api/maintenance-cases/{case.id}/",
            headers=admin_headers,
            json={"status": "closed", "resolution_notes": "dual-track done"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "closed"

        session.expire_all()
        notices = session.exec(
            select(AppNotification).where(
                AppNotification.event_type == "case_closed",
                AppNotification.entity_id == case.id,
            )
        ).all()
        assert notices

        refreshed = session.get(ReplacementRequest, int(req["id"]))
        assert refreshed is not None
        assert refreshed.red_notified_at is None
        assert refreshed.status == ReplacementRequestStatus.TRACK_A_CLOSED.value
    finally:
        cleanup_project(session, project)


def test_ft_cg_004_soft_fix_close_without_dual_track(
    client, admin_headers, session: Session, admin_user
):
    """FT-CG-004 — Soft-fix case closes without dual-track."""
    project, case = create_project_and_case(session, admin_user)
    try:
        onsite = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json={
                "onsite_outcome": "soft_fix",
                "onsite_soft_fix_method": "reboot",
                "resolve_soft_fixed": True,
            },
        )
        assert onsite.status_code == 200, onsite.text

        # Soft path may already resolve; closing should remain allowed (DT-004 / early exit)
        res = client.put(
            f"/api/maintenance-cases/{case.id}/",
            headers=admin_headers,
            json={"status": "closed", "resolution_notes": "soft done"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "closed"
    finally:
        cleanup_project(session, project)


def test_ft_cg_005_clear_red_on_abort(
    client, admin_headers, session: Session, admin_user
):
    """FT-CG-005 / RA-016 — After abort, RED cleared."""
    project, case = create_project_and_case(session, admin_user)
    try:
        req = _seed_fault_and_request(client, admin_headers, int(case.id))
        row = session.get(ReplacementRequest, int(req["id"]))
        assert row
        row.status = ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value
        row.red_notified_at = datetime.now(timezone.utc)
        session.add(row)
        session.commit()

        # Seed a RED notification
        session.add(
            AppNotification(
                user_id=int(admin_user.id),
                event_type="replacement_case_open",
                title="RED",
                message="open",
                priority="high",
                dedupe_key=f"replacement_case_open:{case.id}",
                entity_type="project",
                entity_id=int(project.id),
                project_id=int(project.id),
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

        abort = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/abort/",
            headers=admin_headers,
            json={"reason": "later NFF proven"},
        )
        assert abort.status_code == 200, abort.text
        body = abort.json()
        assert body["status"] == "track_a_closed"
        assert body["abort_reason"] == "later NFF proven"
        assert body["red_notified_at"] is None

        session.expire_all()
        notices = session.exec(
            select(AppNotification).where(
                AppNotification.dedupe_key == f"replacement_case_open:{case.id}",
            )
        ).all()
        assert notices
        assert all(n.read_at is not None for n in notices)
    finally:
        cleanup_project(session, project)


def test_ft_cg_dt004_delivery_close_when_no_dual_track(
    client, admin_headers, session: Session, admin_user
):
    """DT-004 — delivery confirm close allowed when dual-track not applicable."""
    project, case = create_project_and_case(session, admin_user)
    try:
        # No RR — resolve via update then delivery confirm
        resolved = client.put(
            f"/api/maintenance-cases/{case.id}/",
            headers=admin_headers,
            json={"status": "resolved", "resolution_notes": "no dual track"},
        )
        assert resolved.status_code == 200, resolved.text

        delivery = client.post(
            f"/api/maintenance-cases/{case.id}/deliveries/",
            headers=admin_headers,
            json={
                "delivery_type": "re_delivery",
                "received_by": "Site Mgr",
                "notes": "DT-004",
            },
        )
        assert delivery.status_code in (200, 201), delivery.text
        delivery_id = delivery.json()["id"]

        # Force case back to resolved if create already closed it oddly
        session.expire_all()
        case_row = session.get(type(case), int(case.id))
        if case_row and case_row.status != CaseStatus.RESOLVED:
            case_row.status = CaseStatus.RESOLVED
            session.add(case_row)
            session.commit()

        confirm = client.post(
            f"/api/maintenance-deliveries/{delivery_id}/confirm/",
            headers=admin_headers,
            params={"received_by": "Site Mgr"},
        )
        assert confirm.status_code == 200, confirm.text
        session.expire_all()
        closed = session.get(type(case), int(case.id))
        assert closed is not None
        assert closed.status == CaseStatus.CLOSED
    finally:
        cleanup_project(session, project)
