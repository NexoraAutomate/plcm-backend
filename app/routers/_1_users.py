from typing import List
from fastapi import APIRouter, HTTPException, Depends, status, Response
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select, func
from app.database import get_session
from app.models.tables import (User, Role)
from app.schemas import schemas
from app.routers.auth import require_permission, get_current_user, hash_password
from app.auth import check_role
from app.services.pagination import set_list_total_header

router = APIRouter()


def _user_with_roles(user: User) -> schemas.UserWithRoles:
    return schemas.UserWithRoles(
        id=user.id,
        username=user.username,
        full_name=user.full_name or "",
        email=user.email,
        is_active=user.is_active,
        roles=[role.name for role in user.roles],
    )


# ===================== USER ENDPOINTS =====================
@router.post("/users/", response_model=schemas.UserRead, tags=["users"])
def create_user(
    user: schemas.UserCreate, 
    session: Session = Depends(get_session), 
    # current_user: User = Depends(require_permission("create_users"))
):
    print("start")

    existing_user = session.exec(select(User).where(User.username == user.username)).first()
    print("1st")
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail= "Username already exists. Please choose a different username."
        )
    # Check if user role as Admin alredy exists in whole database, 
    # if yes then do not allow to create another user with Admin role. 
    # This is to ensure that there is only one Admin user in the system.
    admin_user = session.exec(select(User).where(User.roles.any(Role.name == "Admin"))).first()
    if admin_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail= "An Admin user already exists. Cannot create another user with Admin role."
        )
    
    default_role = session.exec(select(Role).where(Role.name == "Admin")).first()

    if not default_role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default role 'Viewer' not found. Please ensure it exists in the database."
        )
    
    hashed_password= hash_password(user.password)
    db_user = User(
        username=user.username,
        full_name= user.full_name,
        email= user.email,
        is_active=True,
        password = hashed_password,
    )
    db_user.roles = [default_role]
    # db_user = User(**user.model_dump())
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

@router.get("/users/", response_model=List[schemas.UserWithRoles], tags=["users"])
def list_users(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_users")),
):
    total = session.exec(select(func.count()).select_from(User)).one()
    set_list_total_header(response, total)
    users = session.exec(
        select(User)
        .options(selectinload(User.roles))
        .order_by(User.id.asc())
        .offset(skip)
        .limit(limit)
    ).all()
    return [_user_with_roles(user) for user in users]

@router.get("/users/with-roles/", response_model=List[schemas.UserWithRoles], tags=["users"])
def list_users_with_roles(
    skip: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_users")),
):
    users = session.exec(
        select(User)
        .options(selectinload(User.roles))
        .order_by(User.id.asc())
        .offset(skip)
        .limit(limit)
    ).all()
    return [_user_with_roles(user) for user in users]

@router.get("/users/{user_id}/", response_model=schemas.UserReadWithRoles, tags=["users"])
def get_user(user_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_users"))):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.put("/users/{user_id}/", response_model=schemas.UserRead, tags=["users"])
def update_user(user_id: int, user: schemas.UserUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_users"))):
    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    update_data = user.model_dump(exclude_unset=True)
    if "password" in update_data:
        password = update_data.pop("password")
        if password:
            db_user.password = hash_password(password)
    for k, v in update_data.items():
        setattr(db_user, k, v)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

@router.delete("/users/{user_id}/", tags=["users"])
def delete_user(user_id: int, session: Session = Depends(get_session), 
                # current_user: User = Depends(require_permission("delete_users"))
                ):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # Prevent deletion of users with Admin role

    if user.roles and check_role(user, "Admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete user with Admin role. Please remove Admin role before deletion."
        )

    user.roles.clear()
    session.delete(user)
    session.commit()
    return {"ok": True}

@router.get("/users/{user_id}/projects/", response_model=List[schemas.ProjectRead], tags=["users"])
def list_user_projects(user_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_users"))):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.projects

