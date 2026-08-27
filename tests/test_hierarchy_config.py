"""Spec 01 — hierarchy configuration domain + service tests."""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session, select

from app.database import engine
from app.domain.hierarchy_config import (
    FIXED_HIERARCHY_LEVELS,
    HierarchyConfigLevel,
    InventorySource,
    fixed_levels_payload,
)
from app.models.tables import Hierarchy, HierarchyConfiguration
from app.services.entity_list_service import find_entity_list_entry
from app.services.hierarchy_config_service import (
    HierarchyConfigError,
    _validate_nodes,
    _validate_product_types,
    configuration_to_dict,
    create_configuration,
    delete_configuration,
    list_configurations,
    set_available,
    update_configuration,
)
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.hierarchy_service import get_next_hierarchy_id, sync_hierarchy_id_sequence


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    ensure_user_management_schema()


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s


@pytest.fixture()
def catalog(session: Session):
    for name, level in (
        ("Comm", "system"),
        ("Power", "system"),
        ("A", "system"),
        ("B", "subsystem"),
        ("RF", "subsystem"),
    ):
        _ensure_catalog(session, name, level)


@pytest.fixture()
def unique_code():
    return f"T-{uuid.uuid4().hex[:10].upper()}"


def _ensure_catalog(session: Session, name: str, hierarchy_type: str) -> None:
    if find_entity_list_entry(session, name=name, hierarchy_type=hierarchy_type):
        return
    row = Hierarchy(
        id=get_next_hierarchy_id(session),
        name=name,
        hierarchy_type=hierarchy_type,
        abbreviation=name[:4].upper(),
    )
    session.add(row)
    session.commit()
    sync_hierarchy_id_sequence(session)


def _cleanup(session: Session, *codes: str) -> None:
    rows = session.exec(
        select(HierarchyConfiguration).where(HierarchyConfiguration.code.in_(list(codes)))
    ).all()
    for row in rows:
        delete_configuration(session, row.id, hard=True)


def test_fixed_level_order():
    codes = [level.value for level in FIXED_HIERARCHY_LEVELS]
    assert codes == [
        "product_type",
        "flight",
        "sdls",
        "system",
        "subsystem",
        "module",
        "unit",
        "component",
    ]
    payload = fixed_levels_payload()
    assert len(payload) == 8
    assert payload[0]["code"] == HierarchyConfigLevel.PRODUCT_TYPE.value
    assert payload[-1]["is_template_level"] is True


def test_validate_product_types_requires_unique_codes():
    with pytest.raises(HierarchyConfigError, match="At least one"):
        _validate_product_types([])
    with pytest.raises(HierarchyConfigError, match="unique"):
        _validate_product_types(
            [
                {"code": "SSDLS-1", "name": "A"},
                {"code": "SSDLS-1", "name": "B"},
            ]
        )


def test_validate_nodes_parent_rules(session: Session):
    with pytest.raises(HierarchyConfigError, match="parent"):
        _validate_nodes(
            session,
            [
                {"client_key": "s1", "level": "system", "name": "Comm"},
                {
                    "client_key": "u1",
                    "parent_client_key": "s1",
                    "level": "unit",
                    "name": "Skip",
                },
            ]
        )


def test_create_two_configs_and_available_filter(session: Session, unique_code: str, catalog):
    code_a = f"{unique_code}-A"
    code_b = f"{unique_code}-B"
    _cleanup(session, code_a, code_b)
    try:
        create_configuration(
            session,
            {
                "code": code_a,
                "name": "SSDLS-1 Template",
                "product_types": [{"code": "SSDLS-1", "name": "High Data Rate"}],
                "nodes": [{"client_key": "s1", "level": "system", "name": "Comm"}],
            },
        )
        b = create_configuration(
            session,
            {
                "code": code_b,
                "name": "SSDLS-2 Template",
                "product_types": [{"code": "SSDLS-2", "name": "Low Data Rate"}],
                "nodes": [{"client_key": "s1", "level": "system", "name": "Power"}],
            },
        )
        set_available(session, b.id, False)
        available_codes = {c.code for c in list_configurations(session, available_only=True)}
        assert code_a in available_codes
        assert code_b not in available_codes
    finally:
        _cleanup(session, code_a, code_b)


def test_duplicate_code_rejected(session: Session, unique_code: str):
    _cleanup(session, unique_code)
    try:
        payload = {
            "code": unique_code,
            "name": "One",
            "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
            "nodes": [],
        }
        create_configuration(session, payload)
        with pytest.raises(HierarchyConfigError, match="already exists"):
            create_configuration(session, {**payload, "name": "Two"})
    finally:
        _cleanup(session, unique_code)


def test_duplicate_name_rejected(session: Session, unique_code: str):
    code_a = f"{unique_code}-a"
    code_b = f"{unique_code}-b"
    _cleanup(session, code_a, code_b)
    try:
        create_configuration(
            session,
            {
                "code": code_a,
                "name": "Shared Name",
                "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
                "nodes": [],
            },
        )
        with pytest.raises(HierarchyConfigError, match="name .* already exists"):
            create_configuration(
                session,
                {
                    "code": code_b,
                    "name": "shared name",
                    "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
                    "nodes": [],
                },
            )
    finally:
        _cleanup(session, code_a, code_b)


def test_update_bumps_version_and_replaces_nodes(session: Session, unique_code: str, catalog):
    _cleanup(session, unique_code)
    try:
        cfg = create_configuration(
            session,
            {
                "code": unique_code,
                "name": "Versioned",
                "product_types": [
                    {"code": "SSDLS-1", "name": "HDR"},
                    {"code": "SSDLS-2", "name": "LDR"},
                ],
                "nodes": [{"client_key": "s1", "level": "system", "name": "A"}],
            },
        )
        assert cfg.version == 1
        updated = update_configuration(
            session,
            cfg.id,
            {
                "name": "Versioned 2",
                "nodes": [
                    {"client_key": "s1", "level": "system", "name": "A"},
                    {
                        "client_key": "ss1",
                        "parent_client_key": "s1",
                        "level": "subsystem",
                        "name": "B",
                    },
                ],
            },
        )
        assert updated.version == 2
        assert updated.name == "Versioned 2"
        refreshed = session.get(HierarchyConfiguration, cfg.id)
        assert refreshed is not None
        assert len(refreshed.nodes) == 2
    finally:
        _cleanup(session, unique_code)


def test_inventory_source_defaults_to_turnkey(session: Session, unique_code: str, catalog):
    _cleanup(session, unique_code)
    try:
        cfg = create_configuration(
            session,
            {
                "code": unique_code,
                "name": f"Src {unique_code}",
                "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
                "nodes": [
                    {"client_key": "s1", "level": "system", "name": "Comm"},
                    {
                        "client_key": "ss1",
                        "parent_client_key": "s1",
                        "level": "subsystem",
                        "name": "RF",
                    },
                ],
            },
        )
        payload = configuration_to_dict(cfg)
        sources = {n["name"]: n["inventory_source"] for n in payload["nodes"]}
        assert sources["Comm"] == InventorySource.TURNKEY.value
        assert sources["RF"] == InventorySource.TURNKEY.value
    finally:
        _cleanup(session, unique_code)


def test_inventory_source_build_round_trip(session: Session, unique_code: str, catalog):
    _cleanup(session, unique_code)
    try:
        cfg = create_configuration(
            session,
            {
                "code": unique_code,
                "name": f"Build {unique_code}",
                "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
                "nodes": [
                    {
                        "client_key": "s1",
                        "level": "system",
                        "name": "Comm",
                        "inventory_source": "build_from_children",
                    },
                    {
                        "client_key": "ss1",
                        "parent_client_key": "s1",
                        "level": "subsystem",
                        "name": "RF",
                        "inventory_source": "turnkey",
                    },
                ],
            },
        )
        payload = configuration_to_dict(cfg)
        by_name = {n["name"]: n["inventory_source"] for n in payload["nodes"]}
        assert by_name["Comm"] == InventorySource.BUILD_FROM_CHILDREN.value
        assert by_name["RF"] == InventorySource.TURNKEY.value
    finally:
        _cleanup(session, unique_code)


def test_build_from_children_rejected_on_leaf(session: Session, catalog):
    with pytest.raises(HierarchyConfigError, match="build-from-children"):
        _validate_nodes(
            session,
            [
                {
                    "client_key": "s1",
                    "level": "system",
                    "name": "Comm",
                    "inventory_source": "build_from_children",
                }
            ],
        )
