from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (Module, User)
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

entity_config = ENTITY_CONFIG.get("module")

router = APIRouter()

# ===================== MODULE ENDPOINTS =====================
@router.post("/modules/", response_model=schemas.ModuleRead, tags=["modules"])
def create_module(module: schemas.ModuleCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_modules"))):
    db_module = Module(**module.model_dump())
    if not db_module.original_serial_number and db_module.serial_number:
        db_module.original_serial_number = db_module.serial_number
    require_hierarchy_mutable(session, db_module)
    session.add(db_module)
    session.flush()


# Create
#    1.  Entity status
#    2.  Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    New_entity(session=session, entity=db_module, entity_name = entity_config["display_name"], changed_by_user= current_user.id)
# --------------------------------------------------------------------------------------------------------------------------------------------
    session.commit()
    session.refresh(db_module)
    status_name = db_module.status.status_name if db_module.status else None
    return schemas.ModuleRead(
        **db_module.model_dump(),
        status_name=status_name,
        units=db_module.units
    )

@router.get("/modules/", response_model=List[schemas.ModuleRead], tags=["modules"])
def list_modules(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    include_total: bool = True,
    sort_by: str | None = None,
    sort_order: str | None = None,
    search: Optional[str] = Query(None),
    status_id: Optional[int] = Query(None),
    subsystem_id: Optional[int] = Query(None),
    installed_by_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_modules")),
):
    def to_read(module: Module) -> schemas.ModuleRead:
        status_name = module.status.status_name if module.status else None
        return schemas.ModuleRead(
            **module.model_dump(),
            status_name=status_name,
            units=None,
        )

    return paginated_query(
        session,
        Module,
        skip,
        limit,
        response,
        transform=to_read,
        include_total=include_total,
        sort_by=sort_by,
        sort_order=sort_order,
        where=hierarchy_list_where(
            Module,
            search=search,
            status_id=status_id,
            subsystem_id=subsystem_id,
            installed_by_id=installed_by_id,
        ),
    )

@router.get("/modules/{module_id}/", response_model=schemas.ModuleRead, tags=["modules"])
def get_module(module_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_modules"))):
    module = session.get(Module, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    status_name = module.status.status_name if module.status else None
    return schemas.ModuleRead(
        **module.model_dump(),
        status_name=status_name,
        units=filter_current_installs(module.units)
    )

@router.put("/modules/{module_id}/", response_model=schemas.ModuleRead, tags=["modules"])
def update_module(module_id: int, module: schemas.ModuleUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_modules"))):
    db_module = session.get(Module, module_id)
    if not db_module:
        raise HTTPException(status_code=404, detail="Module not found")
    require_hierarchy_mutable(session, db_module)
    require_install_owner_or_manager(current_user, db_module)
    for k, v in module.model_dump(exclude_unset=True).items():
        setattr(db_module, k, v)
    session.add(db_module)
    session.flush()

# Update Entity status and Create Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    update_entity_status(session=session, entity= db_module, entity_name = entity_config["display_name"], changed_by_user= current_user.id)

    session.commit()
    session.refresh(db_module)
    status_name = db_module.status.status_name if db_module.status else None
    return schemas.ModuleRead(
        **db_module.model_dump(),
        status_name=status_name,
        units=db_module.units
    )

@router.delete("/modules/{module_id}/", tags=["modules"])
def delete_module(module_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_modules"))):
    module = session.get(Module, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    require_hierarchy_mutable(session, module)
    require_install_owner_or_manager(current_user, module)
    session.delete(module)
    session.commit()
    return {"ok": True}

@router.get("/modules/{module_id}/units/", response_model=List[schemas.UnitRead], tags=["modules"])
def list_module_units(module_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_modules"))):
    module = session.get(Module, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    return filter_current_installs(module.units)
