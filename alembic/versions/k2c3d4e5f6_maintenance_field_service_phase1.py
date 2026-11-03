"""Maintenance field-service phase 1: support gate, onsite, return link, OEM claims."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "j1b2c3d4e5"
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
    bind = op.get_bind()

    # Extend resolutiontype enum with soft_fixed (Postgres).
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_type WHERE typname = 'resolutiontype'
                    ) AND NOT EXISTS (
                        SELECT 1
                        FROM pg_enum e
                        JOIN pg_type t ON t.oid = e.enumtypid
                        WHERE t.typname = 'resolutiontype' AND e.enumlabel = 'soft_fixed'
                    ) THEN
                        ALTER TYPE resolutiontype ADD VALUE 'soft_fixed';
                    END IF;
                END
                $$;
                """
            )
        )

    _add_column_if_missing(
        "maintenance_case",
        sa.Column("production_support_date", sa.Date(), nullable=True),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("in_production_support", sa.Boolean(), nullable=True),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("support_override_reason", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("onsite_outcome", sa.String(length=32), nullable=True),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("onsite_soft_fix_method", sa.String(length=32), nullable=True),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("onsite_notes", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("onsite_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "maintenance_case",
        sa.Column("onsite_recorded_by_id", sa.Integer(), nullable=True),
    )

    _add_column_if_missing(
        "inventoryreworkcase",
        sa.Column("maintenance_case_id", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        "inventoryreworkcase",
        sa.Column("faulty_entity_id", sa.Integer(), nullable=True),
    )
    _add_column_if_missing(
        "inventoryreworkcase",
        sa.Column("investigating_pd_id", sa.Integer(), nullable=True),
    )

    tables = set(sa.inspect(bind).get_table_names())
    if "oemwarrantyclaim" not in tables:
        op.create_table(
            "oemwarrantyclaim",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("maintenance_case_id", sa.Integer(), nullable=True, index=True),
            sa.Column("faulty_entity_id", sa.Integer(), nullable=True, index=True),
            sa.Column("inventory_id", sa.Integer(), nullable=True, index=True),
            sa.Column("inventory_instance_id", sa.Integer(), nullable=True, index=True),
            sa.Column("rework_case_id", sa.Integer(), nullable=True, index=True),
            sa.Column("oem_name", sa.String(length=128), nullable=True),
            sa.Column("part_number", sa.String(length=128), nullable=True),
            sa.Column("serial_number", sa.String(length=128), nullable=True),
            sa.Column("warranty_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="open",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_id", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "oemwarrantyclaim" in tables:
        op.drop_table("oemwarrantyclaim")

    for name in (
        "investigating_pd_id",
        "faulty_entity_id",
        "maintenance_case_id",
    ):
        _drop_column_if_exists("inventoryreworkcase", name)

    for name in (
        "onsite_recorded_by_id",
        "onsite_recorded_at",
        "onsite_notes",
        "onsite_soft_fix_method",
        "onsite_outcome",
        "support_override_reason",
        "in_production_support",
        "production_support_date",
    ):
        _drop_column_if_exists("maintenance_case", name)
