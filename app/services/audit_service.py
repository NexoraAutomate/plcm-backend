"""Audit logging for administrator and security-sensitive actions."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session

from app.models.tables import AuditLog, User


def write_audit_log(
    session: Session,
    *,
    action: str,
    actor: Optional[User] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str | int] = None,
    previous_value: Any = None,
    new_value: Any = None,
    details: Optional[str] = None,
    ip_address: Optional[str] = None,
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_username=actor.username if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        previous_value=None if previous_value is None else str(previous_value),
        new_value=None if new_value is None else str(new_value),
        details=details,
        ip_address=ip_address,
    )
    session.add(entry)
    if commit:
        session.commit()
        session.refresh(entry)
    else:
        session.flush()
    return entry
