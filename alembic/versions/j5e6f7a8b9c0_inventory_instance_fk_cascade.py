"""Ensure inventoryinstance.inventory_id cascades on delete

Revision ID: j5e6f7a8b9c0
Revises: i4d5e6f7a8b9
Create Date: 2026-07-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "i4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _fk_name(inspector: sa.Inspector, table: str, column: str) -> str | None:
    for fk in inspector.get_foreign_keys(table):
        if column in (fk.get("constrained_columns") or []):
            return fk.get("name")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventoryinstance" not in inspector.get_table_names():
        return

    fk_name = _fk_name(inspector, "inventoryinstance", "inventory_id")
    if not fk_name:
        return

    op.drop_constraint(fk_name, "inventoryinstance", type_="foreignkey")
    op.create_foreign_key(
        fk_name,
        "inventoryinstance",
        "inventory",
        ["inventory_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventoryinstance" not in inspector.get_table_names():
        return

    fk_name = _fk_name(inspector, "inventoryinstance", "inventory_id")
    if not fk_name:
        return

    op.drop_constraint(fk_name, "inventoryinstance", type_="foreignkey")
    op.create_foreign_key(
        fk_name,
        "inventoryinstance",
        "inventory",
        ["inventory_id"],
        ["id"],
    )
