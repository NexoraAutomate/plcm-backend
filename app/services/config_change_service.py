"""Spec 12 — configuration change after hierarchy / reservation.

CONTROL RULE: existing project configuration is not edited in place after
hierarchy setup / reservation. HM requests a change, returns all inventory
(Spec 11 mechanics), submits a CR with a target available configuration,
Admin approves, then a NEW draft project is created. The source project is
marked SUPERSEDED and linked via successor / predecessor ids.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, col, select

from app.domain.status_transitions import assert_transition
from app.domain.workflow_status import ProjectWorkflowStatus
from app.models.base import (
    CONFIG_CHANGE_RELEASE_REASON,
    ConfigChangeRequestStatus,
)
from app.models.tables import (
    ConfigChangeRequest,
    HierarchyConfiguration,
    Project,
    User,
)
from app.services.inventory_recall_service import (
    InventoryRecallError,
    clear_project_inventory,
    inventory_is_cleared,
    project_cancel_preview,
)
from app.services.project_workflow_service import (
    ProjectWorkflowError,
    _actor_workflow_role,
    _require_available_config,
    create_draft_project,
    get_project_status_id,
    is_structural_frozen,
    project_status_name,
)
from app.domain.workflow_audit import WorkflowAuditAction
from app.services.workflow_audit_service import write_workflow_audit


class ConfigChangeError(ValueError):
    pass


OPEN_CR_STATUSES = frozenset(
    {
        ConfigChangeRequestStatus.REQUESTED.value,
        ConfigChangeRequestStatus.INVENTORY_RETURNED.value,
        ConfigChangeRequestStatus.SUBMITTED.value,
        ConfigChangeRequestStatus.APPROVED.value,
    }
)

SEALED_REQUEST_STATUSES = frozenset(
    {
        ProjectWorkflowStatus.APPROVED.value,
        ProjectWorkflowStatus.HIERARCHY_GENERATED.value,
        ProjectWorkflowStatus.READY_FOR_INVENTORY.value,
    }
)

BLOCKED_REQUEST_STATUSES = frozenset(
    {
        ProjectWorkflowStatus.CANCELLED.value,
        ProjectWorkflowStatus.SUPERSEDED.value,
        ProjectWorkflowStatus.COMPLETED.value,
        ProjectWorkflowStatus.READY_TO_DELIVER.value,
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_open_config_change(
    session: Session, project_id: int
) -> Optional[ConfigChangeRequest]:
    return session.exec(
        select(ConfigChangeRequest).where(
            ConfigChangeRequest.source_project_id == int(project_id),
            col(ConfigChangeRequest.status).in_(list(OPEN_CR_STATUSES)),
        )
    ).first()


def assert_no_open_config_change(
    session: Session, project_id: int, *, action: str = "inventory operations"
) -> None:
    if get_open_config_change(session, project_id) is not None:
        raise ConfigChangeError(f"Open configuration change blocks {action}")


def _require_cr(session: Session, change_id: int) -> ConfigChangeRequest:
    row = session.get(ConfigChangeRequest, change_id)
    if row is None:
        raise ConfigChangeError("Configuration change request not found")
    return row


def _require_source(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise ConfigChangeError("Project not found")
    return project


def _assert_inventory_cleared(session: Session, project_id: int) -> None:
    if not inventory_is_cleared(session, project_id):
        raise ConfigChangeError(
            "Inventory must be fully returned and inspected before this step"
        )


def _advance_if_cleared(session: Session, row: ConfigChangeRequest) -> ConfigChangeRequest:
    if row.status != ConfigChangeRequestStatus.REQUESTED.value:
        return row
    if not inventory_is_cleared(session, int(row.source_project_id)):
        return row
    row.status = ConfigChangeRequestStatus.INVENTORY_RETURNED.value
    row.updated_at = _now()
    session.add(row)
    session.flush()
    return row


def maybe_mark_inventory_returned(
    session: Session, project_id: int
) -> Optional[ConfigChangeRequest]:
    row = get_open_config_change(session, project_id)
    if row is None:
        return None
    before = row.status
    _advance_if_cleared(session, row)
    if row.status != before:
        session.commit()
        session.refresh(row)
    return row


def config_change_to_dict(
    session: Session, row: ConfigChangeRequest
) -> dict[str, Any]:
    source = session.get(Project, row.source_project_id)
    successor = (
        session.get(Project, row.successor_project_id)
        if row.successor_project_id
        else None
    )
    target = (
        session.get(HierarchyConfiguration, row.target_hierarchy_config_id)
        if row.target_hierarchy_config_id
        else None
    )
    preview = None
    cleared = True
    if source is not None and source.id is not None:
        try:
            preview = project_cancel_preview(session, int(source.id))
            cleared = inventory_is_cleared(session, int(source.id))
        except InventoryRecallError:
            preview = None
            cleared = False
    return {
        "id": row.id,
        "source_project_id": row.source_project_id,
        "source_project_name": source.name if source else None,
        "source_project_status": project_status_name(source) if source else None,
        "target_hierarchy_config_id": row.target_hierarchy_config_id,
        "target_hierarchy_config_code": target.code if target else None,
        "target_hierarchy_config_name": target.name if target else None,
        "target_product_type": row.target_product_type,
        "target_flight_count": row.target_flight_count,
        "target_sdls_per_flight": row.target_sdls_per_flight,
        "reason_remarks": row.reason_remarks,
        "status": row.status,
        "successor_project_id": row.successor_project_id,
        "successor_project_name": successor.name if successor else None,
        "requested_by_id": row.requested_by_id,
        "requested_at": row.requested_at,
        "submitted_by_id": row.submitted_by_id,
        "submitted_at": row.submitted_at,
        "approved_by_id": row.approved_by_id,
        "approved_at": row.approved_at,
        "notes": row.notes,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "inventory_cleared": cleared,
        "inventory_preview": preview,
        "structural_frozen": is_structural_frozen(source) if source else False,
    }


def list_config_changes(
    session: Session,
    *,
    source_project_id: Optional[int] = None,
    status_filter: Optional[str] = None,
) -> list[ConfigChangeRequest]:
    stmt = select(ConfigChangeRequest)
    if source_project_id is not None:
        stmt = stmt.where(
            ConfigChangeRequest.source_project_id == int(source_project_id)
        )
    if status_filter:
        stmt = stmt.where(
            ConfigChangeRequest.status == status_filter.strip().upper()
        )
    stmt = stmt.order_by(col(ConfigChangeRequest.updated_at).desc())
    return list(session.exec(stmt).all())


def request_config_change(
    session: Session,
    project_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> ConfigChangeRequest:
    project = _require_source(session, project_id)
    status = project_status_name(project) or ""
    if status == ProjectWorkflowStatus.DRAFT.value:
        raise ConfigChangeError(
            "Draft projects can still change configuration in place; "
            "request a configuration change after approval"
        )
    if status in BLOCKED_REQUEST_STATUSES:
        raise ConfigChangeError(
            f"Cannot request a configuration change from status {status}"
        )
    if status not in SEALED_REQUEST_STATUSES:
        raise ConfigChangeError(
            f"Cannot request a configuration change from status {status}"
        )
    if not is_structural_frozen(project):
        raise ConfigChangeError(
            "Project configuration is not sealed; change it in place instead"
        )
    existing = get_open_config_change(session, project_id)
    if existing is not None:
        return existing

    now = _now()
    row = ConfigChangeRequest(
        source_project_id=int(project.id),
        status=ConfigChangeRequestStatus.REQUESTED.value,
        requested_by_id=int(actor.id) if actor.id else None,
        requested_at=now,
        notes=notes,
        created_at=now,
        updated_at=now,
        target_flight_count=project.flight_count,
        target_sdls_per_flight=project.sdls_per_flight,
        target_product_type=project.product_type,
    )
    session.add(row)
    session.flush()
    _advance_if_cleared(session, row)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.CONFIG_CHANGE_REQUESTED,
        entity_type="config_change",
        entity_id=int(row.id),
        actor=actor,
        project_id=int(project.id),
        new_value={"status": row.status},
        remarks=notes,
    )
    session.commit()
    session.refresh(row)
    return row


def return_config_change_inventory(
    session: Session,
    change_id: int,
    *,
    actor: User,
) -> ConfigChangeRequest:
    row = _require_cr(session, change_id)
    if row.status not in {
        ConfigChangeRequestStatus.REQUESTED.value,
        ConfigChangeRequestStatus.INVENTORY_RETURNED.value,
    }:
        raise ConfigChangeError(
            f"Inventory return is not available in status {row.status}"
        )
    if row.status == ConfigChangeRequestStatus.INVENTORY_RETURNED.value:
        return row

    try:
        clear_project_inventory(
            session,
            int(row.source_project_id),
            actor=actor,
            release_reason=CONFIG_CHANGE_RELEASE_REASON,
            recall_notes="Opened by configuration change",
            recall_event_notes="Configuration change — recall opened",
            rework_close_suffix="Closed because of configuration change (Spec 12).",
            rework_event_notes="Rework closed on configuration change",
            commit=False,
        )
    except InventoryRecallError as exc:
        raise ConfigChangeError(str(exc)) from exc

    _advance_if_cleared(session, row)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.CONFIG_CHANGE_INVENTORY_RETURNED,
        entity_type="config_change",
        entity_id=int(row.id),
        actor=actor,
        project_id=int(row.source_project_id),
        old_value={"status": ConfigChangeRequestStatus.REQUESTED.value},
        new_value={"status": row.status},
    )
    session.commit()
    session.refresh(row)
    return row


def submit_config_change(
    session: Session,
    change_id: int,
    *,
    actor: User,
    target_hierarchy_config_id: int,
    reason_remarks: str,
    product_type: Optional[str] = None,
    flight_count: Optional[int] = None,
    sdls_per_flight: Optional[int] = None,
) -> ConfigChangeRequest:
    row = _require_cr(session, change_id)
    if row.status == ConfigChangeRequestStatus.REQUESTED.value:
        _advance_if_cleared(session, row)
    if row.status != ConfigChangeRequestStatus.INVENTORY_RETURNED.value:
        raise ConfigChangeError(
            "Change request can be submitted only after inventory is returned"
        )
    _assert_inventory_cleared(session, int(row.source_project_id))

    remarks = (reason_remarks or "").strip()
    if not remarks:
        raise ConfigChangeError("reason_remarks is required")

    source = _require_source(session, int(row.source_project_id))
    product = (product_type or row.target_product_type or source.product_type or "").strip()
    if not product:
        raise ConfigChangeError("product_type is required")
    try:
        _require_available_config(session, int(target_hierarchy_config_id), product)
    except ProjectWorkflowError as exc:
        raise ConfigChangeError(str(exc)) from exc

    if int(target_hierarchy_config_id) == int(source.hierarchy_config_id or 0):
        raise ConfigChangeError(
            "Target configuration must differ from the current project configuration"
        )

    flights = flight_count if flight_count is not None else (
        row.target_flight_count or source.flight_count or 1
    )
    sdls = sdls_per_flight if sdls_per_flight is not None else (
        row.target_sdls_per_flight or source.sdls_per_flight or 1
    )
    if int(flights) < 1 or int(sdls) < 1:
        raise ConfigChangeError("flight_count and sdls_per_flight must be >= 1")

    now = _now()
    row.target_hierarchy_config_id = int(target_hierarchy_config_id)
    row.target_product_type = product
    row.target_flight_count = int(flights)
    row.target_sdls_per_flight = int(sdls)
    row.reason_remarks = remarks
    row.status = ConfigChangeRequestStatus.SUBMITTED.value
    row.submitted_by_id = int(actor.id) if actor.id else None
    row.submitted_at = now
    row.updated_at = now
    session.add(row)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.CONFIG_CHANGE_SUBMITTED,
        entity_type="config_change",
        entity_id=int(row.id),
        actor=actor,
        project_id=int(row.source_project_id),
        old_value={"status": ConfigChangeRequestStatus.INVENTORY_RETURNED.value},
        new_value={
            "status": ConfigChangeRequestStatus.SUBMITTED.value,
            "target_hierarchy_config_id": int(target_hierarchy_config_id),
            "target_product_type": product,
        },
        remarks=remarks,
    )
    session.commit()
    session.refresh(row)
    return row


CANCELLABLE_CR_STATUSES = frozenset(
    {
        ConfigChangeRequestStatus.REQUESTED.value,
        ConfigChangeRequestStatus.INVENTORY_RETURNED.value,
        ConfigChangeRequestStatus.SUBMITTED.value,
    }
)


def cancel_config_change(
    session: Session,
    change_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> ConfigChangeRequest:
    """Withdraw an open configuration change so inventory ops can resume.

    Allowed before Admin approval. Does not undo inventory already returned —
    released stock stays Available and can be reserved again.
    """
    row = _require_cr(session, change_id)
    if row.status == ConfigChangeRequestStatus.CANCELLED.value:
        return row
    if row.status not in CANCELLABLE_CR_STATUSES:
        raise ConfigChangeError(
            f"Configuration change cannot be cancelled in status {row.status}"
        )

    old_status = row.status
    now = _now()
    row.status = ConfigChangeRequestStatus.CANCELLED.value
    row.updated_at = now
    if notes is not None:
        remark = (notes or "").strip()
        if remark:
            existing = (row.notes or "").strip()
            row.notes = f"{existing}; {remark}".strip("; ") if existing else remark
    session.add(row)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.CONFIG_CHANGE_CANCELLED,
        entity_type="config_change",
        entity_id=int(row.id),
        actor=actor,
        project_id=int(row.source_project_id),
        old_value={"status": old_status},
        new_value={"status": ConfigChangeRequestStatus.CANCELLED.value},
        remarks=notes,
    )
    session.commit()
    session.refresh(row)
    return row


def approve_config_change(
    session: Session,
    change_id: int,
    *,
    actor: User,
) -> ConfigChangeRequest:
    row = _require_cr(session, change_id)
    if row.status != ConfigChangeRequestStatus.SUBMITTED.value:
        raise ConfigChangeError(
            f"Only submitted change requests can be approved (current: {row.status})"
        )
    _assert_inventory_cleared(session, int(row.source_project_id))
    now = _now()
    row.status = ConfigChangeRequestStatus.APPROVED.value
    row.approved_by_id = int(actor.id) if actor.id else None
    row.approved_at = now
    row.updated_at = now
    session.add(row)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.CONFIG_CHANGE_APPROVED,
        entity_type="config_change",
        entity_id=int(row.id),
        actor=actor,
        project_id=int(row.source_project_id),
        old_value={"status": ConfigChangeRequestStatus.SUBMITTED.value},
        new_value={"status": ConfigChangeRequestStatus.APPROVED.value},
    )
    session.commit()
    session.refresh(row)
    return row


def create_successor_project(
    session: Session,
    change_id: int,
    *,
    actor: User,
    name: Optional[str] = None,
    flight_count: Optional[int] = None,
    sdls_per_flight: Optional[int] = None,
    product_type: Optional[str] = None,
) -> tuple[ConfigChangeRequest, Project]:
    row = _require_cr(session, change_id)
    if row.status != ConfigChangeRequestStatus.APPROVED.value:
        raise ConfigChangeError(
            "Successor project can be created only after Admin approval"
        )
    _assert_inventory_cleared(session, int(row.source_project_id))
    if not row.target_hierarchy_config_id:
        raise ConfigChangeError("Change request is missing a target configuration")

    source = _require_source(session, int(row.source_project_id))
    current = project_status_name(source) or ProjectWorkflowStatus.DRAFT.value
    role = _actor_workflow_role(actor)
    try:
        assert_transition(
            "project",
            current,
            ProjectWorkflowStatus.SUPERSEDED.value,
            actor_role=role,
        )
    except ValueError as exc:
        raise ConfigChangeError(str(exc)) from exc

    product = (product_type or row.target_product_type or source.product_type or "").strip()
    flights = flight_count if flight_count is not None else (
        row.target_flight_count or source.flight_count or 1
    )
    sdls = sdls_per_flight if sdls_per_flight is not None else (
        row.target_sdls_per_flight or source.sdls_per_flight or 1
    )
    draft_name = (name or "").strip() or f"{source.name} (config change)"

    try:
        successor = create_draft_project(
            session,
            {
                "name": draft_name,
                "description": (
                    f"Successor of project {source.id} via configuration change "
                    f"{row.id}."
                ),
                "start_date": source.start_date,
                "end_date": source.end_date,
                "owner_id": source.owner_id,
                "order_id": source.order_id,
                "assigned_hm_id": source.assigned_hm_id or actor.id,
                "hierarchy_config_id": int(row.target_hierarchy_config_id),
                "product_type": product,
                "flight_count": int(flights),
                "sdls_per_flight": int(sdls),
            },
            actor=actor,
            commit=False,
        )
    except ProjectWorkflowError as exc:
        raise ConfigChangeError(str(exc)) from exc

    now = _now()
    successor.predecessor_project_id = int(source.id)
    successor.updated_at = now
    session.add(successor)

    source.successor_project_id = int(successor.id)
    source.status_id = get_project_status_id(
        session, ProjectWorkflowStatus.SUPERSEDED.value
    )
    source.updated_at = now
    session.add(source)

    row.status = ConfigChangeRequestStatus.NEW_PROJECT_CREATED.value
    row.successor_project_id = int(successor.id)
    row.updated_at = now
    session.add(row)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.CONFIG_CHANGE_NEW_PROJECT,
        entity_type="config_change",
        entity_id=int(row.id),
        actor=actor,
        project_id=int(successor.id),
        old_value={
            "source_project_id": int(source.id),
            "source_status": current,
        },
        new_value={
            "successor_project_id": int(successor.id),
            "status": ConfigChangeRequestStatus.NEW_PROJECT_CREATED.value,
        },
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(row)
    session.refresh(successor)
    session.refresh(source)
    return row, successor
