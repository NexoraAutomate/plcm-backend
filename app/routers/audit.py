"""Spec 13 — immutable workflow audit trail APIs."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.database import get_session
from app.models.tables import User
from app.routers.auth import require_permission
from app.schemas import schemas
from app.services.pagination import set_list_total_header
from app.services.workflow_audit_service import (
    action_catalog,
    event_to_dict,
    list_workflow_audits,
)

router = APIRouter()

_IMMUTABLE_DETAIL = "Audit rows cannot be updated or deleted"


@router.get(
    "/",
    response_model=List[schemas.WorkflowAuditEventRead],
    tags=["audit"],
)
def list_audit_events(
    response: Response,
    skip: int = 0,
    limit: int = 50,
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[str] = Query(default=None),
    actor_user_id: Optional[int] = Query(default=None),
    actor_role: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    search: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    _: User = Depends(require_permission("audit.read")),
):
    rows, total = list_workflow_audits(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=action,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        skip=skip,
        limit=min(max(limit, 1), 200),
    )
    set_list_total_header(response, total)
    return [schemas.WorkflowAuditEventRead(**event_to_dict(row)) for row in rows]


@router.get(
    "/actions",
    response_model=List[schemas.WorkflowAuditActionCatalogItem],
    tags=["audit"],
)
def list_audit_actions(
    _: User = Depends(require_permission("audit.read")),
):
    return [schemas.WorkflowAuditActionCatalogItem(**item) for item in action_catalog()]


@router.get("/export.csv", tags=["audit"])
def export_audit_csv(
    entity_type: Optional[str] = Query(default=None),
    entity_id: Optional[str] = Query(default=None),
    actor_user_id: Optional[int] = Query(default=None),
    actor_role: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    project_id: Optional[int] = Query(default=None),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    search: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    _: User = Depends(require_permission("audit.read")),
):
    rows, _total = list_workflow_audits(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=action,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        skip=0,
        limit=5000,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "occurred_at",
            "actor_user_id",
            "actor_username",
            "actor_role",
            "action",
            "entity_type",
            "entity_id",
            "project_id",
            "old_value",
            "new_value",
            "remarks",
            "ip_address",
            "user_agent",
            "correlation_id",
        ]
    )
    for row in rows:
        payload = event_to_dict(row)
        writer.writerow(
            [
                payload["id"],
                payload["occurred_at"],
                payload["actor_user_id"],
                payload["actor_username"] or "",
                payload["actor_role"],
                payload["action"],
                payload["entity_type"],
                payload["entity_id"],
                payload["project_id"] or "",
                json.dumps(payload["old_value"]) if payload["old_value"] is not None else "",
                json.dumps(payload["new_value"]) if payload["new_value"] is not None else "",
                payload["remarks"] or "",
                payload["ip_address"] or "",
                payload["user_agent"] or "",
                payload["correlation_id"] or "",
            ]
        )
    buf.seek(0)
    headers = {
        "Content-Disposition": 'attachment; filename="audit-trail.csv"',
    }
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers=headers,
    )


@router.api_route(
    "/{event_id}",
    methods=["PUT", "PATCH", "DELETE"],
    tags=["audit"],
)
@router.api_route(
    "/{event_id}/",
    methods=["PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
def mutate_audit_event_forbidden(event_id: str):
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail=_IMMUTABLE_DETAIL,
    )
