"""Ensure newly added User columns exist when create_all cannot alter tables."""

from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session

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


def ensure_user_management_schema() -> None:
    """Idempotent column bootstrap for environments that skip Alembic."""
    with engine.begin() as conn:
        for name, ddl in USER_COLUMN_DDL:
            conn.execute(
                text(
                    f"""
                    ALTER TABLE "user"
                    ADD COLUMN IF NOT EXISTS {name} {ddl}
                    """
                )
            )
