from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (System, User)
from app.schemas import schemas
from app.services.create_entity import New_entity
from app.services.create_entitystatusHistory import create_status_history
from app.services.update_entity import update_entity_status
from app.config.entities import ENTITY_CONFIG
from app.routers.auth import require_permission
from app.auth import require_install_owner_or_manager, require_hierarchy_mutable
from app.services.entity_replacement_service import filter_current_installs
from app.services.list_query import hierarchy_list_where
from app.services.pagination import paginated_query

entity_config = ENTITY_CONFIG.get("system")

router = APIRouter()

# ===================== SYSTEM ENDPOINTS =====================
@router.post("/systems/", response_model=schemas.SystemRead, tags=["systems"])
def create_system(system: schemas.SystemCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_systems"))):
    db_system = System(**system.dict())
    # Preserve inventory/user-provided serial numbers — do not rewrite.
    if not db_system.original_serial_number and db_system.serial_number:
        db_system.original_serial_number = db_system.serial_number
    require_hierarchy_mutable(session, db_system)
    session.add(db_system)
    session.flush()

# Create
#    1.  Entity status
#    2.  Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    New_entity(session=session, entity=db_system, entity_name = entity_config["display_name"], changed_by_user= current_user.id)
# --------------------------------------------------------------------------------------------------------------------------------------------

    session.commit()
    session.refresh(db_system)
    status_name = db_system.status.status_name if db_system.status else None
    return schemas.SystemRead(
        **db_system.model_dump(),
        status_name=status_name,
        subsystems=db_system.subsystems
    )

@router.get("/systems/", response_model=List[schemas.SystemRead], tags=["systems"])
def list_systems(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    include_total: bool = True,
    sort_by: str | None = None,
    sort_order: str | None = None,
    search: Optional[str] = Query(None),
    status_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    installed_by_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_systems")),
):
    def to_read(system: System) -> schemas.SystemRead:
        status_name = system.status.status_name if system.status else None
        return schemas.SystemRead(
            **system.model_dump(),
            status_name=status_name,
            subsystems=None,
        )

    return paginated_query(
        session,
        System,
        skip,
        limit,
        response,
        transform=to_read,
        include_total=include_total,
        sort_by=sort_by,
        sort_order=sort_order,
        where=hierarchy_list_where(
            System,
            search=search,
            status_id=status_id,
            project_id=project_id,
            installed_by_id=installed_by_id,
        ),
    )

@router.get("/systems/{system_id}/", response_model=schemas.SystemRead, tags=["systems"])
def get_system(system_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_systems"))):
    system = session.get(System, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")
    status_name = system.status.status_name if system.status else None
    return schemas.SystemRead(
        **system.model_dump(),
        status_name=status_name,
        subsystems=filter_current_installs(system.subsystems)
    )

@router.put("/systems/{system_id}/", response_model=schemas.SystemRead, tags=["systems"])
def update_system(system_id: int, system: schemas.SystemUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_systems"))):
    db_system = session.get(System, system_id)
    if not db_system:
        raise HTTPException(status_code=404, detail="System not found")
    require_hierarchy_mutable(session, db_system)
    require_install_owner_or_manager(current_user, db_system)
    for k, v in system.model_dump(exclude_unset=True).items():
        setattr(db_system, k, v)
    session.add(db_system)
    session.flush()

# Update Entity status and Create Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    update_entity_status(session=session, entity= db_system, entity_name = entity_config["display_name"], changed_by_user= current_user.id)

    session.commit()
    session.refresh(db_system)
    status_name = db_system.status.status_name if db_system.status else None
    return schemas.SystemRead(
        **db_system.model_dump(),
        status_name=status_name,
        subsystems=db_system.subsystems
    )

@router.delete("/systems/{system_id}/", tags=["systems"])
def delete_system(system_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_systems"))):
    system = session.get(System, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")
    require_hierarchy_mutable(session, system)
    require_install_owner_or_manager(current_user, system)
    session.delete(system)
    session.commit()
    return {"ok": True}

@router.get("/systems/{system_id}/subsystems/", response_model=List[schemas.SubsystemRead], tags=["systems"])
def list_system_subsystems(system_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_systems"))):
    system = session.get(System, system_id)
    if not system:
        raise HTTPException(status_code=404, detail="System not found")
    return filter_current_installs(system.subsystems)
