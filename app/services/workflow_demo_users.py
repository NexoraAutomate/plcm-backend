"""
Optional seed of one active user per workflow role (Spec 00 test matrix).

Enabled when CREATE_WORKFLOW_DEMO_USERS is truthy (default: false).
Passwords are intentionally weak and for local/dev smoke only.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.auth import hash_password
from app.models.base import WorkflowRole
from app.models.tables import Role, User

# username → role.name
WORKFLOW_DEMO_USERS: list[dict[str, str]] = [
    {
        "username": "demo-pd",
        "full_name": "Demo Project Director",
        "role": WorkflowRole.PD.value,
        "password": "Demo@pd123",
    },
    {
        "username": "demo-hm",
        "full_name": "Demo Hierarchy Manager",
        "role": WorkflowRole.HM.value,
        "password": "Demo@hm123",
    },
    {
        "username": "demo-im",
        "full_name": "Demo Inventory Manager",
        "role": WorkflowRole.IM.value,
        "password": "Demo@im123",
    },
    {
        "username": "demo-dev",
        "full_name": "Demo Developer",
        "role": WorkflowRole.DEV.value,
        "password": "Demo@dev123",
    },
    # Admin already ensured via ensure_default_admin
]


def _env_flag_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def ensure_workflow_demo_users(session: Session) -> None:
    if not _env_flag_enabled("CREATE_WORKFLOW_DEMO_USERS", default=False):
        return

    for entry in WORKFLOW_DEMO_USERS:
        existing = session.exec(
            select(User).where(User.username == entry["username"])
        ).first()
        if existing:
            continue
        role = session.exec(select(Role).where(Role.name == entry["role"])).first()
        if not role:
            continue
        user = User(
            username=entry["username"],
            email=None,
            full_name=entry["full_name"],
            is_active=True,
            password=hash_password(entry["password"]),
            updated_at=datetime.now(timezone.utc),
        )
        user.roles = [role]
        session.add(user)
    session.commit()
