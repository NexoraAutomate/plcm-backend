"""Password policy validation and history helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlmodel import Session

from app.auth import hash_password, verify_password
from app.models.tables import User
from app.services.security_settings_service import get_or_create_security_settings


SPECIAL_RE = re.compile(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?`~]")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_password_complexity(password: str, settings) -> None:
    """Raise 400 if password does not meet configured complexity rules."""
    if not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is required",
        )

    min_len = settings.min_password_length or 8
    if len(password) < min_len:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {min_len} characters",
        )

    if settings.require_uppercase and not any(c.isupper() for c in password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must include at least one uppercase letter",
        )
    if settings.require_lowercase and not any(c.islower() for c in password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must include at least one lowercase letter",
        )
    if settings.require_numbers and not any(c.isdigit() for c in password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must include at least one number",
        )
    if settings.require_special and not SPECIAL_RE.search(password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must include at least one special character",
        )


def _parse_history(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(h) for h in data if h]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _serialize_history(hashes: list[str]) -> str:
    return json.dumps(hashes)


def assert_not_in_password_history(password: str, user: User, settings) -> None:
    history_len = settings.password_history_length or 0
    if history_len <= 0:
        return

    candidates = []
    if user.password:
        candidates.append(user.password)
    candidates.extend(_parse_history(user.password_history))

    for hashed in candidates[:history_len]:
        try:
            if verify_password(password, hashed):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Password cannot match any of the last {history_len} passwords",
                )
        except HTTPException:
            raise
        except Exception:
            continue


def apply_new_password(user: User, plain_password: str, settings) -> None:
    """Validate policy, update hash + history + password_changed_at on the user object."""
    validate_password_complexity(plain_password, settings)
    assert_not_in_password_history(plain_password, user, settings)

    history = _parse_history(user.password_history)
    if user.password:
        history.insert(0, user.password)
    keep = max(settings.password_history_length or 0, 0)
    user.password_history = _serialize_history(history[:keep]) if keep else None
    user.password = hash_password(plain_password)
    user.password_changed_at = _utcnow()
    user.updated_at = _utcnow()


def enforce_password_policy(
    session: Session,
    password: str,
    *,
    user: Optional[User] = None,
) -> None:
    """Validate complexity (+ history when updating an existing user)."""
    settings = get_or_create_security_settings(session)
    validate_password_complexity(password, settings)
    if user is not None:
        assert_not_in_password_history(password, user, settings)


def set_user_password(session: Session, user: User, password: str) -> None:
    settings = get_or_create_security_settings(session)
    apply_new_password(user, password, settings)


def password_is_expired(user: User, settings) -> bool:
    days = settings.password_expiry_days or 0
    if days <= 0:
        return False
    changed = user.password_changed_at or user.created_at
    if changed is None:
        return False
    if changed.tzinfo is None:
        changed = changed.replace(tzinfo=timezone.utc)
    age = _utcnow() - changed
    return age.days >= days


def public_password_policy(session: Session) -> dict:
    settings = get_or_create_security_settings(session)
    return {
        "min_password_length": settings.min_password_length,
        "require_uppercase": settings.require_uppercase,
        "require_lowercase": settings.require_lowercase,
        "require_numbers": settings.require_numbers,
        "require_special": settings.require_special,
        "password_history_length": settings.password_history_length,
        "password_expiry_days": settings.password_expiry_days,
    }
