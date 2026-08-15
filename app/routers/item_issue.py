"""Spec 07 — assign developer, item request queue, and signed issue."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.auth import check_permission
from app.database import get_session
from app.models.tables import User
from app.routers.auth import get_current_user, require_permission
from app.schemas import schemas
from app.services.hierarchy_developer_service import (
    HierarchyDeveloperError,
    assign_developer,
    assigned_developer_payload,
    assignment_status_map,
    entity_is_physically_issued,
    list_assigned_work,
)
from app.services.item_request_service import (
    ItemRequestError,
    create_bulk_item_requests,
    create_item_request,
    issue_item_request,
    item_request_to_dict,
    list_item_requests,
)

router = APIRouter()


def _http_error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    lower = detail.lower()
    if "not found" in lower:
        code = status.HTTP_404_NOT_FOUND
    elif "only request" in lower or "assigned to you" in lower:
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=detail)


def require_can_issue_user(user: User = Depends(get_current_user)) -> User:
    if (
        check_permission(user, "inventory.issue")
        or check_permission(user, "issue_inventory")
    ):
        return user
    raise HTTPException(
        status_code=403,
        detail="User does not have permission: inventory.issue",
    )


def require_item_request_or_issue(user: User = Depends(get_current_user)) -> User:
    if (
        check_permission(user, "item.request")
        or check_permission(user, "inventory.issue")
        or check_permission(user, "issue_inventory")
    ):
        return user
    raise HTTPException(
        status_code=403,
        detail="User does not have permission: item.request",
    )


@router.post(
    "/hierarchy/{entity_type}/{entity_id}/assign-developer/",
    response_model=schemas.HierarchyAssignDeveloperRead,
    tags=["hierarchy"],
)
def assign_hierarchy_developer(
    entity_type: str,
    entity_id: int,
    payload: schemas.HierarchyAssignDeveloperRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("hierarchy.assign_developer")),
):
    try:
        entity = assign_developer(
            session,
            entity_type,
            entity_id,
            payload.developer_user_id,
            actor=current_user,
        )
        data = assigned_developer_payload(session, entity, entity_type)
        data["issued"] = entity_is_physically_issued(session, entity_type, entity_id)
        return schemas.HierarchyAssignDeveloperRead.model_validate(data)
    except HierarchyDeveloperError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/item-assignments/status/",
    response_model=List[schemas.HierarchyAssignmentStatusRead],
    tags=["hierarchy"],
)
def get_hierarchy_assignment_status(
    entity_type: str,
    ids: str = Query(default="", description="Comma-separated entity ids"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not (
        check_permission(current_user, "hierarchy.assign_developer")
        or check_permission(current_user, "item.request")
        or check_permission(current_user, "view_projects")
        or check_permission(current_user, "view_systems")
    ):
        raise HTTPException(
            status_code=403,
            detail="User does not have permission to view assignment status",
        )
    entity_ids: list[int] = []
    for part in (ids or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            entity_ids.append(int(part))
        except ValueError:
            continue
    status_map = assignment_status_map(session, entity_type, entity_ids)
    return [
        schemas.HierarchyAssignmentStatusRead.model_validate(payload)
        for payload in status_map.values()
    ]


@router.get(
    "/item-assignments/mine/",
    response_model=List[schemas.DeveloperAssignedWorkRead],
    tags=["item-requests"],
)
def list_my_assigned_work(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("item.request")),
):
    return [
        schemas.DeveloperAssignedWorkRead.model_validate(row)
        for row in list_assigned_work(session, int(current_user.id))
    ]


@router.post(
    "/item-requests/",
    response_model=schemas.ItemIssueRequestRead,
    tags=["item-requests"],
)
def create_developer_item_request(
    payload: schemas.ItemIssueRequestCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("item.request")),
):
    try:
        row = create_item_request(
            session,
            entity_type=payload.entity_type,
            entity_id=payload.entity_id,
            actor=current_user,
            notes=payload.notes,
        )
        return schemas.ItemIssueRequestRead.model_validate(
            item_request_to_dict(session, row)
        )
    except ItemRequestError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/item-requests/bulk/",
    response_model=schemas.ItemIssueRequestBulkResult,
    tags=["item-requests"],
)
def create_bulk_developer_item_requests(
    payload: schemas.ItemIssueRequestBulkCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("item.request")),
):
    try:
        items = None
        if payload.items:
            items = [
                {"entity_type": item.entity_type, "entity_id": item.entity_id}
                for item in payload.items
            ]
        created, skipped = create_bulk_item_requests(
            session,
            actor=current_user,
            mode=payload.mode,
            items=items,
            notes=payload.notes,
        )
        return schemas.ItemIssueRequestBulkResult(
            created=[
                schemas.ItemIssueRequestRead.model_validate(
                    item_request_to_dict(session, row)
                )
                for row in created
            ],
            skipped=[
                schemas.ItemIssueRequestBulkSkipped.model_validate(row)
                for row in skipped
            ],
        )
    except ItemRequestError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/item-requests/",
    response_model=List[schemas.ItemIssueRequestRead],
    tags=["item-requests"],
)
def list_developer_item_requests(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    mine: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_item_request_or_issue),
):
    rows = list_item_requests(
        session,
        actor=current_user,
        status=status_filter,
        mine_only=mine,
    )
    return [
        schemas.ItemIssueRequestRead.model_validate(item_request_to_dict(session, row))
        for row in rows
    ]


@router.post(
    "/item-requests/{request_id}/issue/",
    response_model=schemas.ItemIssueRequestRead,
    tags=["item-requests"],
)
def issue_pending_item_request(
    request_id: int,
    payload: schemas.ItemIssueRequestIssueBody,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_can_issue_user),
):
    try:
        row = issue_item_request(
            session,
            request_id,
            actor=current_user,
            signature_type=payload.signature_type,
            signature_payload=payload.signature_payload,
            notes=payload.notes,
        )
        return schemas.ItemIssueRequestRead.model_validate(
            item_request_to_dict(session, row)
        )
    except ItemRequestError as exc:
        raise _http_error(exc) from exc
