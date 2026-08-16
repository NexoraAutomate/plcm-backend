"""Spec 10 — defect / rework loop: remove, return, inspect, disposition, re-issue."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.domain.status_transitions import assert_transition
from app.domain.workflow_roles import WorkflowRole, has_workflow_role
from app.domain.workflow_status import ItemStatus
from app.models.base import (
    IssuanceEventType,
    IssuanceStatus,
    REWORK_CYCLE_WARNING_ATTEMPTS,
    ReworkCaseStatus,
    ReworkDisposition,
    ReworkStage,
)
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryIssuance,
    InventoryIssuanceEvent,
    InventoryReworkCase,
    Project,
    User,
)
from app.services.hierarchy_developer_service import _load_entity
from app.services.inventory_issuance_service import (
    issue_inventory_unit,
    record_issuance_event,
)
from app.services.inventory_reservation_service import (
    get_item_status_id,
    item_status_name,
)
from app.domain.workflow_audit import WorkflowAuditAction
from app.services.workflow_audit_service import write_workflow_audit


class ItemReworkError(ValueError):
    pass


DISPOSITION_STATUSES = {
    ReworkDisposition.REPAIRABLE.value: ItemStatus.REPAIRABLE.value,
    ReworkDisposition.REUSABLE.value: ItemStatus.REUSABLE.value,
    ReworkDisposition.SCRAPPED.value: ItemStatus.SCRAPPED.value,
}

REENTRY_STAGES = frozenset(
    {
        ReworkStage.REISSUED.value,
        ReworkStage.RETESTING.value,
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role_names(user: User) -> list[str]:
    return [r.name for r in (user.roles or []) if r.name]


def _actor_role(user: User) -> str | None:
    names = _role_names(user)
    if has_workflow_role(names, WorkflowRole.ADMIN):
        return WorkflowRole.ADMIN.value
    if has_workflow_role(names, WorkflowRole.IM):
        return WorkflowRole.IM.value
    if has_workflow_role(names, WorkflowRole.DEV):
        return WorkflowRole.DEV.value
    if has_workflow_role(names, WorkflowRole.HM):
        return WorkflowRole.HM.value
    return names[0] if names else None


def cycle_warning(attempt_count: int) -> bool:
    return int(attempt_count or 0) >= REWORK_CYCLE_WARNING_ATTEMPTS


def open_rework_for_entity(
    session: Session, entity_type: str, entity_id: int
) -> Optional[InventoryReworkCase]:
    et = (entity_type or "").strip().lower()
    return session.exec(
        select(InventoryReworkCase).where(
            InventoryReworkCase.target_entity_type == et,
            InventoryReworkCase.target_entity_id == int(entity_id),
            InventoryReworkCase.status == ReworkCaseStatus.OPEN.value,
        )
    ).first()


def open_rework_for_issuance(
    session: Session, issuance_id: int
) -> Optional[InventoryReworkCase]:
    return session.exec(
        select(InventoryReworkCase).where(
            InventoryReworkCase.current_issuance_id == int(issuance_id),
            InventoryReworkCase.status == ReworkCaseStatus.OPEN.value,
        )
    ).first()


def rework_progress_fields(
    session: Session, entity_type: str, entity_id: int
) -> dict[str, Any]:
    case = open_rework_for_entity(session, entity_type, entity_id)
    if case is None:
        return {
            "rework_id": None,
            "rework_status": None,
            "rework_stage": None,
            "rework_attempt_count": None,
            "rework_cycle_warning": False,
            "rework_disposition": None,
            "can_remove": False,
            "can_return": False,
        }
    return {
        "rework_id": case.id,
        "rework_status": case.status,
        "rework_stage": case.stage,
        "rework_attempt_count": case.attempt_count,
        "rework_cycle_warning": cycle_warning(case.attempt_count),
        "rework_disposition": case.disposition,
        "can_remove": (
            case.status == ReworkCaseStatus.OPEN.value
            and case.stage == ReworkStage.FAILED.value
        ),
        "can_return": (
            case.status == ReworkCaseStatus.OPEN.value
            and case.stage == ReworkStage.REMOVED.value
        ),
    }


def _require_open_case(session: Session, rework_id: int) -> InventoryReworkCase:
    case = session.get(InventoryReworkCase, rework_id)
    if case is None:
        raise ItemReworkError("Rework case not found")
    if case.status != ReworkCaseStatus.OPEN.value:
        raise ItemReworkError("Rework case is already closed")
    return case


def _require_assigned_developer(case: InventoryReworkCase, actor: User) -> None:
    if case.assigned_developer_id is None:
        raise ItemReworkError("Rework case has no assigned developer")
    if int(case.assigned_developer_id) != int(actor.id):
        names = _role_names(actor)
        if has_workflow_role(names, WorkflowRole.ADMIN):
            return
        raise ItemReworkError(
            "Only the assigned developer can remove or return this item"
        )


def _issuance_for_case(
    session: Session, case: InventoryReworkCase
) -> InventoryIssuance:
    if case.current_issuance_id:
        issuance = session.get(InventoryIssuance, case.current_issuance_id)
        if issuance is not None:
            return issuance
    raise ItemReworkError("Rework case has no current issuance")


def _instance_status(session: Session, case: InventoryReworkCase) -> str:
    if case.current_instance_id:
        instance = session.get(InventoryInstance, case.current_instance_id)
        if instance is not None:
            name = item_status_name(session, instance.status_id)
            if name:
                return name.strip().upper()
    inventory = session.get(Inventory, case.inventory_id)
    if inventory is not None:
        name = item_status_name(session, inventory.status_id)
        if name:
            return name.strip().upper()
    issuance = (
        session.get(InventoryIssuance, case.current_issuance_id)
        if case.current_issuance_id
        else None
    )
    if issuance is not None and issuance.item_lifecycle_status:
        return issuance.item_lifecycle_status.strip().upper()
    return ItemStatus.UNDER_TESTING_REVIEW.value


def _advance_unit_status(
    session: Session,
    case: InventoryReworkCase,
    to_status: str,
    *,
    actor: User,
) -> None:
    current = _instance_status(session, case)
    if current == to_status:
        return
    try:
        assert_transition("item", current, to_status, actor_role=_actor_role(actor))
    except ValueError as exc:
        raise ItemReworkError(str(exc)) from exc
    status_id = get_item_status_id(session, to_status)
    now = _now()
    if case.current_instance_id:
        instance = session.get(InventoryInstance, case.current_instance_id)
        if instance is not None:
            instance.status_id = status_id
            instance.updated_at = now
            session.add(instance)
    inventory = session.get(Inventory, case.inventory_id)
    if inventory is not None:
        inventory.status_id = status_id
        inventory.updated_at = now
        session.add(inventory)
    if case.current_issuance_id:
        issuance = session.get(InventoryIssuance, case.current_issuance_id)
        if issuance is not None:
            issuance.item_lifecycle_status = to_status
            session.add(issuance)


def _record(
    session: Session,
    case: InventoryReworkCase,
    event_type: str,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> None:
    issuance = _issuance_for_case(session, case)
    record_issuance_event(
        session,
        issuance,
        event_type=event_type,
        actor=actor,
        notes=notes,
    )


def ensure_open_rework_case(
    session: Session,
    issuance: InventoryIssuance,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    """Idempotent: create on first fail, increment attempt on loop re-entry."""
    et = (issuance.target_entity_type or "").strip().lower()
    eid = int(issuance.target_entity_id or 0)
    if not et or not eid:
        raise ItemReworkError("Issuance is not bound to a hierarchy node")
    now = _now()
    existing = open_rework_for_entity(session, et, eid)
    if existing is None:
        case = InventoryReworkCase(
            project_id=int(issuance.project_id or 0),
            flight_id=issuance.flight_id,
            sdls_id=issuance.sdls_id,
            target_entity_type=et,
            target_entity_id=eid,
            inventory_id=int(issuance.inventory_id),
            original_instance_id=issuance.inventory_instance_id,
            current_instance_id=issuance.inventory_instance_id,
            current_issuance_id=issuance.id,
            assigned_developer_id=issuance.issued_to_user_id,
            status=ReworkCaseStatus.OPEN.value,
            stage=ReworkStage.FAILED.value,
            attempt_count=1,
            opened_at=now,
            opened_by_id=int(actor.id) if actor.id else None,
            notes=notes,
            created_at=now,
            updated_at=now,
        )
        if not case.project_id:
            raise ItemReworkError("Issuance is not bound to a project")
        session.add(case)
        session.flush()
        record_issuance_event(
            session,
            issuance,
            event_type=IssuanceEventType.REWORK_OPENED.value,
            actor=actor,
            notes=notes or "Fail path opened rework case",
        )
        return case

    same_issuance = existing.current_issuance_id == issuance.id
    if existing.stage in REENTRY_STAGES or not same_issuance:
        existing.attempt_count = int(existing.attempt_count or 1) + 1
        existing.stage = ReworkStage.FAILED.value
        existing.disposition = None
        existing.repaired_at = None
        existing.repaired_by_id = None
        existing.current_issuance_id = issuance.id
        existing.current_instance_id = issuance.inventory_instance_id
        existing.inventory_id = int(issuance.inventory_id)
        existing.assigned_developer_id = issuance.issued_to_user_id
        existing.updated_at = now
        session.add(existing)
        record_issuance_event(
            session,
            issuance,
            event_type=IssuanceEventType.REWORK_OPENED.value,
            actor=actor,
            notes=notes or f"Rework re-entered at attempt {existing.attempt_count}",
        )
        return existing

    existing.current_issuance_id = issuance.id
    existing.updated_at = now
    session.add(existing)
    return existing


def mark_rework_retesting(
    session: Session, entity_type: str, entity_id: int
) -> None:
    case = open_rework_for_entity(session, entity_type, entity_id)
    if case is None:
        return
    if case.stage == ReworkStage.REISSUED.value:
        case.stage = ReworkStage.RETESTING.value
        case.updated_at = _now()
        session.add(case)


def close_rework_for_issuance(
    session: Session,
    issuance: InventoryIssuance,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> Optional[InventoryReworkCase]:
    et = (issuance.target_entity_type or "").strip().lower()
    eid = issuance.target_entity_id
    case = None
    if et and eid is not None:
        case = open_rework_for_entity(session, et, int(eid))
    if case is None and issuance.id:
        case = open_rework_for_issuance(session, int(issuance.id))
    if case is None:
        return None
    now = _now()
    case.status = ReworkCaseStatus.CLOSED.value
    case.closed_at = now
    case.closed_by_id = int(actor.id) if actor.id else None
    case.current_issuance_id = issuance.id
    case.updated_at = now
    if notes:
        case.notes = notes
    session.add(case)
    record_issuance_event(
        session,
        issuance,
        event_type=IssuanceEventType.REWORK_CLOSED.value,
        actor=actor,
        notes=notes or "Rework closed on HM verify",
    )
    return case


def remove_item(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    case = _require_open_case(session, rework_id)
    _require_assigned_developer(case, actor)
    if case.stage != ReworkStage.FAILED.value:
        raise ItemReworkError(
            f"Item can be removed while stage is failed (current: {case.stage})"
        )
    case.stage = ReworkStage.REMOVED.value
    case.updated_at = _now()
    if notes:
        case.notes = notes
    session.add(case)
    _record(
        session,
        case,
        IssuanceEventType.ITEM_REMOVED.value,
        actor=actor,
        notes=notes,
    )
    session.commit()
    session.refresh(case)
    return case


def return_item(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    case = _require_open_case(session, rework_id)
    _require_assigned_developer(case, actor)
    if case.stage != ReworkStage.REMOVED.value:
        raise ItemReworkError(
            f"Item can be returned while stage is removed (current: {case.stage})"
        )
    _advance_unit_status(
        session, case, ItemStatus.RETURNED.value, actor=actor
    )
    issuance = _issuance_for_case(session, case)
    now = _now()
    issuance.status = IssuanceStatus.RETURNED.value
    issuance.closed_at = now
    issuance.closed_by_id = int(actor.id) if actor.id else None
    issuance.item_lifecycle_status = ItemStatus.RETURNED.value
    session.add(issuance)
    case.stage = ReworkStage.RETURNED.value
    case.updated_at = now
    if notes:
        case.notes = notes
    session.add(case)
    record_issuance_event(
        session,
        issuance,
        event_type=IssuanceEventType.ITEM_RETURNED.value,
        actor=actor,
        notes=notes,
    )
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, case.project_id)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.RETURNED,
        entity_type="inventory_rework",
        entity_id=int(case.id),
        actor=actor,
        project_id=case.project_id,
        old_value={"stage": ReworkStage.REMOVED.value},
        new_value={"stage": ReworkStage.RETURNED.value, "status": ItemStatus.RETURNED.value},
        remarks=notes,
    )
    session.commit()
    session.refresh(case)
    return case


def start_inspection(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    case = _require_open_case(session, rework_id)
    if case.stage != ReworkStage.RETURNED.value:
        raise ItemReworkError(
            f"Inspection starts from returned (current: {case.stage})"
        )
    _advance_unit_status(
        session, case, ItemStatus.INSPECTION.value, actor=actor
    )
    case.stage = ReworkStage.INSPECTION.value
    case.updated_at = _now()
    if notes:
        case.notes = notes
    session.add(case)
    _record(
        session,
        case,
        IssuanceEventType.INSPECTION_STARTED.value,
        actor=actor,
        notes=notes,
    )
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, case.project_id)
    session.commit()
    session.refresh(case)
    return case


def disposition_item(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    outcome: str,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    case = _require_open_case(session, rework_id)
    if case.stage != ReworkStage.INSPECTION.value:
        raise ItemReworkError(
            f"Disposition requires inspection stage (current: {case.stage})"
        )
    key = (outcome or "").strip().lower()
    to_status = DISPOSITION_STATUSES.get(key)
    if to_status is None:
        raise ItemReworkError(
            "Disposition must be repairable, reusable, or scrapped"
        )
    _advance_unit_status(session, case, to_status, actor=actor)
    if key == ReworkDisposition.REUSABLE.value:
        _advance_unit_status(
            session, case, ItemStatus.AVAILABLE.value, actor=actor
        )
    case.disposition = key
    case.stage = key
    case.updated_at = _now()
    if notes:
        case.notes = notes
    session.add(case)
    _record(
        session,
        case,
        IssuanceEventType.DISPOSITIONED.value,
        actor=actor,
        notes=notes or key,
    )
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, case.project_id)
    session.commit()
    session.refresh(case)
    return case


def repair_complete(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    case = _require_open_case(session, rework_id)
    if case.stage != ReworkStage.REPAIRABLE.value:
        raise ItemReworkError(
            f"Repair complete requires repairable stage (current: {case.stage})"
        )
    if _instance_status(session, case) != ItemStatus.REPAIRABLE.value:
        raise ItemReworkError("Current serial is not REPAIRABLE")
    case.repaired_at = _now()
    case.repaired_by_id = int(actor.id) if actor.id else None
    case.updated_at = _now()
    if notes:
        case.notes = notes
    session.add(case)
    session.commit()
    session.refresh(case)
    return case


def reissue_item(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    signature_type: Optional[str],
    signature_payload: Optional[str] = None,
    replacement_instance_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    case = _require_open_case(session, rework_id)
    if case.assigned_developer_id is None:
        raise ItemReworkError("Rework case has no assigned developer")

    replacement_id = (
        int(replacement_instance_id) if replacement_instance_id else None
    )
    current_status = _instance_status(session, case)

    if replacement_id is not None:
        if replacement_id == case.current_instance_id:
            raise ItemReworkError(
                "Replacement serial must be different from the defective unit"
            )
        if current_status == ItemStatus.SCRAPPED.value and not replacement_id:
            raise ItemReworkError("Scrap disposition cannot re-issue that serial")
        instance_id = replacement_id
        inventory_id = case.inventory_id
        replacement = session.get(InventoryInstance, instance_id)
        if replacement is None:
            raise ItemReworkError("Replacement instance not found")
        inventory_id = int(replacement.inventory_id)
    else:
        if current_status == ItemStatus.SCRAPPED.value:
            raise ItemReworkError("Scrap disposition cannot re-issue that serial")
        if case.stage != ReworkStage.REPAIRABLE.value:
            raise ItemReworkError(
                "Same-serial re-issue requires a repairable disposition"
            )
        if case.repaired_at is None:
            raise ItemReworkError("Mark the unit repaired before re-issuing")
        if current_status != ItemStatus.REPAIRABLE.value:
            raise ItemReworkError("Current serial is not REPAIRABLE")
        if case.current_instance_id is None:
            raise ItemReworkError("Rework case has no current serial")
        instance_id = int(case.current_instance_id)
        inventory_id = int(case.inventory_id)

    inventory = session.get(Inventory, inventory_id)
    if inventory is None:
        raise ItemReworkError("Inventory not found")

    try:
        issuance = issue_inventory_unit(
            session,
            inventory,
            issued_to_user_id=int(case.assigned_developer_id),
            issued_by_user_id=int(actor.id),
            instance_id=instance_id,
            target_entity_type=case.target_entity_type,
            target_entity_id=case.target_entity_id,
            notes=notes,
            signature_type=signature_type,
            signature_payload=signature_payload,
            rework=True,
            rework_project_id=case.project_id,
            rework_flight_id=case.flight_id,
            rework_sdls_id=case.sdls_id,
        )
    except HTTPException as exc:
        detail = exc.detail
        raise ItemReworkError(
            detail if isinstance(detail, str) else str(detail)
        ) from exc

    record_issuance_event(
        session,
        issuance,
        event_type=IssuanceEventType.REISSUED.value,
        actor=actor,
        notes=notes or "Rework re-issue",
    )
    now = _now()
    case.current_issuance_id = issuance.id
    case.current_instance_id = issuance.inventory_instance_id
    case.inventory_id = int(issuance.inventory_id)
    case.stage = ReworkStage.REISSUED.value
    case.updated_at = now
    session.add(case)
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, case.project_id)
    session.commit()
    session.refresh(case)
    return case


def list_rework_cases(
    session: Session,
    *,
    stage: Optional[str] = None,
    status_filter: Optional[str] = None,
) -> list[InventoryReworkCase]:
    stmt = select(InventoryReworkCase)
    if status_filter:
        stmt = stmt.where(InventoryReworkCase.status == status_filter.strip().lower())
    else:
        stmt = stmt.where(
            InventoryReworkCase.status == ReworkCaseStatus.OPEN.value
        )
    if stage:
        stmt = stmt.where(InventoryReworkCase.stage == stage.strip().lower())
    stmt = stmt.order_by(col(InventoryReworkCase.updated_at).desc())
    return list(session.exec(stmt).all())


def rework_case_to_dict(
    session: Session, case: InventoryReworkCase
) -> dict[str, Any]:
    project = session.get(Project, case.project_id)
    developer = (
        session.get(User, case.assigned_developer_id)
        if case.assigned_developer_id
        else None
    )
    inventory = session.get(Inventory, case.inventory_id)
    instance = (
        session.get(InventoryInstance, case.current_instance_id)
        if case.current_instance_id
        else None
    )
    entity_name = None
    try:
        entity = _load_entity(
            session, case.target_entity_type, case.target_entity_id
        )
        entity_name = getattr(entity, "name", None)
    except Exception:
        entity_name = None
    item_status = _instance_status(session, case)
    return {
        "id": case.id,
        "project_id": case.project_id,
        "project_name": project.name if project else None,
        "flight_id": case.flight_id,
        "sdls_id": case.sdls_id,
        "target_entity_type": case.target_entity_type,
        "target_entity_id": case.target_entity_id,
        "target_entity_name": entity_name,
        "inventory_id": case.inventory_id,
        "inventory_name": inventory.name if inventory else None,
        "part_number": (
            (instance.configuration_item if instance else None)
            or (inventory.part_number if inventory else None)
        ),
        "serial_number": instance.serial_number if instance else None,
        "original_instance_id": case.original_instance_id,
        "current_instance_id": case.current_instance_id,
        "current_issuance_id": case.current_issuance_id,
        "assigned_developer_id": case.assigned_developer_id,
        "assigned_developer_name": (
            (developer.full_name or developer.username) if developer else None
        ),
        "status": case.status,
        "stage": case.stage,
        "attempt_count": case.attempt_count,
        "cycle_warning": cycle_warning(case.attempt_count),
        "disposition": case.disposition,
        "repaired_at": case.repaired_at,
        "item_status": item_status,
        "opened_at": case.opened_at,
        "closed_at": case.closed_at,
        "notes": case.notes,
        "updated_at": case.updated_at,
    }


def rework_events(
    session: Session, case: InventoryReworkCase
) -> list[InventoryIssuanceEvent]:
    issuances = session.exec(
        select(InventoryIssuance)
        .where(
            InventoryIssuance.target_entity_type == case.target_entity_type,
            InventoryIssuance.target_entity_id == case.target_entity_id,
            InventoryIssuance.project_id == case.project_id,
        )
        .order_by(col(InventoryIssuance.issued_at).asc())
    ).all()
    ids = [int(row.id) for row in issuances if row.id]
    if not ids:
        return []
    return list(
        session.exec(
            select(InventoryIssuanceEvent)
            .where(InventoryIssuanceEvent.issuance_id.in_(ids))
            .order_by(
                col(InventoryIssuanceEvent.created_at).asc(),
                col(InventoryIssuanceEvent.id).asc(),
            )
        ).all()
    )
