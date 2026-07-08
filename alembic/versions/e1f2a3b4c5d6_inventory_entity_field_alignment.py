"""Align inventory fields with hierarchy entities

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-07-08 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd9e0f1a2b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col['name'] for col in inspector.get_columns(table)}


def upgrade() -> None:
    inventory_cols = _column_names('inventory')

    if 'manufacturer_part_number' in inventory_cols and 'part_number' not in inventory_cols:
        op.alter_column('inventory', 'manufacturer_part_number', new_column_name='part_number')
        inventory_cols.remove('manufacturer_part_number')
        inventory_cols.add('part_number')

    if 'part_number' not in inventory_cols:
        op.add_column('inventory', sa.Column('part_number', sa.String(), nullable=True))

    if 'configuration_item' not in inventory_cols:
        op.add_column('inventory', sa.Column('configuration_item', sa.String(), nullable=True))

    if 'status_id' not in inventory_cols:
        op.add_column('inventory', sa.Column('status_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            'fk_inventory_status_id',
            'inventory',
            'status',
            ['status_id'],
            ['id'],
        )

    if 'sku' not in inventory_cols:
        op.add_column('inventory', sa.Column('sku', sa.String(), nullable=True))

    if 'installation_date' not in inventory_cols:
        op.add_column('inventory', sa.Column('installation_date', sa.DateTime(), nullable=True))

    if 'installed_by_id' not in inventory_cols:
        op.add_column('inventory', sa.Column('installed_by_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            'fk_inventory_installed_by_id',
            'inventory',
            'user',
            ['installed_by_id'],
            ['id'],
        )

    if 'original_part_number' not in inventory_cols:
        op.add_column('inventory', sa.Column('original_part_number', sa.String(), nullable=True))

    if 'original_serial_number' not in inventory_cols:
        op.add_column('inventory', sa.Column('original_serial_number', sa.String(), nullable=True))

    op.execute(
        """
        UPDATE inventory
        SET configuration_item = COALESCE(NULLIF(configuration_item, ''), part_number, name)
        WHERE configuration_item IS NULL OR configuration_item = ''
        """
    )

    instance_cols = _column_names('inventoryinstance')

    if 'configuration_item' not in instance_cols:
        op.add_column('inventoryinstance', sa.Column('configuration_item', sa.String(), nullable=True))

    if 'status_id' not in instance_cols:
        op.add_column('inventoryinstance', sa.Column('status_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            'fk_inventoryinstance_status_id',
            'inventoryinstance',
            'status',
            ['status_id'],
            ['id'],
        )

    if 'installation_date' not in instance_cols:
        op.add_column('inventoryinstance', sa.Column('installation_date', sa.DateTime(), nullable=True))

    if 'installed_by_id' not in instance_cols:
        op.add_column('inventoryinstance', sa.Column('installed_by_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            'fk_inventoryinstance_installed_by_id',
            'inventoryinstance',
            'user',
            ['installed_by_id'],
            ['id'],
        )

    if 'original_part_number' not in instance_cols:
        op.add_column('inventoryinstance', sa.Column('original_part_number', sa.String(), nullable=True))

    if 'original_serial_number' not in instance_cols:
        op.add_column('inventoryinstance', sa.Column('original_serial_number', sa.String(), nullable=True))


def downgrade() -> None:
    instance_cols = _column_names('inventoryinstance')

    if 'original_serial_number' in instance_cols:
        op.drop_column('inventoryinstance', 'original_serial_number')
    if 'original_part_number' in instance_cols:
        op.drop_column('inventoryinstance', 'original_part_number')
    if 'installed_by_id' in instance_cols:
        op.drop_constraint('fk_inventoryinstance_installed_by_id', 'inventoryinstance', type_='foreignkey')
        op.drop_column('inventoryinstance', 'installed_by_id')
    if 'installation_date' in instance_cols:
        op.drop_column('inventoryinstance', 'installation_date')
    if 'status_id' in instance_cols:
        op.drop_constraint('fk_inventoryinstance_status_id', 'inventoryinstance', type_='foreignkey')
        op.drop_column('inventoryinstance', 'status_id')
    if 'configuration_item' in instance_cols:
        op.drop_column('inventoryinstance', 'configuration_item')

    inventory_cols = _column_names('inventory')

    if 'original_serial_number' in inventory_cols:
        op.drop_column('inventory', 'original_serial_number')
    if 'original_part_number' in inventory_cols:
        op.drop_column('inventory', 'original_part_number')
    if 'installed_by_id' in inventory_cols:
        op.drop_constraint('fk_inventory_installed_by_id', 'inventory', type_='foreignkey')
        op.drop_column('inventory', 'installed_by_id')
    if 'installation_date' in inventory_cols:
        op.drop_column('inventory', 'installation_date')
    if 'sku' in inventory_cols:
        op.drop_column('inventory', 'sku')
    if 'status_id' in inventory_cols:
        op.drop_constraint('fk_inventory_status_id', 'inventory', type_='foreignkey')
        op.drop_column('inventory', 'status_id')
    if 'configuration_item' in inventory_cols:
        op.drop_column('inventory', 'configuration_item')

    if 'part_number' in inventory_cols and 'manufacturer_part_number' not in inventory_cols:
        op.alter_column('inventory', 'part_number', new_column_name='manufacturer_part_number')
