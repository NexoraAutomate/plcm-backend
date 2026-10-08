"""Pending-action counts for sidebar notification badges."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.models.tables import User
from app.routers.auth import get_current_user
from app.schemas import schemas
from app.services.pending_action_counts_service import build_pending_action_counts

router = APIRouter(prefix="/pending-actions", tags=["pending-actions"])


@router.get("/counts/", response_model=schemas.PendingActionCounts)
def get_pending_action_counts(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return schemas.PendingActionCounts.model_validate(
        build_pending_action_counts(session, current_user)
    )
