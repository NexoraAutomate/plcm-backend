"""Add hierarchical inventory_location_tree; drop flat location lists."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "y0z1a2b3c4"
down_revision: Union[str, None] = "x9y0z1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FLAT_COLUMNS = (
    "inventory_location_rooms",
    "inventory_location_cabinets",
    "inventory_location_racks",
    "inventory_location_presets",
)


def _existing_columns(table: str) -> set[str]:
    if context.is_offline_mode():
        return set()
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table)
    }


def upgrade() -> None:
    cols = _existing_columns("appdefinitions")
    if "inventory_location_tree" not in cols:
        op.add_column(
            "appdefinitions",
            sa.Column("inventory_location_tree", sa.JSON(), nullable=True),
        )
    for name in FLAT_COLUMNS:
        if name in cols:
            op.drop_column("appdefinitions", name)


def downgrade() -> None:
    cols = _existing_columns("appdefinitions")
    for name in ("inventory_location_rooms", "inventory_location_cabinets", "inventory_location_racks"):
        if name not in cols:
            op.add_column(
                "appdefinitions",
                sa.Column(name, sa.JSON(), nullable=True),
            )
    if "inventory_location_tree" in cols:
        op.drop_column("appdefinitions", "inventory_location_tree")
