"""Spec 08 — Developer install/test/complete and HM verify."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, col, select

from app.domain.status_transitions import assert_transition
from app.domain.workflow_roles import WorkflowRole, has_workflow_role
from app.domain.workflow_status import ItemStatus
from app.models.base import IssuanceEventType, ItemTestResult
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryIssuance,
    Project,
    User,
)
from app.services.hierarchy_developer_service import (
    PHYSICAL_ISSUE_STATUSES,
    _load_entity,
)
from app.services.inventory_issuance_service import record_issuance_event
from app.services.inventory_reservation_service import (
    get_item_status_id,
    item_status_name,
)
from app.services.project_workflow_service import (
    ProjectWorkflowError,
    assert_project_not_cancelled,
    user_can_view_project,
)
from app.domain.workflow_audit import WorkflowAuditAction
from app.services.workflow_audit_service import write_workflow_audit

INSTALLABLE_STATUSES = frozenset(
    {
        ItemStatus.ISSUED.value,
        ItemStatus.INSTALLATION_IN_PROGRESS.value,
    }
)


class ItemInstallVerifyError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role_names(user: User) -> list[str]:
    return [r.name for r in (user.roles or []) if r.name]


def _actor_role(user: User) -> str | None:
    names = _role_names(user)
    if has_workflow_role(names, WorkflowRole.ADMIN):
        return WorkflowRole.ADMIN.value
    if has_workflow_role(names, WorkflowRole.HM):
        return WorkflowRole.HM.value
    if has_workflow_role(names, WorkflowRole.DEV):
        return WorkflowRole.DEV.value
    if has_workflow_role(names, WorkflowRole.IM):
        return WorkflowRole.IM.value
    return names[0] if names else None


def _normalize_test_result(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw in ("pass", "passed", ItemTestResult.PASS.value):
        return ItemTestResult.PASS.value
    if raw in ("fail", "failed", ItemTestResult.FAIL.value):
        return ItemTestResult.FAIL.value
    raise ItemInstallVerifyError("Test result must be pass or fail")


def open_issuance_for_entity(
    session: Session, entity_type: str, entity_id: int
) -> Optional[InventoryIssuance]:
    et = (entity_type or "").strip().lower()
    return session.exec(
        select(InventoryIssuance)
        .where(
            InventoryIssuance.target_entity_type == et,
            InventoryIssuance.target_entity_id == int(entity_id),
            InventoryIssuance.status.in_(PHYSICAL_ISSUE_STATUSES),
        )
        .order_by(col(InventoryIssuance.issued_at).desc())
    ).first()


def current_item_status(session: Session, issuance: InventoryIssuance) -> str:
    instance = None
    if issuance.inventory_instance_id:
        instance = session.get(InventoryInstance, issuance.inventory_instance_id)
    if instance is not None:
        name = item_status_name(session, instance.status_id)
        if name:
            return name
    inventory = session.get(Inventory, issuance.inventory_id)
    if inventory is not None:
        name = item_status_name(session, inventory.status_id)
        if name:
            return name
    return (issuance.item_lifecycle_status or ItemStatus.ISSUED.value).strip().upper()


def _advance_item_status(
    session: Session,
    issuance: InventoryIssuance,
    to_status: str,
    *,
    actor: User,
) -> None:
    current = current_item_status(session, issuance)
    if current == to_status:
        issuance.item_lifecycle_status = to_status
        session.add(issuance)
        return
    try:
        assert_transition("item", current, to_status, actor_role=_actor_role(actor))
    except ValueError as exc:
        raise ItemInstallVerifyError(str(exc)) from exc
    status_id = get_item_status_id(session, to_status)
    now = _now()
    if issuance.inventory_instance_id:
        instance = session.get(InventoryInstance, issuance.inventory_instance_id)
        if instance is not None:
            instance.status_id = status_id
            instance.updated_at = now
            session.add(instance)
    inventory = session.get(Inventory, issuance.inventory_id)
    if inventory is not None:
        inventory.status_id = status_id
        inventory.updated_at = now
        session.add(inventory)
    issuance.item_lifecycle_status = to_status
    session.add(issuance)


def _require_assigned_developer(entity: Any, actor: User) -> None:
    assigned_id = getattr(entity, "assigned_developer_id", None)
    if assigned_id is None or int(assigned_id) != int(actor.id):
        raise ItemInstallVerifyError(
            "Only the assigned developer can mark install/test for this item"
        )


def _require_active_project(session: Session, issuance: InventoryIssuance) -> None:
    if not issuance.project_id:
        return
    project = session.get(Project, int(issuance.project_id))
    try:
        assert_project_not_cancelled(project, action="install / test")
    except ProjectWorkflowError as exc:
        raise ItemInstallVerifyError(str(exc)) from exc


def _require_open_issuance(
    session: Session, entity_type: str, entity_id: int
) -> tuple[Any, InventoryIssuance]:
    entity = _load_entity(session, entity_type, entity_id)
    issuance = open_issuance_for_entity(session, entity_type, entity_id)
    if issuance is None:
        raise ItemInstallVerifyError(
            "Item has not been issued to the developer yet"
        )
    return entity, issuance


def install_progress_payload(
    session: Session,
    entity_type: str,
    entity_id: int,
    *,
    issuance: Optional[InventoryIssuance] = None,
) -> dict[str, Any]:
    row = issuance or open_issuance_for_entity(session, entity_type, entity_id)
    from app.services.item_rework_service import rework_progress_fields

    rework = rework_progress_fields(session, entity_type, entity_id)
    if row is None:
        return {
            "issuance_id": None,
            "item_status": None,
            "test_result": None,
            "complete_reported": False,
            "complete_reported_at": None,
            "defect_pending": bool(rework.get("rework_id")),
            "verified": False,
            "verified_at": None,
            "installed_at": None,
            "can_install": False,
            "can_test": False,
            "can_report_complete": False,
            **rework,
        }
    status = current_item_status(session, row)
    test_result = (row.test_result or "").strip().lower() or None
    complete_reported = row.complete_reported_at is not None
    defect_pending = bool(row.defect_pending)
    verified = row.verified_at is not None
    started = row.installed_at is not None
    return {
        "issuance_id": row.id,
        "item_status": status,
        "test_result": test_result,
        "complete_reported": complete_reported,
        "complete_reported_at": row.complete_reported_at,
        "defect_pending": defect_pending,
        "verified": verified,
        "verified_at": row.verified_at,
        "installed_at": row.installed_at,
        "can_install": (
            status in INSTALLABLE_STATUSES
            and not started
            and not verified
            and not defect_pending
        ),
        "can_test": (
            started
            and status == ItemStatus.INSTALLATION_IN_PROGRESS.value
            and test_result is None
            and not verified
        ),
        "can_report_complete": (
            test_result == ItemTestResult.PASS.value
            and not complete_reported
            and not defect_pending
            and not verified
        ),
        **rework,
    }


def issuance_state_dict(
    session: Session,
    issuance: InventoryIssuance,
    *,
    entity: Any = None,
) -> dict[str, Any]:
    et = (issuance.target_entity_type or "").strip().lower()
    eid = int(issuance.target_entity_id or 0)
    flags = install_progress_payload(session, et, eid, issuance=issuance)
    project_id = issuance.project_id
    project_name = None
    if project_id:
        project = session.get(Project, int(project_id))
        project_name = project.name if project else None
    developer = session.get(User, issuance.issued_to_user_id)
    entity_name = getattr(entity, "name", None) if entity is not None else None
    if entity_name is None and et and eid:
        try:
            loaded = entity or _load_entity(session, et, eid)
            entity_name = getattr(loaded, "name", None)
        except Exception:
            entity_name = None
    return {
        "issuance_id": issuance.id,
        "entity_type": et,
        "entity_id": eid,
        "entity_name": entity_name,
        "project_id": project_id,
        "project_name": project_name,
        "serial_number": issuance.serial_number,
        "part_number": issuance.part_number,
        "assigned_developer_id": issuance.issued_to_user_id,
        "assigned_developer_name": (
            (developer.full_name or developer.username) if developer else None
        ),
        **flags,
    }


def start_install(
    session: Session,
    entity_type: str,
    entity_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryIssuance:
    entity, issuance = _require_open_issuance(session, entity_type, entity_id)
    _require_assigned_developer(entity, actor)
    _require_active_project(session, issuance)
    status = current_item_status(session, issuance)
    if issuance.verified_at is not None:
        raise ItemInstallVerifyError("Item is already verified")
    if issuance.defect_pending:
        raise ItemInstallVerifyError("Item has a pending defect and cannot be installed")
    if status not in INSTALLABLE_STATUSES:
        raise ItemInstallVerifyError(
            f"Install can start from ISSUED or INSTALLATION_IN_PROGRESS (current: {status})"
        )
    if status == ItemStatus.ISSUED.value:
        _advance_item_status(
            session, issuance, ItemStatus.INSTALLATION_IN_PROGRESS.value, actor=actor
        )
    if issuance.installed_at is None:
        now = _now()
        issuance.installed_at = now
        issuance.installed_by_id = int(actor.id)
        issuance.installed_entity_type = (entity_type or "").strip().lower()
        issuance.installed_entity_id = int(entity_id)
        session.add(issuance)
        record_issuance_event(
            session,
            issuance,
            event_type=IssuanceEventType.INSTALL_STARTED.value,
            actor=actor,
            notes=notes,
        )
    from app.services.item_rework_service import mark_rework_retesting

    mark_rework_retesting(session, entity_type, entity_id)
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, getattr(issuance, "project_id", None))
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.INSTALLATION_IN_PROGRESS,
        entity_type="inventory_issuance",
        entity_id=int(issuance.id),
        actor=actor,
        project_id=issuance.project_id,
        new_value={"status": ItemStatus.INSTALLATION_IN_PROGRESS.value},
        remarks=notes,
    )
    session.commit()
    session.refresh(issuance)
    return issuance


def submit_test(
    session: Session,
    entity_type: str,
    entity_id: int,
    *,
    result: str,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryIssuance:
    entity, issuance = _require_open_issuance(session, entity_type, entity_id)
    _require_assigned_developer(entity, actor)
    _require_active_project(session, issuance)
    if issuance.installed_at is None:
        raise ItemInstallVerifyError("Start install before recording a test result")
    if issuance.verified_at is not None:
        raise ItemInstallVerifyError("Item is already verified")
    if issuance.test_result:
        raise ItemInstallVerifyError("Test result has already been recorded")
    outcome = _normalize_test_result(result)
    status = current_item_status(session, issuance)
    if status != ItemStatus.INSTALLATION_IN_PROGRESS.value:
        raise ItemInstallVerifyError(
            f"Test can be recorded while INSTALLATION_IN_PROGRESS (current: {status})"
        )
    _advance_item_status(
        session, issuance, ItemStatus.UNDER_TESTING_REVIEW.value, actor=actor
    )
    now = _now()
    issuance.test_result = outcome
    issuance.test_recorded_at = now
    issuance.test_recorded_by_id = int(actor.id)
    if outcome == ItemTestResult.FAIL.value:
        issuance.defect_pending = True
    session.add(issuance)
    record_issuance_event(
        session,
        issuance,
        event_type=(
            IssuanceEventType.TEST_FAILED.value
            if outcome == ItemTestResult.FAIL.value
            else IssuanceEventType.TEST_PASSED.value
        ),
        actor=actor,
        notes=notes,
    )
    if outcome == ItemTestResult.FAIL.value:
        record_issuance_event(
            session,
            issuance,
            event_type=IssuanceEventType.DEFECT_PENDING.value,
            actor=actor,
            notes=notes or "Fail path handoff for Spec 10",
        )
        from app.services.item_rework_service import ensure_open_rework_case

        ensure_open_rework_case(session, issuance, actor=actor, notes=notes)
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, getattr(issuance, "project_id", None))
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.UNDER_TESTING,
        entity_type="inventory_issuance",
        entity_id=int(issuance.id),
        actor=actor,
        project_id=issuance.project_id,
        old_value={"status": ItemStatus.INSTALLATION_IN_PROGRESS.value},
        new_value={
            "status": ItemStatus.UNDER_TESTING_REVIEW.value,
            "test_result": outcome,
        },
        remarks=notes,
    )
    session.commit()
    session.refresh(issuance)
    return issuance


def report_complete(
    session: Session,
    entity_type: str,
    entity_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryIssuance:
    entity, issuance = _require_open_issuance(session, entity_type, entity_id)
    _require_assigned_developer(entity, actor)
    _require_active_project(session, issuance)
    if (issuance.test_result or "").strip().lower() != ItemTestResult.PASS.value:
        raise ItemInstallVerifyError(
            "Installation complete can be reported only after a Pass test result"
        )
    if issuance.defect_pending:
        raise ItemInstallVerifyError("Item has a pending defect and cannot be reported complete")
    if issuance.complete_reported_at is not None:
        raise ItemInstallVerifyError("Installation complete has already been reported")
    if issuance.verified_at is not None:
        raise ItemInstallVerifyError("Item is already verified")
    status = current_item_status(session, issuance)
    if status != ItemStatus.UNDER_TESTING_REVIEW.value:
        raise ItemInstallVerifyError(
            f"Complete can be reported while UNDER_TESTING_REVIEW (current: {status})"
        )
    issuance.complete_reported_at = _now()
    issuance.complete_reported_by_id = int(actor.id)
    session.add(issuance)
    record_issuance_event(
        session,
        issuance,
        event_type=IssuanceEventType.COMPLETE_REPORTED.value,
        actor=actor,
        notes=notes,
    )
    session.commit()
    session.refresh(issuance)
    return issuance


def verify_issuance(
    session: Session,
    issuance_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryIssuance:
    issuance = session.get(InventoryIssuance, issuance_id)
    if issuance is None:
        raise ItemInstallVerifyError("Issuance not found")
    project = session.get(Project, issuance.project_id) if issuance.project_id else None
    if project is not None and not user_can_view_project(actor, project):
        raise ItemInstallVerifyError("You cannot verify items for this project")
    try:
        assert_project_not_cancelled(project, action="verification")
    except ProjectWorkflowError as exc:
        raise ItemInstallVerifyError(str(exc)) from exc
    if (issuance.test_result or "").strip().lower() != ItemTestResult.PASS.value:
        raise ItemInstallVerifyError("HM cannot verify without a Pass test result")
    if issuance.complete_reported_at is None:
        raise ItemInstallVerifyError("HM cannot verify until the developer reports complete")
    if issuance.defect_pending:
        raise ItemInstallVerifyError("Item has a pending defect and cannot be verified")
    if issuance.verified_at is not None:
        raise ItemInstallVerifyError("Item is already verified")
    _advance_item_status(
        session, issuance, ItemStatus.INSTALLED_VERIFIED.value, actor=actor
    )
    issuance.verified_at = _now()
    issuance.verified_by_id = int(actor.id)
    session.add(issuance)
    record_issuance_event(
        session,
        issuance,
        event_type=IssuanceEventType.VERIFIED.value,
        actor=actor,
        notes=notes,
    )
    from app.services.item_rework_service import close_rework_for_issuance

    close_rework_for_issuance(session, issuance, actor=actor, notes=notes)
    from app.services.project_progress_service import touch_project_progress

    touch_project_progress(session, issuance.project_id)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.INSTALLED_VERIFIED,
        entity_type="inventory_issuance",
        entity_id=int(issuance.id),
        actor=actor,
        project_id=issuance.project_id,
        old_value={"status": ItemStatus.UNDER_TESTING_REVIEW.value},
        new_value={"status": ItemStatus.INSTALLED_VERIFIED.value},
        remarks=notes,
    )
    session.commit()
    session.refresh(issuance)
    return issuance


def list_verification_queue(session: Session, actor: User) -> list[dict[str, Any]]:
    rows = session.exec(
        select(InventoryIssuance).where(
            InventoryIssuance.test_result == ItemTestResult.PASS.value,
            InventoryIssuance.complete_reported_at.is_not(None),
            InventoryIssuance.verified_at.is_(None),
            InventoryIssuance.defect_pending.is_(False),
        )
    ).all()
    out: list[dict[str, Any]] = []
    for issuance in rows:
        project = session.get(Project, issuance.project_id) if issuance.project_id else None
        if project is not None and not user_can_view_project(actor, project):
            continue
        out.append(issuance_state_dict(session, issuance))
    out.sort(
        key=lambda row: (
            str(row.get("project_name") or ""),
            str(row.get("entity_name") or ""),
        )
    )
    return out
