"""Adding stock for the same entity category merges into one inventory group."""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session, select

from app.models.tables import Inventory, InventoryInstance
from app.services.inventory_service import (
    create_inventory_instance,
    find_inventory_catalog_group,
    sync_inventory_quantity,
)


@pytest.fixture()
def session():
    from app.database import engine

    with Session(engine) as session:
        yield session


def test_find_inventory_catalog_group_matches_name_and_type(session: Session):
    inv = Inventory(
        name="LRU",
        inventory_type="module",
        part_number="PN-LRU-001",
        quantity=0,
    )
    session.add(inv)
    session.flush()

    hit = find_inventory_catalog_group(
        session,
        name="LRU",
        inventory_type="module",
        part_number="PN-LRU-DIFFERENT",
    )
    assert hit is not None
    assert hit.id == inv.id
    assert hit.part_number == "PN-LRU-001"

    session.delete(inv)
    session.commit()


def test_additional_serial_adds_instance_to_same_group(session: Session):
    name = f"Unit-{uuid.uuid4().hex[:6]}"
    group = Inventory(
        name=name,
        inventory_type="unit",
        part_number="PN-UNIT-001",
        quantity=0,
    )
    session.add(group)
    session.flush()
    create_inventory_instance(
        session,
        group,
        serial_number="SN-UNIT-001",
        location="Shelf A",
    )
    session.commit()

    existing = find_inventory_catalog_group(
        session,
        name=name,
        inventory_type="unit",
        part_number="PN-UNIT-002",
    )
    assert existing is not None
    assert existing.id == group.id

    create_inventory_instance(
        session,
        existing,
        serial_number="SN-UNIT-002",
        location="Shelf B",
    )
    session.commit()
    sync_inventory_quantity(session, existing)
    session.refresh(existing)

    assert existing.quantity == 2
    rows = session.exec(
        select(Inventory).where(
            Inventory.inventory_type == "unit",
            Inventory.name == name,
        )
    ).all()
    assert len(rows) == 1
    serials = {
        row.serial_number
        for row in session.exec(
            select(InventoryInstance).where(InventoryInstance.inventory_id == group.id)
        ).all()
    }
    assert serials == {"SN-UNIT-001", "SN-UNIT-002"}

    for inst in session.exec(
        select(InventoryInstance).where(InventoryInstance.inventory_id == group.id)
    ).all():
        session.delete(inst)
    session.delete(group)
    session.commit()


def test_component_quantity_can_merge_on_same_catalog_group(session: Session):
    name = f"Comp-{uuid.uuid4().hex[:6]}"
    group = Inventory(
        name=name,
        inventory_type="component",
        part_number="PN-COMP-001",
        quantity=3,
        location="Bin 1",
    )
    session.add(group)
    session.commit()
    session.refresh(group)

    existing = find_inventory_catalog_group(
        session,
        name=name,
        inventory_type="component",
        part_number="PN-COMP-002",
    )
    assert existing is not None
    assert existing.id == group.id

    existing.quantity = int(existing.quantity or 0) + 5
    session.add(existing)
    session.commit()
    session.refresh(existing)

    assert existing.quantity == 8
    rows = session.exec(
        select(Inventory).where(
            Inventory.inventory_type == "component",
            Inventory.name == name,
        )
    ).all()
    assert len(rows) == 1

    session.delete(group)
    session.commit()
