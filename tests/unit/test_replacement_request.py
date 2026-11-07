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
    def test_approve_stops_at_pd_approved(self):
        """P3 — PD approve does not jump to im_issue_pending or queue Track B."""
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
            out = rr_svc.pd_decide(
                session,
                case,
                req,
                actor=_actor(),
                decision="approve",
            )

        assert out.status == ReplacementRequestStatus.PD_APPROVED.value
        assert out.pd_decision == "approve"
        rework_mock.assert_not_called()

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


class TestMeRequestIssue:
    def test_me_request_issue_advances(self):
        """UT-RA / RA-005"""
        req = SimpleNamespace(
            id=5,
            status=ReplacementRequestStatus.PD_APPROVED.value,
            assigned_me_id=9,
            shortage_held=False,
            updated_at=None,
        )
        session = MagicMock()
        with patch.object(
            rr_svc,
            "list_reservations",
            return_value=[SimpleNamespace(id=1)],
        ):
            out = rr_svc.me_request_issue(session, req)
        assert out.status == ReplacementRequestStatus.IM_ISSUE_PENDING.value

    def test_me_request_issue_requires_reservation(self):
        req = SimpleNamespace(
            id=5,
            status=ReplacementRequestStatus.PD_APPROVED.value,
            assigned_me_id=9,
            shortage_held=False,
            updated_at=None,
        )
        with patch.object(rr_svc, "list_reservations", return_value=[]):
            with pytest.raises(HTTPException) as exc:
                rr_svc.me_request_issue(MagicMock(), req)
        assert exc.value.status_code == 400


class TestImIssue:
    def test_shortage_holds_without_issue(self):
        """UT-RA-004 / RA-006"""
        case = _case()
        req = SimpleNamespace(
            id=5,
            case_id=1,
            status=ReplacementRequestStatus.IM_ISSUE_PENDING.value,
            assigned_me_id=9,
            shortage_held=False,
            updated_at=None,
            issued_serial=None,
            issued_instance_id=None,
            issued_at=None,
            red_notified_at=None,
        )
        session = MagicMock()
        with patch.object(
            rr_svc,
            "_active_reservation_link",
            side_effect=HTTPException(status_code=409, detail="No active inventory reservation"),
        ):
            with pytest.raises(HTTPException) as exc:
                rr_svc.im_issue(
                    session,
                    case,
                    req,
                    actor=_actor(),
                    signature_type="HARD_COPY",
                    signature_payload="ACK",
                )
        assert exc.value.status_code == 409
        assert req.shortage_held is True

    def test_successful_issue_sets_shipped_and_track_b(self):
        """UT-RA-005 / RA-007 / RA-009"""
        case = _case()
        req = SimpleNamespace(
            id=5,
            case_id=1,
            status=ReplacementRequestStatus.IM_ISSUE_PENDING.value,
            assigned_me_id=9,
            shortage_held=False,
            updated_at=None,
            issued_serial=None,
            issued_instance_id=None,
            issued_at=None,
            red_notified_at=None,
            faulty_entity_id=12,
            faulty_entity_type="unit",
            faulty_entity_ref_id=55,
        )
        link = SimpleNamespace(
            inventory_reservation_id=77,
            inventory_instance_id=88,
        )
        reservation = SimpleNamespace(
            id=77,
            inventory_id=3,
            inventory_instance_id=88,
            status="active",
            target_entity_type="unit",
            target_entity_id=55,
        )
        inventory = SimpleNamespace(id=3, part_number="PN-100")
        session = MagicMock()
        session.get.side_effect = lambda model, pk: {
            3: inventory,
            88: SimpleNamespace(id=88, status_id=1, inventory_id=3),
        }.get(pk)

        issuance = SimpleNamespace(
            serial_number="SN-NEW",
            inventory_instance_id=88,
        )

        with patch.object(
            rr_svc, "_active_reservation_link", return_value=(link, reservation)
        ), patch(
            "app.services.replacement_request_service.item_status_name",
            return_value="RESERVED",
        ), patch(
            "app.services.inventory_issuance_service.issue_inventory_unit",
            return_value=issuance,
        ), patch(
            "app.services.replacement_request_service.field_svc.create_returned_unit_rework"
        ) as rework_mock:
            rework_mock.return_value = SimpleNamespace(
                id=3, stage=ReworkStage.AWAITING_FAULTY_ARRIVAL.value
            )
            out = rr_svc.im_issue(
                session,
                case,
                req,
                actor=_actor(),
                signature_type="HARD_COPY",
                signature_payload="ACK",
            )

        assert out.status == ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value
        assert out.issued_serial == "SN-NEW"
        assert out.red_notified_at is not None
        rework_mock.assert_called_once()


class TestAitFlow:
    def test_ait_approve_patch_delivered(self):
        """UT-RA-007 / RA-012 / RA-014"""
        req = SimpleNamespace(
            id=5,
            status=ReplacementRequestStatus.AIT_IN_PROGRESS.value,
            ait_decision=None,
            ait_reject_reason=None,
            updated_at=None,
        )
        session = MagicMock()
        with patch.object(
            rr_svc,
            "list_ait_attachments",
            return_value=[SimpleNamespace(id=1)],
        ):
            out = rr_svc.pd_ait_decide(session, req, decision="approve")
        assert out.status == ReplacementRequestStatus.PATCH_DELIVERED.value
        assert out.ait_decision == "approve"

    def test_ait_reject_quarantines_and_reopens_issue(self):
        """UT-RA-008 / RA-013"""
        req = SimpleNamespace(
            id=5,
            status=ReplacementRequestStatus.AIT_IN_PROGRESS.value,
            ait_decision=None,
            ait_reject_reason=None,
            issued_instance_id=88,
            issued_serial="SN-FAIL",
            issued_at=None,
            quarantined_instance_id=None,
            shortage_held=False,
            updated_at=None,
        )
        session = MagicMock()
        with patch.object(
            rr_svc,
            "list_ait_attachments",
            return_value=[SimpleNamespace(id=1)],
        ), patch.object(rr_svc, "_quarantine_instance") as q:
            out = rr_svc.pd_ait_decide(
                session, req, decision="reject", reject_reason="failed AIT"
            )
        assert out.status == ReplacementRequestStatus.IM_ISSUE_PENDING.value
        assert out.ait_decision == "reject"
        assert out.quarantined_instance_id == 88
        q.assert_called_once()

    def test_upload_ait_starts_progress(self):
        """UT-RA / RA-010"""
        req = SimpleNamespace(
            id=5,
            case_id=1,
            status=ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value,
            updated_at=None,
        )
        session = MagicMock()
        added = []
        session.add.side_effect = lambda obj: added.append(obj)
        row = rr_svc.upload_ait_attachment(
            session, req, display_name="AIT Report", file_id=42
        )
        assert req.status == ReplacementRequestStatus.AIT_IN_PROGRESS.value
        assert row.display_name == "AIT Report"
        assert row.file_id == 42


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
