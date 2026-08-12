from typing import List
from fastapi import APIRouter, HTTPException, Depends, Response, status
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (Project, User, Status)
from app.schemas import schemas
from app.services.create_entity import New_entity
from app.services.update_entity import update_entity_status
from app.config.entities import ENTITY_CONFIG
from app.services.entity_replacement_service import filter_current_installs
from app.routers.auth import require_permission
from app.services.pagination import paginated_query
from app.services.project_workflow_service import (
    ProjectWorkflowError,
    assert_can_generate_hierarchy,
    assign_hm,
    approve_project,
    create_draft_project,
    guard_structural_update,
)

entity_config = ENTITY_CONFIG.get("project")

router = APIRouter()


def _get_project_status_id(session: Session, status_name: str) -> int | None:
    status = session.exec(
        select(Status).where(Status.status_name == status_name, Status.status_type == "projects")
    ).first()
    return status.id if status else None


def _apply_progress_status_rules(
    session: Session,
    db_project: Project,
    previous_progress: int,
    update_data: dict,
) -> None:
    new_progress = update_data.get("progress")
    if new_progress is None:
        return

    user_set_status = "status_id" in update_data

    if new_progress >= 100:
        completed_id = _get_project_status_id(session, "Completed")
        if completed_id:
            db_project.status_id = completed_id
            db_project.progress = 100
    elif previous_progress >= 100 and 0 < new_progress < 100 and not user_set_status:
        execution_id = _get_project_status_id(session, "Execution")
        if execution_id:
            db_project.status_id = execution_id


def _to_project_read(project: Project, *, include_systems: bool = True) -> schemas.ProjectRead:
    status_name = project.status.status_name if project.status else None
    return schemas.ProjectRead(
        **project.model_dump(),
        status_name=status_name,
        systems=filter_current_installs(project.systems) if include_systems else None,
    )


def _workflow_http_error(exc: ProjectWorkflowError) -> HTTPException:
    detail = str(exc)
    lower = detail.lower()
    if "not found" in lower:
        code = status.HTTP_404_NOT_FOUND
    elif "only admin" in lower or "requires project status" in lower:
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=detail)


# ===================== Spec 02 WORKFLOW ENDPOINTS =====================
@router.post(
    "/projects/draft/",
    response_model=schemas.ProjectRead,
    tags=["projects"],
    status_code=status.HTTP_201_CREATED,
)
def create_project_draft(
    payload: schemas.ProjectDraftCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("project.create_draft")),
):
    try:
        project = create_draft_project(
            session, payload.model_dump(), actor=current_user
        )
        return _to_project_read(project)
    except ProjectWorkflowError as exc:
        raise _workflow_http_error(exc) from exc


@router.post(
    "/projects/{project_id}/assign-hm/",
    response_model=schemas.ProjectRead,
    tags=["projects"],
)
def assign_project_hm(
    project_id: int,
    payload: schemas.ProjectAssignHmRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("project.assign_hm")),
):
    try:
        project = assign_hm(
            session, project_id, payload.hm_user_id, actor=current_user
        )
        return _to_project_read(project)
    except ProjectWorkflowError as exc:
        raise _workflow_http_error(exc) from exc


@router.post(
    "/projects/{project_id}/approve/",
    response_model=schemas.ProjectRead,
    tags=["projects"],
)
def approve_project_endpoint(
    project_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("project.approve")),
):
    try:
        project = approve_project(session, project_id, actor=current_user)
        return _to_project_read(project)
    except ProjectWorkflowError as exc:
        raise _workflow_http_error(exc) from exc


@router.post(
    "/projects/{project_id}/generate-hierarchy/",
    tags=["projects"],
)
def generate_project_hierarchy(
    project_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("hierarchy.generate")),
):
    """Spec 02 guard — blocked until Spec 03; also rejects DRAFT projects."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        assert_can_generate_hierarchy(project)
    except ProjectWorkflowError as exc:
        raise _workflow_http_error(exc) from exc
    return {"ok": True}


# ===================== PROJECT ENDPOINTS =====================
@router.post("/projects/", response_model=schemas.ProjectRead, tags=["projects"])
def create_project(project: schemas.ProjectCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_projects"))):
    db_project = Project(**project.model_dump())
    session.add(db_project)
    session.flush()

# Create
#    1.  Entity status
#    2.  Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    New_entity(session=session, entity=db_project, entity_name = entity_config["display_name"], changed_by_user= current_user.id)
# --------------------------------------------------------------------------------------------------------------------------------------------

    session.commit()
    session.refresh(db_project)
    return _to_project_read(db_project)

@router.get("/projects/", response_model=List[schemas.ProjectRead], tags=["projects"])
def list_projects(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    include_total: bool = True,
    sort_by: str | None = None,
    sort_order: str | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_projects")),
):
    def to_read(project: Project) -> schemas.ProjectRead:
        return _to_project_read(project, include_systems=False)

    return paginated_query(
        session,
        Project,
        skip,
        limit,
        response,
        transform=to_read,
        include_total=include_total,
        sort_by=sort_by,
        sort_order=sort_order,
    )

@router.get("/projects/{project_id}/", response_model=schemas.ProjectRead, tags=["projects"])
def get_project(project_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_projects"))):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_project_read(project)

@router.put("/projects/{project_id}/", response_model=schemas.ProjectRead, tags=["projects"])
def update_project(project_id: int, project: schemas.ProjectUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_projects"))):
    db_project = session.get(Project, project_id)
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")
    previous_progress = db_project.progress or 0
    update_data = project.model_dump(exclude_unset=True)
    try:
        guard_structural_update(db_project, update_data)
    except ProjectWorkflowError as exc:
        raise _workflow_http_error(exc) from exc
    for k, v in update_data.items():
        setattr(db_project, k, v)
    _apply_progress_status_rules(session, db_project, previous_progress, update_data)
    session.add(db_project)
    session.flush()

# Update Entity status and Create Entity Status History
# --------------------------------------------------------------------------------------------------------------------------------------------
    update_entity_status(session=session, entity= db_project, entity_name = entity_config["display_name"],changed_by_user= current_user.id)
    session.commit()
    session.refresh(db_project)
    return _to_project_read(db_project)

@router.delete("/projects/{project_id}/", tags=["projects"])
def delete_project(project_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_projects"))):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    session.delete(project)
    session.commit()
    return {"ok": True}

@router.get("/projects/{project_id}/systems/", response_model=List[schemas.SystemRead], tags=["projects"])
def list_project_systems(project_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_projects"))):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return filter_current_installs(project.systems)
