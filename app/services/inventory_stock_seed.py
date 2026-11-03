"""Admin / CLI helper: seed inventory for test scenarios.

Two stages (either or both):
1. Bootstrap active shortage items that are not yet in inventory as **1 unit** each
2. Multiply selected (or all stocked) inventory groups by a user-defined factor

Shared defaults for new units:
- Part number / supplier original PN preserved; serials continue from last used
- No shelf life or warranty
- Location Room/Cabinet/Rack = R1 / C1 / R1
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
from app.models.tables import Inventory, InventoryInstance, InventoryShortage, User
from app.services.app_definitions_service import get_or_create_app_definitions
from app.services.inventory_label_service import ensure_inventory_labels
from app.services.inventory_reservation_service import get_item_status_id
from app.services.inventory_service import (
    create_inventory_instance,
    find_inventory_catalog_group,
    generate_inventory_instance_serial,
    sync_inventory_quantity,
)
from app.services.inventory_shortage_service import (
    ACTIVE_SHORTAGE_STATUSES,
    _suggested_inventory_identifiers,
    list_shortages,
)

DEFAULT_MULTIPLIER = 10
DEFAULT_UNIT_COST = Decimal("10")
DEFAULT_ROOM = "R1"
DEFAULT_CABINET = "C1"
DEFAULT_RACK = "R1"
DEFAULT_LOCATION = f"{DEFAULT_ROOM} / {DEFAULT_CABINET} / {DEFAULT_RACK}"

_VALID_TYPES = frozenset({"system", "subsystem", "module", "unit", "component"})


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
class InventoryStockSeedBootstrapItem:
    shortage_ids: list[int]
    lru_name: str
    inventory_type: str
    part_number: Optional[str]
    inventory_id: Optional[int] = None
    action: str = "pending"  # created_group | added_unit | skipped
    reason: Optional[str] = None


@dataclass
class InventoryStockSeedResult:
    multiplier: int
    groups_processed: int = 0
    groups_skipped: int = 0
    units_added: int = 0
    location: str = DEFAULT_LOCATION
    unit_cost: Decimal = DEFAULT_UNIT_COST
    groups: list[InventoryStockSeedGroupResult] = field(default_factory=list)
    bootstrap_created_groups: int = 0
    bootstrap_units_added: int = 0
    bootstrap_skipped: int = 0
    bootstrap_items: list[InventoryStockSeedBootstrapItem] = field(default_factory=list)


@dataclass
class MissingShortageCandidate:
    shortage_ids: list[int]
    lru_name: str
    inventory_type: str
    part_number: Optional[str]
    qty_short_total: int
    existing_inventory_id: Optional[int]
    existing_quantity: int


@dataclass
class InventorySeedCatalogOption:
    inventory_id: int
    name: str
    inventory_type: str
    part_number: Optional[str]
    quantity: int


@dataclass
class InventorySeedOptions:
    missing_shortages: list[MissingShortageCandidate] = field(default_factory=list)
    inventory_groups: list[InventorySeedCatalogOption] = field(default_factory=list)


def _compose_location(room: str, cabinet: str, rack: str) -> str:
    parts = [p.strip() for p in (room, cabinet, rack) if p and str(p).strip()]
    return " / ".join(parts) if parts else DEFAULT_LOCATION


def _new_location_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def _catalog_key(name: str, inventory_type: str, part_number: Optional[str]) -> str:
    return (
        f"{(inventory_type or '').strip().lower()}|"
        f"{(name or '').strip().lower()}|"
        f"{(part_number or '').strip().lower()}"
    )


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


def _resolve_shortage_part_number(
    session: Session, shortage: InventoryShortage
) -> Optional[str]:
    suggested_part, _ = _suggested_inventory_identifiers(session, shortage)
    return (
        (shortage.part_number or "").strip()
        or (suggested_part or "").strip()
        or None
    )


def collect_missing_shortage_candidates(
    session: Session,
) -> list[MissingShortageCandidate]:
    """Active shortages whose catalog item is missing or has zero stocked units."""
    shortages = list_shortages(
        session, statuses=list(ACTIVE_SHORTAGE_STATUSES)
    )
    buckets: dict[str, dict[str, Any]] = {}

    for shortage in shortages:
        name = (shortage.lru_name or "").strip()
        inv_type = (shortage.target_entity_type or "").strip().lower()
        if not name or inv_type not in _VALID_TYPES:
            continue
        part_number = _resolve_shortage_part_number(session, shortage)
        key = _catalog_key(name, inv_type, part_number)
        bucket = buckets.get(key)
        if bucket is None:
            inventory: Optional[Inventory] = None
            if shortage.inventory_id is not None:
                inventory = session.get(Inventory, shortage.inventory_id)
            if inventory is None:
                inventory = find_inventory_catalog_group(
                    session,
                    name=name,
                    inventory_type=inv_type,
                    part_number=part_number,
                )
            qty = sync_inventory_quantity(session, inventory) if inventory else 0
            bucket = {
                "shortage_ids": [],
                "lru_name": name,
                "inventory_type": inv_type,
                "part_number": part_number
                or (inventory.part_number if inventory else None),
                "qty_short_total": 0,
                "existing_inventory_id": int(inventory.id)
                if inventory and inventory.id is not None
                else None,
                "existing_quantity": qty,
            }
            buckets[key] = bucket
        bucket["shortage_ids"].append(int(shortage.id))
        bucket["qty_short_total"] += int(shortage.qty_short or 0)

    missing: list[MissingShortageCandidate] = []
    for bucket in buckets.values():
        if int(bucket["existing_quantity"]) >= 1:
            continue
        missing.append(
            MissingShortageCandidate(
                shortage_ids=list(bucket["shortage_ids"]),
                lru_name=str(bucket["lru_name"]),
                inventory_type=str(bucket["inventory_type"]),
                part_number=bucket["part_number"],
                qty_short_total=int(bucket["qty_short_total"]),
                existing_inventory_id=bucket["existing_inventory_id"],
                existing_quantity=int(bucket["existing_quantity"]),
            )
        )
    missing.sort(key=lambda item: (item.inventory_type, item.lru_name.lower()))
    return missing


def list_inventory_seed_catalog(
    session: Session,
) -> list[InventorySeedCatalogOption]:
    rows = session.exec(select(Inventory).order_by(Inventory.name, Inventory.id)).all()
    options: list[InventorySeedCatalogOption] = []
    for inventory in rows:
        if inventory.id is None:
            continue
        qty = sync_inventory_quantity(session, inventory)
        options.append(
            InventorySeedCatalogOption(
                inventory_id=int(inventory.id),
                name=inventory.name or "",
                inventory_type=inventory.inventory_type or "",
                part_number=inventory.part_number,
                quantity=qty,
            )
        )
    return options


def get_inventory_seed_options(session: Session) -> InventorySeedOptions:
    return InventorySeedOptions(
        missing_shortages=collect_missing_shortage_candidates(session),
        inventory_groups=list_inventory_seed_catalog(session),
    )


def seed_missing_shortages_as_single_units(
    session: Session,
    *,
    unit_cost: Decimal = DEFAULT_UNIT_COST,
    location_room: str = DEFAULT_ROOM,
    location_cabinet: str = DEFAULT_CABINET,
    location_rack: str = DEFAULT_RACK,
    dry_run: bool = False,
    actor: Optional[User] = None,
    shortage_ids: Optional[list[int]] = None,
) -> InventoryStockSeedResult:
    """Create/add exactly one AVAILABLE unit for each missing shortage catalog key.

    Does not auto-reserve against shortages so units remain available for the
    next multiply-seed tranche.
    """
    if unit_cost < 0:
        raise ValueError("unit_cost cannot be negative")

    room = (location_room or DEFAULT_ROOM).strip() or DEFAULT_ROOM
    cabinet = (location_cabinet or DEFAULT_CABINET).strip() or DEFAULT_CABINET
    rack = (location_rack or DEFAULT_RACK).strip() or DEFAULT_RACK
    location = _compose_location(room, cabinet, rack)
    cost = Decimal(unit_cost)

    result = InventoryStockSeedResult(
        multiplier=0,
        location=location,
        unit_cost=cost,
    )

    allowed_shortage_ids = (
        {int(sid) for sid in shortage_ids} if shortage_ids is not None else None
    )
    candidates = collect_missing_shortage_candidates(session)
    if allowed_shortage_ids is not None:
        filtered: list[MissingShortageCandidate] = []
        for candidate in candidates:
            selected = [
                sid for sid in candidate.shortage_ids if sid in allowed_shortage_ids
            ]
            if not selected:
                continue
            filtered.append(
                MissingShortageCandidate(
                    shortage_ids=selected,
                    lru_name=candidate.lru_name,
                    inventory_type=candidate.inventory_type,
                    part_number=candidate.part_number,
                    qty_short_total=candidate.qty_short_total,
                    existing_inventory_id=candidate.existing_inventory_id,
                    existing_quantity=candidate.existing_quantity,
                )
            )
        candidates = filtered

    if not dry_run:
        ensure_default_seed_location_tree(
            session, room=room, cabinet=cabinet, rack=rack
        )

    available_id = get_item_status_id(session, ItemStatus.AVAILABLE.value)

    for candidate in candidates:
        if not (candidate.part_number or "").strip():
            result.bootstrap_skipped += 1
            result.bootstrap_items.append(
                InventoryStockSeedBootstrapItem(
                    shortage_ids=list(candidate.shortage_ids),
                    lru_name=candidate.lru_name,
                    inventory_type=candidate.inventory_type,
                    part_number=candidate.part_number,
                    inventory_id=candidate.existing_inventory_id,
                    action="skipped",
                    reason="missing_part_number",
                )
            )
            continue

        if dry_run:
            action = (
                "added_unit"
                if candidate.existing_inventory_id is not None
                else "created_group"
            )
            result.bootstrap_units_added += 1
            if action == "created_group":
                result.bootstrap_created_groups += 1
            result.bootstrap_items.append(
                InventoryStockSeedBootstrapItem(
                    shortage_ids=list(candidate.shortage_ids),
                    lru_name=candidate.lru_name,
                    inventory_type=candidate.inventory_type,
                    part_number=candidate.part_number,
                    inventory_id=candidate.existing_inventory_id,
                    action=action,
                )
            )
            continue

        inventory: Optional[Inventory] = None
        created_group = False
        if candidate.existing_inventory_id is not None:
            inventory = session.get(Inventory, candidate.existing_inventory_id)
        if inventory is None:
            inventory = find_inventory_catalog_group(
                session,
                name=candidate.lru_name,
                inventory_type=candidate.inventory_type,
                part_number=candidate.part_number,
            )
        if inventory is None:
            inventory = Inventory(
                name=candidate.lru_name,
                inventory_type=candidate.inventory_type,
                quantity=0,
                part_number=candidate.part_number,
                configuration_item=candidate.part_number or candidate.lru_name,
                currency="PKR",
                bulk_quote_cost=cost,
                default_unit_cost=cost,
                original_part_number=candidate.part_number,
                holder_user_id=int(actor.id) if actor and actor.id is not None else None,
                shelf_life_expires_at=None,
                warranty_expires_at=None,
                added_date=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(inventory)
            session.flush()
            created_group = True
        else:
            if not inventory.part_number:
                inventory.part_number = candidate.part_number
            inventory.bulk_quote_cost = cost
            inventory.default_unit_cost = cost
            if not (inventory.currency or "").strip():
                inventory.currency = "PKR"
            if not (inventory.original_part_number or "").strip():
                inventory.original_part_number = candidate.part_number
            inventory.updated_at = datetime.now(timezone.utc)
            session.add(inventory)

        assert inventory.id is not None
        previous_qty = sync_inventory_quantity(session, inventory)
        if previous_qty >= 1:
            result.bootstrap_skipped += 1
            result.bootstrap_items.append(
                InventoryStockSeedBootstrapItem(
                    shortage_ids=list(candidate.shortage_ids),
                    lru_name=candidate.lru_name,
                    inventory_type=candidate.inventory_type,
                    part_number=inventory.part_number,
                    inventory_id=int(inventory.id),
                    action="skipped",
                    reason="already_stocked",
                )
            )
            _link_shortages_to_inventory(
                session, candidate.shortage_ids, int(inventory.id), inventory.part_number
            )
            continue

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
            original_part_number=inventory.original_part_number or candidate.part_number,
            original_serial_number=serial,
            unit_cost=cost,
            holder_user_id=int(actor.id) if actor and actor.id is not None else None,
        )
        if actor is not None:
            ensure_inventory_labels(session, inventory, actor=actor)
        new_qty = sync_inventory_quantity(session, inventory)
        _link_shortages_to_inventory(
            session, candidate.shortage_ids, int(inventory.id), inventory.part_number
        )

        result.bootstrap_units_added += 1
        if created_group:
            result.bootstrap_created_groups += 1
        result.bootstrap_items.append(
            InventoryStockSeedBootstrapItem(
                shortage_ids=list(candidate.shortage_ids),
                lru_name=candidate.lru_name,
                inventory_type=candidate.inventory_type,
                part_number=inventory.part_number,
                inventory_id=int(inventory.id),
                action="created_group" if created_group else "added_unit",
            )
        )
        result.groups.append(
            InventoryStockSeedGroupResult(
                inventory_id=int(inventory.id),
                name=inventory.name or candidate.lru_name,
                part_number=inventory.part_number,
                previous_quantity=previous_qty,
                units_added=1,
                new_quantity=new_qty,
            )
        )

    if not dry_run:
        session.flush()
    return result


def _link_shortages_to_inventory(
    session: Session,
    shortage_ids: list[int],
    inventory_id: int,
    part_number: Optional[str],
) -> None:
    now = datetime.now(timezone.utc)
    for shortage_id in shortage_ids:
        shortage = session.get(InventoryShortage, shortage_id)
        if shortage is None:
            continue
        shortage.inventory_id = inventory_id
        if part_number and not (shortage.part_number or "").strip():
            shortage.part_number = part_number
        shortage.updated_at = now
        session.add(shortage)


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
    """Add ``multiplier × current qty`` units to selected inventory catalog groups."""
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
    if inventory_ids is not None:
        if not inventory_ids:
            return result
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


def run_inventory_test_seed(
    session: Session,
    *,
    bootstrap_missing_shortages: bool = False,
    multiply_stock: bool = True,
    multiplier: int = DEFAULT_MULTIPLIER,
    unit_cost: Decimal = DEFAULT_UNIT_COST,
    location_room: str = DEFAULT_ROOM,
    location_cabinet: str = DEFAULT_CABINET,
    location_rack: str = DEFAULT_RACK,
    dry_run: bool = False,
    actor: Optional[User] = None,
    inventory_ids: Optional[list[int]] = None,
    shortage_ids: Optional[list[int]] = None,
) -> InventoryStockSeedResult:
    """Run optional shortage bootstrap then optional stock multiply."""
    if not bootstrap_missing_shortages and not multiply_stock:
        raise ValueError(
            "Select at least one action: bootstrap missing shortages or multiply stock"
        )

    room = (location_room or DEFAULT_ROOM).strip() or DEFAULT_ROOM
    cabinet = (location_cabinet or DEFAULT_CABINET).strip() or DEFAULT_CABINET
    rack = (location_rack or DEFAULT_RACK).strip() or DEFAULT_RACK
    location = _compose_location(room, cabinet, rack)
    cost = Decimal(unit_cost)

    combined = InventoryStockSeedResult(
        multiplier=multiplier if multiply_stock else 0,
        location=location,
        unit_cost=cost,
    )

    bootstrapped_ids: list[int] = []
    if bootstrap_missing_shortages:
        bootstrap = seed_missing_shortages_as_single_units(
            session,
            unit_cost=cost,
            location_room=room,
            location_cabinet=cabinet,
            location_rack=rack,
            dry_run=dry_run,
            actor=actor,
            shortage_ids=shortage_ids,
        )
        combined.bootstrap_created_groups = bootstrap.bootstrap_created_groups
        combined.bootstrap_units_added = bootstrap.bootstrap_units_added
        combined.bootstrap_skipped = bootstrap.bootstrap_skipped
        combined.bootstrap_items = list(bootstrap.bootstrap_items)
        for item in bootstrap.bootstrap_items:
            if item.inventory_id is not None and item.action in {
                "created_group",
                "added_unit",
            }:
                bootstrapped_ids.append(int(item.inventory_id))

    if multiply_stock:
        if inventory_ids is None:
            multiply_ids = None
        else:
            multiply_ids = list(inventory_ids)
            # Same-run bootstrap: newly stocked groups are eligible for the multiplier.
            for inventory_id in bootstrapped_ids:
                if inventory_id not in multiply_ids:
                    multiply_ids.append(inventory_id)

        if (
            dry_run
            and multiply_ids is not None
            and len(multiply_ids) == 0
            and combined.bootstrap_units_added > 0
        ):
            # Preview path: bootstrap has no real inventory ids yet; simulate
            # multiply against the 1 unit each bootstrap would create.
            combined.multiplier = multiplier
            for item in combined.bootstrap_items:
                if item.action not in {"created_group", "added_unit"}:
                    continue
                units = 1 * multiplier
                combined.groups_processed += 1
                combined.units_added += units
                combined.groups.append(
                    InventoryStockSeedGroupResult(
                        inventory_id=int(item.inventory_id or 0),
                        name=item.lru_name,
                        part_number=item.part_number,
                        previous_quantity=1,
                        units_added=units,
                        new_quantity=1 + units,
                    )
                )
        else:
            multiply = seed_inventory_stock_multiplier(
                session,
                multiplier=multiplier,
                unit_cost=cost,
                location_room=room,
                location_cabinet=cabinet,
                location_rack=rack,
                dry_run=dry_run,
                actor=actor,
                inventory_ids=multiply_ids,
            )
            combined.multiplier = multiply.multiplier
            combined.groups_processed = multiply.groups_processed
            combined.groups_skipped = multiply.groups_skipped
            combined.units_added = multiply.units_added
            combined.groups = list(multiply.groups)

    if not dry_run:
        session.flush()
    return combined
