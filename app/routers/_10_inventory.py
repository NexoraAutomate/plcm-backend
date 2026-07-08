from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Response
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import Inventory, InventoryInstance, User
from app.schemas import schemas
from app.routers.auth import require_permission
from app.services.pagination import paginated_query
from app.services.inventory_service import (
    is_component_inventory,
    find_inventory_group,
    create_inventory_instance,
    consume_inventory_unit,
    sync_inventory_quantity,
    normalize_part_number,
)

router = APIRouter()


def _normalize_inventory_quantity(inventory_type: str, quantity: int | None) -> int:
    if is_component_inventory(inventory_type):
        if quantity is None:
            return 0
        if quantity < 0:
            raise HTTPException(status_code=400, detail="Quantity cannot be negative")
        return quantity
    return 0


def _inventory_to_read(
    session: Session,
    inventory: Inventory,
    *,
    include_instances: bool = False,
) -> schemas.InventoryRead:
    data = inventory.model_dump()
    if is_component_inventory(inventory.inventory_type):
        data["instances"] = None
    elif include_instances:
        instances = session.exec(
            select(InventoryInstance)
            .where(InventoryInstance.inventory_id == inventory.id)
            .order_by(InventoryInstance.id)
        ).all()
        data["instances"] = instances
    else:
        data["instances"] = None
    return schemas.InventoryRead.model_validate(data)


def _extract_instance_fields(data: dict) -> dict:
    return {
        "serial_number": data.pop("serial_number", None),
        "configuration_item": data.pop("configuration_item", None),
        "status_id": data.pop("status_id", None),
        "holder_user_id": data.pop("holder_user_id", None),
        "location": data.pop("location", None),
        "added_date": data.pop("added_date", None),
        "shelf_life_expires_at": data.pop("shelf_life_expires_at", None),
        "picture_url": data.pop("picture_url", None),
        "installation_date": data.pop("installation_date", None),
        "installed_by_id": data.pop("installed_by_id", None),
        "original_part_number": data.pop("original_part_number", None),
        "original_serial_number": data.pop("original_serial_number", None),
    }


def _resolve_part_number(data: dict) -> Optional[str]:
    return data.get("part_number") or data.pop("manufacturer_part_number", None)


# ===================== INVENTORY ENDPOINTS =====================
@router.post("/inventory/", response_model=schemas.InventoryRead, tags=["inventory"])
def create_inventory(
    inventory: schemas.InventoryCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("create_inventory")),
):
    data = inventory.model_dump()
    inventory_type = data["inventory_type"]

    if is_component_inventory(inventory_type):
        part_number = _resolve_part_number(data)
        if part_number:
            data["part_number"] = part_number
        if not data.get("configuration_item"):
            data["configuration_item"] = part_number or data.get("name")
        data["quantity"] = _normalize_inventory_quantity(inventory_type, data.get("quantity"))
        db_inventory = Inventory(**data)
        session.add(db_inventory)
        session.commit()
        session.refresh(db_inventory)
        return _inventory_to_read(session, db_inventory)

    part_number = _resolve_part_number(data)
    if not normalize_part_number(part_number):
        raise HTTPException(
            status_code=400,
            detail="Part number is required for non-component inventory",
        )
    data["part_number"] = part_number
    if not data.get("configuration_item"):
        data["configuration_item"] = part_number
    if not (data.get("location") or "").strip():
        raise HTTPException(status_code=400, detail="Location is required for inventory instances")

    instance_fields = _extract_instance_fields(data)
    if not instance_fields.get("configuration_item"):
        instance_fields["configuration_item"] = part_number
    data["quantity"] = 0
    data["serial_number"] = None
    data["holder_user_id"] = None
    data["location"] = None
    data["added_date"] = None
    data["shelf_life_expires_at"] = None
    data["picture_url"] = None
    data["installation_date"] = None
    data["installed_by_id"] = None
    data["original_part_number"] = None
    data["original_serial_number"] = None

    existing = find_inventory_group(
        session,
        name=data["name"],
        inventory_type=inventory_type,
        part_number=part_number,
    )
    if existing:
        db_inventory = existing
        if data.get("description") and not db_inventory.description:
            db_inventory.description = data["description"]
        if data.get("oem_name") and not db_inventory.oem_name:
            db_inventory.oem_name = data["oem_name"]
        session.add(db_inventory)
    else:
        db_inventory = Inventory(**data)
        session.add(db_inventory)
        session.flush()

    create_inventory_instance(session, db_inventory, **instance_fields)
    session.commit()
    session.refresh(db_inventory)
    return _inventory_to_read(session, db_inventory, include_instances=True)


@router.get("/inventory/", response_model=List[schemas.InventoryRead], tags=["inventory"])
def list_inventory(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    inventory_type: str = Query(None, description="Filter by inventory type (system, subsystem, module, unit, component)"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    where = Inventory.inventory_type == inventory_type if inventory_type else None
    items = paginated_query(session, Inventory, skip, limit, response, where=where)
    return [_inventory_to_read(session, item, include_instances=True) for item in items]


@router.get("/inventory/by-type/{inventory_type}/", response_model=List[schemas.InventoryRead], tags=["inventory"])
def list_inventory_by_type(
    inventory_type: str,
    skip: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    """Get all inventory items of a specific type (system, subsystem, module, unit, component)."""
    query = select(Inventory).where(Inventory.inventory_type == inventory_type).offset(skip).limit(limit)
    items = session.exec(query).all()
    return [_inventory_to_read(session, item, include_instances=True) for item in items]


@router.get("/inventory/by-entity/{entity_id}/", response_model=List[schemas.InventoryRead], tags=["inventory"])
def list_inventory_by_entity(
    entity_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    """Get all inventory items associated with a specific entity."""
    query = select(Inventory).where(Inventory.entity_id == entity_id)
    items = session.exec(query).all()
    return [_inventory_to_read(session, item, include_instances=True) for item in items]


@router.get("/inventory/{inventory_id}/", response_model=schemas.InventoryRead, tags=["inventory"])
def get_inventory(
    inventory_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    inventory = session.get(Inventory, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    return _inventory_to_read(session, inventory, include_instances=True)


@router.put("/inventory/{inventory_id}/", response_model=schemas.InventoryRead, tags=["inventory"])
def update_inventory(
    inventory_id: int,
    inventory: schemas.InventoryUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_inventory")),
):
    db_inventory = session.get(Inventory, inventory_id)
    if not db_inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")

    update_data = inventory.model_dump(exclude_unset=True)
    inventory_type = update_data.get("inventory_type", db_inventory.inventory_type)

    if is_component_inventory(inventory_type):
        if "quantity" in update_data or "inventory_type" in update_data:
            quantity = update_data.get("quantity", db_inventory.quantity)
            update_data["quantity"] = _normalize_inventory_quantity(inventory_type, quantity)
    else:
        for field in (
            "quantity",
            "serial_number",
            "configuration_item",
            "status_id",
            "holder_user_id",
            "location",
            "added_date",
            "shelf_life_expires_at",
            "picture_url",
            "installation_date",
            "installed_by_id",
            "original_part_number",
            "original_serial_number",
        ):
            update_data.pop(field, None)

    if "manufacturer_part_number" in update_data:
        update_data["part_number"] = update_data.pop("manufacturer_part_number")

    for k, v in update_data.items():
        setattr(db_inventory, k, v)
    session.add(db_inventory)
    session.commit()
    session.refresh(db_inventory)
    return _inventory_to_read(session, db_inventory, include_instances=True)


@router.delete("/inventory/{inventory_id}/", tags=["inventory"])
def delete_inventory(
    inventory_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("delete_inventory")),
):
    inventory = session.get(Inventory, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    session.delete(inventory)
    session.commit()
    return {"ok": True}


@router.post(
    "/inventory/{inventory_id}/consume/",
    response_model=schemas.InventoryConsumeRead,
    tags=["inventory"],
)
def consume_inventory(
    inventory_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_inventory")),
):
    inventory = session.get(Inventory, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    consumed = consume_inventory_unit(session, inventory)
    session.commit()
    session.refresh(inventory)
    consumed_read = (
        schemas.InventoryInstanceRead.model_validate(consumed) if consumed else None
    )
    return schemas.InventoryConsumeRead(
        inventory=_inventory_to_read(session, inventory, include_instances=True),
        consumed_instance=consumed_read,
    )


# ===================== INVENTORY INSTANCE ENDPOINTS =====================
@router.get(
    "/inventory/{inventory_id}/instances/",
    response_model=List[schemas.InventoryInstanceRead],
    tags=["inventory"],
)
def list_inventory_instances(
    inventory_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    inventory = session.get(Inventory, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    if is_component_inventory(inventory.inventory_type):
        raise HTTPException(status_code=400, detail="Component inventory does not use instances")
    return session.exec(
        select(InventoryInstance)
        .where(InventoryInstance.inventory_id == inventory_id)
        .order_by(InventoryInstance.id)
    ).all()


@router.post(
    "/inventory/{inventory_id}/instances/",
    response_model=schemas.InventoryInstanceRead,
    tags=["inventory"],
)
def create_inventory_instance_endpoint(
    inventory_id: int,
    instance: schemas.InventoryInstanceCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("create_inventory")),
):
    inventory = session.get(Inventory, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    if is_component_inventory(inventory.inventory_type):
        raise HTTPException(status_code=400, detail="Component inventory does not use instances")

    data = instance.model_dump()
    if not (data.get("location") or "").strip():
        raise HTTPException(status_code=400, detail="Location is required for inventory instances")

    db_instance = create_inventory_instance(session, inventory, **data)
    session.commit()
    session.refresh(db_instance)
    return db_instance


@router.put(
    "/inventory/instances/{instance_id}/",
    response_model=schemas.InventoryInstanceRead,
    tags=["inventory"],
)
def update_inventory_instance(
    instance_id: int,
    instance: schemas.InventoryInstanceUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_inventory")),
):
    db_instance = session.get(InventoryInstance, instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Inventory instance not found")
    update_data = instance.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(db_instance, k, v)
    session.add(db_instance)
    session.commit()
    session.refresh(db_instance)
    return db_instance


@router.delete("/inventory/instances/{instance_id}/", tags=["inventory"])
def delete_inventory_instance(
    instance_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("delete_inventory")),
):
    db_instance = session.get(InventoryInstance, instance_id)
    if not db_instance:
        raise HTTPException(status_code=404, detail="Inventory instance not found")
    inventory = session.get(Inventory, db_instance.inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    session.delete(db_instance)
    session.flush()
    remaining = sync_inventory_quantity(session, inventory)
    if remaining == 0:
        session.delete(inventory)
    session.commit()
    return {"ok": True}
