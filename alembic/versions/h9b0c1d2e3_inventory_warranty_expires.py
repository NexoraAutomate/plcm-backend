"""Add warranty_expires_at on inventory and inventoryinstance."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h9b0c1d2e3"
down_revision: Union[str, None] = "g8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "inventory" in tables:
        columns = {column["name"] for column in sa.inspect(bind).get_columns("inventory")}
        if "warranty_expires_at" not in columns:
            op.add_column(
                "inventory",
                sa.Column("warranty_expires_at", sa.DateTime(), nullable=True),
            )

    if "inventoryinstance" in tables:
        columns = {
            column["name"] for column in sa.inspect(bind).get_columns("inventoryinstance")
        }
        if "warranty_expires_at" not in columns:
            op.add_column(
                "inventoryinstance",
                sa.Column("warranty_expires_at", sa.DateTime(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "inventoryinstance" in tables:
        columns = {
            column["name"] for column in sa.inspect(bind).get_columns("inventoryinstance")
        }
        if "warranty_expires_at" in columns:
            op.drop_column("inventoryinstance", "warranty_expires_at")

    if "inventory" in tables:
        columns = {column["name"] for column in sa.inspect(bind).get_columns("inventory")}
        if "warranty_expires_at" in columns:
            op.drop_column("inventory", "warranty_expires_at")
