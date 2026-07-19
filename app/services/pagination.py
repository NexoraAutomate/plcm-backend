from typing import Callable, List, TypeVar

from fastapi import Response
from sqlalchemy import func, inspect
from sqlalchemy.orm import selectinload
from sqlmodel import Session, SQLModel, select

from app.services.sorting import apply_sort

T = TypeVar("T", bound=SQLModel)
R = TypeVar("R")


def set_list_total_header(response: Response, total: int) -> None:
    response.headers["X-Total-Count"] = str(total)
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"


def _eager_load_status(model: type[T]):
    """Batch-load status relationship when present (avoids N+1 per row)."""
    mapper = inspect(model)
    if mapper is not None and "status" in mapper.relationships:
        return selectinload(getattr(model, "status"))
    return None


def paginated_query(
    session: Session,
    model: type[T],
    skip: int,
    limit: int,
    response: Response,
    *,
    where=None,
    transform: Callable[[T], R] | None = None,
    include_total: bool = True,
    sort_by: str | None = None,
    sort_order: str | None = None,
    allowed_sort_fields: set[str] | None = None,
) -> List[R]:
    """Return a page of rows and optionally set X-Total-Count on the response.

    Sorting is applied before offset/limit. When sort_by is missing or invalid,
    rows are ordered by primary key ascending so updates do not reshuffle list
    positions (PostgreSQL has no guaranteed order without ORDER BY).
    """
    if include_total:
        count_stmt = select(func.count()).select_from(model)
        if where is not None:
            count_stmt = count_stmt.where(where)
        total = session.exec(count_stmt).one()
        set_list_total_header(response, total)

    stmt = select(model)
    if where is not None:
        stmt = stmt.where(where)

    stmt = apply_sort(
        stmt,
        model,
        sort_by=sort_by,
        sort_order=sort_order,
        allowed_fields=allowed_sort_fields,
    )

    stmt = stmt.offset(skip).limit(limit)

    status_loader = _eager_load_status(model)
    if status_loader is not None:
        stmt = stmt.options(status_loader)

    rows = session.exec(stmt).all()
    if transform is None:
        return rows  # type: ignore[return-value]
    return [transform(row) for row in rows]
