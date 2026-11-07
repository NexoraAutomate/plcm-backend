"""Developer assignment workflow activity for a single hierarchy item.

Builds a chronological timeline of Spec 07/08 loop steps only:
assign → request → (mark-back) → issue → install → test → complete →
HM verify/reject → rework/re-issue when the loop repeats.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, col, or_, select

from app.domain.workflow_audit import WorkflowAuditAction
from app.models.base import IssuanceEventType, ItemRequestStatus
from app.models.helpers import _ENTITY_MODEL_MAP
from app.models.tables import (
    InventoryIssuance,
    InventoryIssuanceEvent,
    InventoryItemRequest,
    InventoryReservation,
    User,
    WorkflowAuditEvent,
)
from app.services.hierarchy_developer_service import HierarchyDeveloperError
from app.services.item_install_verify_service import install_progress_payload
from app.services.workflow_audit_service import event_to_dict


ASSIGNABLE = frozenset({"system", "subsystem", "module", "unit", "component"})

# Issuance ledger → assignment-workflow step codes
_ISSUANCE_STEP: dict[str, dict[str, str]] = {
    IssuanceEventType.ISSUED.value: {
        "step": "issued",
        "title": "Issued by Inventory Manager",
        "status": "ISSUED",
    },
    IssuanceEventType.REISSUED.value: {
        "step": "reissued",
        "title": "Re-issued by Inventory Manager",
        "status": "ISSUED",
    },
    IssuanceEventType.INSTALL_STARTED.value: {
        "step": "install_started",
        "title": "Installation started",
        "status": "INSTALLATION_IN_PROGRESS",
    },
    IssuanceEventType.TEST_PASSED.value: {
        "step": "test_passed",
        "title": "Test passed",
        "status": "UNDER_TESTING_REVIEW",
    },
    IssuanceEventType.TEST_FAILED.value: {
        "step": "test_failed",
        "title": "Test failed",
        "status": "UNDER_TESTING_REVIEW",
    },
    IssuanceEventType.COMPLETE_REPORTED.value: {
        "step": "complete_reported",
        "title": "Waiting for HM approval",
        "status": "UNDER_TESTING_REVIEW",
    },
    IssuanceEventType.VERIFICATION_REJECTED.value: {
        "step": "hm_rejected",
        "title": "Rejected by Hierarchy Manager",
        "status": "INSTALLATION_REJECTED",
    },
    IssuanceEventType.VERIFIED.value: {
        "step": "hm_verified",
        "title": "Approved by Hierarchy Manager",
        "status": "INSTALLED_VERIFIED",
    },
    IssuanceEventType.DEFECT_PENDING.value: {
        "step": "defect_pending",
        "title": "Defect pending inspection",
        "status": "DEFECT_PENDING",
    },
    IssuanceEventType.REWORK_OPENED.value: {
        "step": "rework_opened",
        "title": "Rework opened",
        "status": "REWORK",
    },
    IssuanceEventType.ITEM_REMOVED.value: {
        "step": "item_removed",
        "title": "Item removed for rework",
        "status": "REWORK",
    },
    IssuanceEventType.ITEM_RETURNED.value: {
        "step": "item_returned",
        "title": "Returned to Inventory Manager",
        "status": "RETURNED",
    },
    IssuanceEventType.INSPECTION_STARTED.value: {
        "step": "inspection_started",
        "title": "IM inspection started",
        "status": "UNDER_INSPECTION",
    },
    IssuanceEventType.DISPOSITIONED.value: {
        "step": "dispositioned",
        "title": "Disposition decided",
        "status": "DISPOSITIONED",
    },
    IssuanceEventType.REWORK_CLOSED.value: {
        "step": "rework_closed",
        "title": "Rework closed",
        "status": "REWORK_CLOSED",
    },
}


def _user_name(session: Session, user_id: Optional[int]) -> Optional[str]:
    if user_id is None:
        return None
    user = session.get(User, int(user_id))
    if not user:
        return None
    return user.full_name or user.username


def _load_entity(session: Session, entity_type: str, entity_id: int) -> Any:
    key = (entity_type or "").strip().lower()
    if key not in ASSIGNABLE:
        raise HierarchyDeveloperError(f"Unsupported entity type: {entity_type}")
    entry = _ENTITY_MODEL_MAP.get(key)
    if not entry:
        raise HierarchyDeveloperError(f"Unsupported entity type: {entity_type}")
    model, _pk, _label = entry
    entity = session.get(model, int(entity_id))
    if not entity:
        raise HierarchyDeveloperError(f"{entity_type} {entity_id} not found")
    return entity


def _step(
    *,
    id: str,
    step: str,
    title: str,
    occurred_at: Optional[datetime],
    actor_user_id: Optional[int] = None,
    actor_name: Optional[str] = None,
    actor_role: Optional[str] = None,
    target_user_id: Optional[int] = None,
    target_name: Optional[str] = None,
    status: Optional[str] = None,
    remarks: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "step": step,
        "title": title,
        "occurred_at": occurred_at,
        "actor_user_id": actor_user_id,
        "actor_name": actor_name,
        "actor_role": actor_role,
        "target_user_id": target_user_id,
        "target_name": target_name,
        "status": status,
        "remarks": remarks,
    }


def list_assignment_activity(
    session: Session, entity_type: str, entity_id: int
) -> dict[str, Any]:
    """Return assignment-workflow steps for one hierarchy item only."""
    et = (entity_type or "").strip().lower()
    eid = int(entity_id)
    entity = _load_entity(session, et, eid)
    progress = install_progress_payload(session, et, eid)

    assigned_developer_id = getattr(entity, "assigned_developer_id", None)
    assigned_developer_name = _user_name(session, assigned_developer_id)

    steps: list[dict[str, Any]] = []

    # 1) HM developer assignment from workflow audit (entity-scoped only)
    assign_audits = session.exec(
        select(WorkflowAuditEvent)
        .where(
            WorkflowAuditEvent.entity_type == et,
            WorkflowAuditEvent.entity_id == str(eid),
            col(WorkflowAuditEvent.action).in_(
                [
                    WorkflowAuditAction.ASSIGNED,
                    WorkflowAuditAction.UNASSIGNED,
                ]
            ),
        )
        .order_by(WorkflowAuditEvent.occurred_at, WorkflowAuditEvent.id)
    ).all()
    for audit in assign_audits:
        payload = event_to_dict(audit)
        new_value = payload.get("new_value") or {}
        old_value = payload.get("old_value") or {}
        if audit.action == WorkflowAuditAction.ASSIGNED:
            target_id = new_value.get("assigned_developer_id")
            target_name = new_value.get("assigned_developer_name") or _user_name(
                session, int(target_id) if target_id is not None else None
            )
            steps.append(
                _step(
                    id=f"audit-{audit.id}",
                    step="assigned",
                    title="Assigned by Hierarchy Manager",
                    occurred_at=audit.occurred_at,
                    actor_user_id=audit.actor_user_id,
                    actor_name=payload.get("actor_username"),
                    actor_role="HM",
                    target_user_id=int(target_id) if target_id is not None else None,
                    target_name=target_name,
                    status="ASSIGNED",
                    remarks=payload.get("remarks"),
                )
            )
        else:
            steps.append(
                _step(
                    id=f"audit-{audit.id}",
                    step="unassigned",
                    title="Assignment cleared",
                    occurred_at=audit.occurred_at,
                    actor_user_id=audit.actor_user_id,
                    actor_name=payload.get("actor_username"),
                    actor_role=payload.get("actor_role"),
                    target_user_id=old_value.get("assigned_developer_id"),
                    target_name=_user_name(
                        session,
                        int(old_value["assigned_developer_id"])
                        if old_value.get("assigned_developer_id") is not None
                        else None,
                    ),
                    status="UNASSIGNED",
                    remarks=payload.get("remarks"),
                )
            )

    if assigned_developer_id and not any(s["step"] == "assigned" for s in steps):
        steps.append(
            _step(
                id=f"synthetic-assigned-{et}-{eid}",
                step="assigned",
                title="Assigned by Hierarchy Manager",
                occurred_at=getattr(entity, "updated_at", None)
                or getattr(entity, "created_at", None),
                actor_role="HM",
                target_user_id=int(assigned_developer_id),
                target_name=assigned_developer_name,
                status="ASSIGNED",
                remarks="Current developer assignment",
            )
        )

    # 2) Reservation (context for handover)
    reservations = session.exec(
        select(InventoryReservation)
        .where(
            InventoryReservation.target_entity_type == et,
            InventoryReservation.target_entity_id == eid,
        )
        .order_by(InventoryReservation.reserved_at, InventoryReservation.id)
    ).all()
    for reservation in reservations:
        steps.append(
            _step(
                id=f"reservation-{reservation.id}",
                step="reserved",
                title="Inventory reserved",
                occurred_at=reservation.reserved_at,
                actor_user_id=reservation.reserved_by_user_id,
                actor_name=_user_name(session, reservation.reserved_by_user_id),
                actor_role="IM",
                target_user_id=int(assigned_developer_id)
                if assigned_developer_id
                else None,
                target_name=assigned_developer_name,
                status="RESERVED",
                remarks=reservation.notes,
            )
        )

    # 3) Developer request / mark-back / issued request rows
    requests = session.exec(
        select(InventoryItemRequest)
        .where(
            InventoryItemRequest.target_entity_type == et,
            InventoryItemRequest.target_entity_id == eid,
        )
        .order_by(InventoryItemRequest.requested_at, InventoryItemRequest.id)
    ).all()
    for req in requests:
        requester = _user_name(session, req.requested_by_user_id)
        assignee = _user_name(session, req.assigned_developer_id)
        steps.append(
            _step(
                id=f"request-{req.id}",
                step="handover_requested",
                title="Handover requested from Inventory Manager",
                occurred_at=req.requested_at,
                actor_user_id=req.requested_by_user_id,
                actor_name=requester,
                actor_role="DEV",
                target_user_id=req.assigned_developer_id,
                target_name=assignee,
                status="REQUESTED",
                remarks=req.notes,
            )
        )
        if req.status == ItemRequestStatus.MARKED_BACK.value or req.marked_back_at:
            steps.append(
                _step(
                    id=f"request-{req.id}-markback",
                    step="marked_back",
                    title="Marked back by Inventory Manager",
                    occurred_at=req.marked_back_at or req.updated_at,
                    actor_user_id=req.marked_back_by_user_id,
                    actor_name=_user_name(session, req.marked_back_by_user_id),
                    actor_role="IM",
                    target_user_id=req.assigned_developer_id,
                    target_name=assignee,
                    status="MARKED_BACK",
                    remarks=req.mark_back_reason,
                )
            )
        if req.status == ItemRequestStatus.CANCELLED.value:
            steps.append(
                _step(
                    id=f"request-{req.id}-cancelled",
                    step="request_cancelled",
                    title="Handover request cancelled",
                    occurred_at=req.updated_at,
                    actor_role="SYSTEM",
                    target_user_id=req.assigned_developer_id,
                    target_name=assignee,
                    status="CANCELLED",
                )
            )

    # 4) Issuance ledger events for this entity (install/test/verify/rework loop)
    issuances = session.exec(
        select(InventoryIssuance)
        .where(
            or_(
                (
                    InventoryIssuance.target_entity_type == et
                )
                & (InventoryIssuance.target_entity_id == eid),
                (
                    InventoryIssuance.installed_entity_type == et
                )
                & (InventoryIssuance.installed_entity_id == eid),
            )
        )
        .order_by(InventoryIssuance.issued_at, InventoryIssuance.id)
    ).all()
    for issuance in issuances:
        issued_to_name = _user_name(session, issuance.issued_to_user_id)
        event_rows = session.exec(
            select(InventoryIssuanceEvent)
            .where(InventoryIssuanceEvent.issuance_id == issuance.id)
            .order_by(InventoryIssuanceEvent.created_at, InventoryIssuanceEvent.id)
        ).all()
        for row in event_rows:
            meta = _ISSUANCE_STEP.get(row.event_type)
            if meta is None:
                continue
            actor_id = row.actor_user_id or row.installer_user_id
            actor_role = "IM" if meta["step"] in {"issued", "reissued"} else None
            if meta["step"] in {
                "install_started",
                "test_passed",
                "test_failed",
                "complete_reported",
            }:
                actor_role = "DEV"
            if meta["step"] in {"hm_verified", "hm_rejected"}:
                actor_role = "HM"
            if meta["step"] in {
                "defect_pending",
                "inspection_started",
                "dispositioned",
                "item_returned",
            }:
                actor_role = actor_role or "IM"
            steps.append(
                _step(
                    id=f"issuance-event-{row.id}",
                    step=meta["step"],
                    title=meta["title"],
                    occurred_at=row.created_at,
                    actor_user_id=actor_id,
                    actor_name=_user_name(session, actor_id),
                    actor_role=actor_role,
                    target_user_id=issuance.issued_to_user_id,
                    target_name=issued_to_name,
                    status=meta["status"],
                    remarks=row.notes,
                )
            )

    _epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def _sort_at(value: Optional[datetime]) -> datetime:
        if value is None:
            return _epoch
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    steps.sort(key=lambda s: (_sort_at(s["occurred_at"]), s["id"]))

    current_status = progress.get("item_status")
    if progress.get("verified"):
        current_label = "Verified by HM"
    elif progress.get("complete_reported") and not progress.get("verified"):
        current_label = "Waiting for HM approval"
    elif progress.get("installation_rejected"):
        current_label = "Installation rejected — retest"
    elif progress.get("defect_pending"):
        current_label = "Defect pending"
    elif progress.get("can_test") or current_status == "UNDER_TESTING_REVIEW":
        current_label = "Testing in progress"
    elif progress.get("can_install") or current_status == "INSTALLATION_IN_PROGRESS":
        current_label = "Installation in progress"
    elif progress.get("issued") or current_status == "ISSUED":
        current_label = "Issued — awaiting install"
    elif any(s["step"] == "handover_requested" for s in steps) and not any(
        s["step"] == "issued" for s in steps
    ):
        current_label = "Handover requested"
    elif assigned_developer_id:
        current_label = "Assigned"
    else:
        current_label = current_status or "Unknown"

    latest = steps[-1] if steps else None
    return {
        "entity_type": et,
        "entity_id": eid,
        "entity_name": getattr(entity, "name", None),
        "current_status": current_status,
        "current_status_label": current_label,
        "assigned_developer_id": int(assigned_developer_id)
        if assigned_developer_id
        else None,
        "assigned_developer_name": assigned_developer_name,
        "latest_step": latest["step"] if latest else None,
        "steps": steps,
    }
