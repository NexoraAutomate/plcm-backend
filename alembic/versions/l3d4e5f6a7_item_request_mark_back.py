"""Item request mark-back reason fields for IM rejection."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "k2c3d4e5f6"
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
        "inventoryitemrequest",
        sa.Column("mark_back_reason", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "inventoryitemrequest",
        sa.Column("marked_back_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "inventoryitemrequest",
        sa.Column("marked_back_by_user_id", sa.Integer(), nullable=True),
    )
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "inventoryitemrequest" in tables:
        indexes = {i["name"] for i in sa.inspect(bind).get_indexes("inventoryitemrequest")}
        if "ix_inventoryitemrequest_marked_back_by_user_id" not in indexes:
            op.create_index(
                "ix_inventoryitemrequest_marked_back_by_user_id",
                "inventoryitemrequest",
                ["marked_back_by_user_id"],
            )
        fks = {fk["name"] for fk in sa.inspect(bind).get_foreign_keys("inventoryitemrequest")}
        if "fk_inventoryitemrequest_marked_back_by_user_id_user" not in fks:
            op.create_foreign_key(
                "fk_inventoryitemrequest_marked_back_by_user_id_user",
                "inventoryitemrequest",
                "user",
                ["marked_back_by_user_id"],
                ["id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "inventoryitemrequest" in tables:
        fks = {fk["name"] for fk in sa.inspect(bind).get_foreign_keys("inventoryitemrequest")}
        if "fk_inventoryitemrequest_marked_back_by_user_id_user" in fks:
            op.drop_constraint(
                "fk_inventoryitemrequest_marked_back_by_user_id_user",
                "inventoryitemrequest",
                type_="foreignkey",
            )
        indexes = {i["name"] for i in sa.inspect(bind).get_indexes("inventoryitemrequest")}
        if "ix_inventoryitemrequest_marked_back_by_user_id" in indexes:
            op.drop_index(
                "ix_inventoryitemrequest_marked_back_by_user_id",
                table_name="inventoryitemrequest",
            )
    _drop_column_if_exists("inventoryitemrequest", "marked_back_by_user_id")
    _drop_column_if_exists("inventoryitemrequest", "marked_back_at")
    _drop_column_if_exists("inventoryitemrequest", "mark_back_reason")
