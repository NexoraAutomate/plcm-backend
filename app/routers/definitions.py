"""Admin-configurable naming templates and entity display labels."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.database import get_session
from app.models.tables import User
from app.schemas import schemas
from app.routers.auth import get_current_user, require_permission
from app.services.login_history_service import client_ip
from app.services.app_definitions_service import (
    get_or_create_app_definitions,
    update_app_definitions,
)

router = APIRouter(prefix="/definitions", tags=["Definitions"])


@router.get("", response_model=schemas.AppDefinitionsRead)
@router.get("/", response_model=schemas.AppDefinitionsRead, include_in_schema=False)
def get_app_definitions(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Any authenticated user may read labels/templates (needed for UI naming)."""
    return get_or_create_app_definitions(session)


@router.put("", response_model=schemas.AppDefinitionsRead)
@router.put("/", response_model=schemas.AppDefinitionsRead, include_in_schema=False)
def put_app_definitions(
    payload: schemas.AppDefinitionsUpdate,
    request: Request,
    user: User = Depends(require_permission("manage_settings")),
    session: Session = Depends(get_session),
):
    try:
        return update_app_definitions(
            session,
            payload.model_dump(exclude_unset=True),
            actor=user,
            ip_address=client_ip(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
