"""Add inventory unit_cost and default_unit_cost columns."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9c0"
down_revision: Union[str, None] = "d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "inventory" in tables:
        inventory_columns = {
            column["name"] for column in sa.inspect(bind).get_columns("inventory")
        }
        if "default_unit_cost" not in inventory_columns:
            op.add_column(
                "inventory",
                sa.Column("default_unit_cost", sa.Numeric(18, 2), nullable=True),
            )

    if "inventoryinstance" in tables:
        instance_columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("inventoryinstance")
        }
        if "unit_cost" not in instance_columns:
            op.add_column(
                "inventoryinstance",
                sa.Column("unit_cost", sa.Numeric(18, 2), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "inventoryinstance" in tables:
        instance_columns = {
            column["name"]
            for column in sa.inspect(bind).get_columns("inventoryinstance")
        }
        if "unit_cost" in instance_columns:
            op.drop_column("inventoryinstance", "unit_cost")

    if "inventory" in tables:
        inventory_columns = {
            column["name"] for column in sa.inspect(bind).get_columns("inventory")
        }
        if "default_unit_cost" in inventory_columns:
            op.drop_column("inventory", "default_unit_cost")
