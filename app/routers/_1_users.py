from typing import List, Optional
from datetime import datetime, timezone, date
from fastapi import APIRouter, HTTPException, Depends, status, Response, Request, Query, File, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select, func, col
from app.database import get_session
from app.models.tables import AppNotification, User, Role, UserLoginHistory
from app.schemas import schemas
from app.routers.auth import require_permission, require_any_role, require_role, get_current_user
from app.auth import (
    check_role,
    check_any_role,
    hash_password,
    PRIVILEGED_ROLE_NAMES,
    initialize_roles_and_permissions,
    sync_roles_and_permissions,
)
from app.services.pagination import set_list_total_header
from app.services.sorting import apply_sort
from app.services.audit_service import write_audit_log
from app.services.login_history_service import close_open_sessions_for_user, client_ip
from app.services.password_policy_service import enforce_password_policy, set_user_password
from app.services.user_avatar import save_user_avatar, clear_user_avatar, resolve_avatar_file
from app.services.workflow_demo_users import (
    list_workflow_demo_user_options,
    seed_workflow_demo_users,
)
from app.services.security_settings_service import require_admin_super_password


def _require_test_data_super_password(session: Session, super_password: Optional[str]) -> None:
    ok, status_code, detail = require_admin_super_password(session, super_password)
    if not ok:
        raise HTTPException(status_code=status_code, detail=detail)

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _user_with_roles(user: User) -> schemas.UserWithRoles:
    return schemas.UserWithRoles(
        id=user.id,
        username=user.username,
        full_name=user.full_name or "",
        email=user.email,
        is_active=user.is_active,
        avatar_url=user.avatar_url,
        roles=[role.name for role in user.roles],
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
        last_logout_at=user.last_logout_at,
        last_activity_at=user.last_activity_at,
        failed_login_count=user.failed_login_count or 0,
        created_by_id=user.created_by_id,
    )


def _activity_summary(session: Session, user: User) -> schemas.UserActivitySummary:
    success_count = session.exec(
        select(func.count()).where(
            UserLoginHistory.user_id == user.id,
            UserLoginHistory.login_status == "Success",
        )
    ).one()
    failed_count = session.exec(
        select(func.count()).where(
            UserLoginHistory.user_id == user.id,
            UserLoginHistory.login_status == "Failed",
        )
    ).one()
    last_success = session.exec(
        select(UserLoginHistory)
        .where(
            UserLoginHistory.user_id == user.id,
            UserLoginHistory.login_status == "Success",
        )
        .order_by(UserLoginHistory.login_time.desc())
    ).first()

    return schemas.UserActivitySummary(
        last_login=user.last_login_at or (last_success.login_time if last_success else None),
        last_logout=user.last_logout_at,
        last_activity=user.last_activity_at
        or (last_success.last_activity if last_success else None)
        or user.last_login_at,
        last_ip_address=last_success.ip_address if last_success else None,
        last_device=last_success.device_name if last_success else None,
        browser=last_success.browser if last_success else None,
        operating_system=last_success.operating_system if last_success else None,
        total_login_count=int(success_count or 0),
        failed_login_count=int(failed_count or 0),
        created_at=user.created_at,
        updated_at=user.updated_at,
        created_by_id=user.created_by_id,
        is_active=user.is_active,
    )


# ===================== USER ENDPOINTS =====================
@router.post("/users/", response_model=schemas.UserRead, tags=["users"])
def create_user(
    user: schemas.UserCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("create_users")),
):
    existing_user = session.exec(select(User).where(User.username == user.username)).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists. Please choose a different username.",
        )

    default_role = session.exec(select(Role).where(Role.name == "Viewer")).first()
    if not default_role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default role 'Viewer' not found. Please ensure it exists in the database.",
        )

    enforce_password_policy(session, user.password)
    hashed_password = hash_password(user.password)
    db_user = User(
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        is_active=True if user.is_active is None else user.is_active,
        password=hashed_password,
        password_changed_at=_utcnow(),
        created_by_id=current_user.id,
        updated_at=_utcnow(),
    )
    db_user.roles = [default_role]
    session.add(db_user)
    session.flush()
    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="user_created",
        title="New user created",
        message=db_user.full_name or db_user.username,
        href="/settings",
        priority="medium",
        actor=current_user,
        include_admin=True,
        entity_type="user",
        entity_id=db_user.id,
    )
    session.commit()
    session.refresh(db_user)
    return db_user


@router.post(
    "/users/test-data/unlock/",
    response_model=schemas.TestDataUnlockRead,
    tags=["users"],
)
def unlock_test_data_tools(
    payload: schemas.TestDataUnlockRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("Admin")),
):
    """Admin-only: verify super password before exposing Test Data tools."""
    _ = current_user
    _require_test_data_super_password(session, payload.super_password)
    return schemas.TestDataUnlockRead(unlocked=True)


@router.get(
    "/users/seed-demo-roles/options/",
    response_model=schemas.WorkflowDemoUserOptionsRead,
    tags=["users"],
)
def get_seed_demo_roles_options(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("Admin")),
    x_admin_super_password: Optional[str] = Query(
        default=None,
        alias="super_password",
        description="Admin super password required for Test Data tools",
    ),
):
    """Admin-only: workflow demo accounts available for Test Data seeding."""
    _ = current_user
    _require_test_data_super_password(session, x_admin_super_password)
    options = list_workflow_demo_user_options(session)
    return schemas.WorkflowDemoUserOptionsRead(
        users=[
            schemas.WorkflowDemoUserOptionRead(
                username=item.username,
                full_name=item.full_name,
                email=item.email,
                role=item.role,
                password=item.password,
                exists=item.exists,
                is_active=item.is_active,
                user_id=item.user_id,
                role_missing=item.role_missing,
            )
            for item in options
        ]
    )


@router.post(
    "/users/seed-demo-roles/",
    response_model=schemas.WorkflowDemoUserSeedRead,
    tags=["users"],
)
def seed_demo_roles(
    payload: schemas.WorkflowDemoUserSeedRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("Admin")),
):
    """Admin-only: create/refresh all or selected workflow demo role users."""
    _require_test_data_super_password(session, payload.super_password)
    if not payload.dry_run and (payload.confirm or "").strip().upper() != "SEED":
        raise HTTPException(
            status_code=400,
            detail='Confirmation required: set confirm to "SEED" to apply',
        )

    # Ensure ME/FSE/IE (+ other default roles) exist before creating users.
    initialize_roles_and_permissions(session)
    sync_roles_and_permissions(session)

    try:
        result = seed_workflow_demo_users(
            session,
            usernames=payload.usernames,
            roles=payload.roles,
            force=True,
            dry_run=payload.dry_run,
            commit=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not payload.dry_run:
        write_audit_log(
            session,
            action="users_seed_demo_roles",
            actor=current_user,
            resource_type="user",
            details=(
                f"created={result.created} updated={result.updated} "
                f"skipped={result.skipped} "
                f"usernames={payload.usernames or 'all'} "
                f"roles={payload.roles or 'all'}"
            ),
            commit=False,
        )
        session.commit()

    return schemas.WorkflowDemoUserSeedRead(
        dry_run=result.dry_run,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        items=[
            schemas.WorkflowDemoUserSeedItemRead(
                username=item.username,
                role=item.role,
                action=item.action,
                reason=item.reason,
                user_id=item.user_id,
            )
            for item in result.items
        ],
    )


@router.get("/users/stats/summary", response_model=schemas.UserStatsSummary, tags=["users"])
def users_stats_summary(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_users")),
):
    total = session.exec(select(func.count()).select_from(User)).one()
    active = session.exec(select(func.count()).where(User.is_active == True)).one()  # noqa: E712
    inactive = session.exec(select(func.count()).where(User.is_active == False)).one()  # noqa: E712
    currently_logged_in = session.exec(
        select(func.count()).where(
            UserLoginHistory.login_status == "Success",
            UserLoginHistory.logout_time.is_(None),  # type: ignore[union-attr]
        )
    ).one()
    today = date.today()
    day_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    failed_today = session.exec(
        select(func.count()).where(
            UserLoginHistory.login_status == "Failed",
            UserLoginHistory.login_time >= day_start,
        )
    ).one()
    return schemas.UserStatsSummary(
        total_users=int(total or 0),
        active_users=int(active or 0),
        inactive_users=int(inactive or 0),
        currently_logged_in=int(currently_logged_in or 0),
        failed_logins_today=int(failed_today or 0),
    )


@router.get("/users/", response_model=List[schemas.UserWithRoles], tags=["users"])
def list_users(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    sort_by: str | None = None,
    sort_order: str | None = None,
    is_active: Optional[bool] = Query(default=None),
    search: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_users")),
):
    stmt = select(User).options(selectinload(User.roles))
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (User.username.ilike(like))  # type: ignore[attr-defined]
            | (User.full_name.ilike(like))  # type: ignore[attr-defined]
            | (User.email.ilike(like))  # type: ignore[attr-defined]
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = session.exec(count_stmt).one()
    set_list_total_header(response, total)

    stmt = apply_sort(
        stmt,
        User,
        sort_by=sort_by,
        sort_order=sort_order,
        allowed_fields={
            "id",
            "username",
            "full_name",
            "email",
            "is_active",
            "created_at",
            "last_login_at",
        },
        default_order=[User.id.asc()],
    )
    users = session.exec(stmt.offset(skip).limit(limit)).all()
    return [_user_with_roles(user) for user in users]


@router.get("/users/with-roles/", response_model=List[schemas.UserWithRoles], tags=["users"])
def list_users_with_roles(
    skip: int = 0,
    limit: int = 100,
    sort_by: str | None = None,
    sort_order: str | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_users")),
):
    stmt = select(User).options(selectinload(User.roles))
    stmt = apply_sort(
        stmt,
        User,
        sort_by=sort_by,
        sort_order=sort_order,
        allowed_fields={"id", "username", "full_name", "email", "is_active", "created_at"},
        default_order=[User.id.asc()],
    )
    users = session.exec(stmt.offset(skip).limit(limit)).all()
    return [_user_with_roles(user) for user in users]


@router.get("/users/{user_id}/avatar/", tags=["users"])
def get_user_avatar(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    avatar_url = user.avatar_url
    if not avatar_url:
        raise HTTPException(status_code=404, detail="Avatar not found")
    if avatar_url.startswith(("http://", "https://")):
        return RedirectResponse(avatar_url)
    file_path = resolve_avatar_file(avatar_url)
    if not file_path:
        raise HTTPException(status_code=404, detail="Avatar file not found")
    return FileResponse(file_path)


@router.post("/users/{user_id}/avatar/", tags=["users"])
async def upload_user_avatar(
    user_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_users")),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    updated = await save_user_avatar(session, user, file)
    return {"avatar_url": updated.avatar_url}


@router.delete("/users/{user_id}/avatar/", tags=["users"])
def delete_user_avatar(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_users")),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    updated = clear_user_avatar(session, user)
    return {"avatar_url": updated.avatar_url}


@router.get("/users/{user_id}/", response_model=schemas.UserReadWithRoles, tags=["users"])
def get_user(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_users")),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get(
    "/users/{user_id}/activity/",
    response_model=schemas.UserActivitySummary,
    tags=["users"],
)
def get_user_activity(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_any_role("Admin", "SubAdmin")),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _activity_summary(session, user)


@router.get(
    "/users/{user_id}/login-history/",
    response_model=List[schemas.UserLoginHistoryRead],
    tags=["users"],
)
def get_user_login_history(
    user_id: int,
    response: Response,
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    login_status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_any_role("Admin", "SubAdmin")),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    stmt = select(UserLoginHistory).where(UserLoginHistory.user_id == user_id)
    if login_status:
        stmt = stmt.where(UserLoginHistory.login_status == login_status)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (UserLoginHistory.ip_address.ilike(like))  # type: ignore[attr-defined]
            | (UserLoginHistory.browser.ilike(like))  # type: ignore[attr-defined]
            | (UserLoginHistory.device_name.ilike(like))  # type: ignore[attr-defined]
            | (UserLoginHistory.failure_reason.ilike(like))  # type: ignore[attr-defined]
        )
    if date_from is not None:
        stmt = stmt.where(UserLoginHistory.login_time >= date_from)
    if date_to is not None:
        stmt = stmt.where(UserLoginHistory.login_time <= date_to)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = session.exec(count_stmt).one()
    set_list_total_header(response, total)

    stmt = apply_sort(
        stmt,
        UserLoginHistory,
        sort_by=sort_by,
        sort_order=sort_order,
        allowed_fields={
            "id",
            "login_time",
            "logout_time",
            "login_status",
            "ip_address",
            "browser",
            "operating_system",
            "last_activity",
            "session_duration",
        },
        default_order=[UserLoginHistory.login_time.desc()],
    )
    return session.exec(stmt.offset(skip).limit(limit)).all()


@router.put("/users/{user_id}/", response_model=schemas.UserRead, tags=["users"])
def update_user(
    user_id: int,
    user: schemas.UserUpdate,
    request: Request,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_users")),
):
    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user.model_dump(exclude_unset=True)
    previous_active = db_user.is_active

    if "is_active" in update_data and not check_any_role(current_user, ["Admin", "SubAdmin"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators may activate or deactivate users.",
        )

    # SubAdmin cannot activate/deactivate Admin or SubAdmin accounts
    if (
        "is_active" in update_data
        and not check_role(current_user, "Admin")
        and any(r.name in PRIVILEGED_ROLE_NAMES for r in (db_user.roles or []))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin can activate or deactivate Admin or SubAdmin users.",
        )

    if "password" in update_data:
        password = update_data.pop("password")
        if password:
            # Admin/SubAdmin resets from Settings may reuse known demo passwords;
            # still enforce complexity, but skip history blocking.
            bypass_history = check_any_role(current_user, ["Admin", "SubAdmin"])
            set_user_password(
                session,
                db_user,
                password,
                bypass_history=bypass_history,
            )

    for k, v in update_data.items():
        setattr(db_user, k, v)

    db_user.updated_at = _utcnow()
    session.add(db_user)

    if "is_active" in update_data and update_data["is_active"] != previous_active:
        action = "User Activated" if update_data["is_active"] else "User Deactivated"
        write_audit_log(
            session,
            action=action,
            actor=current_user,
            resource_type="user",
            resource_id=db_user.id,
            previous_value=previous_active,
            new_value=update_data["is_active"],
            ip_address=client_ip(request),
        )
        if update_data["is_active"] is False:
            close_open_sessions_for_user(session, db_user.id)

    from app.services.app_notification_service import notify

    if "is_active" in update_data and update_data["is_active"] != previous_active:
        notify(
            session,
            event_type="user_activated" if update_data["is_active"] else "user_deactivated",
            title="Account activated" if update_data["is_active"] else "Account deactivated",
            message=db_user.full_name or db_user.username,
            href="/settings",
            priority="medium",
            actor=current_user,
            include_admin=True,
            confirmation_user_ids=[int(db_user.id)] if update_data["is_active"] else None,
            extra_user_ids=[int(db_user.id)] if update_data["is_active"] else None,
            entity_type="user",
            entity_id=db_user.id,
        )
    else:
        notify(
            session,
            event_type="user_edited",
            title="User updated",
            message=db_user.full_name or db_user.username,
            href="/settings",
            priority="medium",
            actor=current_user,
            include_admin=True,
            entity_type="user",
            entity_id=db_user.id,
        )

    session.commit()
    session.refresh(db_user)
    return db_user


@router.delete("/users/{user_id}/", tags=["users"])
def delete_user(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("delete_users")),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.roles and check_role(user, "Admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete user with Admin role. Please remove Admin role before deletion.",
        )

    if user.roles and check_role(user, "SubAdmin") and not check_role(current_user, "Admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin can delete SubAdmin users.",
        )

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="user_deleted",
        title="User deleted",
        message=user.full_name or user.username,
        href="/settings",
        priority="high",
        actor=current_user,
        include_admin=True,
        entity_type="user",
        entity_id=user_id,
    )
    owned = session.exec(
        select(AppNotification).where(AppNotification.user_id == user_id)
    ).all()
    for row in owned:
        session.delete(row)
    acted = session.exec(
        select(AppNotification).where(AppNotification.actor_user_id == user_id)
    ).all()
    for row in acted:
        row.actor_user_id = None
        session.add(row)
    user.roles.clear()
    session.delete(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot delete this user because they are still linked to other records "
                "(for example inventory assignments or workflow history). "
                "Deactivate the user instead."
            ),
        )
    return {"ok": True}


@router.get("/users/{user_id}/projects/", response_model=List[schemas.ProjectRead], tags=["users"])
def list_user_projects(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_users")),
):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.projects
