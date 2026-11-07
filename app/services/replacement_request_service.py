"""
P2 — ReplacementRequest (Track A) + dual-track board helpers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.base import (
    OnsiteOutcome,
    ReplacementRequestStatus,
    ReworkCaseStatus,
    ReworkStage,
)
from app.models.tables import (
    FaultyEntity,
    Inventory,
    InventoryInstance,
    InventoryReservation,
    InventoryReworkCase,
    MaintenanceCase,
    ReplacementRequest,
    ReplacementRequestReservation,
    User,
)
from app.services import maintenance_field_service as field_svc
from app.services.inventory_reservation_service import (
    InventoryReservationError,
    reserve_inventory,
)

# Legal Track A transitions for P2 (+ room for later phases)
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ReplacementRequestStatus.REPLACEMENT_REQUESTED.value: {
        ReplacementRequestStatus.PD_APPROVED.value,
        ReplacementRequestStatus.PD_REJECTED.value,
        # HM may keep status while assigning/reserving
        ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
    },
    ReplacementRequestStatus.PD_APPROVED.value: {
        ReplacementRequestStatus.IM_ISSUE_PENDING.value,
    },
    ReplacementRequestStatus.PD_REJECTED.value: set(),
    ReplacementRequestStatus.IM_ISSUE_PENDING.value: {
        ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value,
    },
    ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value: {
        ReplacementRequestStatus.AIT_IN_PROGRESS.value,
    },
    ReplacementRequestStatus.AIT_IN_PROGRESS.value: {
        ReplacementRequestStatus.AIT_APPROVED.value,
        ReplacementRequestStatus.AIT_REJECTED.value,
    },
    ReplacementRequestStatus.AIT_APPROVED.value: {
        ReplacementRequestStatus.PATCH_DELIVERED.value,
    },
    ReplacementRequestStatus.AIT_REJECTED.value: {
        ReplacementRequestStatus.IM_ISSUE_PENDING.value,
    },
    ReplacementRequestStatus.PATCH_DELIVERED.value: {
        ReplacementRequestStatus.TRACK_A_CLOSED.value,
    },
    ReplacementRequestStatus.TRACK_A_CLOSED.value: set(),
}

_OPEN_REQUEST_STATUSES = frozenset(
    {
        ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
        ReplacementRequestStatus.PD_APPROVED.value,
        ReplacementRequestStatus.IM_ISSUE_PENDING.value,
        ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value,
        ReplacementRequestStatus.AIT_IN_PROGRESS.value,
        ReplacementRequestStatus.AIT_REJECTED.value,
        ReplacementRequestStatus.AIT_APPROVED.value,
        ReplacementRequestStatus.PATCH_DELIVERED.value,
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def assert_status_transition(current: str, new: str) -> None:
    allowed = _ALLOWED_TRANSITIONS.get(current, set())
    if new == current:
        return
    if new not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Illegal ReplacementRequest status jump: {current} → {new}",
        )


def _entity_type_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(getattr(value, "value", value)).strip().lower() or None


def get_open_request_for_case(
    session: Session, case_id: int
) -> Optional[ReplacementRequest]:
    return session.exec(
        select(ReplacementRequest)
        .where(
            ReplacementRequest.case_id == case_id,
            ReplacementRequest.status.in_(list(_OPEN_REQUEST_STATUSES)),
        )
        .order_by(ReplacementRequest.id.desc())
    ).first()


def list_requests_for_case(
    session: Session, case_id: int
) -> list[ReplacementRequest]:
    return list(
        session.exec(
            select(ReplacementRequest)
            .where(ReplacementRequest.case_id == case_id)
            .order_by(ReplacementRequest.id.desc())
        ).all()
    )


def get_request(
    session: Session, request_id: int, *, case_id: Optional[int] = None
) -> ReplacementRequest:
    row = session.get(ReplacementRequest, request_id)
    if not row or (case_id is not None and row.case_id != case_id):
        raise HTTPException(status_code=404, detail="Replacement request not found")
    return row


def list_reservations(
    session: Session, request_id: int
) -> list[ReplacementRequestReservation]:
    return list(
        session.exec(
            select(ReplacementRequestReservation).where(
                ReplacementRequestReservation.replacement_request_id == request_id
            )
        ).all()
    )


def create_replacement_request(
    session: Session,
    case: MaintenanceCase,
    *,
    actor: User,
    faulty_entity_id: Optional[int] = None,
) -> ReplacementRequest:
    outcome = (case.onsite_outcome or "").strip().lower()
    if outcome != OnsiteOutcome.FAULT_IDENTIFIED.value:
        raise HTTPException(
            status_code=400,
            detail="Occurrence Report must be fault_identified before creating a replacement request",
        )
    if not (case.confirmation_channel or "").strip():
        raise HTTPException(
            status_code=400,
            detail="confirmation_channel is required on the Occurrence Report before creating a replacement request",
        )

    existing = get_open_request_for_case(session, int(case.id))
    if existing:
        raise HTTPException(
            status_code=409,
            detail="An open ReplacementRequest already exists for this case",
        )

    fe: Optional[FaultyEntity] = None
    if faulty_entity_id is not None:
        fe = session.get(FaultyEntity, int(faulty_entity_id))
        if not fe or fe.case_id != case.id:
            raise HTTPException(
                status_code=400, detail="faulty_entity_id does not belong to this case"
            )
    else:
        fes = list(
            session.exec(
                select(FaultyEntity).where(FaultyEntity.case_id == case.id)
            ).all()
        )
        fe = fes[0] if fes else None

    et = _entity_type_str(fe.entity_type) if fe else _entity_type_str(case.entity_type)
    eid = int(fe.entity_id) if fe else (
        int(case.entity_id) if case.entity_id is not None else None
    )

    now = _now()
    req = ReplacementRequest(
        case_id=int(case.id),
        faulty_entity_id=int(fe.id) if fe and fe.id else None,
        faulty_entity_type=et,
        faulty_entity_ref_id=eid,
        requested_by_id=int(actor.id),
        assigned_me_id=None,
        status=ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
        created_at=now,
        updated_at=now,
    )
    session.add(req)
    session.flush()
    return req


def assign_me(
    session: Session,
    req: ReplacementRequest,
    *,
    assigned_me_id: int,
) -> ReplacementRequest:
    if req.status == ReplacementRequestStatus.PD_REJECTED.value:
        raise HTTPException(
            status_code=409, detail="Cannot assign ME on a rejected replacement request"
        )
    if req.status not in (
        ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
        ReplacementRequestStatus.PD_APPROVED.value,
        ReplacementRequestStatus.IM_ISSUE_PENDING.value,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot assign ME while status is {req.status}",
        )
    me = session.get(User, int(assigned_me_id))
    if not me:
        raise HTTPException(status_code=400, detail="assigned_me_id user not found")
    req.assigned_me_id = int(assigned_me_id)
    req.updated_at = _now()
    session.add(req)
    session.flush()
    return req


def reserve_for_request(
    session: Session,
    case: MaintenanceCase,
    req: ReplacementRequest,
    *,
    actor: User,
    inventory_id: Optional[int] = None,
    inventory_instance_id: Optional[int] = None,
    part_number: Optional[str] = None,
    serial_number: Optional[str] = None,
    target_entity_type: Optional[str] = None,
    target_entity_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> ReplacementRequest:
    if req.status == ReplacementRequestStatus.PD_REJECTED.value:
        raise HTTPException(
            status_code=409, detail="Cannot reserve for a rejected replacement request"
        )
    if req.status not in (
        ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
        ReplacementRequestStatus.PD_APPROVED.value,
        ReplacementRequestStatus.IM_ISSUE_PENDING.value,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reserve while status is {req.status}",
        )

    et = (target_entity_type or req.faulty_entity_type or case.entity_type or "").strip().lower()
    eid = target_entity_id
    if eid is None:
        eid = req.faulty_entity_ref_id or case.entity_id
    if not et or eid is None:
        raise HTTPException(
            status_code=400,
            detail="target_entity_type and target_entity_id are required to reserve",
        )

    pn = (part_number or case.part_number or "").strip() or None
    if req.faulty_entity_id and not pn:
        fe = session.get(FaultyEntity, req.faulty_entity_id)
        if fe and fe.part_number:
            pn = fe.part_number

    payload: dict[str, Any] = {
        "target_entity_type": et,
        "target_entity_id": int(eid),
        "notes": notes or f"Maintenance replacement request #{req.id}",
    }
    if inventory_id is not None:
        payload["inventory_id"] = int(inventory_id)
    if inventory_instance_id is not None:
        payload["inventory_instance_id"] = int(inventory_instance_id)
    if pn:
        payload["part_number"] = pn
    if serial_number:
        payload["serial_number"] = serial_number

    try:
        reservation = reserve_inventory(
            session,
            int(case.project_id),
            payload,
            actor=actor,
            create_shortage_if_unavailable=False,
            commit=False,
            allow_assembled=True,
            for_maintenance_replacement=True,
        )
    except InventoryReservationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    link = ReplacementRequestReservation(
        replacement_request_id=int(req.id),
        inventory_reservation_id=int(reservation.id) if reservation.id else None,
        inventory_instance_id=(
            int(reservation.inventory_instance_id)
            if reservation.inventory_instance_id
            else None
        ),
        created_at=_now(),
    )
    session.add(link)
    req.updated_at = _now()
    session.add(req)
    session.flush()
    return req


def assign_me_and_reserve(
    session: Session,
    case: MaintenanceCase,
    req: ReplacementRequest,
    *,
    actor: User,
    assigned_me_id: int,
    inventory_id: Optional[int] = None,
    inventory_instance_id: Optional[int] = None,
    part_number: Optional[str] = None,
    serial_number: Optional[str] = None,
    target_entity_type: Optional[str] = None,
    target_entity_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> ReplacementRequest:
    assign_me(session, req, assigned_me_id=assigned_me_id)
    return reserve_for_request(
        session,
        case,
        req,
        actor=actor,
        inventory_id=inventory_id,
        inventory_instance_id=inventory_instance_id,
        part_number=part_number,
        serial_number=serial_number,
        target_entity_type=target_entity_type,
        target_entity_id=target_entity_id,
        notes=notes,
    )


def _ensure_track_b_awaiting(
    session: Session,
    case: MaintenanceCase,
    req: ReplacementRequest,
    *,
    actor: User,
) -> Optional[InventoryReworkCase]:
    """Open or promote Track B rework to awaiting_faulty_arrival (no physical return)."""
    fe_id = req.faulty_entity_id
    et = req.faulty_entity_type
    eid = req.faulty_entity_ref_id
    pn = case.part_number
    sn: Optional[str] = None

    if fe_id:
        fe = session.get(FaultyEntity, fe_id)
        if fe:
            et = _entity_type_str(fe.entity_type) or et
            eid = int(fe.entity_id)
            pn = fe.part_number or pn
            sn = fe.serial_number

    if not et or eid is None:
        # Soft Track B marker: create a stub rework only if we can resolve inventory
        return None

    if fe_id is None:
        # create_returned_unit_rework requires faulty_entity_id; invent a soft open FE link
        # by using 0 is invalid — skip if no FE
        return None

    return field_svc.create_returned_unit_rework(
        session,
        case=case,
        faulty_entity_id=int(fe_id),
        entity_type=str(et),
        entity_id=int(eid),
        part_number=pn,
        serial_number=sn,
        actor=actor,
        notes="Awaiting faulty arrival (Track B — dual-track)",
        initial_stage=ReworkStage.AWAITING_FAULTY_ARRIVAL.value,
    )


def pd_decide(
    session: Session,
    case: MaintenanceCase,
    req: ReplacementRequest,
    *,
    actor: User,
    decision: str,
    reject_reason: Optional[str] = None,
) -> ReplacementRequest:
    key = (decision or "").strip().lower()
    if key not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be approve or reject")

    if req.status != ReplacementRequestStatus.REPLACEMENT_REQUESTED.value:
        raise HTTPException(
            status_code=409,
            detail=f"PD decision only allowed from replacement_requested (current: {req.status})",
        )

    if key == "reject":
        if not (reject_reason or "").strip():
            raise HTTPException(
                status_code=400, detail="reject_reason is required when rejecting"
            )
        assert_status_transition(
            req.status, ReplacementRequestStatus.PD_REJECTED.value
        )
        req.status = ReplacementRequestStatus.PD_REJECTED.value
        req.pd_decision = "reject"
        req.reject_reason = reject_reason.strip()
        req.updated_at = _now()
        session.add(req)
        session.flush()
        return req

    # approve → pd_approved → im_issue_pending; queue Track B
    assert_status_transition(req.status, ReplacementRequestStatus.PD_APPROVED.value)
    req.status = ReplacementRequestStatus.PD_APPROVED.value
    req.pd_decision = "approve"
    req.reject_reason = None
    req.updated_at = _now()
    session.add(req)
    session.flush()

    assert_status_transition(
        req.status, ReplacementRequestStatus.IM_ISSUE_PENDING.value
    )
    req.status = ReplacementRequestStatus.IM_ISSUE_PENDING.value
    req.updated_at = _now()
    session.add(req)
    session.flush()

    _ensure_track_b_awaiting(session, case, req, actor=actor)
    return req


def build_dual_track_board(
    session: Session, case: MaintenanceCase
) -> dict[str, Any]:
    req = get_open_request_for_case(session, int(case.id))
    if req is None:
        # Fall back to latest request (including rejected) for display
        all_reqs = list_requests_for_case(session, int(case.id))
        req = all_reqs[0] if all_reqs else None

    track_b_status: Optional[str] = "idle"
    track_b_rework_id: Optional[int] = None
    track_b_reception_date = None

    reworks = field_svc.list_case_returned_units(session, int(case.id))
    open_rework = next(
        (r for r in reworks if r.status == ReworkCaseStatus.OPEN.value),
        reworks[0] if reworks else None,
    )
    if open_rework:
        track_b_rework_id = int(open_rework.id) if open_rework.id else None
        track_b_status = open_rework.stage or "idle"
        track_b_reception_date = getattr(open_rework, "reception_date", None)
    elif req and req.status == ReplacementRequestStatus.REPLACEMENT_REQUESTED.value:
        track_b_status = "idle"
    elif req is None:
        track_b_status = None

    return {
        "case_id": int(case.id),
        "track_a": req,
        "track_a_status": req.status if req else None,
        "track_b_status": track_b_status,
        "track_b_rework_id": track_b_rework_id,
        "track_b_reception_date": track_b_reception_date,
    }


def reservation_read_extras(
    session: Session, link: ReplacementRequestReservation
) -> dict[str, Optional[str]]:
    sn = None
    pn = None
    if link.inventory_reservation_id:
        res = session.get(InventoryReservation, link.inventory_reservation_id)
        if res:
            sn = res.serial_number
            pn = res.part_number
    if link.inventory_instance_id and not sn:
        inst = session.get(InventoryInstance, link.inventory_instance_id)
        if inst:
            sn = inst.serial_number
            if inst.inventory_id:
                inv = session.get(Inventory, inst.inventory_id)
                if inv:
                    pn = inv.part_number
    return {"serial_number": sn, "part_number": pn}
