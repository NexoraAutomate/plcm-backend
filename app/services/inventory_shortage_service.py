"""
Spec 05 — shortage rows, in-app notify, and FCFS auto-reserve on receipt.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, col, select

from app.domain.workflow_roles import WORKFLOW_ROLE_DB_NAMES, WorkflowRole
from app.domain.workflow_status import ItemStatus
from app.models.base import ShortageNoticeType, ShortageStatus
from app.models.tables import (
    Component,
    Flight,
    Inventory,
    InventoryInstance,
    InventoryReservation,
    InventoryShortage,
    InventoryShortageNotice,
    Module,
    Project,
    Role,
    Sdls,
    Subsystem,
    System,
    User,
    UserRole,
    Unit,
)
from app.services.inventory_reservation_service import (
    InventoryReservationError,
    get_item_status_id,
    is_instance_free_for_project_reserve,
    item_status_name,
    reservation_to_dict,
    reserve_inventory,
)
from app.services.inventory_service import (
    create_inventory_instance,
    find_inventory_catalog_group,
    is_component_inventory,
    normalize_part_number,
)

from app.domain.workflow_audit import WorkflowAuditAction
from app.services.workflow_audit_service import write_workflow_audit

AUTO_RESERVE_NOTE = "Auto-reserved: shortage fulfillment"
ACTIVE_SHORTAGE_STATUSES = (ShortageStatus.OPEN.value, ShortageStatus.PARTIAL.value)
IM_NOTIFY_ROLE_NAMES = frozenset(
    {
        WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM],
        WORKFLOW_ROLE_DB_NAMES[WorkflowRole.ADMIN],
        "SubAdmin",
    }
)


class InventoryShortageError(ValueError):
    pass


class InventoryShortageCreated(InventoryReservationError):
    """Stock unavailable — a shortage row was persisted."""

    def __init__(self, shortage: InventoryShortage, message: str | None = None):
        super().__init__(message or "Stock not available — shortage recorded")
        self.shortage = shortage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def shortage_to_dict(shortage: InventoryShortage) -> dict[str, Any]:
    return {
        "id": shortage.id,
        "project_id": shortage.project_id,
        "flight_id": shortage.flight_id,
        "sdls_id": shortage.sdls_id,
        "target_entity_type": shortage.target_entity_type,
        "target_entity_id": shortage.target_entity_id,
        "inventory_id": shortage.inventory_id,
        "part_number": shortage.part_number,
        "qty_short": shortage.qty_short,
        "qty_original": shortage.qty_original,
        "lru_name": shortage.lru_name,
        "requested_by_user_id": shortage.requested_by_user_id,
        "requested_at": shortage.requested_at,
        "status": shortage.status,
        "last_notified_at": shortage.last_notified_at,
        "fulfilled_reservation_id": shortage.fulfilled_reservation_id,
        "cancelled_at": shortage.cancelled_at,
        "cancelled_by_user_id": shortage.cancelled_by_user_id,
        "notes": shortage.notes,
        "project_name": shortage.project.name if shortage.project else None,
        "flight_code": shortage.flight.code if shortage.flight else None,
        "flight_name": shortage.flight.name if shortage.flight else None,
        "sdls_code": shortage.sdls.code if shortage.sdls else None,
        "sdls_name": shortage.sdls.name if shortage.sdls else None,
        "requested_by_name": (
            (shortage.requested_by.full_name or shortage.requested_by.username)
            if shortage.requested_by
            else None
        ),
    }


def notice_to_dict(notice: InventoryShortageNotice) -> dict[str, Any]:
    return {
        "id": notice.id,
        "user_id": notice.user_id,
        "shortage_id": notice.shortage_id,
        "notice_type": notice.notice_type,
        "part_number": notice.part_number,
        "qty": notice.qty,
        "flight_code": notice.flight_code,
        "flight_name": notice.flight_name,
        "sdls_code": notice.sdls_code,
        "sdls_name": notice.sdls_name,
        "lru_name": notice.lru_name,
        "project_id": notice.project_id,
        "project_name": notice.project_name,
        "message": notice.message,
        "created_at": notice.created_at,
        "read_at": notice.read_at,
    }


def fulfillment_to_dict(
    shortage: InventoryShortage,
    reservation: Optional[InventoryReservation],
    *,
    qty_applied: int,
) -> dict[str, Any]:
    return {
        "shortage_id": shortage.id,
        "reservation_id": reservation.id if reservation else None,
        "project_id": shortage.project_id,
        "project_name": shortage.project.name if shortage.project else None,
        "part_number": shortage.part_number,
        "qty_applied": qty_applied,
        "shortage_status": shortage.status,
        "serial_number": reservation.serial_number if reservation else None,
        "flight_name": shortage.flight.name if shortage.flight else None,
        "sdls_name": shortage.sdls.name if shortage.sdls else None,
        "lru_name": shortage.lru_name,
    }


def _users_with_role_names(session: Session, names: set[str]) -> list[User]:
    wanted = {n.lower() for n in names}
    roles = session.exec(select(Role)).all()
    role_ids = [r.id for r in roles if r.id and (r.name or "").lower() in wanted]
    if not role_ids:
        return []
    links = session.exec(
        select(UserRole).where(col(UserRole.role_id).in_(role_ids))
    ).all()
    user_ids = {int(link.user_id) for link in links if link.user_id is not None}
    users: list[User] = []
    for uid in user_ids:
        user = session.get(User, uid)
        if user and user.is_active:
            users.append(user)
    return users


def _notify_recipients(session: Session, shortage: InventoryShortage) -> list[User]:
    recipients: dict[int, User] = {}
    hm_id = shortage.requested_by_user_id
    project = shortage.project or session.get(Project, shortage.project_id)
    if project and project.assigned_hm_id:
        hm_id = int(project.assigned_hm_id)
    for uid in {shortage.requested_by_user_id, hm_id}:
        user = session.get(User, uid)
        if user and user.id is not None:
            recipients[int(user.id)] = user
    for user in _users_with_role_names(session, set(IM_NOTIFY_ROLE_NAMES)):
        if user.id is not None:
            recipients[int(user.id)] = user
    return list(recipients.values())


def _build_notice_message(
    *,
    notice_type: str,
    part_number: Optional[str],
    qty: int,
    flight_label: str,
    sdls_label: str,
    lru_name: Optional[str],
) -> str:
    pn = part_number or "—"
    lru = lru_name or "item"
    if notice_type == ShortageNoticeType.CREATED.value:
        action = "Shortage"
    elif notice_type == ShortageNoticeType.PARTIAL.value:
        action = "Shortage partially fulfilled"
    else:
        action = "Shortage fulfilled — auto-reserved"
    return (
        f"{action}: PN {pn}, Qty {qty}, Flight {flight_label}, "
        f"SDLS {sdls_label}, LRU {lru}"
    )


def notify_shortage(
    session: Session,
    shortage: InventoryShortage,
    *,
    notice_type: str,
    qty: Optional[int] = None,
) -> list[InventoryShortageNotice]:
    flight = shortage.flight or session.get(Flight, shortage.flight_id)
    sdls = shortage.sdls or session.get(Sdls, shortage.sdls_id)
    project = shortage.project or session.get(Project, shortage.project_id)
    flight_code = flight.code if flight else None
    flight_name = flight.name if flight else None
    sdls_code = sdls.code if sdls else None
    sdls_name = sdls.name if sdls else None
    flight_label = flight_code or flight_name or f"#{shortage.flight_id}"
    sdls_label = sdls_code or sdls_name or f"#{shortage.sdls_id}"
    qty_val = int(qty if qty is not None else shortage.qty_short)
    message = _build_notice_message(
        notice_type=notice_type,
        part_number=shortage.part_number,
        qty=qty_val,
        flight_label=str(flight_label),
        sdls_label=str(sdls_label),
        lru_name=shortage.lru_name,
    )
    rows: list[InventoryShortageNotice] = []
    now = _now()
    for user in _notify_recipients(session, shortage):
        if user.id is None:
            continue
        row = InventoryShortageNotice(
            user_id=int(user.id),
            shortage_id=int(shortage.id),
            notice_type=notice_type,
            part_number=shortage.part_number,
            qty=qty_val,
            flight_code=flight_code,
            flight_name=flight_name,
            sdls_code=sdls_code,
            sdls_name=sdls_name,
            lru_name=shortage.lru_name,
            project_id=shortage.project_id,
            project_name=project.name if project else None,
            message=message,
            created_at=now,
        )
        session.add(row)
        rows.append(row)
    shortage.last_notified_at = now
    shortage.updated_at = now
    session.add(shortage)
    return rows


def find_open_shortage_for_node(
    session: Session,
    *,
    project_id: int,
    target_entity_type: str,
    target_entity_id: int,
) -> Optional[InventoryShortage]:
    return session.exec(
        select(InventoryShortage).where(
            InventoryShortage.project_id == project_id,
            InventoryShortage.target_entity_type == target_entity_type,
            InventoryShortage.target_entity_id == target_entity_id,
            col(InventoryShortage.status).in_(list(ACTIVE_SHORTAGE_STATUSES)),
        )
    ).first()


def record_shortage_for_reserve(
    session: Session,
    *,
    project: Project,
    flight: Flight,
    sdls: Sdls,
    entity: Any,
    entity_type: str,
    entity_id: int,
    actor: User,
    inventory: Optional[Inventory] = None,
    qty_short: int = 1,
    commit: bool = True,
) -> InventoryShortage:
    existing = find_open_shortage_for_node(
        session,
        project_id=int(project.id),
        target_entity_type=entity_type,
        target_entity_id=entity_id,
    )
    if existing:
        return existing

    part_number = None
    inventory_id = None
    if inventory is not None:
        part_number = inventory.part_number
        inventory_id = inventory.id
    if not part_number:
        part_number = getattr(entity, "part_number", None)

    now = _now()
    shortage = InventoryShortage(
        project_id=int(project.id),
        flight_id=int(flight.id),
        sdls_id=int(sdls.id),
        target_entity_type=entity_type,
        target_entity_id=entity_id,
        inventory_id=int(inventory_id) if inventory_id is not None else None,
        part_number=part_number,
        qty_short=max(1, int(qty_short)),
        qty_original=max(1, int(qty_short)),
        lru_name=getattr(entity, "name", None) or entity_type,
        requested_by_user_id=int(actor.id),
        requested_at=now,
        status=ShortageStatus.OPEN.value,
        created_at=now,
        updated_at=now,
    )
    session.add(shortage)
    session.flush()
    notify_shortage(
        session,
        shortage,
        notice_type=ShortageNoticeType.CREATED.value,
        qty=shortage.qty_short,
    )
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.SHORTAGE_CREATED,
        entity_type="inventory_shortage",
        entity_id=int(shortage.id),
        actor=actor,
        project_id=int(project.id),
        new_value={
            "part_number": shortage.part_number,
            "qty_short": shortage.qty_short,
            "status": shortage.status,
        },
    )
    if commit:
        session.commit()
        session.refresh(shortage)
    else:
        session.flush()
    return shortage


def ensure_shortages_for_project(
    session: Session,
    project: Project,
    *,
    actor: User,
) -> int:
    """Create active shortage rows for missing TURNKEY stock after generation."""
    from app.services.inventory_reservation_service import (
        _resolve_flight_sdls_for_entity,
        build_reservation_plan,
    )

    entity_models = {
        "system": System,
        "subsystem": Subsystem,
        "module": Module,
        "unit": Unit,
        "component": Component,
    }
    plan = build_reservation_plan(session, int(project.id))
    created = 0
    for row in plan.get("items", []):
        if row.get("status") != "short":
            continue
        entity_type = str(row["target_entity_type"]).lower()
        model = entity_models.get(entity_type)
        if model is None:
            continue
        entity = session.get(model, int(row["target_entity_id"]))
        flight = (
            session.get(Flight, int(row["flight_id"]))
            if row.get("flight_id")
            else None
        )
        sdls = (
            session.get(Sdls, int(row["sdls_id"]))
            if row.get("sdls_id")
            else None
        )
        if entity is not None and (flight is None or sdls is None):
            try:
                flight, sdls, _ = _resolve_flight_sdls_for_entity(
                    session,
                    entity_type,
                    entity,
                )
            except InventoryReservationError:
                flight = None
                sdls = None
        if entity is None or flight is None or sdls is None:
            continue
        if find_open_shortage_for_node(
            session,
            project_id=int(project.id),
            target_entity_type=entity_type,
            target_entity_id=int(row["target_entity_id"]),
        ):
            continue
        inventory = (
            session.get(Inventory, int(row["inventory_id"]))
            if row.get("inventory_id")
            else None
        )
        record_shortage_for_reserve(
            session,
            project=project,
            flight=flight,
            sdls=sdls,
            entity=entity,
            entity_type=entity_type,
            entity_id=int(row["target_entity_id"]),
            actor=actor,
            inventory=inventory,
            commit=False,
        )
        created += 1
    return created


def receive_shortage_stock(
    session: Session,
    shortage_id: int,
    *,
    actor: User,
    quantity: int,
    part_number: Optional[str] = None,
    serial_numbers: Optional[list[str]] = None,
    location: Optional[str] = None,
) -> tuple[Inventory, list[dict[str, Any]]]:
    """Receive stock from the shortage list and immediately run FCFS fulfillment."""
    shortage = session.get(InventoryShortage, shortage_id)
    if shortage is None:
        raise InventoryShortageError("Shortage not found")
    if shortage.status not in ACTIVE_SHORTAGE_STATUSES:
        raise InventoryShortageError("Shortage is not open")
    if quantity < 1:
        raise InventoryShortageError("Quantity must be at least 1")

    requested_type = (shortage.target_entity_type or "").strip().lower()
    requested_name = (shortage.lru_name or "").strip()
    if not requested_name:
        raise InventoryShortageError("Shortage has no inventory item name")
    if requested_type not in {"system", "subsystem", "module", "unit", "component"}:
        raise InventoryShortageError("Shortage has an unsupported inventory type")

    inventory = (
        session.get(Inventory, shortage.inventory_id)
        if shortage.inventory_id is not None
        else None
    )
    resolved_part_number = (part_number or shortage.part_number or "").strip() or None
    serialized = not is_component_inventory(requested_type)
    serials = [
        str(serial).strip()
        for serial in (serial_numbers or [])
        if str(serial).strip()
    ]
    if serialized:
        if quantity != 1:
            raise InventoryShortageError(
                "Serialized shortages accept one unit at a time"
            )
        if not resolved_part_number and not (inventory and inventory.part_number):
            raise InventoryShortageError("Part number is required for serialized stock")
        if len(serials) != 1:
            raise InventoryShortageError("One serial number is required")
        if not (location or "").strip():
            raise InventoryShortageError("Location is required for serialized stock")

    if inventory is None:
        inventory = find_inventory_catalog_group(
            session,
            name=requested_name,
            inventory_type=requested_type,
            part_number=resolved_part_number,
        )
    if inventory is None:
        inventory = Inventory(
            name=requested_name,
            inventory_type=requested_type,
            quantity=0,
            part_number=resolved_part_number,
            configuration_item=resolved_part_number or requested_name,
            holder_user_id=int(actor.id),
        )
        session.add(inventory)
        session.flush()
    elif inventory.inventory_type != requested_type:
        raise InventoryShortageError("Inventory type does not match shortage")

    fulfillments: list[dict[str, Any]] = []
    if not serialized:
        inventory.quantity = int(inventory.quantity or 0) + quantity
        inventory.updated_at = _now()
        if resolved_part_number and not inventory.part_number:
            inventory.part_number = resolved_part_number
        session.add(inventory)
        shortage.inventory_id = inventory.id
        if not shortage.part_number and inventory.part_number:
            shortage.part_number = inventory.part_number
        session.add(shortage)
        session.commit()
        session.refresh(inventory)
        fulfillments = match_and_auto_reserve_on_receipt(
            session, inventory, actor=actor, qty=quantity
        )
    else:
        if not resolved_part_number and not inventory.part_number:
            raise InventoryShortageError("Part number is required for serialized stock")
        if not inventory.part_number:
            inventory.part_number = resolved_part_number
        shortage.inventory_id = inventory.id
        if not shortage.part_number and inventory.part_number:
            shortage.part_number = inventory.part_number
        session.add_all(
            [
                inventory,
                shortage,
            ]
        )
        instance = create_inventory_instance(
            session,
            inventory,
            serial_number=serials[0],
            original_serial_number=serials[0],
            location=location.strip(),
            holder_user_id=int(actor.id),
        )
        session.commit()
        session.refresh(inventory)
        fulfillments = match_and_auto_reserve_on_receipt(
            session, inventory, actor=actor, instance=instance
        )

    session.refresh(inventory)
    return inventory, fulfillments


def list_shortages(
    session: Session,
    *,
    project_id: Optional[int] = None,
    statuses: Optional[list[str]] = None,
    requested_by_user_id: Optional[int] = None,
    assigned_hm_id: Optional[int] = None,
) -> list[InventoryShortage]:
    query = select(InventoryShortage)
    if project_id is not None:
        query = query.where(InventoryShortage.project_id == project_id)
    if statuses:
        query = query.where(col(InventoryShortage.status).in_(statuses))
    if requested_by_user_id is not None:
        query = query.where(
            InventoryShortage.requested_by_user_id == requested_by_user_id
        )
    rows = list(
        session.exec(
            query.order_by(
                InventoryShortage.requested_at.asc(), InventoryShortage.id.asc()
            )
        ).all()
    )
    if assigned_hm_id is not None and requested_by_user_id is None:
        filtered: list[InventoryShortage] = []
        for row in rows:
            project = row.project or session.get(Project, row.project_id)
            if row.requested_by_user_id == assigned_hm_id:
                filtered.append(row)
            elif project and project.assigned_hm_id == assigned_hm_id:
                filtered.append(row)
        return filtered
    return rows


def cancel_shortage(
    session: Session,
    shortage_id: int,
    *,
    actor: User,
    project_id: Optional[int] = None,
    commit: bool = True,
) -> InventoryShortage:
    shortage = session.get(InventoryShortage, shortage_id)
    if not shortage:
        raise InventoryShortageError("Shortage not found")
    if project_id is not None and shortage.project_id != project_id:
        raise InventoryShortageError("Shortage not found")
    if shortage.status not in ACTIVE_SHORTAGE_STATUSES:
        raise InventoryShortageError("Shortage is not open")
    shortage.status = ShortageStatus.CANCELLED.value
    shortage.cancelled_at = _now()
    shortage.cancelled_by_user_id = int(actor.id)
    shortage.updated_at = _now()
    session.add(shortage)
    if commit:
        session.commit()
        session.refresh(shortage)
    else:
        session.flush()
    return shortage


def list_shortage_notices(
    session: Session,
    *,
    user_id: int,
    unread_only: bool = False,
) -> list[InventoryShortageNotice]:
    query = select(InventoryShortageNotice).where(
        InventoryShortageNotice.user_id == user_id
    )
    if unread_only:
        query = query.where(InventoryShortageNotice.read_at.is_(None))
    query = query.order_by(
        InventoryShortageNotice.created_at.desc(), InventoryShortageNotice.id.desc()
    )
    return list(session.exec(query).all())


def mark_shortage_notice_read(
    session: Session, notice: InventoryShortageNotice
) -> InventoryShortageNotice:
    if notice.read_at is None:
        notice.read_at = _now()
        session.add(notice)
    return notice


def mark_all_shortage_notices_read(session: Session, user_id: int) -> int:
    rows = list_shortage_notices(session, user_id=user_id, unread_only=True)
    now = _now()
    for row in rows:
        row.read_at = now
        session.add(row)
    return len(rows)


def _shortage_matches_inventory(
    shortage: InventoryShortage, inventory: Inventory
) -> bool:
    sn = normalize_part_number(shortage.part_number)
    pn = normalize_part_number(inventory.part_number)
    if sn and pn:
        return sn == pn
    if shortage.inventory_id and inventory.id:
        return int(shortage.inventory_id) == int(inventory.id)
    lru = (shortage.lru_name or "").strip().lower()
    name = (inventory.name or "").strip().lower()
    return bool(lru) and lru == name and shortage.target_entity_type == inventory.inventory_type


def _open_shortages_for_inventory(
    session: Session, inventory: Inventory
) -> list[InventoryShortage]:
    rows = session.exec(
        select(InventoryShortage)
        .where(
            col(InventoryShortage.status).in_(list(ACTIVE_SHORTAGE_STATUSES)),
            InventoryShortage.qty_short > 0,
        )
        .order_by(InventoryShortage.requested_at.asc(), InventoryShortage.id.asc())
    ).all()
    return [row for row in rows if _shortage_matches_inventory(row, inventory)]


def _ensure_instance_available(
    session: Session, instance: InventoryInstance
) -> None:
    current = item_status_name(session, instance.status_id)
    if current is None:
        instance.status_id = get_item_status_id(session, ItemStatus.AVAILABLE.value)
        instance.updated_at = _now()
        session.add(instance)
        session.flush()


def match_and_auto_reserve_on_receipt(
    session: Session,
    inventory: Inventory,
    *,
    actor: User,
    instance: Optional[InventoryInstance] = None,
    qty: int = 1,
) -> list[dict[str, Any]]:
    """Apply newly received stock to waiting shortages in FCFS order."""
    if instance is not None:
        _ensure_instance_available(session, instance)
        if not is_instance_free_for_project_reserve(session, instance):
            return []
        remaining = 1
    else:
        remaining = max(0, int(qty))
    if remaining <= 0:
        return []

    fulfillments: list[dict[str, Any]] = []
    skipped: set[int] = set()

    while remaining > 0:
        waiting = [
            s
            for s in _open_shortages_for_inventory(session, inventory)
            if s.id not in skipped
        ]
        if not waiting:
            break
        shortage = waiting[0]
        skipped.add(int(shortage.id))

        hm = session.get(User, shortage.requested_by_user_id) or actor
        apply_qty = 1 if instance is not None else min(remaining, int(shortage.qty_short))
        payload: dict[str, Any] = {
            "target_entity_type": shortage.target_entity_type,
            "target_entity_id": shortage.target_entity_id,
            "inventory_id": inventory.id,
            "notes": f"{AUTO_RESERVE_NOTE} (shortage_id={shortage.id})",
        }
        if instance is not None and instance.id is not None:
            payload["inventory_instance_id"] = int(instance.id)
        try:
            reservation = reserve_inventory(
                session,
                int(shortage.project_id),
                payload,
                actor=hm,
                create_shortage_if_unavailable=False,
            )
        except InventoryReservationError:
            continue

        shortage.qty_short = max(0, int(shortage.qty_short) - apply_qty)
        shortage.fulfilled_reservation_id = reservation.id
        shortage.updated_at = _now()
        if shortage.qty_short <= 0:
            shortage.status = ShortageStatus.FULFILLED.value
            shortage.qty_short = 0
            notice_type = ShortageNoticeType.FULFILLED.value
        else:
            shortage.status = ShortageStatus.PARTIAL.value
            notice_type = ShortageNoticeType.PARTIAL.value
        session.add(shortage)
        notify_shortage(
            session,
            shortage,
            notice_type=notice_type,
            qty=apply_qty,
        )
        write_workflow_audit(
            session,
            action=(
                WorkflowAuditAction.SHORTAGE_FULFILLED
                if shortage.status == ShortageStatus.FULFILLED.value
                else WorkflowAuditAction.SHORTAGE_PARTIAL
            ),
            entity_type="inventory_shortage",
            entity_id=int(shortage.id),
            actor=actor,
            project_id=int(shortage.project_id),
            new_value={
                "qty_applied": apply_qty,
                "qty_short": shortage.qty_short,
                "status": shortage.status,
                "reservation_id": reservation.id,
            },
            remarks=AUTO_RESERVE_NOTE,
        )
        write_workflow_audit(
            session,
            action=WorkflowAuditAction.AUTO_RESERVE,
            entity_type="inventory_reservation",
            entity_id=int(reservation.id),
            actor=actor,
            project_id=int(shortage.project_id),
            new_value={"shortage_id": shortage.id, "qty_applied": apply_qty},
            remarks=AUTO_RESERVE_NOTE,
        )
        session.commit()
        session.refresh(shortage)
        session.refresh(reservation)
        fulfillments.append(
            fulfillment_to_dict(shortage, reservation, qty_applied=apply_qty)
        )
        remaining -= apply_qty
        if instance is not None:
            break

    return fulfillments
