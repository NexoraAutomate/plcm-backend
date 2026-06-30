from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (User)
from app.schemas import schemas

router = APIRouter()
# ===================== USER ENDPOINTS =====================
@router.post("/users/", response_model=schemas.UserRead, tags=["users"])
def create_user(user: schemas.UserCreate, session: Session = Depends(get_session)):
    db_user = User(**user.model_dump())
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

@router.get("/users/", response_model=List[schemas.UserRead], tags=["users"])
def list_users(skip: int = 0, limit: int = 100, session: Session = Depends(get_session)):
    return session.exec(select(User).offset(skip).limit(limit)).all()

@router.get("/users/{user_id}/", response_model=schemas.UserRead, tags=["users"])
def get_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.put("/users/{user_id}/", response_model=schemas.UserRead, tags=["users"])
def update_user(user_id: int, user: schemas.UserUpdate, session: Session = Depends(get_session)):
    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    for k, v in user.dict(exclude_unset=True).items():
        setattr(db_user, k, v)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

@router.delete("/users/{user_id}/", tags=["users"])
def delete_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    session.delete(user)
    session.commit()
    return {"ok": True}

@router.get("/users/{user_id}/projects/", response_model=List[schemas.ProjectRead], tags=["users"])
def list_user_projects(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.projects

