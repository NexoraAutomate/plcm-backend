from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Response
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import Inventory, InventoryInstance, InventoryChildLink, InventoryIssuance, User
from app.schemas import schemas
from app.routers.auth import require_permission
from app.services.pagination import paginated_query
from app.services.inventory_service import (
    is_component_inventory,
    find_inventory_group,
    create_inventory_instance,
    sync_inventory_quantity,
    normalize_part_number,
    list_inventory_child_links,
    replace_inventory_child_links,
    delete_inventory_item,
)
from app.services.inventory_issuance_service import (
    available_quantity,
    reserved_quantity,
    instance_reservation_map,
    issue_inventory_unit,
    return_issuance,
    list_issuances,
    issuance_to_dict,
    consume_with_issuance,
    revert_entity_to_inventory,
    link_issuance_installed_entity,
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


def _instance_to_read(
    instance: InventoryInstance,
    *,
    reserved_map: dict[int, int] | None = None,
) -> schemas.InventoryInstanceRead:
    data = instance.model_dump()
    open_id = None
    if reserved_map and instance.id is not None:
        open_id = reserved_map.get(instance.id)
    data["is_reserved"] = open_id is not None
    data["open_issuance_id"] = open_id
    return schemas.InventoryInstanceRead.model_validate(data)


def _inventory_to_read(
    session: Session,
    inventory: Inventory,
    *,
    include_instances: bool = False,
) -> schemas.InventoryRead:
    data = inventory.model_dump()
    reserved = reserved_quantity(session, inventory.id)
    avail = available_quantity(session, inventory)
    data["reserved_quantity"] = reserved
    data["available_quantity"] = avail
    if is_component_inventory(inventory.inventory_type):
        data["instances"] = None
    elif include_instances:
        instances = session.exec(
            select(InventoryInstance)
            .where(InventoryInstance.inventory_id == inventory.id)
            .order_by(InventoryInstance.id)
        ).all()
        reserved_map = instance_reservation_map(session, inventory.id)
        data["instances"] = [
            _instance_to_read(inst, reserved_map=reserved_map) for inst in instances
        ]
    else:
        data["instances"] = None
    return schemas.InventoryRead.model_validate(data)


def _issuance_to_read(session: Session, row: InventoryIssuance) -> schemas.InventoryIssuanceRead:
    return schemas.InventoryIssuanceRead.model_validate(issuance_to_dict(session, row))


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
    sort_by: str | None = None,
    sort_order: str | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    where = Inventory.inventory_type == inventory_type if inventory_type else None
    items = paginated_query(
        session,
        Inventory,
        skip,
        limit,
        response,
        where=where,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return [_inventory_to_read(session, item, include_instances=True) for item in items]


@router.get("/inventory/by-type/{inventory_type}/", response_model=List[schemas.InventoryRead], tags=["inventory"])
def list_inventory_by_type(
    inventory_type: str,
    skip: int = 0,
    limit: int = 100,
    sort_by: str | None = None,
    sort_order: str | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    """Get all inventory items of a specific type (system, subsystem, module, unit, component)."""
    from app.services.sorting import apply_sort

    query = select(Inventory).where(Inventory.inventory_type == inventory_type)
    query = apply_sort(query, Inventory, sort_by=sort_by, sort_order=sort_order)
    items = session.exec(query.offset(skip).limit(limit)).all()
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


# ===================== ISSUANCE ENDPOINTS (before /inventory/{id}) =====================
@router.get(
    "/inventory/issuances/",
    response_model=List[schemas.InventoryIssuanceRead],
    tags=["inventory"],
)
def list_inventory_issuances(
    status: Optional[str] = Query(None),
    issued_to_user_id: Optional[int] = Query(None),
    issued_by_user_id: Optional[int] = Query(None),
    inventory_id: Optional[int] = Query(None),
    part_number: Optional[str] = Query(None),
    serial_number: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    rows = list_issuances(
        session,
        status=status,
        issued_to_user_id=issued_to_user_id,
        issued_by_user_id=issued_by_user_id,
        inventory_id=inventory_id,
        part_number=part_number,
        serial_number=serial_number,
        search=search,
    )
    return [_issuance_to_read(session, row) for row in rows]


@router.get(
    "/inventory/issuances/{issuance_id}/",
    response_model=schemas.InventoryIssuanceRead,
    tags=["inventory"],
)
def get_inventory_issuance(
    issuance_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    row = session.get(InventoryIssuance, issuance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issuance not found")
    return _issuance_to_read(session, row)


@router.post(
    "/inventory/issuances/{issuance_id}/return/",
    response_model=schemas.InventoryIssuanceRead,
    tags=["inventory"],
)
def return_inventory_issuance(
    issuance_id: int,
    body: schemas.InventoryIssuanceReturnRequest = schemas.InventoryIssuanceReturnRequest(),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("issue_inventory")),
):
    row = session.get(InventoryIssuance, issuance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issuance not found")
    updated = return_issuance(
        session,
        row,
        closed_by_id=current_user.id,
        notes=body.notes,
    )
    session.commit()
    session.refresh(updated)
    return _issuance_to_read(session, updated)


@router.post(
    "/inventory/issuances/{issuance_id}/link-install/",
    response_model=schemas.InventoryIssuanceRead,
    tags=["inventory"],
)
def link_issuance_install(
    issuance_id: int,
    body: schemas.InventoryIssuanceLinkInstallRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_inventory")),
):
    row = session.get(InventoryIssuance, issuance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issuance not found")
    updated = link_issuance_installed_entity(
        session,
        row,
        installed_entity_type=body.installed_entity_type,
        installed_entity_id=body.installed_entity_id,
    )
    session.commit()
    session.refresh(updated)
    return _issuance_to_read(session, updated)


@router.post(
    "/inventory/revert-to-stock/",
    response_model=schemas.InventoryRevertToStockRead,
    tags=["inventory"],
)
def revert_install_to_inventory(
    body: schemas.InventoryRevertToStockRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("revert_inventory_install")),
):
    inventory, restored, issuance = revert_entity_to_inventory(
        session,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        closed_by_id=current_user.id,
        notes=body.notes,
    )
    restored_read = None
    if restored is not None:
        reserved_map = instance_reservation_map(session, inventory.id)
        restored_read = _instance_to_read(restored, reserved_map=reserved_map)
    issuance_read = _issuance_to_read(session, issuance) if issuance else None
    session.commit()
    session.refresh(inventory)
    return schemas.InventoryRevertToStockRead(
        inventory=_inventory_to_read(session, inventory, include_instances=True),
        restored_instance=restored_read,
        issuance=issuance_read,
    )


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
    delete_inventory_item(session, inventory)
    session.commit()
    return {"ok": True}


@router.get(
    "/inventory/{inventory_id}/children/",
    response_model=List[schemas.InventoryChildLinkRead],
    tags=["inventory"],
)
def get_inventory_children(
    inventory_id: int,
    parent_instance_id: Optional[int] = Query(None),
    parent_instance_serial: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    inventory = session.get(Inventory, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    links = list_inventory_child_links(
        session,
        parent_inventory_id=inventory_id,
        parent_instance_id=parent_instance_id,
        parent_instance_serial=parent_instance_serial,
    )
    return links


@router.put(
    "/inventory/{inventory_id}/children/",
    response_model=List[schemas.InventoryChildLinkRead],
    tags=["inventory"],
)
def replace_inventory_children(
    inventory_id: int,
    body: schemas.InventoryChildrenReplace,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_inventory")),
):
    inventory = session.get(Inventory, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    if not can_add_inventory_children_type(inventory.inventory_type):
        raise HTTPException(status_code=400, detail="This inventory type cannot have children")

    links = replace_inventory_child_links(
        session,
        parent_inventory=inventory,
        parent_instance_id=body.parent_instance_id,
        parent_instance_serial=body.parent_instance_serial,
        children=[child.model_dump() for child in body.children],
    )
    session.commit()
    return links


def can_add_inventory_children_type(inventory_type: str) -> bool:
    return inventory_type != "component"


@router.post(
    "/inventory/{inventory_id}/issue/",
    response_model=schemas.InventoryIssuanceRead,
    tags=["inventory"],
)
def issue_inventory(
    inventory_id: int,
    body: schemas.InventoryIssueRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("issue_inventory")),
):
    inventory = session.get(Inventory, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    issuance = issue_inventory_unit(
        session,
        inventory,
        issued_to_user_id=body.issued_to_user_id,
        issued_by_user_id=current_user.id,
        quantity=body.quantity,
        instance_id=body.instance_id,
        target_entity_type=body.target_entity_type,
        target_entity_id=body.target_entity_id,
        notes=body.notes,
    )
    session.commit()
    session.refresh(issuance)
    return _issuance_to_read(session, issuance)


@router.post(
    "/inventory/{inventory_id}/consume/",
    response_model=schemas.InventoryConsumeRead,
    tags=["inventory"],
)
def consume_inventory(
    inventory_id: int,
    body: schemas.InventoryConsumeRequest = schemas.InventoryConsumeRequest(),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_inventory")),
):
    inventory = session.get(Inventory, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")
    consumed, issuance = consume_with_issuance(
        session,
        inventory,
        instance_id=body.instance_id,
        issuance_id=body.issuance_id,
        installed_by_id=current_user.id,
        installed_entity_type=body.installed_entity_type,
        installed_entity_id=body.installed_entity_id,
    )
    # Snapshot before commit — deleted instances expire and lose attribute access.
    consumed_read = (
        schemas.InventoryInstanceRead.model_validate(
            {
                **consumed.model_dump(),
                "is_reserved": False,
                "open_issuance_id": None,
            }
        )
        if consumed
        else None
    )
    issuance_read = _issuance_to_read(session, issuance) if issuance else None
    session.commit()
    session.refresh(inventory)
    return schemas.InventoryConsumeRead(
        inventory=_inventory_to_read(session, inventory, include_instances=True),
        consumed_instance=consumed_read,
        issuance=issuance_read,
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
    reserved_map = instance_reservation_map(session, inventory_id)
    instances = session.exec(
        select(InventoryInstance)
        .where(InventoryInstance.inventory_id == inventory_id)
        .order_by(InventoryInstance.id)
    ).all()
    return [_instance_to_read(inst, reserved_map=reserved_map) for inst in instances]


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
        delete_inventory_item(session, inventory)
    session.commit()
    return {"ok": True}
