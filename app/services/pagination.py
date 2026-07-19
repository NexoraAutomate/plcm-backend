from typing import Callable, List, TypeVar

from fastapi import Response
from sqlalchemy import func, inspect
from sqlalchemy.orm import selectinload
from sqlmodel import Session, SQLModel, select

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
) -> List[R]:
    """Return a page of rows and optionally set X-Total-Count on the response.

    Always orders by primary key ascending so updates do not reshuffle list
    positions (PostgreSQL has no guaranteed order without ORDER BY).
    """
    if include_total:
        count_stmt = select(func.count()).select_from(model)
        if where is not None:
            count_stmt = count_stmt.where(where)
        total = session.exec(count_stmt).one()
        set_list_total_header(response, total)

    stmt = select(model).offset(skip).limit(limit)
    if where is not None:
        stmt = stmt.where(where)

    # Stable list order: updated rows must keep their original position.
    pk_cols = list(inspect(model).primary_key)
    if pk_cols:
        stmt = stmt.order_by(*pk_cols)

    status_loader = _eager_load_status(model)
    if status_loader is not None:
        stmt = stmt.options(status_loader)

    rows = session.exec(stmt).all()
    if transform is None:
        return rows  # type: ignore[return-value]
    return [transform(row) for row in rows]
