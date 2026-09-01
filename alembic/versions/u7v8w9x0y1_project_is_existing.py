"""Add is_existing_project flag to projects."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "u7v8w9x0y1"
down_revision: Union[str, None] = "t6u7v8w9x0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("project")
    }
    if "is_existing_project" not in existing_columns:
        op.add_column(
            "project",
            sa.Column(
                "is_existing_project",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("project")
    }
    if "is_existing_project" in existing_columns:
        op.drop_column("project", "is_existing_project")
