"""Add signed inventory labels and print/scan history

Revision ID: q2r3s4t5u6
Revises: p1q2r3s4t5u6
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "q2r3s4t5u6"
down_revision: Union[str, None] = "p1q2r3s4t5u6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if context.is_offline_mode():
        tables: set[str] = set()
    else:
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        tables = set(inspector.get_table_names())

    if "inventorylabel" not in tables:
        op.create_table(
            "inventorylabel",
            sa.Column("label_id", sa.String(length=64), nullable=False),
            sa.Column("inventory_id", sa.Integer(), nullable=False),
            sa.Column("inventory_instance_id", sa.Integer(), nullable=True),
            sa.Column("serial_number", sa.String(length=128), nullable=True),
            sa.Column("label_type", sa.String(length=16), nullable=False, server_default="qr"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.Column("signature_version", sa.String(length=16), nullable=False, server_default="v1"),
            sa.Column("print_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("first_printed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_printed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("activated_by_id", sa.Integer(), nullable=True),
            sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deactivated_by_id", sa.Integer(), nullable=True),
            sa.Column("replacement_label_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["inventory_id"], ["inventory.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["inventory_instance_id"], ["inventoryinstance.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["activated_by_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["deactivated_by_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("label_id", name="uq_inventorylabel_label_id"),
        )
    if "inventorylabelprintevent" not in tables:
        op.create_table(
            "inventorylabelprintevent",
            sa.Column("label_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("printed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("label_type", sa.String(length=16), nullable=False),
            sa.Column("label_format", sa.String(length=32), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_first_print", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["label_id"], ["inventorylabel.label_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if "inventorylabelscanevent" not in tables:
        op.create_table(
            "inventorylabelscanevent",
            sa.Column("label_id", sa.String(length=64), nullable=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("location", sa.String(length=255), nullable=True),
            sa.Column("source", sa.String(length=32), nullable=False, server_default="web"),
            sa.Column("valid", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("suspicious", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("payload_fingerprint", sa.String(length=128), nullable=True),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["label_id"], ["inventorylabel.label_id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    op.create_index(
        "ix_inventorylabel_inventory_id",
        "inventorylabel",
        ["inventory_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_inventorylabel_inventory_instance_id",
        "inventorylabel",
        ["inventory_instance_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "uq_inventorylabel_active_instance",
        "inventorylabel",
        ["inventory_instance_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        if_not_exists=True,
    )
    op.create_index(
        "uq_inventorylabel_active_serial",
        "inventorylabel",
        ["inventory_id", "serial_number"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'active' AND inventory_instance_id IS NULL AND serial_number IS NOT NULL"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "uq_inventorylabel_active_inventory",
        "inventorylabel",
        ["inventory_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'active' AND inventory_instance_id IS NULL AND serial_number IS NULL"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_inventorylabelprintevent_label_id",
        "inventorylabelprintevent",
        ["label_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_inventorylabelscanevent_label_id",
        "inventorylabelscanevent",
        ["label_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("inventorylabelscanevent")
    op.drop_table("inventorylabelprintevent")
    op.drop_table("inventorylabel")
