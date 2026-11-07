"""P3 Track A: issue/AIT fields + AIT attachment table on ReplacementRequest."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "o6a7b8c9d0"
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
        "replacement_request",
        sa.Column("issued_serial", sa.String(length=128), nullable=True),
    )
    _add_column_if_missing(
        "replacement_request",
        sa.Column(
            "issued_instance_id",
            sa.Integer(),
            sa.ForeignKey("inventoryinstance.id"),
            nullable=True,
        ),
    )
    _add_column_if_missing(
        "replacement_request",
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "replacement_request",
        sa.Column(
            "shortage_held",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    _add_column_if_missing(
        "replacement_request",
        sa.Column("red_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "replacement_request",
        sa.Column(
            "quarantined_instance_id",
            sa.Integer(),
            sa.ForeignKey("inventoryinstance.id"),
            nullable=True,
        ),
    )
    _add_column_if_missing(
        "replacement_request",
        sa.Column("ait_decision", sa.String(length=16), nullable=True),
    )
    _add_column_if_missing(
        "replacement_request",
        sa.Column("ait_reject_reason", sa.Text(), nullable=True),
    )

    if not _table_exists("replacement_request_ait_attachment"):
        op.create_table(
            "replacement_request_ait_attachment",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "replacement_request_id",
                sa.Integer(),
                sa.ForeignKey("replacement_request.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column(
                "file_id",
                sa.Integer(),
                sa.ForeignKey("entity_attachment.id"),
                nullable=True,
            ),
            sa.Column(
                "occurrence_attachment_id",
                sa.Integer(),
                sa.ForeignKey("maintenance_occurrence_attachment.id"),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )


def downgrade() -> None:
    if _table_exists("replacement_request_ait_attachment"):
        op.drop_table("replacement_request_ait_attachment")
    for col in (
        "ait_reject_reason",
        "ait_decision",
        "quarantined_instance_id",
        "red_notified_at",
        "shortage_held",
        "issued_at",
        "issued_instance_id",
        "issued_serial",
    ):
        _drop_column_if_exists("replacement_request", col)
