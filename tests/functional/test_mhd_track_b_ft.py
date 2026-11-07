"""
FT-IE-* — Track B Inspection functional tests (P4).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session

from app.models.base import ReworkCaseStatus, ReworkStage
from app.models.tables import Inventory, InventoryReworkCase
from tests.mhd_fixtures import (
    admin_headers,  # noqa: F401
    admin_user,  # noqa: F401
    cleanup_project,
    client,  # noqa: F401
    create_project_and_case,
    session,  # noqa: F401
    unique,
    _bootstrap_mhd,  # noqa: F401
)


def _seed_track_b_rework(
    session: Session,
    case,
    *,
    stage: str = ReworkStage.AWAITING_FAULTY_ARRIVAL.value,
) -> InventoryReworkCase:
    inv = Inventory(
        name=unique("TB-INV"),
        inventory_type="unit",
        part_number=case.part_number or unique("PN"),
        quantity=1,
    )
    session.add(inv)
    session.commit()
    session.refresh(inv)

    now = datetime.now(timezone.utc)
    rework = InventoryReworkCase(
        project_id=int(case.project_id),
        target_entity_type=str(case.entity_type or "unit"),
        target_entity_id=int(case.entity_id or 1),
        inventory_id=int(inv.id),
        status=ReworkCaseStatus.OPEN.value,
        stage=stage,
        attempt_count=1,
        opened_at=now,
        opened_by_id=int(case.reported_by) if case.reported_by else None,
        maintenance_case_id=int(case.id),
        investigating_pd_id=int(case.reported_by) if case.reported_by else None,
        created_at=now,
        updated_at=now,
    )
    session.add(rework)
    session.commit()
    session.refresh(rework)
    return rework


def test_ft_ie_001_reception(
    client, admin_headers, session: Session, admin_user
):
    """FT-IE-001 — IM enters reception_date → received."""
    project, case = create_project_and_case(session, admin_user)
    try:
        rework = _seed_track_b_rework(session, case)
        res = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/reception/",
            headers=admin_headers,
            json={},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["stage"] == "received"
        assert body["reception_date"] is not None
    finally:
        cleanup_project(session, project)


def test_ft_ie_002_assign_ie_and_issue(
    client, admin_headers, session: Session, admin_user
):
    """FT-IE-002 — PD assigns IE; IE handover; IM issues → inspection_under_process."""
    project, case = create_project_and_case(session, admin_user)
    try:
        rework = _seed_track_b_rework(
            session, case, stage=ReworkStage.RECEIVED.value
        )
        assign = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/assign-ie/",
            headers=admin_headers,
            json={"ie_user_id": int(admin_user.id)},
        )
        assert assign.status_code == 200, assign.text
        assert assign.json()["stage"] == "ie_assigned"
        assert assign.json()["assigned_ie_id"] == int(admin_user.id)

        hand = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/handover-request/",
            headers=admin_headers,
            json={},
        )
        assert hand.status_code == 200, hand.text
        assert hand.json()["stage"] == "issued_to_ie"

        issue = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/im-issue-to-ie/",
            headers=admin_headers,
            json={},
        )
        assert issue.status_code == 200, issue.text
        assert issue.json()["stage"] == "inspection_under_process"
    finally:
        cleanup_project(session, project)


def test_ft_ie_003_repair_pd_approve(
    client, admin_headers, session: Session, admin_user
):
    """FT-IE-003 — Repairable → repair → PD approve → restocked."""
    project, case = create_project_and_case(session, admin_user)
    try:
        rework = _seed_track_b_rework(
            session,
            case,
            stage=ReworkStage.INSPECTION_UNDER_PROCESS.value,
        )
        disp = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/disposition/",
            headers=admin_headers,
            json={"outcome": "repairable"},
        )
        assert disp.status_code == 200, disp.text
        assert disp.json()["stage"] == "repair_under_progress"

        submit = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/repair-submit/",
            headers=admin_headers,
            json={"notes": "bench pass"},
        )
        assert submit.status_code == 200, submit.text

        decide = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/pd-repair-decision/",
            headers=admin_headers,
            json={"decision": "approve"},
        )
        assert decide.status_code == 200, decide.text
        body = decide.json()
        assert body["stage"] == "restocked"
        assert body["is_track_b_terminal"] is True
    finally:
        cleanup_project(session, project)


def test_ft_ie_005_discard_segregation(
    client, admin_headers, session: Session, admin_user
):
    """FT-IE-005/006 — IE recommend discard; IM trash → Discarded; IE alone does not scrap."""
    project, case = create_project_and_case(session, admin_user)
    try:
        rework = _seed_track_b_rework(
            session,
            case,
            stage=ReworkStage.INSPECTION_UNDER_PROCESS.value,
        )
        disp = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/disposition/",
            headers=admin_headers,
            json={"outcome": "discard"},
        )
        assert disp.status_code == 200, disp.text
        body = disp.json()
        assert body["stage"] == "discard_pending"
        assert body["discarded"] is False
        assert body["status"] == "open"

        confirm = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/confirm-discard/",
            headers=admin_headers,
            json={},
        )
        assert confirm.status_code == 200, confirm.text
        done = confirm.json()
        assert done["stage"] == "discarded"
        assert done["discarded"] is True
        assert done["is_track_b_terminal"] is True

        board = client.get(
            f"/api/maintenance-cases/{case.id}/dual-track/",
            headers=admin_headers,
        )
        assert board.status_code == 200, board.text
        assert board.json()["track_b_discarded"] is True
    finally:
        cleanup_project(session, project)


def test_ft_ie_007_pd_reject_repair(
    client, admin_headers, session: Session, admin_user
):
    """FT-IE-007 — PD rejects repair tests → remains repair_under_progress."""
    project, case = create_project_and_case(session, admin_user)
    try:
        rework = _seed_track_b_rework(
            session,
            case,
            stage=ReworkStage.REPAIR_UNDER_PROGRESS.value,
        )
        decide = client.post(
            f"/api/maintenance-cases/{case.id}/returned-units/{rework.id}/pd-repair-decision/",
            headers=admin_headers,
            json={"decision": "reject", "reject_reason": "AIT fail"},
        )
        assert decide.status_code == 200, decide.text
        body = decide.json()
        assert body["stage"] == "repair_under_progress"
        assert body["status"] == "open"
        assert body["is_track_b_terminal"] is False
    finally:
        cleanup_project(session, project)
