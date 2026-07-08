from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select, func

from app.models.tables import Inventory, InventoryInstance, InventoryChildLink


def is_component_inventory(inventory_type: str) -> bool:
    return inventory_type == "component"


def normalize_part_number(part_number: Optional[str]) -> str:
    return (part_number or "").strip().lower()


def find_inventory_group(
    session: Session,
    *,
    name: str,
    inventory_type: str,
    part_number: Optional[str],
) -> Optional[Inventory]:
    normalized_part = normalize_part_number(part_number)
    query = select(Inventory).where(
        Inventory.inventory_type == inventory_type,
        func.lower(Inventory.name) == name.strip().lower(),
    )
    if normalized_part:
        query = query.where(
            func.lower(func.coalesce(Inventory.part_number, "")) == normalized_part
        )
    else:
        query = query.where(
            (Inventory.part_number.is_(None))
            | (Inventory.part_number == "")
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
    configuration_item: Optional[str] = None,
    status_id: Optional[int] = None,
    holder_user_id: Optional[int] = None,
    location: Optional[str] = None,
    added_date: Optional[datetime] = None,
    shelf_life_expires_at: Optional[datetime] = None,
    picture_url: Optional[str] = None,
    installation_date: Optional[datetime] = None,
    installed_by_id: Optional[int] = None,
    original_part_number: Optional[str] = None,
    original_serial_number: Optional[str] = None,
) -> InventoryInstance:
    instance = InventoryInstance(
        inventory_id=inventory.id,
        serial_number=serial_number,
        configuration_item=configuration_item,
        status_id=status_id,
        holder_user_id=holder_user_id,
        location=location,
        added_date=added_date or datetime.now(timezone.utc),
        shelf_life_expires_at=shelf_life_expires_at,
        picture_url=picture_url,
        installation_date=installation_date,
        installed_by_id=installed_by_id,
        original_part_number=original_part_number,
        original_serial_number=original_serial_number,
    )
    session.add(instance)
    session.flush()
    sync_inventory_quantity(session, inventory)
    return instance


def consume_inventory_unit(
    session: Session,
    inventory: Inventory,
    *,
    instance_id: Optional[int] = None,
) -> Optional[InventoryInstance]:
    if is_component_inventory(inventory.inventory_type):
        if inventory.quantity <= 0:
            raise HTTPException(status_code=400, detail="Inventory item is out of stock")
        inventory.quantity = max(0, inventory.quantity - 1)
        inventory.updated_at = datetime.now(timezone.utc)
        session.add(inventory)
        return None

    if instance_id is not None:
        instance = session.get(InventoryInstance, instance_id)
        if not instance or instance.inventory_id != inventory.id:
            raise HTTPException(status_code=404, detail="Inventory instance not found")
    else:
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


def list_inventory_child_links(
    session: Session,
    *,
    parent_inventory_id: int,
    parent_instance_id: Optional[int] = None,
    parent_instance_serial: Optional[str] = None,
) -> list[InventoryChildLink]:
    if parent_instance_id is not None:
        specific = session.exec(
            select(InventoryChildLink)
            .where(InventoryChildLink.parent_inventory_id == parent_inventory_id)
            .where(InventoryChildLink.parent_instance_id == parent_instance_id)
            .order_by(InventoryChildLink.id)
        ).all()
        if specific:
            return list(specific)

    normalized_serial = (parent_instance_serial or "").strip().lower()
    if normalized_serial:
        serial_matches = session.exec(
            select(InventoryChildLink)
            .where(InventoryChildLink.parent_inventory_id == parent_inventory_id)
            .where(
                func.lower(func.coalesce(InventoryChildLink.parent_instance_serial, ""))
                == normalized_serial
            )
            .order_by(InventoryChildLink.id)
        ).all()
        if serial_matches:
            return list(serial_matches)

    return list(
        session.exec(
            select(InventoryChildLink)
            .where(InventoryChildLink.parent_inventory_id == parent_inventory_id)
            .where(InventoryChildLink.parent_instance_id.is_(None))
            .where(
                (InventoryChildLink.parent_instance_serial.is_(None))
                | (InventoryChildLink.parent_instance_serial == "")
            )
            .order_by(InventoryChildLink.id)
        ).all()
    )


def replace_inventory_child_links(
    session: Session,
    *,
    parent_inventory: Inventory,
    parent_instance_id: Optional[int],
    children: list[dict],
) -> list[InventoryChildLink]:
    if parent_instance_id is not None:
        instance = session.get(InventoryInstance, parent_instance_id)
        if not instance or instance.inventory_id != parent_inventory.id:
            raise HTTPException(status_code=404, detail="Parent inventory instance not found")
        parent_instance_serial = (
            instance.original_serial_number or instance.serial_number or ""
        ).strip() or None
    else:
        parent_instance_serial = None

    delete_query = select(InventoryChildLink).where(
        InventoryChildLink.parent_inventory_id == parent_inventory.id
    )
    if parent_instance_id is None and not parent_instance_serial:
        delete_query = delete_query.where(InventoryChildLink.parent_instance_id.is_(None)).where(
            (InventoryChildLink.parent_instance_serial.is_(None))
            | (InventoryChildLink.parent_instance_serial == "")
        )
    elif parent_instance_id is not None:
        delete_query = delete_query.where(
            InventoryChildLink.parent_instance_id == parent_instance_id
        )
    elif parent_instance_serial:
        delete_query = delete_query.where(
            func.lower(func.coalesce(InventoryChildLink.parent_instance_serial, ""))
            == parent_instance_serial.lower()
        )

    for existing in session.exec(delete_query).all():
        session.delete(existing)
    session.flush()

    created: list[InventoryChildLink] = []
    for entry in children:
        child_inventory_id = entry["child_inventory_id"]
        child_inventory = session.get(Inventory, child_inventory_id)
        if not child_inventory:
            raise HTTPException(
                status_code=404,
                detail=f"Child inventory {child_inventory_id} not found",
            )

        child_instance_id = entry.get("child_instance_id")
        child_instance_serial = entry.get("child_instance_serial")
        if child_instance_id is not None:
            child_instance = session.get(InventoryInstance, child_instance_id)
            if not child_instance or child_instance.inventory_id != child_inventory_id:
                raise HTTPException(status_code=404, detail="Child inventory instance not found")
            child_instance_serial = (
                child_instance_serial
                or child_instance.original_serial_number
                or child_instance.serial_number
                or ""
            ).strip() or None

        link = InventoryChildLink(
            parent_inventory_id=parent_inventory.id,
            parent_instance_id=parent_instance_id,
            parent_instance_serial=parent_instance_serial,
            child_category_name=entry["child_category_name"].strip(),
            child_inventory_id=child_inventory_id,
            child_instance_id=child_instance_id,
            child_instance_serial=child_instance_serial,
        )
        session.add(link)
        created.append(link)

    session.flush()
    return created
