"""Inventory issuance: issue → reserve → install / return / revert."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select, func, col

from app.models.base import EntityType, IssuanceStatus
from app.models.helpers import _ENTITY_MODEL_MAP
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryIssuance,
    InventoryChildLink,
    InventoryReturnNotice,
    User,
)
from app.services.inventory_service import (
    is_component_inventory,
    consume_inventory_unit,
    restore_inventory_unit,
    find_inventory_group,
    sync_inventory_quantity,
)


OPEN_STATUS = IssuanceStatus.ISSUED.value


def inventory_ids_issued_to_user(session: Session, user_id: int) -> list[int]:
    """Inventory group IDs with an open issuance to this user."""
    rows = session.exec(
        select(InventoryIssuance.inventory_id).where(
            InventoryIssuance.issued_to_user_id == user_id,
            InventoryIssuance.status == OPEN_STATUS,
        )
    ).all()
    return list({int(r) for r in rows if r is not None})


def user_can_access_inventory(
    session: Session,
    user: User,
    inventory_id: int,
    *,
    is_manager: bool,
) -> bool:
    if is_manager:
        return True
    return inventory_id in inventory_ids_issued_to_user(session, user.id)


def _user_display_name(user: Optional[User]) -> Optional[str]:
    if not user:
        return None
    return (user.full_name or user.username or "").strip() or None


def issuance_to_dict(session: Session, row: InventoryIssuance) -> dict:
    issued_to = session.get(User, row.issued_to_user_id) if row.issued_to_user_id else None
    issued_by = session.get(User, row.issued_by_user_id) if row.issued_by_user_id else None
    installed_by = session.get(User, row.installed_by_id) if row.installed_by_id else None
    closed_by = session.get(User, row.closed_by_id) if row.closed_by_id else None
    data = row.model_dump()
    data["issued_to_name"] = _user_display_name(issued_to)
    data["issued_by_name"] = _user_display_name(issued_by)
    data["installed_by_name"] = _user_display_name(installed_by)
    data["closed_by_name"] = _user_display_name(closed_by)
    return data


def list_open_issuances_for_inventory(
    session: Session,
    inventory_id: int,
) -> List[InventoryIssuance]:
    return list(
        session.exec(
            select(InventoryIssuance).where(
                InventoryIssuance.inventory_id == inventory_id,
                InventoryIssuance.status == OPEN_STATUS,
            )
        ).all()
    )


def reserved_quantity(session: Session, inventory_id: int) -> int:
    total = session.exec(
        select(func.coalesce(func.sum(InventoryIssuance.quantity), 0)).where(
            InventoryIssuance.inventory_id == inventory_id,
            InventoryIssuance.status == OPEN_STATUS,
        )
    ).one()
    return int(total or 0)


def open_issuance_for_instance(
    session: Session,
    instance_id: int,
) -> Optional[InventoryIssuance]:
    return session.exec(
        select(InventoryIssuance).where(
            InventoryIssuance.inventory_instance_id == instance_id,
            InventoryIssuance.status == OPEN_STATUS,
        )
    ).first()


def available_quantity(session: Session, inventory: Inventory) -> int:
    reserved = reserved_quantity(session, inventory.id)
    total = inventory.quantity or 0
    return max(0, total - reserved)


def instance_reservation_map(
    session: Session,
    inventory_id: int,
) -> dict[int, int]:
    """Map instance_id -> open issuance id."""
    rows = session.exec(
        select(InventoryIssuance).where(
            InventoryIssuance.inventory_id == inventory_id,
            InventoryIssuance.status == OPEN_STATUS,
            InventoryIssuance.inventory_instance_id.is_not(None),
        )
    ).all()
    return {
        int(r.inventory_instance_id): int(r.id)
        for r in rows
        if r.inventory_instance_id is not None and r.id is not None
    }


def issue_inventory_unit(
    session: Session,
    inventory: Inventory,
    *,
    issued_to_user_id: int,
    issued_by_user_id: int,
    quantity: int = 1,
    instance_id: Optional[int] = None,
    target_entity_type: Optional[str] = None,
    target_entity_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> InventoryIssuance:
    if quantity < 1:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")

    issued_to = session.get(User, issued_to_user_id)
    if not issued_to:
        raise HTTPException(status_code=404, detail="Developer (issued_to user) not found")

    serial_number: Optional[str] = None
    resolved_instance_id: Optional[int] = None

    if is_component_inventory(inventory.inventory_type):
        if instance_id is not None:
            raise HTTPException(
                status_code=400,
                detail="Component inventory does not use instances",
            )
        avail = available_quantity(session, inventory)
        if quantity > avail:
            raise HTTPException(
                status_code=400,
                detail=f"Only {avail} unit(s) available to issue (reserved stock excluded)",
            )
    else:
        if quantity != 1:
            raise HTTPException(
                status_code=400,
                detail="Serialized inventory must be issued one unit at a time",
            )
        if instance_id is None:
            raise HTTPException(status_code=400, detail="instance_id is required for serialized stock")
        instance = session.get(InventoryInstance, instance_id)
        if not instance or instance.inventory_id != inventory.id:
            raise HTTPException(status_code=404, detail="Inventory instance not found")
        existing = open_issuance_for_instance(session, instance.id)
        if existing:
            raise HTTPException(
                status_code=400,
                detail="This serial is already issued/reserved",
            )
        resolved_instance_id = instance.id
        serial_number = instance.serial_number

    issuance = InventoryIssuance(
        inventory_id=inventory.id,
        inventory_instance_id=resolved_instance_id,
        quantity=quantity,
        issued_to_user_id=issued_to_user_id,
        issued_by_user_id=issued_by_user_id,
        issued_at=datetime.now(timezone.utc),
        status=OPEN_STATUS,
        target_entity_type=(target_entity_type or "").strip().lower() or None,
        target_entity_id=target_entity_id,
        part_number=inventory.part_number,
        serial_number=serial_number or inventory.serial_number,
        inventory_name=inventory.name,
        inventory_type=inventory.inventory_type,
        notes=notes,
    )
    session.add(issuance)
    session.flush()
    return issuance


def return_issuance(
    session: Session,
    issuance: InventoryIssuance,
    *,
    closed_by: User,
    is_manager: bool,
    notes: Optional[str] = None,
) -> Tuple[InventoryIssuance, InventoryReturnNotice]:
    if issuance.status != OPEN_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"Only open issuances can be returned (current status: {issuance.status})",
        )
    if not is_manager and issuance.issued_to_user_id != closed_by.id:
        raise HTTPException(
            status_code=403,
            detail="You can only return inventory issued to you",
        )

    issuance.status = IssuanceStatus.RETURNED.value
    issuance.closed_at = datetime.now(timezone.utc)
    issuance.closed_by_id = closed_by.id
    if notes:
        issuance.notes = ((issuance.notes or "") + f"\nReturn: {notes}").strip()
    session.add(issuance)
    session.flush()

    returned_by_name = _user_display_name(closed_by) or closed_by.username
    notice = InventoryReturnNotice(
        issuance_id=issuance.id,
        inventory_id=issuance.inventory_id,
        inventory_name=issuance.inventory_name,
        part_number=issuance.part_number,
        serial_number=issuance.serial_number,
        returned_by_user_id=closed_by.id,
        returned_by_name=returned_by_name,
        created_at=datetime.now(timezone.utc),
    )
    session.add(notice)
    session.flush()
    return issuance, notice


def create_return_notice_read(notice: InventoryReturnNotice) -> dict:
    return notice.model_dump()


def list_return_notices(
    session: Session,
    *,
    unread_only: bool = False,
) -> List[InventoryReturnNotice]:
    stmt = select(InventoryReturnNotice).order_by(col(InventoryReturnNotice.created_at).desc())
    if unread_only:
        stmt = stmt.where(InventoryReturnNotice.read_at.is_(None))
    return list(session.exec(stmt).all())


def mark_return_notice_read(
    session: Session,
    notice: InventoryReturnNotice,
) -> InventoryReturnNotice:
    notice.read_at = datetime.now(timezone.utc)
    session.add(notice)
    session.flush()
    return notice


def mark_all_return_notices_read(session: Session) -> int:
    rows = session.exec(
        select(InventoryReturnNotice).where(InventoryReturnNotice.read_at.is_(None))
    ).all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.read_at = now
        session.add(row)
    session.flush()
    return len(rows)


def resolve_issuance_for_consume(
    session: Session,
    inventory: Inventory,
    *,
    issuance_id: Optional[int] = None,
    instance_id: Optional[int] = None,
) -> Optional[InventoryIssuance]:
    """Resolve open issuance for consume; raise if reserved without matching issuance."""
    if issuance_id is not None:
        issuance = session.get(InventoryIssuance, issuance_id)
        if not issuance or issuance.inventory_id != inventory.id:
            raise HTTPException(status_code=404, detail="Issuance not found")
        if issuance.status != OPEN_STATUS:
            raise HTTPException(
                status_code=400,
                detail=f"Issuance is not open (status: {issuance.status})",
            )
        if (
            not is_component_inventory(inventory.inventory_type)
            and instance_id is not None
            and issuance.inventory_instance_id is not None
            and issuance.inventory_instance_id != instance_id
        ):
            raise HTTPException(
                status_code=400,
                detail="Issuance does not match the selected inventory instance",
            )
        return issuance

    if not is_component_inventory(inventory.inventory_type):
        # Pick instance that would be consumed to check reservation
        check_instance_id = instance_id
        if check_instance_id is None:
            first = session.exec(
                select(InventoryInstance)
                .where(InventoryInstance.inventory_id == inventory.id)
                .order_by(InventoryInstance.id)
            ).first()
            check_instance_id = first.id if first else None
        if check_instance_id is not None:
            open_row = open_issuance_for_instance(session, check_instance_id)
            if open_row:
                # Auto-match open issuance for this serial
                return open_row
        return None

    # Components: allow consume of unreserved qty only when no issuance_id
    avail = available_quantity(session, inventory)
    if avail < 1:
        if reserved_quantity(session, inventory.id) > 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    "All remaining stock is reserved/issued. Provide issuance_id to install, "
                    "or return an issuance first."
                ),
            )
        raise HTTPException(status_code=400, detail="Inventory item is out of stock")
    return None


def mark_issuance_installed(
    session: Session,
    issuance: InventoryIssuance,
    *,
    installed_by_id: int,
    installed_entity_type: Optional[str] = None,
    installed_entity_id: Optional[int] = None,
) -> InventoryIssuance:
    issuance.status = IssuanceStatus.INSTALLED.value
    issuance.installed_at = datetime.now(timezone.utc)
    issuance.installed_by_id = installed_by_id
    if installed_entity_type:
        issuance.installed_entity_type = installed_entity_type.strip().lower()
    if installed_entity_id is not None:
        issuance.installed_entity_id = installed_entity_id
    # Instance will be deleted on consume — clear FK, keep serial snapshot
    issuance.inventory_instance_id = None
    session.add(issuance)
    session.flush()
    return issuance


def link_issuance_installed_entity(
    session: Session,
    issuance: InventoryIssuance,
    *,
    installed_entity_type: str,
    installed_entity_id: int,
) -> InventoryIssuance:
    if issuance.status != IssuanceStatus.INSTALLED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Issuance must be installed to link entity (status: {issuance.status})",
        )
    issuance.installed_entity_type = installed_entity_type.strip().lower()
    issuance.installed_entity_id = installed_entity_id
    session.add(issuance)
    session.flush()
    return issuance


def consume_with_issuance(
    session: Session,
    inventory: Inventory,
    *,
    instance_id: Optional[int] = None,
    issuance_id: Optional[int] = None,
    installed_by_id: int,
    installed_entity_type: Optional[str] = None,
    installed_entity_id: Optional[int] = None,
) -> Tuple[Optional[InventoryInstance], Optional[InventoryIssuance]]:
    issuance = resolve_issuance_for_consume(
        session,
        inventory,
        issuance_id=issuance_id,
        instance_id=instance_id,
    )

    consume_instance_id = instance_id
    if issuance and issuance.inventory_instance_id and consume_instance_id is None:
        consume_instance_id = issuance.inventory_instance_id

    # Clear instance FK before consume deletes the row (SET NULL alone is late for snapshotting).
    if issuance and issuance.inventory_instance_id:
        if not issuance.serial_number:
            inst = session.get(InventoryInstance, issuance.inventory_instance_id)
            if inst and inst.serial_number:
                issuance.serial_number = inst.serial_number
        issuance.inventory_instance_id = None
        session.add(issuance)
        session.flush()

    # For component issuances with qty > 1, decrease by issuance quantity
    if issuance and is_component_inventory(inventory.inventory_type):
        qty = issuance.quantity or 1
        if (inventory.quantity or 0) < qty:
            raise HTTPException(status_code=400, detail="Inventory item is out of stock")
        consumed = None
        for _ in range(qty):
            consume_inventory_unit(session, inventory, instance_id=None, allow_reserved=True)
        mark_issuance_installed(
            session,
            issuance,
            installed_by_id=installed_by_id,
            installed_entity_type=installed_entity_type,
            installed_entity_id=installed_entity_id,
        )
        return consumed, issuance

    consumed = consume_inventory_unit(
        session,
        inventory,
        instance_id=consume_instance_id,
        allow_reserved=issuance is not None,
    )
    if issuance:
        serial = None
        if consumed is not None:
            serial = getattr(consumed, "serial_number", None)
        if serial and not issuance.serial_number:
            issuance.serial_number = serial
        mark_issuance_installed(
            session,
            issuance,
            installed_by_id=installed_by_id,
            installed_entity_type=installed_entity_type,
            installed_entity_id=installed_entity_id,
        )
    return consumed, issuance


def find_issuance_for_installed_entity(
    session: Session,
    entity_type: str,
    entity_id: int,
) -> Optional[InventoryIssuance]:
    normalized = entity_type.strip().lower()
    return session.exec(
        select(InventoryIssuance)
        .where(
            InventoryIssuance.status == IssuanceStatus.INSTALLED.value,
            InventoryIssuance.installed_entity_type == normalized,
            InventoryIssuance.installed_entity_id == entity_id,
        )
        .order_by(col(InventoryIssuance.installed_at).desc())
    ).first()


def _ensure_inventory_group(
    session: Session,
    *,
    name: str,
    inventory_type: str,
    part_number: str,
    configuration_item: Optional[str] = None,
) -> Inventory:
    inventory = find_inventory_group(
        session,
        name=name,
        inventory_type=inventory_type,
        part_number=part_number,
    )
    if inventory:
        return inventory
    inventory = Inventory(
        name=name,
        inventory_type=inventory_type,
        part_number=part_number,
        quantity=0,
        configuration_item=configuration_item or part_number,
        description=f"Restored from hierarchy ({inventory_type})",
    )
    session.add(inventory)
    session.flush()
    return inventory


def _restore_entity_as_stock(
    session: Session,
    *,
    entity_type: str,
    entity_row,
) -> Tuple[Inventory, Optional[InventoryInstance]]:
    part_number = getattr(entity_row, "part_number", None) or getattr(
        entity_row, "original_part_number", None
    )
    serial_number = getattr(entity_row, "serial_number", None) or getattr(
        entity_row, "original_serial_number", None
    )
    name = getattr(entity_row, "name", None) or part_number or f"{entity_type}-{entity_row.id}"
    if not part_number:
        raise HTTPException(
            status_code=400,
            detail=f"{entity_type} #{entity_row.id} has no part number; cannot restore",
        )
    inventory = _ensure_inventory_group(
        session,
        name=name,
        inventory_type=entity_type,
        part_number=part_number,
        configuration_item=getattr(entity_row, "configuration_item", None),
    )
    restored: Optional[InventoryInstance] = None
    if is_component_inventory(inventory.inventory_type):
        restore_inventory_unit(session, inventory, serial_number=serial_number)
    else:
        restored = restore_inventory_unit(session, inventory, serial_number=serial_number)
        if restored is not None:
            restored.original_part_number = part_number
            restored.original_serial_number = serial_number
            restored.configuration_item = (
                getattr(entity_row, "configuration_item", None) or part_number
            )
            restored.installation_date = None
            restored.installed_by_id = None
            session.add(restored)
            sync_inventory_quantity(session, inventory)
    return inventory, restored


def revert_entity_to_inventory(
    session: Session,
    *,
    entity_type: str,
    entity_id: int,
    closed_by: User,
    notes: Optional[str] = None,
) -> Tuple[Inventory, Optional[InventoryInstance], Optional[InventoryIssuance]]:
    """Cascade soft-remove install tree; restore assembly; re-issue to installer."""
    from app.models.helpers import _collect_descendants

    normalized = entity_type.strip().lower()
    try:
        et = EntityType(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unsupported entity type: {entity_type}") from exc

    entry = _ENTITY_MODEL_MAP.get(et)
    if not entry:
        raise HTTPException(status_code=400, detail=f"Unsupported entity type: {entity_type}")

    model_cls = entry[0]
    row = session.get(model_cls, entity_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"{normalized} {entity_id} not found")

    if getattr(row, "is_current_install", True) is False:
        raise HTTPException(status_code=400, detail="Entity is not a current install")

    prior = find_issuance_for_installed_entity(session, normalized, entity_id)
    issued_to_id = closed_by.id
    if prior:
        issued_to_id = prior.issued_to_user_id or closed_by.id
        allowed_ids = {
            prior.issued_to_user_id,
            prior.installed_by_id,
            getattr(row, "installed_by_id", None),
        }
        if closed_by.id not in allowed_ids:
            raise HTTPException(
                status_code=403,
                detail="You can only revert inventory that was issued to you or installed by you",
            )
    else:
        installed_by = getattr(row, "installed_by_id", None)
        if installed_by is not None and installed_by != closed_by.id:
            raise HTTPException(
                status_code=403,
                detail="You can only revert installs performed by you",
            )

    # Collect descendants BEFORE soft-removing parent (FK walk uses current installs)
    descendants = _collect_descendants(session, normalized, entity_id)

    # Soft-remove root + clear install metadata
    row.is_current_install = False
    row.replaced_at = datetime.now(timezone.utc)
    row.installation_date = None
    row.installed_by_id = None
    session.add(row)

    # Soft-remove descendants (deepest first so UI trees clear cleanly)
    for desc in reversed(descendants):
        d_type = (desc.entity_type if isinstance(desc.entity_type, str) else str(desc.entity_type)).lower()
        try:
            d_et = EntityType(d_type)
        except ValueError:
            continue
        d_entry = _ENTITY_MODEL_MAP.get(d_et)
        if not d_entry:
            continue
        child_row = session.get(d_entry[0], desc.entity_id)
        if not child_row:
            continue
        child_row.is_current_install = False
        child_row.replaced_at = datetime.now(timezone.utc)
        child_row.installation_date = None
        child_row.installed_by_id = None
        session.add(child_row)

    session.flush()

    # Restore parent stock
    inventory, restored = _restore_entity_as_stock(
        session, entity_type=normalized, entity_row=row
    )
    parent_serial = (
        (restored.serial_number if restored else None)
        or getattr(row, "serial_number", None)
        or getattr(row, "original_serial_number", None)
    )

    # Restore each descendant as composed child under parent
    for desc in descendants:
        d_type = (desc.entity_type if isinstance(desc.entity_type, str) else str(desc.entity_type)).lower()
        try:
            d_et = EntityType(d_type)
        except ValueError:
            continue
        d_entry = _ENTITY_MODEL_MAP.get(d_et)
        if not d_entry:
            continue
        child_row = session.get(d_entry[0], desc.entity_id)
        if not child_row:
            continue
        child_part = getattr(child_row, "part_number", None) or getattr(
            child_row, "original_part_number", None
        )
        if not child_part:
            continue
        try:
            child_inv, child_inst = _restore_entity_as_stock(
                session, entity_type=d_type, entity_row=child_row
            )
        except HTTPException:
            continue
        child_serial = (
            (child_inst.serial_number if child_inst else None)
            or getattr(child_row, "serial_number", None)
            or getattr(child_row, "original_serial_number", None)
        )
        # Link as composed child (already restored into stock; mark consumed into parent)
        # First remove the free instance/qty we just restored so composition matches warehouse rules:
        # create link with stock_consumed and consume the restored unit.
        if is_component_inventory(child_inv.inventory_type):
            if (child_inv.quantity or 0) > 0:
                child_inv.quantity = max(0, (child_inv.quantity or 0) - 1)
                session.add(child_inv)
            child_instance_id = None
        else:
            if child_inst and child_inst.id:
                child_instance_id = child_inst.id
                # Delete free instance — composition holds the serial snapshot
                session.delete(child_inst)
                session.flush()
                sync_inventory_quantity(session, child_inv)
            else:
                child_instance_id = None

        link = InventoryChildLink(
            parent_inventory_id=inventory.id,
            parent_instance_id=restored.id if restored else None,
            parent_instance_serial=parent_serial,
            child_category_name=getattr(child_row, "name", None) or d_type,
            child_inventory_id=child_inv.id,
            child_instance_id=None,
            child_instance_serial=child_serial,
            stock_consumed=True,
        )
        session.add(link)
        _ = child_instance_id

    session.flush()

    # Close prior installed issuance as reverted (history)
    if prior:
        prior.status = IssuanceStatus.REVERTED.value
        prior.closed_at = datetime.now(timezone.utc)
        prior.closed_by_id = closed_by.id
        if notes:
            prior.notes = ((prior.notes or "") + f"\nRevert: {notes}").strip()
        session.add(prior)

    # New open issuance so the assembly appears on the installer's list
    new_issuance = InventoryIssuance(
        inventory_id=inventory.id,
        inventory_instance_id=restored.id if restored else None,
        quantity=1,
        issued_to_user_id=issued_to_id,
        issued_by_user_id=closed_by.id,
        issued_at=datetime.now(timezone.utc),
        status=OPEN_STATUS,
        part_number=inventory.part_number,
        serial_number=parent_serial,
        inventory_name=inventory.name,
        inventory_type=inventory.inventory_type,
        notes=notes or "Reopened after revert from hierarchy",
    )
    session.add(new_issuance)
    session.flush()

    return inventory, restored, new_issuance


def list_issuances(
    session: Session,
    *,
    status: Optional[str] = None,
    issued_to_user_id: Optional[int] = None,
    issued_by_user_id: Optional[int] = None,
    inventory_id: Optional[int] = None,
    part_number: Optional[str] = None,
    serial_number: Optional[str] = None,
    search: Optional[str] = None,
) -> List[InventoryIssuance]:
    stmt = select(InventoryIssuance)
    if status:
        stmt = stmt.where(InventoryIssuance.status == status.strip().lower())
    if issued_to_user_id is not None:
        stmt = stmt.where(InventoryIssuance.issued_to_user_id == issued_to_user_id)
    if issued_by_user_id is not None:
        stmt = stmt.where(InventoryIssuance.issued_by_user_id == issued_by_user_id)
    if inventory_id is not None:
        stmt = stmt.where(InventoryIssuance.inventory_id == inventory_id)
    if part_number:
        stmt = stmt.where(
            func.lower(func.coalesce(InventoryIssuance.part_number, ""))
            == part_number.strip().lower()
        )
    if serial_number:
        stmt = stmt.where(
            func.lower(func.coalesce(InventoryIssuance.serial_number, ""))
            == serial_number.strip().lower()
        )
    if search:
        q = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            func.lower(func.coalesce(InventoryIssuance.inventory_name, "")).like(q)
            | func.lower(func.coalesce(InventoryIssuance.part_number, "")).like(q)
            | func.lower(func.coalesce(InventoryIssuance.serial_number, "")).like(q)
        )
    return list(session.exec(stmt.order_by(col(InventoryIssuance.issued_at).desc())).all())
