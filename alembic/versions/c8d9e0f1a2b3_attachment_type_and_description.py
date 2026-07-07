"""Add attachment type and description to entity_attachment

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ATTACHMENT_TYPE = sa.Enum(
    'test_report',
    'datasheet',
    'manual',
    'certificate',
    'drawing',
    'photo',
    'warranty',
    'invoice',
    'installation_guide',
    'other',
    name='attachmenttype',
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'entity_attachment' not in inspector.get_table_names():
        return

    columns = {col['name'] for col in inspector.get_columns('entity_attachment')}
    if 'attachment_type' not in columns:
        _ATTACHMENT_TYPE.create(bind, checkfirst=True)
        op.add_column(
            'entity_attachment',
            sa.Column(
                'attachment_type',
                _ATTACHMENT_TYPE,
                nullable=False,
                server_default=sa.text("'other'::attachmenttype"),
            ),
        )
    if 'description' not in columns:
        op.add_column(
            'entity_attachment',
            sa.Column('description', sa.String(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'entity_attachment' not in inspector.get_table_names():
        return

    columns = {col['name'] for col in inspector.get_columns('entity_attachment')}
    if 'description' in columns:
        op.drop_column('entity_attachment', 'description')
    if 'attachment_type' in columns:
        op.drop_column('entity_attachment', 'attachment_type')
        _ATTACHMENT_TYPE.drop(bind, checkfirst=True)
