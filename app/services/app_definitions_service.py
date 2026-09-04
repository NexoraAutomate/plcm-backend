"""Persisted admin naming templates and hierarchy entity labels."""

from __future__ import annotations

import re
import math
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.models.tables import AppDefinitions, User
from app.services.audit_service import write_audit_log

DEFAULT_APP_DEFINITIONS = {
    "serial_number_template": "{project}-{name}{seq}",
    "part_number_template": "{project}-{name}{seq}-PN",
    "configuration_item_template": "{project}-{name}{seq}-CI",
    "sku_template": "{serial}-SKU",
    "label_project": "Project",
    "label_projects": "Projects",
    "abbrev_project": "PROJ",
    "label_system": "System",
    "label_systems": "Systems",
    "label_subsystem": "Subsystem",
    "label_subsystems": "Subsystems",
    "label_module": "Module",
    "label_modules": "Modules",
    "label_unit": "Unit",
    "label_units": "Units",
    "label_component": "Component",
    "label_components": "Components",
    "abbrev_system": "SYS",
    "abbrev_subsystem": "SUB",
    "abbrev_module": "MOD",
    "abbrev_unit": "UNIT",
    "abbrev_component": "COMP",
    "part_template_system": "PN-{levelAbbr}-{entityAbbr}-{year}-{vendor}-{seq:5}",
    "serial_template_system": "SN-{levelAbbr}-{entityAbbr}-{year}-{pnSeq:5}-{seq:5}",
    "part_template_subsystem": "PN-{levelAbbr}-{entityAbbr}-{year}-{vendor}-{seq:5}",
    "serial_template_subsystem": "SN-{levelAbbr}-{entityAbbr}-{year}-{pnSeq:5}-{seq:5}",
    "part_template_module": "PN-{levelAbbr}-{entityAbbr}-{year}-{vendor}-{seq:5}",
    "serial_template_module": "SN-{levelAbbr}-{entityAbbr}-{year}-{pnSeq:5}-{seq:5}",
    "part_template_unit": "PN-{levelAbbr}-{entityAbbr}-{year}-{vendor}-{seq:5}",
    "serial_template_unit": "SN-{levelAbbr}-{entityAbbr}-{year}-{pnSeq:5}-{seq:5}",
    "part_template_component": "PN-{levelAbbr}-{entityAbbr}-{year}-{vendor}-{seq:5}",
    "serial_template_component": "SN-{levelAbbr}-{entityAbbr}-{year}-{pnSeq:5}-{seq:5}",
    "inventory_label_code_type": "qr",
    "inventory_qr_size_in": 0.65,
    "inventory_barcode_width_in": 2.0,
    "inventory_barcode_height_in": 0.5,
    "inventory_qr_sticker_width_in": 1.25,
    "inventory_qr_sticker_height_in": 1.25,
    "inventory_barcode_sticker_width_in": 2.25,
    "inventory_barcode_sticker_height_in": 0.9,
    "inventory_location_tree": [],
}

ENTITY_LEVELS = ("project", "system", "subsystem", "module", "unit", "component")

TEMPLATE_FIELDS = (
    "serial_number_template",
    "part_number_template",
    "configuration_item_template",
    "sku_template",
    "part_template_system",
    "serial_template_system",
    "part_template_subsystem",
    "serial_template_subsystem",
    "part_template_module",
    "serial_template_module",
    "part_template_unit",
    "serial_template_unit",
    "part_template_component",
    "serial_template_component",
)

LABEL_FIELDS = (
    "label_project",
    "label_projects",
    "label_system",
    "label_systems",
    "label_subsystem",
    "label_subsystems",
    "label_module",
    "label_modules",
    "label_unit",
    "label_units",
    "label_component",
    "label_components",
)

ABBREV_FIELDS = (
    "abbrev_project",
    "abbrev_system",
    "abbrev_subsystem",
    "abbrev_module",
    "abbrev_unit",
    "abbrev_component",
)

LABEL_SETTING_FIELDS = (
    "inventory_label_code_type",
    "inventory_qr_size_in",
    "inventory_barcode_width_in",
    "inventory_barcode_height_in",
    "inventory_qr_sticker_width_in",
    "inventory_qr_sticker_height_in",
    "inventory_barcode_sticker_width_in",
    "inventory_barcode_sticker_height_in",
)

LOCATION_PRESET_FIELDS = (
    "inventory_location_tree",
)

_PADDED_TOKEN = re.compile(
    r"\{(seq|pnSeq|n)(?::(\d+))?\}|\{(project|name|level|Level|levelAbbr|entityAbbr|vendor|year|serial)\}"
)


def get_or_create_app_definitions(session: Session) -> AppDefinitions:
    row = session.exec(select(AppDefinitions).limit(1)).first()
    if row:
        # Backfill new columns on older rows (create_all won't alter existing).
        dirty = False
        for key, value in DEFAULT_APP_DEFINITIONS.items():
            if hasattr(row, key) and getattr(row, key) in (None, ""):
                setattr(row, key, value)
                dirty = True
        if dirty:
            session.add(row)
            session.commit()
            session.refresh(row)
        return row
    row = AppDefinitions(**DEFAULT_APP_DEFINITIONS)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def entity_label(definitions: AppDefinitions, level: str, *, plural: bool = False) -> str:
    key = level.strip().lower()
    if key not in ENTITY_LEVELS:
        return level.title() if level else "Entity"
    attr = f"label_{key}{'s' if plural else ''}"
    value = getattr(definitions, attr, None)
    if value and str(value).strip():
        return str(value).strip()
    return DEFAULT_APP_DEFINITIONS.get(attr, key.title())


def level_abbrev(definitions: AppDefinitions, level: str) -> str:
    key = level.strip().lower()
    if key not in ENTITY_LEVELS:
        return key.upper()[:4] if key else ""
    attr = f"abbrev_{key}"
    value = getattr(definitions, attr, None)
    if value and str(value).strip():
        return str(value).strip().upper()
    return DEFAULT_APP_DEFINITIONS.get(attr, key.upper()[:4])


def level_template(definitions: AppDefinitions, kind: str, level: str) -> str:
    """kind is 'part' or 'serial'."""
    key = level.strip().lower()
    if key in ENTITY_LEVELS:
        attr = f"{kind}_template_{key}"
        value = getattr(definitions, attr, None)
        if value and str(value).strip():
            return str(value).strip()
        fallback = DEFAULT_APP_DEFINITIONS.get(attr)
        if fallback:
            return fallback
    # Legacy global templates
    if kind == "part":
        return definitions.part_number_template or DEFAULT_APP_DEFINITIONS["part_number_template"]
    return definitions.serial_number_template or DEFAULT_APP_DEFINITIONS["serial_number_template"]


def inventory_label_code_type(session: Session) -> str:
    """Return the administrator-selected code format for inventory labels."""
    settings = get_or_create_app_definitions(session)
    return (
        settings.inventory_label_code_type
        if settings.inventory_label_code_type in {"qr", "barcode"}
        else "qr"
    )


def inventory_label_print_settings(session: Session) -> dict[str, float | str]:
    """Return the administrator-selected label format and physical dimensions."""
    settings = get_or_create_app_definitions(session)
    return {
        key: getattr(settings, key, DEFAULT_APP_DEFINITIONS[key])
        for key in LABEL_SETTING_FIELDS
    }


def _format_num(value: int, width: Optional[int]) -> str:
    if width and width > 0:
        return str(value).zfill(width)
    return str(value)


def apply_identifier_template(
    template: str,
    *,
    project: str = "",
    name: str = "",
    seq: int = 1,
    pn_seq: Optional[int] = None,
    level: str = "",
    level_label: str = "",
    level_abbr: str = "",
    entity_abbr: str = "",
    vendor: str = "",
    serial: str = "",
    year: Optional[str] = None,
) -> str:
    """Expand placeholders used by SN / PN / CI / SKU templates."""
    seq_n = max(1, int(seq or 1))
    pn_n = max(1, int(pn_seq if pn_seq is not None else seq_n))
    year_s = year or str(datetime.now(timezone.utc).year)

    simple = {
        "project": (project or "").strip(),
        "name": (name or "").strip(),
        "level": (level or "").strip().lower(),
        "Level": (level_label or level or "").strip(),
        "levelAbbr": (level_abbr or "").strip(),
        "entityAbbr": (entity_abbr or "").strip(),
        "vendor": (vendor or "").strip(),
        "year": year_s,
        "serial": (serial or "").strip(),
    }

    def repl(match: re.Match[str]) -> str:
        padded_key = match.group(1)
        width = match.group(2)
        plain = match.group(3)
        if padded_key:
            w = int(width) if width else None
            if padded_key == "seq":
                # unpadded {seq} keeps legacy blank-or--N behaviour when no width
                if w is None:
                    return f"-{seq_n}" if seq_n > 1 else ""
                return _format_num(seq_n, w)
            if padded_key == "pnSeq":
                return _format_num(pn_n, w)
            if padded_key == "n":
                return _format_num(seq_n, w)
        if plain:
            return simple.get(plain, "")
        return match.group(0)

    return _PADDED_TOKEN.sub(repl, template or "")


def build_entity_identifiers(
    definitions: AppDefinitions,
    *,
    project: str,
    name: str,
    seq: int = 1,
    pn_seq: Optional[int] = None,
    level: str = "",
    entity_abbr: str = "",
    vendor: str = "",
) -> dict[str, str]:
    level_label = entity_label(definitions, level) if level else ""
    l_abbr = level_abbrev(definitions, level) if level else ""
    e_abbr = (entity_abbr or "").strip().upper()
    pn = apply_identifier_template(
        level_template(definitions, "part", level),
        project=project,
        name=name,
        seq=pn_seq if pn_seq is not None else seq,
        pn_seq=pn_seq if pn_seq is not None else seq,
        level=level,
        level_label=level_label,
        level_abbr=l_abbr,
        entity_abbr=e_abbr,
        vendor=vendor,
    )
    serial = apply_identifier_template(
        level_template(definitions, "serial", level),
        project=project,
        name=name,
        seq=seq,
        pn_seq=pn_seq if pn_seq is not None else seq,
        level=level,
        level_label=level_label,
        level_abbr=l_abbr,
        entity_abbr=e_abbr,
        vendor=vendor,
        serial="",
    )
    ci = apply_identifier_template(
        definitions.configuration_item_template,
        project=project,
        name=name,
        seq=seq,
        level=level,
        level_label=level_label,
        level_abbr=l_abbr,
        entity_abbr=e_abbr,
        vendor=vendor,
        serial=serial,
    )
    sku = apply_identifier_template(
        definitions.sku_template,
        project=project,
        name=name,
        seq=seq,
        level=level,
        level_label=level_label,
        level_abbr=l_abbr,
        entity_abbr=e_abbr,
        vendor=vendor,
        serial=serial,
    )
    return {
        "serial_number": serial,
        "part_number": pn,
        "configuration_item": ci,
        "sku": sku,
    }


def _validate_template(value: str, field: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError(f"{field} cannot be empty")
    if len(cleaned) > 250:
        raise ValueError(f"{field} must be 250 characters or fewer")
    return cleaned


def _validate_label(value: str, field: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError(f"{field} cannot be empty")
    if len(cleaned) > 60:
        raise ValueError(f"{field} must be 60 characters or fewer")
    return cleaned


def _validate_abbrev(value: str, field: str) -> str:
    cleaned = (value or "").strip().upper()
    if not cleaned:
        raise ValueError(f"{field} cannot be empty")
    if len(cleaned) > 16:
        raise ValueError(f"{field} must be 16 characters or fewer")
    return cleaned


def _validate_inches(value: Any, field: str) -> float:
    try:
        cleaned = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if not math.isfinite(cleaned) or cleaned < 0.1 or cleaned > 20:
        raise ValueError(f"{field} must be between 0.1 and 20 inches")
    return round(cleaned, 3)


def _new_location_id() -> str:
    return f"loc_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _validate_named_node(raw: Any, *, kind: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Each {kind} must be an object")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError(f"{kind} name cannot be empty")
    if len(name) > 120:
        raise ValueError(f"{kind} name must be 120 characters or fewer")
    node_id = str(raw.get("id") or "").strip() or _new_location_id()
    if len(node_id) > 64:
        raise ValueError(f"{kind} id must be 64 characters or fewer")
    return {"id": node_id, "name": name}


def _validate_location_tree(value: Any, field: str) -> list[dict[str, Any]]:
    """Validate Room → Cabinet → Rack one-to-many tree."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of rooms")
    if len(value) > 100:
        raise ValueError(f"{field} cannot exceed 100 rooms")

    rooms: list[dict[str, Any]] = []
    room_names: set[str] = set()
    for room_raw in value:
        room = _validate_named_node(room_raw, kind="room")
        room_key = room["name"].casefold()
        if room_key in room_names:
            raise ValueError(f"Duplicate room name: {room['name']}")
        room_names.add(room_key)

        cabinets_raw = room_raw.get("cabinets") if isinstance(room_raw, dict) else []
        if cabinets_raw is None:
            cabinets_raw = []
        if not isinstance(cabinets_raw, list):
            raise ValueError(f"Room '{room['name']}' cabinets must be a list")
        if len(cabinets_raw) > 100:
            raise ValueError(f"Room '{room['name']}' cannot exceed 100 cabinets")

        cabinets: list[dict[str, Any]] = []
        cabinet_names: set[str] = set()
        for cabinet_raw in cabinets_raw:
            cabinet = _validate_named_node(cabinet_raw, kind="cabinet")
            cabinet_key = cabinet["name"].casefold()
            if cabinet_key in cabinet_names:
                raise ValueError(
                    f"Duplicate cabinet '{cabinet['name']}' under room '{room['name']}'"
                )
            cabinet_names.add(cabinet_key)

            racks_raw = cabinet_raw.get("racks") if isinstance(cabinet_raw, dict) else []
            if racks_raw is None:
                racks_raw = []
            if not isinstance(racks_raw, list):
                raise ValueError(f"Cabinet '{cabinet['name']}' racks must be a list")
            if len(racks_raw) > 100:
                raise ValueError(f"Cabinet '{cabinet['name']}' cannot exceed 100 racks")

            racks: list[dict[str, Any]] = []
            rack_names: set[str] = set()
            for rack_raw in racks_raw:
                rack = _validate_named_node(rack_raw, kind="rack")
                rack_key = rack["name"].casefold()
                if rack_key in rack_names:
                    raise ValueError(
                        f"Duplicate rack '{rack['name']}' under cabinet '{cabinet['name']}'"
                    )
                rack_names.add(rack_key)
                racks.append(rack)

            cabinets.append({**cabinet, "racks": racks})

        rooms.append({**room, "cabinets": cabinets})

    return rooms


def update_app_definitions(
    session: Session,
    updates: dict,
    *,
    actor: Optional[User] = None,
    ip_address: Optional[str] = None,
) -> AppDefinitions:
    settings = get_or_create_app_definitions(session)
    changed: list[tuple[str, object, object]] = []
    candidate = {
        key: getattr(settings, key, DEFAULT_APP_DEFINITIONS[key])
        for key in LABEL_SETTING_FIELDS
    }

    for key, value in updates.items():
        if not hasattr(settings, key):
            continue
        if value is None and key not in LOCATION_PRESET_FIELDS:
            continue
        if key in TEMPLATE_FIELDS:
            value = _validate_template(str(value), key)
        elif key in LABEL_FIELDS:
            value = _validate_label(str(value), key)
        elif key in ABBREV_FIELDS:
            value = _validate_abbrev(str(value), key)
        elif key == "inventory_label_code_type":
            value = str(value).strip().lower()
            if value not in {"qr", "barcode"}:
                raise ValueError("inventory_label_code_type must be qr or barcode")
        elif key in LABEL_SETTING_FIELDS:
            value = _validate_inches(value, key)
        elif key in LOCATION_PRESET_FIELDS:
            value = _validate_location_tree(value, key)
        else:
            continue
        if key in LABEL_SETTING_FIELDS:
            candidate[key] = value

        previous = getattr(settings, key)
        if previous == value:
            continue
        setattr(settings, key, value)
        changed.append((key, previous, value))

    if candidate["inventory_qr_size_in"] > min(
        candidate["inventory_qr_sticker_width_in"],
        candidate["inventory_qr_sticker_height_in"],
    ):
        raise ValueError("QR code size must fit inside the QR sticker dimensions")
    if candidate["inventory_qr_sticker_height_in"] < candidate["inventory_qr_size_in"] + 0.4:
        raise ValueError("QR sticker height must leave room for product identification")
    if candidate["inventory_barcode_width_in"] > candidate["inventory_barcode_sticker_width_in"]:
        raise ValueError("Barcode width must fit inside the barcode sticker width")
    if candidate["inventory_barcode_height_in"] > candidate["inventory_barcode_sticker_height_in"]:
        raise ValueError("Barcode height must fit inside the barcode sticker height")
    if candidate["inventory_barcode_sticker_height_in"] < candidate["inventory_barcode_height_in"] + 0.4:
        raise ValueError("Barcode sticker height must leave room for product identification")
    if (
        candidate["inventory_qr_sticker_width_in"] > 8.27
        or candidate["inventory_qr_sticker_height_in"] > 11.69
        or candidate["inventory_barcode_sticker_width_in"] > 8.27
        or candidate["inventory_barcode_sticker_height_in"] > 11.69
    ):
        raise ValueError("Sticker dimensions must fit within an A4 page")

    if not changed:
        return settings

    settings.updated_at = datetime.now(timezone.utc)
    if actor:
        settings.updated_by_id = actor.id
    session.add(settings)

    for key, previous, value in changed:
        write_audit_log(
            session,
            action="App Definitions Changed",
            actor=actor,
            resource_type="app_definitions",
            resource_id=settings.id,
            previous_value=f"{key}={previous}",
            new_value=f"{key}={value}",
            ip_address=ip_address,
        )

    session.commit()
    session.refresh(settings)
    return settings
