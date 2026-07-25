"""Ensure newly added columns exist when create_all cannot alter tables."""

from __future__ import annotations

from sqlalchemy import text

from app.database import engine


USER_COLUMN_DDL = [
    ("updated_at", "TIMESTAMP WITH TIME ZONE"),
    ("last_login_at", "TIMESTAMP WITH TIME ZONE"),
    ("last_logout_at", "TIMESTAMP WITH TIME ZONE"),
    ("last_activity_at", "TIMESTAMP WITH TIME ZONE"),
    ("failed_login_count", "INTEGER DEFAULT 0 NOT NULL"),
    ("locked_until", "TIMESTAMP WITH TIME ZONE"),
    ("created_by_id", "INTEGER"),
]

ISSUANCE_COLUMN_DDL = [
    ("return_requested_at", "TIMESTAMP WITH TIME ZONE"),
]

RETURN_NOTICE_COLUMN_DDL = [
    ("decision", "VARCHAR DEFAULT 'pending'"),
    ("decided_at", "TIMESTAMP WITH TIME ZONE"),
    ("decided_by_id", "INTEGER"),
    ("decision_notes", "VARCHAR"),
]


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table AND column_name = :column
            LIMIT 1
            """
        ),
        {"table": table, "column": column},
    ).first()
    return row is not None


def _add_columns_if_missing(table: str, columns: list[tuple[str, str]]) -> None:
    with engine.begin() as conn:
        for name, ddl in columns:
            conn.execute(
                text(
                    f"""
                    ALTER TABLE {table}
                    ADD COLUMN IF NOT EXISTS {name} {ddl}
                    """
                )
            )


def ensure_user_management_schema() -> None:
    """Idempotent column bootstrap for environments that skip Alembic."""
    _add_columns_if_missing('"user"', USER_COLUMN_DDL)
    _add_columns_if_missing("inventoryissuance", ISSUANCE_COLUMN_DDL)

    with engine.begin() as conn:
        had_decision = _column_exists(conn, "inventoryreturnnotice", "decision")
        for name, ddl in RETURN_NOTICE_COLUMN_DDL:
            conn.execute(
                text(
                    f"""
                    ALTER TABLE inventoryreturnnotice
                    ADD COLUMN IF NOT EXISTS {name} {ddl}
                    """
                )
            )
        # First-time add: existing notices are already finalized returns.
        if not had_decision:
            conn.execute(
                text(
                    """
                    UPDATE inventoryreturnnotice
                    SET decision = 'accepted'
                    WHERE decision IS NULL OR decision = 'pending'
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    UPDATE inventoryreturnnotice
                    SET decision = 'accepted'
                    WHERE decision IS NULL
                    """
                )
            )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_inventoryreturnnotice_decision
                ON inventoryreturnnotice (decision)
                """
            )
        )
