from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (Component, User)
from app.schemas import schemas
from app.services.create_entity import New_entity
from app.services.create_entitystatusHistory import create_status_history
from app.services.update_entity import update_entity_status
from app.config.entities import ENTITY_CONFIG
from app.routers.auth import require_permission

entity_config = ENTITY_CONFIG.get("component")

router = APIRouter()

# ===================== COMPONENT ENDPOINTS =====================
@router.post("/components/", response_model=schemas.ComponentRead, tags=["components"])
def create_component(component: schemas.ComponentCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_components"))):
    db_component = Component(**component.model_dump())
    session.add(db_component)
    session.flush()
    db_component.serial_number = "Comp-" + str(db_component.serial_number)  + "-"+ str(db_component.id)

# Create
#    1.  Entity status
#    2.  Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    New_entity(session=session, entity=db_component, entity_name = entity_config["display_name"], changed_by_user= current_user.id)
# --------------------------------------------------------------------------------------------------------------------------------------------

    session.commit()
    session.refresh(db_component)
    status_name = db_component.status.status_name if db_component.status else None
    return schemas.ComponentRead(
        **db_component.model_dump(),
        status_name=status_name,
    )

@router.get("/components/", response_model=List[schemas.ComponentRead], tags=["components"])
def list_components(skip: int = 0, limit: int = 100, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_components"))):
    components = session.exec(select(Component).offset(skip).limit(limit)).all()
    result = []
    for component in components:
        status_name = component.status.status_name if component.status else None
        result.append(schemas.ComponentRead(
            **component.model_dump(),
            status_name=status_name,
        ))
    return result

@router.get("/components/{component_id}/", response_model=schemas.ComponentRead, tags=["components"])
def get_component(component_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_components"))):
    component = session.get(Component, component_id)
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    status_name = component.status.status_name if component.status else None
    return schemas.ComponentRead(
        **component.model_dump(),
        status_name=status_name,
    )

@router.put("/components/{component_id}/", response_model=schemas.ComponentRead, tags=["components"])
def update_component(component_id: int, component: schemas.ComponentUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_components"))):
    db_component = session.get(Component, component_id)
    if not db_component:
        raise HTTPException(status_code=404, detail="Component not found")
    for k, v in component.model_dump(exclude_unset=True).items():
        setattr(db_component, k, v)
    session.add(db_component)
    session.flush()

# Update Entity status and Create Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    update_entity_status(session=session, entity= db_component, entity_name = entity_config["display_name"], changed_by_user= current_user.id)

    session.commit()
    session.refresh(db_component)
    status_name = db_component.status.status_name if db_component.status else None
    return schemas.ComponentRead(
        **db_component.model_dump(),
        status_name=status_name,
    )

@router.delete("/components/{component_id}/", tags=["components"])
def delete_component(component_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_components"))):
    component = session.get(Component, component_id)
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    session.delete(component)
    session.commit()
    return {"ok": True}

