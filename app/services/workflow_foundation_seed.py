"""
Spec 00 — idempotent seed of canonical item + project workflow statuses.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session, select

from app.domain.workflow_status import (
    ITEM_STATUS_COLORS,
    ITEM_STATUS_LABELS,
    ITEM_STATUS_META,
    ITEM_STATUS_TYPE,
    PROJECT_STATUS_COLORS,
    PROJECT_STATUS_LABELS,
    PROJECT_STATUS_META,
    PROJECT_STATUS_TYPE,
    ItemStatus,
    ProjectWorkflowStatus,
)
from app.models.tables import Status


def sync_status_id_sequence(session: Session) -> None:
    """
    Align PostgreSQL serial sequence with MAX(status.id).

    Batch / manual inserts often leave the sequence behind, which causes
    UniqueViolation on status_pkey during seed inserts.
    """
    session.exec(
        text(
            "SELECT setval("
            "pg_get_serial_sequence('status', 'id'), "
            "GREATEST(COALESCE((SELECT MAX(id) FROM status), 1), 1)"
            ")"
        )
    )


def ensure_workflow_statuses(session: Session) -> dict[str, int]:
    """
    Upsert Spec 00 status rows by (status_name, status_type).

    Does not delete or rename legacy statuses (Initiation, In Stock, …).
    Returns counts: {"created": n, "updated": m, "unchanged": k}.
    """
    created = updated = unchanged = 0

    rows: list[tuple[str, str, str, str]] = []
    for status in ItemStatus:
        rows.append(
            (
                status.value,
                ITEM_STATUS_TYPE,
                ITEM_STATUS_META[status],
                ITEM_STATUS_COLORS[status],
            )
        )
    for status in ProjectWorkflowStatus:
        rows.append(
            (
                status.value,
                PROJECT_STATUS_TYPE,
                PROJECT_STATUS_META[status],
                PROJECT_STATUS_COLORS[status],
            )
        )

    # Avoid Query-invoked autoflush of pending inserts mid-loop
    with session.no_autoflush:
        existing_rows = session.exec(select(Status)).all()

    by_key = {
        (s.status_name, s.status_type or ""): s for s in existing_rows
    }

    to_create: list[Status] = []
    for status_name, status_type, description, color in rows:
        key = (status_name, status_type)
        existing = by_key.get(key)
        if existing is None:
            to_create.append(
                Status(
                    status_name=status_name,
                    status_type=status_type,
                    description=description,
                    color=color,
                )
            )
            created += 1
            continue

        dirty = False
        if (existing.description or "") != description:
            existing.description = description
            dirty = True
        if (existing.color or "") != color:
            existing.color = color
            dirty = True
        if dirty:
            session.add(existing)
            updated += 1
        else:
            unchanged += 1

    if to_create:
        # Sequence may lag after manual / batch status imports
        sync_status_id_sequence(session)
        for row in to_create:
            session.add(row)

    session.commit()
    if to_create:
        sync_status_id_sequence(session)
        session.commit()

    return {"created": created, "updated": updated, "unchanged": unchanged}
