"""Add sibling group columns on hierarchy config nodes."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g8a9b0c1d2"
down_revision: Union[str, None] = "f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "hierarchyconfignode" not in tables:
        return
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("hierarchyconfignode")
    }
    if "sibling_group_id" not in columns:
        op.add_column(
            "hierarchyconfignode",
            sa.Column("sibling_group_id", sa.String(length=64), nullable=True),
        )
        op.create_index(
            "ix_hierarchyconfignode_sibling_group_id",
            "hierarchyconfignode",
            ["sibling_group_id"],
        )
    if "sibling_group_name" not in columns:
        op.add_column(
            "hierarchyconfignode",
            sa.Column("sibling_group_name", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "hierarchyconfignode" not in tables:
        return
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("hierarchyconfignode")
    }
    if "sibling_group_name" in columns:
        op.drop_column("hierarchyconfignode", "sibling_group_name")
    if "sibling_group_id" in columns:
        op.drop_index(
            "ix_hierarchyconfignode_sibling_group_id",
            table_name="hierarchyconfignode",
        )
        op.drop_column("hierarchyconfignode", "sibling_group_id")
