"""Inventory CSV / JSON import and export.

All inventory types are stored as one catalog row per part number, with
individual physical units represented as InventoryInstance children.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.tables import Inventory, InventoryInstance
from app.services.entity_list_service import EntityListError, validate_inventory_entity_name
from app.services.inventory_service import (
    create_inventory_instance,
    find_inventory_group,
    find_inventory_instance_by_serial,
    normalize_part_number,
    sync_inventory_quantity,
)

CSV_VALID_TYPES = {"system", "subsystem", "module", "unit", "component"}

CSV_EXPORT_FIELDS = [
    "id",
    "name",
    "inventory_type",
    "part_number",
    "original_part_number",
    "serial_number",
    "serial_numbers",
    "original_serial_number",
    "quantity",
    "description",
    "oem_name",
    "configuration_item",
    "sku",
    "location",
    "holder_user_id",
    "status_id",
    "added_date",
    "shelf_life_expires_at",
    "installation_date",
    "installed_by_id",
    "picture_url",
    "entity_id",
    "updated_at",
]

CSV_IMPORT_REQUIRED = ["name", "inventory_type"]

JSON_EXPORT_VERSION = 1

_SERIAL_SPLIT = re.compile(r"[;|,\n]+")


@dataclass
class ImportSerial:
    serial_number: str
    original_serial_number: Optional[str] = None
    location: Optional[str] = None
    configuration_item: Optional[str] = None
    shelf_life_expires_at: Optional[datetime] = None
    source_row: int = 0


@dataclass
class ImportGroup:
    name: str
    inventory_type: str
    part_number: Optional[str] = None
    original_part_number: Optional[str] = None
    description: Optional[str] = None
    oem_name: Optional[str] = None
    configuration_item: Optional[str] = None
    sku: Optional[str] = None
    location: Optional[str] = None
    quantity: int = 0
    shelf_life_expires_at: Optional[datetime] = None
    serials: list[ImportSerial] = field(default_factory=list)
    source_rows: list[int] = field(default_factory=list)


def group_key(name: str, inventory_type: str, part_number: Optional[str]) -> tuple[str, str, str]:
    return (
        (name or "").strip().lower(),
        (inventory_type or "").strip().lower(),
        normalize_part_number(part_number),
    )


def split_serial_numbers(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in _SERIAL_SPLIT.split(text) if part.strip()]


def parse_datetime_value(raw: Optional[str]) -> Optional[datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"must be ISO 8601 datetime, got: {text!r}")


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def instance_serial(instance: InventoryInstance) -> str:
    return (instance.original_serial_number or instance.serial_number or "").strip()


def _group_location(inventory: Inventory, instances: list[InventoryInstance]) -> Optional[str]:
    if (inventory.location or "").strip():
        return inventory.location
    locations = [
        (inst.location or "").strip()
        for inst in instances
        if (inst.location or "").strip()
    ]
    unique = list(dict.fromkeys(locations))
    return unique[0] if unique else None


def inventory_to_export_dict(inventory: Inventory, instances: list[InventoryInstance]) -> dict[str, Any]:
    serials = [instance_serial(inst) for inst in instances if instance_serial(inst)]
    location = _group_location(inventory, instances)
    quantity = len(instances)
    return {
        "id": inventory.id,
        "name": inventory.name,
        "inventory_type": inventory.inventory_type,
        "part_number": inventory.part_number,
        "original_part_number": inventory.original_part_number or inventory.part_number,
        "serial_number": None,
        "serial_numbers": serials,
        "original_serial_number": None,
        "quantity": quantity,
        "description": inventory.description,
        "oem_name": inventory.oem_name,
        "configuration_item": inventory.configuration_item,
        "sku": inventory.sku,
        "location": location,
        "holder_user_id": inventory.holder_user_id,
        "status_id": inventory.status_id,
        "added_date": _iso(inventory.added_date),
        "shelf_life_expires_at": _iso(inventory.shelf_life_expires_at),
        "installation_date": _iso(inventory.installation_date),
        "installed_by_id": inventory.installed_by_id,
        "picture_url": inventory.picture_url,
        "entity_id": inventory.entity_id,
        "updated_at": _iso(inventory.updated_at),
        "instances": [
            {
                "id": inst.id,
                "serial_number": inst.serial_number,
                "original_serial_number": inst.original_serial_number or inst.serial_number,
                "location": inst.location,
                "configuration_item": inst.configuration_item,
                "holder_user_id": inst.holder_user_id,
                "status_id": inst.status_id,
                "added_date": _iso(inst.added_date),
                "shelf_life_expires_at": _iso(inst.shelf_life_expires_at),
            }
            for inst in instances
        ],
    }


def build_export_payload(session: Session, items: list[Inventory]) -> dict[str, Any]:
    exported = []
    for item in items:
        instances = list(
            session.exec(
                select(InventoryInstance)
                .where(InventoryInstance.inventory_id == item.id)
                .order_by(InventoryInstance.id)
            ).all()
        )
        exported.append(inventory_to_export_dict(item, instances))
    return {"version": JSON_EXPORT_VERSION, "items": exported}


def build_export_csv(session: Session, items: list[Inventory]) -> str:
    payload = build_export_payload(session, items)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_EXPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for item in payload["items"]:
        row = dict(item)
        serials = row.get("serial_numbers") or []
        row["serial_numbers"] = ";".join(serials)
        row["serial_number"] = ""
        row["original_serial_number"] = ""
        writer.writerow(row)
    return output.getvalue()


def _blank_to_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_zero(raw: Any, *, row_num: int, errors: list[dict]) -> int:
    text = "" if raw is None else str(raw).strip()
    if not text:
        return 0
    try:
        quantity = int(text)
    except (TypeError, ValueError):
        errors.append({"row": row_num, "errors": [f"'quantity' must be an integer, got: {raw!r}"]})
        return 0
    if quantity < 0:
        errors.append({"row": row_num, "errors": ["'quantity' cannot be negative"]})
        return 0
    return quantity


def _parse_shelf(raw: Any, *, row_num: int, errors: list[dict]) -> Optional[datetime]:
    text = _blank_to_none(raw)
    if not text:
        return None
    try:
        return parse_datetime_value(text)
    except ValueError as exc:
        errors.append({"row": row_num, "errors": [f"'shelf_life_expires_at' {exc}"]})
        return None


def _append_serials(group: ImportGroup, serials: list[str], *, row_num: int, location: Optional[str], configuration_item: Optional[str], original_serial: Optional[str], shelf: Optional[datetime]) -> None:
    seen = {item.serial_number.lower() for item in group.serials}
    for index, serial in enumerate(serials):
        key = serial.lower()
        if key in seen:
            continue
        seen.add(key)
        group.serials.append(
            ImportSerial(
                serial_number=serial,
                original_serial_number=original_serial if index == 0 and original_serial else serial,
                location=location,
                configuration_item=configuration_item,
                shelf_life_expires_at=shelf,
                source_row=row_num,
            )
        )


def _upsert_group(
    groups: dict[tuple[str, str, str], ImportGroup],
    *,
    name: str,
    inventory_type: str,
    part_number: Optional[str],
    original_part_number: Optional[str],
    description: Optional[str],
    oem_name: Optional[str],
    configuration_item: Optional[str],
    sku: Optional[str],
    location: Optional[str],
    quantity: int,
    shelf_life_expires_at: Optional[datetime],
    serials: list[str],
    original_serial_number: Optional[str],
    row_num: int,
) -> ImportGroup:
    key = group_key(name, inventory_type, part_number)
    group = groups.get(key)
    if group is None:
        group = ImportGroup(
            name=name,
            inventory_type=inventory_type,
            part_number=part_number,
            original_part_number=original_part_number or part_number,
            description=description,
            oem_name=oem_name,
            configuration_item=configuration_item,
            sku=sku,
            location=location,
            quantity=0,
            shelf_life_expires_at=shelf_life_expires_at,
        )
        groups[key] = group
    else:
        if description and not group.description:
            group.description = description
        if oem_name and not group.oem_name:
            group.oem_name = oem_name
        if sku and not group.sku:
            group.sku = sku
        if configuration_item and not group.configuration_item:
            group.configuration_item = configuration_item
        if location and not group.location:
            group.location = location
        if original_part_number and not group.original_part_number:
            group.original_part_number = original_part_number
        if shelf_life_expires_at and not group.shelf_life_expires_at:
            group.shelf_life_expires_at = shelf_life_expires_at
    group.source_rows.append(row_num)
    group.quantity += quantity or 0
    _append_serials(
        group,
        serials,
        row_num=row_num,
        location=location or group.location,
        configuration_item=configuration_item or group.configuration_item,
        original_serial=original_serial_number,
        shelf=shelf_life_expires_at,
    )
    return group


def parse_csv_groups(text: str) -> tuple[list[ImportGroup], list[dict]]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV file appears to be empty")
    missing = [col for col in CSV_IMPORT_REQUIRED if col not in reader.fieldnames]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CSV is missing required columns: {', '.join(missing)}",
        )

    errors: list[dict] = []
    groups: dict[tuple[str, str, str], ImportGroup] = {}

    for row_num, row in enumerate(reader, start=2):
        row_errors: list[str] = []
        name = (row.get("name") or "").strip()
        inventory_type = (row.get("inventory_type") or "").strip().lower()
        if not name:
            row_errors.append("'name' is required")
        if not inventory_type:
            row_errors.append("'inventory_type' is required")
        elif inventory_type not in CSV_VALID_TYPES:
            row_errors.append(
                f"'inventory_type' must be one of: {', '.join(sorted(CSV_VALID_TYPES))}"
            )
        quantity = _int_or_zero(row.get("quantity"), row_num=row_num, errors=errors)
        shelf = _parse_shelf(row.get("shelf_life_expires_at"), row_num=row_num, errors=errors)
        if row_errors:
            errors.append({"row": row_num, "errors": row_errors})
            continue
        if any(entry["row"] == row_num for entry in errors):
            continue

        part_number = _blank_to_none(row.get("part_number"))
        serials = split_serial_numbers(row.get("serial_numbers"))
        single = _blank_to_none(row.get("serial_number"))
        if single and single.lower() not in {s.lower() for s in serials}:
            serials.append(single)

        _upsert_group(
            groups,
            name=name,
            inventory_type=inventory_type,
            part_number=part_number,
            original_part_number=_blank_to_none(row.get("original_part_number")),
            description=_blank_to_none(row.get("description")),
            oem_name=_blank_to_none(row.get("oem_name")),
            configuration_item=_blank_to_none(row.get("configuration_item")),
            sku=_blank_to_none(row.get("sku")),
            location=_blank_to_none(row.get("location")),
            quantity=quantity,
            shelf_life_expires_at=shelf,
            serials=serials,
            original_serial_number=_blank_to_none(row.get("original_serial_number")),
            row_num=row_num,
        )

    return list(groups.values()), errors


def parse_json_groups(text: str) -> tuple[list[ImportGroup], list[dict]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc.msg}") from exc

    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
    elif isinstance(payload, list):
        items = payload
    else:
        raise HTTPException(
            status_code=400,
            detail="JSON must be a list of items or an object with an 'items' array",
        )

    errors: list[dict] = []
    groups: dict[tuple[str, str, str], ImportGroup] = {}

    for index, item in enumerate(items, start=1):
        row_num = index
        if not isinstance(item, dict):
            errors.append({"row": row_num, "errors": ["each item must be an object"]})
            continue
        name = str(item.get("name") or "").strip()
        inventory_type = str(item.get("inventory_type") or "").strip().lower()
        row_errors: list[str] = []
        if not name:
            row_errors.append("'name' is required")
        if not inventory_type:
            row_errors.append("'inventory_type' is required")
        elif inventory_type not in CSV_VALID_TYPES:
            row_errors.append(
                f"'inventory_type' must be one of: {', '.join(sorted(CSV_VALID_TYPES))}"
            )
        quantity = _int_or_zero(item.get("quantity"), row_num=row_num, errors=errors)
        shelf = None
        try:
            shelf = parse_datetime_value(_blank_to_none(item.get("shelf_life_expires_at")) or "")
        except ValueError as exc:
            errors.append({"row": row_num, "errors": [f"'shelf_life_expires_at' {exc}"]})
        if row_errors:
            errors.append({"row": row_num, "errors": row_errors})
            continue

        serials = split_serial_numbers(item.get("serial_numbers"))
        single = _blank_to_none(item.get("serial_number"))
        if single and single.lower() not in {s.lower() for s in serials}:
            serials.append(single)
        instances = item.get("instances") if isinstance(item.get("instances"), list) else []

        group = _upsert_group(
            groups,
            name=name,
            inventory_type=inventory_type,
            part_number=_blank_to_none(item.get("part_number")),
            original_part_number=_blank_to_none(item.get("original_part_number")),
            description=_blank_to_none(item.get("description")),
            oem_name=_blank_to_none(item.get("oem_name")),
            configuration_item=_blank_to_none(item.get("configuration_item")),
            sku=_blank_to_none(item.get("sku")),
            location=_blank_to_none(item.get("location")),
            quantity=quantity,
            shelf_life_expires_at=shelf,
            serials=serials,
            original_serial_number=_blank_to_none(item.get("original_serial_number")),
            row_num=row_num,
        )

        for inst in instances:
            if not isinstance(inst, dict):
                continue
            serial = _blank_to_none(inst.get("serial_number") or inst.get("original_serial_number"))
            if not serial:
                continue
            inst_location = _blank_to_none(inst.get("location"))
            inst_config = _blank_to_none(inst.get("configuration_item"))
            inst_original = _blank_to_none(inst.get("original_serial_number"))
            existing = next(
                (entry for entry in group.serials if entry.serial_number.lower() == serial.lower()),
                None,
            )
            if existing is None:
                _append_serials(
                    group,
                    [serial],
                    row_num=row_num,
                    location=inst_location or group.location,
                    configuration_item=inst_config or group.configuration_item,
                    original_serial=inst_original,
                    shelf=shelf,
                )
                continue
            if inst_location:
                existing.location = inst_location
            if inst_config:
                existing.configuration_item = inst_config
            if inst_original:
                existing.original_serial_number = inst_original

    return list(groups.values()), errors


def validate_groups(
    session: Session,
    groups: list[ImportGroup],
    existing_errors: list[dict],
) -> list[dict]:
    errors = list(existing_errors)
    for group in groups:
        row_num = group.source_rows[0] if group.source_rows else 0
        try:
            validate_inventory_entity_name(
                session, name=group.name, inventory_type=group.inventory_type
            )
        except EntityListError as exc:
            errors.append({"row": row_num, "errors": [str(exc)]})

        if group.serials and group.quantity <= 0:
            group.quantity = len(group.serials)
    return errors


def apply_import_groups(session: Session, groups: list[ImportGroup]) -> dict[str, Any]:
    created_groups = 0
    updated_groups = 0
    instances_created = 0
    serials_skipped = 0
    rows: list[dict] = []

    now = datetime.now(timezone.utc)
    for group in groups:
        existing = find_inventory_group(
            session,
            name=group.name,
            inventory_type=group.inventory_type,
            part_number=group.part_number,
        )
        if existing:
            inventory = existing
            updated = False
            if group.description and not inventory.description:
                inventory.description = group.description
                updated = True
            if group.oem_name and not inventory.oem_name:
                inventory.oem_name = group.oem_name
                updated = True
            if group.sku and not inventory.sku:
                inventory.sku = group.sku
                updated = True
            if group.configuration_item and not inventory.configuration_item:
                inventory.configuration_item = group.configuration_item
                updated = True
            if updated:
                inventory.updated_at = now
                session.add(inventory)
            updated_groups += 1
        else:
            inventory = Inventory(
                name=group.name,
                inventory_type=group.inventory_type,
                part_number=group.part_number,
                quantity=0,
                description=group.description,
                oem_name=group.oem_name,
                configuration_item=group.configuration_item
                or group.part_number
                or group.name,
                sku=group.sku,
                added_date=now,
                updated_at=now,
            )
            session.add(inventory)
            session.flush()
            created_groups += 1

        default_location = (group.location or "").strip() or "Warehouse"
        requested_units = list(group.serials)
        if not requested_units:
            requested_units = [None] * max(0, group.quantity)
        elif group.quantity > len(requested_units):
            requested_units.extend([None] * (group.quantity - len(requested_units)))
        for serial in requested_units:
            serial_number = serial.serial_number if serial is not None else None
            if serial_number and find_inventory_instance_by_serial(
                session, inventory.id, serial_number
            ):
                serials_skipped += 1
                continue
            create_inventory_instance(
                session,
                inventory,
                serial_number=serial_number,
                original_serial_number=(
                    serial.original_serial_number if serial is not None else None
                ),
                original_part_number=group.original_part_number or group.part_number,
                location=(
                    serial.location if serial is not None else None
                )
                or default_location,
                configuration_item=(
                    serial.configuration_item if serial is not None else None
                )
                or group.configuration_item
                or group.part_number
                or group.name,
                shelf_life_expires_at=(
                    serial.shelf_life_expires_at if serial is not None else None
                )
                or group.shelf_life_expires_at,
            )
            instances_created += 1
        sync_inventory_quantity(session, inventory)

        rows.append(
            {
                "id": inventory.id,
                "name": inventory.name,
                "part_number": inventory.part_number,
                "quantity": inventory.quantity,
            }
        )

    return {
        "imported": created_groups + updated_groups,
        "groups_created": created_groups,
        "groups_updated": updated_groups,
        "instances_created": instances_created,
        "serials_skipped": serials_skipped,
        "component_quantity_added": 0,
        "rows": rows,
    }


def parse_inventory_file(filename: str, text: str) -> tuple[list[ImportGroup], list[dict]]:
    lower = (filename or "").lower()
    if lower.endswith(".json"):
        return parse_json_groups(text)
    return parse_csv_groups(text)


def import_inventory_payload(
    session: Session,
    *,
    filename: str,
    text: str,
    dry_run: bool,
) -> dict[str, Any]:
    groups, errors = parse_inventory_file(filename, text)
    errors = validate_groups(session, groups, errors)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Import contains validation errors", "errors": errors},
        )

    instance_count = sum(max(len(group.serials), group.quantity) for group in groups)
    if dry_run:
        return {
            "dry_run": True,
            "valid_rows": len(groups),
            "groups": len(groups),
            "instances": instance_count,
            "component_quantity": 0,
            "errors": [],
        }

    result = apply_import_groups(session, groups)
    session.commit()
    return result
