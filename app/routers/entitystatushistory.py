from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (EntityStatusHistory, User)
from app.schemas import schemas
from app.routers.auth import require_permission

router = APIRouter()

# ===================== ENTITY STATUS HISTORY ENDPOINTS =====================
@router.post("/entity-status-history/", response_model=schemas.EntityStatusHistoryRead, tags=["status-history"])
def create_status_history(history: schemas.EntityStatusHistoryCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_status_history"))):
    db_history = EntityStatusHistory(**history.model_dump())
    session.add(db_history)
    session.commit()
    session.refresh(db_history)
    return db_history

@router.get("/entity-status-history/", response_model=List[schemas.EntityStatusHistoryRead], tags=["status-history"])
def list_status_history(skip: int = 0, limit: int = 100, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_status_history"))):
    return session.exec(select(EntityStatusHistory).offset(skip).limit(limit)).all()

@router.get("/entity-status-history/{history_id}/", response_model=schemas.EntityStatusHistoryRead, tags=["status-history"])
def get_status_history(history_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_status_history"))):
    history = session.get(EntityStatusHistory, history_id)
    if not history:
        raise HTTPException(status_code=404, detail="Status history not found")
    return history

@router.put("/entity-status-history/{history_id}/", response_model=schemas.EntityStatusHistoryRead, tags=["status-history"])
def update_status_history(history_id: int, history: schemas.EntityStatusHistoryUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_status_history"))):
    db_history = session.get(EntityStatusHistory, history_id)
    if not db_history:
        raise HTTPException(status_code=404, detail="Status history not found")
    for k, v in history.model_dump(exclude_unset=True).items():
        setattr(db_history, k, v)
    session.add(db_history)
    session.commit()
    session.refresh(db_history)
    return db_history

@router.delete("/entity-status-history/{history_id}/", tags=["status-history"])
def delete_status_history(history_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_status_history"))):
    history = session.get(EntityStatusHistory, history_id)
    if not history:
        raise HTTPException(status_code=404, detail="Status history not found")
    session.delete(history)
    session.commit()
    return {"ok": True}
