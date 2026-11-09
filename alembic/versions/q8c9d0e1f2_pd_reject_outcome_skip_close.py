"""PD reject outcome + case workflow skip-to-closed fields."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "p7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if table not in tables:
        return
    columns = {c["name"] for c in sa.inspect(bind).get_columns(table)}
    if column.name not in columns:
        op.add_column(table, column)


def _drop_column_if_exists(table: str, name: str) -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if table not in tables:
        return
    columns = {c["name"] for c in sa.inspect(bind).get_columns(table)}
    if name in columns:
        op.drop_column(table, name)


def upgrade() -> None:
    _add_column_if_missing(
        "replacement_request",
        sa.Column("reject_outcome", sa.String(length=32), nullable=True),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column(
            "workflow_skip_to_closed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("workflow_skip_from_status", sa.String(length=48), nullable=True),
    )


def downgrade() -> None:
    _drop_column_if_exists("maintenance_case", "workflow_skip_from_status")
    _drop_column_if_exists("maintenance_case", "workflow_skip_to_closed")
    _drop_column_if_exists("replacement_request", "reject_outcome")
