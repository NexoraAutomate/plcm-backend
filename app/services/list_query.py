"""Helpers for combining SQLAlchemy WHERE clauses on list endpoints."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import and_, or_


def combine_where(*conditions: Any) -> Any:
    """AND together non-None conditions; return None when empty."""
    parts = [c for c in conditions if c is not None]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return and_(*parts)


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
