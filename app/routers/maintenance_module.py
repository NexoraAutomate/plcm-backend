# =============================================================================
# maintenance_module.py
# Maintenance Case Management — Models, Schemas & Endpoints
# Covers: MaintenanceCase → FaultyEntity → MaintenanceAction → MaintenanceDelivery
# =============================================================================

from __future__ import annotations
from sqlalchemy import update
from sqlalchemy.orm import noload
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Field, Relationship, Session, SQLModel, select

# Project-level imports (adjust paths to match your project structure)
from app.database import get_session
from app.auth import check_permission
from .auth import require_permission
# Hierarchy models — adapt class names / FK attribute names to your schema
from app.models.tables import User

# =============================================================================
# ENDPOINTS — MAINTENANCE CASE
# =============================================================================
from app.schemas.Maintennance import EntityLookupRead
from app.models.base import EntityType, ActionType
from app.schemas.Maintennance import *
from app.models.helpers import _generate_case_number, _cascade_fault_up,_SR_SEARCH_MODELS, _collect_descendants,_create_suspect_fes, _clear_healthy_fes, _resolve_ancestors
from app.models.tables import MaintenanceCase, FaultyEntity, MaintenanceAction, MaintenanceDelivery, Project
from app.services.configuration_history import (
    create_configuration_history_for_resolve,
    get_hardware_part_serial,
)
from app.models.base import FaultyEntityStatus, FaultType, ResolutionType
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

router = APIRouter()


from app.schemas.schemas import MaintenanceUserRead


def _build_case_read(
    session: Session,
    case: MaintenanceCase,
    *,
    project: Project | None = None,
    reporter: User | None = None,
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
    return case_read


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
    payload.project_name = project.name if project else "Undefined"
    data = payload.model_dump()
    data["reported_by"] = data.get("reported_by") or current_user.id
    case = MaintenanceCase(case_number=_generate_case_number(session),**data)
    print("-----------------------------------------------------------case Created:---------------------------------------------------------", case)
    session.add(case)
    session.commit()
    session.refresh(case)
    return _build_case_read(session, case)

@router.get(
    "/maintenance-cases/",
    response_model=List[MaintenanceCaseRead],
    tags=["maintenance-cases"],
)
def list_maintenance_cases(
    project_id:   Optional[int] = None,
    status:       Optional[CaseStatus] = None,
    skip:         int = 0,
    limit:        int = 100,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_cases")),
):
    """
    List cases. Filter by project_id and/or status.

    RESPONSE 200: [ { case 1 }, { case 2 }, ... ]
    """
    query = select(MaintenanceCase).options(
        noload(MaintenanceCase.faulty_entities),
        noload(MaintenanceCase.deliveries),
    )
    if project_id:
        query = query.where(MaintenanceCase.project_id == project_id)
    if status:
        query = query.where(MaintenanceCase.status == status)
    cases = session.exec(
        query.order_by(MaintenanceCase.reported_at.desc()).offset(skip).limit(limit)
    ).all()
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
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(case, k, v)
    if payload.status == CaseStatus.CLOSED and not case.closed_at:
        case.closed_at = datetime.now(timezone.utc)
    session.add(case)
    session.commit()
    session.refresh(case)
    return _build_case_read(session, case)

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
    Hard delete. Only permitted on open cases with no associated actions.
    """
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Maintenance case not found")
    if case.status != CaseStatus.OPEN:
        raise HTTPException(
            status_code=400,
            detail="Only open cases with no recorded actions may be deleted."
        )
    session.delete(case)
    session.commit()
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
    skip:         int = 0,
    limit:        int = 100,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_faulty_entities")),
):
    """
    List all faulty entities for a case. Filter by status or entity_type.

    RESPONSE 200: [ { faulty_entity 1 }, { faulty_entity 2 }, ... ]
    """
    query = select(FaultyEntity).options(
        noload(FaultyEntity.actions),
        noload(FaultyEntity.identified_by_user),
    )
    # if status:
    #     query = query.where(FaultyEntity.status == status)
    # if entity_type:
        # query = query.where(FaultyEntity.entity_type == entity_type)
    rows = session.exec(query.offset(skip).limit(limit)).all()
    return [
        FaultyEntityRead.model_validate(row).model_copy(update={"actions": []})
        for row in rows
    ]

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
        if resolved_fault_type == FaultType.UNCLASSIFIED:
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
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_actions")),
):
    """List all maintenance actions across faulty entities."""
    actions = session.exec(
        select(MaintenanceAction)
        .options(
            noload(MaintenanceAction.faulty_entity),
            noload(MaintenanceAction.performed_by_user),
        )
        .order_by(MaintenanceAction.performed_at.desc())
        .offset(skip).limit(limit)
    ).all()
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
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_actions")),
):
    """List all actions recorded against a faulty entity."""
    return session.exec(
        select(MaintenanceAction)
        .where(MaintenanceAction.faulty_entity_id == fe_id)
        .order_by(MaintenanceAction.performed_at.desc())
        .offset(skip).limit(limit)
    ).all()

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
        case.status = CaseStatus.RESOLVED
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
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_deliveries")),
):
    """List all maintenance deliveries across cases."""
    deliveries = session.exec(
        select(MaintenanceDelivery)
        .options(
            noload(MaintenanceDelivery.case),
            noload(MaintenanceDelivery.delivered_by_user),
        )
        .order_by(MaintenanceDelivery.created_at.desc())
        .offset(skip).limit(limit)
    ).all()
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
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_maintenance_deliveries")),
):
    """List all delivery records for a case (full re-delivery history)."""
    return session.exec(
        select(MaintenanceDelivery)
        .where(MaintenanceDelivery.case_id == case_id)
        .order_by(MaintenanceDelivery.created_at.desc())
    ).all()

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
    # Auto-close the case.
    case = session.get(MaintenanceCase, delivery.case_id)
    if case and case.status == CaseStatus.RESOLVED:
        case.status    = CaseStatus.CLOSED
        case.closed_at = datetime.now(timezone.utc)
        session.add(case)
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

# ── E1. SKU / Part-number lookup ──────────────────────────────────────────────

@router.get(
    "/entities/lookup-by-PN/{part_number}/",
    response_model=EntityLookupRead,
    tags=["entity-lookup"],
)
def lookup_entity_by_PN(
    part_number:          str,
    session:      Session = Depends(get_session),
    current_user: User    = Depends(require_permission("view_faulty_entities")),
):
    """
    Look up any entity in the hierarchy by its SKU / part number / user-defined
    identifier.  Does NOT require knowing the project ID upfront.

    The endpoint:
      1. Searches every entity table in _SR_SEARCH_MODELS for a matching SKU.
      2. Walks UP the hierarchy to find the project, order, and customer.
      3. Walks DOWN the hierarchy to enumerate every child entity.

    RESPONSE 200:
        {
          "matched_entity_type": "module",
          "matched_entity_id":   17,
          "matched_label":       "MOD-PCB-001",
          "ancestors": [
            { "entity_type": "subsystem", "entity_id": 5,  "label": "SS-POWER" },
            { "entity_type": "system",    "entity_id": 2,  "label": "SYS-MAIN" },
            { "entity_type": "project",   "entity_id": 1,  "label": "Alpha Plant" },
            { "entity_type": "order",     "entity_id": 3,  "label": "ORD-2024-007" },
            { "entity_type": "customer",  "entity_id": 9,  "label": "Acme Corp" }
          ],
          "descendants": [
            { "entity_type": "unit",      "entity_id": 22, "label": "UNIT-A",  "depth": 1 },
            { "entity_type": "component", "entity_id": 44, "label": "CAP-C12", "depth": 2 },
            ...
          ],
          "project_id": 1, "project_name": "Alpha Plant",
          "order_id":   3, "order_ref":    "ORD-2024-007",
          "customer_id":9, "customer_name":"Acme Corp"
        }

    ERROR 404: SKU not found in any entity table.
    """
    matched_type: Optional[str] = None   # May be entity name
    matched_id:   Optional[int] = None
    matched_label: Optional[str] = None
    serialNumber : Optional[str] = None
    PartNumber : Optional[str] = None
    

    # print (_SR_SEARCH_MODELS)
    for entity_type, model_cls, PN_attr in _SR_SEARCH_MODELS:
        # print(entity_type, model_cls, PN_attr)
        row = session.exec(
            select(model_cls).where(getattr(model_cls, PN_attr) == part_number)
        ).first()
        if row:
            matched_type  = entity_type
            matched_id    = row.id
            serialNumber = str(getattr(row, "serial_number", part_number))
            PartNumber = str(getattr(row, "part_number", part_number))
            matched_label = str(getattr(row, "name", part_number))
            print("partNumber", PartNumber)
            print("serialNumber", serialNumber)
            break

    if not matched_type or matched_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"No entity found with Part Number / identifier '{part_number}'.",
        )

    # Walk up to customer
    ancestors = _resolve_ancestors(session, matched_type, matched_id)
    # print("@@@@@@@@@@@@@@@@@///////////Ancestors: ", ancestors)

    # Walk down to every leaf
    descendants = _collect_descendants(session, matched_type, matched_id)
    print("-------------------------///////////Descendants: ----------------------------------- ", descendants)

    # Extract convenience fields from ancestors
    project_id = project_name = order_id = order_ref = customer_id = customer_name = None
    for anc in ancestors:
        if anc.entity_type == EntityType.PROJECT:
            project_id   = anc.entity_id
            project_name = anc.entity_name
        elif anc.entity_type == "order":          # EntityType.ORDER if defined
            order_id  = anc.entity_id
            order_ref = anc.entity_name
        elif anc.entity_type == "customer":       # EntityType.CUSTOMER if defined
            customer_id   = anc.entity_id
            customer_name = anc.entity_name

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
        matched_entity_serialNumber = serialNumber,
        matched_entity_PartNumber = PartNumber)

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
    )
    return AdminHierarchyReplaceRead(**result)