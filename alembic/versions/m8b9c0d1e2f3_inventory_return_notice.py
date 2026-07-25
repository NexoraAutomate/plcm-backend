"""Create inventoryreturnnotice table

Revision ID: m8b9c0d1e2f3
Revises: l7a8b9c0d1e2
Create Date: 2026-07-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "l7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventoryreturnnotice" in inspector.get_table_names():
        return

    op.create_table(
        "inventoryreturnnotice",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "issuance_id",
            sa.Integer(),
            sa.ForeignKey("inventoryissuance.id"),
            nullable=False,
        ),
        sa.Column("inventory_id", sa.Integer(), sa.ForeignKey("inventory.id"), nullable=True),
        sa.Column("inventory_name", sa.String(), nullable=True),
        sa.Column("part_number", sa.String(), nullable=True),
        sa.Column("serial_number", sa.String(), nullable=True),
        sa.Column(
            "returned_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id"),
            nullable=False,
        ),
        sa.Column("returned_by_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_inventoryreturnnotice_issuance_id",
        "inventoryreturnnotice",
        ["issuance_id"],
    )
    op.create_index(
        "ix_inventoryreturnnotice_inventory_id",
        "inventoryreturnnotice",
        ["inventory_id"],
    )
    op.create_index(
        "ix_inventoryreturnnotice_returned_by_user_id",
        "inventoryreturnnotice",
        ["returned_by_user_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventoryreturnnotice" not in inspector.get_table_names():
        return
    op.drop_index(
        "ix_inventoryreturnnotice_returned_by_user_id",
        table_name="inventoryreturnnotice",
    )
    op.drop_index("ix_inventoryreturnnotice_inventory_id", table_name="inventoryreturnnotice")
    op.drop_index("ix_inventoryreturnnotice_issuance_id", table_name="inventoryreturnnotice")
    op.drop_table("inventoryreturnnotice")
