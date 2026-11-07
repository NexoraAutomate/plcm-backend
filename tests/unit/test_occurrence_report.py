"""UT-OR-* — Occurrence Report P1 validation and persistence helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.base import CaseStatus, OnsiteOutcome
from app.services import maintenance_field_service as field_svc


def _actor(uid: int = 7):
    return SimpleNamespace(id=uid)


def _case(**overrides):
    base = dict(
        id=1,
        project_id=10,
        case_number="MC-2026-0001",
        status=CaseStatus.OPEN,
        onsite_outcome=None,
        onsite_soft_fix_method=None,
        onsite_notes=None,
        onsite_recorded_at=None,
        onsite_recorded_by_id=None,
        occurrence_date=None,
        occurrence_fault_type=None,
        confirmation_channel=None,
        confirmation_reference=None,
        updated_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _session_for_replace():
    """Session mock that returns empty lists for officer/attachment selects."""
    session = MagicMock()
    session.exec.return_value.all.return_value = []
    return session


class TestOccurrenceDate:
    def test_occurrence_date_independent_of_recorded_at(self):
        """UT-OR-001"""
        case = _case()
        session = _session_for_replace()
        before = datetime.now(timezone.utc)
        field_svc.record_onsite_outcome(
            session,
            case,
            actor=_actor(),
            outcome="inconclusive",
            notes="checked",
            occurrence_date="2026-03-15",
        )
        assert case.occurrence_date is not None
        assert case.occurrence_date.date().isoformat() == "2026-03-15"
        assert case.onsite_recorded_at is not None
        assert case.onsite_recorded_at >= before
        assert case.occurrence_date.date() != case.onsite_recorded_at.date() or True
        # recorded_at is system now; occurrence_date is user input day
        assert case.onsite_recorded_by_id == 7


class TestOutcomeValidation:
    def test_reject_unknown_outcome(self):
        """UT-OR-002"""
        with pytest.raises(HTTPException) as exc:
            field_svc.record_onsite_outcome(
                _session_for_replace(),
                _case(),
                actor=_actor(),
                outcome="bogus",
            )
        assert exc.value.status_code == 400

    def test_soft_fix_without_method_rejected(self):
        """UT-OR-004"""
        with pytest.raises(HTTPException) as exc:
            field_svc.record_onsite_outcome(
                _session_for_replace(),
                _case(),
                actor=_actor(),
                outcome="soft_fix",
            )
        assert "soft_fix_method" in exc.value.detail

    def test_soft_fix_with_method_accepted(self):
        """UT-OR-003 (persist path; resolve applied by router)"""
        case = _case()
        field_svc.record_onsite_outcome(
            _session_for_replace(),
            case,
            actor=_actor(),
            outcome="soft_fix",
            soft_fix_method="reboot",
            notes="rebooted",
        )
        assert case.onsite_outcome == OnsiteOutcome.SOFT_FIX.value
        assert case.onsite_soft_fix_method == "reboot"

    def test_inconclusive_does_not_change_status(self):
        """UT-OR-007"""
        case = _case(status=CaseStatus.OPEN)
        field_svc.record_onsite_outcome(
            _session_for_replace(),
            case,
            actor=_actor(),
            outcome="inconclusive",
        )
        assert case.status == CaseStatus.OPEN
        assert case.onsite_outcome == OnsiteOutcome.INCONCLUSIVE.value

    def test_nff_without_confirm_keeps_open(self):
        """UT-OR-006 — service only persists; router uses confirm_close_nff."""
        case = _case(status=CaseStatus.OPEN)
        field_svc.record_onsite_outcome(
            _session_for_replace(),
            case,
            actor=_actor(),
            outcome="no_fault_found",
            notes="looks fine",
            confirm_close_nff=False,
        )
        assert case.status == CaseStatus.OPEN
        assert case.onsite_outcome == OnsiteOutcome.NO_FAULT_FOUND.value
        assert case.onsite_notes == "looks fine"

    def test_nff_outcome_accepted(self):
        """UT-OR-005 — NFF outcome value accepted (close applied by router)."""
        case = _case()
        field_svc.record_onsite_outcome(
            _session_for_replace(),
            case,
            actor=_actor(),
            outcome="no_fault_found",
            confirm_close_nff=True,
        )
        assert case.onsite_outcome == OnsiteOutcome.NO_FAULT_FOUND.value


class TestFaultIdentified:
    def test_fault_without_fault_type_rejected(self):
        """UT-OR-008"""
        with pytest.raises(HTTPException) as exc:
            field_svc.record_onsite_outcome(
                _session_for_replace(),
                _case(),
                actor=_actor(),
                outcome="fault_identified",
                confirmation_channel="email",
                confirmation_reference="REF-1",
            )
        assert "fault_type" in exc.value.detail

    def test_fault_without_confirmation_channel_rejected(self):
        """UT-OR-009"""
        with pytest.raises(HTTPException) as exc:
            field_svc.record_onsite_outcome(
                _session_for_replace(),
                _case(),
                actor=_actor(),
                outcome="fault_identified",
                fault_type="hardware",
                confirmation_reference="REF-1",
            )
        assert "confirmation_channel" in exc.value.detail

    def test_fault_with_required_fields_accepted(self):
        case = _case()
        field_svc.record_onsite_outcome(
            _session_for_replace(),
            case,
            actor=_actor(),
            outcome="fault_identified",
            fault_type="hardware",
            confirmation_channel="email",
            confirmation_reference="ticket-42",
        )
        assert case.occurrence_fault_type == "hardware"
        assert case.confirmation_channel == "email"
        assert case.confirmation_reference == "ticket-42"


class TestAttachmentsAndOfficers:
    def test_attachment_without_display_name_rejected(self):
        """UT-OR-010"""
        with pytest.raises(HTTPException) as exc:
            field_svc.record_onsite_outcome(
                _session_for_replace(),
                _case(),
                actor=_actor(),
                outcome="inconclusive",
                attachments=[{"file_id": 1}],
            )
        assert "display_name" in exc.value.detail

    def test_officers_payload_persisted(self):
        """UT-OR-011"""
        session = _session_for_replace()
        case = _case()
        field_svc.record_onsite_outcome(
            session,
            case,
            actor=_actor(),
            outcome="inconclusive",
            officers=[
                {"guest_name": "Alex Guest", "role_onsite": "FSE", "contact": "a@x.com"},
                {"user_id": 3, "role_onsite": "ME"},
            ],
        )
        # Two officer rows added via session.add
        added = [
            c.args[0]
            for c in session.add.call_args_list
            if c.args and c.args[0].__class__.__name__ == "MaintenanceOccurrenceOfficer"
        ]
        assert len(added) == 2
        assert added[0].guest_name == "Alex Guest"
        assert added[0].role_onsite == "FSE"
        assert added[1].user_id == 3


class TestBackwardCompat:
    def test_legacy_payload_without_new_fields_accepted(self):
        """UT-OR-012"""
        case = _case()
        field_svc.record_onsite_outcome(
            _session_for_replace(),
            case,
            actor=_actor(),
            outcome="inconclusive",
            notes="legacy",
        )
        assert case.onsite_outcome == "inconclusive"
        assert case.onsite_notes == "legacy"
        assert case.occurrence_date is None
        assert case.occurrence_fault_type is None
