"""Spec 01 — Smart SDLS hierarchy configuration APIs."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.database import get_session
from app.domain.hierarchy_config import (
    DEFAULT_PRODUCT_TYPE_DEFS,
    CONFIG_RULE_NOTES_DEFAULT,
    fixed_levels_payload,
)
from app.models.tables import User
from app.routers.auth import get_current_user, require_permission
from app.schemas import schemas
from app.services.hierarchy_config_service import (
    HierarchyConfigError,
    configuration_to_dict,
    create_configuration,
    delete_configuration,
    get_configuration,
    list_configurations,
    set_available,
    update_configuration,
)

router = APIRouter(prefix="/hierarchy-configurations", tags=["hierarchy-configurations"])


def _http_error(exc: HierarchyConfigError) -> HTTPException:
    detail = str(exc)
    code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


def _to_read(config) -> schemas.HierarchyConfigurationRead:
    return schemas.HierarchyConfigurationRead(**configuration_to_dict(config))


def _to_summary(config) -> schemas.HierarchyConfigurationSummary:
    data = configuration_to_dict(config)
    return schemas.HierarchyConfigurationSummary(
        id=data["id"],
        code=data["code"],
        name=data["name"],
        description=data["description"],
        is_available=data["is_available"],
        version=data["version"],
        product_type_codes=[pt["code"] for pt in data["product_types"]],
    )


@router.get("/meta", response_model=dict[str, Any])
@router.get("/meta/", response_model=dict[str, Any], include_in_schema=False)
def get_hierarchy_config_meta(user: User = Depends(get_current_user)):
    """Fixed level order + default product types for Admin UI."""
    return {
        "fixed_levels": fixed_levels_payload(),
        "default_product_types": DEFAULT_PRODUCT_TYPE_DEFS,
        "default_notes": CONFIG_RULE_NOTES_DEFAULT,
    }


@router.get("/available", response_model=list[schemas.HierarchyConfigurationSummary])
@router.get(
    "/available/",
    response_model=list[schemas.HierarchyConfigurationSummary],
    include_in_schema=False,
)
def list_available_configurations(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """HM / project-create facing list — only available configs (Spec 02 handoff)."""
    configs = list_configurations(session, available_only=True)
    return [_to_summary(c) for c in configs]


@router.get("", response_model=list[schemas.HierarchyConfigurationRead])
@router.get("/", response_model=list[schemas.HierarchyConfigurationRead], include_in_schema=False)
def list_all_configurations(
    available_only: bool = Query(False),
    user: User = Depends(require_permission("hierarchy_config.manage")),
    session: Session = Depends(get_session),
):
    configs = list_configurations(session, available_only=available_only)
    return [_to_read(c) for c in configs]


@router.get("/{config_id}", response_model=schemas.HierarchyConfigurationRead)
@router.get(
    "/{config_id}/",
    response_model=schemas.HierarchyConfigurationRead,
    include_in_schema=False,
)
def get_one_configuration(
    config_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    config = get_configuration(session, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    # Non-managers may only read available configs (HM selection)
    from app.auth import check_permission

    if not config.is_available and not check_permission(user, "hierarchy_config.manage"):
        raise HTTPException(status_code=404, detail="Configuration not found")
    return _to_read(config)


@router.post(
    "",
    response_model=schemas.HierarchyConfigurationRead,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/",
    response_model=schemas.HierarchyConfigurationRead,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_one_configuration(
    payload: schemas.HierarchyConfigurationCreate,
    user: User = Depends(require_permission("hierarchy_config.manage")),
    session: Session = Depends(get_session),
):
    try:
        config = create_configuration(
            session,
            payload.model_dump(),
            actor=user,
        )
        return _to_read(config)
    except HierarchyConfigError as exc:
        raise _http_error(exc) from exc


@router.put("/{config_id}", response_model=schemas.HierarchyConfigurationRead)
@router.put(
    "/{config_id}/",
    response_model=schemas.HierarchyConfigurationRead,
    include_in_schema=False,
)
def update_one_configuration(
    config_id: int,
    payload: schemas.HierarchyConfigurationUpdate,
    user: User = Depends(require_permission("hierarchy_config.manage")),
    session: Session = Depends(get_session),
):
    try:
        config = update_configuration(
            session,
            config_id,
            payload.model_dump(exclude_unset=True),
            actor=user,
        )
        return _to_read(config)
    except HierarchyConfigError as exc:
        raise _http_error(exc) from exc


@router.patch("/{config_id}/availability", response_model=schemas.HierarchyConfigurationRead)
@router.patch(
    "/{config_id}/availability/",
    response_model=schemas.HierarchyConfigurationRead,
    include_in_schema=False,
)
def patch_availability(
    config_id: int,
    is_available: bool = Query(...),
    user: User = Depends(require_permission("hierarchy_config.manage")),
    session: Session = Depends(get_session),
):
    try:
        return _to_read(set_available(session, config_id, is_available))
    except HierarchyConfigError as exc:
        raise _http_error(exc) from exc


@router.delete("/{config_id}")
@router.delete("/{config_id}/", include_in_schema=False)
def delete_one_configuration(
    config_id: int,
    hard: bool = Query(False, description="Hard-delete row; default soft-retires"),
    user: User = Depends(require_permission("hierarchy_config.manage")),
    session: Session = Depends(get_session),
):
    try:
        delete_configuration(session, config_id, hard=hard, actor=user)
        return {"ok": True, "hard": hard}
    except HierarchyConfigError as exc:
        raise _http_error(exc) from exc
