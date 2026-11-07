"""UT-IE-* — Track B inspection / IE disposition (P4)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.base import ReworkCaseStatus, ReworkStage
from app.services import track_b_inspection_service as tb


def _actor(uid: int = 11):
    return SimpleNamespace(id=uid, full_name="Actor", username="actor")


def _rework(**overrides):
    base = dict(
        id=42,
        maintenance_case_id=7,
        project_id=10,
        inventory_id=100,
        current_instance_id=None,
        status=ReworkCaseStatus.OPEN.value,
        stage=ReworkStage.AWAITING_FAULTY_ARRIVAL.value,
        assigned_developer_id=None,
        investigating_pd_id=3,
        reception_date=None,
        disposition=None,
        notes=None,
        repaired_at=None,
        repaired_by_id=None,
        closed_at=None,
        closed_by_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestTerminalHelper:
    def test_is_track_b_terminal(self):
        """UT-IE-010 / IE-011"""
        assert tb.is_track_b_terminal("restocked")
        assert tb.is_track_b_terminal("discarded")
        assert tb.is_track_b_terminal("claim_closed")
        assert not tb.is_track_b_terminal("received")
        assert not tb.is_track_b_terminal("repair_under_progress")
        assert not tb.is_track_b_terminal("discard_pending")


class TestReception:
    def test_reception_sets_received(self):
        """UT-IE-001"""
        rework = _rework()
        session = MagicMock()
        session.get.return_value = rework

        with patch.object(tb, "_set_item_status"), patch(
            "app.services.app_notification_service.notify"
        ):
            out = tb.record_reception(session, 42, actor=_actor())

        assert out.stage == ReworkStage.RECEIVED.value
        assert out.reception_date is not None

    def test_reception_wrong_stage(self):
        rework = _rework(stage=ReworkStage.RECEIVED.value)
        session = MagicMock()
        session.get.return_value = rework
        with pytest.raises(HTTPException) as exc:
            tb.record_reception(session, 42, actor=_actor())
        assert exc.value.status_code == 409


class TestAssignIe:
    def test_pd_assign_ie(self):
        """UT-IE-002"""
        rework = _rework(stage=ReworkStage.RECEIVED.value)
        ie = SimpleNamespace(id=55, full_name="IE", username="ie")
        session = MagicMock()

        def _get(model, pk):
            if pk == 42:
                return rework
            if pk == 55:
                return ie
            return None

        session.get.side_effect = _get

        with patch("app.services.app_notification_service.notify"):
            out = tb.assign_ie(session, 42, ie_user_id=55, actor=_actor())

        assert out.stage == ReworkStage.IE_ASSIGNED.value
        assert out.assigned_developer_id == 55


class TestClaimClosed:
    def test_mark_claim_closed(self):
        rework = _rework(stage=ReworkStage.WARRANTY_CLAIM.value)
        session = MagicMock()
        session.get.return_value = rework
        out = tb.mark_claim_closed(session, 42, actor=_actor())
        assert out.stage == ReworkStage.CLAIM_CLOSED.value
        assert tb.is_track_b_terminal(out.stage)


class TestIssueToIe:
    def test_handover_then_issue(self):
        """UT-IE-003"""
        rework = _rework(
            stage=ReworkStage.IE_ASSIGNED.value, assigned_developer_id=55
        )
        session = MagicMock()
        session.get.return_value = rework

        with patch("app.services.app_notification_service.notify"):
            tb.request_handover(session, 42, actor=_actor(55))
        assert rework.stage == ReworkStage.ISSUED_TO_IE.value

        with patch.object(tb, "_set_item_status"):
            tb.im_issue_to_ie(session, 42, actor=_actor())
        assert rework.stage == ReworkStage.INSPECTION_UNDER_PROCESS.value


class TestDisposition:
    def test_repairable(self):
        """UT-IE-004"""
        rework = _rework(stage=ReworkStage.INSPECTION_UNDER_PROCESS.value)
        session = MagicMock()
        session.get.return_value = rework
        with patch.object(tb, "_set_item_status"):
            tb.ie_disposition(session, 42, actor=_actor(), outcome="repairable")
        assert rework.stage == ReworkStage.REPAIR_UNDER_PROGRESS.value

    def test_warranty_path(self):
        """UT-IE-005"""
        rework = _rework(stage=ReworkStage.INSPECTION_UNDER_PROCESS.value)
        session = MagicMock()
        session.get.return_value = rework
        claim = SimpleNamespace(id=9)

        with patch(
            "app.services.maintenance_field_service.create_or_require_warranty_claim",
            return_value=(claim, "claim"),
        ):
            tb.ie_disposition(session, 42, actor=_actor(), outcome="warranty")
        assert rework.stage == ReworkStage.WARRANTY_CLAIM.value

    def test_discard_recommend_does_not_scrap(self):
        """UT-IE-006"""
        rework = _rework(stage=ReworkStage.INSPECTION_UNDER_PROCESS.value)
        session = MagicMock()
        session.get.return_value = rework
        with patch.object(tb, "_set_item_status") as set_status:
            tb.ie_disposition(session, 42, actor=_actor(), outcome="discard")
        assert rework.stage == ReworkStage.DISCARD_PENDING.value
        set_status.assert_not_called()

    def test_im_confirm_discard(self):
        """UT-IE-007"""
        rework = _rework(stage=ReworkStage.DISCARD_PENDING.value)
        session = MagicMock()
        session.get.return_value = rework
        with patch.object(tb, "_set_item_status") as set_status:
            tb.im_confirm_discard(session, 42, actor=_actor())
        assert rework.stage == ReworkStage.DISCARDED.value
        assert rework.status == ReworkCaseStatus.CLOSED.value
        assert tb.discarded_flag(rework) is True
        set_status.assert_called()


class TestPdRepairGate:
    def test_pd_reject_keeps_repair(self):
        """UT-IE-008"""
        rework = _rework(
            stage=ReworkStage.REPAIR_UNDER_PROGRESS.value, repaired_at="x"
        )
        session = MagicMock()
        session.get.return_value = rework
        tb.pd_repair_decide(
            session, 42, actor=_actor(), decision="reject", reject_reason="fail"
        )
        assert rework.stage == ReworkStage.REPAIR_UNDER_PROGRESS.value
        assert rework.status == ReworkCaseStatus.OPEN.value
        assert rework.repaired_at is None

    def test_pd_approve_restocks(self):
        """UT-IE-009"""
        rework = _rework(stage=ReworkStage.REPAIR_UNDER_PROGRESS.value)
        session = MagicMock()
        session.get.return_value = rework
        with patch.object(tb, "_set_item_status"):
            tb.pd_repair_decide(session, 42, actor=_actor(), decision="approve")
        assert rework.stage == ReworkStage.RESTOCKED.value
        assert rework.status == ReworkCaseStatus.CLOSED.value
        assert tb.is_track_b_terminal(rework.stage)


class TestIllegalJump:
    def test_illegal_skip_reception(self):
        rework = _rework(stage=ReworkStage.AWAITING_FAULTY_ARRIVAL.value)
        session = MagicMock()
        session.get.return_value = rework
        with pytest.raises(HTTPException) as exc:
            tb.assign_ie(session, 42, ie_user_id=1, actor=_actor())
        assert exc.value.status_code == 409
