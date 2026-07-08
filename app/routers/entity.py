from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (Entity, User)
from app.schemas import schemas
from app.routers.auth import require_permission
from app.models.base import EntityType
from app.models.helpers import _PARENT_MAP
from app.services.configuration_history import resolve_generic_entity
from app.services.entity_replacement_service import get_replacement_chain

router = APIRouter()

# ===================== ENTITY ENDPOINTS =====================
# Create New Entity 
@router.post("/entities/", response_model=schemas.EntityRead, tags=["entities"])
def create_entity(entity: schemas.EntityCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_entities"))):
    db_entity = Entity(**entity.model_dump())
    session.add(db_entity)
    session.commit()
    session.refresh(db_entity)
    return db_entity

# List All Entities with Pagination and Optional Filtering 
@router.get("/entities/", response_model=List[schemas.EntityRead], tags=["entities"])
def list_entities(skip: int = 0, limit: int = 100, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_entities"))):
    return session.exec(select(Entity).offset(skip).limit(limit)).all()

@router.get("/entities/lookup/", response_model=schemas.EntityRead, tags=["entities"])
def lookup_entity(
    entity_type: str = Query(..., description="Hardware entity type, e.g. system or System"),
    entity_pk: int = Query(..., description="Primary key of the hardware record"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_entities")),
):
    """Resolve generic Entity row from hardware entity type and primary key."""
    match = resolve_generic_entity(session, entity_type, entity_pk)
    if not match:
        raise HTTPException(
            status_code=404,
            detail=f"No generic entity found for {entity_type} with id {entity_pk}.",
        )
    return match

# Get Single Entity by ID
@router.get("/entities/{entity_id}/", response_model=schemas.EntityRead, tags=["entities"])
def get_entity(entity_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_entities"))):
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity

# Update Existing Entity (Partial Update)
@router.put("/entities/{entity_id}/", response_model=schemas.EntityRead, tags=["entities"])
def update_entity(entity_id: int, entity: schemas.EntityUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_entities"))):
    db_entity = session.get(Entity, entity_id)
    
    if not db_entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    for k, v in entity.model_dump(exclude_unset=True).items():
        setattr(db_entity, k, v)
    session.add(db_entity)
    session.commit()
    session.refresh(db_entity)
    return db_entity

# Delete Entity by ID 
@router.delete("/entities/{entity_id}/", tags=["entities"])
def delete_entity(entity_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_entities"))):
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    session.delete(entity)
    session.commit()
    return {"ok": True}

# Additional Endpoints for Entity Status History and Maintenance Logs 
@router.get("/entities/{entity_id}/status-history/", response_model=List[schemas.EntityStatusHistoryRead], tags=["entities"])
def list_entity_status_history(entity_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_entities"))):
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity.status_history

@router.get("/entities/{entity_id}/maintenance-logs/", response_model=List[schemas.MaintenanceLogRead], tags=["entities"])
def list_entity_maintenance_logs(entity_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_entities"))):
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity.maintenance_logs


@router.get(
    "/entities/{entity_type}/{entity_pk}/replacement-chain/",
    tags=["entities"],
)
def list_entity_replacement_chain(
    entity_type: str,
    entity_pk: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_entities")),
):
    """Return all install versions for a hardware slot (original + replacements)."""
    try:
        normalized = EntityType(entity_type.lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}") from exc

    chain = get_replacement_chain(session, normalized, entity_pk)
    if not chain:
        raise HTTPException(status_code=404, detail="Entity not found")

    return [
        {
            "id": row.id,
            "entity_type": normalized.value,
            "name": getattr(row, "name", None),
            "part_number": getattr(row, "part_number", None),
            "serial_number": getattr(row, "serial_number", None),
            "configuration_item": getattr(row, "configuration_item", None),
            "original_part_number": getattr(row, "original_part_number", None),
            "original_serial_number": getattr(row, "original_serial_number", None),
            "is_current_install": getattr(row, "is_current_install", True),
            "root_entity_id": getattr(row, "root_entity_id", row.id),
            "replaced_entity_id": getattr(row, "replaced_entity_id", None),
            "replacement_sequence": getattr(row, "replacement_sequence", 0),
            "replaced_at": getattr(row, "replaced_at", None),
            "installation_date": getattr(row, "installation_date", None),
            "installed_by_id": getattr(row, "installed_by_id", None),
            "created_at": getattr(row, "created_at", None),
        }
        for row in chain
    ]




@router.get("/part-numbers/", response_model=list[str])
def get_part_numbers(session: Session = Depends(get_session)):
    part_numbers = set()
    # print("Compiler reached here")
    entity_models = list(EntityType)
    # print("Compiler reached 2",entity_models)
    
    for entity_type, (_, model, _) in _PARENT_MAP.items():

        if entity_type in {
            EntityType.PROJECT,
            EntityType.ORDER,
            EntityType.CUSTOMER,
        }:
            continue

        rows = session.exec(
            select(model.part_number)
            .where(model.part_number.is_not(None))
        ).all()
        
        part_numbers.update(rows)
        
    return sorted(part_numbers)