from typing import List, Optional
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, Query, Response, UploadFile, File
from fastapi.responses import StreamingResponse
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
    is_component_inventory,
    find_inventory_group,
    create_inventory_instance,
    sync_inventory_quantity,
    normalize_part_number,
    list_inventory_child_links,
    replace_inventory_child_links,
    delete_inventory_item,
)


def _raise_entity_list_error(exc: EntityListError) -> None:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
from app.services.inventory_issuance_service import (
    available_quantity,
    reserved_quantity,
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
            detail="Only Admin or SubAdmin can manage warehouse inventory issuance",
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
    from app.domain.workflow_roles import WorkflowRole, has_workflow_role

    names = [r.name for r in (user.roles or []) if r.name]
    if has_workflow_role(names, WorkflowRole.IM):
        return
    raise HTTPException(
        status_code=403,
        detail="Only inventory managers can receive stock",
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
    project_hold_map: dict[int, dict] | None = None,
    status_name: str | None = None,
) -> schemas.InventoryInstanceRead:
    data = instance.model_dump()
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
    data = inventory.model_dump()
    reserved = reserved_quantity(session, inventory.id)
    avail = available_quantity(session, inventory)
    data["reserved_quantity"] = reserved
    data["available_quantity"] = avail
    if is_component_inventory(inventory.inventory_type):
        data["instances"] = None
        if issued_to_user_id is not None:
            # Installer: held qty includes return_pending; available = installable only
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
    elif include_instances:
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
        fulfillments = _run_receipt_fcfs(
            session,
            db_inventory,
            actor=current_user,
            qty=int(db_inventory.quantity or 0),
        )
        return _with_fcfs(_inventory_to_read(session, db_inventory), fulfillments)

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

    db_instance = create_inventory_instance(session, db_inventory, **instance_fields)
    session.commit()
    session.refresh(db_inventory)
    session.refresh(db_instance)
    fulfillments = _run_receipt_fcfs(
        session,
        db_inventory,
        actor=current_user,
        instance=db_instance,
    )
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


# ---------------------------------------------------------------------------
# CSV export / import
# ---------------------------------------------------------------------------

CSV_EXPORT_FIELDS = [
    "id", "name", "inventory_type", "part_number", "original_part_number",
    "serial_number", "original_serial_number", "quantity", "description",
    "oem_name", "configuration_item", "sku", "location",
    "holder_user_id", "status_id", "added_date", "shelf_life_expires_at",
    "installation_date", "installed_by_id", "picture_url", "entity_id",
    "updated_at",
]

CSV_IMPORT_REQUIRED = ["name", "inventory_type"]
CSV_IMPORT_OPTIONAL = [
    "part_number", "original_part_number", "serial_number", "original_serial_number",
    "quantity", "description", "oem_name", "configuration_item", "sku",
    "location", "shelf_life_expires_at",
]
CSV_VALID_TYPES = {"system", "subsystem", "module", "unit", "component"}


@router.get("/inventory/export-csv/", tags=["inventory"])
def export_inventory_csv(
    inventory_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_inventory")),
):
    """Export all (or filtered) inventory rows as a CSV file."""
    where = inventory_list_where(
        scope=_scoped_inventory_filter(session, current_user),
        inventory_type=inventory_type,
        search=search,
    )
    stmt = select(Inventory)
    if where is not None:
        stmt = stmt.where(where)
    items = session.exec(stmt).all()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_EXPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for item in items:
        row = item.model_dump()
        for field in ("added_date", "updated_at", "shelf_life_expires_at", "installation_date"):
            if row.get(field) is not None:
                row[field] = row[field].isoformat()
        writer.writerow(row)

    output.seek(0)
    filename = "inventory_export.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/inventory/import-csv/", tags=["inventory"])
async def import_inventory_csv(
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="Validate only; do not save"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("create_inventory")),
):
    """Import inventory items from a CSV file.

    Returns a summary of created rows (or validation errors on dry_run=true).
    """
    if not is_inventory_manager(current_user):
        raise HTTPException(status_code=403, detail="Only inventory managers can import CSV")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV file appears to be empty")

    # Validate required columns
    missing_cols = [c for c in CSV_IMPORT_REQUIRED if c not in (reader.fieldnames or [])]
    if missing_cols:
        raise HTTPException(
            status_code=400,
            detail=f"CSV is missing required columns: {', '.join(missing_cols)}",
        )

    errors: list[dict] = []
    created: list[dict] = []
    valid_row_count = 0

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

        quantity_raw = (row.get("quantity") or "").strip()
        quantity = 0
        if quantity_raw:
            try:
                quantity = int(quantity_raw)
                if quantity < 0:
                    row_errors.append("'quantity' cannot be negative")
            except ValueError:
                row_errors.append(f"'quantity' must be an integer, got: {quantity_raw!r}")

        shelf_life_expires_at = None
        shelf_raw = (row.get("shelf_life_expires_at") or "").strip()
        if shelf_raw:
            try:
                shelf_life_expires_at = datetime.fromisoformat(shelf_raw)
            except ValueError:
                row_errors.append(
                    f"'shelf_life_expires_at' must be ISO 8601 datetime, got: {shelf_raw!r}"
                )

        if row_errors:
            errors.append({"row": row_num, "errors": row_errors})
            continue

        valid_row_count += 1
        if not dry_run:
            inv = Inventory(
                name=name,
                inventory_type=inventory_type,
                part_number=(row.get("part_number") or "").strip() or None,
                original_part_number=(row.get("original_part_number") or "").strip() or None,
                serial_number=(row.get("serial_number") or "").strip() or None,
                original_serial_number=(row.get("original_serial_number") or "").strip() or None,
                quantity=quantity,
                description=(row.get("description") or "").strip() or None,
                oem_name=(row.get("oem_name") or "").strip() or None,
                configuration_item=(row.get("configuration_item") or "").strip() or None,
                sku=(row.get("sku") or "").strip() or None,
                location=(row.get("location") or "").strip() or None,
                shelf_life_expires_at=shelf_life_expires_at,
                added_date=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(inv)
            session.flush()
            created.append({"row": row_num, "id": inv.id, "name": inv.name})

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "CSV contains validation errors", "errors": errors},
        )

    if not dry_run:
        session.commit()
        return {"imported": len(created), "rows": created}

    # dry_run — return count of valid rows
    return {"dry_run": True, "valid_rows": valid_row_count, "errors": []}


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
    return [schemas.InventoryShortageRead(**shortage_to_dict(r)) for r in rows]


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

    previous_qty = int(db_inventory.quantity or 0)
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
    fulfillments: list[dict] = []
    if is_component_inventory(db_inventory.inventory_type):
        delta = int(db_inventory.quantity or 0) - previous_qty
        if delta > 0:
            fulfillments = _run_receipt_fcfs(
                session,
                db_inventory,
                actor=current_user,
                qty=delta,
            )
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
    if is_component_inventory(inventory.inventory_type):
        raise HTTPException(status_code=400, detail="Component inventory does not use instances")
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
    if is_component_inventory(inventory.inventory_type):
        raise HTTPException(status_code=400, detail="Component inventory does not use instances")

    data = instance.model_dump()
    if not (data.get("location") or "").strip():
        raise HTTPException(status_code=400, detail="Location is required for inventory instances")

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
    session.delete(db_instance)
    session.flush()
    remaining = sync_inventory_quantity(session, inventory)
    if remaining == 0:
        delete_inventory_item(session, inventory)
    session.commit()
    return {"ok": True}
