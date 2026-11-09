"""Normalize resolution_type rows from UPPERCASE labels to lowercase values."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "q8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MAP = (
    ("REPAIRED", "repaired"),
    ("REPLACED", "replaced"),
    ("NO_FAULT_FOUND", "no_fault_found"),
    ("DECOMMISSIONED", "decommissioned"),
    ("CLEAR", "clear"),
    ("SOFT_FIXED", "soft_fixed"),
)

_TABLES = ("faulty_entity", "configuration_history")


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table in _TABLES:
        if table not in tables:
            continue
        cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        if "resolution_type" not in cols:
            continue
        for old, new in _MAP:
            bind.execute(
                sa.text(
                    f"UPDATE {table} "
                    f"SET resolution_type = '{new}'::resolutiontype "
                    f"WHERE resolution_type::text = '{old}'"
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table in _TABLES:
        if table not in tables:
            continue
        cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        if "resolution_type" not in cols:
            continue
        for old, new in _MAP:
            bind.execute(
                sa.text(
                    f"UPDATE {table} "
                    f"SET resolution_type = '{old}'::resolutiontype "
                    f"WHERE resolution_type::text = '{new}'"
                )
            )
