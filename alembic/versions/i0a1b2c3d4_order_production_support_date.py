"""Add production_support_date on order."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i0a1b2c3d4"
down_revision: Union[str, None] = "h9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "order" in tables:
        columns = {column["name"] for column in sa.inspect(bind).get_columns("order")}
        if "production_support_date" not in columns:
            op.add_column(
                "order",
                sa.Column("production_support_date", sa.Date(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "order" in tables:
        columns = {column["name"] for column in sa.inspect(bind).get_columns("order")}
        if "production_support_date" in columns:
            op.drop_column("order", "production_support_date")
