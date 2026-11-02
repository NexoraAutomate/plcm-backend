"""Add hierarchy_config_ids_by_flight on project (merge heads)."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = ("i0a1b2c3d4", "i0c1d2e3f4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "project" not in tables:
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("project")}
    if "hierarchy_config_ids_by_flight" not in columns:
        op.add_column(
            "project",
            sa.Column("hierarchy_config_ids_by_flight", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "project" not in tables:
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("project")}
    if "hierarchy_config_ids_by_flight" in columns:
        op.drop_column("project", "hierarchy_config_ids_by_flight")
