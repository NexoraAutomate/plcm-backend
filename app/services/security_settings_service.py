"""Persisted security / password-policy settings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.models.tables import SecuritySettings, User
from app.services.audit_service import write_audit_log


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


def get_or_create_security_settings(session: Session) -> SecuritySettings:
    settings = session.exec(select(SecuritySettings).limit(1)).first()
    if settings:
        return settings
    settings = SecuritySettings(**DEFAULT_SECURITY_SETTINGS)
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
    for key, value in updates.items():
        if not hasattr(settings, key) or value is None:
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
