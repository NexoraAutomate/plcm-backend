"""
Spec 01 — Smart SDLS hierarchy configuration constants.

Fixed level order; Admin configures values/templates within levels,
not arbitrary reordering.
"""

from __future__ import annotations

from enum import Enum


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

PARENT_TEMPLATE_LEVEL: dict[HierarchyConfigLevel, HierarchyConfigLevel | None] = {
    HierarchyConfigLevel.SYSTEM: None,
    HierarchyConfigLevel.SUBSYSTEM: HierarchyConfigLevel.SYSTEM,
    HierarchyConfigLevel.MODULE: HierarchyConfigLevel.SUBSYSTEM,
    HierarchyConfigLevel.UNIT: HierarchyConfigLevel.MODULE,
    HierarchyConfigLevel.COMPONENT: HierarchyConfigLevel.UNIT,
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
