from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (Unit, User)
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

entity_config = ENTITY_CONFIG.get("unit")

router = APIRouter()

# ===================== UNIT ENDPOINTS =====================
@router.post("/units/", response_model=schemas.UnitRead, tags=["units"])
def create_unit(unit: schemas.UnitCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_units"))):
    db_unit = Unit(**unit.model_dump())
    if not db_unit.original_serial_number and db_unit.serial_number:
        db_unit.original_serial_number = db_unit.serial_number
    require_hierarchy_mutable(session, db_unit)
    session.add(db_unit)
    session.flush()
#    1.  Entity status
#    2.  Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    New_entity(session=session, entity=db_unit, entity_name = entity_config["display_name"], changed_by_user= current_user.id)
# --------------------------------------------------------------------------------------------------------------------------------------------

    session.commit()
    session.refresh(db_unit)
    status_name = db_unit.status.status_name if db_unit.status else None
    return schemas.UnitRead(
        **db_unit.model_dump(),
        status_name=status_name,
        components=db_unit.components
    )

@router.get("/units/", response_model=List[schemas.UnitRead], tags=["units"])
def list_units(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    include_total: bool = True,
    sort_by: str | None = None,
    sort_order: str | None = None,
    search: Optional[str] = Query(None),
    status_id: Optional[int] = Query(None),
    module_id: Optional[int] = Query(None),
    installed_by_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_units")),
):
    def to_read(unit: Unit) -> schemas.UnitRead:
        status_name = unit.status.status_name if unit.status else None
        return schemas.UnitRead(
            **unit.model_dump(),
            status_name=status_name,
            components=None,
        )

    return paginated_query(
        session,
        Unit,
        skip,
        limit,
        response,
        transform=to_read,
        include_total=include_total,
        sort_by=sort_by,
        sort_order=sort_order,
        where=hierarchy_list_where(
            Unit,
            search=search,
            status_id=status_id,
            module_id=module_id,
            installed_by_id=installed_by_id,
        ),
    )

@router.get("/units/{unit_id}/", response_model=schemas.UnitRead, tags=["units"])
def get_unit(unit_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_units"))):
    unit = session.get(Unit, unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    status_name = unit.status.status_name if unit.status else None
    return schemas.UnitRead(
        **unit.model_dump(),
        status_name=status_name,
        components=filter_current_installs(unit.components)
    )

@router.put("/units/{unit_id}/", response_model=schemas.UnitRead, tags=["units"])
def update_unit(unit_id: int, unit: schemas.UnitUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_units"))):
    db_unit = session.get(Unit, unit_id)
    if not db_unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    require_hierarchy_mutable(session, db_unit)
    require_install_owner_or_manager(current_user, db_unit)
    for k, v in unit.model_dump(exclude_unset=True).items():
        setattr(db_unit, k, v)
    session.add(db_unit)
    session.flush()

# Update Entity status and Create Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    update_entity_status(session=session, entity= db_unit, entity_name = entity_config["display_name"], changed_by_user= current_user.id)

    session.commit()
    session.refresh(db_unit)
    status_name = db_unit.status.status_name if db_unit.status else None
    return schemas.UnitRead(
        **db_unit.model_dump(),
        status_name=status_name,
        components=db_unit.components
    )

@router.delete("/units/{unit_id}/", tags=["units"])
def delete_unit(unit_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_units"))):
    unit = session.get(Unit, unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    require_hierarchy_mutable(session, unit)
    require_install_owner_or_manager(current_user, unit)
    session.delete(unit)
    session.commit()
    return {"ok": True}

@router.get("/units/{unit_id}/components/", response_model=List[schemas.ComponentRead], tags=["units"])
def list_unit_components(unit_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_units"))):
    unit = session.get(Unit, unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return filter_current_installs(unit.components)
