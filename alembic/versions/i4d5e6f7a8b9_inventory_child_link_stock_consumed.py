"""Mark inventory child links as consumed from stock at compose time

Revision ID: i4d5e6f7a8b9
Revises: h3c4d5e6f7a8
Create Date: 2026-07-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'i4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'h3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {col['name'] for col in inspector.get_columns(table)}


def upgrade() -> None:
    cols = _column_names('inventorychildlink')
    if not cols:
        return

    if 'stock_consumed' not in cols:
        op.add_column(
            'inventorychildlink',
            sa.Column(
                'stock_consumed',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('false'),
            ),
        )


def downgrade() -> None:
    cols = _column_names('inventorychildlink')
    if not cols:
        return

    if 'stock_consumed' in cols:
        op.drop_column('inventorychildlink', 'stock_consumed')
