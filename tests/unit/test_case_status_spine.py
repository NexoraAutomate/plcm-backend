"""UT-RL-003 — CaseStatus spine must remain unchanged (REQ-MHD-DT-001)."""

from app.models.base import CaseStatus


def test_case_status_spine_unchanged():
    assert [s.value for s in CaseStatus] == [
        "open",
        "under_inspection",
        "under_repair",
        "resolved",
        "closed",
    ]
