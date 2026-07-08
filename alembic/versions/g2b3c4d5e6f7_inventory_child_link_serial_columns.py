"""Add serial columns to inventorychildlink

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-09 01:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
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

    if 'parent_instance_serial' not in cols:
        op.add_column(
            'inventorychildlink',
            sa.Column('parent_instance_serial', sa.String(), nullable=True),
        )

    if 'child_instance_serial' not in cols:
        op.add_column(
            'inventorychildlink',
            sa.Column('child_instance_serial', sa.String(), nullable=True),
        )


def downgrade() -> None:
    cols = _column_names('inventorychildlink')
    if not cols:
        return

    if 'child_instance_serial' in cols:
        op.drop_column('inventorychildlink', 'child_instance_serial')

    if 'parent_instance_serial' in cols:
        op.drop_column('inventorychildlink', 'parent_instance_serial')
