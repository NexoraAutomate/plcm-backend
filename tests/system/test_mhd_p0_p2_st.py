"""
System tests for MHD P0–P2 early-exit and non-regression scenarios.

ST-05+ (full dual-track happy path, AIT, IE, close gate) require P3–P5 — marked skip.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from tests.mhd_fixtures import (
    admin_headers,  # noqa: F401
    admin_user,  # noqa: F401
    cleanup_project,
    client,  # noqa: F401
    create_project_and_case,
    add_faulty_entity,
    fault_identified_payload,
    occurrence_payload,
    session,  # noqa: F401
    _bootstrap_mhd,  # noqa: F401
)


def test_st_01_soft_fix_early_exit(client, admin_headers, session: Session, admin_user):
    """ST-01 — Soft fix early exit; no Replacement Request; no Track B."""
    project, case = create_project_and_case(session, admin_user)
    add_faulty_entity(session, case, actor_id=int(admin_user.id))
    try:
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(
                onsite_outcome="soft_fix",
                onsite_soft_fix_method="reboot",
                resolve_soft_fixed=True,
            ),
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "resolved"
        assert res.json()["onsite_outcome"] == "soft_fix"
        board = client.get(
            f"/api/maintenance-cases/{case.id}/dual-track/",
            headers=admin_headers,
        ).json()
        assert board.get("track_a") is None
        assert board.get("track_b_status") in (None, "idle")
        blocked = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/",
            headers=admin_headers,
            json={},
        )
        assert blocked.status_code == 400
    finally:
        cleanup_project(session, project)


def test_st_02_nff_confirm_close(client, admin_headers, session: Session, admin_user):
    """ST-02 — NFF confirm Yes → closed; dual-track not started."""
    project, case = create_project_and_case(session, admin_user)
    add_faulty_entity(session, case, actor_id=int(admin_user.id))
    try:
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(
                onsite_outcome="no_fault_found",
                confirm_close_nff=True,
            ),
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "closed"
        board = client.get(
            f"/api/maintenance-cases/{case.id}/dual-track/",
            headers=admin_headers,
        ).json()
        assert board.get("track_a") is None
    finally:
        cleanup_project(session, project)


def test_st_03_nff_keep_open(client, admin_headers, session: Session, admin_user):
    """ST-03 — NFF confirm No → case open with note."""
    project, case = create_project_and_case(session, admin_user)
    try:
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(
                onsite_outcome="no_fault_found",
                confirm_close_nff=False,
                notes="customer still concerned",
            ),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "open"
        assert "customer still concerned" in (body.get("onsite_notes") or "")
    finally:
        cleanup_project(session, project)


def test_st_04_inconclusive(client, admin_headers, session: Session, admin_user):
    """ST-04 — Inconclusive → open; no Track A CTA success."""
    project, case = create_project_and_case(session, admin_user)
    try:
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(onsite_outcome="inconclusive"),
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "open"
        rr = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/",
            headers=admin_headers,
            json={},
        )
        assert rr.status_code == 400
    finally:
        cleanup_project(session, project)


def test_st_13_non_regression_soft_fix_and_fault_path(
    client, admin_headers, session: Session, admin_user
):
    """ST-13 — Soft fix path + fault→request path both work (P0–P2 NR)."""
    # Soft fix
    p1, c1 = create_project_and_case(session, admin_user)
    add_faulty_entity(session, c1, actor_id=int(admin_user.id))
    try:
        soft = client.post(
            f"/api/maintenance-cases/{c1.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(
                onsite_outcome="soft_fix",
                onsite_soft_fix_method="reboot",
                resolve_soft_fixed=True,
            ),
        )
        assert soft.status_code == 200, soft.text
        assert soft.json()["status"] == "resolved"
    finally:
        cleanup_project(session, p1)

    # Fault → replacement request (legacy create_returned_unit_rework retained on approve)
    p2, c2 = create_project_and_case(session, admin_user)
    try:
        fault = client.post(
            f"/api/maintenance-cases/{c2.id}/onsite-outcome/",
            headers=admin_headers,
            json=fault_identified_payload(),
        )
        assert fault.status_code == 200, fault.text
        rr = client.post(
            f"/api/maintenance-cases/{c2.id}/replacement-requests/",
            headers=admin_headers,
            json={},
        )
        assert rr.status_code == 200, rr.text
        decide = client.post(
            f"/api/maintenance-cases/{c2.id}/replacement-requests/{rr.json()['id']}/pd-decision/",
            headers=admin_headers,
            json={"decision": "approve"},
        )
        assert decide.status_code == 200, decide.text
        assert decide.json()["status"] == "pd_approved"
    finally:
        cleanup_project(session, p2)


@pytest.mark.skip(reason="Requires P3–P5 (IM issue, AIT, IE, close gate)")
def test_st_05_dual_track_happy_path_blocked_until_p5():
    """ST-05 — Full dual-track happy path (deferred)."""


@pytest.mark.skip(reason="Requires P3")
def test_st_06_to_st_12_deferred_p3_p5():
    """ST-06…ST-12 — Deferred until later phases."""


@pytest.mark.skip(reason="Requires P5 notification/badge matrix")
def test_st_14_notification_badge_sweep_deferred():
    """ST-14 — Deferred."""
