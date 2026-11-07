"""
System tests for MHD Occurrence + Dual-Track (P0–P6).

ST-01…04 / ST-13: early exits and non-regression.
ST-05…15: full dual-track / Track B / close gate / notify (P6).
ST-16: skipped — Accepted Deviation IE-014 / GAP-08 (never-returned SLA not started).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.models.base import (
    ReplacementRequestStatus,
    ReworkCaseStatus,
    ReworkStage,
)
from app.models.tables import AppNotification, OemWarrantyClaim, ReplacementRequest
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
from tests.mhd_st_helpers import (
    advance_track_a_to_im_issue_pending,
    build_hierarchy_case,
    cleanup_st_fixture,
    close_case,
    complete_ait,
    get_track_b_rework,
    im_issue_replacement,
    seed_request,
    walk_track_a_to_patch_delivered,
    walk_track_b_repair_restock,
    walk_track_b_to_inspection,
)
from tests.functional.test_mhd_dual_track_ft import _seed_fault_and_request
from tests.functional.test_mhd_track_b_ft import _seed_track_b_rework


# ---------------------------------------------------------------------------
# ST-01 … ST-04 — early exits
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# ST-05 — dual-track happy path
# ---------------------------------------------------------------------------


def test_st_05_dual_track_happy_path(client, admin_headers, session: Session, admin_user):
    """ST-05 — Replace + repair restock; both tracks terminal; close; RED cleared."""
    fx = build_hierarchy_case(
        session, admin_user, spare_serials=["SN-ST05-A"], with_faulty_inventory=True
    )
    project, cfg, case = fx["project"], fx["cfg"], fx["case"]
    try:
        req = seed_request(client, admin_headers, int(case.id))
        ait = walk_track_a_to_patch_delivered(
            client,
            admin_headers,
            case_id=int(case.id),
            request_id=int(req["id"]),
            me_id=int(fx["me"].id),
            inventory_id=int(fx["spare_inv"].id),
            serial_number="SN-ST05-A",
            target_entity_id=int(fx["system"].id),
        )
        assert ait["status"] == "patch_delivered"

        board = client.get(
            f"/api/maintenance-cases/{case.id}/dual-track/",
            headers=admin_headers,
        ).json()
        assert board["track_a_status"] == "patch_delivered"

        tb = walk_track_b_repair_restock(
            client,
            admin_headers,
            session,
            case_id=int(case.id),
            ie_user_id=int(admin_user.id),
        )
        assert tb["stage"] == "restocked"

        closed = close_case(client, admin_headers, case_id=int(case.id))
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"

        session.expire_all()
        refreshed = session.get(ReplacementRequest, int(req["id"]))
        assert refreshed is not None
        assert refreshed.red_notified_at is None
        assert refreshed.status == ReplacementRequestStatus.TRACK_A_CLOSED.value
    finally:
        cleanup_st_fixture(
            session,
            project=project,
            cfg=cfg,
            inventories=[fx.get("spare_inv"), fx.get("faulty_inv")],
        )


# ---------------------------------------------------------------------------
# ST-06 — AIT reject loop
# ---------------------------------------------------------------------------


def test_st_06_ait_reject_loop_then_pass(
    client, admin_headers, session: Session, admin_user
):
    """ST-06 — AIT reject → re-issue second S/N → approve; first quarantined."""
    fx = build_hierarchy_case(
        session,
        admin_user,
        spare_serials=["SN-ST06-1", "SN-ST06-2"],
        with_faulty_inventory=True,
    )
    project, cfg, case = fx["project"], fx["cfg"], fx["case"]
    try:
        req = seed_request(client, admin_headers, int(case.id))
        advance_track_a_to_im_issue_pending(
            client,
            admin_headers,
            case_id=int(case.id),
            request_id=int(req["id"]),
            me_id=int(fx["me"].id),
            inventory_id=int(fx["spare_inv"].id),
            serial_number="SN-ST06-1",
            target_entity_id=int(fx["system"].id),
        )
        first = im_issue_replacement(
            client, admin_headers, case_id=int(case.id), request_id=int(req["id"])
        )
        assert first.status_code == 200, first.text
        first_instance = first.json().get("issued_instance_id")

        rejected = complete_ait(
            client,
            admin_headers,
            case_id=int(case.id),
            request_id=int(req["id"]),
            decision="reject",
            reject_reason="bench fail",
        )
        assert rejected["status"] == "im_issue_pending"
        assert rejected.get("quarantined_instance_id") == first_instance

        # Reserve second spare then re-issue
        reserve2 = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/reserve/",
            headers=admin_headers,
            json={
                "inventory_id": int(fx["spare_inv"].id),
                "serial_number": "SN-ST06-2",
                "target_entity_type": "system",
                "target_entity_id": int(fx["system"].id),
            },
        )
        assert reserve2.status_code == 200, reserve2.text

        second = im_issue_replacement(
            client, admin_headers, case_id=int(case.id), request_id=int(req["id"])
        )
        assert second.status_code == 200, second.text
        assert second.json()["issued_serial"] == "SN-ST06-2"

        approved = complete_ait(
            client,
            admin_headers,
            case_id=int(case.id),
            request_id=int(req["id"]),
            decision="approve",
        )
        assert approved["status"] == "patch_delivered"
    finally:
        cleanup_st_fixture(
            session,
            project=project,
            cfg=cfg,
            inventories=[fx.get("spare_inv"), fx.get("faulty_inv")],
        )


# ---------------------------------------------------------------------------
# ST-07 — Track B warranty
# ---------------------------------------------------------------------------


def test_st_07_track_b_warranty(client, admin_headers, session: Session, admin_user):
    """ST-07 — IE warranty → OEM claim closed → Track B terminal."""
    fx = build_hierarchy_case(
        session,
        admin_user,
        spare_serials=["SN-ST07-A"],
        with_faulty_inventory=True,
        warranty_days=365,
    )
    project, cfg, case = fx["project"], fx["cfg"], fx["case"]
    try:
        req = seed_request(client, admin_headers, int(case.id))
        walk_track_a_to_patch_delivered(
            client,
            admin_headers,
            case_id=int(case.id),
            request_id=int(req["id"]),
            me_id=int(fx["me"].id),
            inventory_id=int(fx["spare_inv"].id),
            serial_number="SN-ST07-A",
            target_entity_id=int(fx["system"].id),
        )
        session.expire_all()
        rework = get_track_b_rework(session, int(case.id))
        assert rework is not None
        walk_track_b_to_inspection(
            client,
            admin_headers,
            case_id=int(case.id),
            rework_id=int(rework.id),
            ie_user_id=int(admin_user.id),
        )
        disp = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/disposition/",
            headers=admin_headers,
            json={"outcome": "warranty"},
        )
        assert disp.status_code == 200, disp.text
        assert disp.json()["stage"] == "warranty_claim"

        session.expire_all()
        claim = session.exec(
            select(OemWarrantyClaim).where(
                OemWarrantyClaim.rework_case_id == rework.id
            )
        ).first()
        assert claim is not None

        upd = client.put(
            f"/api/oem-warranty-claims/{claim.id}/",
            headers=admin_headers,
            json={"status": "closed"},
        )
        assert upd.status_code == 200, upd.text

        session.expire_all()
        rework2 = get_track_b_rework(session, int(case.id))
        assert rework2 is not None
        assert rework2.stage == ReworkStage.CLAIM_CLOSED.value
        assert rework2.status == ReworkCaseStatus.CLOSED.value

        closed = close_case(client, admin_headers, case_id=int(case.id))
        assert closed.status_code == 200, closed.text
    finally:
        cleanup_st_fixture(
            session,
            project=project,
            cfg=cfg,
            inventories=[fx.get("spare_inv"), fx.get("faulty_inv")],
        )


# ---------------------------------------------------------------------------
# ST-08 — Track B discard
# ---------------------------------------------------------------------------


def test_st_08_track_b_discard(client, admin_headers, session: Session, admin_user):
    """ST-08 — Discard path; Discarded badge; Track B terminal."""
    fx = build_hierarchy_case(
        session, admin_user, spare_serials=["SN-ST08-A"], with_faulty_inventory=True
    )
    project, cfg, case = fx["project"], fx["cfg"], fx["case"]
    try:
        req = seed_request(client, admin_headers, int(case.id))
        walk_track_a_to_patch_delivered(
            client,
            admin_headers,
            case_id=int(case.id),
            request_id=int(req["id"]),
            me_id=int(fx["me"].id),
            inventory_id=int(fx["spare_inv"].id),
            serial_number="SN-ST08-A",
            target_entity_id=int(fx["system"].id),
        )
        session.expire_all()
        rework = get_track_b_rework(session, int(case.id))
        assert rework is not None
        walk_track_b_to_inspection(
            client,
            admin_headers,
            case_id=int(case.id),
            rework_id=int(rework.id),
            ie_user_id=int(admin_user.id),
        )
        disp = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/disposition/",
            headers=admin_headers,
            json={"outcome": "discard"},
        )
        assert disp.status_code == 200, disp.text
        assert disp.json()["stage"] == "discard_pending"
        assert disp.json()["discarded"] is False

        confirm = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/confirm-discard/",
            headers=admin_headers,
            json={},
        )
        assert confirm.status_code == 200, confirm.text
        assert confirm.json()["discarded"] is True
        assert confirm.json()["is_track_b_terminal"] is True

        board = client.get(
            f"/api/maintenance-cases/{case.id}/dual-track/",
            headers=admin_headers,
        ).json()
        assert board.get("track_b_discarded") is True
    finally:
        cleanup_st_fixture(
            session,
            project=project,
            cfg=cfg,
            inventories=[fx.get("spare_inv"), fx.get("faulty_inv")],
        )


# ---------------------------------------------------------------------------
# ST-09 — close gate
# ---------------------------------------------------------------------------


def test_st_09_close_gate_enforcement(
    client, admin_headers, session: Session, admin_user
):
    """ST-09 — Partial close blocked; both tracks terminal → close OK."""
    # Track A only incomplete
    p1, c1 = create_project_and_case(session, admin_user)
    try:
        _seed_fault_and_request(client, admin_headers, int(c1.id))
        blocked_a = close_case(client, admin_headers, case_id=int(c1.id))
        assert blocked_a.status_code == 409, blocked_a.text
    finally:
        cleanup_project(session, p1)

    # Track B terminal, Track A incomplete
    p2, c2 = create_project_and_case(session, admin_user)
    try:
        _seed_fault_and_request(client, admin_headers, int(c2.id))
        rework = _seed_track_b_rework(session, c2, stage=ReworkStage.RESTOCKED.value)
        rework.status = ReworkCaseStatus.CLOSED.value
        session.add(rework)
        session.commit()
        blocked_b = close_case(client, admin_headers, case_id=int(c2.id))
        assert blocked_b.status_code == 409, blocked_b.text
    finally:
        cleanup_project(session, p2)

    # Both terminal
    p3, c3 = create_project_and_case(session, admin_user)
    try:
        req = _seed_fault_and_request(client, admin_headers, int(c3.id))
        row = session.get(ReplacementRequest, int(req["id"]))
        assert row
        row.status = ReplacementRequestStatus.PATCH_DELIVERED.value
        session.add(row)
        rework = _seed_track_b_rework(session, c3, stage=ReworkStage.DISCARDED.value)
        rework.status = ReworkCaseStatus.CLOSED.value
        session.add(rework)
        session.commit()
        ok = close_case(client, admin_headers, case_id=int(c3.id))
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "closed"
    finally:
        cleanup_project(session, p3)


# ---------------------------------------------------------------------------
# ST-10 — stock shortage
# ---------------------------------------------------------------------------


def test_st_10_stock_shortage(client, admin_headers, session: Session, admin_user):
    """ST-10 — No matching stock → no fake issue / no RED from ghost issue."""
    fx = build_hierarchy_case(
        session, admin_user, spare_serials=None, with_faulty_inventory=False
    )
    project, cfg, case = fx["project"], fx["cfg"], fx["case"]
    try:
        req = seed_request(client, admin_headers, int(case.id))
        me = fx["me"]
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

        # Reserve without stock → fail
        reserve = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/reserve/",
            headers=admin_headers,
            json={
                "target_entity_type": "system",
                "target_entity_id": int(fx["system"].id),
                "part_number": fx["part_number"],
            },
        )
        assert reserve.status_code == 400, reserve.text

        # ME request-issue without reservation → blocked
        blocked = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/{req['id']}/request-issue/",
            headers=admin_headers,
        )
        assert blocked.status_code == 400, blocked.text

        board = client.get(
            f"/api/maintenance-cases/{case.id}/dual-track/",
            headers=admin_headers,
        ).json()
        assert board["track_a_status"] == "pd_approved"
        assert board.get("track_a", {}).get("red_notified_at") in (None, "")
    finally:
        cleanup_st_fixture(session, project=project, cfg=cfg, inventories=[])


# ---------------------------------------------------------------------------
# ST-11 — PD reject pre-issue
# ---------------------------------------------------------------------------


def test_st_11_pd_reject_pre_issue(
    client, admin_headers, session: Session, admin_user
):
    """ST-11 — PD reject; no inventory movement; no RED."""
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
        assert body.get("red_notified_at") in (None, "")

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


# ---------------------------------------------------------------------------
# ST-12 — segregation of duties discard
# ---------------------------------------------------------------------------


def test_st_12_segregation_of_duties_discard(
    client, admin_headers, session: Session, admin_user
):
    """ST-12 — IE recommend discard does not scrap; IM confirm required."""
    project, case = create_project_and_case(session, admin_user)
    try:
        rework = _seed_track_b_rework(
            session, case, stage=ReworkStage.INSPECTION_UNDER_PROCESS.value
        )
        disp = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/disposition/",
            headers=admin_headers,
            json={"outcome": "discard"},
        )
        assert disp.status_code == 200, disp.text
        assert disp.json()["stage"] == "discard_pending"
        assert disp.json()["discarded"] is False
        assert disp.json()["status"] == "open"

        confirm = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/confirm-discard/",
            headers=admin_headers,
            json={},
        )
        assert confirm.status_code == 200, confirm.text
        assert confirm.json()["discarded"] is True
        assert confirm.json()["stage"] == "discarded"
    finally:
        cleanup_project(session, project)


# ---------------------------------------------------------------------------
# ST-13 — non-regression
# ---------------------------------------------------------------------------


def test_st_13_non_regression_soft_fix_and_fault_path(
    client, admin_headers, session: Session, admin_user
):
    """ST-13 — Soft fix path + fault→request path both work."""
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


# ---------------------------------------------------------------------------
# ST-14 — notification & badge sweep
# ---------------------------------------------------------------------------


def test_st_14_notification_badge_sweep(
    client, admin_headers, session: Session, admin_user
):
    """ST-14 — Key FSD §7 events + RED visibility on dual-track walk."""
    fx = build_hierarchy_case(
        session, admin_user, spare_serials=["SN-ST14-A"], with_faulty_inventory=True
    )
    project, cfg, case = fx["project"], fx["cfg"], fx["case"]
    try:
        req = seed_request(client, admin_headers, int(case.id))
        walk_track_a_to_patch_delivered(
            client,
            admin_headers,
            case_id=int(case.id),
            request_id=int(req["id"]),
            me_id=int(fx["me"].id),
            inventory_id=int(fx["spare_inv"].id),
            serial_number="SN-ST14-A",
            target_entity_id=int(fx["system"].id),
        )
        walk_track_b_repair_restock(
            client,
            admin_headers,
            session,
            case_id=int(case.id),
            ie_user_id=int(admin_user.id),
        )
        closed = close_case(client, admin_headers, case_id=int(case.id))
        assert closed.status_code == 200, closed.text

        session.expire_all()
        expected_events = {
            "replacement_requested",
            "replacement_approved",
            "replacement_issue_requested",
            "replacement_shipped",
            "replacement_case_open",
            "case_closed",
        }
        notices = session.exec(
            select(AppNotification).where(AppNotification.entity_id == case.id)
        ).all()
        # RED notify may be entity_type=project
        project_notices = session.exec(
            select(AppNotification).where(
                AppNotification.dedupe_key == f"replacement_case_open:{case.id}"
            )
        ).all()
        event_types = {n.event_type for n in notices} | {
            n.event_type for n in project_notices
        }
        missing = expected_events - event_types
        assert not missing, f"Missing notify events: {missing}; got {event_types}"

        board = client.get(
            f"/api/maintenance-cases/{case.id}/dual-track/",
            headers=admin_headers,
        ).json()
        # After close, Track A closed / RED cleared
        assert board.get("track_a_status") in (
            "track_a_closed",
            "patch_delivered",
        )
    finally:
        cleanup_st_fixture(
            session,
            project=project,
            cfg=cfg,
            inventories=[fx.get("spare_inv"), fx.get("faulty_inv")],
        )


# ---------------------------------------------------------------------------
# ST-15 — abort Track A
# ---------------------------------------------------------------------------


def test_st_15_abort_track_a(client, admin_headers, session: Session, admin_user):
    """ST-15 — Abort Track A; RED cleared; audit retained."""
    project, case = create_project_and_case(session, admin_user)
    try:
        req = _seed_fault_and_request(client, admin_headers, int(case.id))
        row = session.get(ReplacementRequest, int(req["id"]))
        assert row
        row.status = ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value
        row.red_notified_at = datetime.now(timezone.utc)
        session.add(row)
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


# ---------------------------------------------------------------------------
# ST-16 — optional / Accepted Deviation
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="Accepted Deviation IE-014 / GAP-08 — never-returned SLA not started")
def test_st_16_faulty_never_returned_sla():
    """ST-16 — Optional; deferred backlog."""
