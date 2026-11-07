"""
FT-OR-* — Occurrence Report functional API (+ UI label source check) for P1.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.models.tables import AppNotification, MaintenanceOccurrenceOfficer
from tests.mhd_fixtures import (
    FRONTEND_FIELD_PANEL,
    add_faulty_entity,
    admin_headers,  # noqa: F401
    admin_user,  # noqa: F401
    cleanup_project,
    client,  # noqa: F401
    create_project_and_case,
    fault_identified_payload,
    occurrence_payload,
    session,  # noqa: F401
    _bootstrap_mhd,  # noqa: F401
)


def test_ft_or_001_ui_labels_occurrence_report():
    """FT-OR-001 — Panel titled Occurrence Report; Record Occurrence Report button."""
    assert FRONTEND_FIELD_PANEL.exists(), f"Missing UI file: {FRONTEND_FIELD_PANEL}"
    text = FRONTEND_FIELD_PANEL.read_text(encoding="utf-8")
    assert "Occurrence Report" in text
    assert "Record Occurrence Report" in text


def test_ft_or_002_occurrence_date_and_recorded_by(
    client, admin_headers, session: Session, admin_user
):
    """FT-OR-002 — occurrence_date saved; recorded_at ≈ now; recorded_by = actor."""
    project, case = create_project_and_case(session, admin_user)
    try:
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(
                onsite_outcome="inconclusive",
                occurrence_date="2026-01-10T00:00:00Z",
            ),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        # User calendar day may serialize with offset; accept UTC/local day boundary.
        occ = body.get("occurrence_date") or ""
        assert "2026-01-09" in occ or "2026-01-10" in occ
        assert body.get("onsite_recorded_at")
        assert body.get("onsite_recorded_by_id") == admin_user.id
        assert body.get("onsite_recorded_at") != body.get("occurrence_date")
    finally:
        cleanup_project(session, project)


def test_ft_or_003_soft_fix_resolves(client, admin_headers, session: Session, admin_user):
    """FT-OR-003 — Soft fix + method → soft_fixed; no Track A CTA state (no request)."""
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
                notes="rebooted OK",
            ),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["onsite_outcome"] == "soft_fix"
        assert body["status"] == "resolved"
        board = client.get(
            f"/api/maintenance-cases/{case.id}/dual-track/",
            headers=admin_headers,
        )
        assert board.status_code == 200
        assert board.json().get("track_a") is None
    finally:
        cleanup_project(session, project)


def test_ft_or_004_nff_confirm_closes(client, admin_headers, session: Session, admin_user):
    """FT-OR-004 — NFF → Yes on modal → resolved/closed as NFF."""
    project, case = create_project_and_case(session, admin_user)
    add_faulty_entity(session, case, actor_id=int(admin_user.id))
    try:
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(
                onsite_outcome="no_fault_found",
                confirm_close_nff=True,
                notes="NFF confirm yes",
            ),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["onsite_outcome"] == "no_fault_found"
        assert body["status"] == "closed"
    finally:
        cleanup_project(session, project)


def test_ft_or_005_nff_keep_open(client, admin_headers, session: Session, admin_user):
    """FT-OR-005 — NFF → No on modal → case open; note visible."""
    project, case = create_project_and_case(session, admin_user)
    try:
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(
                onsite_outcome="no_fault_found",
                confirm_close_nff=False,
                notes="NFF keep open",
            ),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "open"
        assert body["onsite_outcome"] == "no_fault_found"
        assert "NFF keep open" in (body.get("onsite_notes") or "")
    finally:
        cleanup_project(session, project)


def test_ft_or_006_inconclusive_stays_open(client, admin_headers, session: Session, admin_user):
    """FT-OR-006 — Inconclusive → case open; no replacement request."""
    project, case = create_project_and_case(session, admin_user)
    try:
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(onsite_outcome="inconclusive"),
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "open"
        create_rr = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/",
            headers=admin_headers,
            json={},
        )
        assert create_rr.status_code == 400
    finally:
        cleanup_project(session, project)


def test_ft_or_007_fault_enables_replacement_cta(
    client, admin_headers, session: Session, admin_user
):
    """FT-OR-007 — Fault + type + channel → CTA Create Replacement Request works."""
    project, case = create_project_and_case(session, admin_user)
    try:
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=fault_identified_payload(),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["onsite_outcome"] == "fault_identified"
        assert body.get("occurrence_fault_type") == "hardware"
        assert body.get("confirmation_channel") == "email"
        # UI CTA wiring present
        ui = FRONTEND_FIELD_PANEL.read_text(encoding="utf-8")
        assert "Request immediate replacement" in ui
        rr = client.post(
            f"/api/maintenance-cases/{case.id}/replacement-requests/",
            headers=admin_headers,
            json={},
        )
        assert rr.status_code == 200, rr.text
        assert rr.json()["status"] == "replacement_requested"
    finally:
        cleanup_project(session, project)


def test_ft_or_008_009_named_attachments(client, admin_headers, session: Session, admin_user):
    """FT-OR-008/009 — Named attachment accepted; missing display_name rejected."""
    project, case = create_project_and_case(session, admin_user)
    try:
        bad = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(
                onsite_outcome="inconclusive",
                attachments=[{"file_id": 1}],
            ),
        )
        assert bad.status_code in (400, 422), bad.text

        ok = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(
                onsite_outcome="inconclusive",
                attachments=[{"display_name": "Photo A", "file_id": None}],
            ),
        )
        assert ok.status_code == 200, ok.text
        atts = ok.json().get("occurrence_attachments") or []
        assert any(a.get("display_name") == "Photo A" for a in atts)
    finally:
        cleanup_project(session, project)


def test_ft_or_010_officers_persisted(client, admin_headers, session: Session, admin_user):
    """FT-OR-010 — FSE officer + guest observer persisted after reload."""
    project, case = create_project_and_case(session, admin_user)
    try:
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(
                onsite_outcome="inconclusive",
                officers=[
                    {
                        "guest_name": "Guest Observer",
                        "role_onsite": "observer",
                        "contact": "g@example.com",
                    },
                    {"user_id": int(admin_user.id), "role_onsite": "FSE"},
                ],
            ),
        )
        assert res.status_code == 200, res.text
        officers = res.json().get("occurrence_officers") or []
        assert len(officers) >= 2
        # reload case
        get_res = client.get(
            f"/api/maintenance-cases/{case.id}/",
            headers=admin_headers,
        )
        assert get_res.status_code == 200, get_res.text
        reloaded = get_res.json().get("occurrence_officers") or []
        assert len(reloaded) >= 2
        roles = {o.get("role_onsite") for o in reloaded}
        assert "FSE" in roles
        assert "observer" in roles
        # DB row check
        rows = session.exec(
            select(MaintenanceOccurrenceOfficer).where(
                MaintenanceOccurrenceOfficer.case_id == case.id
            )
        ).all()
        assert len(rows) >= 2
    finally:
        cleanup_project(session, project)


def test_ft_or_011_investigation_tree_usable_after_fault(
    client, admin_headers, session: Session, admin_user
):
    """FT-OR-011 — After fault, case remains open for investigation (tree parallel)."""
    project, case = create_project_and_case(session, admin_user)
    try:
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=fault_identified_payload(),
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "open"
        # Case still readable / editable surface for investigation
        get_res = client.get(
            f"/api/maintenance-cases/{case.id}/",
            headers=admin_headers,
        )
        assert get_res.status_code == 200
        assert get_res.json()["status"] == "open"
        ui = FRONTEND_FIELD_PANEL.read_text(encoding="utf-8")
        assert "investigation continues in parallel" in ui.lower() or "parallel" in ui.lower()
    finally:
        cleanup_project(session, project)


def test_ft_or_012_occurrence_recorded_notify(
    client, admin_headers, session: Session, admin_user
):
    """FT-OR-012 — After record, occurrence_recorded notification is created."""
    project, case = create_project_and_case(session, admin_user)
    try:
        before = len(
            session.exec(
                select(AppNotification).where(
                    AppNotification.event_type == "occurrence_recorded",
                    AppNotification.entity_id == case.id,
                )
            ).all()
        )
        res = client.post(
            f"/api/maintenance-cases/{case.id}/onsite-outcome/",
            headers=admin_headers,
            json=occurrence_payload(onsite_outcome="inconclusive"),
        )
        assert res.status_code == 200, res.text
        session.expire_all()
        after = session.exec(
            select(AppNotification).where(
                AppNotification.event_type == "occurrence_recorded",
                AppNotification.entity_id == case.id,
            )
        ).all()
        assert len(after) > before
    finally:
        cleanup_project(session, project)
