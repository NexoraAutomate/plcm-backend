from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import Hierarchy, User
from app.schemas import schemas
from app.routers.auth import require_permission

router = APIRouter()

@router.post("/hierarchies/", response_model=schemas.HierarchyRead, tags=["hierarchy"])
def create_hierarchy(entry: schemas.HierarchyCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_hierarchy"))):
    db_entry = Hierarchy(**entry.model_dump())
    session.add(db_entry)
    session.commit()
    session.refresh(db_entry)
    return db_entry

@router.post("/hierarchies/batch/", response_model=List[schemas.HierarchyRead], tags=["hierarchy"])
def create_hierarchy_batch(entries: List[schemas.HierarchyCreate], session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_hierarchy"))):
    db_entries = [Hierarchy(**entry.model_dump()) for entry in entries]
    session.add_all(db_entries)
    session.commit()
    for db_entry in db_entries:
        session.refresh(db_entry)
    return db_entries

@router.get("/hierarchies/", response_model=List[schemas.HierarchyRead], tags=["hierarchy"])
def list_hierarchies(
    hierarchy_type: str | None = None,
    parent_id: int | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_hierarchy"))
):
    query = select(Hierarchy)
    if hierarchy_type:
        query = query.where(Hierarchy.hierarchy_type == hierarchy_type)
    if parent_id is not None:
        query = query.where(Hierarchy.parent_id == parent_id)
    return session.exec(query).all()

@router.get("/hierarchies/{hierarchy_id}/", response_model=schemas.HierarchyRead, tags=["hierarchy"])
def get_hierarchy(hierarchy_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_hierarchy"))):
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
