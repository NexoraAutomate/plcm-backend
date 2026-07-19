from typing import List, Optional
from datetime import datetime, timezone, date
from fastapi import APIRouter, HTTPException, Depends, status, Response, Request, Query
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select, func, col
from app.database import get_session
from app.models.tables import User, Role, UserLoginHistory
from app.schemas import schemas
from app.routers.auth import require_permission, get_current_user, require_role
from app.auth import check_role, hash_password
from app.services.pagination import set_list_total_header
from app.services.sorting import apply_sort
from app.services.audit_service import write_audit_log
from app.services.login_history_service import close_open_sessions_for_user, client_ip

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

    hashed_password = hash_password(user.password)
    db_user = User(
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        is_active=True if user.is_active is None else user.is_active,
        password=hashed_password,
        created_by_id=current_user.id,
        updated_at=_utcnow(),
    )
    db_user.roles = [default_role]
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


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
        allowed_fields={"id", "username", "full_name", "email", "is_active"},
        default_order=[User.id.asc()],
    )
    users = session.exec(stmt.offset(skip).limit(limit)).all()
    return [_user_with_roles(user) for user in users]


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
    current_user: User = Depends(require_role("Admin")),
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
    current_user: User = Depends(require_role("Admin")),
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

    if "is_active" in update_data and not check_role(current_user, "Admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators may activate or deactivate users.",
        )

    if "password" in update_data:
        password = update_data.pop("password")
        if password:
            db_user.password = hash_password(password)

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

    user.roles.clear()
    session.delete(user)
    session.commit()
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
