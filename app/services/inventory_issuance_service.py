"""Inventory issuance: issue → reserve → install / return / revert."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select, func, col

from app.domain.status_transitions import assert_transition
from app.domain.workflow_status import ItemStatus
from app.models.base import (
    EntityType,
    HARD_COPY_ACKNOWLEDGMENT,
    InstallerNoticeType,
    IssuanceEventType,
    IssuanceStatus,
    SignatureType,
)
from app.models.helpers import _ENTITY_MODEL_MAP
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryIssuance,
    InventoryIssuanceEvent,
    InventoryInstallerNotice,
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
RETURN_PENDING_STATUS = IssuanceStatus.RETURN_PENDING.value
# Still reserved / visible on installer inventory list
RESERVED_STATUSES = (OPEN_STATUS, RETURN_PENDING_STATUS)


def inventory_ids_issued_to_user(session: Session, user_id: int) -> list[int]:
    """Inventory group IDs with an open or return-pending issuance to this user."""
    rows = session.exec(
        select(InventoryIssuance.inventory_id).where(
            InventoryIssuance.issued_to_user_id == user_id,
            InventoryIssuance.status.in_(RESERVED_STATUSES),
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


def _require_notes(notes: Optional[str], *, label: str = "Remarks") -> str:
    cleaned = (notes or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{label} are required")
    return cleaned


def record_issuance_event(
    session: Session,
    issuance: InventoryIssuance,
    *,
    event_type: str,
    actor: Optional[User] = None,
    notes: Optional[str] = None,
) -> InventoryIssuanceEvent:
    installer = (
        session.get(User, issuance.issued_to_user_id)
        if issuance.issued_to_user_id
        else None
    )
    event = InventoryIssuanceEvent(
        issuance_id=issuance.id,
        inventory_id=issuance.inventory_id,
        inventory_instance_id=issuance.inventory_instance_id,
        event_type=event_type,
        quantity=issuance.quantity or 1,
        actor_user_id=actor.id if actor else None,
        actor_name=_user_display_name(actor),
        installer_user_id=issuance.issued_to_user_id,
        installer_name=_user_display_name(installer),
        notes=(notes or "").strip() or None,
        part_number=issuance.part_number,
        serial_number=issuance.serial_number,
        inventory_name=issuance.inventory_name,
        inventory_type=issuance.inventory_type,
        created_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.flush()
    return event


def create_installer_notice(
    session: Session,
    *,
    user_id: int,
    notice_type: str,
    issuance: InventoryIssuance,
    message: str,
    notes: Optional[str] = None,
) -> InventoryInstallerNotice:
    notice = InventoryInstallerNotice(
        user_id=user_id,
        notice_type=notice_type,
        issuance_id=issuance.id,
        inventory_id=issuance.inventory_id,
        inventory_name=issuance.inventory_name,
        part_number=issuance.part_number,
        serial_number=issuance.serial_number,
        message=message,
        notes=(notes or "").strip() or None,
        created_at=datetime.now(timezone.utc),
    )
    session.add(notice)
    session.flush()
    return notice


def create_installer_notice_read(
    notice: InventoryInstallerNotice,
    session: Optional[Session] = None,
) -> dict:
    data = notice.model_dump()
    for key in ("created_at", "read_at"):
        if key in data:
            data[key] = _ensure_utc(data.get(key))
    user_name = None
    if session is not None and notice.user_id is not None:
        user = session.get(User, notice.user_id)
        user_name = _user_display_name(user)
    data["user_name"] = user_name
    return data


def list_installer_notices(
    session: Session,
    *,
    user_id: Optional[int] = None,
    unread_only: bool = False,
    search: Optional[str] = None,
) -> List[InventoryInstallerNotice]:
    stmt = select(InventoryInstallerNotice).order_by(
        col(InventoryInstallerNotice.created_at).desc()
    )
    if user_id is not None:
        stmt = stmt.where(InventoryInstallerNotice.user_id == user_id)
    if unread_only:
        stmt = stmt.where(InventoryInstallerNotice.read_at.is_(None))
    term = (search or "").strip()
    if term:
        like = f"%{term.lower()}%"
        stmt = stmt.where(
            func.lower(
                func.coalesce(InventoryInstallerNotice.message, "")
                + " "
                + func.coalesce(InventoryInstallerNotice.inventory_name, "")
                + " "
                + func.coalesce(InventoryInstallerNotice.part_number, "")
                + " "
                + func.coalesce(InventoryInstallerNotice.serial_number, "")
                + " "
                + func.coalesce(InventoryInstallerNotice.notes, "")
                + " "
                + func.coalesce(InventoryInstallerNotice.notice_type, "")
            ).like(like)
        )
    return list(session.exec(stmt).all())


def mark_installer_notice_read(
    session: Session,
    notice: InventoryInstallerNotice,
) -> InventoryInstallerNotice:
    if notice.read_at is None:
        notice.read_at = datetime.now(timezone.utc)
        session.add(notice)
        session.flush()
    return notice


def mark_all_installer_notices_read(
    session: Session,
    *,
    user_id: Optional[int] = None,
) -> int:
    stmt = select(InventoryInstallerNotice).where(
        InventoryInstallerNotice.read_at.is_(None)
    )
    if user_id is not None:
        stmt = stmt.where(InventoryInstallerNotice.user_id == user_id)
    rows = list(session.exec(stmt).all())
    now = datetime.now(timezone.utc)
    for row in rows:
        row.read_at = now
        session.add(row)
    session.flush()
    return len(rows)


def related_issuance_ids(session: Session, issuance: InventoryIssuance) -> list[int]:
    """Issuances that share the same physical unit (instance and/or serial)."""
    ids: set[int] = {int(issuance.id)} if issuance.id is not None else set()
    if issuance.inventory_instance_id is not None:
        rows = session.exec(
            select(InventoryIssuance.id).where(
                InventoryIssuance.inventory_instance_id == issuance.inventory_instance_id
            )
        ).all()
        ids.update(int(r) for r in rows if r is not None)
    serial = (issuance.serial_number or "").strip()
    if serial and issuance.inventory_id is not None:
        rows = session.exec(
            select(InventoryIssuance.id).where(
                InventoryIssuance.inventory_id == issuance.inventory_id,
                func.lower(func.coalesce(InventoryIssuance.serial_number, ""))
                == serial.lower(),
            )
        ).all()
        ids.update(int(r) for r in rows if r is not None)
    return sorted(ids)


def issuance_event_to_dict(event: InventoryIssuanceEvent) -> dict:
    data = event.model_dump()
    data["created_at"] = _ensure_utc(data.get("created_at"))
    return data


def list_issuance_history(
    session: Session,
    issuance: InventoryIssuance,
) -> List[dict]:
    """Full ping-pong timeline for a unit, newest last."""
    chain_ids = related_issuance_ids(session, issuance)
    events = list(
        session.exec(
            select(InventoryIssuanceEvent)
            .where(InventoryIssuanceEvent.issuance_id.in_(chain_ids))
            .order_by(col(InventoryIssuanceEvent.created_at).asc(), col(InventoryIssuanceEvent.id).asc())
        ).all()
    )
    if events:
        return [issuance_event_to_dict(e) for e in events]

    # Fallback for legacy rows created before the event ledger existed.
    synthesized: list[dict] = []
    rows = list(
        session.exec(
            select(InventoryIssuance)
            .where(InventoryIssuance.id.in_(chain_ids))
            .order_by(col(InventoryIssuance.issued_at).asc(), col(InventoryIssuance.id).asc())
        ).all()
    )
    for row in rows:
        issued_to = session.get(User, row.issued_to_user_id) if row.issued_to_user_id else None
        issued_by = session.get(User, row.issued_by_user_id) if row.issued_by_user_id else None
        base = {
            "id": None,
            "issuance_id": row.id,
            "inventory_id": row.inventory_id,
            "inventory_instance_id": row.inventory_instance_id,
            "quantity": row.quantity or 1,
            "installer_user_id": row.issued_to_user_id,
            "installer_name": _user_display_name(issued_to),
            "part_number": row.part_number,
            "serial_number": row.serial_number,
            "inventory_name": row.inventory_name,
            "inventory_type": row.inventory_type,
        }
        synthesized.append(
            {
                **base,
                "event_type": IssuanceEventType.ISSUED.value,
                "actor_user_id": row.issued_by_user_id,
                "actor_name": _user_display_name(issued_by),
                "notes": row.notes,
                "created_at": _ensure_utc(row.issued_at),
            }
        )
        notices = list(
            session.exec(
                select(InventoryReturnNotice)
                .where(InventoryReturnNotice.issuance_id == row.id)
                .order_by(col(InventoryReturnNotice.created_at).asc())
            ).all()
        )
        for notice in notices:
            synthesized.append(
                {
                    **base,
                    "event_type": IssuanceEventType.RETURN_REQUESTED.value,
                    "actor_user_id": notice.returned_by_user_id,
                    "actor_name": notice.returned_by_name,
                    "notes": notice.request_notes,
                    "created_at": _ensure_utc(notice.created_at),
                }
            )
            if notice.decision == "accepted":
                decided_by = session.get(User, notice.decided_by_id) if notice.decided_by_id else None
                synthesized.append(
                    {
                        **base,
                        "event_type": IssuanceEventType.RETURN_ACCEPTED.value,
                        "actor_user_id": notice.decided_by_id,
                        "actor_name": _user_display_name(decided_by),
                        "notes": notice.decision_notes,
                        "created_at": _ensure_utc(notice.decided_at or notice.created_at),
                    }
                )
            elif notice.decision == "rejected":
                decided_by = session.get(User, notice.decided_by_id) if notice.decided_by_id else None
                synthesized.append(
                    {
                        **base,
                        "event_type": IssuanceEventType.RETURN_REJECTED.value,
                        "actor_user_id": notice.decided_by_id,
                        "actor_name": _user_display_name(decided_by),
                        "notes": notice.decision_notes,
                        "created_at": _ensure_utc(notice.decided_at or notice.created_at),
                    }
                )
        if row.status == IssuanceStatus.INSTALLED.value and row.installed_at:
            installed_by = session.get(User, row.installed_by_id) if row.installed_by_id else None
            synthesized.append(
                {
                    **base,
                    "event_type": IssuanceEventType.INSTALLED.value,
                    "actor_user_id": row.installed_by_id,
                    "actor_name": _user_display_name(installed_by),
                    "notes": None,
                    "created_at": _ensure_utc(row.installed_at),
                }
            )
        if row.status == IssuanceStatus.REVERTED.value and row.closed_at:
            closed_by = session.get(User, row.closed_by_id) if row.closed_by_id else None
            synthesized.append(
                {
                    **base,
                    "event_type": IssuanceEventType.REVERTED.value,
                    "actor_user_id": row.closed_by_id,
                    "actor_name": _user_display_name(closed_by),
                    "notes": row.notes,
                    "created_at": _ensure_utc(row.closed_at),
                }
            )
    synthesized.sort(key=lambda e: (e.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), e.get("issuance_id") or 0))
    return synthesized


def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize datetimes to UTC-aware for API serialization."""
    from app.utils.datetimes import to_api_utc

    return to_api_utc(value)


def issuance_to_dict(session: Session, row: InventoryIssuance) -> dict:
    issued_to = session.get(User, row.issued_to_user_id) if row.issued_to_user_id else None
    issued_by = session.get(User, row.issued_by_user_id) if row.issued_by_user_id else None
    installed_by = session.get(User, row.installed_by_id) if row.installed_by_id else None
    closed_by = session.get(User, row.closed_by_id) if row.closed_by_id else None
    data = row.model_dump()
    for key in (
        "issued_at",
        "installed_at",
        "closed_at",
        "return_requested_at",
    ):
        if key in data:
            data[key] = _ensure_utc(data.get(key))
    data["issued_to_name"] = _user_display_name(issued_to)
    data["issued_by_name"] = _user_display_name(issued_by)
    data["installed_by_name"] = _user_display_name(installed_by)
    data["closed_by_name"] = _user_display_name(closed_by)
    data.pop("signature_payload", None)
    return data


def list_open_issuances_for_inventory(
    session: Session,
    inventory_id: int,
) -> List[InventoryIssuance]:
    return list(
        session.exec(
            select(InventoryIssuance).where(
                InventoryIssuance.inventory_id == inventory_id,
                InventoryIssuance.status.in_(RESERVED_STATUSES),
            )
        ).all()
    )


def reserved_quantity(session: Session, inventory_id: int) -> int:
    total = session.exec(
        select(func.coalesce(func.sum(InventoryIssuance.quantity), 0)).where(
            InventoryIssuance.inventory_id == inventory_id,
            InventoryIssuance.status.in_(RESERVED_STATUSES),
        )
    ).one()
    return int(total or 0)


def open_issuance_for_instance(
    session: Session,
    instance_id: int,
    *,
    statuses: tuple[str, ...] = RESERVED_STATUSES,
) -> Optional[InventoryIssuance]:
    return session.exec(
        select(InventoryIssuance).where(
            InventoryIssuance.inventory_instance_id == instance_id,
            InventoryIssuance.status.in_(statuses),
        )
    ).first()


def installable_issuance_for_instance(
    session: Session,
    instance_id: int,
) -> Optional[InventoryIssuance]:
    """Only open `issued` rows — return_pending cannot be installed."""
    return open_issuance_for_instance(session, instance_id, statuses=(OPEN_STATUS,))


def available_quantity(session: Session, inventory: Inventory) -> int:
    from app.services.inventory_reservation_service import project_reserved_quantity

    reserved = reserved_quantity(session, inventory.id)
    project_reserved = project_reserved_quantity(session, int(inventory.id))
    total = inventory.quantity or 0
    return max(0, total - reserved - project_reserved)


def instance_reservation_map(
    session: Session,
    inventory_id: int,
) -> dict[int, tuple[int, str]]:
    """Map instance_id -> (open/pending issuance id, status)."""
    rows = session.exec(
        select(InventoryIssuance).where(
            InventoryIssuance.inventory_id == inventory_id,
            InventoryIssuance.status.in_(RESERVED_STATUSES),
            InventoryIssuance.inventory_instance_id.is_not(None),
        )
    ).all()
    return {
        int(r.inventory_instance_id): (int(r.id), str(r.status))
        for r in rows
        if r.inventory_instance_id is not None and r.id is not None
    }


def require_issue_signature(
    signature_type: Optional[str],
    signature_payload: Optional[str],
) -> tuple[str, str]:
    """Spec 07 — issue is blocked without DIGITAL payload or HARD_COPY acknowledgment."""
    kind = (signature_type or "").strip().upper()
    if kind not in (SignatureType.DIGITAL.value, SignatureType.HARD_COPY.value):
        raise HTTPException(
            status_code=400,
            detail="Signature is required to issue (DIGITAL or HARD_COPY)",
        )
    payload = (signature_payload or "").strip()
    if kind == SignatureType.DIGITAL.value:
        if not payload:
            raise HTTPException(
                status_code=400,
                detail="Digital signature payload is required",
            )
        return kind, payload
    ack = payload.upper().replace(" ", "_")
    if ack in ("", "FALSE", "0", "NO"):
        raise HTTPException(
            status_code=400,
            detail="Hard-copy acknowledgment is required",
        )
    return kind, HARD_COPY_ACKNOWLEDGMENT


def _set_item_lifecycle_status(
    session: Session,
    *,
    inventory: Inventory,
    instance: Optional[InventoryInstance],
    from_status: str,
    to_status: str,
) -> None:
    from app.services.inventory_reservation_service import get_item_status_id

    try:
        assert_transition("item", from_status, to_status, actor_role=None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    status_id = get_item_status_id(session, to_status)
    now = datetime.now(timezone.utc)
    if instance is not None:
        instance.status_id = status_id
        instance.updated_at = now
        session.add(instance)
    inventory.status_id = status_id
    inventory.updated_at = now
    session.add(inventory)


def _advance_to_issued(
    session: Session,
    *,
    inventory: Inventory,
    instance: Optional[InventoryInstance],
    current: str,
) -> None:
    if current == ItemStatus.ISSUED.value:
        return
    if current == ItemStatus.RESERVED.value:
        _set_item_lifecycle_status(
            session,
            inventory=inventory,
            instance=instance,
            from_status=current,
            to_status=ItemStatus.ISSUED.value,
        )
        return
    if current == ItemStatus.AVAILABLE.value:
        _set_item_lifecycle_status(
            session,
            inventory=inventory,
            instance=instance,
            from_status=ItemStatus.AVAILABLE.value,
            to_status=ItemStatus.RESERVED.value,
        )
        _set_item_lifecycle_status(
            session,
            inventory=inventory,
            instance=instance,
            from_status=ItemStatus.RESERVED.value,
            to_status=ItemStatus.ISSUED.value,
        )
        return
    if current == ItemStatus.REPAIRABLE.value:
        _set_item_lifecycle_status(
            session,
            inventory=inventory,
            instance=instance,
            from_status=ItemStatus.REPAIRABLE.value,
            to_status=ItemStatus.ISSUED.value,
        )
        return
    raise HTTPException(
        status_code=400,
        detail=f"Item status {current} cannot be issued",
    )


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
    signature_type: Optional[str] = None,
    signature_payload: Optional[str] = None,
    item_request_id: Optional[int] = None,
    rework: bool = False,
    rework_project_id: Optional[int] = None,
    rework_flight_id: Optional[int] = None,
    rework_sdls_id: Optional[int] = None,
) -> InventoryIssuance:
    if quantity < 1:
        raise HTTPException(status_code=400, detail="Quantity must be at least 1")

    sig_type, sig_payload = require_issue_signature(signature_type, signature_payload)

    issued_to = session.get(User, issued_to_user_id)
    if not issued_to:
        raise HTTPException(status_code=404, detail="Developer (issued_to user) not found")

    serial_number: Optional[str] = None
    resolved_instance_id: Optional[int] = None
    instance: Optional[InventoryInstance] = None
    reservation_id: Optional[int] = None
    project_id: Optional[int] = None
    flight_id: Optional[int] = None
    sdls_id: Optional[int] = None

    from app.services.inventory_reservation_service import item_status_name

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
        current = item_status_name(session, inventory.status_id) or ItemStatus.AVAILABLE.value
        _advance_to_issued(session, inventory=inventory, instance=None, current=current)
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
        from app.services.inventory_reservation_service import (
            active_reservation_for_instance,
            consume_reservation,
        )

        project_hold = active_reservation_for_instance(session, int(instance.id))
        requested_type = (target_entity_type or "").strip().lower() or None
        requested_id = target_entity_id
        if rework:
            if item_status_name(session, instance.status_id) == ItemStatus.SCRAPPED.value:
                raise HTTPException(
                    status_code=400,
                    detail="Scrap disposition cannot re-issue that serial",
                )
            if project_hold:
                reservation_id = int(project_hold.id) if project_hold.id else None
                project_id = int(project_hold.project_id)
                flight_id = int(project_hold.flight_id)
                sdls_id = int(project_hold.sdls_id)
                target_entity_type = project_hold.target_entity_type
                target_entity_id = project_hold.target_entity_id
            else:
                project_id = rework_project_id
                flight_id = rework_flight_id
                sdls_id = rework_sdls_id
                if not project_id:
                    raise HTTPException(
                        status_code=400,
                        detail="Rework re-issue requires project allocation",
                    )
        elif project_hold:
            if not item_request_id:
                raise HTTPException(
                    status_code=400,
                    detail="Developer must request this reserved item before it can be issued",
                )
            hold_type = (project_hold.target_entity_type or "").strip().lower()
            hold_id = int(project_hold.target_entity_id)
            if requested_type and requested_id is not None:
                if hold_type != requested_type or hold_id != int(requested_id):
                    raise HTTPException(
                        status_code=400,
                        detail="Item is reserved to a different project/hierarchy",
                    )
            target_entity_type = project_hold.target_entity_type
            target_entity_id = project_hold.target_entity_id
            reservation_id = int(project_hold.id) if project_hold.id else None
            project_id = int(project_hold.project_id)
            flight_id = int(project_hold.flight_id)
            sdls_id = int(project_hold.sdls_id)
        elif requested_type and requested_id is not None:
            raise HTTPException(
                status_code=400,
                detail="Issue is only allowed for stock reserved to this hierarchy",
            )
        current = (
            item_status_name(session, instance.status_id) or ItemStatus.AVAILABLE.value
        )
        _advance_to_issued(
            session, inventory=inventory, instance=instance, current=current
        )
        if project_hold:
            actor = session.get(User, issued_by_user_id)
            consume_reservation(session, project_hold, actor=actor)
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
        signature_type=sig_type,
        signature_payload=sig_payload,
        item_request_id=item_request_id,
        reservation_id=reservation_id,
        project_id=project_id,
        flight_id=flight_id,
        sdls_id=sdls_id,
        item_lifecycle_status=ItemStatus.ISSUED.value,
    )
    session.add(issuance)
    session.flush()
    actor = session.get(User, issued_by_user_id)
    record_issuance_event(
        session,
        issuance,
        event_type=IssuanceEventType.ISSUED.value,
        actor=actor,
        notes=notes,
    )
    item_label = issuance.inventory_name or issuance.part_number or f"Inventory #{issuance.inventory_id}"
    create_installer_notice(
        session,
        user_id=issued_to_user_id,
        notice_type=InstallerNoticeType.ISSUED.value,
        issuance=issuance,
        message=f"Inventory issued to you: {item_label}"
        + (f" ({issuance.serial_number})" if issuance.serial_number else ""),
        notes=notes,
    )
    return issuance


def return_issuance(
    session: Session,
    issuance: InventoryIssuance,
    *,
    closed_by: User,
    is_manager: bool,
    notes: Optional[str] = None,
) -> Tuple[InventoryIssuance, InventoryReturnNotice]:
    """
    Installer: request return (status → return_pending; still reserved until admin accepts).
    Manager force-return of open issued stock: finalize immediately to returned.
    """
    cleaned_notes = _require_notes(notes, label="Return remarks")

    if is_manager:
        if issuance.status not in (OPEN_STATUS, RETURN_PENDING_STATUS):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Only issued / return-pending issuances can be returned "
                    f"(current status: {issuance.status})"
                ),
            )
        return accept_return_issuance(
            session,
            issuance,
            decided_by=closed_by,
            notes=cleaned_notes,
            create_notice_if_missing=issuance.status == OPEN_STATUS,
            returned_by_user_id=issuance.issued_to_user_id,
            request_notes=cleaned_notes if issuance.status == OPEN_STATUS else None,
        )

    if issuance.status != OPEN_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"Only open issuances can be returned (current status: {issuance.status})",
        )
    if issuance.issued_to_user_id != closed_by.id:
        raise HTTPException(
            status_code=403,
            detail="You can only return inventory issued to you",
        )

    now = datetime.now(timezone.utc)
    issuance.status = RETURN_PENDING_STATUS
    issuance.return_requested_at = now
    issuance.notes = ((issuance.notes or "") + f"\nReturn requested: {cleaned_notes}").strip()
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
        created_at=now,
        decision="pending",
        request_notes=cleaned_notes,
    )
    session.add(notice)
    session.flush()
    record_issuance_event(
        session,
        issuance,
        event_type=IssuanceEventType.RETURN_REQUESTED.value,
        actor=closed_by,
        notes=cleaned_notes,
    )
    return issuance, notice


def _pending_notice_for_issuance(
    session: Session,
    issuance_id: int,
) -> Optional[InventoryReturnNotice]:
    return session.exec(
        select(InventoryReturnNotice)
        .where(
            InventoryReturnNotice.issuance_id == issuance_id,
            InventoryReturnNotice.decision == "pending",
        )
        .order_by(col(InventoryReturnNotice.created_at).desc())
    ).first()


def accept_return_issuance(
    session: Session,
    issuance: InventoryIssuance,
    *,
    decided_by: User,
    notes: Optional[str] = None,
    create_notice_if_missing: bool = False,
    returned_by_user_id: Optional[int] = None,
    request_notes: Optional[str] = None,
) -> Tuple[InventoryIssuance, InventoryReturnNotice]:
    """Admin accepts return → status returned; stock no longer reserved."""
    cleaned_notes = _require_notes(notes, label="Admin remarks")

    if issuance.status not in (OPEN_STATUS, RETURN_PENDING_STATUS):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Only issued / return-pending issuances can be accepted "
                f"(current status: {issuance.status})"
            ),
        )

    now = datetime.now(timezone.utc)
    issuance.status = IssuanceStatus.RETURNED.value
    issuance.closed_at = now
    issuance.closed_by_id = decided_by.id
    issuance.notes = ((issuance.notes or "") + f"\nReturn accepted: {cleaned_notes}").strip()
    session.add(issuance)
    session.flush()

    notice = _pending_notice_for_issuance(session, issuance.id)
    if notice is None and create_notice_if_missing:
        by_id = returned_by_user_id or issuance.issued_to_user_id
        by_user = session.get(User, by_id) if by_id else None
        notice = InventoryReturnNotice(
            issuance_id=issuance.id,
            inventory_id=issuance.inventory_id,
            inventory_name=issuance.inventory_name,
            part_number=issuance.part_number,
            serial_number=issuance.serial_number,
            returned_by_user_id=by_id,
            returned_by_name=_user_display_name(by_user),
            created_at=now,
            decision="pending",
            request_notes=request_notes,
        )
        session.add(notice)
        session.flush()

    if notice is None:
        raise HTTPException(status_code=404, detail="No pending return notice for this issuance")

    notice.decision = "accepted"
    notice.decided_at = now
    notice.decided_by_id = decided_by.id
    notice.read_at = now
    notice.decision_notes = cleaned_notes
    session.add(notice)
    session.flush()
    record_issuance_event(
        session,
        issuance,
        event_type=IssuanceEventType.RETURN_ACCEPTED.value,
        actor=decided_by,
        notes=cleaned_notes,
    )
    item_label = issuance.inventory_name or issuance.part_number or f"Inventory #{issuance.inventory_id}"
    create_installer_notice(
        session,
        user_id=issuance.issued_to_user_id,
        notice_type=InstallerNoticeType.RETURN_ACCEPTED.value,
        issuance=issuance,
        message=f"Your return of {item_label} was accepted",
        notes=cleaned_notes,
    )
    return issuance, notice


def reject_return_issuance(
    session: Session,
    issuance: InventoryIssuance,
    *,
    decided_by: User,
    notes: Optional[str] = None,
) -> Tuple[InventoryIssuance, InventoryReturnNotice]:
    """Admin rejects return → reissue to installer (status back to issued)."""
    cleaned_notes = _require_notes(notes, label="Admin remarks")

    if issuance.status != RETURN_PENDING_STATUS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Only return-pending issuances can be rejected "
                f"(current status: {issuance.status})"
            ),
        )

    now = datetime.now(timezone.utc)
    issuance.status = OPEN_STATUS
    issuance.return_requested_at = None
    issuance.notes = ((issuance.notes or "") + f"\nReturn rejected: {cleaned_notes}").strip()
    session.add(issuance)
    session.flush()

    notice = _pending_notice_for_issuance(session, issuance.id)
    if notice is None:
        raise HTTPException(status_code=404, detail="No pending return notice for this issuance")

    notice.decision = "rejected"
    notice.decided_at = now
    notice.decided_by_id = decided_by.id
    notice.read_at = now
    notice.decision_notes = cleaned_notes
    session.add(notice)
    session.flush()
    record_issuance_event(
        session,
        issuance,
        event_type=IssuanceEventType.RETURN_REJECTED.value,
        actor=decided_by,
        notes=cleaned_notes,
    )
    item_label = issuance.inventory_name or issuance.part_number or f"Inventory #{issuance.inventory_id}"
    create_installer_notice(
        session,
        user_id=issuance.issued_to_user_id,
        notice_type=InstallerNoticeType.RETURN_REJECTED.value,
        issuance=issuance,
        message=f"Your return of {item_label} was rejected — item remains issued to you",
        notes=cleaned_notes,
    )
    return issuance, notice


def create_return_notice_read(notice: InventoryReturnNotice) -> dict:
    data = notice.model_dump()
    for key in ("created_at", "read_at", "decided_at"):
        if key in data:
            data[key] = _ensure_utc(data.get(key))
    return data


def list_return_notices(
    session: Session,
    *,
    unread_only: bool = False,
    pending_only: bool = False,
    search: Optional[str] = None,
) -> List[InventoryReturnNotice]:
    stmt = select(InventoryReturnNotice).order_by(col(InventoryReturnNotice.created_at).desc())
    if pending_only:
        stmt = stmt.where(InventoryReturnNotice.decision == "pending")
    elif unread_only:
        stmt = stmt.where(InventoryReturnNotice.read_at.is_(None))
    term = (search or "").strip()
    if term:
        like = f"%{term.lower()}%"
        stmt = stmt.where(
            func.lower(
                func.coalesce(InventoryReturnNotice.inventory_name, "")
                + " "
                + func.coalesce(InventoryReturnNotice.part_number, "")
                + " "
                + func.coalesce(InventoryReturnNotice.serial_number, "")
                + " "
                + func.coalesce(InventoryReturnNotice.returned_by_name, "")
                + " "
                + func.coalesce(InventoryReturnNotice.decision_notes, "")
                + " "
                + func.coalesce(InventoryReturnNotice.request_notes, "")
                + " "
                + func.coalesce(InventoryReturnNotice.decision, "")
            ).like(like)
        )
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
            pending = open_issuance_for_instance(
                session, check_instance_id, statuses=(RETURN_PENDING_STATUS,)
            )
            if pending is not None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "This serial has a return pending admin approval and cannot "
                        "be installed until the return is accepted or rejected."
                    ),
                )
            open_row = installable_issuance_for_instance(session, check_instance_id)
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
    actor = session.get(User, installed_by_id)
    record_issuance_event(
        session,
        issuance,
        event_type=IssuanceEventType.INSTALLED.value,
        actor=actor,
        notes=None,
    )
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
    if issuance is not None and issuance.status != OPEN_STATUS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Issuance cannot be installed (status: {issuance.status}). "
                "Return-pending stock must be accepted or rejected first."
            ),
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
        from app.auth import require_install_owner_or_manager

        require_install_owner_or_manager(closed_by, row)
        installed_by = getattr(row, "installed_by_id", None)
        if installed_by is not None:
            issued_to_id = int(installed_by)

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
        record_issuance_event(
            session,
            prior,
            event_type=IssuanceEventType.REVERTED.value,
            actor=closed_by,
            notes=notes,
        )

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
    record_issuance_event(
        session,
        new_issuance,
        event_type=IssuanceEventType.ISSUED.value,
        actor=closed_by,
        notes=notes or "Reopened after revert from hierarchy",
    )
    item_label = (
        new_issuance.inventory_name
        or new_issuance.part_number
        or f"Inventory #{new_issuance.inventory_id}"
    )
    create_installer_notice(
        session,
        user_id=issued_to_id,
        notice_type=InstallerNoticeType.ISSUED.value,
        issuance=new_issuance,
        message=f"Inventory reissued to you after revert: {item_label}"
        + (f" ({new_issuance.serial_number})" if new_issuance.serial_number else ""),
        notes=notes or "Reopened after revert from hierarchy",
    )

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
