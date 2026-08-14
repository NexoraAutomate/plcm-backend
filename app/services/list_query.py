"""Helpers for combining SQLAlchemy WHERE clauses on list endpoints."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import and_, func, or_
from sqlmodel import select


def combine_where(*conditions: Any) -> Any:
    """AND together non-None conditions; return None when empty."""
    parts = [c for c in conditions if c is not None]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return and_(*parts)


def text_search(model: Any, search: Optional[str], *fields: str) -> Any:
    """Case-insensitive OR match across the given model columns."""
    term = (search or "").strip()
    if not term:
        return None
    like = f"%{term}%"
    clauses: list[Any] = []
    for name in fields:
        col = getattr(model, name, None)
        if col is not None:
            clauses.append(col.ilike(like))
    if not clauses:
        return None
    return or_(*clauses) if len(clauses) > 1 else clauses[0]


def eq_if_set(model: Any, field: str, value: Any) -> Any:
    if value is None or value == "":
        return None
    col = getattr(model, field, None)
    if col is None:
        return None
    return col == value


def hierarchy_list_where(
    model: Any,
    *,
    current_install_only: bool = True,
    installed_by_id: Optional[int] = None,
    status_id: Optional[int] = None,
    project_id: Optional[int] = None,
    system_id: Optional[int] = None,
    subsystem_id: Optional[int] = None,
    module_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    search: Optional[str] = None,
) -> Any:
    """Build a where clause for hierarchy entity list endpoints."""
    conditions: list[Any] = []
    if current_install_only and hasattr(model, "is_current_install"):
        conditions.append(model.is_current_install == True)  # noqa: E712
    if installed_by_id is not None and hasattr(model, "installed_by_id"):
        conditions.append(model.installed_by_id == installed_by_id)
    if status_id is not None and hasattr(model, "status_id"):
        conditions.append(model.status_id == status_id)
    if project_id is not None and hasattr(model, "project_id"):
        conditions.append(model.project_id == project_id)
    if system_id is not None and hasattr(model, "system_id"):
        conditions.append(model.system_id == system_id)
    if subsystem_id is not None and hasattr(model, "subsystem_id"):
        conditions.append(model.subsystem_id == subsystem_id)
    if module_id is not None and hasattr(model, "module_id"):
        conditions.append(model.module_id == module_id)
    if unit_id is not None and hasattr(model, "unit_id"):
        conditions.append(model.unit_id == unit_id)
    term = (search or "").strip()
    if term and hasattr(model, "name"):
        like = f"%{term}%"
        name_clause = model.name.ilike(like)
        if hasattr(model, "serial_number") and hasattr(model, "part_number"):
            conditions.append(
                or_(
                    name_clause,
                    model.serial_number.ilike(like),
                    model.part_number.ilike(like),
                )
            )
        else:
            conditions.append(name_clause)
    return combine_where(*conditions)


def inventory_search_where(search: Optional[str]) -> Any:
    """Match catalog fields or any instance serial number."""
    from app.models.tables import Inventory, InventoryInstance

    term = (search or "").strip()
    if not term:
        return None
    like = f"%{term}%"
    instance_match = select(InventoryInstance.inventory_id).where(
        InventoryInstance.serial_number.ilike(like)
    )
    return or_(
        Inventory.name.ilike(like),
        Inventory.part_number.ilike(like),
        Inventory.serial_number.ilike(like),
        Inventory.sku.ilike(like),
        Inventory.description.ilike(like),
        Inventory.oem_name.ilike(like),
        Inventory.location.ilike(like),
        Inventory.id.in_(instance_match),
    )


def inventory_stock_where(stock: Optional[str]) -> Any:
    """Filter catalog rows by available / reserved / out_of_stock."""
    from app.models.base import InventoryReservationStatus, IssuanceStatus
    from app.models.tables import Inventory, InventoryIssuance, InventoryReservation

    kind = (stock or "").strip().lower()
    if not kind or kind == "all":
        return None

    held_issuance = (IssuanceStatus.ISSUED.value, IssuanceStatus.RETURN_PENDING.value)

    active_holds = select(InventoryReservation.inventory_id).where(
        InventoryReservation.status == InventoryReservationStatus.ACTIVE.value
    )
    if kind == "reserved":
        return Inventory.id.in_(active_holds)

    issued_qty = (
        select(func.coalesce(func.sum(InventoryIssuance.quantity), 0))
        .where(
            InventoryIssuance.inventory_id == Inventory.id,
            InventoryIssuance.status.in_(held_issuance),
        )
        .correlate(Inventory)
        .scalar_subquery()
    )
    project_held_qty = (
        select(func.count())
        .where(
            InventoryReservation.inventory_id == Inventory.id,
            InventoryReservation.status == InventoryReservationStatus.ACTIVE.value,
        )
        .correlate(Inventory)
        .scalar_subquery()
    )
    available_qty = Inventory.quantity - issued_qty - project_held_qty

    if kind == "available":
        return available_qty > 0
    if kind == "out_of_stock":
        return and_(available_qty <= 0, ~Inventory.id.in_(active_holds))
    return None


def inventory_list_where(
    *,
    scope: Any = None,
    inventory_type: Optional[str] = None,
    search: Optional[str] = None,
    stock: Optional[str] = None,
) -> Any:
    type_filter = None
    if inventory_type:
        from app.models.tables import Inventory

        type_filter = Inventory.inventory_type == inventory_type
    return combine_where(
        scope,
        type_filter,
        inventory_search_where(search),
        inventory_stock_where(stock),
    )


def maintenance_log_search_where(search: Optional[str]) -> Any:
    from app.models.tables import Entity, MaintenanceLog

    term = (search or "").strip()
    if not term:
        return None
    like = f"%{term}%"
    entity_match = select(Entity.id).where(Entity.display_name.ilike(like))
    return or_(
        MaintenanceLog.notes.ilike(like),
        MaintenanceLog.entity_id.in_(entity_match),
    )
