"""Add inventory_child_link for in-stock parent-child composition

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-07-09 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'inventorychildlink' in inspector.get_table_names():
        cols = {col['name'] for col in inspector.get_columns('inventorychildlink')}
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
        return

    op.create_table(
        'inventorychildlink',
        sa.Column('child_category_name', sa.String(), nullable=False),
        sa.Column('child_inventory_id', sa.Integer(), nullable=False),
        sa.Column('child_instance_id', sa.Integer(), nullable=True),
        sa.Column('parent_instance_serial', sa.String(), nullable=True),
        sa.Column('child_instance_serial', sa.String(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('parent_inventory_id', sa.Integer(), nullable=False),
        sa.Column('parent_instance_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['child_instance_id'], ['inventoryinstance.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['child_inventory_id'], ['inventory.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_instance_id'], ['inventoryinstance.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['parent_inventory_id'], ['inventory.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_inventorychildlink_parent_inventory_id'),
        'inventorychildlink',
        ['parent_inventory_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_inventorychildlink_parent_instance_id'),
        'inventorychildlink',
        ['parent_instance_id'],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'inventorychildlink' not in inspector.get_table_names():
        return
    op.drop_index(op.f('ix_inventorychildlink_parent_instance_id'), table_name='inventorychildlink')
    op.drop_index(op.f('ix_inventorychildlink_parent_inventory_id'), table_name='inventorychildlink')
    op.drop_table('inventorychildlink')
