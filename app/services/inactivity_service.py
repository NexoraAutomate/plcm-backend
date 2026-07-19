"""Automatic deactivation of users inactive beyond the configured threshold."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from app.models.tables import User
from app.services.audit_service import write_audit_log
from app.services.login_history_service import close_open_sessions_for_user
from app.services.security_settings_service import get_or_create_security_settings


def deactivate_inactive_users(
    session: Session,
    *,
    actor: Optional[User] = None,
    dry_run: bool = False,
) -> dict:
    """
    Deactivate users with no successful login within the configured inactivity window.

    Uses `last_login_at` when available, otherwise falls back to `created_at`.
    Safe to call from startup, cron, workers, or a manual admin action.
    """
    settings = get_or_create_security_settings(session)
    days = settings.inactivity_deactivate_days
    if days is None or days <= 0:
        return {
            "deactivated_count": 0,
            "candidate_count": 0,
            "inactivity_days": days or 0,
            "dry_run": dry_run,
            "user_ids": [],
        }

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    users = session.exec(select(User).where(User.is_active == True)).all()  # noqa: E712
    candidates: list[User] = []
    for user in users:
        reference = user.last_login_at or user.created_at
        if reference is None:
            continue
        # Normalize naive datetimes from DB
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        if reference < cutoff:
            candidates.append(user)

    if dry_run:
        return {
            "deactivated_count": 0,
            "candidate_count": len(candidates),
            "inactivity_days": days,
            "dry_run": True,
            "user_ids": [u.id for u in candidates if u.id is not None],
        }

    deactivated_ids: list[int] = []
    now = datetime.now(timezone.utc)
    for user in candidates:
        previous = user.is_active
        user.is_active = False
        user.updated_at = now
        session.add(user)
        if user.id is not None:
            close_open_sessions_for_user(session, user.id)
            deactivated_ids.append(user.id)
        write_audit_log(
            session,
            action="User Deactivated",
            actor=actor,
            resource_type="user",
            resource_id=user.id,
            previous_value=previous,
            new_value=False,
            details=f"Automatic inactivity deactivation after {days} days",
        )

    session.commit()
    return {
        "deactivated_count": len(deactivated_ids),
        "candidate_count": len(candidates),
        "inactivity_days": days,
        "dry_run": False,
        "user_ids": deactivated_ids,
    }
