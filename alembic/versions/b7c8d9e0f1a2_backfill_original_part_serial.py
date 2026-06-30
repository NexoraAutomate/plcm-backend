"""Backfill original part/serial from current values for legacy rows

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-06-28

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HARDWARE_TABLES = ('system', 'subsystem', 'module', 'unit', 'component')


def upgrade() -> None:
    for table in _HARDWARE_TABLES:
        op.execute(
            f"""
            UPDATE {table}
            SET original_part_number = part_number
            WHERE original_part_number IS NULL
              AND part_number IS NOT NULL
              AND TRIM(part_number) <> ''
            """
        )
        op.execute(
            f"""
            UPDATE {table}
            SET original_serial_number = serial_number
            WHERE original_serial_number IS NULL
              AND serial_number IS NOT NULL
              AND TRIM(serial_number) <> ''
            """
        )


def downgrade() -> None:
    # Data migration — no safe automatic rollback.
    pass
