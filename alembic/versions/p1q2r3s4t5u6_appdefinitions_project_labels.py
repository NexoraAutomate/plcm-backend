"""Add label_project, label_projects, abbrev_project to AppDefinitions

Revision ID: p1q2r3s4t5u6
Revises: a1b2c3d4e5f6
Create Date: 2026-08-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'p1q2r3s4t5u6'
down_revision: Union[str, None] = 'o0d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c['name'] for c in inspector.get_columns('appdefinitions')}

    if 'label_project' not in existing_cols:
        op.add_column(
            'appdefinitions',
            sa.Column('label_project', sa.String(), nullable=False, server_default='Project'),
        )
    if 'label_projects' not in existing_cols:
        op.add_column(
            'appdefinitions',
            sa.Column('label_projects', sa.String(), nullable=False, server_default='Projects'),
        )
    if 'abbrev_project' not in existing_cols:
        op.add_column(
            'appdefinitions',
            sa.Column('abbrev_project', sa.String(), nullable=False, server_default='PROJ'),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c['name'] for c in inspector.get_columns('appdefinitions')}

    for col in ('label_project', 'label_projects', 'abbrev_project'):
        if col in existing_cols:
            op.drop_column('appdefinitions', col)
