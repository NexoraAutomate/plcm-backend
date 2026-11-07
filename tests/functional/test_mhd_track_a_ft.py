"""
FT-RA-* — Track A Replacement / AIT functional tests (P3).
"""

from __future__ import annotations

from sqlmodel import Session

from tests.functional.test_mhd_dual_track_ft import (
    _ensure_me_user,
    _seed_fault_and_request,
)
from tests.mhd_fixtures import (
    admin_headers,  # noqa: F401
    admin_user,  # noqa: F401
    cleanup_project,
    client,  # noqa: F401
    create_project_and_case,
    session,  # noqa: F401
    _bootstrap_mhd,  # noqa: F401
)


def test_ft_ra_001_pd_rejects_request(
    client, admin_headers, session: Session, admin_user
):
    """FT-RA-001 — PD rejects request; cannot proceed to issue."""
    project, case = create_project_and_case(session, admin_user)
    try:
        req = _seed_fault_and_request(client, admin_headers, int(case.id))
        decide = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/pd-decision/",
            headers=admin_headers,
            json={"decision": "reject", "reject_reason": "wrong PN"},
        )
        assert decide.status_code == 200, decide.text
        body = decide.json()
        assert body["status"] == "pd_rejected"
        assert body["reject_reason"] == "wrong PN"

        issue = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/request-issue/",
            headers=admin_headers,
        )
        assert issue.status_code == 409, issue.text

        im = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/im-issue/",
            headers=admin_headers,
            json={"signature_type": "HARD_COPY", "signature_payload": "ACK"},
        )
        assert im.status_code == 409, im.text
    finally:
        cleanup_project(session, project)


def test_ft_ra_002_pd_approve_then_me_request_issue(
    client, admin_headers, session: Session, admin_user
):
    """FT-RA-002 — PD approve → pd_approved; ME request-issue needs reservation."""
    project, case = create_project_and_case(session, admin_user)
    try:
        req = _seed_fault_and_request(client, admin_headers, int(case.id))
        me = _ensure_me_user(session)
        assign = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/assign-me/",
            headers=admin_headers,
            json={"assigned_me_id": int(me.id)},
        )
        assert assign.status_code == 200, assign.text

        decide = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/pd-decision/",
            headers=admin_headers,
            json={"decision": "approve"},
        )
        assert decide.status_code == 200, decide.text
        assert decide.json()["status"] == "pd_approved"

        # Without reservation → blocked (RA-005 gate)
        blocked = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/request-issue/",
            headers=admin_headers,
        )
        assert blocked.status_code == 400, blocked.text
    finally:
        cleanup_project(session, project)


def test_ft_ra_ait_upload_and_pd_gate_guards(
    client, admin_headers, session: Session, admin_user
):
    """FT-RA-005/006 guards — AIT endpoints reject wrong status."""
    project, case = create_project_and_case(session, admin_user)
    try:
        req = _seed_fault_and_request(client, admin_headers, int(case.id))
        start = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/ait/start/",
            headers=admin_headers,
        )
        assert start.status_code == 409, start.text

        attach = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/ait/attachments/",
            headers=admin_headers,
            json={"display_name": "AIT", "file_id": 1},
        )
        assert attach.status_code == 409, attach.text

        ait_pd = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/ait/pd-decision/",
            headers=admin_headers,
            json={"decision": "approve"},
        )
        assert ait_pd.status_code == 409, ait_pd.text
    finally:
        cleanup_project(session, project)
