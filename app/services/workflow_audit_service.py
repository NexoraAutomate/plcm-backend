"""Spec 13 — immutable workflow audit writer, listing, and system actor."""

from __future__ import annotations

import json
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.auth import hash_password
from app.domain.workflow_audit import (
    SYSTEM_ACTOR_ROLE,
    SYSTEM_USERNAME,
    WORKFLOW_AUDIT_ACTIONS,
    WORKFLOW_AUDIT_ACTION_LABELS,
)
from app.domain.workflow_roles import WorkflowRole, has_workflow_role, normalize_workflow_role
from app.models.tables import User, WorkflowAuditEvent


class AuditRequestContext:
    __slots__ = ("ip_address", "user_agent", "correlation_id")

    def __init__(
        self,
        *,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.correlation_id = correlation_id


_audit_request: ContextVar[Optional[AuditRequestContext]] = ContextVar(
    "workflow_audit_request", default=None
)


def bind_audit_request(
    *,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Token:
    return _audit_request.set(
        AuditRequestContext(
            ip_address=ip_address,
            user_agent=(user_agent or None) and (user_agent[:512] if user_agent else None),
            correlation_id=correlation_id,
        )
    )


def reset_audit_request(token: Token) -> None:
    _audit_request.reset(token)


def get_audit_request() -> Optional[AuditRequestContext]:
    return _audit_request.get()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _role_names(user: User) -> list[str]:
    return [r.name for r in (user.roles or [])]


def resolve_actor_role(user: Optional[User], *, system: bool = False) -> str:
    if system:
        return SYSTEM_ACTOR_ROLE
    if user is None:
        return SYSTEM_ACTOR_ROLE
    names = _role_names(user)
    for role in (
        WorkflowRole.ADMIN,
        WorkflowRole.PD,
        WorkflowRole.HM,
        WorkflowRole.IM,
        WorkflowRole.DEV,
    ):
        if has_workflow_role(names, role):
            return role.value
    if names:
        mapped = normalize_workflow_role(names[0])
        if mapped:
            return mapped.value
        return names[0]
    return SYSTEM_ACTOR_ROLE


def ensure_system_user(session: Session) -> User:
    existing = session.exec(select(User).where(User.username == SYSTEM_USERNAME)).first()
    if existing:
        return existing
    user = User(
        username=SYSTEM_USERNAME,
        email="system@plcm.local",
        full_name="System",
        is_active=False,
        password=hash_password(uuid.uuid4().hex),
        updated_at=_now(),
    )
    session.add(user)
    session.flush()
    return user


def write_workflow_audit(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int,
    actor: Optional[User] = None,
    actor_role: Optional[str] = None,
    project_id: Optional[int] = None,
    old_value: Any = None,
    new_value: Any = None,
    remarks: Optional[str] = None,
    system: bool = False,
) -> WorkflowAuditEvent:
    """Append an immutable audit row in the current transaction (flush, no commit)."""
    ctx = get_audit_request()
    use_system = system or actor is None
    if use_system:
        actor = ensure_system_user(session)
    if actor is None or actor.id is None:
        raise RuntimeError("Workflow audit requires an actor user")

    role = (actor_role or resolve_actor_role(actor, system=use_system)).strip().upper()
    event = WorkflowAuditEvent(
        id=str(uuid.uuid4()),
        occurred_at=_now(),
        actor_user_id=int(actor.id),
        actor_username=actor.username,
        actor_role=role,
        action=str(action).strip().upper(),
        entity_type=str(entity_type).strip().lower(),
        entity_id=str(entity_id),
        project_id=int(project_id) if project_id is not None else None,
        old_value=_jsonable(old_value),
        new_value=_jsonable(new_value),
        remarks=remarks,
        ip_address=ctx.ip_address if ctx else None,
        user_agent=ctx.user_agent if ctx else None,
        correlation_id=ctx.correlation_id if ctx else None,
    )
    session.add(event)
    session.flush()
    return event


def event_to_dict(event: WorkflowAuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "occurred_at": event.occurred_at,
        "actor_user_id": event.actor_user_id,
        "actor_username": event.actor_username,
        "actor_role": event.actor_role,
        "action": event.action,
        "action_label": WORKFLOW_AUDIT_ACTION_LABELS.get(event.action, event.action),
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "project_id": event.project_id,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "remarks": event.remarks,
        "ip_address": event.ip_address,
        "user_agent": event.user_agent,
        "correlation_id": event.correlation_id,
    }


def list_workflow_audits(
    session: Session,
    *,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    actor_role: Optional[str] = None,
    action: Optional[str] = None,
    project_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[WorkflowAuditEvent], int]:
    stmt = select(WorkflowAuditEvent)
    if entity_type:
        stmt = stmt.where(WorkflowAuditEvent.entity_type == entity_type.strip().lower())
    if entity_id:
        stmt = stmt.where(WorkflowAuditEvent.entity_id == str(entity_id))
    if actor_user_id is not None:
        stmt = stmt.where(WorkflowAuditEvent.actor_user_id == int(actor_user_id))
    if actor_role:
        stmt = stmt.where(WorkflowAuditEvent.actor_role == actor_role.strip().upper())
    if action:
        stmt = stmt.where(WorkflowAuditEvent.action == action.strip().upper())
    if project_id is not None:
        stmt = stmt.where(WorkflowAuditEvent.project_id == int(project_id))
    if date_from is not None:
        stmt = stmt.where(WorkflowAuditEvent.occurred_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(WorkflowAuditEvent.occurred_at <= date_to)
    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                WorkflowAuditEvent.action.ilike(like),
                WorkflowAuditEvent.entity_type.ilike(like),
                WorkflowAuditEvent.entity_id.ilike(like),
                WorkflowAuditEvent.actor_username.ilike(like),
                WorkflowAuditEvent.remarks.ilike(like),
            )
        )

    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    rows = list(
        session.exec(
            stmt.order_by(WorkflowAuditEvent.occurred_at.desc()).offset(skip).limit(limit)
        ).all()
    )
    return rows, int(total)


def action_catalog() -> list[dict[str, str]]:
    return [
        {"code": code, "label": WORKFLOW_AUDIT_ACTION_LABELS.get(code, code)}
        for code in WORKFLOW_AUDIT_ACTIONS
    ]
