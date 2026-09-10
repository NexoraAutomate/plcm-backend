"""Add oem_name to hierarchy hardware entities."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3d4e5f6a7"
down_revision: Union[str, None] = "a2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("system", "subsystem", "module", "unit", "component")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in TABLES:
        existing = {column["name"] for column in inspector.get_columns(table)}
        if "oem_name" not in existing:
            op.add_column(table, sa.Column("oem_name", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in TABLES:
        existing = {column["name"] for column in inspector.get_columns(table)}
        if "oem_name" in existing:
            op.drop_column(table, "oem_name")
