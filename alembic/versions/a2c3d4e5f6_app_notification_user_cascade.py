"""Cascade AppNotification rows when a user is deleted.

Revision ID: a2c3d4e5f6
Revises: z1a2b3c4d5
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "a2c3d4e5f6"
down_revision: Union[str, None] = "z1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _fk_names(inspector: sa.Inspector, table: str, column: str) -> list[str]:
    names: list[str] = []
    for fk in inspector.get_foreign_keys(table):
        if column in (fk.get("constrained_columns") or []) and fk.get("name"):
            names.append(fk["name"])
    return names


def upgrade() -> None:
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "appnotification" not in inspector.get_table_names():
        return
    user_fks = _fk_names(inspector, "appnotification", "user_id")
    actor_fks = _fk_names(inspector, "appnotification", "actor_user_id")
    for name in user_fks + actor_fks:
        op.drop_constraint(name, "appnotification", type_="foreignkey")
    op.create_foreign_key(
        "appnotification_user_id_fkey",
        "appnotification",
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "appnotification_actor_user_id_fkey",
        "appnotification",
        "user",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "appnotification" not in inspector.get_table_names():
        return
    for name in _fk_names(inspector, "appnotification", "user_id"):
        op.drop_constraint(name, "appnotification", type_="foreignkey")
    for name in _fk_names(inspector, "appnotification", "actor_user_id"):
        op.drop_constraint(name, "appnotification", type_="foreignkey")
    op.create_foreign_key(
        "appnotification_user_id_fkey",
        "appnotification",
        "user",
        ["user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "appnotification_actor_user_id_fkey",
        "appnotification",
        "user",
        ["actor_user_id"],
        ["id"],
    )
