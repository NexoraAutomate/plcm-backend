"""Add return_pending support and notice decision fields

Revision ID: n9c0d1e2f3a4
Revises: m8b9c0d1e2f3
Create Date: 2026-07-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "n9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "m8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "inventoryissuance" in inspector.get_table_names() and not _has_column(
        inspector, "inventoryissuance", "return_requested_at"
    ):
        op.add_column(
            "inventoryissuance",
            sa.Column("return_requested_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "inventoryreturnnotice" in inspector.get_table_names():
        if not _has_column(inspector, "inventoryreturnnotice", "decision"):
            op.add_column(
                "inventoryreturnnotice",
                sa.Column("decision", sa.String(), nullable=True, server_default="pending"),
            )
            op.create_index(
                "ix_inventoryreturnnotice_decision",
                "inventoryreturnnotice",
                ["decision"],
            )
        if not _has_column(inspector, "inventoryreturnnotice", "decided_at"):
            op.add_column(
                "inventoryreturnnotice",
                sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            )
        if not _has_column(inspector, "inventoryreturnnotice", "decided_by_id"):
            op.add_column(
                "inventoryreturnnotice",
                sa.Column(
                    "decided_by_id",
                    sa.Integer(),
                    sa.ForeignKey("user.id"),
                    nullable=True,
                ),
            )
        if not _has_column(inspector, "inventoryreturnnotice", "decision_notes"):
            op.add_column(
                "inventoryreturnnotice",
                sa.Column("decision_notes", sa.String(), nullable=True),
            )
        # Existing notices are already finalized returns
        op.execute(
            sa.text(
                "UPDATE inventoryreturnnotice SET decision = 'accepted' "
                "WHERE decision IS NULL OR decision = 'pending'"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "inventoryreturnnotice" in inspector.get_table_names():
        if _has_column(inspector, "inventoryreturnnotice", "decision_notes"):
            op.drop_column("inventoryreturnnotice", "decision_notes")
        if _has_column(inspector, "inventoryreturnnotice", "decided_by_id"):
            op.drop_column("inventoryreturnnotice", "decided_by_id")
        if _has_column(inspector, "inventoryreturnnotice", "decided_at"):
            op.drop_column("inventoryreturnnotice", "decided_at")
        if _has_column(inspector, "inventoryreturnnotice", "decision"):
            try:
                op.drop_index(
                    "ix_inventoryreturnnotice_decision",
                    table_name="inventoryreturnnotice",
                )
            except Exception:
                pass
            op.drop_column("inventoryreturnnotice", "decision")

    if "inventoryissuance" in inspector.get_table_names() and _has_column(
        inspector, "inventoryissuance", "return_requested_at"
    ):
        op.drop_column("inventoryissuance", "return_requested_at")
