"""Add unified appnotification table for Spec 14 gap events.

Revision ID: z1a2b3c4d5
Revises: y0z1a2b3c4
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "z1a2b3c4d5"
down_revision: Union[str, None] = "y0z1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        tables: set[str] = set()
    else:
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        tables = set(inspector.get_table_names())

    if "appnotification" not in tables:
        op.create_table(
            "appnotification",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("href", sa.String(length=512), nullable=False, server_default="/notifications"),
            sa.Column("priority", sa.String(length=16), nullable=False, server_default="medium"),
            sa.Column("entity_type", sa.String(length=64), nullable=True),
            sa.Column("entity_id", sa.Integer(), nullable=True),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("dedupe_key", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["actor_user_id"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_appnotification_user_id", "appnotification", ["user_id"])
        op.create_index("ix_appnotification_event_type", "appnotification", ["event_type"])
        op.create_index("ix_appnotification_created_at", "appnotification", ["created_at"])
        op.create_index("ix_appnotification_dedupe_key", "appnotification", ["dedupe_key"])


def downgrade() -> None:
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "appnotification" in tables:
        op.drop_index("ix_appnotification_dedupe_key", table_name="appnotification")
        op.drop_index("ix_appnotification_created_at", table_name="appnotification")
        op.drop_index("ix_appnotification_event_type", table_name="appnotification")
        op.drop_index("ix_appnotification_user_id", table_name="appnotification")
        op.drop_table("appnotification")
