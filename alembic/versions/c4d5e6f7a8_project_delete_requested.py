"""Add delete_requested fields to project."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8"
down_revision: Union[str, None] = "b3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("project")
    }
    if "delete_requested_at" not in existing_columns:
        op.add_column(
            "project",
            sa.Column("delete_requested_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "delete_requested_by_id" not in existing_columns:
        op.add_column(
            "project",
            sa.Column("delete_requested_by_id", sa.Integer(), nullable=True),
        )
        op.create_index(
            "ix_project_delete_requested_by_id",
            "project",
            ["delete_requested_by_id"],
            unique=False,
        )
        op.create_foreign_key(
            "fk_project_delete_requested_by_id_user",
            "project",
            "user",
            ["delete_requested_by_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("project")
    }
    if "delete_requested_by_id" in existing_columns:
        op.drop_constraint(
            "fk_project_delete_requested_by_id_user", "project", type_="foreignkey"
        )
        op.drop_index("ix_project_delete_requested_by_id", table_name="project")
        op.drop_column("project", "delete_requested_by_id")
    if "delete_requested_at" in existing_columns:
        op.drop_column("project", "delete_requested_at")
