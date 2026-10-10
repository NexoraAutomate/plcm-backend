"""Persisted security / password-policy settings."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.auth import hash_password
from app.models.tables import SecuritySettings, User
from app.schemas import schemas
from app.services.audit_service import write_audit_log


DEFAULT_ADMIN_SESSION_SUPER_PASSWORD = "super@admin8276"

DEFAULT_SECURITY_SETTINGS = {
    "min_password_length": 8,
    "password_expiry_days": 90,
    "require_uppercase": True,
    "require_lowercase": True,
    "require_numbers": True,
    "require_special": False,
    "password_history_length": 5,
    "max_login_attempts": 5,
    "lockout_duration_minutes": 30,
    "inactivity_deactivate_days": 90,
    "two_factor_enabled": False,
    "two_factor_require_all": False,
    "two_factor_require_admins_only": True,
}


def default_admin_session_super_password() -> str:
    return (
        os.getenv("ADMIN_SESSION_SUPER_PASSWORD", DEFAULT_ADMIN_SESSION_SUPER_PASSWORD).strip()
        or DEFAULT_ADMIN_SESSION_SUPER_PASSWORD
    )


def ensure_admin_session_super_password(session: Session, settings: SecuritySettings) -> SecuritySettings:
    """Bootstrap a hashed super password when none is stored yet."""
    if settings.admin_session_super_password_hash:
        return settings
    settings.admin_session_super_password_hash = hash_password(
        default_admin_session_super_password()
    )
    settings.updated_at = datetime.now(timezone.utc)
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings


def security_settings_to_read(settings: SecuritySettings) -> schemas.SecuritySettingsRead:
    return schemas.SecuritySettingsRead(
        id=int(settings.id),
        min_password_length=settings.min_password_length,
        password_expiry_days=settings.password_expiry_days,
        require_uppercase=settings.require_uppercase,
        require_lowercase=settings.require_lowercase,
        require_numbers=settings.require_numbers,
        require_special=settings.require_special,
        password_history_length=settings.password_history_length,
        max_login_attempts=settings.max_login_attempts,
        lockout_duration_minutes=settings.lockout_duration_minutes,
        inactivity_deactivate_days=settings.inactivity_deactivate_days,
        two_factor_enabled=settings.two_factor_enabled,
        two_factor_require_all=settings.two_factor_require_all,
        two_factor_require_admins_only=settings.two_factor_require_admins_only,
        admin_session_super_password_set=bool(settings.admin_session_super_password_hash),
        updated_at=settings.updated_at,
    )


def get_or_create_security_settings(session: Session) -> SecuritySettings:
    settings = session.exec(select(SecuritySettings).limit(1)).first()
    if settings:
        return ensure_admin_session_super_password(session, settings)
    settings = SecuritySettings(
        **DEFAULT_SECURITY_SETTINGS,
        admin_session_super_password_hash=hash_password(
            default_admin_session_super_password()
        ),
    )
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings


def update_security_settings(
    session: Session,
    updates: dict,
    *,
    actor: Optional[User] = None,
    ip_address: Optional[str] = None,
) -> SecuritySettings:
    settings = get_or_create_security_settings(session)
    changed: list[tuple[str, object, object]] = []

    plaintext_super = updates.pop("admin_session_super_password", None)
    if isinstance(plaintext_super, str) and plaintext_super.strip():
        previous_set = bool(settings.admin_session_super_password_hash)
        settings.admin_session_super_password_hash = hash_password(plaintext_super.strip())
        changed.append(
            (
                "admin_session_super_password",
                "set" if previous_set else "unset",
                "updated",
            )
        )

    for key, value in updates.items():
        if not hasattr(settings, key) or value is None:
            continue
        if key == "admin_session_super_password_hash":
            continue
        previous = getattr(settings, key)
        if previous == value:
            continue
        setattr(settings, key, value)
        changed.append((key, previous, value))

    if not changed:
        return settings

    settings.updated_at = datetime.now(timezone.utc)
    if actor:
        settings.updated_by_id = actor.id
    session.add(settings)

    for key, previous, value in changed:
        action = (
            "Inactivity Duration Modified"
            if key == "inactivity_deactivate_days"
            else "Security Policy Changed"
        )
        write_audit_log(
            session,
            action=action,
            actor=actor,
            resource_type="security_settings",
            resource_id=settings.id,
            previous_value=f"{key}={previous}",
            new_value=f"{key}={value}",
            ip_address=ip_address,
        )

    session.commit()
    session.refresh(settings)
    return settings
