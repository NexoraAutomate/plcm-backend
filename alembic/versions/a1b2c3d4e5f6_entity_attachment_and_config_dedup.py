"""Entity attachment table and configuration history dedup

Revision ID: a1b2c3d4e5f6
Revises: 5e5e498ecb5c
Create Date: 2026-06-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '5e5e498ecb5c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'entity_attachment' not in inspector.get_table_names():
        op.create_table(
            'entity_attachment',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('owner_type', sa.String(), nullable=False),
            sa.Column('owner_id', sa.Integer(), nullable=False),
            sa.Column('file_name', sa.String(), nullable=False),
            sa.Column('file_path', sa.String(), nullable=False),
            sa.Column('mime_type', sa.String(), nullable=True),
            sa.Column('uploaded_by_id', sa.Integer(), nullable=True),
            sa.Column(
                'uploaded_at',
                sa.DateTime(timezone=True),
                server_default=sa.text('now()'),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(['uploaded_by_id'], ['user.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_entity_attachment_owner',
            'entity_attachment',
            ['owner_type', 'owner_id'],
        )

    op.execute(
        """
        DELETE FROM configuration_history a
        USING configuration_history b
        WHERE a.id > b.id
          AND a.maintenance_case_id IS NOT DISTINCT FROM b.maintenance_case_id
          AND a.entity_id = b.entity_id
          AND a.resolution_type = b.resolution_type
          AND COALESCE(a.old_part_number, '') = COALESCE(b.old_part_number, '')
          AND COALESCE(a.new_part_number, '') = COALESCE(b.new_part_number, '')
          AND date_trunc('minute', a.change_date) = date_trunc('minute', b.change_date)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'entity_attachment' in inspector.get_table_names():
        op.drop_index('ix_entity_attachment_owner', table_name='entity_attachment')
        op.drop_table('entity_attachment')
