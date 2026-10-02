"""Allow skipped hierarchy levels via alternate parent FKs.

Revision ID: c4e5f6a7b8
Revises: b3d4e5f6a7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e5f6a7b8"
down_revision: Union[str, None] = "b3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return column in {c["name"] for c in inspector.get_columns(table)}


def _has_fk(inspector: sa.Inspector, table: str, column: str) -> bool:
    for fk in inspector.get_foreign_keys(table):
        if column in (fk.get("constrained_columns") or []):
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # module: subsystem_id optional; may hang under system
    if _has_column(inspector, "module", "subsystem_id"):
        op.alter_column("module", "subsystem_id", existing_type=sa.Integer(), nullable=True)
    if not _has_column(inspector, "module", "system_id"):
        op.add_column("module", sa.Column("system_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_module_system_id_system",
            "module",
            "system",
            ["system_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # unit: module_id optional; may hang under subsystem/system
    inspector = sa.inspect(bind)
    if _has_column(inspector, "unit", "module_id"):
        op.alter_column("unit", "module_id", existing_type=sa.Integer(), nullable=True)
    if not _has_column(inspector, "unit", "subsystem_id"):
        op.add_column("unit", sa.Column("subsystem_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_unit_subsystem_id_subsystem",
            "unit",
            "subsystem",
            ["subsystem_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if not _has_column(inspector, "unit", "system_id"):
        op.add_column("unit", sa.Column("system_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_unit_system_id_system",
            "unit",
            "system",
            ["system_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # component: unit_id optional; may hang under module/subsystem/system
    inspector = sa.inspect(bind)
    if _has_column(inspector, "component", "unit_id"):
        op.alter_column("component", "unit_id", existing_type=sa.Integer(), nullable=True)
    if not _has_column(inspector, "component", "module_id"):
        op.add_column("component", sa.Column("module_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_component_module_id_module",
            "component",
            "module",
            ["module_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if not _has_column(inspector, "component", "subsystem_id"):
        op.add_column("component", sa.Column("subsystem_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_component_subsystem_id_subsystem",
            "component",
            "subsystem",
            ["subsystem_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if not _has_column(inspector, "component", "system_id"):
        op.add_column("component", sa.Column("system_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_component_system_id_system",
            "component",
            "system",
            ["system_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    bind = op.get_bind()

    for table, column, fk_name in (
        ("component", "system_id", "fk_component_system_id_system"),
        ("component", "subsystem_id", "fk_component_subsystem_id_subsystem"),
        ("component", "module_id", "fk_component_module_id_module"),
        ("unit", "system_id", "fk_unit_system_id_system"),
        ("unit", "subsystem_id", "fk_unit_subsystem_id_subsystem"),
        ("module", "system_id", "fk_module_system_id_system"),
    ):
        inspector = sa.inspect(bind)
        if _has_fk(inspector, table, column):
            op.drop_constraint(fk_name, table, type_="foreignkey")
        inspector = sa.inspect(bind)
        if _has_column(inspector, table, column):
            op.drop_column(table, column)
