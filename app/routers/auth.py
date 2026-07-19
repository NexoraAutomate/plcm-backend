"""
Authentication Router
Handles user login, logout, password changes, and role management
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, status, Header, Request, Response, Query
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlmodel import Session, select, SQLModel, func, col
from app.database import get_session
from app.models.tables import User, Role, Permission, UserLoginHistory, AuditLog
from app.schemas import schemas
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_user_from_token,
    get_user_permissions,
    check_role,
    check_permission,
    decode_token,
)
from datetime import datetime, timedelta, timezone
from app.services.sorting import apply_sort
from app.services.login_history_service import (
    record_login_attempt,
    new_session_id,
    close_open_sessions_for_user,
    close_session_by_id,
    client_ip,
)
from app.services.security_settings_service import (
    get_or_create_security_settings,
    update_security_settings,
)
from app.services.inactivity_service import deactivate_inactive_users
from app.services.audit_service import write_audit_log
from app.services.pagination import set_list_total_header

router = APIRouter(prefix="/auth", tags=["Authentication"])
oauth2_scheme:OAuth2PasswordBearer = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ACCOUNT_DEACTIVATED_MESSAGE = (
    "Your account has been deactivated. Please contact your system administrator."
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_locked(user: User) -> bool:
    if not user.locked_until:
        return False
    locked_until = user.locked_until
    if locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    return locked_until > _utcnow()


def authenticate_user(
    session: Session,
    username: str,
    password: str,
    request: Optional[Request] = None,
) -> tuple[User, str]:
    """
    Authenticate a user and record login history.
    Returns (user, session_id) on success; raises HTTPException on failure.
    """
    settings = get_or_create_security_settings(session)
    user = session.exec(select(User).where(User.username == username)).first()

    # Inactive check before credential validation (does not reveal password validity)
    if user is not None and not user.is_active:
        record_login_attempt(
            session,
            username=username,
            login_status="Failed",
            user=user,
            failure_reason="Inactive account",
            request=request,
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ACCOUNT_DEACTIVATED_MESSAGE,
        )

    if user is None or not verify_password(password, user.password or ""):
        if user is not None:
            user.failed_login_count = (user.failed_login_count or 0) + 1
            max_attempts = settings.max_login_attempts or 5
            if user.failed_login_count >= max_attempts:
                lock_minutes = settings.lockout_duration_minutes or 30
                user.locked_until = _utcnow() + timedelta(minutes=lock_minutes)
            session.add(user)
            record_login_attempt(
                session,
                username=username,
                login_status="Failed",
                user=user,
                failure_reason="Invalid password",
                request=request,
            )
            session.commit()
        else:
            record_login_attempt(
                session,
                username=username,
                login_status="Failed",
                failure_reason="Invalid username",
                request=request,
                commit=True,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if _is_locked(user):
        record_login_attempt(
            session,
            username=username,
            login_status="Failed",
            user=user,
            failure_reason="Locked account",
            request=request,
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is temporarily locked due to too many failed login attempts.",
        )

    session_id = new_session_id()
    now = _utcnow()
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_activity_at = now
    user.updated_at = now
    session.add(user)
    record_login_attempt(
        session,
        username=username,
        login_status="Success",
        user=user,
        request=request,
        session_id=session_id,
    )
    session.commit()
    session.refresh(user)
    return user, session_id


def build_token_response(user: User) -> schemas.TokenResponse:
    role_names = [role.name for role in user.roles]
    permissions = get_user_permissions(user)
    token_data = {
        "sub": str(user.id),
        "username": user.username,
        "roles": role_names,
        "permissions": permissions,
    }
    access_token = create_access_token(data=token_data, expires_delta=timedelta(days=30))
    return schemas.TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        username=user.username,
        email=user.email,
        roles=role_names,
        permissions=permissions,
    )

# ==================== DEPENDENCY FUNCTIONS ====================

def get_current_user(token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)) -> User:
    """Dependency to get current authenticated user from token."""
    # print("TOKEN RECEIVED:", token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )
    
    # token = extract_token_from_header(authorization)
    user = get_user_from_token(token, session)
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is inactive",
        )
    
    return user

def require_permission(permission: str):
    """Check permission from the live role assignment (DB), not only the JWT snapshot."""
    async def check_permission_dependency(
        token: str = Depends(oauth2_scheme),
        session: Session = Depends(get_session),
    ):
        payload = decode_token(token)
        user = session.get(User, payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User is inactive or not found",
            )
        # Prefer live DB permissions so role sync applies without forcing re-login
        if not check_permission(user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User does not have permission: {permission}",
            )
        return user
    return check_permission_dependency

def require_role(role: str):
    """Dependency to check if user has a specific role."""
    async def check_role_dependency(user: User = Depends(get_current_user),):
        if not check_role(user, role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User does not have role: {role}",
            )
        return user
    return check_role_dependency

# ==================== AUTHENTICATION ENDPOINTS ====================

@router.post("/login", response_model=schemas.TokenResponse)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    """Login endpoint. Returns JWT token with user info and permissions."""
    user, _session_id = authenticate_user(
        session, form_data.username, form_data.password, request=request
    )
    return build_token_response(user)


@router.post("/token/", response_model=schemas.TokenResponse)
def login_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    """OAuth2-compatible token endpoint (alias of /login)."""
    user, _session_id = authenticate_user(
        session, form_data.username, form_data.password, request=request
    )
    return build_token_response(user)

@router.post("/register", response_model=schemas.UserReadWithRoles)
def register(
    user_data: schemas.UserCreate, 
    session: Session = Depends(get_session)
    ):
    """Register a new user. New users get the 'Viewer' role by default."""
    existing_user = session.exec(select(User).where(User.username == user_data.username)).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )
    
    default_role = session.exec(select(Role).where(Role.name == "Viewer")).first()

    print("DEFAULT ROLE:", default_role)
    
    if not default_role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default role not initialized",
        )
    
    hashed_password = hash_password(user_data.password)
    db_user = User(
        username=user_data.username,
        email=user_data.email,
        full_name=user_data.full_name,
        is_active=True if user_data.is_active is None else user_data.is_active,
        password=hashed_password,
        updated_at=_utcnow(),
    )
    db_user.roles = [default_role]
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

@router.post("/change-password")
def change_password(
    change_pwd: schemas.ChangePasswordRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Change password for the current user."""
    if not verify_password(change_pwd.old_password, user.password or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    user.password = hash_password(change_pwd.new_password)
    user.updated_at = _utcnow()
    session.add(user)
    session.commit()
    return {"message": "Password changed successfully"}

@router.post("/logout")
def logout(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    session_id: Optional[str] = Query(default=None),
):
    """Record logout for the current user (closes open login-history sessions)."""
    now = _utcnow()
    user.last_logout_at = now
    user.last_activity_at = now
    user.updated_at = now
    session.add(user)
    if session_id:
        close_session_by_id(session, session_id)
    else:
        close_open_sessions_for_user(session, user.id)
    session.commit()
    return {"message": "Logged out successfully"}

# ==================== ROLE MANAGEMENT ENDPOINTS ====================

@router.get("/roles", response_model=List[schemas.RoleRead])
def list_roles(
    sort_by: str | None = None,
    sort_order: str | None = None,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session),
):
    """List all roles. Requires Admin role."""
    stmt = apply_sort(
        select(Role),
        Role,
        sort_by=sort_by,
        sort_order=sort_order,
        allowed_fields={"id", "name", "description"},
    )
    roles = session.exec(stmt).all()
    return roles

@router.get("/roles/{role_id}", response_model=schemas.RoleRead)
def get_role(role_id: int, user: User = Depends(require_role("Admin")), session: Session = Depends(get_session)): 
    """Get a specific role. Requires Admin role."""
    role = session.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role

def _resolve_permissions(session: Session, permission_ids: list[int] | None) -> list[Permission]:
    if not permission_ids:
        return []
    permissions = session.exec(select(Permission).where(Permission.id.in_(permission_ids))).all()
    if len(permissions) != len(set(permission_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more permission IDs are invalid",
        )
    return list(permissions)


@router.post("/roles", response_model=schemas.RoleRead)
def create_role(role_data: schemas.RoleCreate, user: User = Depends(require_role("Admin")), session: Session = Depends(get_session)):
    """Create a new role. Requires Admin role."""
    existing = session.exec(select(Role).where(Role.name == role_data.name)).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role already exists",
        )
    
    payload = role_data.model_dump(exclude={"permission_ids"})
    role = Role(**payload)
    if role_data.permission_ids is not None:
        role.permissions = _resolve_permissions(session, role_data.permission_ids)
    session.add(role)
    session.commit()
    session.refresh(role)
    
    return role

@router.put("/roles/{role_id}", response_model=schemas.RoleRead)
def update_role(
    role_id: int,
    role_data: schemas.RoleUpdate,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session)
):
    """Update a role. Requires Admin role."""
    role = session.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    data = role_data.model_dump(exclude_unset=True)
    permission_ids = data.pop("permission_ids", None)
    for key, value in data.items():
        setattr(role, key, value)
    if permission_ids is not None:
        role.permissions = _resolve_permissions(session, permission_ids)

    session.add(role)
    session.commit()
    session.refresh(role)
    
    return role


@router.put("/roles/{role_id}/permissions", response_model=schemas.RoleRead)
def update_role_permissions(
    role_id: int,
    payload: schemas.RolePermissionsUpdate,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session),
):
    """Replace a role's permissions. Requires Admin role."""
    role = session.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    role.permissions = _resolve_permissions(session, payload.permission_ids)
    session.add(role)
    session.commit()
    session.refresh(role)
    return role


@router.delete("/roles/{role_id}")
def delete_role(
    role_id: int,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session),
):
    """Delete a role if it is not assigned to any users. Requires Admin role."""
    role = session.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.name.lower() == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The Admin role cannot be deleted",
        )
    assigned_count = len(role.users or [])
    if assigned_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete role assigned to {assigned_count} user(s). Reassign users first.",
        )
    session.delete(role)
    session.commit()
    return {"message": f"Role '{role.name}' deleted successfully", "role_id": role_id}


# ==================== PERMISSION REGISTRY ====================

@router.get("/permission-registry", response_model=List[schemas.PermissionRead])
def list_permission_registry(
    sort_by: str | None = None,
    sort_order: str | None = None,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session),
):
    """List all permissions in the system. Requires Admin role."""
    stmt = apply_sort(
        select(Permission),
        Permission,
        sort_by=sort_by,
        sort_order=sort_order,
        allowed_fields={"id", "name", "description"},
    )
    return session.exec(stmt).all()


@router.post("/permission-registry", response_model=schemas.PermissionRead)
def create_permission(
    permission_data: schemas.PermissionCreate,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session),
):
    """Create a permission. Requires Admin role."""
    existing = session.exec(select(Permission).where(Permission.name == permission_data.name)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Permission already exists",
        )
    permission = Permission(**permission_data.model_dump())
    session.add(permission)
    session.commit()
    session.refresh(permission)
    return permission


@router.put("/permission-registry/{permission_id}", response_model=schemas.PermissionRead)
def update_permission(
    permission_id: int,
    permission_data: schemas.PermissionUpdate,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session),
):
    """Update a permission. Requires Admin role."""
    permission = session.get(Permission, permission_id)
    if not permission:
        raise HTTPException(status_code=404, detail="Permission not found")
    for key, value in permission_data.model_dump(exclude_unset=True).items():
        setattr(permission, key, value)
    session.add(permission)
    session.commit()
    session.refresh(permission)
    return permission


@router.delete("/permission-registry/{permission_id}")
def delete_permission(
    permission_id: int,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session),
):
    """Delete a permission if it is not assigned to any roles. Requires Admin role."""
    permission = session.get(Permission, permission_id)
    if not permission:
        raise HTTPException(status_code=404, detail="Permission not found")
    assigned_roles = len(permission.roles or [])
    if assigned_roles > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete permission assigned to {assigned_roles} role(s). Unassign it first.",
        )
    session.delete(permission)
    session.commit()
    return {"message": f"Permission '{permission.name}' deleted successfully", "permission_id": permission_id}


# ==================== ROLE ASSIGNMENT ====================
@router.post("/assign-role")
def assign_role_to_user(
    assignment: schemas.AssignRoleRequest,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session)
):
    """Set a user's role (replaces any existing roles). Requires Admin role."""
    target_user = session.get(User, assignment.user_id)
    if not target_user:
        raise HTTPException(
            status_code=404, 
            detail="User not found")
    
    role = session.get(Role, assignment.role_id)
    if not role:
        raise HTTPException(
            status_code=404, 
            detail="Role not found")
    
    is_admin = assignment.role_id == session.exec(select(Role.id).where(Role.name == "Admin")).first()
    if is_admin:
        raise HTTPException(
            status_code= status.HTTP_403_FORBIDDEN,
            detail= "Admin Already exists. Cannot assign Admin role to another user."
        )

    # Replace existing roles so edit-user changes the role instead of stacking
    target_user.roles = [role]
    session.add(target_user)
    session.commit()
    
    return {
        "message": f"Role '{role.name}' assigned to user '{target_user.username}'",
        "user_id": target_user.id,
        "role_id": role.id
    }

@router.delete("/remove-role")
def remove_role_from_user(
    assignment: schemas.AssignRoleRequest,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session)
):
    """Remove a role from a user. Requires Admin role."""
    target_user = session.get(User, assignment.user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    role = session.get(Role, assignment.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    
    if target_user.roles and check_role(target_user, "Admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot remove role from user with Admin role."
        )

    if role in target_user.roles:
        target_user.roles.remove(role)
        session.add(target_user)
        session.commit()
    
    return {
        "message": f"Role '{role.name}' removed from user '{target_user.username}'",
        "user_id": target_user.id,
        "role_id": role.id
    }

# ==================== CURRENT USER INFO ====================
@router.get("/me", response_model=schemas.CurrentUserRead)
@router.get("/me/", response_model=schemas.CurrentUserRead, include_in_schema=False)
def get_current_user_info(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
):
    """Get current logged-in user's information including roles and permissions."""
    payload = decode_token(token)
    user = session.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is inactive or not found",
        )
    return schemas.CurrentUserRead(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        created_at=user.created_at,
        roles=[role.name for role in user.roles],
        permissions=get_user_permissions(user),
    )

@router.get("/permissions", response_model=List[str])
def get_current_user_permissions(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get all permissions for the current user."""
    return get_user_permissions(user)

class MessageResponse(SQLModel):
    message: str

from app.auth import sync_roles_and_permissions
@router.get("/updateDefaultpermissions", response_model=MessageResponse)
def update_default_permissions(session: Session = Depends(get_session)):
    """Get all permissions for the current user."""
    sync_roles_and_permissions(session)
    return {"message": "Default permissions synchronized successfully"}


# ==================== SECURITY SETTINGS ====================

@router.get("/security-settings", response_model=schemas.SecuritySettingsRead)
def get_security_settings(
    user: User = Depends(require_permission("manage_settings")),
    session: Session = Depends(get_session),
):
    return get_or_create_security_settings(session)


@router.put("/security-settings", response_model=schemas.SecuritySettingsRead)
def put_security_settings(
    payload: schemas.SecuritySettingsUpdate,
    request: Request,
    user: User = Depends(require_permission("manage_settings")),
    session: Session = Depends(get_session),
):
    return update_security_settings(
        session,
        payload.model_dump(exclude_unset=True),
        actor=user,
        ip_address=client_ip(request),
    )


@router.post("/run-inactivity-check")
def run_inactivity_check(
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session),
    dry_run: bool = Query(default=False),
):
    """Manually run automatic inactivity deactivation (Admin only)."""
    return deactivate_inactive_users(session, actor=user, dry_run=dry_run)


# ==================== LOGIN HISTORY ====================

@router.get("/login-history", response_model=List[schemas.UserLoginHistoryRead])
def list_login_history(
    response: Response,
    skip: int = 0,
    limit: int = 50,
    user_id: Optional[int] = None,
    search: Optional[str] = None,
    login_status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session),
):
    """List login history across users. Admin only."""
    stmt = select(UserLoginHistory)
    if user_id is not None:
        stmt = stmt.where(UserLoginHistory.user_id == user_id)
    if login_status:
        stmt = stmt.where(UserLoginHistory.login_status == login_status)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            (UserLoginHistory.username.ilike(like))  # type: ignore[attr-defined]
            | (UserLoginHistory.ip_address.ilike(like))  # type: ignore[attr-defined]
            | (UserLoginHistory.browser.ilike(like))  # type: ignore[attr-defined]
            | (UserLoginHistory.device_name.ilike(like))  # type: ignore[attr-defined]
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
            "username",
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


@router.get("/audit-logs", response_model=List[schemas.AuditLogRead])
def list_audit_logs(
    response: Response,
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(require_permission("view_audit_logs")),
    session: Session = Depends(get_session),
):
    total = session.exec(select(func.count()).select_from(AuditLog)).one()
    set_list_total_header(response, total)
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)
    return session.exec(stmt).all()