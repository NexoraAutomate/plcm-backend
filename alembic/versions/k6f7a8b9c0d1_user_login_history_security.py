"""User management: login history, audit log, security settings, user activity columns

Revision ID: k6f7a8b9c0d1
Revises: j5e6f7a8b9c0
Create Date: 2026-07-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "j5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "user" in inspector.get_table_names():
        columns = [
            ("updated_at", sa.DateTime(timezone=True), True),
            ("last_login_at", sa.DateTime(timezone=True), True),
            ("last_logout_at", sa.DateTime(timezone=True), True),
            ("last_activity_at", sa.DateTime(timezone=True), True),
            ("failed_login_count", sa.Integer(), False),
            ("locked_until", sa.DateTime(timezone=True), True),
            ("created_by_id", sa.Integer(), True),
        ]
        for name, col_type, nullable in columns:
            if not _has_column(inspector, "user", name):
                server_default = "0" if name == "failed_login_count" else None
                op.add_column(
                    "user",
                    sa.Column(name, col_type, nullable=nullable, server_default=server_default),
                )
        # Refresh inspector after adds
        inspector = sa.inspect(bind)
        fks = inspector.get_foreign_keys("user")
        has_created_by_fk = any(
            "created_by_id" in (fk.get("constrained_columns") or []) for fk in fks
        )
        if _has_column(inspector, "user", "created_by_id") and not has_created_by_fk:
            op.create_foreign_key(
                "fk_user_created_by_id",
                "user",
                "user",
                ["created_by_id"],
                ["id"],
            )

    if "userloginhistory" not in inspector.get_table_names():
        op.create_table(
            "userloginhistory",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("username", sa.String(), nullable=False),
            sa.Column("login_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("logout_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("session_id", sa.String(length=64), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("device_name", sa.String(length=255), nullable=True),
            sa.Column("browser", sa.String(length=255), nullable=True),
            sa.Column("operating_system", sa.String(length=255), nullable=True),
            sa.Column("login_status", sa.String(length=32), nullable=False),
            sa.Column("failure_reason", sa.String(length=255), nullable=True),
            sa.Column("last_activity", sa.DateTime(timezone=True), nullable=True),
            sa.Column("session_duration", sa.Integer(), nullable=True),
            sa.Column("authentication_method", sa.String(length=64), nullable=False),
            sa.Column("country", sa.String(length=128), nullable=True),
            sa.Column("city", sa.String(length=128), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_userloginhistory_user_id", "userloginhistory", ["user_id"])
        op.create_index("ix_userloginhistory_session_id", "userloginhistory", ["session_id"])

    if "auditlog" not in inspector.get_table_names():
        op.create_table(
            "auditlog",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("actor_username", sa.String(length=255), nullable=True),
            sa.Column("action", sa.String(length=128), nullable=False),
            sa.Column("resource_type", sa.String(length=64), nullable=True),
            sa.Column("resource_id", sa.String(length=64), nullable=True),
            sa.Column("previous_value", sa.Text(), nullable=True),
            sa.Column("new_value", sa.Text(), nullable=True),
            sa.Column("details", sa.Text(), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_auditlog_actor_user_id", "auditlog", ["actor_user_id"])

    if "securitysettings" not in inspector.get_table_names():
        op.create_table(
            "securitysettings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("min_password_length", sa.Integer(), nullable=False, server_default="8"),
            sa.Column("password_expiry_days", sa.Integer(), nullable=False, server_default="90"),
            sa.Column("require_uppercase", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("require_lowercase", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("require_numbers", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("require_special", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("password_history_length", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("max_login_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("lockout_duration_minutes", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("inactivity_deactivate_days", sa.Integer(), nullable=False, server_default="90"),
            sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("two_factor_require_all", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "two_factor_require_admins_only",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("securitysettings", "auditlog", "userloginhistory"):
        if table in inspector.get_table_names():
            op.drop_table(table)
