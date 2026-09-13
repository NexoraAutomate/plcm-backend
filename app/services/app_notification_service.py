"""Spec 14 — persist role-targeted in-app notices for gap events.

Does not recreate inventory notices that already have dedicated tables:
issue-to-installer, return request/decision, shortage created/partial/fulfilled,
idle reservation reminder, reservation auto-release.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from app.domain.workflow_audit import WorkflowAuditAction
from app.domain.workflow_roles import WORKFLOW_ROLE_DB_NAMES, WorkflowRole, has_workflow_role
from app.models.tables import (
    AppNotification,
    InventoryRecallTask,
    Project,
    Role,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)

EXISTING_EVENT_TYPES = frozenset(
    {
        "issued",
        "inventory_issued",
        "return_requested",
        "inventory_returned",
        "return_accepted",
        "inventory_return_accepted",
        "return_rejected",
        "inventory_return_rejected",
        "shortage_created",
        "inventory_shortage",
        "shortage_partial",
        "inventory_shortage_partial",
        "shortage_fulfilled",
        "inventory_shortage_fulfilled",
        "reservation_idle_reminder",
        "reservation_auto_released",
    }
)

SKIP_AUDIT_ACTIONS = frozenset(
    {
        WorkflowAuditAction.ISSUED,
        WorkflowAuditAction.RE_ISSUED,
        WorkflowAuditAction.SHORTAGE_CREATED,
        WorkflowAuditAction.SHORTAGE_PARTIAL,
        WorkflowAuditAction.SHORTAGE_FULFILLED,
        WorkflowAuditAction.AUTO_RESERVE,
        WorkflowAuditAction.AUTO_RELEASE_EXPIRY,
        WorkflowAuditAction.LABEL_SCANNED,
    }
)

ADMIN_ROLE_NAMES = frozenset({"Admin", "SubAdmin"})
IM_ROLE_NAMES = frozenset(
    {
        WORKFLOW_ROLE_DB_NAMES[WorkflowRole.IM],
        "InventoryManager",
    }
)
PD_ROLE_NAMES = frozenset(
    {
        WORKFLOW_ROLE_DB_NAMES[WorkflowRole.PD],
        "ProjectDirector",
        "ProjectManager",
    }
)
MAINTENANCE_ROLE_NAMES = frozenset({"Maintenance"})

PROGRESS_MILESTONES = (25, 50, 75)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role_names(user: Optional[User]) -> list[str]:
    if user is None:
        return []
    return [r.name for r in (user.roles or []) if r.name]


def _is_pd(user: User) -> bool:
    names = _role_names(user)
    return has_workflow_role(names, WorkflowRole.PD) or any(
        n in PD_ROLE_NAMES for n in names
    )


def users_with_role_names(session: Session, names: Iterable[str]) -> list[User]:
    wanted = {n.lower() for n in names if n}
    if not wanted:
        return []
    roles = session.exec(select(Role)).all()
    role_ids = [r.id for r in roles if r.id and (r.name or "").lower() in wanted]
    if not role_ids:
        return []
    links = session.exec(select(UserRole).where(col(UserRole.role_id).in_(role_ids))).all()
    users: list[User] = []
    seen: set[int] = set()
    for link in links:
        if link.user_id is None or int(link.user_id) in seen:
            continue
        user = session.get(User, link.user_id)
        if user and user.is_active and user.id is not None:
            seen.add(int(user.id))
            users.append(user)
    return users


def admin_users(session: Session) -> list[User]:
    return users_with_role_names(session, ADMIN_ROLE_NAMES)


def im_users(session: Session) -> list[User]:
    return users_with_role_names(session, IM_ROLE_NAMES)


def pd_users(session: Session) -> list[User]:
    return users_with_role_names(session, PD_ROLE_NAMES)


def maintenance_users(session: Session) -> list[User]:
    return users_with_role_names(session, MAINTENANCE_ROLE_NAMES)


def assigned_hm(session: Session, project: Optional[Project]) -> Optional[User]:
    if project is None or not project.assigned_hm_id:
        return None
    user = session.get(User, int(project.assigned_hm_id))
    if user and user.is_active:
        return user
    return None


def concerned_pds(session: Session, project: Optional[Project]) -> list[User]:
    if project is not None and project.owner_id:
        owner = session.get(User, int(project.owner_id))
        if owner and owner.is_active and _is_pd(owner):
            return [owner]
    return pd_users(session)


def load_project(session: Session, project_id: Optional[int]) -> Optional[Project]:
    if project_id is None:
        return None
    return session.get(Project, int(project_id))


def notify(
    session: Session,
    *,
    event_type: str,
    title: str,
    message: str,
    href: str = "/notifications",
    priority: str = "medium",
    actor: Optional[User] = None,
    exclude_actor: bool = True,
    confirmation_user_ids: Optional[Iterable[int]] = None,
    extra_user_ids: Optional[Iterable[int]] = None,
    roles: Optional[Iterable[str]] = None,
    include_admin: bool = False,
    include_im: bool = False,
    include_pd: bool = False,
    include_assigned_hm: bool = False,
    include_concerned_pd: bool = False,
    include_maintenance: bool = False,
    project: Optional[Project] = None,
    project_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    dedupe_key: Optional[str] = None,
) -> list[AppNotification]:
    """Insert one row per recipient. Never raises. Skips already-implemented event types."""
    try:
        return _notify(
            session,
            event_type=event_type,
            title=title,
            message=message,
            href=href,
            priority=priority,
            actor=actor,
            exclude_actor=exclude_actor,
            confirmation_user_ids=confirmation_user_ids,
            extra_user_ids=extra_user_ids,
            roles=roles,
            include_admin=include_admin,
            include_im=include_im,
            include_pd=include_pd,
            include_assigned_hm=include_assigned_hm,
            include_concerned_pd=include_concerned_pd,
            include_maintenance=include_maintenance,
            project=project,
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            dedupe_key=dedupe_key,
        )
    except Exception:
        logger.exception("Failed to emit notification %s", event_type)
        return []


def _notify(
    session: Session,
    *,
    event_type: str,
    title: str,
    message: str,
    href: str,
    priority: str,
    actor: Optional[User],
    exclude_actor: bool,
    confirmation_user_ids: Optional[Iterable[int]],
    extra_user_ids: Optional[Iterable[int]],
    roles: Optional[Iterable[str]],
    include_admin: bool,
    include_im: bool,
    include_pd: bool,
    include_assigned_hm: bool,
    include_concerned_pd: bool,
    include_maintenance: bool,
    project: Optional[Project],
    project_id: Optional[int],
    entity_type: Optional[str],
    entity_id: Optional[int],
    dedupe_key: Optional[str],
) -> list[AppNotification]:
    if event_type in EXISTING_EVENT_TYPES:
        return []

    proj = project or load_project(session, project_id)
    pid = int(proj.id) if proj is not None and proj.id is not None else (
        int(project_id) if project_id is not None else None
    )
    actor_id = int(actor.id) if actor is not None and actor.id is not None else None
    confirm = {int(uid) for uid in (confirmation_user_ids or []) if uid is not None}

    recipients: dict[int, User] = {}

    def _add(user: Optional[User]) -> None:
        if user is None or user.id is None or not user.is_active:
            return
        uid = int(user.id)
        if exclude_actor and actor_id is not None and uid == actor_id and uid not in confirm:
            return
        recipients[uid] = user

    for user in users_with_role_names(session, roles or []):
        _add(user)
    if include_admin:
        for user in admin_users(session):
            _add(user)
    if include_im:
        for user in im_users(session):
            _add(user)
    if include_pd:
        for user in pd_users(session):
            _add(user)
    if include_concerned_pd:
        for user in concerned_pds(session, proj):
            _add(user)
    if include_assigned_hm:
        _add(assigned_hm(session, proj))
    if include_maintenance:
        for user in maintenance_users(session):
            _add(user)
    for uid in extra_user_ids or []:
        if uid is None:
            continue
        _add(session.get(User, int(uid)))
    for uid in confirm:
        _add(session.get(User, uid))

    rows: list[AppNotification] = []
    now = _now()
    for uid, _user in recipients.items():
        if dedupe_key:
            existing = session.exec(
                select(AppNotification).where(
                    AppNotification.user_id == uid,
                    AppNotification.dedupe_key == dedupe_key,
                )
            ).first()
            if existing:
                continue
        row = AppNotification(
            user_id=uid,
            event_type=event_type,
            title=title[:255],
            message=message,
            href=(href or "/notifications")[:512],
            priority=priority if priority in {"high", "medium", "low"} else "medium",
            entity_type=entity_type,
            entity_id=int(entity_id) if entity_id is not None else None,
            actor_user_id=actor_id,
            project_id=pid,
            dedupe_key=dedupe_key,
            created_at=now,
        )
        session.add(row)
        rows.append(row)
    if rows:
        session.flush()
    return rows


def _audit_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _project_href(project_id: Optional[int]) -> str:
    if project_id is None:
        return "/projects"
    return f"/projects/{int(project_id)}"


def _project_label(session: Session, project: Optional[Project], project_id: Optional[int]) -> str:
    if project is not None and project.name:
        return project.name
    if project_id is not None:
        return f"Project #{int(project_id)}"
    return "Project"


def notify_from_audit(
    session: Session,
    event: Any,
    *,
    actor: Optional[User] = None,
) -> list[AppNotification]:
    """Map Spec 13 audit actions to Spec 14 gap notices. Skip existing inventory channels."""
    action = str(getattr(event, "action", "") or "").strip().upper()
    if not action or action in SKIP_AUDIT_ACTIONS:
        return []
    entity_type = str(getattr(event, "entity_type", "") or "").strip().lower()
    try:
        entity_id = int(getattr(event, "entity_id"))
    except (TypeError, ValueError):
        entity_id = None
    project_id = getattr(event, "project_id", None)
    project = load_project(session, project_id)
    label = _project_label(session, project, project_id)
    href = _project_href(project_id if entity_type == "project" or project_id else None)
    new_value = _audit_dict(getattr(event, "new_value", None))
    old_value = _audit_dict(getattr(event, "old_value", None))
    remarks = getattr(event, "remarks", None)

    common = dict(
        actor=actor,
        project=project,
        project_id=project_id,
        entity_type=entity_type or None,
        entity_id=entity_id,
    )

    if action == WorkflowAuditAction.PROJECT_CREATED:
        return notify(
            session,
            event_type="project_draft_submitted",
            title="Project draft submitted",
            message=f"{label} is awaiting approval",
            href=href,
            priority="high",
            include_admin=True,
            include_pd=True,
            include_assigned_hm=True,
            **common,
        )
    if action == WorkflowAuditAction.HM_ASSIGNED:
        new_hm = new_value.get("assigned_hm_id")
        old_hm = old_value.get("assigned_hm_id")
        extra = [int(new_hm)] if new_hm else []
        if old_hm and old_hm != new_hm:
            extra.append(int(old_hm))
        return notify(
            session,
            event_type="hm_assigned",
            title="Hierarchy manager assigned",
            message=f"{label} assigned to a hierarchy manager",
            href=href,
            priority="high",
            extra_user_ids=extra,
            include_concerned_pd=True,
            **common,
        )
    if action == WorkflowAuditAction.PROJECT_APPROVED:
        return notify(
            session,
            event_type="project_approved",
            title="Project approved",
            message=f"{label} was approved",
            href=href,
            priority="high",
            include_assigned_hm=True,
            include_concerned_pd=True,
            **common,
        )
    if action == WorkflowAuditAction.HIERARCHY_GENERATED:
        return notify(
            session,
            event_type="hierarchy_generated",
            title="Hierarchy generated",
            message=f"{label} is ready for inventory work",
            href=href,
            priority="medium",
            include_assigned_hm=True,
            include_concerned_pd=True,
            include_im=True,
            **common,
        )
    if action == WorkflowAuditAction.PROJECT_CANCELLED:
        extra: list[int] = []
        if project_id is not None:
            tasks = session.exec(
                select(InventoryRecallTask).where(
                    InventoryRecallTask.project_id == int(project_id)
                )
            ).all()
            extra = [
                int(t.assigned_developer_id)
                for t in tasks
                if getattr(t, "assigned_developer_id", None)
            ]
        return notify(
            session,
            event_type="project_cancelled",
            title="Project cancelled",
            message=f"{label} was cancelled — recall may be in progress",
            href=href,
            priority="high",
            include_assigned_hm=True,
            include_im=True,
            include_concerned_pd=True,
            include_admin=True,
            extra_user_ids=extra,
            **common,
        )
    if action == WorkflowAuditAction.ASSIGNED:
        dev_id = new_value.get("assigned_developer_id")
        prev = old_value.get("assigned_developer_id")
        extra = [int(dev_id)] if dev_id else []
        if prev and prev != dev_id:
            extra.append(int(prev))
        name = new_value.get("assigned_developer_name") or "developer"
        return notify(
            session,
            event_type="developer_assigned",
            title="Work assigned",
            message=f"You were assigned to a hierarchy item on {label}"
            if dev_id
            else f"{name} assigned on {label}",
            href=href if project_id else "/my-assignments",
            priority="high",
            extra_user_ids=extra,
            confirmation_user_ids=[int(dev_id)] if dev_id else None,
            **common,
        )
    if action == WorkflowAuditAction.UNASSIGNED:
        prev = old_value.get("assigned_developer_id")
        extra = [int(prev)] if prev else []
        return notify(
            session,
            event_type="developer_unassigned",
            title="Assignment removed",
            message=f"A hierarchy assignment on {label} was cleared",
            href=href if project_id else "/my-assignments",
            priority="high",
            extra_user_ids=extra,
            **common,
        )
    if action == WorkflowAuditAction.RESERVED:
        return notify(
            session,
            event_type="inventory_reserved",
            title="Inventory reserved",
            message=remarks or f"Stock reserved for {label}",
            href=href,
            priority="medium",
            include_assigned_hm=True,
            include_im=True,
            **common,
        )
    if action == WorkflowAuditAction.RELEASED:
        return notify(
            session,
            event_type="reservation_released",
            title="Reservation released",
            message=remarks or f"Reserved stock released on {label}",
            href=href,
            priority="medium",
            include_im=True,
            include_assigned_hm=True,
            **common,
        )
    if action == WorkflowAuditAction.RESERVATION_EXTENDED:
        return notify(
            session,
            event_type="reservation_extended",
            title="Reservation extended",
            message=remarks or f"A reservation on {label} was extended",
            href=href,
            priority="low",
            include_im=True,
            **common,
        )
    if action == WorkflowAuditAction.INSTALLATION_IN_PROGRESS:
        return notify(
            session,
            event_type="install_started",
            title="Installation started",
            message=f"Install started on {label}",
            href=href,
            priority="low",
            include_assigned_hm=True,
            **common,
        )
    if action == WorkflowAuditAction.UNDER_TESTING:
        result = str(new_value.get("test_result") or "").lower()
        failed = result == "fail"
        return notify(
            session,
            event_type="test_failed" if failed else "test_passed",
            title="Installation test failed" if failed else "Installation test passed",
            message=f"{'Fail' if failed else 'Pass'} recorded on {label}",
            href=href,
            priority="high" if failed else "medium",
            include_concerned_pd=True,
            include_assigned_hm=True,
            include_im=failed,
            **common,
        )
    if action == WorkflowAuditAction.COMPLETE_REPORTED:
        return notify(
            session,
            event_type="handover_requested",
            title="Verification requested",
            message=f"Developer reported installation complete on {label}",
            href="/verify-queue",
            priority="high",
            include_assigned_hm=True,
            **common,
        )
    if action == WorkflowAuditAction.INSTALLED_VERIFIED:
        return notify(
            session,
            event_type="verified_installed",
            title="Installation verified",
            message=f"Item verified installed on {label}",
            href=href,
            priority="medium",
            include_concerned_pd=True,
            extra_user_ids=[
                int(v)
                for v in [new_value.get("assigned_developer_id"), new_value.get("issued_to_user_id")]
                if v
            ],
            **common,
        )
    if action == WorkflowAuditAction.INSTALLATION_REJECTED:
        return notify(
            session,
            event_type="installation_rejected",
            title="Installation rejected",
            message=remarks or f"HM rejected installation on {label}",
            href="/my-assignments",
            priority="high",
            extra_user_ids=[
                int(v)
                for v in [new_value.get("assigned_developer_id"), new_value.get("issued_to_user_id")]
                if v
            ],
            **common,
        )
    if action == WorkflowAuditAction.RETURNED and entity_type == "inventory_rework":
        return notify(
            session,
            event_type="rework_returned",
            title="Rework item returned",
            message=f"A defective item was returned to IM on {label}",
            href="/inspect-queue",
            priority="high",
            include_im=True,
            **common,
        )
    if action == WorkflowAuditAction.RETURNED and entity_type == "inventory_recall":
        forced = bool(new_value.get("forced"))
        extra = []
        if project_id is not None:
            task = session.get(InventoryRecallTask, entity_id) if entity_id else None
            if task and task.assigned_developer_id:
                extra = [int(task.assigned_developer_id)]
        return notify(
            session,
            event_type="recall_force_return" if forced else "recall_returned",
            title="Recall force-return" if forced else "Recalled item returned",
            message=f"{'Force-returned' if forced else 'Developer returned'} a recalled item on {label}",
            href=href,
            priority="high",
            include_im=True,
            extra_user_ids=extra if forced else None,
            **common,
        )
    if action == WorkflowAuditAction.MODIFIED and entity_type == "inventory_recall":
        return notify(
            session,
            event_type="recall_inspected",
            title="Recall inspection complete",
            message=f"Recalled item disposition: {new_value.get('disposition') or 'updated'}",
            href=href,
            priority="medium",
            include_assigned_hm=True,
            include_concerned_pd=True,
            **common,
        )
    if action == WorkflowAuditAction.CONFIG_CHANGE_REQUESTED:
        return notify(
            session,
            event_type="config_change_requested",
            title="Configuration change requested",
            message=f"HM requested a configuration change on {label}",
            href=href,
            priority="high",
            include_admin=True,
            include_im=True,
            **common,
        )
    if action == WorkflowAuditAction.CONFIG_CHANGE_INVENTORY_RETURNED:
        return notify(
            session,
            event_type="config_change_inventory_returned",
            title="Config-change inventory returned",
            message=f"All project inventory returned for configuration change on {label}",
            href=href,
            priority="high",
            include_im=True,
            **common,
        )
    if action == WorkflowAuditAction.CONFIG_CHANGE_SUBMITTED:
        return notify(
            session,
            event_type="config_change_submitted",
            title="Configuration change submitted",
            message=f"Change request on {label} is ready for admin approval",
            href=href,
            priority="high",
            include_admin=True,
            **common,
        )
    if action == WorkflowAuditAction.CONFIG_CHANGE_APPROVED:
        return notify(
            session,
            event_type="config_change_approved",
            title="Configuration change approved",
            message=f"Admin approved the configuration change on {label}",
            href=href,
            priority="high",
            include_assigned_hm=True,
            include_concerned_pd=True,
            **common,
        )
    if action == WorkflowAuditAction.CONFIG_CHANGE_CANCELLED:
        return notify(
            session,
            event_type="config_change_cancelled",
            title="Configuration change withdrawn",
            message=f"Configuration change on {label} was cancelled",
            href=href,
            priority="medium",
            include_admin=True,
            include_im=True,
            **common,
        )
    if action == WorkflowAuditAction.CONFIG_CHANGE_NEW_PROJECT:
        return notify(
            session,
            event_type="config_change_successor",
            title="Successor project created",
            message=f"A new project was created from the configuration change on {label}",
            href=href,
            priority="medium",
            include_assigned_hm=True,
            include_admin=True,
            include_concerned_pd=True,
            include_im=True,
            **common,
        )
    if action == WorkflowAuditAction.LABEL_GENERATED:
        return notify(
            session,
            event_type="label_generated",
            title="Inventory labels generated",
            message=remarks or "New inventory labels were generated",
            href="/inventory",
            priority="low",
            include_im=True,
            **common,
        )
    if action in {WorkflowAuditAction.LABEL_PRINTED, WorkflowAuditAction.LABEL_REPRINTED}:
        return notify(
            session,
            event_type="label_printed",
            title="Inventory labels printed",
            message=remarks or "Inventory labels were printed",
            href="/inventory",
            priority="low",
            include_im=True,
            **common,
        )
    if action in {
        WorkflowAuditAction.LABEL_SUSPICIOUS_SCAN,
        WorkflowAuditAction.LABEL_INVESTIGATION_STARTED,
        WorkflowAuditAction.LABEL_DEACTIVATED,
        WorkflowAuditAction.LABEL_REPLACED,
    }:
        return notify(
            session,
            event_type="label_compromised",
            title="Inventory label security event",
            message=remarks or action.replace("_", " ").title(),
            href="/inventory",
            priority="high",
            include_im=True,
            include_admin=True,
            **common,
        )
    if action == WorkflowAuditAction.ASSEMBLED_INVENTORY:
        return notify(
            session,
            event_type="inventory_assembled",
            title="Parent inventory auto-assembled",
            message=remarks or f"Assembled inventory on {label}",
            href=href,
            priority="low",
            include_im=True,
            include_assigned_hm=True,
            **common,
        )
    if action == WorkflowAuditAction.DELETED and entity_type == "project":
        return notify(
            session,
            event_type="project_deleted",
            title="Project deleted",
            message=f"{label} was deleted",
            href="/projects",
            priority="high",
            include_assigned_hm=True,
            include_concerned_pd=True,
            include_admin=True,
            **common,
        )
    if action == WorkflowAuditAction.STATUS_CHANGED and entity_type == "project":
        new_status = str(new_value.get("status") or "")
        if new_status in {"COMPLETED", "READY_TO_DELIVER", "Completed"}:
            return notify(
                session,
                event_type="project_completed",
                title="Project completed",
                message=f"{label} reached completion",
                href=href,
                priority="high",
                include_concerned_pd=True,
                include_assigned_hm=True,
                include_admin=True,
                **common,
            )
        if new_status == "SUPERSEDED":
            return notify(
                session,
                event_type="project_superseded",
                title="Project superseded",
                message=f"{label} was superseded by a successor project",
                href=href,
                priority="medium",
                include_assigned_hm=True,
                include_concerned_pd=True,
                include_im=True,
                **common,
            )
        if new_status == "READY_FOR_INVENTORY":
            return notify(
                session,
                event_type="ready_for_inventory",
                title="Project ready for inventory",
                message=f"{label} can now reserve and issue stock",
                href=href,
                priority="medium",
                include_im=True,
                include_assigned_hm=True,
                **common,
            )
    if action == WorkflowAuditAction.MODIFIED and entity_type == "hierarchy_configuration":
        return notify(
            session,
            event_type="hierarchy_config_edited",
            title="Hierarchy configuration updated",
            message=remarks or "A hierarchy configuration was changed",
            href="/settings",
            priority="medium",
            include_admin=True,
            **common,
        )
    if action == WorkflowAuditAction.CREATED and entity_type == "hierarchy_configuration":
        return notify(
            session,
            event_type="hierarchy_config_created",
            title="Hierarchy configuration created",
            message=remarks or "A hierarchy configuration was created",
            href="/settings",
            priority="medium",
            include_admin=True,
            **common,
        )
    if action == WorkflowAuditAction.DELETED and entity_type == "hierarchy_configuration":
        return notify(
            session,
            event_type="hierarchy_config_deleted",
            title="Hierarchy configuration removed",
            message=remarks or "A hierarchy configuration was removed",
            href="/settings",
            priority="medium",
            include_admin=True,
            **common,
        )
    return []


def notify_progress_milestones(
    session: Session,
    project: Project,
    progress_pct: int,
    *,
    actor: Optional[User] = None,
) -> list[AppNotification]:
    rows: list[AppNotification] = []
    pct = int(progress_pct or 0)
    for mark in PROGRESS_MILESTONES:
        if pct < mark:
            continue
        key = f"project_progress:{project.id}:{mark}"
        rows.extend(
            notify(
                session,
                event_type="project_progress_milestone",
                title=f"Project reached {mark}%",
                message=f"{project.name or f'Project #{project.id}'} is at {pct}%",
                href=_project_href(project.id),
                priority="low",
                actor=actor,
                include_assigned_hm=True,
                include_concerned_pd=True,
                project=project,
                entity_type="project",
                entity_id=project.id,
                dedupe_key=key,
            )
        )
    return rows


def list_app_notifications(
    session: Session,
    user_id: int,
    *,
    unread_only: bool = False,
    search: Optional[str] = None,
    limit: int = 200,
) -> list[AppNotification]:
    stmt = select(AppNotification).where(AppNotification.user_id == int(user_id))
    if unread_only:
        stmt = stmt.where(AppNotification.read_at.is_(None))
    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                func.coalesce(AppNotification.title, "").ilike(like),
                func.coalesce(AppNotification.message, "").ilike(like),
                func.coalesce(AppNotification.event_type, "").ilike(like),
            )
        )
    stmt = stmt.order_by(col(AppNotification.created_at).desc(), col(AppNotification.id).desc())
    return list(session.exec(stmt.limit(limit)).all())


def mark_app_notification_read(
    session: Session, notice: AppNotification
) -> AppNotification:
    if notice.read_at is None:
        notice.read_at = _now()
        session.add(notice)
        session.commit()
        session.refresh(notice)
    return notice


def mark_all_app_notifications_read(session: Session, user_id: int) -> int:
    rows = session.exec(
        select(AppNotification).where(
            AppNotification.user_id == int(user_id),
            AppNotification.read_at.is_(None),
        )
    ).all()
    now = _now()
    for row in rows:
        row.read_at = now
        session.add(row)
    session.commit()
    return len(rows)


def notification_to_dict(row: AppNotification) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "event_type": row.event_type,
        "title": row.title,
        "message": row.message,
        "href": row.href,
        "priority": row.priority,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "actor_user_id": row.actor_user_id,
        "project_id": row.project_id,
        "created_at": row.created_at,
        "read_at": row.read_at,
    }
