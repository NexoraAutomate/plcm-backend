"""
Spec 06 — reservation expiry (deadlock prevention).

Idle RESERVED stock: reminder after idle days, then grace, then auto-release
via Spec 04 release with reason AUTO_RELEASE_EXPIRY. ISSUED (and later) skipped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.domain.workflow_status import ItemStatus
from app.models.base import (
    AUTO_RELEASE_EXPIRY_REASON,
    InventoryReservationStatus,
    ReservationExpiryNoticeType,
)
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryReservation,
    InventoryReservationExpiryNotice,
    Project,
    User,
)
from app.services.inventory_issuance_service import open_issuance_for_instance
from app.services.inventory_reservation_service import (
    item_status_name,
    release_reservation,
    reservation_grace_days,
    reservation_idle_days,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def reservation_has_progressed(
    session: Session, reservation: InventoryReservation
) -> bool:
    """True when the unit is no longer merely RESERVED (ISSUED or later / open issue)."""
    if reservation.inventory_instance_id:
        instance = session.get(InventoryInstance, reservation.inventory_instance_id)
        if instance is None:
            return True
        name = item_status_name(session, instance.status_id) or ""
        if name != ItemStatus.RESERVED.value:
            return True
        if open_issuance_for_instance(session, int(instance.id)):
            return True
        return False
    inventory = session.get(Inventory, reservation.inventory_id)
    if inventory is None:
        return True
    name = item_status_name(session, inventory.status_id) or ""
    return name != ItemStatus.RESERVED.value


def idle_deadline(reservation: InventoryReservation) -> datetime:
    """When the idle reminder is due (expires_at, or reserved_at + idle * (1+extensions))."""
    if reservation.expires_at is not None:
        return _aware(reservation.expires_at)
    reserved_at = _aware(reservation.reserved_at)
    idle = reservation_idle_days()
    extra = idle * int(reservation.extension_count or 0)
    return reserved_at + timedelta(days=idle + extra)


def auto_release_deadline(reservation: InventoryReservation) -> datetime:
    return idle_deadline(reservation) + timedelta(days=reservation_grace_days())


def notice_to_dict(notice: InventoryReservationExpiryNotice) -> dict[str, Any]:
    return {
        "id": notice.id,
        "user_id": notice.user_id,
        "reservation_id": notice.reservation_id,
        "notice_type": notice.notice_type,
        "part_number": notice.part_number,
        "serial_number": notice.serial_number,
        "flight_code": notice.flight_code,
        "flight_name": notice.flight_name,
        "sdls_code": notice.sdls_code,
        "sdls_name": notice.sdls_name,
        "inventory_name": notice.inventory_name,
        "project_id": notice.project_id,
        "project_name": notice.project_name,
        "message": notice.message,
        "created_at": notice.created_at,
        "read_at": notice.read_at,
    }


def _notify_recipients(
    session: Session, reservation: InventoryReservation
) -> list[User]:
    recipients: dict[int, User] = {}
    for uid in {reservation.reserved_by_user_id}:
        user = session.get(User, uid)
        if user and user.id is not None:
            recipients[int(user.id)] = user
    project = reservation.project or session.get(Project, reservation.project_id)
    if project and project.assigned_hm_id:
        user = session.get(User, int(project.assigned_hm_id))
        if user and user.id is not None:
            recipients[int(user.id)] = user
    return list(recipients.values())


def _send_notice(
    session: Session,
    reservation: InventoryReservation,
    *,
    notice_type: str,
    now: datetime,
) -> list[InventoryReservationExpiryNotice]:
    project = reservation.project or session.get(Project, reservation.project_id)
    flight_code = reservation.flight.code if reservation.flight else None
    flight_name = reservation.flight.name if reservation.flight else None
    sdls_code = reservation.sdls.code if reservation.sdls else None
    sdls_name = reservation.sdls.name if reservation.sdls else None
    inventory_name = reservation.inventory.name if reservation.inventory else None
    project_name = project.name if project else None
    sn = reservation.serial_number or "unit"
    pn = reservation.part_number or "—"
    loc = f"{flight_name or flight_code or 'Flight'} / {sdls_name or sdls_code or 'SDLS'}"
    if notice_type == ReservationExpiryNoticeType.AUTO_RELEASED.value:
        message = (
            f"Reservation auto-released ({AUTO_RELEASE_EXPIRY_REASON}): "
            f"{inventory_name or sn}, PN {pn}, {loc}"
        )
    else:
        grace = reservation_grace_days()
        message = (
            f"Idle reservation reminder: {inventory_name or sn}, PN {pn}, {loc}. "
            f"Will auto-release in {grace} day(s) unless issued or extended."
        )
    rows: list[InventoryReservationExpiryNotice] = []
    for user in _notify_recipients(session, reservation):
        if user.id is None:
            continue
        row = InventoryReservationExpiryNotice(
            user_id=int(user.id),
            reservation_id=int(reservation.id),
            notice_type=notice_type,
            part_number=reservation.part_number,
            serial_number=reservation.serial_number,
            flight_code=flight_code,
            flight_name=flight_name,
            sdls_code=sdls_code,
            sdls_name=sdls_name,
            inventory_name=inventory_name,
            project_id=reservation.project_id,
            project_name=project_name,
            message=message,
            created_at=now,
        )
        session.add(row)
        rows.append(row)
    return rows


def remind_idle_reservation(
    session: Session,
    reservation: InventoryReservation,
    *,
    now: Optional[datetime] = None,
) -> list[InventoryReservationExpiryNotice]:
    if reservation.last_reminder_at is not None:
        return []
    clock = now or _now()
    rows = _send_notice(
        session,
        reservation,
        notice_type=ReservationExpiryNoticeType.REMINDER.value,
        now=clock,
    )
    reservation.last_reminder_at = clock
    reservation.updated_at = clock
    session.add(reservation)
    session.commit()
    session.refresh(reservation)
    for row in rows:
        session.refresh(row)
    return rows


def list_expiry_notices(
    session: Session,
    *,
    user_id: int,
    unread_only: bool = False,
) -> list[InventoryReservationExpiryNotice]:
    query = select(InventoryReservationExpiryNotice).where(
        InventoryReservationExpiryNotice.user_id == user_id
    )
    if unread_only:
        query = query.where(InventoryReservationExpiryNotice.read_at.is_(None))
    query = query.order_by(
        InventoryReservationExpiryNotice.created_at.desc(),
        InventoryReservationExpiryNotice.id.desc(),
    )
    return list(session.exec(query).all())


def mark_expiry_notice_read(
    session: Session, notice: InventoryReservationExpiryNotice
) -> InventoryReservationExpiryNotice:
    if notice.read_at is None:
        notice.read_at = _now()
        session.add(notice)
    return notice


def mark_all_expiry_notices_read(session: Session, user_id: int) -> int:
    rows = list_expiry_notices(session, user_id=user_id, unread_only=True)
    now = _now()
    for row in rows:
        row.read_at = now
        session.add(row)
    return len(rows)


def evaluate_reservation_expiry(
    session: Session,
    *,
    now: Optional[datetime] = None,
    project_id: Optional[int] = None,
) -> dict[str, int]:
    """
    Scan active reservations. Remind at idle deadline; auto-release after grace.

    Passing `now` supports time-travel tests without freezing the clock.
    `project_id` limits the scan (tests); the scheduled job evaluates all projects.
    """
    clock = _aware(now) if now is not None else _now()
    query = select(InventoryReservation).where(
        InventoryReservation.status == InventoryReservationStatus.ACTIVE.value
    )
    if project_id is not None:
        query = query.where(InventoryReservation.project_id == project_id)
    rows = list(session.exec(query).all())
    reminded = 0
    released = 0
    skipped_progressed = 0
    for reservation in rows:
        if reservation_has_progressed(session, reservation):
            skipped_progressed += 1
            continue
        idle_at = idle_deadline(reservation)
        release_at = auto_release_deadline(reservation)
        if clock >= release_at:
            if reservation.last_reminder_at is None:
                remind_idle_reservation(session, reservation, now=clock)
                reminded += 1
            _send_notice(
                session,
                reservation,
                notice_type=ReservationExpiryNoticeType.AUTO_RELEASED.value,
                now=clock,
            )
            session.commit()
            release_reservation(
                session,
                int(reservation.project_id),
                int(reservation.id),
                actor=reservation.reserved_by,
                reason=AUTO_RELEASE_EXPIRY_REASON,
            )
            released += 1
        elif clock >= idle_at:
            if reservation.last_reminder_at is None:
                remind_idle_reservation(session, reservation, now=clock)
                reminded += 1
    return {
        "examined": len(rows),
        "reminded": reminded,
        "released": released,
        "skipped_progressed": skipped_progressed,
    }
