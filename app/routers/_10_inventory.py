from typing import List, Optional
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, Query, Response, UploadFile, File, status
from fastapi.responses import StreamingResponse, FileResponse
from sqlmodel import Session, select, func, col
from app.database import get_session
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryChildLink,
    InventoryIssuance,
    InventoryReturnNotice,
    InventoryInstallerNotice,
    User,
    EntityAttachment,
)
from app.schemas import schemas
from app.routers.auth import get_current_user, require_permission
from app.auth import check_permission, is_inventory_manager
from app.services.pagination import paginated_query
from app.services.list_query import inventory_list_where
from app.services.entity_list_service import (
    EntityListError,
    validate_inventory_entity_name,
)
from app.services.inventory_service import (
    generate_inventory_instance_serial,
    find_inventory_group,
    find_inventory_catalog_group,
    create_inventory_instance,
    retire_inventory_instance_labels,
    sync_inventory_quantity,
    normalize_part_number,
    list_inventory_child_links,
    replace_inventory_child_links,
    delete_inventory_item,
)
from app.services.inventory_label_service import ensure_inventory_labels
from app.services.inventory_import_export import (
    build_export_csv,
    build_export_payload,
    import_inventory_payload,
)


def _raise_entity_list_error(exc: EntityListError) -> None:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
from app.services.inventory_issuance_service import (
    available_quantity,
    reserved_quantity,
    installed_used_quantity,
    instance_reservation_map,
    issue_inventory_unit,
    return_issuance,
    accept_return_issuance,
    reject_return_issuance,
    list_issuances,
    list_issuance_history,
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
    list_installer_notices,
    mark_installer_notice_read,
    mark_all_installer_notices_read,
    create_installer_notice_read,
    RESERVED_STATUSES,
)

router = APIRouter()


def _require_inventory_manager(user: User) -> None:
    if not is_inventory_manager(user):
        raise HTTPException(
            status_code=403,
            detail="Only inventory managers can manage warehouse inventory issuance",
        )


def _require_can_issue(user: User) -> None:
    if check_permission(user, "inventory.issue") or check_permission(user, "issue_inventory"):
        return
    if is_inventory_manager(user):
        return
    raise HTTPException(
        status_code=403,
        detail="Only inventory managers can issue inventory",
    )


def _require_can_receive_stock(user: User) -> None:
    """Admin/SubAdmin or workflow Inventory Manager may receive stock (Spec 05)."""
    if is_inventory_manager(user):
        return
    raise HTTPException(
        status_code=403,
        detail="Only inventory managers can receive stock",
    )


def _require_installer_not_manager(user: User) -> None:
    if is_inventory_manager(user):
        raise HTTPException(
            status_code=403,
            detail="Inventory managers cannot revert installs; installers revert, managers issue/accept returns",
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
    if quantity is None:
        return 1
    if quantity < 0:
        raise HTTPException(status_code=400, detail="Quantity cannot be negative")
    return quantity


def _instance_to_read(
    instance: InventoryInstance,
    *,
    reserved_map: dict[int, tuple[int, str]] | None = None,
    project_hold_map: dict[int, dict] | None = None,
    status_name: str | None = None,
) -> schemas.InventoryInstanceRead:
    # SQLAlchemy expires table-model attributes after commit.  Reading through
    # getattr refreshes those attributes; model_dump() alone only sees the
    # partially populated __dict__ and can omit required fields.
    data = {
        field_name: getattr(instance, field_name)
        for field_name in InventoryInstance.model_fields
    }
    open_id = None
    open_status = None
    if reserved_map and instance.id is not None:
        entry = reserved_map.get(instance.id)
        if entry is not None:
            open_id, open_status = entry
    hold = None
    if project_hold_map and instance.id is not None:
        hold = project_hold_map.get(instance.id)
    data["is_reserved"] = open_id is not None
    data["is_project_reserved"] = hold is not None
    data["status_name"] = status_name
    data["project_reservation"] = hold
    data["open_issuance_id"] = open_id
    data["open_issuance_status"] = open_status
    return schemas.InventoryInstanceRead.model_validate(data)


def _enrich_instance_read(
    session: Session, instance: InventoryInstance
) -> schemas.InventoryInstanceRead:
    reserved_map: dict[int, tuple[int, str]] = {}
    hold_map: dict[int, dict] = {}
    if instance.inventory_id:
        reserved_map = instance_reservation_map(session, instance.inventory_id)
        from app.services.inventory_reservation_service import project_holds_by_instance_id

        hold_map = project_holds_by_instance_id(session, instance.inventory_id)
    names = _instance_status_names(session, [instance])
    status_name = names.get(int(instance.status_id)) if instance.status_id else None
    return _instance_to_read(
        instance,
        reserved_map=reserved_map,
        project_hold_map=hold_map,
        status_name=status_name,
    )


def _instance_status_names(
    session: Session, instances: list[InventoryInstance]
) -> dict[int, str]:
    ids = {int(i.status_id) for i in instances if i.status_id is not None}
    if not ids:
        return {}
    from app.models.tables import Status

    rows = session.exec(select(Status).where(col(Status.id).in_(list(ids)))).all()
    return {int(s.id): s.status_name for s in rows if s.id is not None}


def _inventory_to_read(
    session: Session,
    inventory: Inventory,
    *,
    include_instances: bool = False,
    issued_to_user_id: Optional[int] = None,
) -> schemas.InventoryRead:
    # SQLAlchemy expires table-model attributes after commit.  Reading through
    # getattr refreshes those attributes; model_dump() alone only sees the
    # partially populated __dict__ and can omit required fields.
    data = {
        field_name: getattr(inventory, field_name)
        for field_name in Inventory.model_fields
    }
    reserved = reserved_quantity(session, inventory.id)
    avail = available_quantity(session, inventory)
    data["reserved_quantity"] = reserved
    data["available_quantity"] = avail
    data["total_used"] = installed_used_quantity(session, int(inventory.id))
    if include_instances:
        instances = session.exec(
            select(InventoryInstance)
            .where(InventoryInstance.inventory_id == inventory.id)
            .order_by(InventoryInstance.id)
        ).all()
        reserved_map = instance_reservation_map(session, inventory.id)
        from app.services.inventory_reservation_service import project_holds_by_instance_id

        hold_map = project_holds_by_instance_id(session, inventory.id)
        status_names = _instance_status_names(session, list(instances))
        if issued_to_user_id is not None:
            # Installer: only serials open-issued / return-pending to them
            open_rows = list(
                session.exec(
                    select(InventoryIssuance).where(
                        InventoryIssuance.inventory_id == inventory.id,
                        InventoryIssuance.issued_to_user_id == issued_to_user_id,
                        InventoryIssuance.status.in_(RESERVED_STATUSES),
                    )
                ).all()
            )
            allowed_instance_ids = {
                int(r.inventory_instance_id)
                for r in open_rows
                if r.inventory_instance_id is not None
            }
            instances = [i for i in instances if i.id in allowed_instance_ids]
            reserved_map = {k: v for k, v in reserved_map.items() if k in allowed_instance_ids}
            # Quantity comes from issuance ledger (not just linked instance rows)
            installable_qty = sum(
                int(r.quantity or 0) for r in open_rows if r.status == "issued"
            )
            pending_qty = sum(
                int(r.quantity or 0) for r in open_rows if r.status == "return_pending"
            )
            data["quantity"] = installable_qty + pending_qty
            data["reserved_quantity"] = pending_qty
            data["available_quantity"] = installable_qty
        data["instances"] = [
            _instance_to_read(
                inst,
                reserved_map=reserved_map,
                project_hold_map=hold_map,
                status_name=(
                    status_names.get(int(inst.status_id)) if inst.status_id else None
                ),
            )
            for inst in instances
        ]
    else:
        data["instances"] = None
        if issued_to_user_id is not None:
            installable_qty = session.exec(
                select(func.coalesce(func.sum(InventoryIssuance.quantity), 0)).where(
                    InventoryIssuance.inventory_id == inventory.id,
                    InventoryIssuance.issued_to_user_id == issued_to_user_id,
                    InventoryIssuance.status == "issued",
                )
            ).one()
            pending_qty = session.exec(
                select(func.coalesce(func.sum(InventoryIssuance.quantity), 0)).where(
                    InventoryIssuance.inventory_id == inventory.id,
                    InventoryIssuance.issued_to_user_id == issued_to_user_id,
                    InventoryIssuance.status == "return_pending",
                )
            ).one()
            installable_qty = int(installable_qty or 0)
            pending_qty = int(pending_qty or 0)
            data["quantity"] = installable_qty + pending_qty
            data["reserved_quantity"] = pending_qty
            data["available_quantity"] = installable_qty
    return schemas.InventoryRead.model_validate(data)


def _with_fcfs(
    read: schemas.InventoryRead,
    fulfillments: list[dict],
) -> schemas.InventoryRead:
    data = read.model_dump()
    data["fcfs_fulfillments"] = fulfillments
    return schemas.InventoryRead.model_validate(data)


def _run_receipt_fcfs(
    session: Session,
    inventory: Inventory,
    *,
    actor: User,
    instance: InventoryInstance | None = None,
    qty: int = 1,
) -> list[dict]:
    from app.services.inventory_shortage_service import match_and_auto_reserve_on_receipt

    return match_and_auto_reserve_on_receipt(
        session,
        inventory,
        actor=actor,
        instance=instance,
        qty=qty,
    )


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
    _require_can_receive_stock(current_user)
    data = inventory.model_dump()
    inventory_type = data["inventory_type"]

    try:
        validate_inventory_entity_name(
            session, name=data["name"], inventory_type=inventory_type
        )
    except EntityListError as exc:
        _raise_entity_list_error(exc)

    part_number = _resolve_part_number(data)
    if not normalize_part_number(part_number) and inventory_type != "component":
        raise HTTPException(
            status_code=400,
            detail="Part number is required for non-component inventory",
        )
    if part_number:
        data["part_number"] = part_number
    if not data.get("configuration_item"):
        data["configuration_item"] = part_number or data.get("name")
    quantity = _normalize_inventory_quantity(inventory_type, data.get("quantity"))
    if quantity < 1:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")
    instance_fields = _extract_instance_fields(data)
    if not instance_fields.get("configuration_item"):
        instance_fields["configuration_item"] = part_number or data.get("name")
    if not (instance_fields.get("location") or "").strip():
        instance_fields["location"] = "Warehouse"
    requested_serial = (instance_fields.get("serial_number") or "").strip()
    requested_original_serial = (instance_fields.get("original_serial_number") or "").strip()
    data["quantity"] = 0
    data["serial_number"] = None
    data["holder_user_id"] = None
    data["location"] = None
    data["shelf_life_expires_at"] = None
    data["picture_url"] = None
    data["installation_date"] = None
    data["installed_by_id"] = None
    data["original_part_number"] = None
    data["original_serial_number"] = None

    existing = find_inventory_catalog_group(
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

    created_instances: list[InventoryInstance] = []
    for index in range(quantity):
        unit_fields = dict(instance_fields)
        if requested_serial:
            unit_fields["serial_number"] = (
                requested_serial
                if quantity == 1
                else f"{requested_serial}-{index + 1:04d}"
            )
        else:
            unit_fields["serial_number"] = generate_inventory_instance_serial(
                session, db_inventory
            )
        if requested_original_serial:
            unit_fields["original_serial_number"] = (
                requested_original_serial
                if quantity == 1
                else f"{requested_original_serial}-{index + 1:04d}"
            )
        db_instance = create_inventory_instance(session, db_inventory, **unit_fields)
        created_instances.append(db_instance)
    session.commit()
    session.refresh(db_inventory)
    fulfillments: list[dict] = []
    for db_instance in created_instances:
        session.refresh(db_instance)
        fulfillments.extend(
            _run_receipt_fcfs(
                session,
                db_inventory,
                actor=current_user,
                instance=db_instance,
            )
        )
    ensure_inventory_labels(session, db_inventory, actor=current_user)
    session.commit()
    return _with_fcfs(
        _inventory_to_read(session, db_inventory, include_instances=True),
        fulfillments,
    )


@router.get("/inventory/", response_model=List[schemas.InventoryRead], tags=["inventory"])
def list_inventory(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    inventory_type: str = Query(None, description="Filter by inventory type (system, subsystem, module, unit, component)"),
    search: Optional[str] = Query(None),
    stock: Optional[str] = Query(None, description="available | reserved | out_of_stock"),
    sort_by: str | None = None,
    sort_order: str | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    where = inventory_list_where(
        scope=_scoped_inventory_filter(session, current_user),
        inventory_type=inventory_type,
        search=search,
        stock=stock,
    )
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


@router.get(
    "/inventory/stats/summary",
    response_model=schemas.InventoryStatsSummary,
    tags=["inventory"],
)
def inventory_stats_summary(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    from app.services.inventory_stats_service import build_inventory_stats_summary

    return schemas.InventoryStatsSummary(**build_inventory_stats_summary(session, current_user))


@router.get(
    "/inventory/ids/",
    response_model=schemas.InventoryIdsRead,
    tags=["inventory"],
)
def list_inventory_ids(
    inventory_type: str = Query(None, description="Filter by inventory type (system, subsystem, module, unit, component)"),
    search: Optional[str] = Query(None),
    stock: Optional[str] = Query(None, description="available | reserved | out_of_stock"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    """Return every matching inventory id for the current list filters (all pages)."""
    where = inventory_list_where(
        scope=_scoped_inventory_filter(session, current_user),
        inventory_type=inventory_type,
        search=search,
        stock=stock,
    )
    stmt = select(Inventory.id)
    if where is not None:
        stmt = stmt.where(where)
    ids = [int(item_id) for item_id in session.exec(stmt).all() if item_id is not None]
    return schemas.InventoryIdsRead(ids=ids)


# ---------------------------------------------------------------------------
# CSV / JSON export / import (one catalog row per part number; units as children)
# ---------------------------------------------------------------------------

def _filtered_inventory_items(
    session: Session,
    current_user: User,
    inventory_type: Optional[str],
    search: Optional[str],
) -> list[Inventory]:
    where = inventory_list_where(
        scope=_scoped_inventory_filter(session, current_user),
        inventory_type=inventory_type,
        search=search,
    )
    stmt = select(Inventory)
    if where is not None:
        stmt = stmt.where(where)
    return list(session.exec(stmt).all())


@router.get("/inventory/export-csv/", tags=["inventory"])
def export_inventory_csv(
    inventory_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    """Export one catalog row per part number. Serials are in `serial_numbers`."""
    items = _filtered_inventory_items(session, current_user, inventory_type, search)
    csv_text = build_export_csv(session, items)
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="inventory_export.csv"'},
    )


@router.get("/inventory/export-json/", tags=["inventory"])
def export_inventory_json(
    inventory_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    """Export nested JSON: each item has `instances[]` child serials."""
    items = _filtered_inventory_items(session, current_user, inventory_type, search)
    payload = build_export_payload(session, items)
    body = json.dumps(payload, indent=2)
    return StreamingResponse(
        iter([body]),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="inventory_export.json"'},
    )


async def _import_inventory_file(
    file: UploadFile,
    dry_run: bool,
    session: Session,
    current_user: User,
):
    if not is_inventory_manager(current_user):
        raise HTTPException(status_code=403, detail="Only inventory managers can import inventory")
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    return import_inventory_payload(
        session,
        filename=file.filename or "inventory.csv",
        text=text,
        dry_run=dry_run,
    )


@router.post("/inventory/import-csv/", tags=["inventory"])
async def import_inventory_csv(
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="Validate only; do not save"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("create_inventory")),
):
    """Import CSV or JSON. Same part number is merged; serials become child instances."""
    return await _import_inventory_file(file, dry_run, session, current_user)


@router.post("/inventory/import/", tags=["inventory"])
async def import_inventory(
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="Validate only; do not save"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("create_inventory")),
):
    """Import inventory from CSV or JSON. Serials attach to the matching part number."""
    return await _import_inventory_file(file, dry_run, session, current_user)


@router.post(
    "/inventory/bulk-delete/",
    response_model=schemas.InventoryBulkDeleteRead,
    tags=["inventory"],
)
def bulk_delete_inventory(
    body: schemas.InventoryBulkDeleteRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("delete_inventory")),
):
    _require_inventory_manager(current_user)
    ids = list(dict.fromkeys(int(item_id) for item_id in (body.ids or []) if item_id is not None))
    if not ids:
        raise HTTPException(status_code=400, detail="No inventory ids provided")

    deleted = 0
    not_found: list[int] = []
    for inventory_id in ids:
        inventory = session.get(Inventory, inventory_id)
        if not inventory:
            not_found.append(inventory_id)
            continue
        delete_inventory_item(session, inventory)
        deleted += 1
    session.commit()
    return schemas.InventoryBulkDeleteRead(deleted=deleted, not_found=not_found)


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


@router.get(
    "/inventory/issuances/{issuance_id}/history/",
    response_model=List[schemas.InventoryIssuanceEventRead],
    tags=["inventory"],
)
def get_inventory_issuance_history(
    issuance_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory_issuances")),
):
    row = session.get(InventoryIssuance, issuance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issuance not found")
    if not is_inventory_manager(current_user) and row.issued_to_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to view this issuance")
    events = list_issuance_history(session, row)
    if not is_inventory_manager(current_user):
        # Keep chain visible only for this installer's own issuances
        own_ids = {
            int(r)
            for r in session.exec(
                select(InventoryIssuance.id).where(
                    InventoryIssuance.issued_to_user_id == current_user.id
                )
            ).all()
            if r is not None
        }
        events = [e for e in events if int(e.get("issuance_id") or 0) in own_ids]
    return [
        schemas.InventoryIssuanceEventRead.model_validate(event)
        for event in events
    ]


def _require_issuance_view(
    session: Session,
    issuance_id: int,
    current_user: User,
) -> InventoryIssuance:
    row = session.get(InventoryIssuance, issuance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issuance not found")
    if not is_inventory_manager(current_user) and row.issued_to_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to view this issuance")
    return row


def _issuance_signature_read(session: Session, row: InventoryIssuance) -> schemas.InventoryIssuanceSignatureRead:
    from app.models.base import AttachmentType
    from app.services.issuance_signature_service import (
        get_issuance_attachment,
        issuance_signature_summary,
    )

    summary = issuance_signature_summary(session, row)
    signature_attachment = None
    proforma_attachment = None
    if summary.get("signature_attachment_id"):
        signature_attachment = session.get(EntityAttachment, summary["signature_attachment_id"])
    if summary.get("proforma_attachment_id"):
        proforma_attachment = session.get(EntityAttachment, summary["proforma_attachment_id"])
    if signature_attachment is None and summary.get("has_signature_attachment"):
        signature_attachment = get_issuance_attachment(
            session, int(row.id), AttachmentType.ISSUANCE_SIGNATURE
        )
    if proforma_attachment is None and summary.get("has_proforma_attachment"):
        proforma_attachment = get_issuance_attachment(
            session, int(row.id), AttachmentType.ISSUANCE_PROFORMA
        )
    return schemas.InventoryIssuanceSignatureRead(
        signature_type=summary.get("signature_type"),
        has_signature_attachment=bool(summary.get("has_signature_attachment")),
        has_proforma_attachment=bool(summary.get("has_proforma_attachment")),
        signature_attachment_id=signature_attachment.id if signature_attachment else None,
        proforma_attachment_id=proforma_attachment.id if proforma_attachment else None,
        signature_file_name=signature_attachment.file_name if signature_attachment else None,
        proforma_file_name=proforma_attachment.file_name if proforma_attachment else None,
        signature_mime_type=signature_attachment.mime_type if signature_attachment else None,
        proforma_mime_type=proforma_attachment.mime_type if proforma_attachment else None,
    )


@router.get(
    "/inventory/issuances/{issuance_id}/signature/",
    response_model=schemas.InventoryIssuanceSignatureRead,
    tags=["inventory"],
)
def get_inventory_issuance_signature(
    issuance_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory_issuances")),
):
    row = _require_issuance_view(session, issuance_id, current_user)
    return _issuance_signature_read(session, row)


@router.get(
    "/inventory/issuances/{issuance_id}/signature/{kind}/download/",
    tags=["inventory"],
)
def download_inventory_issuance_signature(
    issuance_id: int,
    kind: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory_issuances")),
):
    from pathlib import Path

    from app.models.base import AttachmentType, SignatureType
    from app.services.issuance_signature_service import get_issuance_attachment

    row = _require_issuance_view(session, issuance_id, current_user)
    normalized = kind.strip().lower()
    if normalized == "digital":
        attachment = get_issuance_attachment(
            session, int(row.id), AttachmentType.ISSUANCE_SIGNATURE
        )
        if attachment is None:
            payload = (row.signature_payload or "").strip()
            if (row.signature_type or "").upper() == SignatureType.DIGITAL.value and payload.startswith("data:"):
                import base64
                import re

                match = re.match(r"^data:([^;]+);base64,(.+)$", payload, re.DOTALL)
                if match:
                    mime = match.group(1).strip() or "image/png"
                    content = base64.b64decode(match.group(2))
                    return Response(
                        content=content,
                        media_type=mime,
                        headers={
                            "Content-Disposition": 'inline; filename="issuance-signature.png"'
                        },
                    )
            raise HTTPException(status_code=404, detail="Digital signature not found")
    elif normalized == "proforma":
        attachment = get_issuance_attachment(
            session, int(row.id), AttachmentType.ISSUANCE_PROFORMA
        )
        if attachment is None:
            raise HTTPException(status_code=404, detail="Issuance proforma not found")
    else:
        raise HTTPException(status_code=400, detail="Invalid signature kind")

    file_path = Path(attachment.file_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Signature file missing on disk")
    disposition = "inline" if normalized == "digital" else "attachment"
    return FileResponse(
        path=file_path,
        filename=attachment.file_name,
        media_type=attachment.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'{disposition}; filename="{attachment.file_name}"'},
    )


@router.post(
    "/inventory/issuances/{issuance_id}/proforma/",
    response_model=schemas.InventoryIssuanceSignatureRead,
    status_code=201,
    tags=["inventory"],
)
async def upload_inventory_issuance_proforma(
    issuance_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    import uuid
    from pathlib import Path

    from app.models.base import AttachmentType, SignatureType
    from app.services.issuance_signature_service import (
        ISSUANCE_OWNER_TYPE,
        UPLOAD_ROOT,
        get_issuance_attachment,
    )

    _require_can_issue(current_user)

    row = session.get(InventoryIssuance, issuance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Issuance not found")
    if (row.signature_type or "").upper() != SignatureType.HARD_COPY.value:
        raise HTTPException(
            status_code=400,
            detail="Proforma upload is only allowed for hard-copy issuances",
        )

    existing = get_issuance_attachment(session, int(row.id), AttachmentType.ISSUANCE_PROFORMA)
    if existing:
        old_path = Path(existing.file_path)
        if old_path.is_file():
            old_path.unlink()
        session.delete(existing)
        session.flush()

    ext = Path(file.filename or "proforma").suffix or ".pdf"
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest_dir = UPLOAD_ROOT / ISSUANCE_OWNER_TYPE / str(row.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / stored_name
    content = await file.read()
    dest_path.write_bytes(content)

    attachment = EntityAttachment(
        owner_type=ISSUANCE_OWNER_TYPE,
        owner_id=int(row.id),
        file_name=file.filename or stored_name,
        file_path=str(dest_path.as_posix()),
        mime_type=file.content_type,
        attachment_type=AttachmentType.ISSUANCE_PROFORMA,
        description="Inventory Issuance Proforma (hard copy scan)",
        uploaded_by_id=current_user.id,
    )
    session.add(attachment)
    session.commit()
    session.refresh(row)
    return _issuance_signature_read(session, row)


@router.post(
    "/inventory/issuances/{issuance_id}/return/",
    response_model=schemas.InventoryIssuanceRead,
    tags=["inventory"],
)
def return_inventory_issuance(
    issuance_id: int,
    body: schemas.InventoryIssuanceReturnRequest,
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
    body: schemas.InventoryIssuanceReturnRequest,
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
    body: schemas.InventoryIssuanceReturnRequest,
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
    search: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    _require_inventory_manager(current_user)
    rows = list_return_notices(
        session,
        unread_only=unread_only,
        pending_only=pending_only,
        search=search,
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


@router.get(
    "/inventory/installer-notices/",
    response_model=List[schemas.InventoryInstallerNoticeRead],
    tags=["inventory"],
)
def get_inventory_installer_notices(
    unread_only: bool = Query(False),
    search: Optional[str] = Query(None),
    all_users: bool = Query(
        False,
        description="Admin/SubAdmin only: list notices for every installer",
    ),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    if all_users:
        _require_inventory_manager(current_user)
        rows = list_installer_notices(
            session, user_id=None, unread_only=unread_only, search=search
        )
    else:
        rows = list_installer_notices(
            session,
            user_id=current_user.id,
            unread_only=unread_only,
            search=search,
        )
    return [
        schemas.InventoryInstallerNoticeRead.model_validate(
            create_installer_notice_read(r, session)
        )
        for r in rows
    ]


@router.post(
    "/inventory/installer-notices/{notice_id}/read/",
    response_model=schemas.InventoryInstallerNoticeRead,
    tags=["inventory"],
)
def read_inventory_installer_notice(
    notice_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    row = session.get(InventoryInstallerNotice, notice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Installer notice not found")
    if not is_inventory_manager(current_user) and row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Installer notice not found")
    updated = mark_installer_notice_read(session, row)
    session.commit()
    session.refresh(updated)
    return schemas.InventoryInstallerNoticeRead.model_validate(
        create_installer_notice_read(updated, session)
    )


@router.post(
    "/inventory/installer-notices/read-all/",
    tags=["inventory"],
)
def read_all_inventory_installer_notices(
    all_users: bool = Query(False),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    if all_users:
        _require_inventory_manager(current_user)
        count = mark_all_installer_notices_read(session, user_id=None)
    else:
        count = mark_all_installer_notices_read(session, user_id=current_user.id)
    session.commit()
    return {"ok": True, "marked": count}


@router.get(
    "/inventory/shortages/",
    response_model=List[schemas.InventoryShortageRead],
    tags=["inventory"],
)
def list_inventory_shortages(
    active_only: bool = Query(True),
    project_id: Optional[int] = Query(None),
    mine: bool = Query(False),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    from app.models.base import ShortageStatus
    from app.services.inventory_shortage_service import list_shortages, shortage_to_dict

    statuses = (
        [ShortageStatus.OPEN.value, ShortageStatus.PARTIAL.value]
        if active_only
        else None
    )
    hm_id = int(current_user.id) if mine else None
    rows = list_shortages(
        session,
        project_id=project_id,
        statuses=statuses,
        assigned_hm_id=hm_id,
    )
    return [
        schemas.InventoryShortageRead(**shortage_to_dict(r, session=session))
        for r in rows
    ]


@router.post(
    "/inventory/shortages/{shortage_id}/receive/",
    response_model=schemas.InventoryRead,
    tags=["inventory"],
)
def receive_inventory_shortage(
    shortage_id: int,
    body: schemas.InventoryShortageReceiveRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("inventory.receive")),
):
    from app.services.inventory_shortage_service import (
        InventoryShortageError,
        receive_shortage_stock,
    )

    _require_can_receive_stock(current_user)
    try:
        inventory, fulfillments = receive_shortage_stock(
            session,
            shortage_id,
            actor=current_user,
            quantity=body.quantity,
            part_number=body.part_number,
            serial_numbers=body.serial_numbers,
            location=body.location,
        )
    except InventoryShortageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    ensure_inventory_labels(session, inventory, actor=current_user)
    session.commit()
    return _with_fcfs(
        _inventory_to_read(
            session,
            inventory,
            include_instances=True,
        ),
        fulfillments,
    )


@router.get(
    "/inventory/shortage-notices/",
    response_model=List[schemas.InventoryShortageNoticeRead],
    tags=["inventory"],
)
def get_inventory_shortage_notices(
    unread_only: bool = Query(False),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_notifications")),
):
    from app.services.inventory_shortage_service import list_shortage_notices, notice_to_dict

    rows = list_shortage_notices(
        session,
        user_id=int(current_user.id),
        unread_only=unread_only,
    )
    return [schemas.InventoryShortageNoticeRead(**notice_to_dict(r)) for r in rows]


@router.post(
    "/inventory/shortage-notices/{notice_id}/read/",
    response_model=schemas.InventoryShortageNoticeRead,
    tags=["inventory"],
)
def read_inventory_shortage_notice(
    notice_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_notifications")),
):
    from app.models.tables import InventoryShortageNotice
    from app.services.inventory_shortage_service import (
        mark_shortage_notice_read,
        notice_to_dict,
    )

    row = session.get(InventoryShortageNotice, notice_id)
    if not row or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Shortage notice not found")
    updated = mark_shortage_notice_read(session, row)
    session.commit()
    session.refresh(updated)
    return schemas.InventoryShortageNoticeRead(**notice_to_dict(updated))


@router.post(
    "/inventory/shortage-notices/read-all/",
    tags=["inventory"],
)
def read_all_inventory_shortage_notices(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_notifications")),
):
    from app.services.inventory_shortage_service import mark_all_shortage_notices_read

    count = mark_all_shortage_notices_read(session, int(current_user.id))
    session.commit()
    return {"ok": True, "marked": count}


@router.get(
    "/inventory/reservation-expiry-notices/",
    response_model=List[schemas.InventoryReservationExpiryNoticeRead],
    tags=["inventory"],
)
def get_reservation_expiry_notices(
    unread_only: bool = Query(False),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_notifications")),
):
    from app.services.inventory_reservation_expiry_service import (
        list_expiry_notices,
        notice_to_dict,
    )

    rows = list_expiry_notices(
        session,
        user_id=int(current_user.id),
        unread_only=unread_only,
    )
    return [
        schemas.InventoryReservationExpiryNoticeRead(**notice_to_dict(r)) for r in rows
    ]


@router.post(
    "/inventory/reservation-expiry-notices/{notice_id}/read/",
    response_model=schemas.InventoryReservationExpiryNoticeRead,
    tags=["inventory"],
)
def read_reservation_expiry_notice(
    notice_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_notifications")),
):
    from app.models.tables import InventoryReservationExpiryNotice
    from app.services.inventory_reservation_expiry_service import (
        mark_expiry_notice_read,
        notice_to_dict,
    )

    row = session.get(InventoryReservationExpiryNotice, notice_id)
    if not row or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Expiry notice not found")
    updated = mark_expiry_notice_read(session, row)
    session.commit()
    session.refresh(updated)
    return schemas.InventoryReservationExpiryNoticeRead(**notice_to_dict(updated))


@router.post(
    "/inventory/reservation-expiry-notices/read-all/",
    tags=["inventory"],
)
def read_all_reservation_expiry_notices(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_notifications")),
):
    from app.services.inventory_reservation_expiry_service import (
        mark_all_expiry_notices_read,
    )

    count = mark_all_expiry_notices_read(session, int(current_user.id))
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
        restored_read = _enrich_instance_read(session, restored)
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
    requested_quantity = update_data.pop("quantity", None)
    for field in (
        "serial_number",
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
    fulfillments: list[dict] = []
    if requested_quantity is not None:
        target_quantity = _normalize_inventory_quantity(
            inventory_type, requested_quantity
        )
        instances = list(
            session.exec(
                select(InventoryInstance)
                .where(InventoryInstance.inventory_id == db_inventory.id)
                .order_by(InventoryInstance.id)
            ).all()
        )
        current_quantity = len(instances)
        if target_quantity > current_quantity:
            for _ in range(target_quantity - current_quantity):
                created = create_inventory_instance(
                    session,
                    db_inventory,
                    configuration_item=db_inventory.configuration_item
                    or db_inventory.part_number
                    or db_inventory.name,
                    location=db_inventory.location or "Warehouse",
                )
                fulfillments.extend(
                    _run_receipt_fcfs(
                        session,
                        db_inventory,
                        actor=current_user,
                        instance=created,
                    )
                )
        elif target_quantity < current_quantity:
            from app.services.inventory_reservation_service import (
                is_instance_free_for_project_reserve,
            )

            removable = [
                instance
                for instance in reversed(instances)
                if is_instance_free_for_project_reserve(session, instance)
            ]
            if len(removable) < current_quantity - target_quantity:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot reduce quantity below reserved or issued units",
                )
            for instance in removable[: current_quantity - target_quantity]:
                session.delete(instance)
        sync_inventory_quantity(session, db_inventory)
        ensure_inventory_labels(session, db_inventory, actor=current_user)
        session.commit()
    return _with_fcfs(
        _inventory_to_read(session, db_inventory, include_instances=True),
        fulfillments,
    )


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
    current_user: User = Depends(get_current_user),
):
    _require_can_issue(current_user)
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
        signature_type=body.signature_type,
        signature_payload=body.signature_payload,
        item_request_id=body.item_request_id,
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
    if not user_can_access_inventory(
        session, current_user, inventory_id, is_manager=is_inventory_manager(current_user)
    ):
        raise HTTPException(status_code=403, detail="Not allowed to view this inventory")

    reserved_map = instance_reservation_map(session, inventory_id)
    from app.services.inventory_reservation_service import project_holds_by_instance_id

    hold_map = project_holds_by_instance_id(session, inventory_id)
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

    status_names = _instance_status_names(session, list(instances))
    return [
        _instance_to_read(
            inst,
            reserved_map=reserved_map,
            project_hold_map=hold_map,
            status_name=(
                status_names.get(int(inst.status_id)) if inst.status_id else None
            ),
        )
        for inst in instances
    ]


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
    _require_can_receive_stock(current_user)
    inventory = session.get(Inventory, inventory_id)
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")

    data = instance.model_dump()
    if not (data.get("location") or "").strip():
        data["location"] = "Warehouse"

    db_instance = create_inventory_instance(session, inventory, **data)
    session.commit()
    session.refresh(db_instance)
    session.refresh(inventory)
    fulfillments = _run_receipt_fcfs(
        session,
        inventory,
        actor=current_user,
        instance=db_instance,
    )
    ensure_inventory_labels(session, inventory, actor=current_user)
    session.commit()
    read = _enrich_instance_read(session, db_instance)
    payload = read.model_dump()
    payload["fcfs_fulfillments"] = fulfillments
    return schemas.InventoryInstanceRead.model_validate(payload)


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
    if "serial_number" in update_data:
        serial_number = (update_data.get("serial_number") or "").strip()
        if not serial_number:
            inventory = session.get(Inventory, db_instance.inventory_id)
            if not inventory:
                raise HTTPException(status_code=404, detail="Inventory not found")
            serial_number = generate_inventory_instance_serial(session, inventory)
        duplicate = session.exec(
            select(InventoryInstance).where(
                InventoryInstance.inventory_id == db_instance.inventory_id,
                InventoryInstance.id != db_instance.id,
                func.lower(InventoryInstance.serial_number) == serial_number.lower(),
            )
        ).first()
        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Inventory unit '{serial_number}' already exists in this group",
            )
        update_data["serial_number"] = serial_number
    for k, v in update_data.items():
        setattr(db_instance, k, v)
    session.add(db_instance)
    session.commit()
    session.refresh(db_instance)
    return _enrich_instance_read(session, db_instance)


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
    if db_instance.id is not None:
        retire_inventory_instance_labels(session, int(db_instance.id))
    session.delete(db_instance)
    session.flush()
    remaining = sync_inventory_quantity(session, inventory)
    if remaining == 0:
        delete_inventory_item(session, inventory)
    session.commit()
    return {"ok": True}
