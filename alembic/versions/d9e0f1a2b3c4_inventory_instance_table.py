"""Add inventory_instance table for serialized non-component stock

Revision ID: d9e0f1a2b3c4
Revises: 7b1914e5980d
Create Date: 2026-07-08 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd9e0f1a2b3c4'
down_revision: Union[str, Sequence[str], None] = '7b1914e5980d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'inventoryinstance',
        sa.Column('serial_number', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('holder_user_id', sa.Integer(), nullable=True),
        sa.Column('location', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('added_date', sa.DateTime(), nullable=False),
        sa.Column('shelf_life_expires_at', sa.DateTime(), nullable=True),
        sa.Column('picture_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('inventory_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['holder_user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['inventory_id'], ['inventory.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_inventoryinstance_inventory_id'), 'inventoryinstance', ['inventory_id'], unique=False)

    op.execute(
        """
        INSERT INTO inventoryinstance (
            inventory_id, serial_number, holder_user_id, location,
            added_date, shelf_life_expires_at, picture_url, updated_at
        )
        SELECT
            id, serial_number, holder_user_id, location,
            added_date, shelf_life_expires_at, picture_url, updated_at
        FROM inventory
        WHERE inventory_type != 'component'
        """
    )

    op.execute(
        """
        UPDATE inventory
        SET quantity = (
            SELECT COUNT(*) FROM inventoryinstance
            WHERE inventoryinstance.inventory_id = inventory.id
        )
        WHERE inventory_type != 'component'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE inventory AS inv
        SET
            serial_number = inst.serial_number,
            holder_user_id = inst.holder_user_id,
            location = inst.location,
            added_date = inst.added_date,
            shelf_life_expires_at = inst.shelf_life_expires_at,
            picture_url = inst.picture_url,
            quantity = 1
        FROM (
            SELECT DISTINCT ON (inventory_id)
                inventory_id, serial_number, holder_user_id, location,
                added_date, shelf_life_expires_at, picture_url
            FROM inventoryinstance
            ORDER BY inventory_id, id
        ) AS inst
        WHERE inv.id = inst.inventory_id
          AND inv.inventory_type != 'component'
        """
    )
    op.drop_index(op.f('ix_inventoryinstance_inventory_id'), table_name='inventoryinstance')
    op.drop_table('inventoryinstance')
