from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select, func

from app.models.tables import Inventory, InventoryInstance


def is_component_inventory(inventory_type: str) -> bool:
    return inventory_type == "component"


def normalize_part_number(part_number: Optional[str]) -> str:
    return (part_number or "").strip().lower()


def find_inventory_group(
    session: Session,
    *,
    name: str,
    inventory_type: str,
    manufacturer_part_number: Optional[str],
) -> Optional[Inventory]:
    normalized_part = normalize_part_number(manufacturer_part_number)
    query = select(Inventory).where(
        Inventory.inventory_type == inventory_type,
        func.lower(Inventory.name) == name.strip().lower(),
    )
    if normalized_part:
        query = query.where(
            func.lower(func.coalesce(Inventory.manufacturer_part_number, "")) == normalized_part
        )
    else:
        query = query.where(
            (Inventory.manufacturer_part_number.is_(None))
            | (Inventory.manufacturer_part_number == "")
        )
    return session.exec(query).first()


def sync_inventory_quantity(session: Session, inventory: Inventory) -> int:
    if is_component_inventory(inventory.inventory_type):
        return inventory.quantity
    count = session.exec(
        select(func.count())
        .select_from(InventoryInstance)
        .where(InventoryInstance.inventory_id == inventory.id)
    ).one()
    inventory.quantity = count
    inventory.updated_at = datetime.now(timezone.utc)
    session.add(inventory)
    return count


def create_inventory_instance(
    session: Session,
    inventory: Inventory,
    *,
    serial_number: Optional[str] = None,
    holder_user_id: Optional[int] = None,
    location: Optional[str] = None,
    added_date: Optional[datetime] = None,
    shelf_life_expires_at: Optional[datetime] = None,
    picture_url: Optional[str] = None,
) -> InventoryInstance:
    instance = InventoryInstance(
        inventory_id=inventory.id,
        serial_number=serial_number,
        holder_user_id=holder_user_id,
        location=location,
        added_date=added_date or datetime.now(timezone.utc),
        shelf_life_expires_at=shelf_life_expires_at,
        picture_url=picture_url,
    )
    session.add(instance)
    session.flush()
    sync_inventory_quantity(session, inventory)
    return instance


def consume_inventory_unit(session: Session, inventory: Inventory) -> Optional[InventoryInstance]:
    if is_component_inventory(inventory.inventory_type):
        if inventory.quantity <= 0:
            raise HTTPException(status_code=400, detail="Inventory item is out of stock")
        inventory.quantity = max(0, inventory.quantity - 1)
        inventory.updated_at = datetime.now(timezone.utc)
        session.add(inventory)
        return None

    instance = session.exec(
        select(InventoryInstance)
        .where(InventoryInstance.inventory_id == inventory.id)
        .order_by(InventoryInstance.id)
    ).first()
    if not instance:
        raise HTTPException(status_code=400, detail="Inventory item is out of stock")
    session.delete(instance)
    session.flush()
    sync_inventory_quantity(session, inventory)
    return instance
