"""Add issuance signature/proforma attachment types.

Revision ID: v8w9x0y1z2
Revises: u7v8w9x0y1
Create Date: 2026-09-02

"""
from typing import Sequence, Union

from alembic import op


revision: str = "v8w9x0y1z2"
down_revision: Union[str, None] = "u7v8w9x0y1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'attachmenttype') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'attachmenttype'
                      AND e.enumlabel = 'issuance_signature'
                ) THEN
                    ALTER TYPE attachmenttype ADD VALUE 'issuance_signature';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON e.enumtypid = t.oid
                    WHERE t.typname = 'attachmenttype'
                      AND e.enumlabel = 'issuance_proforma'
                ) THEN
                    ALTER TYPE attachmenttype ADD VALUE 'issuance_proforma';
                END IF;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # PostgreSQL cannot easily remove enum values safely.
    pass
