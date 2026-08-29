"""Add administrator-controlled inventory label settings."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "r3s4t5u6v7"
down_revision: Union[str, None] = "q2r3s4t5u6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LABEL_COLUMNS = (
    ("inventory_label_code_type", sa.String(length=16), "qr"),
    ("inventory_qr_size_in", sa.Float(), "0.65"),
    ("inventory_barcode_width_in", sa.Float(), "2.0"),
    ("inventory_barcode_height_in", sa.Float(), "0.5"),
    ("inventory_qr_sticker_width_in", sa.Float(), "1.25"),
    ("inventory_qr_sticker_height_in", sa.Float(), "1.25"),
    ("inventory_barcode_sticker_width_in", sa.Float(), "2.25"),
    ("inventory_barcode_sticker_height_in", sa.Float(), "0.9"),
)


def upgrade() -> None:
    if context.is_offline_mode():
        columns: set[str] = set()
    else:
        columns = {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns("appdefinitions")
        }

    for name, column_type, default in LABEL_COLUMNS:
        if name not in columns:
            op.add_column(
                "appdefinitions",
                sa.Column(name, column_type, nullable=False, server_default=default),
            )


def downgrade() -> None:
    for name, _, _ in reversed(LABEL_COLUMNS):
        op.drop_column("appdefinitions", name)
