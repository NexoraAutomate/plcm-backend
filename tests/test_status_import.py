"""Status CSV / Excel import."""

from __future__ import annotations

import pytest

from app.services.entity_list_import_service import build_xlsx
from app.services.status_import_service import (
    StatusImportError,
    build_status_type_aliases,
    normalize_status_type,
    parse_status_file,
    suggest_color_for_status_name,
)


def test_parse_csv_with_required_headers():
    content = (
        "Status,Description,Entity Type\n"
        "Design,Initial design,projects\n"
        "Available,In stock,units\n"
    ).encode("utf-8")
    rows = parse_status_file(content, "statuses.csv")
    assert rows[0]["status"] == "Design"
    assert rows[0]["description"] == "Initial design"
    assert rows[0]["entity type"] == "projects"
    assert rows[1]["status"] == "Available"


def test_parse_xlsx():
    content = build_xlsx(
        [
            ["Status", "Description", "Entity Type"],
            ["Open", "Order open", "orders"],
        ]
    )
    rows = parse_status_file(content, "statuses.xlsx")
    assert rows == [
        {"status": "Open", "description": "Order open", "entity type": "orders"}
    ]


def test_normalize_status_type_allows_any():
    aliases = build_status_type_aliases()
    assert normalize_status_type("projects", aliases) == "projects"
    assert normalize_status_type("Project", aliases) == "projects"
    assert normalize_status_type("Unit", aliases) == "units"
    assert normalize_status_type("inventory", aliases) == "inventory"
    assert normalize_status_type("Custom Type", aliases) == "Custom Type"


def test_suggest_color_known_name():
    assert suggest_color_for_status_name("AVAILABLE") == "#548235"
    assert suggest_color_for_status_name("Unknown Status") == "#2F5496"


def test_missing_required_column():
    content = "Status,Entity Type\nDesign,projects\n".encode("utf-8")
    rows = parse_status_file(content, "statuses.csv")
    from app.services.status_import_service import import_status_rows

    class _FakeSession:
        def exec(self, *_args, **_kwargs):
            class _Result:
                def first(self):
                    return None

                def all(self):
                    return []

            return _Result()

    with pytest.raises(StatusImportError, match="Description"):
        import_status_rows(_FakeSession(), rows, dry_run=True)
