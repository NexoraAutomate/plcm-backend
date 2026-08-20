from typing import List
from fastapi import APIRouter, HTTPException, Depends, File, Query, Response, UploadFile
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (Status, User)
from app.schemas import schemas
from app.routers.auth import require_permission
from app.services.pagination import paginated_query
from app.services.status_import_service import (
    StatusImportError,
    import_status_rows,
    parse_status_file,
)

router = APIRouter()

# ===================== STATUS ENDPOINTS =====================
@router.post("/statuses/", response_model=schemas.StatusRead, tags=["statuses"])
def create_status(status: schemas.StatusCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_statuses"))):
    db_status = Status(**status.model_dump())
    session.add(db_status)
    session.commit()
    session.refresh(db_status)
    return db_status

@router.post("/statuses/batch/", response_model=List[schemas.StatusRead], tags=["statuses"])
def create_statuses(
    statuses: List[schemas.StatusCreate],
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("create_statuses"))
):
    # print(current_user)
    db_statuses = [Status(**status.model_dump()) for status in statuses]
    
    
    try:
        session.add_all(db_statuses)
        session.commit()
        # print(f"Batch created")
    except Exception:
        session.rollback()
        raise

    # session.add_all(db_statuses)
    # session.commit()

    for db_status in db_statuses:
        session.refresh(db_status)
    
    return db_statuses


@router.post("/statuses/import/", tags=["statuses"])
async def import_statuses_spreadsheet(
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="Validate only; do not save"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("create_statuses")),
):
    """Import statuses from CSV or Excel (.xlsx).

    Required columns: Status, Description, Entity Type.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        rows = parse_status_file(content, file.filename or "")
        return import_status_rows(session, rows, dry_run=dry_run)
    except StatusImportError as exc:
        if exc.errors:
            raise HTTPException(
                status_code=422,
                detail={"message": exc.message, "errors": exc.errors},
            ) from exc
        raise HTTPException(status_code=400, detail=exc.message) from exc

@router.get("/statuses/", response_model=List[schemas.StatusRead], tags=["statuses"])
def list_statuses(
    response: Response,
    status_type: str | None = None,
    skip: int = 0,
    limit: int = 100,
    sort_by: str | None = None,
    sort_order: str | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_statuses")),
):
    where = Status.status_type == status_type if status_type else None
    return paginated_query(
        session,
        Status,
        skip,
        limit,
        response,
        where=where,
        sort_by=sort_by,
        sort_order=sort_order,
    )

@router.get("/statuses/{status_id}/", response_model=schemas.StatusRead, tags=["statuses"])
def get_status(status_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_statuses"))):
    status = session.get(Status, status_id)
    if not status:
        raise HTTPException(status_code=404, detail="Status not found")
    return status

@router.put("/statuses/{status_id}/", response_model=schemas.StatusRead, tags=["statuses"])
def update_status(status_id: int, status: schemas.StatusUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_statuses"))):
    db_status = session.get(Status, status_id)
    if not db_status:
        raise HTTPException(status_code=404, detail="Status not found")
    for k, v in status.model_dump(exclude_unset=True).items():
        setattr(db_status, k, v)
    session.add(db_status)
    session.commit()
    session.refresh(db_status)
    return db_status

@router.delete("/statuses/{status_id}/", tags=["statuses"])
def delete_status(status_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_statuses"))):
    status = session.get(Status, status_id)
    if not status:
        raise HTTPException(status_code=404, detail="Status not found")
    session.delete(status)
    session.commit()
    return {"ok": True}