from typing import List
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (Component, User)
from app.schemas import schemas
from app.services.create_entity import New_entity
from app.services.create_entitystatusHistory import create_status_history
from app.services.update_entity import update_entity_status
from app.config.entities import ENTITY_CONFIG
from app.routers.auth import require_permission
from app.services.pagination import paginated_query

entity_config = ENTITY_CONFIG.get("component")

router = APIRouter()

# ===================== COMPONENT ENDPOINTS =====================
@router.post("/components/", response_model=schemas.ComponentRead, tags=["components"])
def create_component(component: schemas.ComponentCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_components"))):
    db_component = Component(**component.model_dump())
    if not db_component.original_serial_number and db_component.serial_number:
        db_component.original_serial_number = db_component.serial_number
    session.add(db_component)
    session.flush()

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
def list_components(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    include_total: bool = True,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_components")),
):
    def to_read(component: Component) -> schemas.ComponentRead:
        status_name = component.status.status_name if component.status else None
        return schemas.ComponentRead(
            **component.model_dump(),
            status_name=status_name,
        )

    return paginated_query(session, Component, skip, limit, response, transform=to_read, include_total=include_total)

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

