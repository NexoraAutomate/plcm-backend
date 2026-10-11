"""
Spec 09 — weighted project progress from tree concentration + lifecycle stages.

Parent progress is a weighted average of children. Default weight of a subtree
is the number of required leaf nodes. Stage fractions are the documented
implementation policy (Reserved … Installed Verified). Fail/open defects never
count as Installed Verified.

When a parent has its own inventory coverage (reservation / issuance / assemble
shell), children contribute the bulk of the work (design / develop / test) and
the parent's remaining share is Assembly–Integration–Test (AIT). Verified
children therefore credit most of the parent %, while unfinished parent AIT
blocks 100% and rolls up honestly to SDLS / flight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.domain.workflow_status import ItemStatus

# Procurement / Procured are not in the inventory domain — not started (0).
STAGE_COMPLETION_FRACTION: dict[str, float] = {
    ItemStatus.RESERVED.value: 0.1,
    ItemStatus.ISSUED.value: 0.3,
    ItemStatus.INSTALLATION_IN_PROGRESS.value: 0.5,
    ItemStatus.INSTALLATION_REJECTED.value: 0.55,
    ItemStatus.UNDER_TESTING_REVIEW.value: 0.75,
    ItemStatus.INSTALLED_VERIFIED.value: 1.0,
}

# Parents with own coverage: majority of effort is in children; remainder is AIT.
PARENT_CHILDREN_WORK_SHARE = 0.8
PARENT_AIT_WORK_SHARE = 1.0 - PARENT_CHILDREN_WORK_SHARE

# Human / plan aliases that may appear on instances or UI labels.
STAGE_STATUS_ALIASES: dict[str, str] = {
    "RESERVED": ItemStatus.RESERVED.value,
    "ISSUED": ItemStatus.ISSUED.value,
    "INSTALLATION_IN_PROGRESS": ItemStatus.INSTALLATION_IN_PROGRESS.value,
    "INSTALLATION IN PROGRESS": ItemStatus.INSTALLATION_IN_PROGRESS.value,
    "INSTALLING": ItemStatus.INSTALLATION_IN_PROGRESS.value,
    "IN_PROGRESS": ItemStatus.INSTALLATION_IN_PROGRESS.value,
    "INSTALLATION_REJECTED": ItemStatus.INSTALLATION_REJECTED.value,
    "INSTALLATION REJECTED": ItemStatus.INSTALLATION_REJECTED.value,
    "UNDER_TESTING_REVIEW": ItemStatus.UNDER_TESTING_REVIEW.value,
    "UNDER TESTING / REVIEW": ItemStatus.UNDER_TESTING_REVIEW.value,
    "UNDER TESTING": ItemStatus.UNDER_TESTING_REVIEW.value,
    "TESTING": ItemStatus.UNDER_TESTING_REVIEW.value,
    "INSTALLED_VERIFIED": ItemStatus.INSTALLED_VERIFIED.value,
    "INSTALLED VERIFIED": ItemStatus.INSTALLED_VERIFIED.value,
    "VERIFIED": ItemStatus.INSTALLED_VERIFIED.value,
}

NOT_STARTED_STATUS = "NOT_STARTED"
STAGE_POLICY = "lifecycle_fractions"
BOTTLENECK_LIMIT = 10


def normalize_stage_status(status: Optional[str]) -> Optional[str]:
    """Map free-form / spaced labels onto Spec 09 ItemStatus codes."""
    raw = (status or "").strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper == NOT_STARTED_STATUS:
        return NOT_STARTED_STATUS
    if upper in STAGE_COMPLETION_FRACTION:
        return upper
    aliased = STAGE_STATUS_ALIASES.get(upper)
    if aliased:
        return aliased
    collapsed = upper.replace(" ", "_").replace("/", "_").replace("-", "_")
    while "__" in collapsed:
        collapsed = collapsed.replace("__", "_")
    if collapsed in STAGE_COMPLETION_FRACTION:
        return collapsed
    return STAGE_STATUS_ALIASES.get(collapsed, upper)


def stage_rank(status: Optional[str], *, defect_pending: bool = False) -> float:
    """Comparable rank for picking the more advanced of two lifecycle statuses."""
    return stage_fraction(status, defect_pending=defect_pending)


def stage_fraction(
    status: Optional[str], *, defect_pending: bool = False
) -> float:
    code = normalize_stage_status(status)
    if defect_pending and code == ItemStatus.INSTALLED_VERIFIED.value:
        code = ItemStatus.UNDER_TESTING_REVIEW.value
    if not code or code == NOT_STARTED_STATUS:
        return 0.0
    return float(STAGE_COMPLETION_FRACTION.get(code, 0.0))


def is_verified_leaf(status: Optional[str], *, defect_pending: bool = False) -> bool:
    if defect_pending:
        return False
    return normalize_stage_status(status) == ItemStatus.INSTALLED_VERIFIED.value


def node_has_own_coverage(node: "ProgressNode") -> bool:
    """True when lifecycle coverage was recorded on this node (not inherited)."""
    if node.cover_entity_type is None or node.cover_entity_id is None:
        return False
    return (
        node.cover_entity_type == node.entity_type
        and int(node.cover_entity_id) == int(node.entity_id)
    )


def weighted_average(pairs: list[tuple[float, float]]) -> float:
    """pairs: (progress_fraction, weight). Equal weights → simple mean."""
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return 0.0
    return sum(progress * weight for progress, weight in pairs) / total_w


def progress_pct(fraction: float) -> int:
    return int(round(max(0.0, min(1.0, fraction)) * 100))


def bottleneck_reason(status: Optional[str], *, defect_pending: bool = False) -> str:
    if defect_pending:
        return "fail_loop"
    code = normalize_stage_status(status)
    if not code or code == NOT_STARTED_STATUS:
        return "not_started"
    if code == ItemStatus.RESERVED.value:
        return "reserved"
    return code.lower()


@dataclass
class ProgressNode:
    entity_type: str
    entity_id: int
    name: str
    children: list["ProgressNode"] = field(default_factory=list)
    status: Optional[str] = None
    defect_pending: bool = False
    code: Optional[str] = None
    product_type: Optional[str] = None
    weight: int = 0
    progress: float = 0.0
    verified_leaves: int = 0
    path: str = ""
    cover_entity_type: Optional[str] = None
    cover_entity_id: Optional[int] = None
    cover_name: Optional[str] = None


def rollup_progress(node: ProgressNode, parent_path: str = "") -> ProgressNode:
    node.path = f"{parent_path} / {node.name}" if parent_path else node.name
    if not node.children:
        node.weight = 1
        node.progress = stage_fraction(node.status, defect_pending=node.defect_pending)
        node.verified_leaves = (
            1
            if is_verified_leaf(node.status, defect_pending=node.defect_pending)
            else 0
        )
        if node.cover_entity_type is None:
            node.cover_entity_type = node.entity_type
            node.cover_entity_id = node.entity_id
            node.cover_name = node.name
        return node
    for child in node.children:
        rollup_progress(child, node.path)
    node.weight = sum(child.weight for child in node.children)
    children_progress = weighted_average(
        [(child.progress, float(child.weight)) for child in node.children]
    )
    node.verified_leaves = sum(child.verified_leaves for child in node.children)
    # Own coverage (system / subsystem / module / unit AIT): credit most work
    # from children, keep a residual share for the parent's own lifecycle so
    # e.g. verified children + Reserved parent ≈ 82% (not 10% and not 100%).
    # Structural containers without coverage roll up children only.
    if node_has_own_coverage(node):
        parent_fraction = stage_fraction(
            node.status, defect_pending=node.defect_pending
        )
        node.progress = (
            PARENT_CHILDREN_WORK_SHARE * children_progress
            + PARENT_AIT_WORK_SHARE * parent_fraction
        )
    else:
        node.progress = children_progress
    return node


def collect_bottlenecks(
    root: ProgressNode, *, limit: int = BOTTLENECK_LIMIT
) -> list[dict[str, Any]]:
    incomplete: list[ProgressNode] = []

    def walk(node: ProgressNode) -> None:
        if node.children:
            if node_has_own_coverage(node) and not is_verified_leaf(
                node.status, defect_pending=node.defect_pending
            ):
                incomplete.append(node)
            for child in node.children:
                walk(child)
            return
        if not is_verified_leaf(node.status, defect_pending=node.defect_pending):
            incomplete.append(node)

    walk(root)

    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for leaf in incomplete:
        cover_type = leaf.cover_entity_type or leaf.entity_type
        cover_id = (
            leaf.cover_entity_id
            if leaf.cover_entity_id is not None
            else leaf.entity_id
        )
        status = leaf.status or NOT_STARTED_STATUS
        key = (cover_type, cover_id, status, bool(leaf.defect_pending))
        row = grouped.get(key)
        if row is None:
            grouped[key] = {
                "entity_type": cover_type,
                "entity_id": int(cover_id),
                "name": leaf.cover_name or leaf.name,
                "path": leaf.path,
                "status": None if status == NOT_STARTED_STATUS else status,
                "defect_pending": bool(leaf.defect_pending),
                "weight": 1,
                "reason": bottleneck_reason(
                    leaf.status, defect_pending=leaf.defect_pending
                ),
            }
        else:
            row["weight"] += 1

    ranked = sorted(
        grouped.values(),
        key=lambda row: (
            0 if row["reason"] == "fail_loop" else 1,
            -int(row["weight"]),
            str(row["path"]),
        ),
    )
    return ranked[:limit]
