from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.database import get_session
from app.models.tables import User
from app.routers.auth import require_permission
from app.schemas.reports import (
    BuildHistoryDossierResponse,
    ExecutiveReportResponse,
    HierarchyReportResponse,
    InventoryReportResponse,
    MaintenanceHistoryDossierResponse,
    MaintenanceSummaryResponse,
    ReportHistoryListResponse,
    ReportRegisterRequest,
    ReportRegisterResponse,
    ReportVerifyResponse,
)
from app.services.dashboard_service import DashboardFilters
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/register", response_model=ReportRegisterResponse)
def register_report(
    payload: ReportRegisterRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("export_reports")),
):
    return report_service.register_report(session, payload, current_user)


@router.get("/verify/{report_uuid}", response_model=ReportVerifyResponse)
def verify_report(
    report_uuid: UUID,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_reports")),
):
    return report_service.verify_report(session, str(report_uuid))


@router.get("/history", response_model=ReportHistoryListResponse)
def list_report_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    report_type: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_order: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_reports")),
):
    return report_service.list_report_history(
        session,
        page=page,
        page_size=page_size,
        report_type=report_type,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/build-history/{project_id}", response_model=BuildHistoryDossierResponse)
def get_build_history_dossier(
    project_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("generate_build_dossier")),
):
    try:
        return report_service.build_history_dossier(session, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/hierarchy/{project_id}", response_model=HierarchyReportResponse)
def get_hierarchy_report(
    project_id: int,
    mode: str = Query("bhd", description="Report mode: bhd or mmhd"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_reports")),
):
    try:
        return report_service.hierarchy_report(session, project_id, mode=mode)
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_400_BAD_REQUEST
            if "mode must" in detail
            else status.HTTP_404_NOT_FOUND
        )
        raise HTTPException(status_code=code, detail=detail) from exc


@router.get(
    "/maintenance-history/{case_id}",
    response_model=MaintenanceHistoryDossierResponse,
)
def get_maintenance_history_dossier(
    case_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("generate_maintenance_dossier")),
):
    try:
        return report_service.maintenance_history_dossier(session, case_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/inventory", response_model=InventoryReportResponse)
def get_inventory_report(
    mode: str = Query("current"),
    search: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    project_id: Optional[int] = Query(None),
    part_number: Optional[str] = Query(None),
    serial_number: Optional[str] = Query(None),
    status_name: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_reports")),
):
    return report_service.inventory_report(
        session,
        mode=mode,
        search=search,
        location=location,
        project_id=project_id,
        part_number=part_number,
        serial_number=serial_number,
        status_name=status_name,
    )


@router.get("/maintenance-summary", response_model=MaintenanceSummaryResponse)
def get_maintenance_summary(
    project_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    search: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_reports")),
):
    return report_service.maintenance_summary_report(
        session,
        project_id=project_id,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )


@router.get("/executive", response_model=ExecutiveReportResponse)
def get_executive_report(
    customer_id: Optional[int] = Query(None),
    order_id: Optional[int] = Query(None),
    project_id: Optional[int] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    project_status: Optional[str] = Query(None),
    maintenance_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_executive_dashboard")),
):
    filters = DashboardFilters(
        customer_id=customer_id,
        order_id=order_id,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        project_status=project_status,
        maintenance_status=maintenance_status,
        search=search,
    )
    return report_service.executive_report(session, filters)
