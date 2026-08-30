"""Store an independent SDLS count for each project flight."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "s5t6u7v8w9"
down_revision: Union[str, None] = "r3s4t5u6v7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("project")
    }
    if "sdls_counts_by_flight" not in existing_columns:
        op.add_column(
            "project",
            sa.Column("sdls_counts_by_flight", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("project")
    }
    if "sdls_counts_by_flight" in existing_columns:
        op.drop_column("project", "sdls_counts_by_flight")
