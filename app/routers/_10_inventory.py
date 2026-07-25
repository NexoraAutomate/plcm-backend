from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query, Response
from sqlmodel import Session, select, func
from app.database import get_session
from app.models.tables import Inventory, InventoryInstance, InventoryChildLink, InventoryIssuance, InventoryReturnNotice, User
from app.schemas import schemas
from app.routers.auth import require_permission
from app.auth import is_inventory_manager
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
    accept_return_issuance,
    reject_return_issuance,
    list_issuances,
    issuance_to_dict,
    consume_with_issuance,
    resolve_issuance_for_consume,
    revert_entity_to_inventory,
    link_issuance_installed_entity,
    inventory_ids_issued_to_user,
    user_can_access_inventory,
    list_return_notices,
    mark_return_notice_read,
    mark_all_return_notices_read,
    create_return_notice_read,
    RESERVED_STATUSES,
)

router = APIRouter()


def _require_inventory_manager(user: User) -> None:
    if not is_inventory_manager(user):
        raise HTTPException(
            status_code=403,
            detail="Only Admin or SubAdmin can manage warehouse inventory issuance",
        )


def _require_installer_not_manager(user: User) -> None:
    if is_inventory_manager(user):
        raise HTTPException(
            status_code=403,
            detail="Admin/SubAdmin cannot revert installs; installers revert, managers issue/accept returns",
        )


def _scoped_inventory_filter(session: Session, current_user: User):
    """Return SQLAlchemy where clause fragment or None for managers."""
    if is_inventory_manager(current_user):
        return None
    ids = inventory_ids_issued_to_user(session, current_user.id)
    if not ids:
        return Inventory.id == -1
    return Inventory.id.in_(ids)


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
    reserved_map: dict[int, tuple[int, str]] | None = None,
) -> schemas.InventoryInstanceRead:
    data = instance.model_dump()
    open_id = None
    open_status = None
    if reserved_map and instance.id is not None:
        entry = reserved_map.get(instance.id)
        if entry is not None:
            open_id, open_status = entry
    data["is_reserved"] = open_id is not None
    data["open_issuance_id"] = open_id
    data["open_issuance_status"] = open_status
    return schemas.InventoryInstanceRead.model_validate(data)


def _inventory_to_read(
    session: Session,
    inventory: Inventory,
    *,
    include_instances: bool = False,
    issued_to_user_id: Optional[int] = None,
) -> schemas.InventoryRead:
    data = inventory.model_dump()
    reserved = reserved_quantity(session, inventory.id)
    avail = available_quantity(session, inventory)
    data["reserved_quantity"] = reserved
    data["available_quantity"] = avail
    if is_component_inventory(inventory.inventory_type):
        data["instances"] = None
        if issued_to_user_id is not None:
            # Installer: show only quantity issued to them (not full warehouse)
            issued_qty = session.exec(
                select(func.coalesce(func.sum(InventoryIssuance.quantity), 0)).where(
                    InventoryIssuance.inventory_id == inventory.id,
                    InventoryIssuance.issued_to_user_id == issued_to_user_id,
                    InventoryIssuance.status.in_(RESERVED_STATUSES),
                )
            ).one()
            issued_qty = int(issued_qty or 0)
            data["quantity"] = issued_qty
            data["reserved_quantity"] = 0
            data["available_quantity"] = issued_qty
    elif include_instances:
        instances = session.exec(
            select(InventoryInstance)
            .where(InventoryInstance.inventory_id == inventory.id)
            .order_by(InventoryInstance.id)
        ).all()
        reserved_map = instance_reservation_map(session, inventory.id)
        if issued_to_user_id is not None:
            # Installer: only serials open-issued to them
            allowed_instance_ids = {
                int(r.inventory_instance_id)
                for r in session.exec(
                    select(InventoryIssuance).where(
                        InventoryIssuance.inventory_id == inventory.id,
                        InventoryIssuance.issued_to_user_id == issued_to_user_id,
                        InventoryIssuance.status.in_(RESERVED_STATUSES),
                        InventoryIssuance.inventory_instance_id.is_not(None),
                    )
                ).all()
                if r.inventory_instance_id is not None
            }
            instances = [i for i in instances if i.id in allowed_instance_ids]
            reserved_map = {k: v for k, v in reserved_map.items() if k in allowed_instance_ids}
            # Installer sees issued count only (not full warehouse quantity)
            issued_count = len(instances)
            data["quantity"] = issued_count
            data["reserved_quantity"] = 0
            data["available_quantity"] = issued_count
        data["instances"] = [
            _instance_to_read(inst, reserved_map=reserved_map) for inst in instances
        ]
    else:
        data["instances"] = None
        if issued_to_user_id is not None:
            issued_count = session.exec(
                select(func.coalesce(func.sum(InventoryIssuance.quantity), 0)).where(
                    InventoryIssuance.inventory_id == inventory.id,
                    InventoryIssuance.issued_to_user_id == issued_to_user_id,
                    InventoryIssuance.status.in_(RESERVED_STATUSES),
                )
            ).one()
            issued_count = int(issued_count or 0)
            data["quantity"] = issued_count
            data["reserved_quantity"] = 0
            data["available_quantity"] = issued_count
    return schemas.InventoryRead.model_validate(data)


def _read_for_user(
    session: Session,
    inventory: Inventory,
    current_user: User,
    *,
    include_instances: bool = True,
) -> schemas.InventoryRead:
    issued_to = None if is_inventory_manager(current_user) else current_user.id
    return _inventory_to_read(
        session,
        inventory,
        include_instances=include_instances,
        issued_to_user_id=issued_to,
    )


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
    _require_inventory_manager(current_user)
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
    scope = _scoped_inventory_filter(session, current_user)
    type_filter = Inventory.inventory_type == inventory_type if inventory_type else None
    if scope is not None and type_filter is not None:
        where = (scope) & (type_filter)
    elif scope is not None:
        where = scope
    else:
        where = type_filter
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
    return [_read_for_user(session, item, current_user) for item in items]


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
    scope = _scoped_inventory_filter(session, current_user)
    if scope is not None:
        query = query.where(scope)
    query = apply_sort(query, Inventory, sort_by=sort_by, sort_order=sort_order)
    items = session.exec(query.offset(skip).limit(limit)).all()
    return [_read_for_user(session, item, current_user) for item in items]


@router.get("/inventory/by-entity/{entity_id}/", response_model=List[schemas.InventoryRead], tags=["inventory"])
def list_inventory_by_entity(
    entity_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    """Get all inventory items associated with a specific entity."""
    query = select(Inventory).where(Inventory.entity_id == entity_id)
    scope = _scoped_inventory_filter(session, current_user)
    if scope is not None:
        query = query.where(scope)
    items = session.exec(query).all()
    return [_read_for_user(session, item, current_user) for item in items]


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
    current_user: User = Depends(require_permission("view_inventory_issuances")),
):
    manager = is_inventory_manager(current_user)
    effective_issued_to = issued_to_user_id
    if not manager:
        effective_issued_to = current_user.id
    rows = list_issuances(
        session,
        status=status,
        issued_to_user_id=effective_issued_to,
        issued_by_user_id=issued_by_user_id if manager else None,
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
    current_user: User = Depends(require_permission("view_inventory_issuances")),
):
    row = session.get(InventoryIssuance, issuance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issuance not found")
    if not is_inventory_manager(current_user) and row.issued_to_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to view this issuance")
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
    current_user: User = Depends(require_permission("view_inventory")),
):
    row = session.get(InventoryIssuance, issuance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issuance not found")
    updated, _notice = return_issuance(
        session,
        row,
        closed_by=current_user,
        is_manager=is_inventory_manager(current_user),
        notes=body.notes,
    )
    session.commit()
    session.refresh(updated)
    return _issuance_to_read(session, updated)


@router.post(
    "/inventory/issuances/{issuance_id}/accept-return/",
    response_model=schemas.InventoryIssuanceRead,
    tags=["inventory"],
)
def accept_inventory_return(
    issuance_id: int,
    body: schemas.InventoryIssuanceReturnRequest = schemas.InventoryIssuanceReturnRequest(),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    _require_inventory_manager(current_user)
    row = session.get(InventoryIssuance, issuance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issuance not found")
    updated, _notice = accept_return_issuance(
        session,
        row,
        decided_by=current_user,
        notes=body.notes,
    )
    session.commit()
    session.refresh(updated)
    return _issuance_to_read(session, updated)


@router.post(
    "/inventory/issuances/{issuance_id}/reject-return/",
    response_model=schemas.InventoryIssuanceRead,
    tags=["inventory"],
)
def reject_inventory_return(
    issuance_id: int,
    body: schemas.InventoryIssuanceReturnRequest = schemas.InventoryIssuanceReturnRequest(),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    _require_inventory_manager(current_user)
    row = session.get(InventoryIssuance, issuance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issuance not found")
    updated, _notice = reject_return_issuance(
        session,
        row,
        decided_by=current_user,
        notes=body.notes,
    )
    session.commit()
    session.refresh(updated)
    return _issuance_to_read(session, updated)


@router.get(
    "/inventory/return-notices/",
    response_model=List[schemas.InventoryReturnNoticeRead],
    tags=["inventory"],
)
def get_inventory_return_notices(
    unread_only: bool = Query(False),
    pending_only: bool = Query(False),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    _require_inventory_manager(current_user)
    rows = list_return_notices(
        session, unread_only=unread_only, pending_only=pending_only
    )
    return [
        schemas.InventoryReturnNoticeRead.model_validate(create_return_notice_read(r))
        for r in rows
    ]


@router.post(
    "/inventory/return-notices/{notice_id}/read/",
    response_model=schemas.InventoryReturnNoticeRead,
    tags=["inventory"],
)
def read_inventory_return_notice(
    notice_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    _require_inventory_manager(current_user)
    row = session.get(InventoryReturnNotice, notice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Return notice not found")
    updated = mark_return_notice_read(session, row)
    session.commit()
    session.refresh(updated)
    return schemas.InventoryReturnNoticeRead.model_validate(
        create_return_notice_read(updated)
    )


@router.post(
    "/inventory/return-notices/read-all/",
    tags=["inventory"],
)
def read_all_inventory_return_notices(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    _require_inventory_manager(current_user)
    count = mark_all_return_notices_read(session)
    session.commit()
    return {"ok": True, "marked": count}


@router.post(
    "/inventory/issuances/{issuance_id}/link-install/",
    response_model=schemas.InventoryIssuanceRead,
    tags=["inventory"],
)
def link_issuance_install(
    issuance_id: int,
    body: schemas.InventoryIssuanceLinkInstallRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    row = session.get(InventoryIssuance, issuance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issuance not found")
    if (
        not is_inventory_manager(current_user)
        and row.issued_to_user_id != current_user.id
        and row.installed_by_id != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="You can only link installs for your own issuances",
        )
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
    _require_installer_not_manager(current_user)
    inventory, restored, issuance = revert_entity_to_inventory(
        session,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        closed_by=current_user,
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
    if not user_can_access_inventory(
        session, current_user, inventory.id, is_manager=is_inventory_manager(current_user)
    ):
        raise HTTPException(status_code=403, detail="Not allowed to view this inventory item")
    return _read_for_user(session, inventory, current_user)


@router.put("/inventory/{inventory_id}/", response_model=schemas.InventoryRead, tags=["inventory"])
def update_inventory(
    inventory_id: int,
    inventory: schemas.InventoryUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_inventory")),
):
    _require_inventory_manager(current_user)
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
    _require_inventory_manager(current_user)
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
    _require_inventory_manager(current_user)
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
    current_user: User = Depends(require_permission("view_inventory")),
):
    inventory = session.get(Inventory, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")

    manager = is_inventory_manager(current_user)
    effective_issuance_id = body.issuance_id

    if not manager:
        if not user_can_access_inventory(
            session, current_user, inventory.id, is_manager=False
        ):
            raise HTTPException(
                status_code=403,
                detail="You can only install inventory issued to you",
            )
        issuance = resolve_issuance_for_consume(
            session,
            inventory,
            issuance_id=effective_issuance_id,
            instance_id=body.instance_id,
        )
        if issuance is None:
            # Components / auto-match: pick caller's open issuance for this group
            issuance = session.exec(
                select(InventoryIssuance)
                .where(
                    InventoryIssuance.inventory_id == inventory.id,
                    InventoryIssuance.issued_to_user_id == current_user.id,
                    InventoryIssuance.status == "issued",
                )
                .order_by(InventoryIssuance.id)
            ).first()
            if issuance is not None:
                effective_issuance_id = issuance.id
        if issuance is None or issuance.issued_to_user_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="You can only install inventory issued to you",
            )

    consumed, issuance = consume_with_issuance(
        session,
        inventory,
        instance_id=body.instance_id,
        issuance_id=effective_issuance_id,
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
                "open_issuance_status": None,
            }
        )
        if consumed
        else None
    )
    issuance_read = _issuance_to_read(session, issuance) if issuance else None
    session.commit()
    session.refresh(inventory)
    return schemas.InventoryConsumeRead(
        inventory=_read_for_user(session, inventory, current_user, include_instances=True),
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
    if not user_can_access_inventory(
        session, current_user, inventory_id, is_manager=is_inventory_manager(current_user)
    ):
        raise HTTPException(status_code=403, detail="Not allowed to view this inventory")

    reserved_map = instance_reservation_map(session, inventory_id)
    instances = session.exec(
        select(InventoryInstance)
        .where(InventoryInstance.inventory_id == inventory_id)
        .order_by(InventoryInstance.id)
    ).all()

    if not is_inventory_manager(current_user):
        allowed_instance_ids = {
            int(r.inventory_instance_id)
            for r in session.exec(
                select(InventoryIssuance).where(
                    InventoryIssuance.inventory_id == inventory_id,
                    InventoryIssuance.issued_to_user_id == current_user.id,
                    InventoryIssuance.status.in_(RESERVED_STATUSES),
                    InventoryIssuance.inventory_instance_id.is_not(None),
                )
            ).all()
            if r.inventory_instance_id is not None
        }
        instances = [i for i in instances if i.id in allowed_instance_ids]
        reserved_map = {k: v for k, v in reserved_map.items() if k in allowed_instance_ids}

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
