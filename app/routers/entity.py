from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import or_
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import (
    Component,
    Entity,
    EntityStatusHistory,
    InventoryIssuance,
    InventoryIssuanceEvent,
    InventoryReservation,
    Module,
    Project,
    Status,
    Subsystem,
    System,
    Unit,
    User,
    WorkflowAuditEvent,
)
from app.schemas import schemas
from app.routers.auth import require_permission
from app.models.base import EntityType
from app.models.helpers import _PARENT_MAP
from app.services.configuration_history import resolve_generic_entity
from app.services.entity_replacement_service import get_replacement_chain
from app.services.sorting import apply_sort
from app.services.workflow_audit_service import (
    event_to_dict,
    resolve_actor_role,
)
from app.domain.workflow_audit import WORKFLOW_AUDIT_ACTION_LABELS, WorkflowAuditAction

router = APIRouter()

# ===================== ENTITY ENDPOINTS =====================
# Create New Entity 
@router.post("/entities/", response_model=schemas.EntityRead, tags=["entities"])
def create_entity(entity: schemas.EntityCreate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("create_entities"))):
    db_entity = Entity(**entity.model_dump())
    session.add(db_entity)
    session.commit()
    session.refresh(db_entity)
    return db_entity

# List All Entities with Pagination and Optional Filtering 
@router.get("/entities/", response_model=List[schemas.EntityRead], tags=["entities"])
def list_entities(
    skip: int = 0,
    limit: int = 100,
    sort_by: str | None = None,
    sort_order: str | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_entities")),
):
    stmt = apply_sort(select(Entity), Entity, sort_by=sort_by, sort_order=sort_order)
    return session.exec(stmt.offset(skip).limit(limit)).all()

@router.get("/entities/lookup/", response_model=schemas.EntityRead, tags=["entities"])
def lookup_entity(
    entity_type: str = Query(..., description="Hardware entity type, e.g. system or System"),
    entity_pk: int = Query(..., description="Primary key of the hardware record"),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_entities")),
):
    """Resolve generic Entity row from hardware entity type and primary key."""
    match = resolve_generic_entity(session, entity_type, entity_pk)
    if not match:
        raise HTTPException(
            status_code=404,
            detail=f"No generic entity found for {entity_type} with id {entity_pk}.",
        )
    return match

# Get Single Entity by ID
@router.get("/entities/{entity_id}/", response_model=schemas.EntityRead, tags=["entities"])
def get_entity(entity_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_entities"))):
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity

# Update Existing Entity (Partial Update)
@router.put("/entities/{entity_id}/", response_model=schemas.EntityRead, tags=["entities"])
def update_entity(entity_id: int, entity: schemas.EntityUpdate, session: Session = Depends(get_session), current_user: User = Depends(require_permission("edit_entities"))):
    db_entity = session.get(Entity, entity_id)
    
    if not db_entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    for k, v in entity.model_dump(exclude_unset=True).items():
        setattr(db_entity, k, v)
    session.add(db_entity)
    session.commit()
    session.refresh(db_entity)
    return db_entity

# Delete Entity by ID 
@router.delete("/entities/{entity_id}/", tags=["entities"])
def delete_entity(entity_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("delete_entities"))):
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    session.delete(entity)
    session.commit()
    return {"ok": True}

# Additional Endpoints for Entity Status History and Maintenance Logs 
@router.get("/entities/{entity_id}/status-history/", response_model=List[schemas.EntityStatusHistoryRead], tags=["entities"])
def list_entity_status_history(entity_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_entities"))):
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity.status_history


def _hardware_project_id(session: Session, entity_type: str, entity: object) -> Optional[int]:
    """Resolve the owning project without relying on relationship loading."""
    et = entity_type.strip().lower()
    if et == "project":
        return int(getattr(entity, "id"))
    if et == "system":
        return getattr(entity, "project_id", None)
    if et == "subsystem":
        parent = session.get(System, getattr(entity, "system_id", None))
        return getattr(parent, "project_id", None) if parent else None
    if et == "module":
        parent = session.get(Subsystem, getattr(entity, "subsystem_id", None))
        return _hardware_project_id(session, "subsystem", parent) if parent else None
    if et == "unit":
        parent = session.get(Module, getattr(entity, "module_id", None))
        return _hardware_project_id(session, "module", parent) if parent else None
    if et == "component":
        parent = session.get(Unit, getattr(entity, "unit_id", None))
        return _hardware_project_id(session, "unit", parent) if parent else None
    return None


def _lifecycle_event(
    *,
    event_id: str,
    occurred_at,
    actor: Optional[User],
    action: str,
    entity_type: str,
    entity_id: int,
    project_id: Optional[int],
    old_value=None,
    new_value=None,
    remarks: Optional[str] = None,
) -> dict:
    return {
        "id": event_id,
        "occurred_at": occurred_at,
        "actor_user_id": actor.id if actor else None,
        "actor_username": actor.username if actor else None,
        "actor_role": resolve_actor_role(actor),
        "action": action,
        "action_label": WORKFLOW_AUDIT_ACTION_LABELS.get(action, action),
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "project_id": project_id,
        "old_value": old_value,
        "new_value": new_value,
        "remarks": remarks,
    }


@router.get(
    "/entities/{entity_type}/{entity_pk}/lifecycle-history/",
    response_model=List[schemas.EntityLifecycleHistoryRead],
    tags=["entities"],
)
def list_entity_lifecycle_history(
    entity_type: str,
    entity_pk: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_entities")),
):
    """Return one reconstructable timeline for a hardware node.

    Legacy status rows, reservations, assignments, issuance, testing, and HM
    verification are normalized into the same actor/timestamp shape.
    """
    normalized = entity_type.strip().lower()
    models = {
        "system": System,
        "subsystem": Subsystem,
        "module": Module,
        "unit": Unit,
        "component": Component,
        "project": Project,
    }
    model = models.get(normalized)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}")
    hardware_entity = session.get(model, entity_pk)
    if not hardware_entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    project_id = _hardware_project_id(session, normalized, hardware_entity)
    generic = resolve_generic_entity(session, normalized, entity_pk)
    events: list[dict] = []
    status_rows: list[EntityStatusHistory] = []

    if generic:
        status_rows = list(
            session.exec(
                select(EntityStatusHistory)
                .where(EntityStatusHistory.entity_id == generic.id)
                .order_by(EntityStatusHistory.changed_at)
            ).all()
        )
        previous_status = None
        for row in status_rows:
            status = session.get(Status, row.status_id)
            actor = session.get(User, row.changed_by) if row.changed_by else None
            status_name = status.status_name if status else f"Status #{row.status_id}"
            event_id = f"status-{row.id}"
            events.append(
                _lifecycle_event(
                    event_id=event_id,
                    occurred_at=row.changed_at,
                    actor=actor,
                    action=(
                        WorkflowAuditAction.CREATED
                        if previous_status is None
                        else WorkflowAuditAction.STATUS_CHANGED
                    ),
                    entity_type=normalized,
                    entity_id=entity_pk,
                    project_id=project_id,
                    old_value={"status": previous_status} if previous_status else None,
                    new_value={"status": status_name, "status_id": row.status_id},
                    remarks=row.notes,
                )
            )
            previous_status = status_name

    current_status_id = getattr(hardware_entity, "status_id", None) or getattr(
        generic, "status_id", None
    )
    if not status_rows and current_status_id is not None:
        status = session.get(Status, current_status_id)
        status_name = status.status_name if status else f"Status #{current_status_id}"
        events.append(
            _lifecycle_event(
                event_id=f"synthetic-created-{normalized}-{entity_pk}",
                occurred_at=getattr(hardware_entity, "created_at"),
                actor=None,
                action=WorkflowAuditAction.CREATED,
                entity_type=normalized,
                entity_id=entity_pk,
                project_id=project_id,
                new_value={"status": status_name, "status_id": current_status_id},
                remarks="Initial lifecycle state",
            )
        )

    reservations = list(
        session.exec(
            select(InventoryReservation).where(
                InventoryReservation.target_entity_type == normalized,
                InventoryReservation.target_entity_id == entity_pk,
            )
        ).all()
    )
    issuances = list(
        session.exec(
            select(InventoryIssuance).where(
                or_(
                    (
                        InventoryIssuance.target_entity_type == normalized
                    )
                    & (InventoryIssuance.target_entity_id == entity_pk),
                    (
                        InventoryIssuance.installed_entity_type == normalized
                    )
                    & (InventoryIssuance.installed_entity_id == entity_pk),
                )
            )
        ).all()
    )
    reservation_ids = {int(row.id) for row in reservations if row.id is not None}
    issuance_ids = {int(row.id) for row in issuances if row.id is not None}

    audits = list(
        session.exec(
            select(WorkflowAuditEvent)
            .where(
                WorkflowAuditEvent.project_id == project_id
                if project_id is not None
                else WorkflowAuditEvent.entity_type == normalized
            )
            .order_by(WorkflowAuditEvent.occurred_at)
        ).all()
    )
    project_context_actions = {
        WorkflowAuditAction.PROJECT_CREATED,
        WorkflowAuditAction.PROJECT_APPROVED,
        WorkflowAuditAction.HIERARCHY_GENERATED,
        WorkflowAuditAction.HM_ASSIGNED,
    }
    for audit in audits:
        audit_dict = event_to_dict(audit)
        audit_entity_type = audit.entity_type.strip().lower()
        relevant = (
            (audit_entity_type == normalized and audit.entity_id == str(entity_pk))
            or (
                audit_entity_type == "inventory_reservation"
                and audit.entity_id in {str(item) for item in reservation_ids}
            )
            or (
                audit_entity_type == "inventory_issuance"
                and audit.entity_id in {str(item) for item in issuance_ids}
            )
            or (
                normalized != "project"
                and audit_entity_type == "project"
                and audit.action in project_context_actions
            )
            or (normalized == "project" and audit_entity_type == "project")
        )
        if relevant:
            events.append(audit_dict)

    # Some older installations have immutable issuance ledger events but no
    # workflow audit rows. Reconstruct those events without duplicating actions
    # that are already represented by a workflow audit.
    issuance_event_actions = {
        "issued": WorkflowAuditAction.ISSUED,
        "reissued": WorkflowAuditAction.RE_ISSUED,
        "install_started": WorkflowAuditAction.INSTALLATION_IN_PROGRESS,
        "test_passed": WorkflowAuditAction.UNDER_TESTING,
        "test_failed": WorkflowAuditAction.UNDER_TESTING,
        "complete_reported": WorkflowAuditAction.COMPLETE_REPORTED,
        "verified": WorkflowAuditAction.INSTALLED_VERIFIED,
        "return_requested": WorkflowAuditAction.RETURNED,
        "return_accepted": WorkflowAuditAction.RETURNED,
        "return_rejected": WorkflowAuditAction.RE_ISSUED,
        "reverted": WorkflowAuditAction.RETURNED,
        "item_returned": WorkflowAuditAction.RETURNED,
    }
    audited_actions_by_issuance: dict[str, set[str]] = {}
    for audit in audits:
        if audit.entity_type.strip().lower() == "inventory_issuance":
            audited_actions_by_issuance.setdefault(audit.entity_id, set()).add(
                audit.action.upper()
            )

    for issuance in issuances:
        issuance_rows = session.exec(
            select(InventoryIssuanceEvent).where(
                InventoryIssuanceEvent.issuance_id == issuance.id
            )
            .order_by(InventoryIssuanceEvent.created_at)
        ).all()
        audited_actions = audited_actions_by_issuance.get(str(issuance.id), set())
        for row in issuance_rows:
            action = issuance_event_actions.get(row.event_type)
            if action is None or action in audited_actions:
                continue
            event_id = f"issuance-event-{row.id}"
            actor = session.get(User, row.actor_user_id) if row.actor_user_id else None
            events.append(
                _lifecycle_event(
                    event_id=event_id,
                    occurred_at=row.created_at,
                    actor=actor,
                    action=action,
                    entity_type=normalized,
                    entity_id=entity_pk,
                    project_id=project_id,
                    new_value={
                        "issuance_id": issuance.id,
                        "event_type": row.event_type,
                        "status": (
                            "INSTALLATION_IN_PROGRESS"
                            if row.event_type == "install_started"
                            else (
                                "UNDER_TESTING"
                                if row.event_type in {"test_passed", "test_failed"}
                                else (
                                    "INSTALLED_VERIFIED"
                                    if row.event_type == "verified"
                                    else None
                                )
                            )
                        ),
                        "test_result": (
                            "pass"
                            if row.event_type == "test_passed"
                            else "fail"
                            if row.event_type == "test_failed"
                            else None
                        ),
                    },
                    remarks=row.notes,
                )
            )

    hardware_assignment_id = getattr(hardware_entity, "assigned_developer_id", None)
    if hardware_assignment_id is not None and not any(
        event["action"] == WorkflowAuditAction.ASSIGNED for event in events
    ):
        developer = session.get(User, hardware_assignment_id)
        events.append(
            _lifecycle_event(
                event_id=f"synthetic-assigned-{normalized}-{entity_pk}",
                occurred_at=getattr(hardware_entity, "updated_at", hardware_entity.created_at),
                actor=None,
                action=WorkflowAuditAction.ASSIGNED,
                entity_type=normalized,
                entity_id=entity_pk,
                project_id=project_id,
                new_value={
                    "assigned_developer_id": int(hardware_assignment_id),
                    "assigned_developer_name": (
                        developer.full_name or developer.username
                        if developer
                        else None
                    ),
                },
                remarks="Current developer assignment from legacy entity data",
            )
        )

    # HM and PD fields predate the audit table in some databases. Add
    # non-mutating snapshots so the current accountable people are still
    # visible in the node timeline.
    project = (
        hardware_entity if normalized == "project"
        else session.get(Project, project_id) if project_id is not None
        else None
    )
    if project is not None:
        if project.assigned_hm_id and not any(
            event["action"] == WorkflowAuditAction.HM_ASSIGNED for event in events
        ):
            hm = session.get(User, project.assigned_hm_id)
            events.append(
                _lifecycle_event(
                    event_id=f"synthetic-hm-assigned-{project.id}",
                    occurred_at=getattr(project, "updated_at", project.created_at),
                    actor=None,
                    action=WorkflowAuditAction.HM_ASSIGNED,
                    entity_type="project",
                    entity_id=int(project.id),
                    project_id=int(project.id),
                    new_value={
                        "assigned_hm_id": int(project.assigned_hm_id),
                        "assigned_hm_name": (
                            hm.full_name or hm.username if hm else None
                        ),
                    },
                    remarks="Current HM assignment from project data",
                )
            )
        if project.approved_by_id and not any(
            event["action"] == WorkflowAuditAction.PROJECT_APPROVED
            for event in events
        ):
            pd = session.get(User, project.approved_by_id)
            events.append(
                _lifecycle_event(
                    event_id=f"synthetic-project-approved-{project.id}",
                    occurred_at=project.approved_at or project.updated_at,
                    actor=pd,
                    action=WorkflowAuditAction.PROJECT_APPROVED,
                    entity_type="project",
                    entity_id=int(project.id),
                    project_id=int(project.id),
                    new_value={
                        "approved_by_id": int(project.approved_by_id),
                        "approved_by_name": (
                            pd.full_name or pd.username if pd else None
                        ),
                    },
                    remarks="Approval snapshot from project data",
                )
            )

    # Old reservations may predate workflow audit. Add a non-duplicating
    # fallback so their actor and dates are still visible.
    audited_reservation_actions: dict[int, set[str]] = {}
    for row in audits:
        if (
            row.entity_type.strip().lower() == "inventory_reservation"
            and row.entity_id.isdigit()
        ):
            audited_reservation_actions.setdefault(int(row.entity_id), set()).add(
                row.action.upper()
            )
    for reservation in reservations:
        reservation_actions = audited_reservation_actions.get(reservation.id, set())
        if WorkflowAuditAction.RESERVED not in reservation_actions:
            actor = session.get(User, reservation.reserved_by_user_id)
            events.append(
                _lifecycle_event(
                    event_id=f"reservation-{reservation.id}-reserved",
                    occurred_at=reservation.reserved_at,
                    actor=actor,
                    action=WorkflowAuditAction.RESERVED,
                    entity_type=normalized,
                    entity_id=entity_pk,
                    project_id=project_id,
                    new_value={"reservation_id": reservation.id, "status": "RESERVED"},
                    remarks=reservation.notes,
                )
            )
        if reservation.released_at and not {
            WorkflowAuditAction.RELEASED,
            WorkflowAuditAction.AUTO_RELEASE_EXPIRY,
        }.intersection(reservation_actions):
            release_actor = (
                session.get(User, reservation.released_by_user_id)
                if reservation.released_by_user_id
                else None
            )
            events.append(
                _lifecycle_event(
                    event_id=f"reservation-{reservation.id}-released",
                    occurred_at=reservation.released_at,
                    actor=release_actor,
                    action=WorkflowAuditAction.RELEASED,
                    entity_type=normalized,
                    entity_id=entity_pk,
                    project_id=project_id,
                    old_value={"status": "RESERVED"},
                    new_value={"status": "RELEASED"},
                )
            )

    return sorted(events, key=lambda item: item["occurred_at"], reverse=True)

@router.get("/entities/{entity_id}/maintenance-logs/", response_model=List[schemas.MaintenanceLogRead], tags=["entities"])
def list_entity_maintenance_logs(entity_id: int, session: Session = Depends(get_session), current_user: User = Depends(require_permission("view_entities"))):
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity.maintenance_logs


@router.get(
    "/entities/{entity_type}/{entity_pk}/replacement-chain/",
    tags=["entities"],
)
def list_entity_replacement_chain(
    entity_type: str,
    entity_pk: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_entities")),
):
    """Return all install versions for a hardware slot (original + replacements)."""
    try:
        normalized = EntityType(entity_type.lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}") from exc

    chain = get_replacement_chain(session, normalized, entity_pk)
    if not chain:
        raise HTTPException(status_code=404, detail="Entity not found")

    return [
        {
            "id": row.id,
            "entity_type": normalized.value,
            "name": getattr(row, "name", None),
            "part_number": getattr(row, "part_number", None),
            "serial_number": getattr(row, "serial_number", None),
            "configuration_item": getattr(row, "configuration_item", None),
            "original_part_number": getattr(row, "original_part_number", None),
            "original_serial_number": getattr(row, "original_serial_number", None),
            "is_current_install": getattr(row, "is_current_install", True),
            "root_entity_id": getattr(row, "root_entity_id", row.id),
            "replaced_entity_id": getattr(row, "replaced_entity_id", None),
            "replacement_sequence": getattr(row, "replacement_sequence", 0),
            "replaced_at": getattr(row, "replaced_at", None),
            "installation_date": getattr(row, "installation_date", None),
            "installed_by_id": getattr(row, "installed_by_id", None),
            "created_at": getattr(row, "created_at", None),
        }
        for row in chain
    ]




@router.get("/part-numbers/", response_model=list[str])
def get_part_numbers(session: Session = Depends(get_session)):
    part_numbers = set()
    entity_models = list(EntityType)
    
    for entity_type, (_, model, _) in _PARENT_MAP.items():

        if entity_type in {
            EntityType.PROJECT,
            EntityType.ORDER,
            EntityType.CUSTOMER,
        }:
            continue

        rows = session.exec(
            select(model.part_number)
            .where(model.part_number.is_not(None))
        ).all()
        
        part_numbers.update(rows)
        
    return sorted(part_numbers)


@router.get("/serial-numbers/", response_model=list[str])
def get_serial_numbers(
    q: str = Query("", description="Case-insensitive substring filter on serial number"),
    limit: int = Query(25, ge=1, le=100, description="Max results (typeahead)"),
    session: Session = Depends(get_session),
):
    """
    Search serial numbers for hardware currently installed under a project.
    Returns both serial_number and original_serial_number when they differ so
    typeahead matches the SN shown on installed entities and inventory labels.
    """
    from sqlalchemy import or_
    from app.models.tables import System, Subsystem, Module, Unit, Component

    needle = (q or "").strip()
    # Require a short prefix so we never dump tens of thousands of rows.
    if len(needle) < 2:
        return []

    pattern = f"%{needle}%"
    found: set[str] = set()
    per_level = min(limit, 100)

    def _as_serial(value) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def collect_serials(serial_number, original_serial_number) -> None:
        # Include both when they differ so typeahead finds the SN shown in
        # the project UI (serial_number) and the inventory/original SN.
        for value in (
            _as_serial(original_serial_number),
            _as_serial(serial_number),
        ):
            if value:
                found.add(value)

    def collect_rows(rows) -> None:
        for row in rows:
            # SQLAlchemy Row is sequence-like but not a tuple/list — index it.
            try:
                serial_number = row[0]
                original_serial_number = row[1]
            except (TypeError, IndexError, KeyError):
                serial_number, original_serial_number = row, None
            collect_serials(serial_number, original_serial_number)

    def matches_serial(model):
        return or_(
            model.serial_number.ilike(pattern),
            model.original_serial_number.ilike(pattern),
        )

    collect_rows(
        session.exec(
            select(System.serial_number, System.original_serial_number)
            .where(
                System.project_id.is_not(None),
                System.is_current_install == True,  # noqa: E712
                matches_serial(System),
            )
            .order_by(System.original_serial_number, System.serial_number)
            .limit(per_level)
        ).all()
    )

    collect_rows(
        session.exec(
            select(Subsystem.serial_number, Subsystem.original_serial_number)
            .join(System, Subsystem.system_id == System.id)
            .where(
                System.project_id.is_not(None),
                Subsystem.is_current_install == True,  # noqa: E712
                matches_serial(Subsystem),
            )
            .order_by(Subsystem.original_serial_number, Subsystem.serial_number)
            .limit(per_level)
        ).all()
    )

    collect_rows(
        session.exec(
            select(Module.serial_number, Module.original_serial_number)
            .join(Subsystem, Module.subsystem_id == Subsystem.id)
            .join(System, Subsystem.system_id == System.id)
            .where(
                System.project_id.is_not(None),
                Module.is_current_install == True,  # noqa: E712
                matches_serial(Module),
            )
            .order_by(Module.original_serial_number, Module.serial_number)
            .limit(per_level)
        ).all()
    )

    collect_rows(
        session.exec(
            select(Unit.serial_number, Unit.original_serial_number)
            .join(Module, Unit.module_id == Module.id)
            .join(Subsystem, Module.subsystem_id == Subsystem.id)
            .join(System, Subsystem.system_id == System.id)
            .where(
                System.project_id.is_not(None),
                Unit.is_current_install == True,  # noqa: E712
                matches_serial(Unit),
            )
            .order_by(Unit.original_serial_number, Unit.serial_number)
            .limit(per_level)
        ).all()
    )

    collect_rows(
        session.exec(
            select(Component.serial_number, Component.original_serial_number)
            .join(Unit, Component.unit_id == Unit.id)
            .join(Module, Unit.module_id == Module.id)
            .join(Subsystem, Module.subsystem_id == Subsystem.id)
            .join(System, Subsystem.system_id == System.id)
            .where(
                System.project_id.is_not(None),
                Component.is_current_install == True,  # noqa: E712
                matches_serial(Component),
            )
            .order_by(Component.original_serial_number, Component.serial_number)
            .limit(per_level)
        ).all()
    )

    return sorted(found)[:limit]