"""Add admin session super password hash to security settings."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9"
down_revision: Union[str, None] = "c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "securitysettings" not in tables:
        return
    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("securitysettings")
    }
    if "admin_session_super_password_hash" not in existing_columns:
        op.add_column(
            "securitysettings",
            sa.Column("admin_session_super_password_hash", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "securitysettings" not in tables:
        return
    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("securitysettings")
    }
    if "admin_session_super_password_hash" in existing_columns:
        op.drop_column("securitysettings", "admin_session_super_password_hash")
