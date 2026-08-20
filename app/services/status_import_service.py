"""Parse CSV/Excel sheets and bulk-create Status rows.

Required columns: Status | Description | Entity Type.
Entity Type may be any non-empty value (known labels are normalized when possible).
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.domain.workflow_status import ITEM_STATUS_COLORS, PROJECT_STATUS_COLORS
from app.models.tables import AppDefinitions, Status
from app.services.app_definitions_service import (
    DEFAULT_APP_DEFINITIONS,
    entity_label,
)
from app.services.entity_list_import_service import (
    EntityListImportError,
    parse_entity_list_file,
    _normalize_header,
    _pick_field,
)

StatusImportError = EntityListImportError

STATUS_HEADERS = frozenset({"status", "status name", "status_name", "name"})
DESCRIPTION_HEADERS = frozenset({"description", "desc", "details"})
ENTITY_TYPE_HEADERS = frozenset(
    {
        "entity type",
        "entity_type",
        "status type",
        "status_type",
        "type",
        "category",
    }
)

# Optional aliases only — custom entity types are stored as provided.
KNOWN_STATUS_TYPE_KEYS = (
    "projects",
    "systems",
    "subsystems",
    "modules",
    "units",
    "components",
    "orders",
    "customers",
)

DEFAULT_STATUS_COLOR = "#2F5496"

_KNOWN_STATUS_COLORS: dict[str, str] = {
    **{k.value: v for k, v in ITEM_STATUS_COLORS.items()},
    **{k.value: v for k, v in PROJECT_STATUS_COLORS.items()},
    "Available": "#548235",
    "Reserved": "#2E75B6",
    "Issued": "#0070C0",
    "Installation In Progress": "#C55A11",
    "Under Testing / Review": "#BF9000",
    "Installed Verified": "#00B050",
    "Returned": "#7030A0",
    "Inspection": "#ED7D31",
    "Reusable": "#70AD47",
    "Repairable": "#C55A11",
    "Scrapped": "#595959",
    "Draft": "#7F7F7F",
    "Approved": "#00B050",
    "Hierarchy Generated": "#2E75B6",
    "Ready For Inventory": "#548235",
    "Cancelled": "#C00000",
    "Completed": "#375623",
    "Ready To Deliver": "#2F5496",
    "Superseded": "#7030A0",
    "Design": "#2E75B6",
    "Execution": "#0070C0",
    "Monitoring": "#BF9000",
    "On Hold": "#C55A11",
    "Active": "#00B050",
    "Inactive": "#595959",
    "Open": "#0070C0",
    "Resolved": "#548235",
    "Rejected": "#C00000",
}


def suggest_color_for_status_name(name: str) -> str:
    if name in _KNOWN_STATUS_COLORS:
        return _KNOWN_STATUS_COLORS[name]
    upper = name.upper().replace(" ", "_")
    if upper in _KNOWN_STATUS_COLORS:
        return _KNOWN_STATUS_COLORS[upper]
    return DEFAULT_STATUS_COLOR


def build_status_type_aliases(definitions: AppDefinitions | None = None) -> dict[str, str]:
    """Map friendly labels → canonical keys for known hierarchy/admin types."""
    aliases: dict[str, str] = {}
    level_to_key = {
        "project": "projects",
        "system": "systems",
        "subsystem": "subsystems",
        "module": "modules",
        "unit": "units",
        "component": "components",
    }
    for key in KNOWN_STATUS_TYPE_KEYS:
        aliases[key] = key
        singular = key[:-1] if key.endswith("s") else key
        aliases[singular] = key

    for level, key in level_to_key.items():
        aliases[level] = key
        aliases[f"{level}s"] = key
        labels = [
            DEFAULT_APP_DEFINITIONS.get(f"label_{level}", level),
            DEFAULT_APP_DEFINITIONS.get(f"label_{level}s", f"{level}s"),
        ]
        if definitions is not None:
            labels.append(entity_label(definitions, level))
            labels.append(entity_label(definitions, level, plural=True))
        for label in labels:
            if label:
                aliases[_normalize_header(str(label))] = key

    aliases["order"] = "orders"
    aliases["customer"] = "customers"
    return aliases


def normalize_status_type(raw: str, aliases: dict[str, str]) -> str:
    """Use a known alias when available; otherwise keep the trimmed value."""
    trimmed = (raw or "").strip()
    if not trimmed:
        return ""
    return aliases.get(_normalize_header(trimmed), trimmed)


def parse_status_file(content: bytes, filename: str) -> list[dict[str, str]]:
    return parse_entity_list_file(content, filename)


def _required_columns(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise StatusImportError("File has a header row but no data rows.")
    keys = {_normalize_header(k) for k in rows[0].keys()}
    missing: list[str] = []
    if not (keys & STATUS_HEADERS):
        missing.append("Status")
    if not (keys & DESCRIPTION_HEADERS):
        missing.append("Description")
    if not (keys & ENTITY_TYPE_HEADERS):
        missing.append("Entity Type")
    if missing:
        raise StatusImportError(
            "File is missing required columns: "
            + ", ".join(missing)
            + ". Expected headers: Status, Description, Entity Type."
        )


def import_status_rows(
    session: Session,
    rows: list[dict[str, str]],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    _required_columns(rows)
    definitions = session.exec(select(AppDefinitions).limit(1)).first()
    aliases = build_status_type_aliases(definitions)

    existing = list(session.exec(select(Status)).all())
    seen = {
        (
            (entry.status_name or "").strip().lower(),
            (entry.status_type or "").strip().lower(),
        )
        for entry in existing
    }

    errors: list[dict] = []
    payloads: list[dict[str, Any]] = []
    skipped = 0

    for index, row in enumerate(rows, start=2):
        name = _pick_field(row, STATUS_HEADERS)
        description = _pick_field(row, DESCRIPTION_HEADERS)
        type_raw = _pick_field(row, ENTITY_TYPE_HEADERS)
        row_errors: list[str] = []

        if not name and not type_raw and not description:
            continue
        if not name:
            row_errors.append("'Status' is required")
        if not type_raw:
            row_errors.append("'Entity Type' is required")

        status_type = normalize_status_type(type_raw, aliases) if type_raw else ""

        if row_errors:
            errors.append({"row": index, "errors": row_errors})
            continue

        key = (name.lower(), status_type.lower())
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        payloads.append(
            {
                "status_name": name,
                "description": description or None,
                "status_type": status_type,
                "color": suggest_color_for_status_name(name),
            }
        )

    if errors:
        raise StatusImportError(
            "File contains validation errors",
            errors=errors,
        )

    if dry_run:
        return {
            "dry_run": True,
            "valid_rows": len(payloads),
            "skipped": skipped,
            "errors": [],
        }

    created: list[dict[str, Any]] = []
    if payloads:
        db_statuses = [Status(**payload) for payload in payloads]
        session.add_all(db_statuses)
        session.commit()
        for entry in db_statuses:
            session.refresh(entry)
            created.append(
                {
                    "id": entry.id,
                    "status_name": entry.status_name,
                    "status_type": entry.status_type,
                }
            )

    return {
        "imported": len(created),
        "skipped": skipped,
        "rows": created,
        "errors": [],
    }
