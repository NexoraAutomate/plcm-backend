"""Create inventoryissuance ledger table

Revision ID: l7a8b9c0d1e2
Revises: k6f7a8b9c0d1
Create Date: 2026-07-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "k6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventoryissuance" in inspector.get_table_names():
        return

    op.create_table(
        "inventoryissuance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inventory_id", sa.Integer(), sa.ForeignKey("inventory.id"), nullable=False),
        sa.Column(
            "inventory_instance_id",
            sa.Integer(),
            sa.ForeignKey("inventoryinstance.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("issued_to_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("issued_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="issued"),
        sa.Column("target_entity_type", sa.String(), nullable=True),
        sa.Column("target_entity_id", sa.Integer(), nullable=True),
        sa.Column("part_number", sa.String(), nullable=True),
        sa.Column("serial_number", sa.String(), nullable=True),
        sa.Column("inventory_name", sa.String(), nullable=True),
        sa.Column("inventory_type", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("installed_entity_type", sa.String(), nullable=True),
        sa.Column("installed_entity_id", sa.Integer(), nullable=True),
        sa.Column("installed_by_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
    )
    op.create_index("ix_inventoryissuance_inventory_id", "inventoryissuance", ["inventory_id"])
    op.create_index(
        "ix_inventoryissuance_inventory_instance_id",
        "inventoryissuance",
        ["inventory_instance_id"],
    )
    op.create_index(
        "ix_inventoryissuance_issued_to_user_id",
        "inventoryissuance",
        ["issued_to_user_id"],
    )
    op.create_index(
        "ix_inventoryissuance_issued_by_user_id",
        "inventoryissuance",
        ["issued_by_user_id"],
    )
    op.create_index("ix_inventoryissuance_status", "inventoryissuance", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "inventoryissuance" not in inspector.get_table_names():
        return
    op.drop_index("ix_inventoryissuance_status", table_name="inventoryissuance")
    op.drop_index("ix_inventoryissuance_issued_by_user_id", table_name="inventoryissuance")
    op.drop_index("ix_inventoryissuance_issued_to_user_id", table_name="inventoryissuance")
    op.drop_index("ix_inventoryissuance_inventory_instance_id", table_name="inventoryissuance")
    op.drop_index("ix_inventoryissuance_inventory_id", table_name="inventoryissuance")
    op.drop_table("inventoryissuance")
