"""
Optional seed of one active user per workflow role (Spec 00 test matrix).

Enabled when CREATE_WORKFLOW_DEMO_USERS is truthy (default: false).
Passwords are intentionally weak and for local/dev smoke only.
Admin Test Data UI can force-seed all or selected accounts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from sqlmodel import Session, select

from app.auth import hash_password
from app.domain.workflow_roles import WORKFLOW_ROLE_DB_NAMES, WorkflowRole
from app.models.tables import Role, User

# username → role.name (DB display names)
WORKFLOW_DEMO_USERS: list[dict[str, str]] = [
    {
        "username": "demo-pd",
        "full_name": "Demo Project Director",
        "email": "demo-pd@example.com",
        "role": WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD],
        "password": "Demo@pd123",
    },
    {
        "username": "demo-hm",
        "full_name": "Demo Hierarchy Manager",
        "email": "demo-hm@example.com",
        "role": WORKFLOW_ROLE_DB_NAMES[WorkflowRole.HM],
        "password": "Demo@hm123",
    },
    {
        "username": "demo-im",
        "full_name": "Demo Inventory Manager",
        "email": "demo-im@example.com",
        "role": WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM],
        "password": "Demo@im123",
    },
    {
        "username": "demo-dev",
        "full_name": "Demo Developer",
        "email": "demo-dev@example.com",
        "role": WORKFLOW_ROLE_DB_NAMES[WorkflowRole.DEV],
        "password": "Demo@dev123",
    },
    {
        "username": "demo-me",
        "full_name": "Demo Maintenance Engineer",
        "email": "demo-me@example.com",
        "role": WORKFLOW_ROLE_DB_NAMES[WorkflowRole.ME],
        "password": "Demo@me123",
    },
    {
        "username": "demo-fse",
        "full_name": "Demo Field Service Engineer",
        "email": "demo-fse@example.com",
        "role": WORKFLOW_ROLE_DB_NAMES[WorkflowRole.FSE],
        "password": "Demo@fse123",
    },
    {
        "username": "demo-ie",
        "full_name": "Demo Inspection Engineer",
        "email": "demo-ie@example.com",
        "role": WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IE],
        "password": "Demo@ie123",
    },
    {
        # Legacy notify / case-ops role until ME migration is complete (REQ-ROLE-006)
        "username": "demo-maintenance",
        "full_name": "Demo Maintenance (legacy)",
        "email": "demo-maintenance@example.com",
        "role": "Maintenance",
        "password": "Demo@maint123",
    },
    # Admin already ensured via ensure_default_admin
]


def _env_flag_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class WorkflowDemoUserOption:
    username: str
    full_name: str
    email: str
    role: str
    password: str
    exists: bool
    is_active: Optional[bool] = None
    user_id: Optional[int] = None
    role_missing: bool = False


@dataclass
class WorkflowDemoUserSeedItem:
    username: str
    role: str
    action: str
    reason: Optional[str] = None
    user_id: Optional[int] = None


@dataclass
class WorkflowDemoUserSeedResult:
    dry_run: bool = False
    created: int = 0
    updated: int = 0
    skipped: int = 0
    items: list[WorkflowDemoUserSeedItem] = field(default_factory=list)


def _normalize_filter_values(values: Optional[Iterable[str]]) -> Optional[set[str]]:
    if values is None:
        return None
    normalized = {str(v).strip() for v in values if str(v).strip()}
    return normalized


def _selected_entries(
    *,
    usernames: Optional[Sequence[str]] = None,
    roles: Optional[Sequence[str]] = None,
) -> list[dict[str, str]]:
    username_filter = _normalize_filter_values(usernames)
    role_filter = _normalize_filter_values(roles)
    if username_filter is None and role_filter is None:
        return list(WORKFLOW_DEMO_USERS)

    selected: list[dict[str, str]] = []
    for entry in WORKFLOW_DEMO_USERS:
        if username_filter is not None and entry["username"] not in username_filter:
            continue
        if role_filter is not None and entry["role"] not in role_filter:
            continue
        selected.append(entry)
    return selected


def list_workflow_demo_user_options(session: Session) -> list[WorkflowDemoUserOption]:
    """Return cheat-sheet demo accounts with current DB presence."""
    options: list[WorkflowDemoUserOption] = []
    for entry in WORKFLOW_DEMO_USERS:
        role = session.exec(select(Role).where(Role.name == entry["role"])).first()
        existing = session.exec(
            select(User).where(User.username == entry["username"])
        ).first()
        options.append(
            WorkflowDemoUserOption(
                username=entry["username"],
                full_name=entry["full_name"],
                email=entry["email"],
                role=entry["role"],
                password=entry["password"],
                exists=existing is not None,
                is_active=existing.is_active if existing else None,
                user_id=existing.id if existing else None,
                role_missing=role is None,
            )
        )
    return options


def seed_workflow_demo_users(
    session: Session,
    *,
    usernames: Optional[Sequence[str]] = None,
    roles: Optional[Sequence[str]] = None,
    force: bool = True,
    dry_run: bool = False,
    commit: bool = True,
) -> WorkflowDemoUserSeedResult:
    """Create/refresh selected (or all) demo users.

    ``force=True`` resets password / email / role / active to cheat-sheet values.
    """
    _ = force  # Always force-refresh when seeding from admin/CLI helpers.
    entries = _selected_entries(usernames=usernames, roles=roles)
    if not entries:
        raise ValueError("No matching demo roles selected")

    result = WorkflowDemoUserSeedResult(dry_run=dry_run)
    now = datetime.now(timezone.utc)

    for entry in entries:
        role = session.exec(select(Role).where(Role.name == entry["role"])).first()
        if not role:
            result.skipped += 1
            result.items.append(
                WorkflowDemoUserSeedItem(
                    username=entry["username"],
                    role=entry["role"],
                    action="skipped",
                    reason="role_missing",
                )
            )
            continue

        existing = session.exec(
            select(User).where(User.username == entry["username"])
        ).first()

        if existing:
            if dry_run:
                result.updated += 1
                result.items.append(
                    WorkflowDemoUserSeedItem(
                        username=entry["username"],
                        role=entry["role"],
                        action="would_update",
                        user_id=existing.id,
                    )
                )
                continue

            existing.email = entry["email"]
            existing.password = hash_password(entry["password"])
            existing.full_name = entry["full_name"]
            existing.is_active = True
            existing.roles = [role]
            existing.updated_at = now
            session.add(existing)
            result.updated += 1
            result.items.append(
                WorkflowDemoUserSeedItem(
                    username=entry["username"],
                    role=entry["role"],
                    action="updated",
                    user_id=existing.id,
                )
            )
            continue

        if dry_run:
            result.created += 1
            result.items.append(
                WorkflowDemoUserSeedItem(
                    username=entry["username"],
                    role=entry["role"],
                    action="would_create",
                )
            )
            continue

        user = User(
            username=entry["username"],
            email=entry["email"],
            full_name=entry["full_name"],
            is_active=True,
            password=hash_password(entry["password"]),
            updated_at=now,
        )
        user.roles = [role]
        session.add(user)
        session.flush()
        result.created += 1
        result.items.append(
            WorkflowDemoUserSeedItem(
                username=entry["username"],
                role=entry["role"],
                action="created",
                user_id=user.id,
            )
        )

    if not dry_run and commit:
        session.commit()
    return result


def ensure_workflow_demo_users(session: Session, *, force: bool = False) -> int:
    """Create or refresh demo users. Returns count of users created or updated.

    When ``force`` is True (CLI seed), skips the CREATE_WORKFLOW_DEMO_USERS gate
    and resets password / email / role / active to the cheat-sheet values.
    Without force, still backfills missing email on existing demo users.
    """
    if not force and not _env_flag_enabled("CREATE_WORKFLOW_DEMO_USERS", default=False):
        return 0

    if force:
        result = seed_workflow_demo_users(session, force=True, dry_run=False, commit=True)
        return result.created + result.updated

    # Soft path: only create missing users / backfill email (startup env flag).
    changed = 0
    now = datetime.now(timezone.utc)
    for entry in WORKFLOW_DEMO_USERS:
        role = session.exec(select(Role).where(Role.name == entry["role"])).first()
        if not role:
            continue

        existing = session.exec(
            select(User).where(User.username == entry["username"])
        ).first()

        if existing:
            dirty = False
            if not existing.email:
                existing.email = entry["email"]
                dirty = True
            if dirty:
                existing.updated_at = now
                session.add(existing)
                changed += 1
            continue

        user = User(
            username=entry["username"],
            email=entry["email"],
            full_name=entry["full_name"],
            is_active=True,
            password=hash_password(entry["password"]),
            updated_at=now,
        )
        user.roles = [role]
        session.add(user)
        changed += 1
    session.commit()
    return changed
