"""Spec 07 — Developer request-to-issue queue and IM signed issue."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.domain.workflow_roles import WorkflowRole, has_workflow_role
from app.models.base import ItemRequestStatus
from app.models.tables import (
    Inventory,
    InventoryItemRequest,
    InventoryReservation,
    User,
)
from app.services.hierarchy_developer_service import (
    ASSIGNABLE_ENTITY_TYPES,
    HierarchyDeveloperError,
    _load_entity,
)
from app.services.inventory_issuance_service import issue_inventory_unit, issuance_to_dict
from app.services.inventory_reservation_service import (
    InventoryReservationError,
    active_reservation_for_entity,
    _load_hierarchy_entity,
    _resolve_flight_sdls_for_entity,
)


class ItemRequestError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role_names(user: User) -> list[str]:
    return [r.name for r in (user.roles or []) if r.name]


def _is_admin(user: User) -> bool:
    return has_workflow_role(_role_names(user), WorkflowRole.ADMIN)


def _user_display(user: Optional[User]) -> Optional[str]:
    if not user:
        return None
    return user.full_name or user.username


def create_item_request(
    session: Session,
    *,
    entity_type: str,
    entity_id: int,
    actor: User,
    notes: Optional[str] = None,
    commit: bool = True,
) -> InventoryItemRequest:
    et = (entity_type or "").strip().lower()
    if et not in ASSIGNABLE_ENTITY_TYPES:
        raise ItemRequestError(f"Unsupported entity type: {entity_type}")
    try:
        entity = _load_entity(session, et, entity_id)
    except HierarchyDeveloperError as exc:
        raise ItemRequestError(str(exc)) from exc

    assigned_id = getattr(entity, "assigned_developer_id", None)
    if not assigned_id:
        raise ItemRequestError("Hierarchy item is not assigned to a developer")
    if int(assigned_id) != int(actor.id) and not _is_admin(actor):
        raise ItemRequestError("You can only request items assigned to you")

    reservation = active_reservation_for_entity(session, et, entity_id)
    if reservation is None:
        raise ItemRequestError("No reserved inventory for this hierarchy item")

    existing = session.exec(
        select(InventoryItemRequest).where(
            InventoryItemRequest.reservation_id == reservation.id,
            InventoryItemRequest.status == ItemRequestStatus.PENDING.value,
        )
    ).first()
    if existing:
        return existing

    try:
        flight, sdls, _system = _resolve_flight_sdls_for_entity(session, et, entity)
    except InventoryReservationError as exc:
        raise ItemRequestError(str(exc)) from exc

    row = InventoryItemRequest(
        project_id=reservation.project_id,
        flight_id=reservation.flight_id or flight.id,
        sdls_id=reservation.sdls_id or sdls.id,
        target_entity_type=et,
        target_entity_id=int(entity_id),
        assigned_developer_id=int(assigned_id),
        requested_by_user_id=int(actor.id),
        inventory_id=int(reservation.inventory_id),
        inventory_instance_id=reservation.inventory_instance_id,
        reservation_id=int(reservation.id),
        status=ItemRequestStatus.PENDING.value,
        requested_at=_now(),
        notes=notes,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(row)
    if commit:
        session.commit()
        session.refresh(row)
    else:
        session.flush()
    return row


def create_bulk_item_requests(
    session: Session,
    *,
    actor: User,
    mode: str,
    items: Optional[list[dict]] = None,
    notes: Optional[str] = None,
) -> tuple[list[InventoryItemRequest], list[dict]]:
    from app.services.hierarchy_developer_service import list_assigned_work

    kind = (mode or "").strip().lower()
    if kind not in {"all", "reserved", "selected"}:
        raise ItemRequestError("Bulk mode must be all, reserved, or selected")

    work = list_assigned_work(session, int(actor.id))
    if kind == "selected":
        wanted = {
            (
                str(item.get("entity_type") or "").strip().lower(),
                int(item.get("entity_id")),
            )
            for item in (items or [])
            if item.get("entity_id") is not None
        }
        if not wanted:
            raise ItemRequestError("Select at least one assigned item")
        work = [row for row in work if (row["entity_type"], row["entity_id"]) in wanted]
    elif kind == "reserved":
        work = [row for row in work if row.get("reserved") and not row.get("issued")]
    else:
        work = [row for row in work if not row.get("issued")]

    created: list[InventoryItemRequest] = []
    skipped: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for row in work:
        key = (row["entity_type"], int(row["entity_id"]))
        if key in seen:
            continue
        seen.add(key)
        if row.get("issued"):
            skipped.append(
                {
                    "entity_type": row["entity_type"],
                    "entity_id": row["entity_id"],
                    "reason": "Already issued",
                }
            )
            continue
        if not row.get("reserved"):
            skipped.append(
                {
                    "entity_type": row["entity_type"],
                    "entity_id": row["entity_id"],
                    "reason": "No reserved inventory for this hierarchy item",
                }
            )
            continue
        try:
            created.append(
                create_item_request(
                    session,
                    entity_type=row["entity_type"],
                    entity_id=int(row["entity_id"]),
                    actor=actor,
                    notes=notes,
                    commit=False,
                )
            )
        except ItemRequestError as exc:
            skipped.append(
                {
                    "entity_type": row["entity_type"],
                    "entity_id": row["entity_id"],
                    "reason": str(exc),
                }
            )
    session.commit()
    for created_row in created:
        session.refresh(created_row)
    return created, skipped


def list_item_requests(
    session: Session,
    *,
    actor: User,
    status: Optional[str] = None,
    mine_only: bool = False,
) -> list[InventoryItemRequest]:
    query = select(InventoryItemRequest)
    if status:
        query = query.where(InventoryItemRequest.status == status.strip().lower())
    if mine_only or (
        has_workflow_role(_role_names(actor), WorkflowRole.DEV) and not _is_admin(actor)
    ):
        query = query.where(InventoryItemRequest.assigned_developer_id == int(actor.id))
    query = query.order_by(
        InventoryItemRequest.requested_at.desc(), InventoryItemRequest.id.desc()
    )
    return list(session.exec(query).all())


def issue_item_request(
    session: Session,
    request_id: int,
    *,
    actor: User,
    signature_type: str,
    signature_payload: Optional[str],
    notes: Optional[str] = None,
) -> InventoryItemRequest:
    row = session.get(InventoryItemRequest, request_id)
    if not row:
        raise ItemRequestError("Issue request not found")
    if row.status != ItemRequestStatus.PENDING.value:
        raise ItemRequestError("Issue request is not pending")

    reservation = session.get(InventoryReservation, row.reservation_id)
    if not reservation:
        raise ItemRequestError("Reservation for this request was not found")

    inventory = session.get(Inventory, row.inventory_id)
    if not inventory:
        raise ItemRequestError("Inventory not found")

    try:
        issuance = issue_inventory_unit(
            session,
            inventory,
            issued_to_user_id=int(row.assigned_developer_id),
            issued_by_user_id=int(actor.id),
            quantity=1,
            instance_id=row.inventory_instance_id,
            target_entity_type=row.target_entity_type,
            target_entity_id=row.target_entity_id,
            notes=notes or row.notes,
            signature_type=signature_type,
            signature_payload=signature_payload,
            item_request_id=int(row.id) if row.id else None,
        )
    except HTTPException as exc:
        raise ItemRequestError(exc.detail if isinstance(exc.detail, str) else str(exc.detail)) from exc

    row.status = ItemRequestStatus.ISSUED.value
    row.issued_at = issuance.issued_at
    row.issued_issuance_id = issuance.id
    row.updated_at = _now()
    session.add(row)
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, row.project_id)
    session.commit()
    session.refresh(row)
    return row


def item_request_to_dict(session: Session, row: InventoryItemRequest) -> dict[str, Any]:
    developer = session.get(User, row.assigned_developer_id)
    requester = session.get(User, row.requested_by_user_id)
    inventory = row.inventory or session.get(Inventory, row.inventory_id)
    target_name = None
    try:
        entity = _load_hierarchy_entity(
            session, row.target_entity_type, row.target_entity_id
        )
        target_name = getattr(entity, "name", None)
    except InventoryReservationError:
        target_name = None
    return {
        "id": row.id,
        "project_id": row.project_id,
        "project_name": row.project.name if row.project else None,
        "flight_id": row.flight_id,
        "flight_code": row.flight.code if row.flight else None,
        "flight_name": row.flight.name if row.flight else None,
        "sdls_id": row.sdls_id,
        "sdls_code": row.sdls.code if row.sdls else None,
        "sdls_name": row.sdls.name if row.sdls else None,
        "target_entity_type": row.target_entity_type,
        "target_entity_id": row.target_entity_id,
        "target_entity_name": target_name,
        "assigned_developer_id": row.assigned_developer_id,
        "assigned_developer_name": _user_display(developer),
        "requested_by_user_id": row.requested_by_user_id,
        "requested_by_name": _user_display(requester),
        "inventory_id": row.inventory_id,
        "inventory_instance_id": row.inventory_instance_id,
        "inventory_name": inventory.name if inventory else None,
        "part_number": inventory.part_number if inventory else None,
        "serial_number": row.reservation.serial_number
        if row.reservation
        else (inventory.serial_number if inventory else None),
        "reservation_id": row.reservation_id,
        "status": row.status,
        "requested_at": row.requested_at,
        "issued_at": row.issued_at,
        "issued_issuance_id": row.issued_issuance_id,
        "notes": row.notes,
    }


def issuance_read_for_request(session: Session, row: InventoryItemRequest) -> Optional[dict]:
    if not row.issued_issuance_id:
        return None
    from app.models.tables import InventoryIssuance

    issuance = session.get(InventoryIssuance, row.issued_issuance_id)
    if not issuance:
        return None
    return issuance_to_dict(session, issuance)
