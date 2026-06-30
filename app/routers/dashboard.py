from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.database import get_session
from app.models.tables import User
from app.routers.auth import require_permission
from app.schemas.dashboard import ExecutiveDashboardResponse
from app.services.dashboard_service import DashboardFilters, build_executive_dashboard

router = APIRouter(prefix="/dashboard", tags=["executive-dashboard"])


def _parse_filters(
    customer_id: Optional[int] = None,
    order_id: Optional[int] = None,
    project_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    project_status: Optional[str] = None,
    maintenance_status: Optional[str] = None,
    configuration_status: Optional[str] = None,
    search: Optional[str] = None,
    kpi_filter: Optional[str] = None,
) -> DashboardFilters:
    return DashboardFilters(
        customer_id=customer_id,
        order_id=order_id,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        project_status=project_status,
        maintenance_status=maintenance_status,
        configuration_status=configuration_status,
        search=search,
        kpi_filter=kpi_filter,
    )


@router.get("/executive", response_model=ExecutiveDashboardResponse)
def get_executive_dashboard(
    customer_id: Optional[int] = Query(None),
    order_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    project_status: Optional[str] = Query(None),
    maintenance_status: Optional[str] = Query(None),
    configuration_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    kpi_filter: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_executive_dashboard")),
):
    filters = _parse_filters(
        customer_id=customer_id,
        order_id=order_id,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        project_status=project_status,
        maintenance_status=maintenance_status,
        configuration_status=configuration_status,
        search=search,
        kpi_filter=kpi_filter,
    )
    return build_executive_dashboard(session, filters)
