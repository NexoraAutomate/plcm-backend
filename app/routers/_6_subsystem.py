from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (Subsystem, User)
from app.schemas import schemas
from app.services.create_entity import New_entity
from app.services.create_entitystatusHistory import create_status_history
from app.services.update_entity import update_entity_status
from app.config.entities import ENTITY_CONFIG
from app.routers.auth import require_permission

entity_config = ENTITY_CONFIG.get("subsystem")

router = APIRouter()

# ===================== SUBSYSTEM ENDPOINTS =====================
@router.post("/subsystems/", response_model=schemas.SubsystemRead, tags=["subsystems"])
def create_subsystem(subsystem: schemas.SubsystemCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_subsystems"))):
    db_subsystem = Subsystem(**subsystem.model_dump())
    session.add(db_subsystem)
    session.flush()
    db_subsystem.serial_number = "Subsys-"  + str(db_subsystem.serial_number)+ "-"+ str(db_subsystem.id)

# Create
#    1.  Entity status
#    2.  Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    New_entity(session=session, entity=db_subsystem, entity_name = entity_config["display_name"], changed_by_user= current_user.id)
# --------------------------------------------------------------------------------------------------------------------------------------------

    session.commit()
    session.refresh(db_subsystem)
    status_name = db_subsystem.status.status_name if db_subsystem.status else None
    return schemas.SubsystemRead(
        **db_subsystem.model_dump(),
        status_name=status_name,
        modules=db_subsystem.modules
    )

@router.get("/subsystems/", response_model=List[schemas.SubsystemRead], tags=["subsystems"])
def list_subsystems(skip: int = 0, limit: int = 100, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_subsystems"))):
    subsystems = session.exec(select(Subsystem).offset(skip).limit(limit)).all()
    result = []
    for subsystem in subsystems:
        status_name = subsystem.status.status_name if subsystem.status else None
        result.append(schemas.SubsystemRead(
            **subsystem.model_dump(),
            status_name=status_name,
            modules=None,
        ))
    return result

@router.get("/subsystems/{subsystem_id}/", response_model=schemas.SubsystemRead, tags=["subsystems"])
def get_subsystem(subsystem_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_subsystems"))):
    subsystem = session.get(Subsystem, subsystem_id)
    if not subsystem:
        raise HTTPException(status_code=404, detail="Subsystem not found")
    status_name = subsystem.status.status_name if subsystem.status else None
    return schemas.SubsystemRead(
        **subsystem.model_dump(),
        status_name=status_name,
        modules=subsystem.modules
    )

@router.put("/subsystems/{subsystem_id}/", response_model=schemas.SubsystemRead, tags=["subsystems"])
def update_subsystem(subsystem_id: int, subsystem: schemas.SubsystemUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_subsystems"))):
    db_subsystem = session.get(Subsystem, subsystem_id)
    if not db_subsystem:
        raise HTTPException(status_code=404, detail="Subsystem not found")
    for k, v in subsystem.model_dump(exclude_unset=True).items():
        setattr(db_subsystem, k, v)
    session.add(db_subsystem)
    session.flush()

# Update Entity status and Create Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    update_entity_status(session=session, entity= db_subsystem, entity_name = entity_config["display_name"], changed_by_user= current_user.id)

    session.commit()
    session.refresh(db_subsystem)
    status_name = db_subsystem.status.status_name if db_subsystem.status else None
    return schemas.SubsystemRead(
        **db_subsystem.model_dump(),
        status_name=status_name,
        modules=db_subsystem.modules
    )

@router.delete("/subsystems/{subsystem_id}/", tags=["subsystems"])
def delete_subsystem(subsystem_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_subsystems"))):
    subsystem = session.get(Subsystem, subsystem_id)
    if not subsystem:
        raise HTTPException(status_code=404, detail="Subsystem not found")
    session.delete(subsystem)
    session.commit()
    return {"ok": True}

@router.get("/subsystems/{subsystem_id}/modules/", response_model=List[schemas.ModuleRead], tags=["subsystems"])
def list_subsystem_modules(subsystem_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_subsystems"))):
    subsystem = session.get(Subsystem, subsystem_id)
    if not subsystem:
        raise HTTPException(status_code=404, detail="Subsystem not found")
    return subsystem.modules
