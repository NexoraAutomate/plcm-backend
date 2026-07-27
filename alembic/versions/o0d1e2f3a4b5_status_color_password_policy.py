"""Add status.color and user password policy columns

Revision ID: o0d1e2f3a4b5
Revises: n9c0d1e2f3a4
Create Date: 2026-07-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "n9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "status" in inspector.get_table_names() and not _has_column(inspector, "status", "color"):
        op.add_column("status", sa.Column("color", sa.String(), nullable=True))

    if "user" in inspector.get_table_names():
        if not _has_column(inspector, "user", "password_changed_at"):
            op.add_column(
                "user",
                sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
            )
        if not _has_column(inspector, "user", "password_history"):
            op.add_column("user", sa.Column("password_history", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "status" in inspector.get_table_names() and _has_column(inspector, "status", "color"):
        op.drop_column("status", "color")
    if "user" in inspector.get_table_names():
        if _has_column(inspector, "user", "password_history"):
            op.drop_column("user", "password_history")
        if _has_column(inspector, "user", "password_changed_at"):
            op.drop_column("user", "password_changed_at")
