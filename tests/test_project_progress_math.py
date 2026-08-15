"""Spec 09 — weighted rollup math (no database)."""

from __future__ import annotations

from app.domain.project_progress import (
    NOT_STARTED_STATUS,
    ProgressNode,
    collect_bottlenecks,
    is_verified_leaf,
    progress_pct,
    rollup_progress,
    stage_fraction,
    weighted_average,
)
from app.domain.workflow_status import ItemStatus


def _leaf(name: str, status: str | None = None, *, defect_pending: bool = False) -> ProgressNode:
    return ProgressNode(
        entity_type="component",
        entity_id=hash(name) % 10_000,
        name=name,
        status=status or NOT_STARTED_STATUS,
        defect_pending=defect_pending,
    )


def test_stage_fractions():
    assert stage_fraction(None) == 0.0
    assert stage_fraction(ItemStatus.RESERVED.value) == 0.1
    assert stage_fraction(ItemStatus.ISSUED.value) == 0.3
    assert stage_fraction(ItemStatus.INSTALLATION_IN_PROGRESS.value) == 0.5
    assert stage_fraction(ItemStatus.UNDER_TESTING_REVIEW.value) == 0.75
    assert stage_fraction(ItemStatus.INSTALLED_VERIFIED.value) == 1.0


def test_fail_does_not_count_as_verified():
    assert not is_verified_leaf(
        ItemStatus.INSTALLED_VERIFIED.value, defect_pending=True
    )
    assert stage_fraction(
        ItemStatus.INSTALLED_VERIFIED.value, defect_pending=True
    ) == 0.75


def test_equal_weights_are_simple_mean():
    assert weighted_average([(1.0, 1), (0.0, 1)]) == 0.5
    assert progress_pct(0.5) == 50


def test_uneven_18_of_20_is_90_not_50():
    sdls_a = ProgressNode(
        entity_type="sdls",
        entity_id=1,
        name="SDLS-A",
        children=[
            _leaf(f"A{i}", ItemStatus.INSTALLED_VERIFIED.value) for i in range(18)
        ],
    )
    sdls_b = ProgressNode(
        entity_type="sdls",
        entity_id=2,
        name="SDLS-B",
        children=[_leaf("B1"), _leaf("B2")],
    )
    root = ProgressNode(
        entity_type="project",
        entity_id=1,
        name="P",
        children=[sdls_a, sdls_b],
    )
    rollup_progress(root)
    assert root.weight == 20
    assert root.verified_leaves == 18
    assert progress_pct(root.progress) == 90
    assert progress_pct(sdls_a.progress) == 100
    assert progress_pct(sdls_b.progress) == 0


def test_stepwise_stage_weights_increment():
    leaf = _leaf("L1", ItemStatus.RESERVED.value)
    parent = ProgressNode(
        entity_type="system", entity_id=1, name="SYS", children=[leaf]
    )
    rollup_progress(parent)
    assert progress_pct(parent.progress) == 10
    leaf.status = ItemStatus.ISSUED.value
    rollup_progress(parent)
    assert progress_pct(parent.progress) == 30
    leaf.status = ItemStatus.INSTALLATION_IN_PROGRESS.value
    rollup_progress(parent)
    assert progress_pct(parent.progress) == 50
    leaf.status = ItemStatus.UNDER_TESTING_REVIEW.value
    rollup_progress(parent)
    assert progress_pct(parent.progress) == 75
    leaf.status = ItemStatus.INSTALLED_VERIFIED.value
    rollup_progress(parent)
    assert progress_pct(parent.progress) == 100


def test_bottlenecks_rank_fail_loops_first():
    root = ProgressNode(
        entity_type="project",
        entity_id=1,
        name="P",
        children=[
            _leaf("ok", ItemStatus.INSTALLED_VERIFIED.value),
            _leaf(
                "fail",
                ItemStatus.UNDER_TESTING_REVIEW.value,
                defect_pending=True,
            ),
            _leaf("hold", ItemStatus.RESERVED.value),
        ],
    )
    rollup_progress(root)
    rows = collect_bottlenecks(root)
    assert rows[0]["reason"] == "fail_loop"
    assert any(row["reason"] == "reserved" for row in rows)
    assert not any(
        is_verified_leaf(row.get("status"), defect_pending=row["defect_pending"])
        for row in rows
    )
