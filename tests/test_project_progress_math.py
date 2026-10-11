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
from app.services.project_progress_service import _subtree_display_status


def _leaf(name: str, status: str | None = None, *, defect_pending: bool = False) -> ProgressNode:
    return ProgressNode(
        entity_type="component",
        entity_id=hash(name) % 10_000,
        name=name,
        status=status or NOT_STARTED_STATUS,
        defect_pending=defect_pending,
    )


def _with_own_coverage(node: ProgressNode, status: str) -> ProgressNode:
    """Mark coverage as recorded on this node (not inherited from an ancestor)."""
    node.status = status
    node.cover_entity_type = node.entity_type
    node.cover_entity_id = node.entity_id
    node.cover_name = node.name
    return node


def test_stage_fractions():
    assert stage_fraction(None) == 0.0
    assert stage_fraction(ItemStatus.RESERVED.value) == 0.1
    assert stage_fraction(ItemStatus.ISSUED.value) == 0.3
    assert stage_fraction(ItemStatus.INSTALLATION_IN_PROGRESS.value) == 0.5
    assert stage_fraction(ItemStatus.UNDER_TESTING_REVIEW.value) == 0.75
    assert stage_fraction(ItemStatus.INSTALLED_VERIFIED.value) == 1.0
    # Spaced / alias labels must map to the same Spec 09 fractions.
    assert stage_fraction("Installation In Progress") == 0.5
    assert stage_fraction("installing") == 0.5
    assert stage_fraction("Under Testing / Review") == 0.75
    assert stage_fraction("Installed Verified") == 1.0


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


def test_reserved_and_installing_systems_differ_in_progress():
    """Different lifecycle stages must not collapse to the same %."""
    reserved_leaf = _leaf("R1", ItemStatus.RESERVED.value)
    reserved = ProgressNode(
        entity_type="system", entity_id=1, name="SYS-R", children=[reserved_leaf]
    )
    installing_leaf = _leaf("I1", ItemStatus.INSTALLATION_IN_PROGRESS.value)
    installing = ProgressNode(
        entity_type="system", entity_id=2, name="SYS-I", children=[installing_leaf]
    )
    rollup_progress(reserved)
    rollup_progress(installing)
    assert progress_pct(reserved.progress) == 10
    assert progress_pct(installing.progress) == 50
    assert progress_pct(reserved.progress) != progress_pct(installing.progress)


def test_reserved_parent_caps_progress_when_children_are_verified():
    """System/module/unit/subsystem integration pending must block 100%."""
    for entity_type, name in (
        ("system", "Antenna Pedestal"),
        ("subsystem", "RF Bay"),
        ("module", "Mod-A"),
        ("unit", "Unit-1"),
    ):
        children = [
            _leaf(f"{name}-a", ItemStatus.INSTALLED_VERIFIED.value),
            _leaf(f"{name}-b", ItemStatus.INSTALLED_VERIFIED.value),
        ]
        parent = _with_own_coverage(
            ProgressNode(
                entity_type=entity_type,
                entity_id=hash(entity_type) % 10_000,
                name=name,
                children=children,
            ),
            ItemStatus.RESERVED.value,
        )
        rollup_progress(parent)
        assert parent.verified_leaves == 2
        assert parent.weight == 2
        assert progress_pct(parent.progress) == 10
        assert _subtree_display_status(parent) == ItemStatus.RESERVED.value

        # Once the parent itself is verified, rollup may reach 100%.
        parent.status = ItemStatus.INSTALLED_VERIFIED.value
        rollup_progress(parent)
        assert progress_pct(parent.progress) == 100
        assert _subtree_display_status(parent) == ItemStatus.INSTALLED_VERIFIED.value


def test_structural_parent_without_coverage_still_rolls_up_children():
    """Flight/SDLS containers without inventory coverage stay children-weighted."""
    leaf = _leaf("L1", ItemStatus.INSTALLED_VERIFIED.value)
    system = ProgressNode(
        entity_type="system", entity_id=1, name="SYS", children=[leaf]
    )
    rollup_progress(system)
    assert progress_pct(system.progress) == 100


def test_incomplete_own_coverage_parent_is_bottleneck():
    child = _leaf("C1", ItemStatus.INSTALLED_VERIFIED.value)
    parent = _with_own_coverage(
        ProgressNode(
            entity_type="system",
            entity_id=1,
            name="Antenna Pedestal",
            children=[child],
        ),
        ItemStatus.RESERVED.value,
    )
    rollup_progress(parent)
    rows = collect_bottlenecks(parent)
    assert any(
        row["entity_type"] == "system" and row["reason"] == "reserved" for row in rows
    )


def test_advanced_parent_coverage_overrides_stale_child_reserved():
    from app.services.project_progress_service import _apply_coverage

    leaf = ProgressNode(entity_type="component", entity_id=10, name="C1")
    system = ProgressNode(
        entity_type="system",
        entity_id=1,
        name="SYS",
        children=[leaf],
    )
    coverage = {
        ("system", 1): {
            "status": ItemStatus.INSTALLATION_IN_PROGRESS.value,
            "defect_pending": False,
        },
        ("component", 10): {
            "status": ItemStatus.RESERVED.value,
            "defect_pending": False,
        },
    }
    _apply_coverage(system, coverage)
    rollup_progress(system)
    assert leaf.status == ItemStatus.INSTALLATION_IN_PROGRESS.value
    assert progress_pct(system.progress) == 50


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
