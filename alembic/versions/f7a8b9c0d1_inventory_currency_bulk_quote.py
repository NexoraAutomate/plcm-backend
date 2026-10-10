"""Add inventory currency and bulk_quote_cost columns."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1"
down_revision: Union[str, None] = "e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "inventory" not in tables:
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("inventory")}
    if "currency" not in columns:
        op.add_column(
            "inventory",
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="PKR"),
        )
        op.alter_column("inventory", "currency", server_default=None)
    if "bulk_quote_cost" not in columns:
        op.add_column(
            "inventory",
            sa.Column("bulk_quote_cost", sa.Numeric(18, 2), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "inventory" not in tables:
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("inventory")}
    if "bulk_quote_cost" in columns:
        op.drop_column("inventory", "bulk_quote_cost")
    if "currency" in columns:
        op.drop_column("inventory", "currency")
