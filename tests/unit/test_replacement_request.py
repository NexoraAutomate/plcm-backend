"""UT-RA-* / FT-DT helpers — ReplacementRequest P2 dual-track wiring."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.base import (
    CaseStatus,
    OnsiteOutcome,
    ReplacementRequestStatus,
    ReworkStage,
)
from app.services import replacement_request_service as rr_svc


def _actor(uid: int = 7):
    return SimpleNamespace(id=uid, full_name="Actor", username="actor")


def _case(**overrides):
    base = dict(
        id=1,
        project_id=10,
        case_number="MC-2026-0001",
        status=CaseStatus.OPEN,
        onsite_outcome=OnsiteOutcome.FAULT_IDENTIFIED.value,
        confirmation_channel="email",
        confirmation_reference="REF-1",
        entity_type="unit",
        entity_id=55,
        part_number="PN-100",
        reported_by=3,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestCreateReplacementRequest:
    def test_create_links_case_and_sets_status(self):
        """UT-RA-001"""
        case = _case()
        session = MagicMock()
        session.exec.return_value.first.return_value = None  # no open request
        session.exec.return_value.all.return_value = []  # no FEs
        session.get.return_value = None

        added = []
        session.add.side_effect = lambda obj: added.append(obj)

        req = rr_svc.create_replacement_request(
            session, case, actor=_actor(9), faulty_entity_id=None
        )

        assert req.case_id == 1
        assert req.requested_by_id == 9
        assert req.status == ReplacementRequestStatus.REPLACEMENT_REQUESTED.value
        assert req.faulty_entity_type == "unit"
        assert req.faulty_entity_ref_id == 55
        assert added

    def test_create_requires_fault_identified(self):
        case = _case(onsite_outcome=OnsiteOutcome.INCONCLUSIVE.value)
        with pytest.raises(HTTPException) as exc:
            rr_svc.create_replacement_request(
                MagicMock(), case, actor=_actor()
            )
        assert exc.value.status_code == 400

    def test_create_requires_confirmation_channel(self):
        case = _case(confirmation_channel=None)
        with pytest.raises(HTTPException) as exc:
            rr_svc.create_replacement_request(
                MagicMock(), case, actor=_actor()
            )
        assert exc.value.status_code == 400

    def test_duplicate_open_request_conflict(self):
        case = _case()
        session = MagicMock()
        session.exec.return_value.first.return_value = SimpleNamespace(id=99)
        with pytest.raises(HTTPException) as exc:
            rr_svc.create_replacement_request(
                session, case, actor=_actor()
            )
        assert exc.value.status_code == 409


class TestReserve:
    def test_reserve_marks_reserved_via_inventory(self):
        """UT-RA-002"""
        case = _case()
        req = SimpleNamespace(
            id=5,
            case_id=1,
            status=ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
            faulty_entity_type="unit",
            faulty_entity_ref_id=55,
            faulty_entity_id=None,
            updated_at=None,
        )
        session = MagicMock()
        fake_reservation = SimpleNamespace(id=77, inventory_instance_id=88)

        with patch(
            "app.services.replacement_request_service.reserve_inventory",
            return_value=fake_reservation,
        ) as reserve_mock:
            rr_svc.reserve_for_request(
                session,
                case,
                req,
                actor=_actor(),
                part_number="PN-100",
                serial_number="SN-NEW-1",
            )

        reserve_mock.assert_called_once()
        kwargs = reserve_mock.call_args.kwargs
        assert kwargs["for_maintenance_replacement"] is True
        assert kwargs["allow_assembled"] is True
        assert kwargs["commit"] is False
        # Junction row added
        assert session.add.call_count >= 1
        added_types = [type(c.args[0]).__name__ for c in session.add.call_args_list]
        assert "ReplacementRequestReservation" in added_types or any(
            getattr(c.args[0], "inventory_reservation_id", None) == 77
            for c in session.add.call_args_list
        )


class TestPdDecideAndTrackB:
    def test_approve_sets_im_issue_pending_and_awaiting(self):
        """FT-DT-004 support — Track A advances without faulty reception."""
        case = _case()
        req = SimpleNamespace(
            id=5,
            case_id=1,
            status=ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
            faulty_entity_id=12,
            faulty_entity_type="unit",
            faulty_entity_ref_id=55,
            pd_decision=None,
            reject_reason=None,
            updated_at=None,
        )
        session = MagicMock()

        with patch(
            "app.services.replacement_request_service.field_svc.create_returned_unit_rework"
        ) as rework_mock:
            rework_mock.return_value = SimpleNamespace(
                id=3, stage=ReworkStage.AWAITING_FAULTY_ARRIVAL.value
            )
            out = rr_svc.pd_decide(
                session,
                case,
                req,
                actor=_actor(),
                decision="approve",
            )

        assert out.status == ReplacementRequestStatus.IM_ISSUE_PENDING.value
        assert out.pd_decision == "approve"
        rework_mock.assert_called_once()
        assert (
            rework_mock.call_args.kwargs["initial_stage"]
            == ReworkStage.AWAITING_FAULTY_ARRIVAL.value
        )

    def test_reject_requires_reason_and_stops(self):
        case = _case()
        req = SimpleNamespace(
            id=5,
            case_id=1,
            status=ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
            pd_decision=None,
            reject_reason=None,
            updated_at=None,
        )
        with pytest.raises(HTTPException) as exc:
            rr_svc.pd_decide(
                MagicMock(), case, req, actor=_actor(), decision="reject"
            )
        assert exc.value.status_code == 400

        out = rr_svc.pd_decide(
            MagicMock(),
            case,
            req,
            actor=_actor(),
            decision="reject",
            reject_reason="wrong PN",
        )
        assert out.status == ReplacementRequestStatus.PD_REJECTED.value
        assert out.reject_reason == "wrong PN"


class TestStatusGuard:
    def test_illegal_jump_rejected(self):
        with pytest.raises(HTTPException) as exc:
            rr_svc.assert_status_transition(
                ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
                ReplacementRequestStatus.AIT_APPROVED.value,
            )
        assert exc.value.status_code == 409


class TestDualTrackBoard:
    def test_board_idle_track_b_when_requested(self):
        """FT-DT-001 — Track A started; Track B idle before approve."""
        case = _case()
        req = SimpleNamespace(
            id=5,
            status=ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
        )
        session = MagicMock()

        with patch.object(rr_svc, "get_open_request_for_case", return_value=req), patch(
            "app.services.replacement_request_service.field_svc.list_case_returned_units",
            return_value=[],
        ):
            board = rr_svc.build_dual_track_board(session, case)

        assert board["track_a_status"] == ReplacementRequestStatus.REPLACEMENT_REQUESTED.value
        assert board["track_b_status"] == "idle"
