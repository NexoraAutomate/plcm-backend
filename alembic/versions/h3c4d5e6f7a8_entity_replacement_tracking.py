"""Add entity replacement tracking fields to hardware tables

Revision ID: h3c4d5e6f7a8
Revises: g2b3c4d5e6f7
Create Date: 2026-07-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'h3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'g2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HARDWARE_TABLES = ('system', 'subsystem', 'module', 'unit', 'component')


def upgrade() -> None:
    for table in _HARDWARE_TABLES:
        op.add_column(
            table,
            sa.Column(
                'is_current_install',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('true'),
            ),
        )
        op.add_column(table, sa.Column('root_entity_id', sa.Integer(), nullable=True))
        op.add_column(table, sa.Column('replaced_entity_id', sa.Integer(), nullable=True))
        op.add_column(
            table,
            sa.Column(
                'replacement_sequence',
                sa.Integer(),
                nullable=False,
                server_default=sa.text('0'),
            ),
        )
        op.add_column(table, sa.Column('replaced_at', sa.DateTime(timezone=True), nullable=True))

    for table in _HARDWARE_TABLES:
        op.execute(
            f"""
            UPDATE {table}
            SET root_entity_id = id
            WHERE root_entity_id IS NULL
            """
        )


def downgrade() -> None:
    for table in reversed(_HARDWARE_TABLES):
        op.drop_column(table, 'replaced_at')
        op.drop_column(table, 'replacement_sequence')
        op.drop_column(table, 'replaced_entity_id')
        op.drop_column(table, 'root_entity_id')
        op.drop_column(table, 'is_current_install')
