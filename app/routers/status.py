from typing import List
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (Status, User)
from app.schemas import schemas
from app.routers.auth import require_permission
from app.services.pagination import paginated_query

router = APIRouter()

# ===================== STATUS ENDPOINTS =====================
@router.post("/statuses/", response_model=schemas.StatusRead, tags=["statuses"])
def create_status(status: schemas.StatusCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_statuses"))):
    db_status = Status(**status.model_dump())
    session.add(db_status)
    session.commit()
    session.refresh(db_status)
    return db_status

@router.post("/statuses/batch/", response_model=List[schemas.StatusRead], tags=["statuses"])
def create_statuses(
    statuses: List[schemas.StatusCreate],
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("create_statuses"))
):
    # print(current_user)
    db_statuses = [Status(**status.model_dump()) for status in statuses]
    
    
    try:
        session.add_all(db_statuses)
        session.commit()
        # print(f"Batch created")
    except Exception:
        session.rollback()
        raise

    # session.add_all(db_statuses)
    # session.commit()

    for db_status in db_statuses:
        session.refresh(db_status)
    
    return db_statuses

@router.get("/statuses/", response_model=List[schemas.StatusRead], tags=["statuses"])
def list_statuses(
    response: Response,
    status_type: str | None = None,
    skip: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_statuses")),
):
    where = Status.status_type == status_type if status_type else None
    return paginated_query(session, Status, skip, limit, response, where=where)

@router.get("/statuses/{status_id}/", response_model=schemas.StatusRead, tags=["statuses"])
def get_status(status_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_statuses"))):
    status = session.get(Status, status_id)
    if not status:
        raise HTTPException(status_code=404, detail="Status not found")
    return status

@router.put("/statuses/{status_id}/", response_model=schemas.StatusRead, tags=["statuses"])
def update_status(status_id: int, status: schemas.StatusUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_statuses"))):
    db_status = session.get(Status, status_id)
    if not db_status:
        raise HTTPException(status_code=404, detail="Status not found")
    for k, v in status.model_dump(exclude_unset=True).items():
        setattr(db_status, k, v)
    session.add(db_status)
    session.commit()
    session.refresh(db_status)
    return db_status

@router.delete("/statuses/{status_id}/", tags=["statuses"])
def delete_status(status_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_statuses"))):
    status = session.get(Status, status_id)
    if not status:
        raise HTTPException(status_code=404, detail="Status not found")
    session.delete(status)
    session.commit()
    return {"ok": True}