"""Add lowercase ResolutionType PG enum labels (align with Python .value).

Historic DB used UPPERCASE member names; soft_fixed was later added lowercase.
App writes lowercase values via values_callable — ensure all labels exist.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "n5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LABELS = (
    "repaired",
    "replaced",
    "no_fault_found",
    "decommissioned",
    "clear",
    "soft_fixed",
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {
        r[0]
        for r in bind.execute(
            sa.text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON e.enumtypid = t.oid "
                "WHERE t.typname = 'resolutiontype'"
            )
        )
    }
    for label in _LABELS:
        if label in existing:
            continue
        # ADD VALUE cannot run inside a transaction block on some PG versions;
        # Alembic usually autocommits ALTER TYPE ADD VALUE.
        bind.execute(sa.text(f"ALTER TYPE resolutiontype ADD VALUE IF NOT EXISTS '{label}'"))


def downgrade() -> None:
    # PostgreSQL cannot easily drop enum values; leave labels in place.
    pass
