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
    entity_models = list(EntityType)
    
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


@router.get("/serial-numbers/", response_model=list[str])
def get_serial_numbers(
    q: str = Query("", description="Case-insensitive substring filter on serial number"),
    limit: int = Query(25, ge=1, le=100, description="Max results (typeahead)"),
    session: Session = Depends(get_session),
):
    """
    Search serial numbers for hardware currently installed under a project.
    Prefers original_serial_number (inventory SN) when present so typeahead
    matches inventory labels even if serial_number was historically rewritten.
    """
    from sqlalchemy import or_
    from app.models.tables import System, Subsystem, Module, Unit, Component

    needle = (q or "").strip()
    # Require a short prefix so we never dump tens of thousands of rows.
    if len(needle) < 2:
        return []

    pattern = f"%{needle}%"
    found: set[str] = set()
    per_level = min(limit, 100)

    def preferred_serial(serial_number, original_serial_number) -> str | None:
        original = (original_serial_number or "").strip()
        current = (serial_number or "").strip()
        value = original or current
        return value or None

    def collect_rows(rows) -> None:
        for row in rows:
            if isinstance(row, (tuple, list)):
                serial_number, original_serial_number = row[0], row[1]
            else:
                serial_number, original_serial_number = row, None
            value = preferred_serial(serial_number, original_serial_number)
            if value:
                found.add(value)

    def matches_serial(model):
        return or_(
            model.serial_number.ilike(pattern),
            model.original_serial_number.ilike(pattern),
        )

    collect_rows(
        session.exec(
            select(System.serial_number, System.original_serial_number)
            .where(
                System.project_id.is_not(None),
                System.is_current_install == True,  # noqa: E712
                matches_serial(System),
            )
            .order_by(System.original_serial_number, System.serial_number)
            .limit(per_level)
        ).all()
    )

    collect_rows(
        session.exec(
            select(Subsystem.serial_number, Subsystem.original_serial_number)
            .join(System, Subsystem.system_id == System.id)
            .where(
                System.project_id.is_not(None),
                Subsystem.is_current_install == True,  # noqa: E712
                matches_serial(Subsystem),
            )
            .order_by(Subsystem.original_serial_number, Subsystem.serial_number)
            .limit(per_level)
        ).all()
    )

    collect_rows(
        session.exec(
            select(Module.serial_number, Module.original_serial_number)
            .join(Subsystem, Module.subsystem_id == Subsystem.id)
            .join(System, Subsystem.system_id == System.id)
            .where(
                System.project_id.is_not(None),
                Module.is_current_install == True,  # noqa: E712
                matches_serial(Module),
            )
            .order_by(Module.original_serial_number, Module.serial_number)
            .limit(per_level)
        ).all()
    )

    collect_rows(
        session.exec(
            select(Unit.serial_number, Unit.original_serial_number)
            .join(Module, Unit.module_id == Module.id)
            .join(Subsystem, Module.subsystem_id == Subsystem.id)
            .join(System, Subsystem.system_id == System.id)
            .where(
                System.project_id.is_not(None),
                Unit.is_current_install == True,  # noqa: E712
                matches_serial(Unit),
            )
            .order_by(Unit.original_serial_number, Unit.serial_number)
            .limit(per_level)
        ).all()
    )

    collect_rows(
        session.exec(
            select(Component.serial_number, Component.original_serial_number)
            .join(Unit, Component.unit_id == Unit.id)
            .join(Module, Unit.module_id == Module.id)
            .join(Subsystem, Module.subsystem_id == Subsystem.id)
            .join(System, Subsystem.system_id == System.id)
            .where(
                System.project_id.is_not(None),
                Component.is_current_install == True,  # noqa: E712
                matches_serial(Component),
            )
            .order_by(Component.original_serial_number, Component.serial_number)
            .limit(per_level)
        ).all()
    )

    return sorted(found)[:limit]