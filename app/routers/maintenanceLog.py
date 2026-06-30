from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (MaintenanceLog, User)
from app.schemas import schemas
from app.routers.auth import require_permission

router = APIRouter( tags=["maintenance_old"])

# ===================== MAINTENANCE LOG ENDPOINTS =====================
@router.post("/maintenance-logs/", response_model=schemas.MaintenanceLogRead)
def create_maintenance_log(log: schemas.MaintenanceLogCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_maintenance"))):
    db_log = MaintenanceLog(**log.model_dump())
    session.add(db_log)
    session.commit()
    session.refresh(db_log)
    return db_log

@router.get("/maintenance-logs/", response_model=List[schemas.MaintenanceLogRead])
def list_maintenance_logs(skip: int = 0, limit: int = 100, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_maintenance"))):
    return session.exec(select(MaintenanceLog).offset(skip).limit(limit)).all()

@router.get("/maintenance-logs/{log_id}/", response_model=schemas.MaintenanceLogRead)
def get_maintenance_log(log_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_maintenance"))):
    log = session.get(MaintenanceLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Maintenance log not found")
    return log

@router.put("/maintenance-logs/{log_id}/", response_model=schemas.MaintenanceLogRead)
def update_maintenance_log(log_id: int, log: schemas.MaintenanceLogUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_maintenance"))):
    db_log = session.get(MaintenanceLog, log_id)
    if not db_log:
        raise HTTPException(status_code=404, detail="Maintenance log not found")
    for k, v in log.model_dump(exclude_unset=True).items():
        setattr(db_log, k, v)
    session.add(db_log)
    session.commit()
    session.refresh(db_log)
    return db_log

@router.delete("/maintenance-logs/{log_id}/")
def delete_maintenance_log(log_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_maintenance"))):
    log = session.get(MaintenanceLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Maintenance log not found")
    session.delete(log)
    session.commit()
    return {"ok": True}