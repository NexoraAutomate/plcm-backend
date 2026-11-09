# =============================================================================
# maintenance_module.py
# Maintenance Case Management — Models, Schemas & Endpoints
# Covers: MaintenanceCase → FaultyEntity → MaintenanceAction → MaintenanceDelivery
# =============================================================================

from __future__ import annotations
from sqlalchemy import update, func
from sqlalchemy.orm import noload
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Field, Relationship, Session, SQLModel, select

# Project-level imports (adjust paths to match your project structure)
from app.database import get_session
from app.auth import check_permission
from .auth import get_current_user, require_permission, require_any_permission
# Hierarchy models — adapt class names / FK attribute names to your schema
from app.models.tables import User

# =============================================================================
# ENDPOINTS — MAINTENANCE CASE
# =============================================================================
from app.schemas.Maintennance import EntityLookupRead
from app.models.base import EntityType, ActionType
from app.schemas.Maintennance import *
from app.models.helpers import (
    _generate_case_number,
    _cascade_fault_up,
    _SR_SEARCH_MODELS,
    _collect_descendants,
    _create_suspect_fes,
    _clear_healthy_fes,
    _resolve_ancestors,
    _ENTITY_MODEL_MAP,
)
from app.services.pagination import set_list_total_header
from app.services.sorting import apply_sort
from app.services.list_query import text_search
from app.models.tables import (
    MaintenanceCase,
    FaultyEntity,
    MaintenanceAction,
    MaintenanceDelivery,
    Project,
    InventoryReworkCase,
    OemWarrantyClaim,
    Inventory,
    InventoryInstance,
    MaintenanceOccurrenceAttachment,
    MaintenanceOccurrenceOfficer,
    ReplacementRequest,
    ReplacementRequestAitAttachment,
    ReplacementRequestReservation,
)
from app.services.configuration_history import (
    create_configuration_history_for_resolve,
    get_hardware_part_serial,
)
from app.models.base import CaseStatus, FaultyEntityStatus, FaultType, ResolutionType
from app.services import maintenance_field_service as field_svc
from app.services import replacement_request_service as rr_svc
from app.services import track_b_inspection_service as track_b_svc

router = APIRouter()

# Active cases that block opening another case for the same hardware entity.
OPEN_CASE_STATUSES = (
    CaseStatus.OPEN,
    CaseStatus.UNDER_INSPECTION,
    CaseStatus.UNDER_REPAIR,
)


from app.schemas.schemas import MaintenanceUserRead


def _serialize_returned_unit(session: Session, rework: InventoryReworkCase) -> ReturnedUnitRead:
    inventory = session.get(Inventory, rework.inventory_id) if rework.inventory_id else None
    instance = (
        session.get(InventoryInstance, rework.current_instance_id)
        if rework.current_instance_id
        else None
    )
    pd = session.get(User, rework.investigating_pd_id) if rework.investigating_pd_id else None
    ie = (
        session.get(User, rework.assigned_developer_id)
        if rework.assigned_developer_id
        else None
    )
    case_number = None
    if rework.maintenance_case_id:
        case = session.get(MaintenanceCase, rework.maintenance_case_id)
        case_number = case.case_number if case else None
    expires = None
    if instance and getattr(instance, "warranty_expires_at", None):
        expires = instance.warranty_expires_at
    elif inventory and getattr(inventory, "warranty_expires_at", None):
        expires = inventory.warranty_expires_at
    return ReturnedUnitRead(
        id=int(rework.id),
        maintenance_case_id=rework.maintenance_case_id,
        case_number=case_number,
        faulty_entity_id=rework.faulty_entity_id,
        investigating_pd_id=rework.investigating_pd_id,
        investigating_pd_name=(pd.full_name or pd.username) if pd else None,
        assigned_ie_id=rework.assigned_developer_id,
        assigned_ie_name=(ie.full_name or ie.username) if ie else None,
        project_id=rework.project_id,
        inventory_id=rework.inventory_id,
        part_number=(
            (instance.configuration_item if instance else None)
            or (inventory.part_number if inventory else None)
        ),
        serial_number=instance.serial_number if instance else None,
        status=rework.status,
        stage=rework.stage,
        disposition=rework.disposition,
        notes=rework.notes,
        opened_at=rework.opened_at,
        updated_at=rework.updated_at,
        reception_date=getattr(rework, "reception_date", None),
        warranty_expires_at=expires,
        warranty_active=field_svc.warranty_active(expires) if expires else False,
        oem_name=inventory.oem_name if inventory else None,
        is_track_b_terminal=track_b_svc.is_track_b_terminal(rework.stage),
        discarded=track_b_svc.discarded_flag(rework),
    )


def _build_case_read(
    session: Session,
    case: MaintenanceCase,
    *,
    project: Project | None = None,
    reporter: User | None = None,
    include_field_service: bool = True,
) -> MaintenanceCaseRead:
    if project is None:
        project = session.get(Project, case.project_id)
    if reporter is None and case.reported_by is not None:
        reporter = session.get(User, case.reported_by)
    case_read = MaintenanceCaseRead.model_validate(case)
    case_read.project_name = project.name if project else "Undefined"
    case_read.reported_by_user = (
        MaintenanceUserRead.model_validate(reporter) if reporter else None
    )
    case_read.faulty_entities = []
    case_read.deliveries = []
    if include_field_service:
        returned = field_svc.list_case_returned_units(session, int(case.id))
        case_read.returned_units = [
            _serialize_returned_unit(session, row) for row in returned
        ]
        claims = session.exec(
            select(OemWarrantyClaim)
            .where(OemWarrantyClaim.maintenance_case_id == case.id)
            .order_by(OemWarrantyClaim.id.desc())
        ).all()
        case_read.warranty_claims = [
            OemWarrantyClaimRead.model_validate(claim) for claim in claims
        ]
        case_read.occurrence_attachments = [
            OccurrenceAttachmentRead.model_validate(row)
            for row in field_svc.list_occurrence_attachments(session, int(case.id))
        ]
        case_read.occurrence_officers = [
            OccurrenceOfficerRead.model_validate(row)
            for row in field_svc.list_occurrence_officers(session, int(case.id))
        ]
    else:
        case_read.returned_units = []
        case_read.warranty_claims = []
        case_read.occurrence_attachments = []
        case_read.occurrence_officers = []
    case_read.fault_type = getattr(case, "occurrence_fault_type", None)
    return case_read


@router.get(
    "/projects/{project_id}/production-support/",
    response_model=ProductionSupportPreview,
    tags=["maintenance-cases"],
)
def get_project_production_support(
    project_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_maintenance_cases")),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    order = field_svc.resolve_order_for_project(session, project_id)
    snap_date, in_support = field_svc.compute_production_support(
        order.production_support_date if order else None
    )
    return ProductionSupportPreview(
        project_id=project_id,
        order_id=order.id if order else None,
        production_support_date=snap_date,
        in_production_support=in_support,
        requires_override=in_support is False,
    )


@router.post("/maintenance-cases/",
    response_model=MaintenanceCaseRead,
    status_code=201,
    tags=["maintenance-cases"],
)
def create_maintenance_case(
    payload:      MaintenanceCaseCreate,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("create_maintenance_cases")),
):
    """

    Open a new maintenance case against a delivered project.
    Case number is auto-generated (MC-YYYY-NNNN).

    REQUEST:
        {
          "project_id":  1,
          "description": "Customer returned unit — PCB burning smell after 3 weeks.",
          "status":      "open"
        }
    RESPONSE 201:
        {
          "id": 1, "case_number": "MC-2024-0001",
          "project_id": 1, "status": "open",
          "reported_at": "2024-05-02T09:00:00Z",
          "faulty_entities": [], "deliveries": []
        }
    """
    project= session.get(Project, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    payload.project_name = project.name if project else "Undefined"

    support_fields = field_svc.apply_support_gate_on_create(
        session,
        project_id=payload.project_id,
        support_override_reason=payload.support_override_reason,
    )

    # Block a second open/active case for the same hardware (same serial via entity).
    if payload.entity_id is not None and payload.entity_type:
        entity_type_norm = str(payload.entity_type).strip().lower()
        existing_open = session.exec(
            select(MaintenanceCase).where(
                MaintenanceCase.entity_id == payload.entity_id,
                func.lower(MaintenanceCase.entity_type) == entity_type_norm,
                MaintenanceCase.status.in_(OPEN_CASE_STATUSES),
            )
        ).first()
        if existing_open:
            case_ref = existing_open.case_number or f"#{existing_open.id}"
            raise HTTPException(
                status_code=400,
                detail=(
                    f"An open maintenance case already exists for this serial number "
                    f"({case_ref}). Close or resolve it before opening a new case."
                ),
            )

    data = payload.model_dump()
    data["reported_by"] = data.get("reported_by") or current_user.id
    # resolved_at is set only when engineers resolve the case
    data["resolved_at"] = None
    data.update(support_fields)
    case = MaintenanceCase(case_number=_generate_case_number(session),**data)
    print("-----------------------------------------------------------case Created:---------------------------------------------------------", case)
    session.add(case)
    session.commit()
    session.refresh(case)
    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="maintenance_case_opened",
        title="Maintenance case opened",
        message=case.case_number or case.description or f"Case #{case.id}",
        href=f"/maintenance/cases/{case.id}",
        priority="high",
        actor=current_user,
        include_maintenance=True,
        include_assigned_hm=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )
    session.commit()
    return _build_case_read(session, case)

@router.get(
    "/maintenance-cases/",
    response_model=List[MaintenanceCaseRead],
    tags=["maintenance-cases"],
)
def list_maintenance_cases(
    response: Response,
    project_id:   Optional[int] = None,
    status:       Optional[CaseStatus] = None,
    search:       Optional[str] = None,
    skip:         int = 0,
    limit:        int = 100,
    sort_by:      Optional[str] = None,
    sort_order:   Optional[str] = None,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_cases")),
):
    """
    List cases. Filter by project_id and/or status.

    RESPONSE 200: [ { case 1 }, { case 2 }, ... ]
    """
    search_clause = text_search(
        MaintenanceCase, search, "case_number", "description", "project_name", "part_number"
    )
    count_stmt = select(func.count()).select_from(MaintenanceCase)
    if project_id:
        count_stmt = count_stmt.where(MaintenanceCase.project_id == project_id)
    if status:
        count_stmt = count_stmt.where(MaintenanceCase.status == status)
    if search_clause is not None:
        count_stmt = count_stmt.where(search_clause)
    set_list_total_header(response, session.exec(count_stmt).one())

    query = select(MaintenanceCase).options(
        noload(MaintenanceCase.faulty_entities),
        noload(MaintenanceCase.deliveries),
    )
    if project_id:
        query = query.where(MaintenanceCase.project_id == project_id)
    if status:
        query = query.where(MaintenanceCase.status == status)
    if search_clause is not None:
        query = query.where(search_clause)
    query = apply_sort(
        query,
        MaintenanceCase,
        sort_by=sort_by,
        sort_order=sort_order,
        default_order=[MaintenanceCase.reported_at.desc()],
    )
    cases = session.exec(query.offset(skip).limit(limit)).all()
    if not cases:
        return []

    project_ids = {c.project_id for c in cases}
    user_ids = {c.reported_by for c in cases if c.reported_by is not None}
    projects = {
        p.id: p
        for p in session.exec(select(Project).where(Project.id.in_(project_ids))).all()
    }
    users = {
        u.id: u
        for u in session.exec(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}

    return [
        _build_case_read(
            session,
            case,
            project=projects.get(case.project_id),
            reporter=users.get(case.reported_by) if case.reported_by else None,
            include_field_service=False,
        )
        for case in cases
    ]

@router.get(
    "/maintenance-cases/{case_id}/",
    response_model=MaintenanceCaseRead,
    tags=["maintenance-cases"],
)
def get_maintenance_case(
    case_id:      int,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_cases")),
):
    """
    Retrieve a single case with all faulty entities and deliveries nested.

    RESPONSE 200:
        {
          "id": 1, "case_number": "MC-2024-0001", "status": "under_repair",
          "faulty_entities": [
            { "entity_type": "component", "status": "confirmed_faulty",
              "actions": [ { "action_type": "inspection", ... } ] }
          ],
          "deliveries": []
        }
    """
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")

    return _build_case_read(session, case)


@router.post(
    "/maintenance-cases/{case_id}/onsite-outcome/",
    response_model=MaintenanceCaseRead,
    tags=["maintenance-cases"],
)
def record_case_onsite_outcome(
    case_id: int,
    payload: OnsiteOutcomePayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "edit_maintenance_cases",
            "maintenance.occurrence_report",
        )
    ),
):
    """Record Occurrence Report: soft_fix | fault_identified | inconclusive | no_fault_found."""
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")

    attachment_dicts = None
    if payload.attachments is not None:
        attachment_dicts = [
            a.model_dump(exclude_none=True) for a in payload.attachments
        ]
    officer_dicts = None
    if payload.officers is not None:
        officer_dicts = [o.model_dump(exclude_none=True) for o in payload.officers]

    field_svc.record_onsite_outcome(
        session,
        case,
        actor=current_user,
        outcome=payload.onsite_outcome,
        soft_fix_method=payload.onsite_soft_fix_method,
        notes=payload.notes,
        occurrence_date=payload.occurrence_date,
        fault_type=payload.fault_type,
        confirmation_channel=payload.confirmation_channel,
        confirmation_reference=payload.confirmation_reference,
        attachments=attachment_dicts,
        officers=officer_dicts,
        confirm_close_nff=payload.confirm_close_nff,
    )

    outcome_key = payload.onsite_outcome.strip().lower()
    now = datetime.now(timezone.utc)

    if outcome_key == "soft_fix" and payload.resolve_soft_fixed:
        open_fes = session.exec(
            select(FaultyEntity).where(
                FaultyEntity.case_id == case_id,
                FaultyEntity.status.in_(
                    [
                        FaultyEntityStatus.IDENTIFIED,
                        FaultyEntityStatus.SUSPECTED,
                        FaultyEntityStatus.UNDER_INSPECTION,
                        FaultyEntityStatus.CONFIRMED_FAULTY,
                    ]
                ),
            )
        ).all()
        for fe in open_fes:
            fe.status = FaultyEntityStatus.RESOLVED
            fe.resolution_type = ResolutionType.SOFT_FIXED
            fe.resolved_at = now
            session.add(fe)
        if case.status in OPEN_CASE_STATUSES:
            case.status = CaseStatus.RESOLVED
            case.resolved_at = now
            if payload.notes:
                case.resolution_notes = payload.notes
            session.add(case)

    if outcome_key == "no_fault_found" and payload.confirm_close_nff:
        open_fes = session.exec(
            select(FaultyEntity).where(
                FaultyEntity.case_id == case_id,
                FaultyEntity.status.in_(
                    [
                        FaultyEntityStatus.IDENTIFIED,
                        FaultyEntityStatus.SUSPECTED,
                        FaultyEntityStatus.UNDER_INSPECTION,
                        FaultyEntityStatus.CONFIRMED_FAULTY,
                    ]
                ),
            )
        ).all()
        for fe in open_fes:
            fe.status = FaultyEntityStatus.NO_FAULT_FOUND
            fe.resolution_type = ResolutionType.NO_FAULT_FOUND
            fe.resolved_at = now
            session.add(fe)
        if case.status in OPEN_CASE_STATUSES:
            case.status = CaseStatus.CLOSED
            case.resolved_at = now
            case.closed_at = now
            if payload.notes:
                case.resolution_notes = payload.notes
            session.add(case)

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="occurrence_recorded",
        title="Occurrence Report recorded",
        message=(
            f"{case.case_number or f'Case #{case.id}'}: "
            f"{outcome_key.replace('_', ' ')}"
        ),
        href=f"/maintenance/cases/{case.id}",
        priority="medium",
        actor=current_user,
        include_pd=True,
        include_maintenance=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )

    session.commit()
    session.refresh(case)
    return _build_case_read(session, case)


@router.get(
    "/maintenance-returned-units/",
    response_model=List[ReturnedUnitRead],
    tags=["maintenance-cases"],
)
def list_all_returned_units(
    skip: int = 0,
    limit: int = 200,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_maintenance_cases")),
):
    """Global inbox of maintenance-linked returned units (Track B)."""
    _ = current_user
    limit = max(1, min(int(limit or 200), 500))
    skip = max(0, int(skip or 0))
    rows = list(
        session.exec(
            select(InventoryReworkCase)
            .where(InventoryReworkCase.maintenance_case_id.is_not(None))
            .order_by(InventoryReworkCase.id.desc())
            .offset(skip)
            .limit(limit)
        ).all()
    )
    return [_serialize_returned_unit(session, row) for row in rows]


@router.get(
    "/maintenance-cases/{case_id}/returned-units/",
    response_model=List[ReturnedUnitRead],
    tags=["maintenance-cases"],
)
def list_case_returned_units(
    case_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_maintenance_cases")),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    rows = field_svc.list_case_returned_units(session, case_id)
    return [_serialize_returned_unit(session, row) for row in rows]


def _get_case_rework(
    session: Session, case_id: int, rework_id: int
) -> InventoryReworkCase:
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    rework = session.get(InventoryReworkCase, rework_id)
    if not rework or rework.maintenance_case_id != case_id:
        raise HTTPException(status_code=404, detail="Returned unit not found for case")
    return rework


@router.post(
    "/maintenance-cases/{case_id}/returned-units/{rework_id}/reception/",
    response_model=ReturnedUnitRead,
    tags=["maintenance-cases"],
)
def track_b_record_reception(
    case_id: int,
    rework_id: int,
    payload: TrackBReceptionPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.reception",
            "inventory.issue",
            "issue_inventory",
        )
    ),
):
    _get_case_rework(session, case_id, rework_id)
    rework = track_b_svc.record_reception(
        session,
        rework_id,
        actor=current_user,
        reception_date=payload.reception_date,
        notes=payload.notes,
    )
    session.commit()
    session.refresh(rework)
    return _serialize_returned_unit(session, rework)


@router.post(
    "/maintenance-cases/{case_id}/returned-units/{rework_id}/assign-ie/",
    response_model=ReturnedUnitRead,
    tags=["maintenance-cases"],
)
def track_b_assign_ie(
    case_id: int,
    rework_id: int,
    payload: TrackBAssignIePayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("maintenance.assign_ie")),
):
    _get_case_rework(session, case_id, rework_id)
    rework = track_b_svc.assign_ie(
        session,
        rework_id,
        ie_user_id=payload.ie_user_id,
        actor=current_user,
    )
    session.commit()
    session.refresh(rework)
    return _serialize_returned_unit(session, rework)


@router.post(
    "/maintenance-cases/{case_id}/returned-units/{rework_id}/handover-request/",
    response_model=ReturnedUnitRead,
    tags=["maintenance-cases"],
)
def track_b_handover_request(
    case_id: int,
    rework_id: int,
    payload: Optional[TrackBNotesPayload] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.inspection_disposition",
            "edit_maintenance_cases",
        )
    ),
):
    _get_case_rework(session, case_id, rework_id)
    rework = track_b_svc.request_handover(
        session,
        rework_id,
        actor=current_user,
        notes=payload.notes if payload else None,
    )
    session.commit()
    session.refresh(rework)
    return _serialize_returned_unit(session, rework)


@router.post(
    "/maintenance-cases/{case_id}/returned-units/{rework_id}/im-issue-to-ie/",
    response_model=ReturnedUnitRead,
    tags=["maintenance-cases"],
)
def track_b_im_issue_to_ie(
    case_id: int,
    rework_id: int,
    payload: Optional[TrackBNotesPayload] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.im_issue_to_ie",
            "inventory.issue",
            "issue_inventory",
        )
    ),
):
    _get_case_rework(session, case_id, rework_id)
    rework = track_b_svc.im_issue_to_ie(
        session,
        rework_id,
        actor=current_user,
        notes=payload.notes if payload else None,
    )
    session.commit()
    session.refresh(rework)
    return _serialize_returned_unit(session, rework)


@router.post(
    "/maintenance-cases/{case_id}/returned-units/{rework_id}/disposition/",
    response_model=ReturnedUnitRead,
    tags=["maintenance-cases"],
)
def track_b_disposition(
    case_id: int,
    rework_id: int,
    payload: TrackBDispositionPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.inspection_disposition",
            "edit_maintenance_cases",
        )
    ),
):
    _get_case_rework(session, case_id, rework_id)
    rework = track_b_svc.ie_disposition(
        session,
        rework_id,
        actor=current_user,
        outcome=payload.outcome,
        notes=payload.notes,
    )
    session.commit()
    session.refresh(rework)
    return _serialize_returned_unit(session, rework)


@router.post(
    "/maintenance-cases/{case_id}/returned-units/{rework_id}/confirm-discard/",
    response_model=ReturnedUnitRead,
    tags=["maintenance-cases"],
)
def track_b_confirm_discard(
    case_id: int,
    rework_id: int,
    payload: Optional[TrackBNotesPayload] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.confirm_discard",
            "inventory.issue",
            "issue_inventory",
        )
    ),
):
    _get_case_rework(session, case_id, rework_id)
    rework = track_b_svc.im_confirm_discard(
        session,
        rework_id,
        actor=current_user,
        notes=payload.notes if payload else None,
    )
    session.commit()
    session.refresh(rework)
    return _serialize_returned_unit(session, rework)


@router.post(
    "/maintenance-cases/{case_id}/returned-units/{rework_id}/repair-submit/",
    response_model=ReturnedUnitRead,
    tags=["maintenance-cases"],
)
def track_b_repair_submit(
    case_id: int,
    rework_id: int,
    payload: Optional[TrackBNotesPayload] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.inspection_disposition",
            "edit_maintenance_cases",
        )
    ),
):
    _get_case_rework(session, case_id, rework_id)
    rework = track_b_svc.ie_submit_repair(
        session,
        rework_id,
        actor=current_user,
        notes=payload.notes if payload else None,
    )
    session.commit()
    session.refresh(rework)
    return _serialize_returned_unit(session, rework)


@router.post(
    "/maintenance-cases/{case_id}/returned-units/{rework_id}/pd-repair-decision/",
    response_model=ReturnedUnitRead,
    tags=["maintenance-cases"],
)
def track_b_pd_repair_decision(
    case_id: int,
    rework_id: int,
    payload: TrackBPdRepairDecisionPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("maintenance.repair_approve")),
):
    _get_case_rework(session, case_id, rework_id)
    rework = track_b_svc.pd_repair_decide(
        session,
        rework_id,
        actor=current_user,
        decision=payload.decision,
        reject_reason=payload.reject_reason,
    )
    session.commit()
    session.refresh(rework)
    return _serialize_returned_unit(session, rework)


def _serialize_replacement_request(
    session: Session, req: ReplacementRequest
) -> ReplacementRequestRead:
    links = rr_svc.list_reservations(session, int(req.id))
    reservations: List[ReplacementRequestReservationRead] = []
    for link in links:
        extras = rr_svc.reservation_read_extras(session, link)
        reservations.append(
            ReplacementRequestReservationRead(
                id=int(link.id),
                replacement_request_id=int(link.replacement_request_id),
                inventory_reservation_id=link.inventory_reservation_id,
                inventory_instance_id=link.inventory_instance_id,
                serial_number=extras.get("serial_number"),
                part_number=extras.get("part_number"),
            )
        )
    ait_rows = rr_svc.list_ait_attachments(session, int(req.id))
    ait_attachments: List[ReplacementRequestAitAttachmentRead] = [
        ReplacementRequestAitAttachmentRead(
            id=int(row.id),
            replacement_request_id=int(row.replacement_request_id),
            display_name=row.display_name,
            file_id=row.file_id,
            occurrence_attachment_id=row.occurrence_attachment_id,
            created_at=row.created_at,
        )
        for row in ait_rows
        if row.id is not None
    ]
    me_name = None
    if req.assigned_me_id:
        me = session.get(User, req.assigned_me_id)
        if me:
            me_name = me.full_name or me.username
    return ReplacementRequestRead(
        id=int(req.id),
        case_id=int(req.case_id),
        faulty_entity_id=req.faulty_entity_id,
        faulty_entity_type=req.faulty_entity_type,
        faulty_entity_ref_id=req.faulty_entity_ref_id,
        requested_by_id=int(req.requested_by_id),
        assigned_me_id=req.assigned_me_id,
        assigned_me_name=me_name,
        status=req.status,
        pd_decision=req.pd_decision,
        reject_reason=req.reject_reason,
        reject_outcome=getattr(req, "reject_outcome", None),
        abort_reason=req.abort_reason,
        issued_serial=getattr(req, "issued_serial", None),
        issued_instance_id=getattr(req, "issued_instance_id", None),
        issued_at=getattr(req, "issued_at", None),
        shortage_held=bool(getattr(req, "shortage_held", False)),
        red_notified_at=getattr(req, "red_notified_at", None),
        quarantined_instance_id=getattr(req, "quarantined_instance_id", None),
        ait_decision=getattr(req, "ait_decision", None),
        ait_reject_reason=getattr(req, "ait_reject_reason", None),
        created_at=req.created_at,
        updated_at=req.updated_at,
        reservations=reservations,
        ait_attachments=ait_attachments,
    )


@router.post(
    "/maintenance-cases/{case_id}/replacement-requests/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def create_replacement_request(
    case_id: int,
    payload: ReplacementRequestCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.replacement_request",
            "create_maintenance_cases",
        )
    ),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.create_replacement_request(
        session,
        case,
        actor=current_user,
        faulty_entity_id=payload.faulty_entity_id,
    )

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="replacement_requested",
        title="Replacement request created",
        message=(
            f"{case.case_number or f'Case #{case.id}'}: "
            "Immediate replacement requested (Track A)"
        ),
        href=f"/maintenance/cases/{case.id}",
        priority="high",
        actor=current_user,
        include_pd=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )

    session.commit()
    session.refresh(req)
    return _serialize_replacement_request(session, req)


@router.get(
    "/maintenance-cases/{case_id}/replacement-requests/",
    response_model=List[ReplacementRequestRead],
    tags=["maintenance-cases"],
)
def list_replacement_requests(
    case_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_maintenance_cases")),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    rows = rr_svc.list_requests_for_case(session, case_id)
    return [_serialize_replacement_request(session, row) for row in rows]


@router.get(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def get_replacement_request(
    case_id: int,
    request_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_maintenance_cases")),
):
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    return _serialize_replacement_request(session, req)


@router.post(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/assign-me/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def assign_replacement_request_me(
    case_id: int,
    request_id: int,
    payload: ReplacementRequestAssignMePayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.assign_me",
            "inventory.reserve",
        )
    ),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    rr_svc.assign_me(session, req, assigned_me_id=payload.assigned_me_id)

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="replacement_me_assigned",
        title="ME assigned to replacement",
        message=(
            f"{case.case_number or f'Case #{case.id}'}: "
            f"ME user #{payload.assigned_me_id} assigned"
        ),
        href=f"/maintenance/cases/{case.id}",
        priority="high",
        actor=current_user,
        include_pd=True,
        include_maintenance=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )

    session.commit()
    session.refresh(req)
    return _serialize_replacement_request(session, req)


@router.get(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/available-stock/",
    response_model=List[ReplacementStockOptionRead],
    tags=["maintenance-cases"],
)
def list_replacement_available_stock(
    case_id: int,
    request_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.assign_me",
            "inventory.reserve",
        )
    ),
):
    """Free part/serial options for Track A reserve (PD/HM), not the IM catalog."""
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    return rr_svc.list_available_replacement_stock(session, case, req)


@router.post(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/reserve/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def reserve_replacement_request(
    case_id: int,
    request_id: int,
    payload: ReplacementRequestReservePayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.assign_me",
            "inventory.reserve",
        )
    ),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    rr_svc.reserve_for_request(
        session,
        case,
        req,
        actor=current_user,
        inventory_id=payload.inventory_id,
        inventory_instance_id=payload.inventory_instance_id,
        part_number=payload.part_number,
        serial_number=payload.serial_number,
        target_entity_type=payload.target_entity_type,
        target_entity_id=payload.target_entity_id,
        notes=payload.notes,
    )
    session.commit()
    session.refresh(req)
    return _serialize_replacement_request(session, req)


@router.post(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/pd-decision/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def pd_decide_replacement_request(
    case_id: int,
    request_id: int,
    payload: ReplacementRequestPdDecisionPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.replacement_approve",
        )
    ),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    rr_svc.pd_decide(
        session,
        case,
        req,
        actor=current_user,
        decision=payload.decision,
        reject_reason=payload.reject_reason,
        reject_outcome=payload.reject_outcome,
    )

    from app.services.app_notification_service import notify

    approved = (payload.decision or "").strip().lower() == "approve"
    outcome = (payload.reject_outcome or "").strip().lower() if not approved else ""
    if approved:
        title = "Replacement request approved"
        message = f"{case.case_number or f'Case #{case.id}'}: PD approved — Track A continues"
        event_type = "replacement_approved"
    elif outcome == "issue_fixed":
        title = "Maintenance case closed — issue fixed"
        message = (
            f"{case.case_number or f'Case #{case.id}'}: "
            f"PD rejected replacement — issue fixed. Case closed. {payload.reject_reason or ''}"
        )
        event_type = "case_closed"
    elif outcome == "modification_required":
        title = "Replacement needs modification"
        message = (
            f"{case.case_number or f'Case #{case.id}'}: "
            f"PD rejected — modification required. Re-submit after updates. {payload.reject_reason or ''}"
        )
        event_type = "replacement_rejected"
    else:
        title = "Replacement request rejected"
        message = (
            f"{case.case_number or f'Case #{case.id}'}: "
            f"PD rejected — {payload.reject_reason or ''}"
        )
        event_type = "replacement_rejected"

    notify(
        session,
        event_type=event_type,
        title=title,
        message=message,
        href=f"/maintenance/cases/{case.id}",
        priority="high",
        actor=current_user,
        include_pd=True,
        include_maintenance=True,
        extra_user_ids=[int(req.requested_by_id)] if getattr(req, "requested_by_id", None) else None,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )

    session.commit()
    session.refresh(req)
    return _serialize_replacement_request(session, req)


@router.post(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/resubmit/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def resubmit_replacement_request(
    case_id: int,
    request_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "create_maintenance_cases",
            "edit_maintenance_cases",
            "maintenance.occurrence_report",
        )
    ),
):
    """Opener re-sends a modification_required rejection back to PD for approval."""
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    rr_svc.resubmit_after_modification(session, case, req, actor=current_user)

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="replacement_requested",
        title="Replacement re-submitted for PD approval",
        message=(
            f"{case.case_number or f'Case #{case.id}'}: "
            "Requester updated the request after PD modification feedback"
        ),
        href=f"/maintenance/cases/{case.id}",
        priority="high",
        actor=current_user,
        include_pd=True,
        include_maintenance=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )

    session.commit()
    session.refresh(req)
    return _serialize_replacement_request(session, req)


@router.post(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/request-issue/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def me_request_replacement_issue(
    case_id: int,
    request_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.request_issue",
            "maintenance.replacement_request",
        )
    ),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    rr_svc.me_request_issue(session, req)

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="replacement_issue_requested",
        title="ME requested IM issue",
        message=(
            f"{case.case_number or f'Case #{case.id}'}: "
            "ME requested ISSUE of reserved replacement inventory"
        ),
        href=f"/maintenance/cases/{case.id}",
        priority="high",
        actor=current_user,
        include_im=True,
        include_pd=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )

    session.commit()
    session.refresh(req)
    return _serialize_replacement_request(session, req)


@router.post(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/im-issue/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def im_issue_replacement_request(
    case_id: int,
    request_id: int,
    payload: ReplacementRequestImIssuePayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.im_issue",
            "issue_inventory",
            "inventory.issue",
        )
    ),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    try:
        rr_svc.im_issue(
            session,
            case,
            req,
            actor=current_user,
            signature_type=payload.signature_type,
            signature_payload=payload.signature_payload,
            notes=payload.notes,
        )
    except HTTPException:
        session.commit()  # persist shortage_held when set
        session.refresh(req)
        if req.shortage_held:
            from app.services.app_notification_service import notify

            notify(
                session,
                event_type="replacement_shortage",
                title="Replacement stock shortage",
                message=(
                    f"{case.case_number or f'Case #{case.id}'}: "
                    "IM cannot issue — shortage held (no fake issue)"
                ),
                href=f"/maintenance/cases/{case.id}",
                priority="high",
                actor=current_user,
                include_pd=True,
                include_assigned_hm=True,
                project_id=case.project_id,
                entity_type="maintenance_case",
                entity_id=case.id,
            )
            session.commit()
        raise

    from app.services.app_notification_service import notify

    sn = req.issued_serial or "S/N"
    notify(
        session,
        event_type="replacement_shipped",
        title="Replacement shipped (RED)",
        message=(
            f"{case.case_number or f'Case #{case.id}'}: "
            f"Replacement {sn} issued — Track A open (RED)"
        ),
        href=f"/maintenance/cases/{case.id}",
        priority="high",
        actor=current_user,
        include_pd=True,
        include_im=True,
        include_maintenance=True,
        include_assigned_hm=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )
    notify(
        session,
        event_type="replacement_case_open",
        title="RED — replacement case open",
        message=(
            f"{case.case_number or f'Case #{case.id}'}: "
            "Replacement case open on Project/Order/Flight/SDLS"
        ),
        href=f"/projects/{case.project_id}" if case.project_id else f"/maintenance/cases/{case.id}",
        priority="high",
        actor=current_user,
        include_pd=True,
        include_assigned_hm=True,
        include_concerned_pd=True,
        project_id=case.project_id,
        entity_type="project",
        entity_id=case.project_id,
        dedupe_key=f"replacement_case_open:{case.id}",
    )

    session.commit()
    session.refresh(req)
    return _serialize_replacement_request(session, req)


@router.post(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/ait/start/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def me_start_ait(
    case_id: int,
    request_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.ait_upload",
        )
    ),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    rr_svc.me_start_ait(session, req)

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="ait_in_progress",
        title="AIT in progress",
        message=(
            f"{case.case_number or f'Case #{case.id}'}: "
            "ME notified AIT / site integration in progress"
        ),
        href=f"/maintenance/cases/{case.id}",
        priority="normal",
        actor=current_user,
        include_pd=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )

    session.commit()
    session.refresh(req)
    return _serialize_replacement_request(session, req)


@router.post(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/ait/attachments/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def upload_ait_attachment(
    case_id: int,
    request_id: int,
    payload: ReplacementRequestAitAttachmentPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.ait_upload",
            "upload_attachments",
        )
    ),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    rr_svc.upload_ait_attachment(
        session,
        req,
        display_name=payload.display_name,
        file_id=payload.file_id,
        occurrence_attachment_id=payload.occurrence_attachment_id,
    )

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="ait_in_progress",
        title="AIT evidence uploaded",
        message=(
            f"{case.case_number or f'Case #{case.id}'}: "
            f"AIT attachment '{payload.display_name}' uploaded"
        ),
        href=f"/maintenance/cases/{case.id}",
        priority="normal",
        actor=current_user,
        include_pd=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )

    session.commit()
    session.refresh(req)
    return _serialize_replacement_request(session, req)


@router.post(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/ait/pd-decision/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def pd_ait_decide_replacement_request(
    case_id: int,
    request_id: int,
    payload: ReplacementRequestAitDecisionPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.ait_approve",
        )
    ),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    rr_svc.pd_ait_decide(
        session,
        req,
        decision=payload.decision,
        reject_reason=payload.reject_reason,
    )

    from app.services.app_notification_service import notify

    approved = (payload.decision or "").strip().lower() == "approve"
    notify(
        session,
        event_type="ait_approved" if approved else "ait_rejected",
        title="AIT approved" if approved else "AIT rejected",
        message=(
            f"{case.case_number or f'Case #{case.id}'}: "
            + (
                "AIT approved — Track A patch_delivered"
                if approved
                else f"AIT rejected — re-issue loop ({payload.reject_reason or ''})"
            )
        ),
        href=f"/maintenance/cases/{case.id}",
        priority="high" if not approved else "normal",
        actor=current_user,
        include_im=True,
        include_maintenance=True,
        include_pd=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )

    session.commit()
    session.refresh(req)
    return _serialize_replacement_request(session, req)


@router.post(
    "/maintenance-cases/{case_id}/replacement-requests/{request_id}/abort/",
    response_model=ReplacementRequestRead,
    tags=["maintenance-cases"],
)
def abort_replacement_request(
    case_id: int,
    request_id: int,
    payload: ReplacementRequestAbortPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(
        require_any_permission(
            "maintenance.replacement_approve",
            "maintenance.case_close",
            "edit_maintenance_cases",
        )
    ),
):
    """RA-017 — abort Track A (e.g. later NFF); clear RED; keep audit."""
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    req = rr_svc.get_request(session, request_id, case_id=case_id)
    rr_svc.abort_track_a(session, req, reason=payload.reason)

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="replacement_aborted",
        title="Replacement request aborted",
        message=(
            f"{case.case_number or f'Case #{case.id}'}: "
            f"Track A aborted — {payload.reason}"
        ),
        href=f"/maintenance/cases/{case.id}",
        priority="high",
        actor=current_user,
        include_pd=True,
        include_im=True,
        include_maintenance=True,
        include_assigned_hm=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case.id,
    )

    session.commit()
    session.refresh(req)
    return _serialize_replacement_request(session, req)


@router.get(
    "/maintenance-assignments/mine/",
    response_model=List[MaintenanceAssignedWorkRead],
    tags=["maintenance-assignments"],
)
def list_my_maintenance_assignments(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Personal MMHD inbox for any signed-in user.

    Rows are filtered to assigned / previously-acted / currently-authorized tasks.
    """
    from app.services.maintenance_assignment_service import list_maintenance_assigned_work

    return [
        MaintenanceAssignedWorkRead.model_validate(row)
        for row in list_maintenance_assigned_work(session, current_user)
    ]


@router.get(
    "/maintenance-cases/{case_id}/dual-track/",
    response_model=DualTrackBoardRead,
    tags=["maintenance-cases"],
)
def get_dual_track_board(
    case_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_maintenance_cases")),
):
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    board = rr_svc.build_dual_track_board(session, case)
    track_a = board.get("track_a")
    return DualTrackBoardRead(
        case_id=int(case.id),
        track_a=(
            _serialize_replacement_request(session, track_a) if track_a else None
        ),
        track_a_status=board.get("track_a_status"),
        track_b_status=board.get("track_b_status"),
        track_b_rework_id=board.get("track_b_rework_id"),
        track_b_reception_date=board.get("track_b_reception_date"),
        track_b_discarded=bool(board.get("track_b_discarded")),
        track_b_terminal=bool(board.get("track_b_terminal")),
    )


@router.post(
    "/item-rework/{rework_id}/assign-investigating-pd/",
    response_model=ReturnedUnitRead,
    tags=["maintenance-cases"],
)
def assign_returned_unit_investigating_pd(
    rework_id: int,
    payload: AssignInvestigatingPdPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_maintenance_cases")),
):
    rework = field_svc.assign_investigating_pd(
        session, rework_id, pd_user_id=payload.pd_user_id
    )
    session.commit()
    session.refresh(rework)
    return _serialize_returned_unit(session, rework)


@router.get(
    "/oem-warranty-claims/",
    response_model=List[OemWarrantyClaimRead],
    tags=["oem-warranty-claims"],
)
def list_oem_warranty_claims(
    response: Response,
    maintenance_case_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_maintenance_cases")),
):
    count_stmt = select(func.count()).select_from(OemWarrantyClaim)
    query = select(OemWarrantyClaim)
    if maintenance_case_id is not None:
        count_stmt = count_stmt.where(
            OemWarrantyClaim.maintenance_case_id == maintenance_case_id
        )
        query = query.where(OemWarrantyClaim.maintenance_case_id == maintenance_case_id)
    if status:
        count_stmt = count_stmt.where(OemWarrantyClaim.status == status)
        query = query.where(OemWarrantyClaim.status == status)
    set_list_total_header(response, session.exec(count_stmt).one())
    rows = session.exec(
        query.order_by(OemWarrantyClaim.id.desc()).offset(skip).limit(limit)
    ).all()
    return [OemWarrantyClaimRead.model_validate(row) for row in rows]


@router.post(
    "/oem-warranty-claims/",
    response_model=OemWarrantyClaimRead,
    status_code=201,
    tags=["oem-warranty-claims"],
)
def create_oem_warranty_claim(
    payload: OemWarrantyClaimCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_maintenance_cases")),
):
    rework = session.get(InventoryReworkCase, payload.rework_case_id)
    if not rework:
        raise HTTPException(status_code=404, detail="Rework case not found")
    claim, action = field_svc.create_or_require_warranty_claim(
        session,
        rework=rework,
        actor=current_user,
        force_discard=payload.force_discard,
        notes=payload.notes,
    )
    if action == "discard" or claim is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Warranty is not active for this unit. Confirm discard instead of opening a claim."
            ),
        )
    session.commit()
    session.refresh(claim)
    return OemWarrantyClaimRead.model_validate(claim)


@router.put(
    "/oem-warranty-claims/{claim_id}/",
    response_model=OemWarrantyClaimRead,
    tags=["oem-warranty-claims"],
)
def update_oem_warranty_claim(
    claim_id: int,
    payload: OemWarrantyClaimUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_maintenance_cases")),
):
    claim = session.get(OemWarrantyClaim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Warranty claim not found")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(claim, key, value)
    claim.updated_at = datetime.now(timezone.utc)
    session.add(claim)
    track_b_svc.sync_claim_closed_if_needed(
        session, claim, actor=current_user
    )
    session.commit()
    session.refresh(claim)
    return OemWarrantyClaimRead.model_validate(claim)


@router.put(
    "/maintenance-cases/{case_id}/",
    response_model=MaintenanceCaseRead,
    tags=["maintenance-cases"],
)
def update_maintenance_case(
    case_id:      int,
    payload:      MaintenanceCaseUpdate,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("edit_maintenance_cases")),
):
    """
    Update case status and/or resolution notes.
    Automatically sets closed_at when status transitions to 'closed'.

    REQUEST:  { "status": "resolved", "resolution_notes": "Burnt capacitor replaced." }
    RESPONSE: Updated MaintenanceCaseRead
    """
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")

    next_status = payload.status if "status" in payload.model_dump(exclude_unset=True) else None
    if next_status in (CaseStatus.RESOLVED, CaseStatus.CLOSED):
        if not check_permission(current_user, "maintenance.case_close"):
            raise HTTPException(
                status_code=403,
                detail="User does not have permission: maintenance.case_close",
            )
        # Apply payload fields that affect Soft/NFF detection before the gate
        dump = payload.model_dump(exclude_unset=True)
        for k in ("onsite_outcome", "resolution_type", "resolution_notes"):
            if k in dump:
                setattr(case, k, dump[k])
        rr_svc.assert_dual_track_close_allowed(session, case)

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(case, k, v)
    if payload.status == CaseStatus.RESOLVED and not case.resolved_at:
        case.resolved_at = datetime.now(timezone.utc)
    if payload.status == CaseStatus.CLOSED:
        if not case.closed_at:
            case.closed_at = datetime.now(timezone.utc)
        if not case.resolved_at:
            case.resolved_at = datetime.now(timezone.utc)
        rr_svc.finalize_track_a_on_case_close(session, case)
    elif payload.status == CaseStatus.RESOLVED:
        rr_svc.clear_replacement_red(session, int(case.id))
    session.add(case)
    from app.services.app_notification_service import notify

    status_val = str(getattr(payload, "status", None) or getattr(case, "status", "") or "").lower()
    if "resolved" in status_val and "closed" not in status_val:
        notify(
            session,
            event_type="case_resolved",
            title="Maintenance case resolved",
            message=case.case_number or f"Case #{case.id}",
            href=f"/maintenance/cases/{case.id}",
            priority="low",
            actor=current_user,
            include_maintenance=True,
            include_assigned_hm=True,
            extra_user_ids=[int(case.reported_by)] if getattr(case, "reported_by", None) else None,
            project_id=case.project_id,
            entity_type="maintenance_case",
            entity_id=case.id,
        )
    if "closed" in status_val:
        notify(
            session,
            event_type="case_closed",
            title="Maintenance case closed",
            message=case.case_number or f"Case #{case.id}",
            href=f"/maintenance/cases/{case.id}",
            priority="medium",
            actor=current_user,
            include_maintenance=True,
            include_assigned_hm=True,
            include_pd=True,
            extra_user_ids=[int(case.reported_by)] if getattr(case, "reported_by", None) else None,
            project_id=case.project_id,
            entity_type="maintenance_case",
            entity_id=case.id,
        )
    session.commit()
    session.refresh(case)
    return _build_case_read(session, case)

def _hard_delete_maintenance_case(session: Session, case: MaintenanceCase) -> None:
    """Delete child rows that lack DB ON DELETE CASCADE, then the case."""
    case_id = int(case.id)

    # Track A: AIT attachments → reservations → replacement requests
    req_ids = list(
        session.exec(
            select(ReplacementRequest.id).where(ReplacementRequest.case_id == case_id)
        ).all()
    )
    if req_ids:
        for req_id in req_ids:
            for row in session.exec(
                select(ReplacementRequestAitAttachment).where(
                    ReplacementRequestAitAttachment.replacement_request_id == int(req_id)
                )
            ).all():
                session.delete(row)
            for row in session.exec(
                select(ReplacementRequestReservation).where(
                    ReplacementRequestReservation.replacement_request_id == int(req_id)
                )
            ).all():
                session.delete(row)
        for row in session.exec(
            select(ReplacementRequest).where(ReplacementRequest.case_id == case_id)
        ).all():
            session.delete(row)

    # Occurrence Report children (FK has no ON DELETE CASCADE)
    for row in session.exec(
        select(MaintenanceOccurrenceAttachment).where(
            MaintenanceOccurrenceAttachment.case_id == case_id
        )
    ).all():
        session.delete(row)
    for row in session.exec(
        select(MaintenanceOccurrenceOfficer).where(
            MaintenanceOccurrenceOfficer.case_id == case_id
        )
    ).all():
        session.delete(row)

    # Optional links — detach rather than delete inventory/rework history
    for claim in session.exec(
        select(OemWarrantyClaim).where(OemWarrantyClaim.maintenance_case_id == case_id)
    ).all():
        claim.maintenance_case_id = None
        session.add(claim)
    for rework in session.exec(
        select(InventoryReworkCase).where(
            InventoryReworkCase.maintenance_case_id == case_id
        )
    ).all():
        rework.maintenance_case_id = None
        session.add(rework)

    session.flush()
    session.delete(case)


@router.delete(
    "/maintenance-cases/{case_id}/",
    tags=["maintenance-cases"],
)
def delete_maintenance_case(
    case_id:      int,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("delete_maintenance_cases")),
):
    """
    Hard delete. Allowed for open or closed cases. Cascades occurrence /
    replacement-request children that are not ON DELETE CASCADE at the DB.
    """
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    if case.status not in (CaseStatus.OPEN, CaseStatus.CLOSED):
        raise HTTPException(
            status_code=400,
            detail=(
                "Only open or closed cases may be deleted. "
                f"Current status: {getattr(case.status, 'value', case.status)}."
            ),
        )
    try:
        _hard_delete_maintenance_case(session, case)
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete maintenance case: {exc}",
        ) from exc
    return {"detail": f"Maintenance case {case_id} deleted."}

# =============================================================================
# ENDPOINTS — FAULTY ENTITY
# =============================================================================

@router.post(
    "/maintenance-cases/{case_id}/faulty-entities/",
    response_model=FaultyEntityRead,
    status_code=201,
    tags=["faulty-entities"],
)
def add_faulty_entity(
    case_id:      int,
    payload:      FaultyEntityCreate,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("create_faulty_entities")),
):
    """
    Manually add one faulty entity to a case.
    Use /cascade-fault/ when you need automatic parent propagation.

    REQUEST:
        {
          "entity_type": "component", "entity_id": 42,
          "fault_type":  "hardware",
          "fault_description": "Capacitor C12 visibly burnt.",
          "parent_faulty_entity_id": 7
        }
    RESPONSE 201:
        { "id": 3, "case_id": 1, "entity_type": "component",
          "status": "identified", "actions": [] }
    """
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    print("Payload Data:  ", payload)
    data = payload.model_dump()
    data["identified_by"] = data.get("identified_by") or current_user.id
    fe = FaultyEntity(case_id=case_id, **data)
    print("Adding Faulty Entity on Backend", fe)
    session.add(fe)
    session.commit()
    session.refresh(fe)
    return fe
 
@router.post(
    "/maintenance-cases/{case_id}/cascade-fault/",
    response_model=FaultyEntityCascadeRead,
    status_code=201,
    tags=["faulty-entities"],
)
def cascade_fault(
    case_id:      int,
    payload:      FaultyEntityCascadeCreate,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("create_faulty_entities")),
):
    """
    Identify a root faulty entity and automatically propagate upward
    through the hierarchy, creating one FaultyEntity per ancestor level.

    REQUEST:
        {
          "root_entity_type":  "component", "root_entity_id": 42,
          "fault_type":        "hardware",
          "fault_description": "Burnt capacitor C12."
        }
    RESPONSE 201:
        {
          "created_faulty_entities": [
            { "entity_type": "component", "status": "confirmed_faulty", ... },
            { "entity_type": "unit",      "status": "identified", ... },
            { "entity_type": "module",    "status": "identified", ... }
          ],
          "total_levels_cascaded": 3,
          "message": "Fault cascaded up 3 hierarchy levels."
        }
    """
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    created = _cascade_fault_up(
        session,
        case_id,
        payload.root_entity_type,
        payload.root_entity_id,
        payload.fault_type,
        payload.fault_description,
        current_user.id,
    )
    n = len(created)
    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="cascade_fault",
        title="Fault cascaded up hierarchy",
        message=f"Fault cascaded {n} level{'s' if n != 1 else ''} on case #{case_id}",
        href=f"/maintenance/cases/{case_id}",
        priority="high",
        actor=current_user,
        include_maintenance=True,
        include_pd=True,
        project_id=case.project_id,
        entity_type="maintenance_case",
        entity_id=case_id,
    )
    session.commit()
    return FaultyEntityCascadeRead(
        created_faulty_entities=created,
        total_levels_cascaded=n,
        message=f"Fault cascaded up {n} hierarchy level{'s' if n != 1 else ''}.",
    )

@router.get(
    "/maintenance-cases/{case_id}/faulty-entities/",
    response_model=List[FaultyEntityRead],
    tags=["faulty-entities"],
)
def list_faulty_entities(
    case_id:      int,
    status:       Optional[FaultyEntityStatus] = None,
    entity_type:  Optional[EntityType]          = None,
    skip:         int = 0,
    limit:        int = 100,
    sort_by:      Optional[str] = None,
    sort_order:   Optional[str] = None,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_faulty_entities")),
):
    """
    List all faulty entities for a case. Filter by status or entity_type.

    RESPONSE 200: [ { faulty_entity 1 }, { faulty_entity 2 }, ... ]
    """
    query = select(FaultyEntity).where(FaultyEntity.case_id == case_id).options(
        noload(FaultyEntity.actions),
        noload(FaultyEntity.identified_by_user),
    )
    if status:
        query = query.where(FaultyEntity.status == status)
    if entity_type:
        query = query.where(FaultyEntity.entity_type == entity_type)
    query = apply_sort(query, FaultyEntity, sort_by=sort_by, sort_order=sort_order)
    rows = session.exec(query.offset(skip).limit(limit)).all()
    return [
        FaultyEntityRead.model_validate(row).model_copy(update={"actions": []})
        for row in rows
    ]

@router.get(
    "/faulty-entities/",
    response_model=List[FaultyEntityRead],
    tags=["faulty-entities"],
)
def list_faulty_entities(
    response: Response,
    skip:         int = 0,
    limit:        int = 100,
    sort_by:      Optional[str] = None,
    sort_order:   Optional[str] = None,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_faulty_entities")),
):
    """
    List all faulty entities for a case. Filter by status or entity_type.

    RESPONSE 200: [ { faulty_entity 1 }, { faulty_entity 2 }, ... ]
    """
    set_list_total_header(
        response,
        session.exec(select(func.count()).select_from(FaultyEntity)).one(),
    )
    query = select(FaultyEntity).options(
        noload(FaultyEntity.actions),
        noload(FaultyEntity.identified_by_user),
    )
    # if status:
    #     query = query.where(FaultyEntity.status == status)
    # if entity_type:
        # query = query.where(FaultyEntity.entity_type == entity_type)
    query = apply_sort(query, FaultyEntity, sort_by=sort_by, sort_order=sort_order)
    rows = session.exec(query.offset(skip).limit(limit)).all()
    return [
        FaultyEntityRead.model_validate(row).model_copy(update={"actions": []})
        for row in rows
    ]


def _lookup_entity_oem_name(
    session: Session,
    entity_type: str | EntityType | None,
    entity_id: int | None,
) -> Optional[str]:
    if entity_type is None or entity_id is None:
        return None
    try:
        et = (
            entity_type
            if isinstance(entity_type, EntityType)
            else EntityType(str(entity_type).lower().strip())
        )
    except ValueError:
        return None
    entry = _ENTITY_MODEL_MAP.get(et)
    if not entry:
        return None
    model_cls, _, _ = entry
    row = session.get(model_cls, entity_id)
    if not row:
        return None
    oem = getattr(row, "oem_name", None)
    if oem is None:
        return None
    trimmed = str(oem).strip()
    return trimmed or None


@router.get(
    "/faulty-entities/product-fault-history/",
    response_model=ProductFaultHistoryRead,
    tags=["faulty-entities"],
)
def get_product_fault_history(
    part_number: str,
    oem_name: Optional[str] = None,
    limit: int = 200,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_faulty_entities")),
):
    """
    Fault history for the same product (part number), aggregated by OEM.

    Returns same-OEM vs different-OEM counts relative to `oem_name` (current
    entity OEM), plus a chronological history list for drill-down.
    """
    pn = (part_number or "").strip()
    if not pn:
        raise HTTPException(status_code=400, detail="part_number is required")

    current_oem = (oem_name or "").strip() or None
    capped = max(1, min(limit, 500))

    records = session.exec(
        select(FaultyEntity)
        .where(FaultyEntity.part_number == pn)
        .order_by(FaultyEntity.identified_at.desc())
        .limit(capped)
    ).all()

    history: list[ProductFaultHistoryItem] = []
    same_oem = 0
    different_oem = 0
    unknown_oem = 0
    oem_cache: dict[tuple[str, int], Optional[str]] = {}

    for row in records:
        cache_key = (str(row.entity_type).lower(), int(row.entity_id))
        if cache_key not in oem_cache:
            oem_cache[cache_key] = _lookup_entity_oem_name(
                session, row.entity_type, row.entity_id
            )
        row_oem = oem_cache[cache_key]

        same: Optional[bool] = None
        if current_oem and row_oem:
            same = row_oem.casefold() == current_oem.casefold()
            if same:
                same_oem += 1
            else:
                different_oem += 1
        elif current_oem and not row_oem:
            unknown_oem += 1
        elif not current_oem and row_oem:
            unknown_oem += 1
        else:
            unknown_oem += 1

        item = ProductFaultHistoryItem.model_validate(row).model_copy(
            update={
                "actions": [],
                "oem_name": row_oem,
                "same_oem": same,
            }
        )
        history.append(item)

    last = history[0] if history else None
    return ProductFaultHistoryRead(
        part_number=pn,
        current_oem=current_oem,
        same_oem_fault_count=same_oem,
        different_oem_fault_count=different_oem,
        unknown_oem_fault_count=unknown_oem,
        total_fault_count=len(history),
        last_fault_at=last.identified_at if last else None,
        last_fault_id=last.id if last else None,
        history=history,
    )


@router.get(
    "/faulty-entities/{fe_id}/",
    response_model=FaultyEntityRead,
    tags=["faulty-entities"],
)
def get_faulty_entity(
    fe_id:        int,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_faulty_entities")),
):
    fe = session.get(FaultyEntity, fe_id)
    if not fe:
        raise HTTPException(status_code=404, detail="Faulty entity not found")
    return fe

@router.put(
    "/faulty-entities/{fe_id}/",
    response_model=FaultyEntityRead,
    tags=["faulty-entities"],
)
def update_faulty_entity(
    fe_id:        int,
    payload:      FaultyEntityUpdate,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("edit_faulty_entities")),
):
    """
    Update fault classification or status.
    When resolving, supply resolution_type; resolved_at is set automatically.

    REQUEST:  { "status": "resolved", "resolution_type": "repaired" }
    RESPONSE: Updated FaultyEntityRead
    """
    
    print("payload ", payload)
    fe = session.get(FaultyEntity, fe_id)
    if not fe:
        raise HTTPException(status_code=404, detail="Faulty entity not found")

    previous_status = fe.status
    resolution_type = payload.resolution_type or fe.resolution_type
    config_fields = {
        "old_part_number",
        "new_part_number",
        "old_serial_number",
        "new_serial_number",
        "remarks",
    }

    if payload.old_part_number is None and payload.new_part_number is None:
        old_part, old_serial = get_hardware_part_serial(session, fe.entity_type, fe.entity_id)
    else:
        old_part, old_serial = payload.old_part_number, payload.old_serial_number

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key in config_fields:
            continue
        setattr(fe, key, value)

    if payload.status == FaultyEntityStatus.RESOLVED:
        resolved_fault_type = payload.fault_type if payload.fault_type is not None else fe.fault_type
        skip_fault_class = resolution_type in (
            ResolutionType.NO_FAULT_FOUND,
            ResolutionType.SOFT_FIXED,
            ResolutionType.CLEAR,
        )
        if not skip_fault_class and resolved_fault_type == FaultType.UNCLASSIFIED:
            raise HTTPException(
                status_code=400,
                detail="Fault type must be selected before resolving a faulty entity."
            )
        if not fe.resolved_at:
            fe.resolved_at = datetime.now(timezone.utc)

        if resolution_type and previous_status != FaultyEntityStatus.RESOLVED:
            create_configuration_history_for_resolve(
                session,
                entity_type=fe.entity_type,
                entity_pk=fe.entity_id,
                maintenance_case_id=fe.case_id,
                performed_by=current_user.id,
                faulty_entity_id=fe.id,
                resolution_type=resolution_type,
                fault_type=resolved_fault_type,
                old_part_number=old_part,
                new_part_number=payload.new_part_number,
                old_serial_number=old_serial,
                new_serial_number=payload.new_serial_number,
                remarks=payload.remarks,
            )

            # Field replace → open IM return/rework linked to this case
            if resolution_type == ResolutionType.REPLACED:
                case = session.get(MaintenanceCase, fe.case_id)
                if case:
                    field_svc.create_returned_unit_rework(
                        session,
                        case=case,
                        faulty_entity_id=int(fe.id),
                        entity_type=str(fe.entity_type),
                        entity_id=int(fe.entity_id),
                        part_number=old_part or fe.part_number,
                        serial_number=old_serial or fe.serial_number,
                        actor=current_user,
                        notes=payload.remarks,
                    )

    session.add(fe)
    session.commit()
    session.refresh(fe)
    return fe

@router.delete(
    "/faulty-entities/{fe_id}/",
    tags=["faulty-entities"],
)
def delete_faulty_entity(
    fe_id:        int,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("delete_faulty_entities")),
):
    fe = session.get(FaultyEntity, fe_id)
    if not fe:
        raise HTTPException(status_code=404, detail="Faulty entity not found")
    if fe.actions:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a faulty entity that has recorded actions."
        )
    session.delete(fe)
    session.commit()
    return {"detail": f"Faulty entity {fe_id} deleted."}

@router.get(
    "/entities/{entity_type}/{entity_id}/maintenance-history/",
    response_model=List[FaultyEntityRead],
    tags=["faulty-entities"],
)
def get_entity_maintenance_history(
    entity_type:  EntityType,
    entity_id:    int,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_faulty_entities")),
):
    """
    Full fault history of a single entity across ALL cases — past and present.
    Use this to detect repeat failures on the same unit or component.

    RESPONSE 200:
        [
          { "case_id": 1, "resolution_type": "repaired",   "resolved_at": "2024-05-05..." },
          { "case_id": 5, "resolution_type": "replaced",   "resolved_at": "2024-09-11..." }
        ]
    """
    records = session.exec(
        select(FaultyEntity)
        .where(FaultyEntity.entity_type == entity_type)
        .where(FaultyEntity.entity_id == entity_id)
        .order_by(FaultyEntity.identified_at.desc())
    ).all()
    return records


def mark_children_healthy(session: Session, fe: FaultyEntity, status: FaultyEntityStatus):

    children = session.exec(
        select(FaultyEntity).where(
            FaultyEntity.case_id == fe.case_id,
            FaultyEntity.parent_entity_id == fe.entity_id,
            FaultyEntity.parent_entity_type == fe.entity_type,
        )
    ).all()
    for child in children:
        child.identified_by = fe.identified_by
        if status is not None and status == FaultyEntityStatus.HEALTHY:
            child.status = FaultyEntityStatus.HEALTHY
        elif status == FaultyEntityStatus.CONFIRMED_FAULTY:
            child.status = FaultyEntityStatus.UNDER_INSPECTION
        elif status == FaultyEntityStatus.NO_FAULT_FOUND:
            child.status = FaultyEntityStatus.NO_FAULT_FOUND
        elif status == FaultyEntityStatus.RESOLVED:
            child.status = FaultyEntityStatus.RESOLVED
            child.resolved_at = datetime.now(timezone.utc)
        mark_children_healthy(session, child, child.status)

@router.put(
    "/faulty-entities-Children/{fe_id}/",
    response_model=FaultyEntityRead,
)
def update_faulty_Children(
    fe_id: int,
    payload: FaultyEntityUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_faulty_entities")),
):

    fe = session.get(FaultyEntity, fe_id)

    if not fe:
        raise HTTPException(404, "Faulty entity not found")

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(fe, k, v)

    if payload.status == FaultyEntityStatus.HEALTHY:
        mark_children_healthy(session, fe, payload.status)

    session.commit()
    session.refresh(fe)

    return fe
# =============================================================================
# ENDPOINTS — MAINTENANCE ACTION
# =============================================================================

@router.post(
    "/maintenance-actions/",
    response_model=MaintenanceActionRead,
    status_code=201,
    tags=["maintenance-actions"],
)
def create_maintenance_action(
    # fe_id:        int,
    payload:      MaintenanceActionCreate,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("create_maintenance_actions")),
):
    """
    Log an action (inspection, repair, replacement, testing, etc.)
    against a faulty entity.

    REQUEST:
        {
          "action_type": "replacement",
          "notes":       "Replaced burnt capacitor C12 (100µF 50V).",
          "outcome":     "pass",
          "replacement_entity_id":   99,
          "replacement_entity_type": "component"
        }
    RESPONSE 201:
        {
          "id": 1, "faulty_entity_id": 3,
          "action_type": "replacement", "outcome": "pass",
          "performed_at": "2024-05-05T14:30:00Z"
        }
    """
    fe_id = payload.faulty_entity_id
    fe = session.get(FaultyEntity, fe_id)
    if not fe:
        raise HTTPException(status_code=404, detail="Faulty entity not found")
    data = payload.model_dump()
    data["performed_by"] = data.get("performed_by") or current_user.id
    action = MaintenanceAction(**data)
    session.add(action)

    # When a replacement action passes, auto-resolve the faulty entity.
    if (
        payload.action_type == ActionType.REPLACEMENT
        and payload.outcome == ActionOutcome.PASS
    ):
        if fe.fault_type == FaultType.UNCLASSIFIED:
            raise HTTPException(
                status_code=400,
                detail="Fault type must be selected before resolving a faulty entity."
            )
        fe.status = FaultyEntityStatus.RESOLVED
        fe.resolution_type = ResolutionType.REPLACED
        fe.resolved_at = datetime.now(timezone.utc)
        session.add(fe)

    session.commit()
    session.refresh(action)
    return action

@router.get(
    "/maintenance-actions/",
    response_model=List[MaintenanceActionRead],
    tags=["maintenance-actions"],
)
def list_all_maintenance_actions(
    skip:         int = 0,
    limit:        int = 100,
    case_id:      Optional[int] = None,
    sort_by:      Optional[str] = None,
    sort_order:   Optional[str] = None,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_actions")),
):
    """List maintenance actions, optionally scoped to a single maintenance case."""
    statement = select(MaintenanceAction).options(
        noload(MaintenanceAction.faulty_entity),
        noload(MaintenanceAction.performed_by_user),
    )
    if case_id is not None:
        statement = (
            statement
            .join(FaultyEntity, MaintenanceAction.faulty_entity_id == FaultyEntity.id)
            .where(FaultyEntity.case_id == case_id)
        )
    statement = apply_sort(
        statement,
        MaintenanceAction,
        sort_by=sort_by,
        sort_order=sort_order,
        default_order=[MaintenanceAction.performed_at.desc()],
    )
    actions = session.exec(statement.offset(skip).limit(limit)).all()
    return [
        MaintenanceActionRead.model_validate(action).model_copy(
            update={"performed_by_user": None}
        )
        for action in actions
    ]

@router.get(
    "/faulty-entities/{fe_id}/actions/",
    response_model=List[MaintenanceActionRead],
    tags=["maintenance-actions"],
)
def list_maintenance_actions(
    fe_id:        int,
    skip:         int = 0,
    limit:        int = 100,
    sort_by:      Optional[str] = None,
    sort_order:   Optional[str] = None,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_actions")),
):
    """List all actions recorded against a faulty entity."""
    statement = select(MaintenanceAction).where(MaintenanceAction.faulty_entity_id == fe_id)
    statement = apply_sort(
        statement,
        MaintenanceAction,
        sort_by=sort_by,
        sort_order=sort_order,
        default_order=[MaintenanceAction.performed_at.desc()],
    )
    return session.exec(statement.offset(skip).limit(limit)).all()

@router.get(
    "/maintenance-actions/{action_id}/",
    response_model=MaintenanceActionRead,
    tags=["maintenance-actions"],
)
def get_maintenance_action(
    action_id:    int,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_actions")),
):
    action = session.get(MaintenanceAction, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Maintenance action not found")
    return action

@router.put(
    "/maintenance-actions/{action_id}/",
    response_model=MaintenanceActionRead,
    tags=["maintenance-actions"],
)
def update_maintenance_action(
    action_id:    int,
    payload:      MaintenanceActionUpdate,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("edit_maintenance_actions")),
):
    """Update notes or outcome of a recorded action."""
    action = session.get(MaintenanceAction, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Maintenance action not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(action, k, v)
    session.add(action)
    session.commit()
    session.refresh(action)
    return action

@router.delete(
    "/maintenance-actions/{action_id}/",
    tags=["maintenance-actions"],
)
def delete_maintenance_action(
    action_id:    int,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("delete_maintenance_actions")),
):
    action = session.get(MaintenanceAction, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Maintenance action not found")
    session.delete(action)
    session.commit()
    return {"detail": f"Maintenance action {action_id} deleted."}

# =============================================================================
# ENDPOINTS — MAINTENANCE DELIVERY
# =============================================================================

@router.post(
    "/maintenance-cases/{case_id}/deliveries/",
    response_model=MaintenanceDeliveryRead,
    status_code=201,
    tags=["maintenance-deliveries"],
)
def create_maintenance_delivery(
    case_id:      int,
    payload:      MaintenanceDeliveryCreate,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("create_maintenance_deliveries")),
):
    """
    Record a re-delivery of the repaired product to the customer.
    Transitions the case status to 'resolved' if not already.

    REQUEST:
        {
          "delivery_type": "re_delivery",
          "received_by":   "John Smith – Site Manager",
          "notes":         "Courier: DHL-XP-9921."
        }
    RESPONSE 201:
        { "id": 1, "case_id": 1, "delivery_type": "re_delivery",
          "status": "dispatched", "created_at": "2024-05-06T08:00:00Z" }
    """
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    data = payload.model_dump()
    data["delivered_by"] = data.get("delivered_by") or current_user.id
    data["status"] = DeliveryStatus.DISPATCHED
    delivery = MaintenanceDelivery(case_id=case_id, **data)
    session.add(delivery)
    # Mark case as resolved when re-delivery is dispatched (if not already).
    if case.status not in (CaseStatus.RESOLVED, CaseStatus.CLOSED):
        rr_svc.assert_dual_track_close_allowed(session, case)
        case.status = CaseStatus.RESOLVED
        if not case.resolved_at:
            case.resolved_at = datetime.now(timezone.utc)
        rr_svc.clear_replacement_red(session, int(case.id))
        session.add(case)
    session.commit()
    session.refresh(delivery)
    return delivery

@router.get(
    "/maintenance-deliveries/",
    response_model=List[MaintenanceDeliveryRead],
    tags=["maintenance-deliveries"],
)
def list_all_maintenance_deliveries(
    skip:         int = 0,
    limit:        int = 100,
    sort_by:      Optional[str] = None,
    sort_order:   Optional[str] = None,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_deliveries")),
):
    """List all maintenance deliveries across cases."""
    statement = select(MaintenanceDelivery).options(
        noload(MaintenanceDelivery.case),
        noload(MaintenanceDelivery.delivered_by_user),
    )
    statement = apply_sort(
        statement,
        MaintenanceDelivery,
        sort_by=sort_by,
        sort_order=sort_order,
        default_order=[MaintenanceDelivery.created_at.desc()],
    )
    deliveries = session.exec(statement.offset(skip).limit(limit)).all()
    return [
        MaintenanceDeliveryRead.model_validate(delivery).model_copy(
            update={"delivered_by_user": None}
        )
        for delivery in deliveries
    ]

@router.get(
    "/maintenance-cases/{case_id}/deliveries/",
    response_model=List[MaintenanceDeliveryRead],
    tags=["maintenance-deliveries"],
)
def list_maintenance_deliveries(
    case_id:      int,
    sort_by:      Optional[str] = None,
    sort_order:   Optional[str] = None,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_deliveries")),
):
    """List all delivery records for a case (full re-delivery history)."""
    statement = select(MaintenanceDelivery).where(MaintenanceDelivery.case_id == case_id)
    statement = apply_sort(
        statement,
        MaintenanceDelivery,
        sort_by=sort_by,
        sort_order=sort_order,
        default_order=[MaintenanceDelivery.created_at.desc()],
    )
    return session.exec(statement).all()

@router.get(
    "/maintenance-deliveries/{delivery_id}/",
    response_model=MaintenanceDeliveryRead,
    tags=["maintenance-deliveries"],
)
def get_maintenance_delivery(
    delivery_id:  int,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_deliveries")),
):
    delivery = session.get(MaintenanceDelivery, delivery_id)
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery record not found")
    return delivery

@router.put(
    "/maintenance-deliveries/{delivery_id}/",
    response_model=MaintenanceDeliveryRead,
    tags=["maintenance-deliveries"],
)
def update_maintenance_delivery(
    delivery_id:  int,
    payload:      MaintenanceDeliveryUpdate,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("edit_maintenance_deliveries")),
):
    """Update delivery status, received_by, or notes."""
    delivery = session.get(MaintenanceDelivery, delivery_id)
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery record not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(delivery, k, v)
    session.add(delivery)
    session.commit()
    session.refresh(delivery)
    return delivery

@router.post(
    "/maintenance-deliveries/{delivery_id}/confirm/",
    response_model=MaintenanceDeliveryRead,
    tags=["maintenance-deliveries"],
)
def confirm_maintenance_delivery(
    delivery_id:  int,
    received_by:  str,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("edit_maintenance_deliveries")),
):
    """
    Customer confirms receipt of the repaired product.
    Auto-closes the parent case when confirmed.

    RESPONSE:
        { "status": "confirmed_by_customer",
          "delivered_at": "2024-05-07T11:00:00Z",
          "received_by":  "John Smith – Site Manager" }
    """
    delivery = session.get(MaintenanceDelivery, delivery_id)
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery record not found")
    delivery.status      = DeliveryStatus.CONFIRMED_BY_CUSTOMER
    delivery.delivered_at = datetime.now(timezone.utc)
    delivery.received_by  = received_by
    session.add(delivery)
    # Auto-close the case (DT-004 when dual-track not applicable; else DT-003 gate).
    case = session.get(MaintenanceCase, delivery.case_id)
    if case and case.status == CaseStatus.RESOLVED:
        rr_svc.assert_dual_track_close_allowed(session, case)
        case.status    = CaseStatus.CLOSED
        case.closed_at = datetime.now(timezone.utc)
        rr_svc.finalize_track_a_on_case_close(session, case)
        session.add(case)
        from app.services.app_notification_service import notify as notify_close

        notify_close(
            session,
            event_type="case_closed",
            title="Maintenance case closed",
            message=case.case_number or f"Case #{case.id}",
            href=f"/maintenance/cases/{case.id}",
            priority="medium",
            actor=current_user,
            include_maintenance=True,
            include_assigned_hm=True,
            include_pd=True,
            project_id=case.project_id,
            entity_type="maintenance_case",
            entity_id=case.id,
        )
    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="delivery_confirmed",
        title="Maintenance delivery confirmed",
        message=received_by or "Customer confirmed receipt",
        href=f"/maintenance/cases/{delivery.case_id}" if delivery.case_id else "/maintenance",
        priority="medium",
        actor=current_user,
        include_maintenance=True,
        include_pd=True,
        entity_type="maintenance_delivery",
        entity_id=delivery.id,
        project_id=getattr(case, "project_id", None) if case else None,
    )
    session.commit()
    session.refresh(delivery)
    return delivery

@router.delete(
    "/maintenance-deliveries/{delivery_id}/",
    tags=["maintenance-deliveries"],
)
def delete_maintenance_delivery(
    delivery_id:  int,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("delete_maintenance_deliveries")),
):
    delivery = session.get(MaintenanceDelivery, delivery_id)
    if not delivery:
        raise HTTPException(status_code=404, detail="Delivery record not found")
    if delivery.status == DeliveryStatus.CONFIRMED_BY_CUSTOMER:
        raise HTTPException(
            status_code=400,
            detail="Confirmed deliveries cannot be deleted."
        )
    session.delete(delivery)
    session.commit()
    return {"detail": f"Delivery record {delivery_id} deleted."}

# ── E1. Serial-number lookup ──────────────────────────────────────────────────

def _lookup_entity_by_serial(session: Session, serial_number: str) -> EntityLookupRead:
    """
    Look up any current-install hierarchy entity by unique serial number.
    Matches serial_number or original_serial_number (inventory SN).
    Falls back to verified InventoryIssuance install links when hierarchy
    serial columns were never populated.
    Walks up to project/order/customer and down through descendants.
    """
    from sqlalchemy import or_
    from app.domain.workflow_status import ItemStatus
    from app.models.tables import InventoryIssuance

    matched_type: Optional[str] = None
    matched_id: Optional[int] = None
    matched_label: Optional[str] = None
    serialNumber: Optional[str] = None
    PartNumber: Optional[str] = None

    for entity_type, model_cls, identity_attr in _SR_SEARCH_MODELS:
        serial_col = getattr(model_cls, identity_attr)
        original_col = getattr(model_cls, "original_serial_number", None)
        conditions = [serial_col == serial_number]
        if original_col is not None:
            conditions.append(original_col == serial_number)
        statement = select(model_cls).where(or_(*conditions))
        if hasattr(model_cls, "is_current_install"):
            statement = statement.where(model_cls.is_current_install == True)  # noqa: E712
        row = session.exec(statement).first()
        if row:
            matched_type = entity_type
            matched_id = row.id
            original = getattr(row, "original_serial_number", None)
            current = getattr(row, "serial_number", None)
            # Prefer inventory/original SN for response when available.
            serialNumber = str(
                (original or current or serial_number) or serial_number
            )
            PartNumber = str(getattr(row, "part_number", "") or "")
            matched_label = str(getattr(row, "name", serial_number))
            break

    # Hierarchy rows often keep serial_number null after verify; resolve via issuance.
    if not matched_type or matched_id is None:
        issuance = session.exec(
            select(InventoryIssuance)
            .where(
                InventoryIssuance.serial_number == serial_number,
                InventoryIssuance.installed_entity_id.is_not(None),
                InventoryIssuance.installed_entity_type.is_not(None),
                or_(
                    InventoryIssuance.item_lifecycle_status
                    == ItemStatus.INSTALLED_VERIFIED.value,
                    InventoryIssuance.verified_at.is_not(None),
                ),
            )
            .order_by(InventoryIssuance.verified_at.desc())
        ).first()
        if issuance and issuance.installed_entity_type and issuance.installed_entity_id:
            et = str(
                getattr(issuance.installed_entity_type, "value", issuance.installed_entity_type)
            ).strip().lower()
            model_map = {
                str(getattr(entity_type, "value", entity_type)).strip().lower(): model_cls
                for entity_type, model_cls, _identity in _SR_SEARCH_MODELS
            }
            model_cls = model_map.get(et)
            row = session.get(model_cls, issuance.installed_entity_id) if model_cls else None
            if row is not None and (
                not hasattr(row, "is_current_install") or row.is_current_install
            ):
                matched_type = et
                matched_id = int(issuance.installed_entity_id)
                serialNumber = str(issuance.serial_number or serial_number)
                PartNumber = str(
                    issuance.part_number
                    or getattr(row, "part_number", "")
                    or ""
                )
                matched_label = str(getattr(row, "name", serial_number))

    if not matched_type or matched_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"No entity found with serial number '{serial_number}'.",
        )

    ancestors = _resolve_ancestors(session, matched_type, matched_id)
    descendants = _collect_descendants(session, matched_type, matched_id)

    project_id = project_name = order_id = order_ref = customer_id = customer_name = None
    for anc in ancestors:
        if anc.entity_type == EntityType.PROJECT:
            project_id = anc.entity_id
            project_name = anc.entity_name
        elif anc.entity_type == "order":
            order_id = anc.entity_id
            order_ref = anc.entity_name
        elif anc.entity_type == "customer":
            customer_id = anc.entity_id
            customer_name = anc.entity_name

    # Spare inventory serials (or orphan hierarchy rows) are not valid for case lookup.
    if project_id is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Serial number '{serial_number}' is not installed under any project. "
                "Only project-installed hardware can be looked up."
            ),
        )

    # Maintenance cases are only for hardware already shipped (COMPLETED projects).
    from app.domain.workflow_status import ProjectWorkflowStatus
    from app.models.tables import Status

    project = session.get(Project, project_id)
    completed_status_ids = set(
        session.exec(
            select(Status.id).where(
                Status.status_type == "projects",
                Status.status_name == ProjectWorkflowStatus.COMPLETED.value,
            )
        ).all()
    )
    if (
        project is None
        or project.status_id is None
        or project.status_id not in completed_status_ids
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Serial number '{serial_number}' belongs to a project that is not completed. "
                "Maintenance cases can only be opened for hardware already shipped to the customer."
            ),
        )

    return EntityLookupRead(
        matched_entity_type=matched_type,
        matched_entity_id=matched_id,
        matched_label=matched_label,
        ancestors=ancestors,
        descendants=descendants,
        project_id=project_id,
        project_name=project_name,
        order_id=order_id,
        order_ref=order_ref,
        customer_id=customer_id,
        customer_name=customer_name,
        matched_entity_serialNumber=serialNumber,
        matched_entity_PartNumber=PartNumber,
    )


@router.get(
    "/entities/lookup-by-SN/{serial_number}/",
    response_model=EntityLookupRead,
    tags=["entity-lookup"],
)
def lookup_entity_by_SN(
    serial_number: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_faulty_entities")),
):
    """Look up any entity in the hierarchy by its unique serial number."""
    return _lookup_entity_by_serial(session, serial_number)


@router.get(
    "/entities/lookup-by-PN/{part_number}/",
    response_model=EntityLookupRead,
    tags=["entity-lookup"],
    deprecated=True,
)
def lookup_entity_by_PN(
    part_number: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_faulty_entities")),
):
    """
    Deprecated alias: path historically used part number, but lookups are now
    keyed by unique serial number (part numbers are shared across units).
    """
    return _lookup_entity_by_serial(session, part_number)

# ── E2. Suspect all children of a mid-hierarchy fault ─────────────────────────

@router.post(
    "/maintenance-cases/{case_id}/suspect-children/",
    response_model=SuspectChildrenRead,
    status_code=201,
    tags=["faulty-entities"],
)
def suspect_children(
    case_id:      int,
    payload:      SuspectChildrenPayload,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("create_faulty_entities")),
):
    """
    Called when a mid-hierarchy entity (e.g. a module) is known to be faulty
    but the root cause within it has not yet been identified.

    The endpoint:
      1. Creates (or retrieves) the FaultyEntity row for the reported entity
         with status = CONFIRMED_FAULTY.
      2. Walks DOWN the hierarchy and creates one provisional FaultyEntity per
         descendant (unit, component, …) with status = UNDER_INSPECTION.
      3. All provisional rows share parent_faulty_entity_id pointing to step 1.

    These provisional rows act as a checklist for the engineer — every
    descendant is highlighted as a potential fault source.

    After the engineer identifies the actual faulty entity, call
    POST /maintenance-cases/{case_id}/confirm-fault/ to commit the real fault
    and automatically clean up all other provisional rows.

    REQUEST:
        {
          "entity_type":       "module",
          "entity_id":         17,
          "fault_type":        "hardware",
          "fault_description": "Module overheating — root cause TBD."
        }

    RESPONSE 201:
        {
          "parent_faulty_entity_id": 5,
          "suspect_entities_created": [ { unit FE }, { component FE }, ... ],
          "total_suspects": 8,
          "message": "8 descendant entities marked as under_inspection."
        }
    """
    print("Getting data from Backend", payload)
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")

    # Step 1 — Create the confirmed-faulty FE for the reported entity

    parent_fe = FaultyEntity(
        case_id=case_id,
        entity_type=payload.entity_type.value,
        entity_id=payload.entity_id,
        fault_type=payload.fault_type,
        fault_description=payload.fault_description,
        status=FaultyEntityStatus.CONFIRMED_FAULTY,
        identified_by=current_user.id,
        parent_faulty_entity_id=None,
        parent_entity_id=None,
        parent_entity_type=None,
        entity_name=payload.entity_name,
        serial_number=payload.serial_number,
        part_number=payload.part_number,

        )
    # print("@@@@@@@@@@@@@@@@@///////////Suspecting parent on Backend", parent_fe)

    session.add(parent_fe)
    session.flush()       # get parent_fe.id

    # Step 2 — Collect all descendants
    descendants = _collect_descendants(session, payload.entity_type.value, payload.entity_id)
    # print("@@@@@@@@@@@@@@@@@///////////Suspecting decendants", descendants)

    if not descendants:
        session.commit()
        session.refresh(parent_fe)

        return SuspectChildrenRead(
            parent_faulty_entity_id=parent_fe.id,
            suspect_entities_created=[],
            total_suspects=0,
            message="No child entities found — this appears to be a leaf node.",
        )

    # Step 3 — Create provisional UNDER_INSPECTION rows
    suspects = _create_suspect_fes(
        session,
        case_id,
        descendants,
        payload.fault_type,
        parent_fe.id,
        current_user.id,
    )
    # print("@@@@@@@@@@@@@@@@@///////////Suspecting Child on Backend", suspects)
    session.commit()
    session.refresh(parent_fe)
    for s in suspects:
        session.refresh(s)

    n = len(suspects)
    return SuspectChildrenRead(
        parent_faulty_entity_id=parent_fe.id,
        suspect_entities_created=suspects,
        total_suspects=n,
        message=f"{n} descendant entit{'ies' if n != 1 else 'y'} marked as under_inspection.",
    )

# ── E3. Engineer confirms exact fault — clear all healthy sibling suspects ─────

@router.post(
    "/maintenance-cases/{case_id}/confirm-fault/",
    response_model=ConfirmFaultRead,
    status_code=201,
    tags=["faulty-entities"],
)
def confirm_fault(
    case_id:      int,
    payload:      ConfirmFaultPayload,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("create_faulty_entities")),
):
    """
    Called once the engineer has traced the fault to a specific entity (e.g.
    a burnt capacitor inside one of the suspected units).

    The endpoint:
      1. Finds or creates a FaultyEntity for the confirmed entity with
         status = CONFIRMED_FAULTY.
      2. Walks the CASCADE upward (calls existing _cascade_fault_up logic)
         to flag each ancestor as IDENTIFIED — only up to the already-existing
         parent faulty entity (no duplicates).
      3. Deletes all provisional UNDER_INSPECTION faulty-entity rows belonging
         to sibling entities (and their subtrees) that were found healthy.
         ─ No row is left for any healthy entity — no permanent history.
         ─ If an UNDER_INSPECTION row already has an action logged against it,
           it is instead set to NO_FAULT_FOUND (preserved for audit safety).

    REQUEST:
        {
          "confirmed_entity_type":   "component",
          "confirmed_entity_id":     44,
          "fault_type":              "hardware",
          "fault_description":       "Capacitor C12 burnt — 100µF 50V.",
          "parent_faulty_entity_id": 5
        }

    RESPONSE 201:
        {
          "confirmed_faulty_entity": { FaultyEntityRead },
          "cleared_suspect_count":   7,
          "message": "Fault confirmed on component id=44. 7 healthy suspects cleared."
        }
    """
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")

    parent_fe = session.get(FaultyEntity, payload.parent_faulty_entity_id)
    if not parent_fe:
        raise HTTPException(
            status_code=404,
            detail=f"Parent faulty entity {payload.parent_faulty_entity_id} not found. "
                   "Run suspect-children first.",
        )

    # Step 1 — Check for an existing UNDER_INSPECTION row for the confirmed entity.
    # If one was created during suspect-children, upgrade it. Otherwise create fresh.
    confirmed_fe: Optional[FaultyEntity] = session.exec(
        select(FaultyEntity).where(
            FaultyEntity.case_id == case_id,
            FaultyEntity.entity_type == payload.confirmed_entity_type,
            FaultyEntity.entity_id == payload.confirmed_entity_id,
        )
    ).first()

    if confirmed_fe:
        # Upgrade the provisional suspect row
        confirmed_fe.status            = FaultyEntityStatus.CONFIRMED_FAULTY
        confirmed_fe.fault_type        = payload.fault_type
        confirmed_fe.fault_description = payload.fault_description
        session.add(confirmed_fe)
    else:
        # No suspect row existed — create a fresh CONFIRMED_FAULTY row
        confirmed_fe = FaultyEntity(
            case_id=case_id,
            entity_type=payload.confirmed_entity_type,
            entity_id=payload.confirmed_entity_id,
            fault_type=payload.fault_type,
            fault_description=payload.fault_description,
            status=FaultyEntityStatus.CONFIRMED_FAULTY,
            parent_faulty_entity_id=payload.parent_faulty_entity_id,
            identified_by=current_user.id,
        )
        session.add(confirmed_fe)

    session.flush()

    # Step 2 — Clear all healthy sibling suspects
    cleared = _clear_healthy_fes(
        session,
        case_id,
        payload.parent_faulty_entity_id,
        payload.confirmed_entity_type,
        payload.confirmed_entity_id,
    )

    session.commit()
    session.refresh(confirmed_fe)

    return ConfirmFaultRead(
        confirmed_faulty_entity=confirmed_fe,
        cleared_suspect_count=cleared,
        message=(
            f"Fault confirmed on {payload.confirmed_entity_type} "
            f"id={payload.confirmed_entity_id}. "
            f"{cleared} healthy suspect{'s' if cleared != 1 else ''} cleared."
        ),
    )


@router.post(
    "/maintenance-cases/admin-hierarchy-replace/",
    response_model=AdminHierarchyReplaceRead,
    status_code=201,
    tags=["maintenance-cases"],
)
def admin_hierarchy_replace_endpoint(
    payload: AdminHierarchyReplacePayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_maintenance_cases")),
):
    """
    Admin one-shot replacement from the hierarchy dashboard.
    Creates a maintenance case, confirms a hardware fault, progresses statuses,
    resolves with replacement, writes configuration history, and updates part number.
    """
    if not check_permission(current_user, "create_faulty_entities"):
        raise HTTPException(
            status_code=403,
            detail="User does not have permission: create_faulty_entities",
        )

    from app.services.admin_hierarchy_replace import admin_hierarchy_replace

    result = admin_hierarchy_replace(
        session,
        project_id=payload.project_id,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        new_part_number=payload.new_part_number,
        performed_by=current_user,
        new_serial_number=payload.new_serial_number,
        notes=payload.notes,
        inventory_item_id=payload.inventory_item_id,
        inventory_instance_id=payload.inventory_instance_id,
    )
    return AdminHierarchyReplaceRead(**result)