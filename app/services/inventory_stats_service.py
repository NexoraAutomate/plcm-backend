"""Aggregate inventory KPI counts for the inventory list dashboard."""

from __future__ import annotations

from sqlmodel import Session, select

from app.auth import check_permission, is_inventory_manager
from app.models.base import IssuanceStatus, ShortageStatus
from app.models.tables import Inventory, InventoryIssuance, User
from app.services.inventory_issuance_service import (
    available_quantity,
    inventory_ids_issued_to_user,
    reserved_quantity,
)
from app.services.inventory_reservation_service import project_reserved_quantity
from app.services.inventory_shortage_service import list_shortages
from app.services.item_request_service import list_item_requests
from app.services.item_rework_service import list_rework_cases
from app.services.list_query import inventory_list_where


def _scoped_inventory_filter(session: Session, current_user: User):
    """Return SQLAlchemy where clause fragment or None for inventory managers."""
    if is_inventory_manager(current_user):
        return None
    ids = inventory_ids_issued_to_user(session, current_user.id)
    if not ids:
        return Inventory.id == -1
    return Inventory.id.in_(ids)


def _inventory_display_name(item: Inventory) -> str:
    name = (item.name or "").strip()
    if name:
        return name
    part = (item.part_number or "").strip()
    if part:
        return part
    return f"Item #{item.id}"


def _shortage_display_name(shortage) -> str:
    lru = (getattr(shortage, "lru_name", None) or "").strip()
    if lru:
        return lru
    part = (getattr(shortage, "part_number", None) or "").strip()
    if part:
        return part
    return f"Shortage #{shortage.id}"


def build_inventory_stats_summary(session: Session, current_user: User) -> dict:
    scope = _scoped_inventory_filter(session, current_user)
    items = list(
        session.exec(
            select(Inventory).where(scope) if scope is not None else select(Inventory)
        ).all()
    )

    available_units = 0
    reserved_issued_open_units = 0
    for item in items:
        available_units += available_quantity(session, item)
        reserved_issued_open_units += reserved_quantity(session, int(item.id))
        reserved_issued_open_units += project_reserved_quantity(session, int(item.id))

    out_where = inventory_list_where(scope=scope, stock="out_of_stock")
    out_stmt = select(Inventory).where(out_where).order_by(Inventory.name).limit(3)
    out_of_stock_top = [
        _inventory_display_name(row) for row in session.exec(out_stmt).all()
    ]
    out_of_stock_count = len(session.exec(select(Inventory.id).where(out_where)).all())

    shortages = list_shortages(
        session,
        statuses=[ShortageStatus.OPEN.value, ShortageStatus.PARTIAL.value],
    )
    open_shortage_top = [_shortage_display_name(row) for row in shortages[:3]]

    pending_issue_requests = 0
    if (
        check_permission(current_user, "inventory.issue")
        or check_permission(current_user, "issue_inventory")
        or check_permission(current_user, "item.request")
    ):
        pending_issue_requests = len(
            list_item_requests(session, actor=current_user, status="pending")
        )

    return_pending_count = 0
    if check_permission(current_user, "view_inventory_issuances"):
        return_stmt = select(InventoryIssuance).where(
            InventoryIssuance.status == IssuanceStatus.RETURN_PENDING.value
        )
        if not is_inventory_manager(current_user):
            return_stmt = return_stmt.where(
                InventoryIssuance.issued_to_user_id == int(current_user.id)
            )
        return_pending_count = len(session.exec(return_stmt).all())

    inspect_count = 0
    if check_permission(current_user, "item.inspect"):
        inspect_count = len(list_rework_cases(session))

    return {
        "total_catalog_items": len(items),
        "available_units": available_units,
        "reserved_issued_open_units": reserved_issued_open_units,
        "out_of_stock_catalog_items": out_of_stock_count,
        "out_of_stock_top_names": out_of_stock_top,
        "open_shortages": len(shortages),
        "open_shortage_top_names": open_shortage_top,
        "pending_issue_requests": pending_issue_requests,
        "return_pending_inspect": return_pending_count + inspect_count,
    }
