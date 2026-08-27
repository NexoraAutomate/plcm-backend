from typing import List, Literal
from fastapi import APIRouter, HTTPException, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import Hierarchy, User
from app.schemas import schemas
from app.routers.auth import require_permission, require_any_permission, require_role
from app.services.hierarchy_service import create_hierarchy_entry, get_next_hierarchy_id, sync_hierarchy_id_sequence
from app.services.entity_list_service import enrich_hierarchy_reads
from app.services.entity_list_import_service import (
    EntityListImportError,
    export_entity_list_file,
    import_entity_list_rows,
    parse_entity_list_file,
)

router = APIRouter()

@router.post("/hierarchies/", response_model=schemas.HierarchyRead, tags=["hierarchy"])
def create_hierarchy(entry: schemas.HierarchyCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_hierarchy"))):
    db_entry = create_hierarchy_entry(session, entry.model_dump())
    session.commit()
    session.refresh(db_entry)
    return db_entry

@router.post("/hierarchies/batch/", response_model=List[schemas.HierarchyRead], tags=["hierarchy"])
def create_hierarchy_batch(entries: List[schemas.HierarchyCreate], session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_hierarchy"))):
    next_id = get_next_hierarchy_id(session)
    db_entries = []
    for entry in entries:
        db_entry = Hierarchy(**entry.model_dump())
        db_entry.id = next_id
        next_id += 1
        db_entries.append(db_entry)
    session.add_all(db_entries)
    session.flush()
    sync_hierarchy_id_sequence(session)
    session.commit()
    for db_entry in db_entries:
        session.refresh(db_entry)
    return db_entries


@router.post("/hierarchies/import/", tags=["hierarchy"])
async def import_hierarchy_spreadsheet(
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="Validate only; do not save"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("create_hierarchy")),
):
    """Import Entity List rows from a CSV or Excel (.xlsx) file.

    Required columns: entity name, entity type.
    Optional: abbreviation / acronym.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        rows = parse_entity_list_file(content, file.filename or "")
        return import_entity_list_rows(session, rows, dry_run=dry_run)
    except EntityListImportError as exc:
        if exc.errors:
            raise HTTPException(
                status_code=422,
                detail={"message": exc.message, "errors": exc.errors},
            ) from exc
        raise HTTPException(status_code=400, detail=exc.message) from exc


@router.get("/hierarchies/export/", tags=["hierarchy"])
def export_hierarchy_spreadsheet(
    file_format: Literal["csv", "xlsx"] = Query("csv", alias="format"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("Admin")),
):
    """Download the Entity List as CSV or Excel. Admin only."""
    content, filename, media_type = export_entity_list_file(session, file_format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.get("/hierarchies/", response_model=List[schemas.HierarchyRead], tags=["hierarchy"])
def list_hierarchies(
    hierarchy_type: str | None = None,
    parent_id: int | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission("view_hierarchy", "create_inventory", "edit_inventory")
    ),
):
    query = select(Hierarchy)
    if hierarchy_type:
        query = query.where(Hierarchy.hierarchy_type == hierarchy_type)
    if parent_id is not None:
        query = query.where(Hierarchy.parent_id == parent_id)
    entries = list(session.exec(query).all())
    return enrich_hierarchy_reads(session, entries)

@router.get("/hierarchies/{hierarchy_id}/", response_model=schemas.HierarchyRead, tags=["hierarchy"])
def get_hierarchy(
    hierarchy_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission("view_hierarchy", "create_inventory", "edit_inventory")
    ),
):
    entry = session.get(Hierarchy, hierarchy_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Hierarchy entry not found")
    return entry

@router.put("/hierarchies/{hierarchy_id}/", response_model=schemas.HierarchyRead, tags=["hierarchy"])
def update_hierarchy(hierarchy_id: int, entry: schemas.HierarchyUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_hierarchy"))):
    db_entry = session.get(Hierarchy, hierarchy_id)
    if not db_entry:
        raise HTTPException(status_code=404, detail="Hierarchy entry not found")
    for k, v in entry.model_dump(exclude_unset=True).items():
        setattr(db_entry, k, v)
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry

@router.delete("/hierarchies/{hierarchy_id}/", tags=["hierarchy"])
def delete_hierarchy(hierarchy_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_hierarchy"))):
    entry = session.get(Hierarchy, hierarchy_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Hierarchy entry not found")
    session.delete(entry)
    session.commit()
    return {"ok": True}
