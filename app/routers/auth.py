"""
Authentication Router
Handles user login, logout, password changes, and role management
"""

from typing import List
from fastapi import APIRouter, HTTPException, Depends, status, Header
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlmodel import Session, select, SQLModel
from app.database import get_session
from app.models.tables import User, Role, Permission
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
from datetime import timedelta

router = APIRouter(prefix="/auth", tags=["Authentication"])
oauth2_scheme:OAuth2PasswordBearer = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

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
    """Check permission from JWT (fast) then load a minimal user row."""
    async def check_permission_dependency(
        token: str = Depends(oauth2_scheme),
        session: Session = Depends(get_session),
    ):
        payload = decode_token(token)
        if permission not in payload.get("permissions", []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User does not have permission: {permission}",
            )
        user = session.get(User, payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User is inactive or not found",
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
def login(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    """Login endpoint. Returns JWT token with user info and permissions."""
    user = session.exec(select(User).where(User.username == form_data.username)).first()
    if not user or not verify_password(form_data.password, user.password or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
        )
    
    role_names = [role.name for role in user.roles]
    permissions = get_user_permissions(user)
    
    """Create JWT access Token"""

    token_data = {
        "sub": str(user.id),
        "username": user.username,
        "roles": role_names,
        "permissions": permissions
    }
    access_token = create_access_token(data=token_data, expires_delta=timedelta(days=30))
    
    return schemas.TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        username=user.username,
        email=user.email,
        roles=role_names,
        permissions=permissions
    )


@router.post("/token/", response_model=schemas.TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    """Login endpoint. Returns JWT token with user info and permissions."""
    user = session.exec(select(User).where(User.username == form_data.username)).first()
    if not user or not verify_password(form_data.password, user.password or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
        )
    
    role_names = [role.name for role in user.roles]
    permissions = get_user_permissions(user)
    
    """Create JWT access Token"""

    token_data = {
        "sub": str(user.id),
        "username": user.username,
        "roles": role_names,
        "permissions": permissions
    }
    access_token = create_access_token(data=token_data, expires_delta=timedelta(days=30))
    
    return schemas.TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        username=user.username,
        email=user.email,
        roles=role_names,
        permissions=permissions
    )

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
    
    default_role = session.exec(select(Role).where(Role.name == "Admin")).first()

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
        is_active=True,
        password=hashed_password
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
    session.add(user)
    session.commit()
    return {"message": "Password changed successfully"}

# ==================== ROLE MANAGEMENT ENDPOINTS ====================

@router.get("/roles", response_model=List[schemas.RoleRead])
def list_roles(user: User = Depends(require_role("Admin")), session: Session = Depends(get_session)):
    """List all roles. Requires Admin role."""
    roles = session.exec(select(Role)).all()
    return roles

@router.get("/roles/{role_id}", response_model=schemas.RoleRead)
def get_role(role_id: int, user: User = Depends(require_role("Admin")), session: Session = Depends(get_session)): 
    """Get a specific role. Requires Admin role."""
    role = session.get(Role, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role

@router.post("/roles", response_model=schemas.RoleRead)
def create_role(role_data: schemas.RoleCreate, user: User = Depends(require_role("Admin")), session: Session = Depends(get_session)):
    """Create a new role. Requires Admin role."""
    existing = session.exec(select(Role).where(Role.name == role_data.name)).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role already exists",
        )
    
    role = Role(**role_data.model_dump())
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
    
    for key, value in role_data.model_dump(exclude_unset=True).items():
        setattr(role, key, value)

    session.add(role)
    session.commit()
    session.refresh(role)
    
    return role

# ==================== ROLE ASSIGNMENT ====================
@router.post("/assign-role")
def assign_role_to_user(
    assignment: schemas.AssignRoleRequest,
    user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session)
):
    """Assign a role to a user. Requires Admin role."""
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

    if role not in target_user.roles:
        target_user.roles.append(role)  
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
    
    if user.roles and check_role(user, "Admin"):
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
        roles=payload.get("roles", []),
        permissions=payload.get("permissions", []),
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