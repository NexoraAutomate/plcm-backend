"""
P4 — Track B faulty inspection / IE disposition spine.

Augments maintenance-linked InventoryReworkCase without changing Spec-10
project rework flows in item_rework_service.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session

from app.domain.workflow_status import ItemStatus
from app.models.base import (
    OemWarrantyClaimStatus,
    ReworkCaseStatus,
    ReworkDisposition,
    ReworkStage,
)
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryReworkCase,
    OemWarrantyClaim,
    User,
)
from app.services import maintenance_field_service as field_svc
from app.services.inventory_reservation_service import get_item_status_id


TRACK_B_TERMINAL = frozenset(
    {
        ReworkStage.RESTOCKED.value,
        ReworkStage.DISCARDED.value,
        ReworkStage.CLAIM_CLOSED.value,
    }
)

# Allowed from → to for MHD Track B (maintenance-linked rework).
TRACK_B_TRANSITIONS: dict[str, frozenset[str]] = {
    ReworkStage.AWAITING_FAULTY_ARRIVAL.value: frozenset(
        {ReworkStage.RECEIVED.value}
    ),
    ReworkStage.RECEIVED.value: frozenset({ReworkStage.IE_ASSIGNED.value}),
    ReworkStage.IE_ASSIGNED.value: frozenset({ReworkStage.ISSUED_TO_IE.value}),
    ReworkStage.ISSUED_TO_IE.value: frozenset(
        {ReworkStage.INSPECTION_UNDER_PROCESS.value}
    ),
    ReworkStage.INSPECTION_UNDER_PROCESS.value: frozenset(
        {
            ReworkStage.REPAIR_UNDER_PROGRESS.value,
            ReworkStage.WARRANTY_CLAIM.value,
            ReworkStage.DISCARD_PENDING.value,
            ReworkStage.RESTOCKED.value,  # IE-013 reusable
        }
    ),
    ReworkStage.REPAIR_UNDER_PROGRESS.value: frozenset(
        {
            ReworkStage.REPAIR_UNDER_PROGRESS.value,  # PD reject / repair submit
            ReworkStage.RESTOCKED.value,
        }
    ),
    ReworkStage.WARRANTY_CLAIM.value: frozenset(
        {ReworkStage.CLAIM_CLOSED.value}
    ),
    ReworkStage.DISCARD_PENDING.value: frozenset(
        {ReworkStage.DISCARDED.value}
    ),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_track_b_terminal(stage: Optional[str]) -> bool:
    """UT-IE-010 / IE-011 — only restocked | discarded | claim_closed."""
    return (stage or "").strip().lower() in TRACK_B_TERMINAL


def assert_track_b_transition(from_stage: str, to_stage: str) -> None:
    allowed = TRACK_B_TRANSITIONS.get((from_stage or "").strip().lower(), frozenset())
    if (to_stage or "").strip().lower() not in allowed:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Illegal Track B transition: {from_stage} → {to_stage}"
            ),
        )


def _require_maintenance_rework(
    session: Session, rework_id: int
) -> InventoryReworkCase:
    rework = session.get(InventoryReworkCase, rework_id)
    if not rework:
        raise HTTPException(status_code=404, detail="Returned unit / rework not found")
    if not rework.maintenance_case_id:
        raise HTTPException(
            status_code=400,
            detail="Track B actions require a maintenance-linked rework case",
        )
    if rework.status != ReworkCaseStatus.OPEN.value and not is_track_b_terminal(
        rework.stage
    ):
        raise HTTPException(
            status_code=409, detail=f"Rework case is {rework.status}"
        )
    return rework


def _require_open(rework: InventoryReworkCase) -> None:
    if rework.status != ReworkCaseStatus.OPEN.value:
        raise HTTPException(
            status_code=409, detail="Rework case is closed"
        )
    if is_track_b_terminal(rework.stage):
        raise HTTPException(
            status_code=409,
            detail=f"Track B already terminal ({rework.stage})",
        )


def _set_item_status(
    session: Session,
    rework: InventoryReworkCase,
    status_code: str,
) -> None:
    """Best-effort instance/catalog status update (no Spec-10 transition assert)."""
    try:
        status_id = get_item_status_id(session, status_code)
    except Exception:
        return
    now = _now()
    if rework.current_instance_id:
        instance = session.get(InventoryInstance, rework.current_instance_id)
        if instance is not None:
            instance.status_id = status_id
            instance.updated_at = now
            session.add(instance)
    if rework.inventory_id:
        inventory = session.get(Inventory, rework.inventory_id)
        if inventory is not None:
            inventory.status_id = status_id
            inventory.updated_at = now
            session.add(inventory)


def _close_rework(rework: InventoryReworkCase, actor: Optional[User] = None) -> None:
    rework.status = ReworkCaseStatus.CLOSED.value
    rework.closed_at = _now()
    if actor and actor.id:
        rework.closed_by_id = int(actor.id)
    rework.updated_at = _now()


def record_reception(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    reception_date: Optional[datetime] = None,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    """IE-001/002 — IM records reception; notify PD."""
    rework = _require_maintenance_rework(session, rework_id)
    _require_open(rework)
    if rework.stage != ReworkStage.AWAITING_FAULTY_ARRIVAL.value:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Reception only from awaiting_faulty_arrival (current: {rework.stage})"
            ),
        )
    assert_track_b_transition(
        rework.stage, ReworkStage.RECEIVED.value
    )
    rework.reception_date = reception_date or _now()
    rework.stage = ReworkStage.RECEIVED.value
    rework.updated_at = _now()
    if notes:
        rework.notes = notes
    _set_item_status(session, rework, ItemStatus.RETURNED.value)
    session.add(rework)
    session.flush()

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="faulty_received",
        title="Faulty unit received",
        message=f"IM recorded reception for rework #{rework.id}",
        href=(
            f"/maintenance/cases/{rework.maintenance_case_id}"
            if rework.maintenance_case_id
            else "/inspect-queue"
        ),
        priority="high",
        actor=actor,
        include_pd=True,
        project_id=rework.project_id,
        entity_type="inventory_rework",
        entity_id=rework.id,
        extra_user_ids=(
            [int(rework.investigating_pd_id)]
            if rework.investigating_pd_id
            else None
        ),
    )
    return rework


def assign_ie(
    session: Session,
    rework_id: int,
    *,
    ie_user_id: int,
    actor: User,
) -> InventoryReworkCase:
    """IE-003 — PD assigns Inspection Engineer."""
    rework = _require_maintenance_rework(session, rework_id)
    _require_open(rework)
    if rework.stage != ReworkStage.RECEIVED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Assign IE only from received (current: {rework.stage})",
        )
    ie = session.get(User, ie_user_id)
    if not ie:
        raise HTTPException(status_code=404, detail="IE user not found")
    assert_track_b_transition(rework.stage, ReworkStage.IE_ASSIGNED.value)
    rework.assigned_developer_id = int(ie_user_id)
    rework.stage = ReworkStage.IE_ASSIGNED.value
    rework.updated_at = _now()
    session.add(rework)
    session.flush()

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="ie_assigned",
        title="Inspection Engineer assigned",
        message=f"PD assigned IE for rework #{rework.id}",
        href=f"/maintenance/cases/{rework.maintenance_case_id}",
        priority="medium",
        actor=actor,
        extra_user_ids=[int(ie_user_id)],
        project_id=rework.project_id,
        entity_type="inventory_rework",
        entity_id=rework.id,
    )
    return rework


def request_handover(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    """IE-004 (part) — IE requests handover from IM → issued_to_ie."""
    rework = _require_maintenance_rework(session, rework_id)
    _require_open(rework)
    if rework.stage != ReworkStage.IE_ASSIGNED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Handover request only from ie_assigned (current: {rework.stage})",
        )
    if rework.assigned_developer_id and actor.id:
        if int(rework.assigned_developer_id) != int(actor.id):
            # Allow edit_maintenance actors; soft check only when IE mismatched
            pass
    assert_track_b_transition(rework.stage, ReworkStage.ISSUED_TO_IE.value)
    rework.stage = ReworkStage.ISSUED_TO_IE.value
    rework.updated_at = _now()
    if notes:
        rework.notes = notes
    session.add(rework)
    session.flush()

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="handover_requested",
        title="IE requested faulty handover",
        message=f"IE requested IM issue of faulty unit for rework #{rework.id}",
        href=f"/maintenance/cases/{rework.maintenance_case_id}",
        priority="high",
        actor=actor,
        include_im=True,
        project_id=rework.project_id,
        entity_type="inventory_rework",
        entity_id=rework.id,
    )
    return rework


def im_issue_to_ie(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    """IE-004 — IM issues faulty to IE → inspection_under_process."""
    rework = _require_maintenance_rework(session, rework_id)
    _require_open(rework)
    if rework.stage != ReworkStage.ISSUED_TO_IE.value:
        raise HTTPException(
            status_code=409,
            detail=(
                f"IM issue to IE only from issued_to_ie (current: {rework.stage})"
            ),
        )
    if not rework.assigned_developer_id:
        raise HTTPException(status_code=400, detail="IE must be assigned first")
    assert_track_b_transition(
        rework.stage, ReworkStage.INSPECTION_UNDER_PROCESS.value
    )
    rework.stage = ReworkStage.INSPECTION_UNDER_PROCESS.value
    rework.updated_at = _now()
    if notes:
        rework.notes = notes
    _set_item_status(session, rework, ItemStatus.INSPECTION.value)
    session.add(rework)
    session.flush()

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="issued_to_ie",
        title="Faulty issued to IE",
        message=f"IM issued faulty unit to IE for rework #{rework.id}",
        href=f"/maintenance/cases/{rework.maintenance_case_id}",
        priority="medium",
        actor=actor,
        include_im=True,
        extra_user_ids=(
            [int(rework.assigned_developer_id)]
            if rework.assigned_developer_id
            else None
        ),
        project_id=rework.project_id,
        entity_type="inventory_rework",
        entity_id=rework.id,
    )
    return rework


def ie_disposition(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    outcome: str,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    """
    IE-005/006/007/013 — disposition from inspection_under_process.

    Outcomes:
      repairable → repair_under_progress
      warranty → warranty_claim (+ OEM claim)
      discard → discard_pending (NO scrap; IM must confirm)
      reusable → restocked (Should IE-013)
    """
    rework = _require_maintenance_rework(session, rework_id)
    _require_open(rework)
    if rework.stage != ReworkStage.INSPECTION_UNDER_PROCESS.value:
        raise HTTPException(
            status_code=409,
            detail=(
                "Disposition requires inspection_under_process "
                f"(current: {rework.stage})"
            ),
        )
    key = (outcome or "").strip().lower()
    if key == "repairable":
        to_stage = ReworkStage.REPAIR_UNDER_PROGRESS.value
        assert_track_b_transition(rework.stage, to_stage)
        rework.disposition = ReworkDisposition.REPAIRABLE.value
        rework.stage = to_stage
        _set_item_status(session, rework, ItemStatus.REPAIRABLE.value)
    elif key in ("warranty", "warranty_claim", "irreparable_warranty"):
        to_stage = ReworkStage.WARRANTY_CLAIM.value
        assert_track_b_transition(rework.stage, to_stage)
        claim, action = field_svc.create_or_require_warranty_claim(
            session,
            rework=rework,
            actor=actor,
            force_discard=False,
            notes=notes,
        )
        if action == "discard" or claim is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Warranty is not active. Use outcome=discard to recommend trash."
                ),
            )
        rework.disposition = ReworkDisposition.SCRAPPED.value
        rework.stage = to_stage
    elif key in ("discard", "scrapped", "recommend_discard"):
        to_stage = ReworkStage.DISCARD_PENDING.value
        assert_track_b_transition(rework.stage, to_stage)
        # Segregation: IE must NOT scrap here (UT-IE-006)
        rework.disposition = ReworkDisposition.SCRAPPED.value
        rework.stage = to_stage
    elif key == "reusable":
        to_stage = ReworkStage.RESTOCKED.value
        assert_track_b_transition(rework.stage, to_stage)
        rework.disposition = ReworkDisposition.REUSABLE.value
        rework.stage = to_stage
        _set_item_status(session, rework, ItemStatus.AVAILABLE.value)
        _close_rework(rework, actor)
    else:
        raise HTTPException(
            status_code=400,
            detail="outcome must be repairable, warranty, discard, or reusable",
        )
    rework.updated_at = _now()
    if notes:
        rework.notes = notes
    session.add(rework)
    session.flush()

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="inspection_disposition",
        title="IE inspection disposition",
        message=(
            f"Rework #{rework.id}: disposition → {key} "
            f"(stage={rework.stage})"
        ),
        href=f"/maintenance/cases/{rework.maintenance_case_id}",
        priority="medium",
        actor=actor,
        include_pd=True,
        project_id=rework.project_id,
        entity_type="inventory_rework",
        entity_id=rework.id,
    )
    return rework


def im_confirm_discard(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    """IE-007/008 — IM confirms trash → discarded + SCRAPPED."""
    rework = _require_maintenance_rework(session, rework_id)
    _require_open(rework)
    if rework.stage != ReworkStage.DISCARD_PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Confirm discard only from discard_pending (current: {rework.stage})"
            ),
        )
    assert_track_b_transition(rework.stage, ReworkStage.DISCARDED.value)
    rework.stage = ReworkStage.DISCARDED.value
    rework.disposition = ReworkDisposition.SCRAPPED.value
    rework.updated_at = _now()
    if notes:
        rework.notes = notes
    _set_item_status(session, rework, ItemStatus.SCRAPPED.value)
    _close_rework(rework, actor)
    session.add(rework)
    session.flush()

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="discard_completed",
        title="Faulty unit discarded",
        message=f"IM confirmed discard for rework #{rework.id}",
        href=f"/maintenance/cases/{rework.maintenance_case_id}",
        priority="medium",
        actor=actor,
        include_pd=True,
        include_im=True,
        project_id=rework.project_id,
        entity_type="inventory_rework",
        entity_id=rework.id,
    )
    return rework


def ie_submit_repair(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    notes: Optional[str] = None,
) -> InventoryReworkCase:
    """IE-009 — IE submits repair evidence; stays repair_under_progress; notify PD."""
    rework = _require_maintenance_rework(session, rework_id)
    _require_open(rework)
    if rework.stage != ReworkStage.REPAIR_UNDER_PROGRESS.value:
        raise HTTPException(
            status_code=409,
            detail=(
                "Repair submit only from repair_under_progress "
                f"(current: {rework.stage})"
            ),
        )
    rework.repaired_at = _now()
    rework.repaired_by_id = int(actor.id) if actor.id else None
    rework.updated_at = _now()
    if notes:
        rework.notes = notes
    session.add(rework)
    session.flush()

    from app.services.app_notification_service import notify

    notify(
        session,
        event_type="repair_awaiting_pd",
        title="Repair ready for PD verify",
        message=f"IE submitted repair evidence for rework #{rework.id}",
        href=f"/maintenance/cases/{rework.maintenance_case_id}",
        priority="high",
        actor=actor,
        include_pd=True,
        project_id=rework.project_id,
        entity_type="inventory_rework",
        entity_id=rework.id,
    )
    return rework


def pd_repair_decide(
    session: Session,
    rework_id: int,
    *,
    actor: User,
    decision: str,
    reject_reason: Optional[str] = None,
) -> InventoryReworkCase:
    """IE-009/010 — PD approve → restocked; reject → stay repair_under_progress."""
    rework = _require_maintenance_rework(session, rework_id)
    _require_open(rework)
    if rework.stage != ReworkStage.REPAIR_UNDER_PROGRESS.value:
        raise HTTPException(
            status_code=409,
            detail=(
                "PD repair decision only from repair_under_progress "
                f"(current: {rework.stage})"
            ),
        )
    key = (decision or "").strip().lower()
    if key in ("approve", "approved"):
        assert_track_b_transition(rework.stage, ReworkStage.RESTOCKED.value)
        rework.stage = ReworkStage.RESTOCKED.value
        rework.updated_at = _now()
        _set_item_status(session, rework, ItemStatus.AVAILABLE.value)
        _close_rework(rework, actor)
        session.add(rework)
        session.flush()

        from app.services.app_notification_service import notify

        notify(
            session,
            event_type="repaired_restocked",
            title="Repaired unit restocked",
            message=f"PD approved repair; rework #{rework.id} restocked",
            href=f"/maintenance/cases/{rework.maintenance_case_id}",
            priority="medium",
            actor=actor,
            include_pd=True,
            include_im=True,
            project_id=rework.project_id,
            entity_type="inventory_rework",
            entity_id=rework.id,
        )
        return rework
    if key in ("reject", "rejected"):
        # Stay on repair_under_progress (UT-IE-008)
        assert_track_b_transition(
            rework.stage, ReworkStage.REPAIR_UNDER_PROGRESS.value
        )
        rework.repaired_at = None
        rework.updated_at = _now()
        if reject_reason:
            rework.notes = (
                f"{rework.notes or ''}\nPD reject: {reject_reason}".strip()
            )
        session.add(rework)
        session.flush()
        return rework
    raise HTTPException(
        status_code=400, detail="decision must be approve or reject"
    )


def mark_claim_closed(
    session: Session,
    rework_id: int,
    *,
    actor: Optional[User] = None,
) -> InventoryReworkCase:
    """IE-006/011 — OEM claim closed → claim_closed terminal."""
    rework = _require_maintenance_rework(session, rework_id)
    if rework.stage != ReworkStage.WARRANTY_CLAIM.value:
        raise HTTPException(
            status_code=409,
            detail=(
                f"claim_closed only from warranty_claim (current: {rework.stage})"
            ),
        )
    if rework.status != ReworkCaseStatus.OPEN.value:
        return rework
    assert_track_b_transition(rework.stage, ReworkStage.CLAIM_CLOSED.value)
    rework.stage = ReworkStage.CLAIM_CLOSED.value
    rework.updated_at = _now()
    _close_rework(rework, actor)
    session.add(rework)
    session.flush()
    return rework


def sync_claim_closed_if_needed(
    session: Session,
    claim: OemWarrantyClaim,
    *,
    actor: Optional[User] = None,
) -> Optional[InventoryReworkCase]:
    """Hook for OEM claim update → Track B claim_closed."""
    status = (claim.status or "").strip().lower()
    if status != OemWarrantyClaimStatus.CLOSED.value:
        return None
    if not claim.rework_case_id:
        return None
    rework = session.get(InventoryReworkCase, int(claim.rework_case_id))
    if not rework or rework.stage != ReworkStage.WARRANTY_CLAIM.value:
        return None
    return mark_claim_closed(session, int(rework.id), actor=actor)


def discarded_flag(rework: InventoryReworkCase) -> bool:
    """IE-008 — Discarded badge when Track B discarded (SCRAPPED via IM)."""
    return (rework.stage or "") == ReworkStage.DISCARDED.value
