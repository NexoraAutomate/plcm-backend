"""Add Room/Cabinet/Rack location presets and inventory fields."""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "x9y0z1a2b3"
down_revision: Union[str, None] = "v8w9x0y1z2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFINITIONS_COLUMNS = (
    "inventory_location_rooms",
    "inventory_location_cabinets",
    "inventory_location_racks",
)

INVENTORY_LOCATION_COLUMNS = (
    "location_room",
    "location_cabinet",
    "location_rack",
)


def _existing_columns(table: str) -> set[str]:
    if context.is_offline_mode():
        return set()
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table)
    }


def upgrade() -> None:
    def_cols = _existing_columns("appdefinitions")
    for name in DEFINITIONS_COLUMNS:
        if name not in def_cols:
            op.add_column(
                "appdefinitions",
                sa.Column(name, sa.JSON(), nullable=True),
            )

    # Drop legacy flat presets column if a previous revision added it.
    if "inventory_location_presets" in def_cols:
        op.drop_column("appdefinitions", "inventory_location_presets")

    for table in ("inventory", "inventoryinstance"):
        cols = _existing_columns(table)
        for name in INVENTORY_LOCATION_COLUMNS:
            if name not in cols:
                op.add_column(
                    table,
                    sa.Column(name, sa.String(length=120), nullable=True),
                )


def downgrade() -> None:
    for table in ("inventoryinstance", "inventory"):
        for name in reversed(INVENTORY_LOCATION_COLUMNS):
            op.drop_column(table, name)
    for name in reversed(DEFINITIONS_COLUMNS):
        op.drop_column("appdefinitions", name)
