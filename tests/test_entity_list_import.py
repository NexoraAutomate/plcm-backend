"""Entity List CSV / Excel import and export."""

from __future__ import annotations

import pytest

from app.services.entity_list_import_service import (
    EntityListImportError,
    build_entity_list_csv,
    build_type_aliases,
    build_xlsx,
    parse_entity_list_file,
    resolve_entity_type,
)


def test_parse_csv_with_friendly_headers():
    content = (
        "Entity Name,Entity Type,Abbreviation\n"
        "Antenna Pedestal,Unit,AP\n"
        "Power Supply,component,ps\n"
    ).encode("utf-8")
    rows = parse_entity_list_file(content, "entities.csv")
    assert rows[0]["entity name"] == "Antenna Pedestal"
    assert rows[0]["entity type"] == "Unit"
    assert rows[1]["abbreviation"] == "ps"


def test_parse_csv_semicolon_and_aliases():
    content = "name;hierarchy_type\nRadar;system\n".encode("utf-8")
    rows = parse_entity_list_file(content, "entities.csv")
    assert rows == [{"name": "Radar", "hierarchy type": "system"}]


def test_parse_xlsx():
    content = build_xlsx(
        [
            ["entity_name", "entity_type"],
            ["Harness Antenna", "module"],
        ]
    )
    rows = parse_entity_list_file(content, "entities.xlsx")
    assert rows == [{"entity name": "Harness Antenna", "entity type": "module"}]


def test_old_xls_rejected():
    with pytest.raises(EntityListImportError, match="xlsx or .csv"):
        parse_entity_list_file(b"not-excel", "entities.xls")


def test_empty_file_rejected():
    with pytest.raises(EntityListImportError, match="empty"):
        parse_entity_list_file(b"", "entities.csv")


def test_resolve_entity_type_aliases():
    aliases = build_type_aliases()
    assert resolve_entity_type("SYSTEM", aliases) == "system"
    assert resolve_entity_type("Units", aliases) == "unit"
    assert resolve_entity_type("Component", aliases) == "component"
    assert resolve_entity_type("not-a-level", aliases) is None


def test_export_csv_round_trip():
    matrix = [
        ["entity_name", "entity_type", "abbreviation"],
        ["Antenna Pedestal", "unit", "AP"],
        ['Power "Supply"', "component", "PS"],
    ]
    content = build_entity_list_csv(matrix)
    rows = parse_entity_list_file(content, "entity-list.csv")
    assert rows[0]["entity name"] == "Antenna Pedestal"
    assert rows[0]["entity type"] == "unit"
    assert rows[1]["entity name"] == 'Power "Supply"'


def test_export_xlsx_round_trip():
    matrix = [
        ["entity_name", "entity_type", "abbreviation"],
        ["Antenna & Pedestal", "unit", "AP"],
    ]
    content = build_xlsx(matrix)
    rows = parse_entity_list_file(content, "entity-list.xlsx")
    assert rows == [
        {
            "entity name": "Antenna & Pedestal",
            "entity type": "unit",
            "abbreviation": "AP",
        }
    ]
