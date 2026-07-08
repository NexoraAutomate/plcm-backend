from sqlalchemy import func, text
from sqlmodel import Session, select

from app.models.tables import Hierarchy


def get_next_hierarchy_id(session: Session) -> int:
    """Return max(hierarchy.id) + 1 so new rows never collide with existing keys."""
    max_id = session.exec(select(func.max(Hierarchy.id))).one()
    return (max_id or 0) + 1


def sync_hierarchy_id_sequence(session: Session) -> None:
    """Keep the PostgreSQL serial sequence aligned with the highest hierarchy id."""
    session.exec(
        text(
            "SELECT setval("
            "pg_get_serial_sequence('hierarchy', 'id'), "
            "COALESCE((SELECT MAX(id) FROM hierarchy), 1), "
            "true"
            ")"
        )
    )


def create_hierarchy_entry(session: Session, entry_data: dict) -> Hierarchy:
    db_entry = Hierarchy(**entry_data)
    db_entry.id = get_next_hierarchy_id(session)
    session.add(db_entry)
    session.flush()
    sync_hierarchy_id_sequence(session)
    return db_entry
