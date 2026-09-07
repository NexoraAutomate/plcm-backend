"""Spec 14 — current-user app notifications (gap events)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.database import get_session
from app.models.tables import AppNotification, User
from app.routers.auth import require_permission
from app.schemas import schemas
from app.services.app_notification_service import (
    list_app_notifications,
    mark_all_app_notifications_read,
    mark_app_notification_read,
    notification_to_dict,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/", response_model=List[schemas.AppNotificationRead])
def list_notifications(
    unread_only: bool = Query(False),
    search: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_notifications")),
):
    rows = list_app_notifications(
        session,
        int(current_user.id),
        unread_only=unread_only,
        search=search,
    )
    return [schemas.AppNotificationRead.model_validate(notification_to_dict(r)) for r in rows]


@router.post("/{notice_id}/read/", response_model=schemas.AppNotificationRead)
def read_notification(
    notice_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_notifications")),
):
    row = session.get(AppNotification, notice_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    updated = mark_app_notification_read(session, row)
    return schemas.AppNotificationRead.model_validate(notification_to_dict(updated))


@router.post("/read-all/")
def read_all_notifications(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_notifications")),
):
    count = mark_all_app_notifications_read(session, int(current_user.id))
    return {"ok": True, "marked": count}
