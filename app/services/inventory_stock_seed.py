"""Admin / CLI helper: multiply existing inventory stock for test scenarios.

One run adds ``multiplier × current_quantity`` new units per catalog group:
- Part number and supplier OEM / original PN stay the same
- Serial numbers continue from the last used sequence
- No shelf life or warranty
- Default location Room/Cabinet/Rack = R1 / C1 / R1
- Unit cost and bulk quote cost default to 10
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from sqlmodel import Session, select

from app.domain.workflow_status import ItemStatus
from app.models.tables import Inventory, InventoryInstance, User
from app.services.app_definitions_service import get_or_create_app_definitions
from app.services.inventory_label_service import ensure_inventory_labels
from app.services.inventory_reservation_service import get_item_status_id
from app.services.inventory_service import (
    create_inventory_instance,
    generate_inventory_instance_serial,
    sync_inventory_quantity,
)

DEFAULT_MULTIPLIER = 10
DEFAULT_UNIT_COST = Decimal("10")
DEFAULT_ROOM = "R1"
DEFAULT_CABINET = "C1"
DEFAULT_RACK = "R1"
DEFAULT_LOCATION = f"{DEFAULT_ROOM} / {DEFAULT_CABINET} / {DEFAULT_RACK}"


@dataclass
class InventoryStockSeedGroupResult:
    inventory_id: int
    name: str
    part_number: Optional[str]
    previous_quantity: int
    units_added: int
    new_quantity: int
    skipped_reason: Optional[str] = None


@dataclass
class InventoryStockSeedResult:
    multiplier: int
    groups_processed: int = 0
    groups_skipped: int = 0
    units_added: int = 0
    location: str = DEFAULT_LOCATION
    unit_cost: Decimal = DEFAULT_UNIT_COST
    groups: list[InventoryStockSeedGroupResult] = field(default_factory=list)


def _compose_location(room: str, cabinet: str, rack: str) -> str:
    parts = [p.strip() for p in (room, cabinet, rack) if p and str(p).strip()]
    return " / ".join(parts) if parts else DEFAULT_LOCATION


def _new_location_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def ensure_default_seed_location_tree(
    session: Session,
    *,
    room: str = DEFAULT_ROOM,
    cabinet: str = DEFAULT_CABINET,
    rack: str = DEFAULT_RACK,
) -> None:
    """Ensure Room/Cabinet/Rack exist in the admin location tree (idempotent)."""
    room_name = (room or DEFAULT_ROOM).strip() or DEFAULT_ROOM
    cabinet_name = (cabinet or DEFAULT_CABINET).strip() or DEFAULT_CABINET
    rack_name = (rack or DEFAULT_RACK).strip() or DEFAULT_RACK

    definitions = get_or_create_app_definitions(session)
    tree: list[dict[str, Any]] = list(definitions.inventory_location_tree or [])
    dirty = False

    room_node = next(
        (
            node
            for node in tree
            if isinstance(node, dict)
            and str(node.get("name") or "").strip().lower() == room_name.lower()
        ),
        None,
    )
    if room_node is None:
        room_node = {
            "id": _new_location_id("room"),
            "name": room_name,
            "cabinets": [],
        }
        tree.append(room_node)
        dirty = True

    cabinets = room_node.setdefault("cabinets", [])
    if not isinstance(cabinets, list):
        cabinets = []
        room_node["cabinets"] = cabinets
        dirty = True

    cabinet_node = next(
        (
            node
            for node in cabinets
            if isinstance(node, dict)
            and str(node.get("name") or "").strip().lower() == cabinet_name.lower()
        ),
        None,
    )
    if cabinet_node is None:
        cabinet_node = {
            "id": _new_location_id("cab"),
            "name": cabinet_name,
            "racks": [],
        }
        cabinets.append(cabinet_node)
        dirty = True

    racks = cabinet_node.setdefault("racks", [])
    if not isinstance(racks, list):
        racks = []
        cabinet_node["racks"] = racks
        dirty = True

    rack_exists = any(
        isinstance(node, dict)
        and str(node.get("name") or "").strip().lower() == rack_name.lower()
        for node in racks
    )
    if not rack_exists:
        racks.append({"id": _new_location_id("rack"), "name": rack_name})
        dirty = True

    if dirty:
        definitions.inventory_location_tree = tree
        definitions.updated_at = datetime.now(timezone.utc)
        session.add(definitions)
        session.flush()


def _supplier_original_part_number(
    session: Session, inventory: Inventory
) -> Optional[str]:
    """Prefer the latest unit's supplier PN, then catalog PN."""
    if inventory.id is None:
        return (inventory.part_number or "").strip() or None
    latest = session.exec(
        select(InventoryInstance)
        .where(InventoryInstance.inventory_id == inventory.id)
        .order_by(InventoryInstance.id.desc())
    ).first()
    if latest is not None:
        from_unit = (latest.original_part_number or "").strip()
        if from_unit:
            return from_unit
    catalog = (inventory.original_part_number or "").strip()
    if catalog:
        return catalog
    return (inventory.part_number or "").strip() or None


def seed_inventory_stock_multiplier(
    session: Session,
    *,
    multiplier: int = DEFAULT_MULTIPLIER,
    unit_cost: Decimal = DEFAULT_UNIT_COST,
    location_room: str = DEFAULT_ROOM,
    location_cabinet: str = DEFAULT_CABINET,
    location_rack: str = DEFAULT_RACK,
    dry_run: bool = False,
    actor: Optional[User] = None,
    inventory_ids: Optional[list[int]] = None,
) -> InventoryStockSeedResult:
    """Add ``multiplier × current qty`` units to each inventory catalog group."""
    if multiplier < 1:
        raise ValueError("multiplier must be at least 1")
    if unit_cost < 0:
        raise ValueError("unit_cost cannot be negative")

    room = (location_room or DEFAULT_ROOM).strip() or DEFAULT_ROOM
    cabinet = (location_cabinet or DEFAULT_CABINET).strip() or DEFAULT_CABINET
    rack = (location_rack or DEFAULT_RACK).strip() or DEFAULT_RACK
    location = _compose_location(room, cabinet, rack)
    cost = Decimal(unit_cost)

    result = InventoryStockSeedResult(
        multiplier=multiplier,
        location=location,
        unit_cost=cost,
    )

    if not dry_run:
        ensure_default_seed_location_tree(
            session, room=room, cabinet=cabinet, rack=rack
        )

    available_id = get_item_status_id(session, ItemStatus.AVAILABLE.value)

    query = select(Inventory).order_by(Inventory.id)
    if inventory_ids:
        query = query.where(Inventory.id.in_(inventory_ids))
    groups = session.exec(query).all()

    for inventory in groups:
        if inventory.id is None:
            continue

        previous_qty = sync_inventory_quantity(session, inventory)
        if previous_qty < 1:
            result.groups_skipped += 1
            result.groups.append(
                InventoryStockSeedGroupResult(
                    inventory_id=int(inventory.id),
                    name=inventory.name or "",
                    part_number=inventory.part_number,
                    previous_quantity=previous_qty,
                    units_added=0,
                    new_quantity=previous_qty,
                    skipped_reason="empty_stock",
                )
            )
            continue

        units_to_add = previous_qty * multiplier
        original_part = _supplier_original_part_number(session, inventory)

        if dry_run:
            result.groups_processed += 1
            result.units_added += units_to_add
            result.groups.append(
                InventoryStockSeedGroupResult(
                    inventory_id=int(inventory.id),
                    name=inventory.name or "",
                    part_number=inventory.part_number,
                    previous_quantity=previous_qty,
                    units_added=units_to_add,
                    new_quantity=previous_qty + units_to_add,
                )
            )
            continue

        inventory.bulk_quote_cost = cost
        inventory.default_unit_cost = cost
        if not (inventory.currency or "").strip():
            inventory.currency = "PKR"
        inventory.updated_at = datetime.now(timezone.utc)
        session.add(inventory)

        for _ in range(units_to_add):
            serial = generate_inventory_instance_serial(session, inventory)
            create_inventory_instance(
                session,
                inventory,
                serial_number=serial,
                configuration_item=inventory.configuration_item
                or inventory.part_number
                or inventory.name,
                status_id=available_id,
                location=location,
                location_room=room,
                location_cabinet=cabinet,
                location_rack=rack,
                shelf_life_expires_at=None,
                warranty_expires_at=None,
                original_part_number=original_part,
                original_serial_number=serial,
                unit_cost=cost,
            )

        if actor is not None:
            ensure_inventory_labels(session, inventory, actor=actor)
        new_qty = sync_inventory_quantity(session, inventory)
        result.groups_processed += 1
        result.units_added += units_to_add
        result.groups.append(
            InventoryStockSeedGroupResult(
                inventory_id=int(inventory.id),
                name=inventory.name or "",
                part_number=inventory.part_number,
                previous_quantity=previous_qty,
                units_added=units_to_add,
                new_quantity=new_qty,
            )
        )

    if not dry_run:
        session.flush()

    return result
