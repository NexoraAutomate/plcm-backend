"""Occurrence Report P1: occurrence fields, officers, attachments."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "l3d4e5f6a7"
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


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("occurrence_date", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("occurrence_fault_type", sa.String(length=64), nullable=True),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("confirmation_channel", sa.String(length=16), nullable=True),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("confirmation_reference", sa.String(length=512), nullable=True),
    )

    if not _table_exists("maintenance_occurrence_attachment"):
        op.create_table(
            "maintenance_occurrence_attachment",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_id", sa.Integer(), sa.ForeignKey("maintenance_case.id"), nullable=False, index=True),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("file_id", sa.Integer(), sa.ForeignKey("entity_attachment.id"), nullable=True),
            sa.Column("category", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    if not _table_exists("maintenance_occurrence_officer"):
        op.create_table(
            "maintenance_occurrence_officer",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("case_id", sa.Integer(), sa.ForeignKey("maintenance_case.id"), nullable=False, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("guest_name", sa.String(length=255), nullable=True),
            sa.Column("role_onsite", sa.String(length=64), nullable=False),
            sa.Column("contact", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "maintenance_occurrence_officer" in tables:
        op.drop_table("maintenance_occurrence_officer")
    if "maintenance_occurrence_attachment" in tables:
        op.drop_table("maintenance_occurrence_attachment")
    _drop_column_if_exists("maintenance_case", "confirmation_reference")
    _drop_column_if_exists("maintenance_case", "confirmation_channel")
    _drop_column_if_exists("maintenance_case", "occurrence_fault_type")
    _drop_column_if_exists("maintenance_case", "occurrence_date")
