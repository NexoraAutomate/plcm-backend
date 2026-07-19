# =============================================================================
# maintenance_module.py
# Maintenance Case Management — Models, Schemas & Endpoints
# Covers: MaintenanceCase → FaultyEntity → MaintenanceAction → MaintenanceDelivery
# =============================================================================

from __future__ import annotations
from sqlalchemy import update
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Field, Relationship, Session, SQLModel, select

# Project-level imports (adjust paths to match your project structure)
from app.database import get_session
from .auth import require_permission
# Hierarchy models — adapt class names / FK attribute names to your schema
from app.models.tables import User

# =============================================================================
# ENDPOINTS — MAINTENANCE CASE
# =============================================================================
from app.schemas.Maintennance import EntityLookupRead
from app.models.base import EntityType, ActionType
from app.schemas.Maintennance import *
from app.models.tables import ConfigurationHistory, ConfigurationHistoryBase
from app.services.configuration_history import create_configuration_history_record
from app.services.sorting import apply_sort
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

router = APIRouter()

# =====================================================
# List Configuration History
# =====================================================
@router.get(
    "/configuration_history_list/",
    response_model=List[ConfigurationHistoryRead],
)
def list_configuration_history(
    skip: int = 0,
    limit: int = 100,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    # entity_id: Optional[int] = None,
    # maintenance_case_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_configuration_history")),
):
    statement = select(ConfigurationHistory)

    # if entity_id:
    #     statement = statement.where(ConfigurationHistory.entity_id == entity_id)

    # if maintenance_case_id:
    #     statement = statement.where(ConfigurationHistory.maintenance_case_id == maintenance_case_id)

    statement = apply_sort(
        statement,
        ConfigurationHistory,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    statement = statement.offset(skip).limit(limit)

    return session.exec(statement).all()

# =====================================================
# List Configuration History by case ID
# =====================================================

@router.get(
    "/configuration_history_list/{caseId}/caseID/",
    response_model=List[ConfigurationHistoryRead],
)
def list_configuration_history_by_case(
    caseId: int,
    skip: int = 0,
    limit: int = 100,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_configuration_history")),
):
    statement = select(ConfigurationHistory).where(
        ConfigurationHistory.maintenance_case_id == caseId
    )

    statement = apply_sort(
        statement,
        ConfigurationHistory,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    statement = statement.offset(skip).limit(limit)

    return session.exec(statement).all()

# =====================================================
# List Configuration History by Entity ID
# =====================================================

@router.get(
    "/configuration_history_list/{entityId}/EntityID/",
    response_model=List[ConfigurationHistoryRead],
)
def list_configuration_history_by_entity(
    entityId: int,
    skip: int = 0,
    limit: int = 100,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_configuration_history")),
):
    statement = select(ConfigurationHistory).where(
        ConfigurationHistory.entity_id == entityId
    )

    statement = apply_sort(
        statement,
        ConfigurationHistory,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    statement = statement.offset(skip).limit(limit)

    return session.exec(statement).all()

# =====================================================
# Get Single Record
# =====================================================
@router.get(
    "/configuration_history/{history_id}/",
    response_model=ConfigurationHistoryRead,
)
def get_configuration_history(
    history_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_configuration_history")),
):
    history = session.get(ConfigurationHistory, history_id)

    if not history:
        raise HTTPException(
            status_code=404,
            detail="Configuration history record not found.",
        )

    return history


# =====================================================
# Create
# =====================================================
@router.post(
    "/configuration_history/",
    response_model=ConfigurationHistoryRead,
    status_code=201,
)
def create_configuration_history(
    payload: ConfigurationHistoryCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("create_configuration_history")),
):
    return create_configuration_history_record(session, payload)


# =====================================================
# Update
# =====================================================
@router.put(
    "/configuration_history/{history_id}/",
    response_model=ConfigurationHistoryRead,
)
def update_configuration_history(
    history_id: int,
    payload: ConfigurationHistoryUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_configuration_history")),
):
    history = session.get(ConfigurationHistory, history_id)

    if not history:
        raise HTTPException(
            status_code=404,
            detail="Configuration history record not found.",
        )

    update_data = payload.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(history, key, value)

    session.add(history)
    session.commit()
    session.refresh(history)

    return history


# =====================================================
# Delete
# =====================================================
@router.delete(
    "/configuration_history/{history_id}/",
    status_code=204,
)
def delete_configuration_history(
    history_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("delete_configuration_history")),
):
    history = session.get(ConfigurationHistory, history_id)

    if not history:
        raise HTTPException(
            status_code=404,
            detail="Configuration history record not found.",
        )

    session.delete(history)
    session.commit()

    return