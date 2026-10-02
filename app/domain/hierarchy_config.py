"""
Spec 01 — Smart SDLS hierarchy configuration constants.

Fixed level order; Admin configures values/templates within levels,
not arbitrary reordering.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class HierarchyConfigLevel(str, Enum):
    PRODUCT_TYPE = "product_type"
    FLIGHT = "flight"
    SDLS = "sdls"
    SYSTEM = "system"
    SUBSYSTEM = "subsystem"
    MODULE = "module"
    UNIT = "unit"
    COMPONENT = "component"


# Spec 01 fixed order — never reorder
FIXED_HIERARCHY_LEVELS: tuple[HierarchyConfigLevel, ...] = (
    HierarchyConfigLevel.PRODUCT_TYPE,
    HierarchyConfigLevel.FLIGHT,
    HierarchyConfigLevel.SDLS,
    HierarchyConfigLevel.SYSTEM,
    HierarchyConfigLevel.SUBSYSTEM,
    HierarchyConfigLevel.MODULE,
    HierarchyConfigLevel.UNIT,
    HierarchyConfigLevel.COMPONENT,
)

FIXED_HIERARCHY_LEVEL_LABELS: dict[HierarchyConfigLevel, str] = {
    HierarchyConfigLevel.PRODUCT_TYPE: "Product Type",
    HierarchyConfigLevel.FLIGHT: "Flight",
    HierarchyConfigLevel.SDLS: "SDLS",
    HierarchyConfigLevel.SYSTEM: "System",
    HierarchyConfigLevel.SUBSYSTEM: "Subsystem",
    HierarchyConfigLevel.MODULE: "Module",
    HierarchyConfigLevel.UNIT: "Unit",
    HierarchyConfigLevel.COMPONENT: "Component",
}

# Lower template levels Admin defines once per config (same under every SDLS)
TEMPLATE_NODE_LEVELS: tuple[HierarchyConfigLevel, ...] = (
    HierarchyConfigLevel.SYSTEM,
    HierarchyConfigLevel.SUBSYSTEM,
    HierarchyConfigLevel.MODULE,
    HierarchyConfigLevel.UNIT,
    HierarchyConfigLevel.COMPONENT,
)

TEMPLATE_LEVEL_RANK: dict[HierarchyConfigLevel, int] = {
    level: index for index, level in enumerate(TEMPLATE_NODE_LEVELS)
}

# Preferred (adjacent) parent — used as UX default, not as a hard rule.
PARENT_TEMPLATE_LEVEL: dict[HierarchyConfigLevel, HierarchyConfigLevel | None] = {
    HierarchyConfigLevel.SYSTEM: None,
    HierarchyConfigLevel.SUBSYSTEM: HierarchyConfigLevel.SYSTEM,
    HierarchyConfigLevel.MODULE: HierarchyConfigLevel.SUBSYSTEM,
    HierarchyConfigLevel.UNIT: HierarchyConfigLevel.MODULE,
    HierarchyConfigLevel.COMPONENT: HierarchyConfigLevel.UNIT,
}


def is_valid_template_parent(
    parent_level: HierarchyConfigLevel | None,
    child_level: HierarchyConfigLevel,
) -> bool:
    """Any higher template level may parent any lower level; System is root."""
    if child_level == HierarchyConfigLevel.SYSTEM:
        return parent_level is None
    if parent_level is None:
        return False
    if parent_level not in TEMPLATE_LEVEL_RANK or child_level not in TEMPLATE_LEVEL_RANK:
        return False
    return TEMPLATE_LEVEL_RANK[parent_level] < TEMPLATE_LEVEL_RANK[child_level]


def allowed_parent_levels(
    child_level: HierarchyConfigLevel,
) -> tuple[HierarchyConfigLevel, ...]:
    if child_level == HierarchyConfigLevel.SYSTEM:
        return ()
    child_rank = TEMPLATE_LEVEL_RANK[child_level]
    return tuple(
        level for level in TEMPLATE_NODE_LEVELS if TEMPLATE_LEVEL_RANK[level] < child_rank
    )


def allowed_child_levels(
    parent_level: HierarchyConfigLevel,
) -> tuple[HierarchyConfigLevel, ...]:
    parent_rank = TEMPLATE_LEVEL_RANK[parent_level]
    return tuple(
        level for level in TEMPLATE_NODE_LEVELS if TEMPLATE_LEVEL_RANK[level] > parent_rank
    )


# Runtime FK attribute on the child table for (child_level, parent_level).
PARENT_FK_ATTR: dict[tuple[str, str], str] = {
    (HierarchyConfigLevel.SUBSYSTEM.value, HierarchyConfigLevel.SYSTEM.value): "system_id",
    (HierarchyConfigLevel.MODULE.value, HierarchyConfigLevel.SUBSYSTEM.value): "subsystem_id",
    (HierarchyConfigLevel.MODULE.value, HierarchyConfigLevel.SYSTEM.value): "system_id",
    (HierarchyConfigLevel.UNIT.value, HierarchyConfigLevel.MODULE.value): "module_id",
    (HierarchyConfigLevel.UNIT.value, HierarchyConfigLevel.SUBSYSTEM.value): "subsystem_id",
    (HierarchyConfigLevel.UNIT.value, HierarchyConfigLevel.SYSTEM.value): "system_id",
    (HierarchyConfigLevel.COMPONENT.value, HierarchyConfigLevel.UNIT.value): "unit_id",
    (HierarchyConfigLevel.COMPONENT.value, HierarchyConfigLevel.MODULE.value): "module_id",
    (HierarchyConfigLevel.COMPONENT.value, HierarchyConfigLevel.SUBSYSTEM.value): "subsystem_id",
    (HierarchyConfigLevel.COMPONENT.value, HierarchyConfigLevel.SYSTEM.value): "system_id",
}


class DefaultProductType(str, Enum):
    SSDLS_1 = "SSDLS-1"
    SSDLS_2 = "SSDLS-2"


DEFAULT_PRODUCT_TYPE_DEFS: list[dict[str, str]] = [
    {
        "code": DefaultProductType.SSDLS_1.value,
        "name": "High Data Rate",
        "description": "SSDLS-1 — High Data Rate product type",
    },
    {
        "code": DefaultProductType.SSDLS_2.value,
        "name": "Low Data Rate",
        "description": "SSDLS-2 — Low Data Rate product type",
    },
]

class InventorySource(str, Enum):
    """How a configuration node becomes inventory."""

    TURNKEY = "turnkey"
    BUILD_FROM_CHILDREN = "build_from_children"


_INVENTORY_SOURCE_ALIASES = {
    "turnkey": InventorySource.TURNKEY.value,
    "procured": InventorySource.TURNKEY.value,
    "build_from_children": InventorySource.BUILD_FROM_CHILDREN.value,
    "build": InventorySource.BUILD_FROM_CHILDREN.value,
}


def normalize_inventory_source(value: Any, *, default: str | None = None) -> str:
    """Return a canonical inventory_source, defaulting to turnkey when omitted."""
    fallback = default if default is not None else InventorySource.TURNKEY.value
    if value is None:
        return fallback
    raw = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if not raw:
        return fallback
    if raw not in _INVENTORY_SOURCE_ALIASES:
        allowed = ", ".join(sorted({src.value for src in InventorySource}))
        raise ValueError(f"inventory_source must be one of: {allowed}")
    return _INVENTORY_SOURCE_ALIASES[raw]


def is_build_from_children(value: Any) -> bool:
    try:
        return (
            normalize_inventory_source(value) == InventorySource.BUILD_FROM_CHILDREN.value
        )
    except ValueError:
        return False


CONFIG_RULE_NOTES_DEFAULT = (
    "Customer order defines Product Type, number of Flights, and number of SDLS "
    "per Flight (project scope — Spec 02). Admin defines the common lower-level "
    "hierarchy (System → Component) once in this configuration."
)


def fixed_levels_payload() -> list[dict[str, str | int]]:
    return [
        {
            "code": level.value,
            "label": FIXED_HIERARCHY_LEVEL_LABELS[level],
            "order": index,
            "is_template_level": level in TEMPLATE_NODE_LEVELS,
        }
        for index, level in enumerate(FIXED_HIERARCHY_LEVELS)
    ]
