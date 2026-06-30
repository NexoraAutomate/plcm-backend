from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (Project, User, Status)
from app.schemas import schemas
from app.services.create_entity import New_entity
from app.services.create_entitystatusHistory import create_status_history
from app.services.update_entity import update_entity_status
from app.config.entities import ENTITY_CONFIG
from app.routers.auth import require_permission

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
    status_name = db_project.status.status_name if db_project.status else None
    return schemas.ProjectRead(
        **db_project.model_dump(),
        status_name=status_name,
        systems=db_project.systems
    )

@router.get("/projects/", response_model=List[schemas.ProjectRead], tags=["projects"])
def list_projects(skip: int = 0, limit: int = 100, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_projects"))):
    projects = session.exec(select(Project).offset(skip).limit(limit)).all()
    result = []
    for project in projects:
        status_name = project.status.status_name if project.status else None
        result.append(schemas.ProjectRead(
            **project.model_dump(),
            status_name=status_name,
            systems=project.systems
        ))
    return result

@router.get("/projects/{project_id}/", response_model=schemas.ProjectRead, tags=["projects"])
def get_project(project_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_projects"))):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    status_name = project.status.status_name if project.status else None
    return schemas.ProjectRead(
        **project.model_dump(),
        status_name=status_name,
        systems=project.systems
    )

@router.put("/projects/{project_id}/", response_model=schemas.ProjectRead, tags=["projects"])
def update_project(project_id: int, project: schemas.ProjectUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_projects"))):
    db_project = session.get(Project, project_id)
    if not db_project:
        raise HTTPException(status_code=404, detail="Project not found")
    previous_progress = db_project.progress or 0
    update_data = project.model_dump(exclude_unset=True)
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
    status_name = db_project.status.status_name if db_project.status else None
    return schemas.ProjectRead(
        **db_project.model_dump(),
        status_name=status_name,
        systems=db_project.systems
    )

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
    return project.systems
