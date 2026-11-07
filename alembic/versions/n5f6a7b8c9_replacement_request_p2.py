"""P2 dual-track: ReplacementRequest + awaiting_faulty_arrival + reception_date."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "m4e5f6a7b8"
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
        "inventoryreworkcase",
        sa.Column("reception_date", sa.DateTime(timezone=True), nullable=True),
    )

    if not _table_exists("replacement_request"):
        op.create_table(
            "replacement_request",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "case_id",
                sa.Integer(),
                sa.ForeignKey("maintenance_case.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "faulty_entity_id",
                sa.Integer(),
                sa.ForeignKey("faulty_entity.id"),
                nullable=True,
                index=True,
            ),
            sa.Column("faulty_entity_type", sa.String(length=32), nullable=True),
            sa.Column("faulty_entity_ref_id", sa.Integer(), nullable=True, index=True),
            sa.Column(
                "requested_by_id",
                sa.Integer(),
                sa.ForeignKey("user.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "assigned_me_id",
                sa.Integer(),
                sa.ForeignKey("user.id"),
                nullable=True,
                index=True,
            ),
            sa.Column("status", sa.String(length=48), nullable=False, index=True),
            sa.Column("pd_decision", sa.String(length=16), nullable=True),
            sa.Column("reject_reason", sa.Text(), nullable=True),
            sa.Column("abort_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )

    if not _table_exists("replacement_request_reservation"):
        op.create_table(
            "replacement_request_reservation",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "replacement_request_id",
                sa.Integer(),
                sa.ForeignKey("replacement_request.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "inventory_reservation_id",
                sa.Integer(),
                sa.ForeignKey("inventoryreservation.id"),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "inventory_instance_id",
                sa.Integer(),
                sa.ForeignKey("inventoryinstance.id"),
                nullable=True,
                index=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    if _table_exists("replacement_request_reservation"):
        op.drop_table("replacement_request_reservation")
    if _table_exists("replacement_request"):
        op.drop_table("replacement_request")
    _drop_column_if_exists("inventoryreworkcase", "reception_date")
