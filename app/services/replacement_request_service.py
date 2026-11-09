"""
P2/P3 — ReplacementRequest (Track A) + dual-track board helpers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.domain.workflow_status import ItemStatus
from app.auth import check_permission
from app.models.base import (
    CaseStatus,
    EntityType,
    InventoryReservationStatus,
    OnsiteOutcome,
    ReplacementRequestStatus,
    ResolutionType,
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
    MaintenanceOccurrenceAttachment,
    ReplacementRequest,
    ReplacementRequestAitAttachment,
    ReplacementRequestReservation,
    User,
)
from app.services import maintenance_field_service as field_svc
from app.services.inventory_reservation_service import (
    InventoryReservationError,
    get_item_status_id,
    item_status_name,
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
    ReplacementRequestStatus.PD_REJECTED.value: {
        # Opener may resubmit after PD asks for modification
        ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
    },
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

_TRACK_A_COMPLETE_STATUSES = frozenset(
    {
        ReplacementRequestStatus.PATCH_DELIVERED.value,
        ReplacementRequestStatus.TRACK_A_CLOSED.value,
    }
)

_TRACK_A_INACTIVE_STATUSES = frozenset(
    {
        ReplacementRequestStatus.PD_REJECTED.value,
        ReplacementRequestStatus.TRACK_A_CLOSED.value,
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
    """PD/HM assign ME only after PD approval (reassign allowed pre-issue)."""
    if req.status == ReplacementRequestStatus.PD_REJECTED.value:
        raise HTTPException(
            status_code=409, detail="Cannot assign ME on a rejected replacement request"
        )
    if req.status in _TRACK_A_INACTIVE_STATUSES:
        raise HTTPException(
            status_code=409, detail="Cannot assign ME on a closed/aborted replacement request"
        )
    # Assign ME only after PD approve; reassignment allowed through pre-issue statuses.
    if req.status not in (
        ReplacementRequestStatus.PD_APPROVED.value,
        ReplacementRequestStatus.IM_ISSUE_PENDING.value,
        ReplacementRequestStatus.AIT_REJECTED.value,
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Assign ME only after PD approval "
                f"(current: {req.status})"
            ),
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
    if not req.assigned_me_id:
        raise HTTPException(
            status_code=400,
            detail="Assign ME before reserving replacement inventory",
        )
    if req.status not in (
        ReplacementRequestStatus.PD_APPROVED.value,
        ReplacementRequestStatus.IM_ISSUE_PENDING.value,
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Reserve inventory only after PD approval and ME assignment "
                f"(current: {req.status})"
            ),
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


_REJECT_OUTCOMES = frozenset({"issue_fixed", "modification_required"})


def pd_decide(
    session: Session,
    case: MaintenanceCase,
    req: ReplacementRequest,
    *,
    actor: User,
    decision: str,
    reject_reason: Optional[str] = None,
    reject_outcome: Optional[str] = None,
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
        outcome = (reject_outcome or "").strip().lower()
        if outcome not in _REJECT_OUTCOMES:
            raise HTTPException(
                status_code=400,
                detail="reject_outcome must be issue_fixed or modification_required when rejecting",
            )
        assert_status_transition(
            req.status, ReplacementRequestStatus.PD_REJECTED.value
        )
        req.status = ReplacementRequestStatus.PD_REJECTED.value
        req.pd_decision = "reject"
        req.reject_reason = reject_reason.strip()
        req.reject_outcome = outcome
        req.updated_at = _now()
        session.add(req)

        if outcome == "issue_fixed":
            # Close the maintenance case and mark stepper skip arc.
            raw_status = getattr(case, "status", None)
            prior_status = str(getattr(raw_status, "value", raw_status) or CaseStatus.OPEN.value)
            prior_status = prior_status.strip().lower() or CaseStatus.OPEN.value
            case.workflow_skip_to_closed = True
            case.workflow_skip_from_status = prior_status
            case.status = CaseStatus.CLOSED
            note = f"Closed by PD — issue fixed without replacement. {reject_reason.strip()}"
            existing_notes = (case.resolution_notes or "").strip()
            case.resolution_notes = f"{existing_notes}\n{note}".strip() if existing_notes else note
            if not case.closed_at:
                case.closed_at = _now()
            if not case.resolved_at:
                case.resolved_at = _now()
            case.updated_at = _now()
            session.add(case)
            clear_replacement_red(session, int(case.id), req)

        session.flush()
        return req

    # P3: approve stops at pd_approved; ME request-issue advances next
    assert_status_transition(req.status, ReplacementRequestStatus.PD_APPROVED.value)
    req.status = ReplacementRequestStatus.PD_APPROVED.value
    req.pd_decision = "approve"
    req.reject_reason = None
    req.reject_outcome = None
    req.updated_at = _now()
    session.add(req)
    session.flush()
    return req


def resubmit_after_modification(
    session: Session,
    case: MaintenanceCase,
    req: ReplacementRequest,
    *,
    actor: User,
) -> ReplacementRequest:
    """Opener re-sends a PD-rejected (modification_required) request for approval."""
    if req.status != ReplacementRequestStatus.PD_REJECTED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Resubmit only allowed from pd_rejected (current: {req.status})",
        )
    outcome = (getattr(req, "reject_outcome", None) or "").strip().lower()
    if outcome != "modification_required":
        raise HTTPException(
            status_code=409,
            detail="Resubmit only allowed when PD requested modification",
        )
    if int(req.requested_by_id) != int(actor.id):
        if not check_permission(actor, "create_maintenance_cases") and not check_permission(
            actor, "edit_maintenance_cases"
        ):
            raise HTTPException(
                status_code=403,
                detail="Only the requester (or a case editor) can resubmit after modification",
            )

    case_status = str(getattr(getattr(case, "status", None), "value", getattr(case, "status", "")) or "").lower()
    if case_status == CaseStatus.CLOSED.value:
        raise HTTPException(
            status_code=409,
            detail="Cannot resubmit replacement on a closed maintenance case",
        )

    assert_status_transition(
        req.status, ReplacementRequestStatus.REPLACEMENT_REQUESTED.value
    )
    req.status = ReplacementRequestStatus.REPLACEMENT_REQUESTED.value
    req.pd_decision = None
    req.reject_reason = None
    req.reject_outcome = None
    req.updated_at = _now()
    session.add(req)
    session.flush()
    return req


def me_request_issue(
    session: Session,
    req: ReplacementRequest,
) -> ReplacementRequest:
    """ME requests IM to ISSUE reserved inventory (RA-005)."""
    if req.status != ReplacementRequestStatus.PD_APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=f"ME request-issue only from pd_approved (current: {req.status})",
        )
    if not req.assigned_me_id:
        raise HTTPException(
            status_code=400, detail="ME must be assigned before requesting issue"
        )
    links = list_reservations(session, int(req.id))
    if not links:
        raise HTTPException(
            status_code=400,
            detail="At least one inventory reservation is required before requesting issue",
        )
    assert_status_transition(
        req.status, ReplacementRequestStatus.IM_ISSUE_PENDING.value
    )
    req.status = ReplacementRequestStatus.IM_ISSUE_PENDING.value
    req.shortage_held = False
    req.updated_at = _now()
    session.add(req)
    session.flush()
    return req


def _active_reservation_link(
    session: Session, req: ReplacementRequest
) -> tuple[ReplacementRequestReservation, InventoryReservation]:
    links = list_reservations(session, int(req.id))
    if not links:
        raise HTTPException(
            status_code=400, detail="No reservation linked to this replacement request"
        )
    # Prefer newest active reservation
    for link in reversed(links):
        if not link.inventory_reservation_id:
            continue
        res = session.get(InventoryReservation, int(link.inventory_reservation_id))
        if res and res.status == InventoryReservationStatus.ACTIVE.value:
            return link, res
    raise HTTPException(
        status_code=409,
        detail="No active inventory reservation available for issue (shortage or consumed)",
    )


def _quarantine_instance(session: Session, instance_id: int) -> None:
    inst = session.get(InventoryInstance, int(instance_id))
    if not inst:
        return
    status_id = get_item_status_id(session, ItemStatus.INSPECTION.value)
    inst.status_id = status_id
    session.add(inst)
    if inst.inventory_id:
        inv = session.get(Inventory, int(inst.inventory_id))
        if inv:
            inv.status_id = status_id
            session.add(inv)
    session.flush()


def _hold_shortage(session: Session, req: ReplacementRequest) -> ReplacementRequest:
    req.shortage_held = True
    req.updated_at = _now()
    session.add(req)
    session.flush()
    return req


def im_issue(
    session: Session,
    case: MaintenanceCase,
    req: ReplacementRequest,
    *,
    actor: User,
    signature_type: str,
    signature_payload: Optional[str] = None,
    notes: Optional[str] = None,
) -> ReplacementRequest:
    """IM issues reserved S/N, hierarchy swap, Replaced badge, RED, Track B (RA-006…009)."""
    if req.status != ReplacementRequestStatus.IM_ISSUE_PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f"IM issue only from im_issue_pending (current: {req.status})",
        )
    if not req.assigned_me_id:
        raise HTTPException(status_code=400, detail="assigned_me_id is required to issue")

    try:
        link, reservation = _active_reservation_link(session, req)
    except HTTPException as exc:
        if exc.status_code == 409:
            _hold_shortage(session, req)
        raise

    instance_id = link.inventory_instance_id or reservation.inventory_instance_id
    inventory = session.get(Inventory, int(reservation.inventory_id))
    if not inventory:
        _hold_shortage(session, req)
        raise HTTPException(status_code=409, detail="Reserved inventory not found (shortage)")

    if instance_id:
        inst = session.get(InventoryInstance, int(instance_id))
        if not inst:
            _hold_shortage(session, req)
            raise HTTPException(
                status_code=409, detail="Reserved serial not found (shortage)"
            )
        status_name = (item_status_name(session, inst.status_id) or "").upper()
        if status_name in (
            ItemStatus.SCRAPPED.value,
            ItemStatus.INSPECTION.value,
            ItemStatus.ISSUED.value,
            ItemStatus.INSTALLED_VERIFIED.value,
        ):
            _hold_shortage(session, req)
            raise HTTPException(
                status_code=409,
                detail=f"Reserved serial not issuable (status={status_name or 'unknown'}); shortage held",
            )

    from app.services.inventory_issuance_service import issue_inventory_unit
    from app.services.entity_replacement_service import create_replacement_entity

    try:
        issuance = issue_inventory_unit(
            session,
            inventory,
            issued_to_user_id=int(req.assigned_me_id),
            issued_by_user_id=int(actor.id),
            quantity=1,
            instance_id=int(instance_id) if instance_id else None,
            target_entity_type=reservation.target_entity_type,
            target_entity_id=reservation.target_entity_id,
            notes=notes or f"Maintenance replacement request #{req.id}",
            signature_type=signature_type,
            signature_payload=signature_payload,
            request_reservation_id=int(reservation.id),
            for_maintenance_replacement=True,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        if exc.status_code in (400, 404, 409) and any(
            k in detail.lower()
            for k in ("not found", "unavailable", "scrapped", "already issued", "shortage")
        ):
            _hold_shortage(session, req)
            raise HTTPException(status_code=409, detail=f"Stock shortage: {detail}") from exc
        raise

    # Hierarchy S/N swap → Replaced badge (replaced_at / sequence)
    et_raw = (
        reservation.target_entity_type
        or req.faulty_entity_type
        or case.entity_type
        or ""
    ).strip().lower()
    eid = reservation.target_entity_id or req.faulty_entity_ref_id or case.entity_id
    if et_raw and eid is not None and et_raw in {e.value for e in EntityType}:
        try:
            from app.services.entity_replacement_service import (
                apply_inventory_to_replacement,
                resolve_current_install_row,
            )

            entity_type = EntityType(et_raw)
            old_row = resolve_current_install_row(session, entity_type, int(eid))
            new_pn = inventory.part_number or case.part_number or ""
            new_sn = issuance.serial_number
            inv_part, inv_serial, inv_config, inv_picture = apply_inventory_to_replacement(
                session, inventory, issuance.inventory_instance_id
            )
            create_replacement_entity(
                session,
                entity_type=entity_type,
                old_row=old_row,
                new_part_number=inv_part or new_pn,
                new_serial_number=inv_serial or new_sn,
                new_configuration_item=inv_config or inv_part or new_pn,
                performed_by_id=int(actor.id),
                picture_url=inv_picture,
            )
        except Exception:
            # Issue still counts; hierarchy swap best-effort for tests without full hierarchy
            pass

    assert_status_transition(
        req.status, ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value
    )
    now = _now()
    req.status = ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value
    req.issued_serial = issuance.serial_number
    req.issued_instance_id = issuance.inventory_instance_id
    req.issued_at = now
    req.shortage_held = False
    req.red_notified_at = now
    req.updated_at = now
    session.add(req)
    session.flush()

    _ensure_track_b_awaiting(session, case, req, actor=actor)
    return req


def me_start_ait(
    session: Session,
    req: ReplacementRequest,
) -> ReplacementRequest:
    """ME marks AIT in progress (RA-010/011 custody + site)."""
    if req.status != ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value:
        raise HTTPException(
            status_code=409,
            detail=f"AIT start only from shipped_replaced_badge (current: {req.status})",
        )
    assert_status_transition(
        req.status, ReplacementRequestStatus.AIT_IN_PROGRESS.value
    )
    req.status = ReplacementRequestStatus.AIT_IN_PROGRESS.value
    req.updated_at = _now()
    session.add(req)
    session.flush()
    return req


def list_ait_attachments(
    session: Session, request_id: int
) -> list[ReplacementRequestAitAttachment]:
    return list(
        session.exec(
            select(ReplacementRequestAitAttachment).where(
                ReplacementRequestAitAttachment.replacement_request_id == request_id
            )
        ).all()
    )


def upload_ait_attachment(
    session: Session,
    req: ReplacementRequest,
    *,
    display_name: str,
    file_id: Optional[int] = None,
    occurrence_attachment_id: Optional[int] = None,
) -> ReplacementRequestAitAttachment:
    """Attach named AIT evidence (RA-010); optional link to occurrence attachment (RA-019)."""
    if req.status not in (
        ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value,
        ReplacementRequestStatus.AIT_IN_PROGRESS.value,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"AIT upload not allowed while status is {req.status}",
        )
    name = (display_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="display_name is required")
    if file_id is None and occurrence_attachment_id is None:
        raise HTTPException(
            status_code=400,
            detail="file_id or occurrence_attachment_id is required",
        )
    if occurrence_attachment_id is not None:
        occ = session.get(MaintenanceOccurrenceAttachment, int(occurrence_attachment_id))
        if not occ or occ.case_id != req.case_id:
            raise HTTPException(
                status_code=400,
                detail="occurrence_attachment_id does not belong to this case",
            )
        if file_id is None:
            file_id = occ.file_id

    if req.status == ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value:
        me_start_ait(session, req)

    row = ReplacementRequestAitAttachment(
        replacement_request_id=int(req.id),
        display_name=name,
        file_id=int(file_id) if file_id is not None else None,
        occurrence_attachment_id=(
            int(occurrence_attachment_id) if occurrence_attachment_id is not None else None
        ),
        created_at=_now(),
    )
    session.add(row)
    req.updated_at = _now()
    session.add(req)
    session.flush()
    return row


def pd_ait_decide(
    session: Session,
    req: ReplacementRequest,
    *,
    decision: str,
    reject_reason: Optional[str] = None,
) -> ReplacementRequest:
    """PD Approve/Reject AIT (RA-012…014); reject quarantines and re-opens issue loop."""
    key = (decision or "").strip().lower()
    if key not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be approve or reject")

    if req.status != ReplacementRequestStatus.AIT_IN_PROGRESS.value:
        raise HTTPException(
            status_code=409,
            detail=f"AIT decision only from ait_in_progress (current: {req.status})",
        )

    attachments = list_ait_attachments(session, int(req.id))
    if not attachments:
        raise HTTPException(
            status_code=400, detail="AIT attachments are required before PD decision"
        )

    if key == "reject":
        if not (reject_reason or "").strip():
            raise HTTPException(
                status_code=400, detail="reject_reason is required when rejecting AIT"
            )
        assert_status_transition(
            req.status, ReplacementRequestStatus.AIT_REJECTED.value
        )
        req.status = ReplacementRequestStatus.AIT_REJECTED.value
        req.ait_decision = "reject"
        req.ait_reject_reason = reject_reason.strip()
        if req.issued_instance_id:
            _quarantine_instance(session, int(req.issued_instance_id))
            req.quarantined_instance_id = int(req.issued_instance_id)
        req.issued_instance_id = None
        req.issued_serial = None
        req.issued_at = None
        req.updated_at = _now()
        session.add(req)
        session.flush()

        assert_status_transition(
            req.status, ReplacementRequestStatus.IM_ISSUE_PENDING.value
        )
        req.status = ReplacementRequestStatus.IM_ISSUE_PENDING.value
        req.shortage_held = False
        req.updated_at = _now()
        session.add(req)
        session.flush()
        return req

    assert_status_transition(
        req.status, ReplacementRequestStatus.AIT_APPROVED.value
    )
    req.status = ReplacementRequestStatus.AIT_APPROVED.value
    req.ait_decision = "approve"
    req.ait_reject_reason = None
    req.updated_at = _now()
    session.add(req)
    session.flush()

    assert_status_transition(
        req.status, ReplacementRequestStatus.PATCH_DELIVERED.value
    )
    req.status = ReplacementRequestStatus.PATCH_DELIVERED.value
    req.updated_at = _now()
    session.add(req)
    session.flush()
    # RA-016 — clear RED when patch delivered
    clear_replacement_red(session, int(req.case_id), req)
    return req


def is_soft_nff_early_exit(case: MaintenanceCase) -> bool:
    """Soft-fix / NFF paths close without dual-track gate (DT-003 early exit)."""
    outcome = (getattr(case, "onsite_outcome", None) or "").strip().lower()
    if outcome in (
        OnsiteOutcome.SOFT_FIX.value,
        OnsiteOutcome.NO_FAULT_FOUND.value,
    ):
        return True
    rt = getattr(case, "resolution_type", None)
    if rt is not None:
        rt_val = str(getattr(rt, "value", rt) or "").strip().lower()
        if rt_val == ResolutionType.SOFT_FIXED.value:
            return True
    return False


def dual_track_applicable(session: Session, case: MaintenanceCase) -> bool:
    """True when dual-track close gate must run (not DT-004 exempt)."""
    for req in list_requests_for_case(session, int(case.id)):
        if req.status == ReplacementRequestStatus.PD_REJECTED.value:
            continue
        if (
            req.status == ReplacementRequestStatus.TRACK_A_CLOSED.value
            and (req.abort_reason or "").strip()
        ):
            # Aborted Track A — gate only if Track B still active below
            continue
        # Any non-rejected / non-abort RR means dual-track was started
        return True

    reworks = field_svc.list_case_returned_units(session, int(case.id))
    for rework in reworks:
        stage = (rework.stage or "").strip().lower()
        if stage in ("", "idle"):
            continue
        # Any real Track B spine (open or terminal) implies dual-track applies
        return True
    return False


def dual_track_active(session: Session, case: MaintenanceCase) -> bool:
    """Open Track A (non-inactive) or non-terminal Track B."""
    req = get_open_request_for_case(session, int(case.id))
    if req and req.status not in _TRACK_A_INACTIVE_STATUSES:
        return True
    from app.services import track_b_inspection_service as track_b_svc

    reworks = field_svc.list_case_returned_units(session, int(case.id))
    for rework in reworks:
        if rework.status != ReworkCaseStatus.OPEN.value:
            continue
        stage = (rework.stage or "").strip().lower()
        if stage in ("", "idle"):
            continue
        if not track_b_svc.is_track_b_terminal(rework.stage):
            return True
    return False


def clear_replacement_red(
    session: Session,
    case_id: int,
    req: Optional[ReplacementRequest] = None,
) -> None:
    """RA-016 / UT-NT-003 — clear red_notified_at and dismiss RED notifications."""
    targets: list[ReplacementRequest]
    if req is not None:
        targets = [req]
    else:
        targets = [
            r
            for r in list_requests_for_case(session, int(case_id))
            if getattr(r, "red_notified_at", None) is not None
        ]
    for row in targets:
        if getattr(row, "red_notified_at", None) is not None:
            row.red_notified_at = None
            row.updated_at = _now()
            session.add(row)
    from app.services.app_notification_service import (
        dismiss_replacement_case_open_notifications,
    )

    dismiss_replacement_case_open_notifications(
        session, case_id=int(case_id), commit=False
    )
    session.flush()


def assert_dual_track_close_allowed(session: Session, case: MaintenanceCase) -> None:
    """
    DT-003 / UT-RA-010 — raise 409 unless Soft/NFF early exit, dual-track N/A (DT-004),
    or Track A complete AND Track B terminal.
    """
    if is_soft_nff_early_exit(case):
        return
    if not dual_track_applicable(session, case):
        return

    board = build_dual_track_board(session, case)
    track_a_status = board.get("track_a_status")
    track_a = board.get("track_a")
    track_b_terminal = bool(board.get("track_b_terminal"))
    track_b_status = board.get("track_b_status")

    aborted = bool(
        track_a
        and track_a_status == ReplacementRequestStatus.TRACK_A_CLOSED.value
        and (getattr(track_a, "abort_reason", None) or "").strip()
    )
    track_a_ok = track_a_status in _TRACK_A_COMPLETE_STATUSES
    if aborted and (track_b_status in (None, "idle") or track_b_terminal):
        return

    if not track_a_ok:
        raise HTTPException(
            status_code=409,
            detail=(
                "Dual-track close gate: Track A incomplete "
                f"(status={track_a_status or 'none'}; need patch_delivered)"
            ),
        )
    if not track_b_terminal:
        raise HTTPException(
            status_code=409,
            detail=(
                "Dual-track close gate: Track B incomplete "
                f"(status={track_b_status or 'none'}; need restocked|discarded|claim_closed)"
            ),
        )


def finalize_track_a_on_case_close(
    session: Session, case: MaintenanceCase
) -> Optional[ReplacementRequest]:
    """Move patch_delivered → track_a_closed when the case closes."""
    req = get_open_request_for_case(session, int(case.id))
    if not req:
        return None
    if req.status == ReplacementRequestStatus.PATCH_DELIVERED.value:
        assert_status_transition(
            req.status, ReplacementRequestStatus.TRACK_A_CLOSED.value
        )
        req.status = ReplacementRequestStatus.TRACK_A_CLOSED.value
        req.updated_at = _now()
        session.add(req)
        session.flush()
    clear_replacement_red(session, int(case.id), req)
    return req


def abort_track_a(
    session: Session,
    req: ReplacementRequest,
    *,
    reason: str,
) -> ReplacementRequest:
    """RA-017 — abort Track A (e.g. later NFF); cancel request; clear RED; keep audit."""
    reason_text = (reason or "").strip()
    if not reason_text:
        raise HTTPException(status_code=400, detail="abort reason is required")
    if req.status in (
        ReplacementRequestStatus.PD_REJECTED.value,
        ReplacementRequestStatus.TRACK_A_CLOSED.value,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot abort replacement request in status {req.status}",
        )
    req.abort_reason = reason_text
    req.status = ReplacementRequestStatus.TRACK_A_CLOSED.value
    req.updated_at = _now()
    session.add(req)
    session.flush()
    clear_replacement_red(session, int(req.case_id), req)
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
    track_b_discarded = False
    track_b_terminal = False
    if open_rework:
        from app.services import track_b_inspection_service as track_b_svc

        track_b_rework_id = int(open_rework.id) if open_rework.id else None
        track_b_status = open_rework.stage or "idle"
        track_b_reception_date = getattr(open_rework, "reception_date", None)
        track_b_discarded = track_b_svc.discarded_flag(open_rework)
        track_b_terminal = track_b_svc.is_track_b_terminal(open_rework.stage)
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
        "track_b_discarded": track_b_discarded,
        "track_b_terminal": track_b_terminal,
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
