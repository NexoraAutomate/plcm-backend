"""Spec 12 — configuration change request APIs."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.database import get_session
from app.models.tables import ConfigChangeRequest, Project, User
from app.routers._4_projects import _to_project_read
from app.routers.auth import require_permission
from app.schemas import schemas
from app.models.base import ConfigChangeRequestStatus
from app.services.config_change_service import (
    ConfigChangeError,
    approve_config_change,
    cancel_config_change,
    config_change_to_dict,
    create_successor_project,
    get_open_config_change,
    list_config_changes,
    request_config_change,
    return_config_change_inventory,
    submit_config_change,
)

router = APIRouter()


def _http_error(exc: ConfigChangeError) -> HTTPException:
    detail = str(exc)
    lower = detail.lower()
    if "not found" in lower:
        code = status.HTTP_404_NOT_FOUND
    elif "only submitted" in lower or "only after admin" in lower:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=detail)


def _to_read(
    session: Session,
    row,
    *,
    include_project: bool = False,
    successor: Optional[Project] = None,
) -> schemas.ConfigChangeRequestRead:
    payload = config_change_to_dict(session, row)
    if include_project:
        source = session.get(Project, row.source_project_id)
        if source is not None:
            payload["project"] = _to_project_read(source)
    if successor is not None:
        payload["successor_project"] = _to_project_read(successor)
    elif row.successor_project_id:
        linked = session.get(Project, row.successor_project_id)
        if linked is not None:
            payload["successor_project"] = _to_project_read(linked)
    return schemas.ConfigChangeRequestRead(**payload)


@router.get(
    "/config-changes/",
    response_model=List[schemas.ConfigChangeRequestRead],
    tags=["config-changes"],
)
def list_config_changes_endpoint(
    source_project_id: Optional[int] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_projects")),
):
    rows = list_config_changes(
        session,
        source_project_id=source_project_id,
        status_filter=status_filter,
    )
    return [_to_read(session, row) for row in rows]


@router.get(
    "/config-changes/{change_id}/",
    response_model=schemas.ConfigChangeRequestRead,
    tags=["config-changes"],
)
def get_config_change_endpoint(
    change_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_projects")),
):
    row = session.get(ConfigChangeRequest, change_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuration change request not found",
        )
    return _to_read(session, row, include_project=True)


@router.get(
    "/projects/{project_id}/config-change/",
    response_model=Optional[schemas.ConfigChangeRequestRead],
    tags=["config-changes"],
)
def get_project_config_change_endpoint(
    project_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_projects")),
):
    row = get_open_config_change(session, project_id)
    if row is None:
        # Prefer a completed successor flow for history; skip cancelled withdrawals
        # so HM can request again and resume reserve / generate.
        rows = list_config_changes(session, source_project_id=project_id)
        row = next(
            (
                r
                for r in rows
                if r.status
                == ConfigChangeRequestStatus.NEW_PROJECT_CREATED.value
            ),
            None,
        )
    if row is None:
        return None
    return _to_read(session, row, include_project=True)


@router.post(
    "/projects/{project_id}/config-change/",
    response_model=schemas.ConfigChangeRequestRead,
    tags=["config-changes"],
    status_code=status.HTTP_201_CREATED,
)
def request_config_change_endpoint(
    project_id: int,
    payload: schemas.ConfigChangeRequestCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("config_change.request")),
):
    try:
        row = request_config_change(
            session, project_id, actor=current_user, notes=payload.notes
        )
    except ConfigChangeError as exc:
        raise _http_error(exc) from exc
    return _to_read(session, row, include_project=True)


@router.post(
    "/config-changes/{change_id}/cancel/",
    response_model=schemas.ConfigChangeRequestRead,
    tags=["config-changes"],
)
def cancel_config_change_endpoint(
    change_id: int,
    payload: schemas.ConfigChangeCancelRequest = schemas.ConfigChangeCancelRequest(),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("config_change.request")),
):
    try:
        row = cancel_config_change(
            session, change_id, actor=current_user, notes=payload.notes
        )
    except ConfigChangeError as exc:
        raise _http_error(exc) from exc
    return _to_read(session, row, include_project=True)


@router.post(
    "/config-changes/{change_id}/return-inventory/",
    response_model=schemas.ConfigChangeRequestRead,
    tags=["config-changes"],
)
def return_inventory_endpoint(
    change_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("config_change.request")),
):
    try:
        row = return_config_change_inventory(
            session, change_id, actor=current_user
        )
    except ConfigChangeError as exc:
        raise _http_error(exc) from exc
    return _to_read(session, row, include_project=True)


@router.post(
    "/config-changes/{change_id}/submit/",
    response_model=schemas.ConfigChangeRequestRead,
    tags=["config-changes"],
)
def submit_config_change_endpoint(
    change_id: int,
    payload: schemas.ConfigChangeSubmitRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("config_change.request")),
):
    try:
        row = submit_config_change(
            session,
            change_id,
            actor=current_user,
            target_hierarchy_config_id=payload.target_hierarchy_config_id,
            reason_remarks=payload.reason_remarks,
            product_type=payload.product_type,
            flight_count=payload.flight_count,
            sdls_per_flight=payload.sdls_per_flight,
        )
    except ConfigChangeError as exc:
        raise _http_error(exc) from exc
    return _to_read(session, row, include_project=True)


@router.post(
    "/config-changes/{change_id}/approve/",
    response_model=schemas.ConfigChangeRequestRead,
    tags=["config-changes"],
)
def approve_config_change_endpoint(
    change_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("config_change.approve")),
):
    try:
        row = approve_config_change(session, change_id, actor=current_user)
    except ConfigChangeError as exc:
        raise _http_error(exc) from exc
    return _to_read(session, row, include_project=True)


@router.post(
    "/config-changes/{change_id}/create-project/",
    response_model=schemas.ConfigChangeCreateProjectResult,
    tags=["config-changes"],
    status_code=status.HTTP_201_CREATED,
)
def create_successor_endpoint(
    change_id: int,
    payload: schemas.ConfigChangeCreateProjectRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("config_change.request")),
):
    try:
        row, successor = create_successor_project(
            session,
            change_id,
            actor=current_user,
            name=payload.name,
            flight_count=payload.flight_count,
            sdls_per_flight=payload.sdls_per_flight,
            product_type=payload.product_type,
        )
    except ConfigChangeError as exc:
        raise _http_error(exc) from exc
    return schemas.ConfigChangeCreateProjectResult(
        change=_to_read(session, row, include_project=True, successor=successor),
        project=_to_project_read(successor),
    )
