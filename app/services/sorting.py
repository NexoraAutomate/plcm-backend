"""Reusable server-side sorting for list queries.

Apply sorting at the SQL level before pagination. Invalid sort_by values are
ignored so callers can fall back to their default order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence, TypeVar

from sqlalchemy import String, Text, func, inspect
from sqlalchemy.sql.elements import UnaryExpression
from sqlmodel import SQLModel

T = TypeVar("T", bound=SQLModel)

SortOrder = Literal["asc", "desc"]


@dataclass(frozen=True)
class SortSpec:
    """Single-column sort. Designed so a list of SortSpec can support multi-column later."""

    field: str
    order: SortOrder = "asc"


def normalize_sort_order(sort_order: str | None) -> SortOrder | None:
    if sort_order is None:
        return None
    normalized = sort_order.strip().lower()
    if normalized in ("asc", "desc"):
        return normalized  # type: ignore[return-value]
    return None


def _is_string_column(column) -> bool:
    try:
        col_type = column.type
        return isinstance(col_type, (String, Text))
    except Exception:
        return False


def _model_columns(model: type[T]) -> dict:
    mapper = inspect(model)
    if mapper is None:
        return {}
    return {col.key: getattr(model, col.key) for col in mapper.columns}


def _build_order_expr(column, order: SortOrder) -> UnaryExpression:
    if _is_string_column(column):
        expr = func.lower(column)
    else:
        expr = column

    ordered = expr.asc() if order == "asc" else expr.desc()
    return ordered.nulls_last()


def resolve_sort_spec(
    sort_by: str | None,
    sort_order: str | None,
    *,
    allowed_fields: set[str] | None = None,
) -> SortSpec | None:
    """Validate and normalize a single sort request. Returns None if invalid/empty."""
    if not sort_by or not str(sort_by).strip():
        return None
    field = str(sort_by).strip()
    if allowed_fields is not None and field not in allowed_fields:
        return None
    order = normalize_sort_order(sort_order) or "asc"
    return SortSpec(field=field, order=order)


def apply_sort(
    stmt,
    model: type[T],
    sort_by: str | None = None,
    sort_order: str | None = None,
    *,
    allowed_fields: set[str] | None = None,
    default_order: Sequence | None = None,
):
    """Apply ORDER BY for sort_by/sort_order, or default_order / PK when unset.

    - Invalid sort_by is ignored (falls through to default).
    - String columns use case-insensitive lower().
    - Nulls sort last for both directions.
    - Primary key columns are always appended as a stable tie-breaker.
    """
    columns = _model_columns(model)
    pk_cols = list(inspect(model).primary_key) if inspect(model) is not None else []

    effective_allowed = allowed_fields
    if effective_allowed is None:
        effective_allowed = set(columns.keys())

    spec = resolve_sort_spec(sort_by, sort_order, allowed_fields=effective_allowed)

    order_exprs: list = []
    if spec is not None and spec.field in columns:
        order_exprs.append(_build_order_expr(columns[spec.field], spec.order))
        # Stable tie-breaker: append PKs not already the primary sort column.
        for pk in pk_cols:
            if getattr(pk, "key", None) != spec.field:
                order_exprs.append(pk)
    elif default_order:
        order_exprs.extend(list(default_order))
    elif pk_cols:
        order_exprs.extend(pk_cols)

    if order_exprs:
        stmt = stmt.order_by(*order_exprs)
    return stmt


def parse_sort_query(
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Normalize FastAPI query params for passing into apply_sort / paginated_query."""
    if not sort_by or not str(sort_by).strip():
        return None, None
    order = normalize_sort_order(sort_order)
    return str(sort_by).strip(), order
