from typing import List, Optional
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
from app.services.list_query import combine_where, eq_if_set, text_search
from app.services.project_workflow_service import (
    ProjectWorkflowError,
    assign_hm,
    approve_project,
    create_draft_project,
    guard_structural_update,
    project_list_visibility_where,
    user_can_view_project,
)
from app.services.hierarchy_generation_service import generate_project_hierarchy as do_generate_hierarchy

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


def _require_visible_project(session: Session, project_id: int, current_user: User) -> Project:
    project = session.get(Project, project_id)
    if not project or not user_can_view_project(current_user, project):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


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
    response_model=schemas.HierarchyGenerationResult,
    tags=["projects"],
)
def generate_project_hierarchy(
    project_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("hierarchy.generate")),
):
    """Spec 03 — materialize Flight→SDLS→System… from config + project scope."""
    try:
        result = do_generate_hierarchy(session, project_id, actor=current_user)
        project = session.get(Project, project_id)
        return schemas.HierarchyGenerationResult(
            **result,
            project=_to_project_read(project) if project else None,
        )
    except ProjectWorkflowError as exc:
        raise _workflow_http_error(exc) from exc


@router.get(
    "/projects/{project_id}/hierarchy-tree/",
    response_model=schemas.ProjectHierarchyTree,
    tags=["projects"],
)
def get_project_hierarchy_tree(
    project_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_projects")),
):
    """Spec 03 — nested Flight → SDLS → System tree for project navigation."""
    from app.models.tables import Flight, Sdls

    project = _require_visible_project(session, project_id, current_user)

    flights = session.exec(
        select(Flight)
        .where(Flight.project_id == project_id)
        .order_by(Flight.sequence, Flight.id)
    ).all()

    flight_nodes: list[schemas.FlightTreeNode] = []
    for flight in flights:
        sdls_rows = session.exec(
            select(Sdls)
            .where(Sdls.flight_id == flight.id)
            .order_by(Sdls.sequence, Sdls.id)
        ).all()
        sdls_nodes: list[schemas.SdlsTreeNode] = []
        for sdls in sdls_rows:
            systems = [
                s
                for s in (project.systems or [])
                if s.sdls_id == sdls.id
            ]
            sdls_nodes.append(
                schemas.SdlsTreeNode(
                    id=int(sdls.id),
                    name=sdls.name,
                    code=sdls.code,
                    sequence=sdls.sequence,
                    product_type=sdls.product_type,
                    systems=[
                        schemas.HierarchyTreeSystemNode(
                            id=int(s.id),
                            name=s.name,
                            subsystem_count=len(s.subsystems or []),
                        )
                        for s in systems
                    ],
                )
            )
        flight_nodes.append(
            schemas.FlightTreeNode(
                id=int(flight.id),
                name=flight.name,
                code=flight.code,
                sequence=flight.sequence,
                sdls=sdls_nodes,
            )
        )

    return schemas.ProjectHierarchyTree(
        project_id=project_id,
        status=project.status.status_name if project.status else None,
        flights=flight_nodes,
    )


def _reservation_http_error(exc: Exception) -> HTTPException:
    detail = str(exc)
    lower = detail.lower()
    if "not found" in lower:
        code = status.HTTP_404_NOT_FOUND
    elif "must be ready" in lower or "permission" in lower:
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=detail)


# ===================== Spec 04 RESERVATIONS =====================
@router.get(
    "/projects/{project_id}/reservations/availability",
    response_model=schemas.InventoryAvailabilityCheck,
    tags=["projects"],
)
def check_reservation_availability(
    project_id: int,
    target_entity_type: str,
    target_entity_id: int,
    part_number: str | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("inventory.reserve")),
):
    from app.services.inventory_reservation_service import (
        InventoryReservationError,
        check_availability,
    )

    _require_visible_project(session, project_id, current_user)
    try:
        result = check_availability(
            session,
            project_id=project_id,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            part_number=part_number,
        )
        return schemas.InventoryAvailabilityCheck(**result)
    except InventoryReservationError as exc:
        raise _reservation_http_error(exc) from exc


@router.get(
    "/projects/{project_id}/reservations/",
    response_model=List[schemas.InventoryReservationRead],
    tags=["projects"],
)
def list_reservations(
    project_id: int,
    active_only: bool = False,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_projects")),
):
    from app.services.inventory_reservation_service import (
        list_project_reservations,
        reservation_to_dict,
    )

    project = _require_visible_project(session, project_id, current_user)
    rows = list_project_reservations(session, project_id, active_only=active_only)
    return [schemas.InventoryReservationRead(**reservation_to_dict(r)) for r in rows]


@router.post(
    "/projects/{project_id}/reservations/",
    response_model=schemas.ReserveOutcome,
    tags=["projects"],
    status_code=status.HTTP_201_CREATED,
)
def create_reservation(
    project_id: int,
    payload: schemas.InventoryReservationCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("inventory.reserve")),
):
    from app.services.inventory_reservation_service import (
        InventoryReservationError,
        reservation_to_dict,
        reserve_inventory,
    )
    from app.services.inventory_shortage_service import (
        InventoryShortageCreated,
        shortage_to_dict,
    )

    try:
        row = reserve_inventory(
            session, project_id, payload.model_dump(), actor=current_user
        )
        return schemas.ReserveOutcome(
            outcome="reserved",
            reservation=schemas.InventoryReservationRead(**reservation_to_dict(row)),
        )
    except InventoryShortageCreated as exc:
        return schemas.ReserveOutcome(
            outcome="shortage",
            shortage=schemas.InventoryShortageRead(**shortage_to_dict(exc.shortage)),
        )
    except InventoryReservationError as exc:
        raise _reservation_http_error(exc) from exc


@router.get(
    "/projects/{project_id}/shortages/",
    response_model=List[schemas.InventoryShortageRead],
    tags=["projects"],
)
def list_project_shortages(
    project_id: int,
    active_only: bool = True,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_projects")),
):
    from app.models.base import ShortageStatus
    from app.services.inventory_shortage_service import list_shortages, shortage_to_dict

    project = _require_visible_project(session, project_id, current_user)
    statuses = (
        [ShortageStatus.OPEN.value, ShortageStatus.PARTIAL.value]
        if active_only
        else None
    )
    rows = list_shortages(session, project_id=project_id, statuses=statuses)
    return [schemas.InventoryShortageRead(**shortage_to_dict(r)) for r in rows]


@router.post(
    "/projects/{project_id}/shortages/{shortage_id}/cancel/",
    response_model=schemas.InventoryShortageRead,
    tags=["projects"],
)
def cancel_project_shortage(
    project_id: int,
    shortage_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("inventory.reserve")),
):
    from app.services.inventory_shortage_service import (
        InventoryShortageError,
        cancel_shortage,
        shortage_to_dict,
    )

    try:
        row = cancel_shortage(
            session, shortage_id, actor=current_user, project_id=project_id
        )
        return schemas.InventoryShortageRead(**shortage_to_dict(row))
    except InventoryShortageError as exc:
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=detail) from exc


@router.post(
    "/projects/{project_id}/reservations/{reservation_id}/release/",
    response_model=schemas.InventoryReservationRead,
    tags=["projects"],
)
def release_project_reservation(
    project_id: int,
    reservation_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("inventory.release")),
):
    from app.services.inventory_reservation_service import (
        InventoryReservationError,
        release_reservation,
        reservation_to_dict,
    )

    try:
        row = release_reservation(
            session, project_id, reservation_id, actor=current_user
        )
        return schemas.InventoryReservationRead(**reservation_to_dict(row))
    except InventoryReservationError as exc:
        raise _reservation_http_error(exc) from exc


@router.post(
    "/projects/{project_id}/reservations/{reservation_id}/extend/",
    response_model=schemas.InventoryReservationRead,
    tags=["projects"],
)
def extend_project_reservation(
    project_id: int,
    reservation_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("inventory.reserve")),
):
    from app.services.inventory_reservation_service import (
        InventoryReservationError,
        extend_reservation,
        reservation_to_dict,
    )

    try:
        row = extend_reservation(
            session, project_id, reservation_id, actor=current_user
        )
        return schemas.InventoryReservationRead(**reservation_to_dict(row))
    except InventoryReservationError as exc:
        raise _reservation_http_error(exc) from exc


@router.post(
    "/inventory/reservations/expiry/run/",
    response_model=schemas.ReservationExpiryJobResult,
    tags=["inventory"],
)
def run_reservation_expiry_job(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("inventory.release")),
):
    from app.services.inventory_reservation_expiry_service import (
        evaluate_reservation_expiry,
    )

    result = evaluate_reservation_expiry(session)
    return schemas.ReservationExpiryJobResult(**result)


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
    search: Optional[str] = None,
    status_id: Optional[int] = None,
    order_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_projects")),
):
    def to_read(project: Project) -> schemas.ProjectRead:
        return _to_project_read(project, include_systems=False)

    where = combine_where(
        text_search(Project, search, "name", "description", "product_type"),
        eq_if_set(Project, "status_id", status_id),
        eq_if_set(Project, "order_id", order_id),
        project_list_visibility_where(current_user),
    )

    return paginated_query(
        session,
        Project,
        skip,
        limit,
        response,
        where=where,
        transform=to_read,
        include_total=include_total,
        sort_by=sort_by,
        sort_order=sort_order,
    )

@router.get("/projects/{project_id}/", response_model=schemas.ProjectRead, tags=["projects"])
def get_project(project_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_projects"))):
    project = _require_visible_project(session, project_id, current_user)
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
    project = _require_visible_project(session, project_id, current_user)
    return filter_current_installs(project.systems)
