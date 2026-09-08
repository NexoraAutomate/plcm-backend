"""Admin-configurable naming templates and entity display labels."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.auth import check_permission
from app.database import get_session
from app.models.tables import User
from app.schemas import schemas
from app.routers.auth import get_current_user
from app.services.login_history_service import client_ip
from app.services.app_definitions_service import (
    LOCATION_PRESET_FIELDS,
    get_or_create_app_definitions,
    update_app_definitions,
)

router = APIRouter(prefix="/definitions", tags=["Definitions"])

_LOCATION_ONLY_FIELDS = frozenset(LOCATION_PRESET_FIELDS)


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
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    Full definitions updates require manage_settings.
    Users with edit_inventory (e.g. Inventory Manager) may only update
    inventory_location_tree.
    """
    updates = payload.model_dump(exclude_unset=True)
    if check_permission(user, "manage_settings"):
        pass
    elif check_permission(user, "edit_inventory"):
        extra = set(updates.keys()) - _LOCATION_ONLY_FIELDS
        if not updates or extra:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "With edit_inventory you may only update inventory storage locations "
                    "(inventory_location_tree)"
                ),
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have permission: manage_settings or edit_inventory",
        )

    try:
        return update_app_definitions(
            session,
            updates,
            actor=user,
            ip_address=client_ip(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
