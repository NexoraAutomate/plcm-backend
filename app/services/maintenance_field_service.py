"""Field-service helpers for maintenance cases (Phase 1 + Occurrence Report P1)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional, Sequence

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.base import (
    ConfirmationChannel,
    FaultType,
    OemWarrantyClaimStatus,
    OnsiteOutcome,
    ReworkCaseStatus,
    ReworkStage,
    SoftFixMethod,
)
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryReworkCase,
    MaintenanceCase,
    MaintenanceOccurrenceAttachment,
    MaintenanceOccurrenceOfficer,
    OemWarrantyClaim,
    Order,
    Project,
    User,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_order_for_project(session: Session, project_id: int) -> Optional[Order]:
    project = session.get(Project, project_id)
    if not project or not project.order_id:
        return None
    return session.get(Order, project.order_id)


def compute_production_support(
    support_date: Optional[date],
    *,
    today: Optional[date] = None,
) -> tuple[Optional[date], Optional[bool]]:
    """Return (snapshot_date, in_support). None in_support when date unset."""
    if support_date is None:
        return None, None
    day = today or date.today()
    return support_date, support_date >= day


def apply_support_gate_on_create(
    session: Session,
    *,
    project_id: int,
    support_override_reason: Optional[str],
) -> dict[str, Any]:
    """
    Soft-block: out-of-support requires a non-empty override reason.
    Returns fields to stamp onto the new MaintenanceCase.
    """
    order = resolve_order_for_project(session, project_id)
    support_date = order.production_support_date if order else None
    snap_date, in_support = compute_production_support(support_date)

    override = (support_override_reason or "").strip() or None
    if in_support is False and not override:
        raise HTTPException(
            status_code=400,
            detail=(
                "Production support period has ended for this order. "
                "Provide support_override_reason to open the case anyway."
            ),
        )

    return {
        "production_support_date": snap_date,
        "in_production_support": in_support,
        "support_override_reason": override if in_support is False else None,
    }


def _parse_occurrence_date(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    # date-only YYYY-MM-DD
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        d = date.fromisoformat(text)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="occurrence_date must be a valid ISO date or datetime",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _replace_occurrence_attachments(
    session: Session,
    case: MaintenanceCase,
    attachments: Optional[Sequence[dict[str, Any]]],
) -> None:
    if attachments is None:
        return
    existing = session.exec(
        select(MaintenanceOccurrenceAttachment).where(
            MaintenanceOccurrenceAttachment.case_id == case.id
        )
    ).all()
    for row in existing:
        session.delete(row)
    session.flush()

    for raw in attachments:
        display_name = (raw.get("display_name") or raw.get("name") or "").strip()
        if not display_name:
            raise HTTPException(
                status_code=400,
                detail="Each occurrence attachment requires a display_name",
            )
        file_id = raw.get("file_id")
        category = (raw.get("category") or "").strip() or None
        session.add(
            MaintenanceOccurrenceAttachment(
                case_id=int(case.id),
                display_name=display_name,
                file_id=int(file_id) if file_id is not None else None,
                category=category,
                created_at=_now(),
            )
        )


def _replace_occurrence_officers(
    session: Session,
    case: MaintenanceCase,
    officers: Optional[Sequence[dict[str, Any]]],
) -> None:
    if officers is None:
        return
    existing = session.exec(
        select(MaintenanceOccurrenceOfficer).where(
            MaintenanceOccurrenceOfficer.case_id == case.id
        )
    ).all()
    for row in existing:
        session.delete(row)
    session.flush()

    for raw in officers:
        user_id = raw.get("user_id")
        guest_name = (raw.get("guest_name") or "").strip() or None
        role_onsite = (raw.get("role_onsite") or "").strip()
        contact = (raw.get("contact") or "").strip() or None
        if not role_onsite:
            raise HTTPException(
                status_code=400,
                detail="Each occurrence officer requires role_onsite",
            )
        if user_id is None and not guest_name:
            raise HTTPException(
                status_code=400,
                detail="Each occurrence officer requires user_id or guest_name",
            )
        session.add(
            MaintenanceOccurrenceOfficer(
                case_id=int(case.id),
                user_id=int(user_id) if user_id is not None else None,
                guest_name=guest_name,
                role_onsite=role_onsite,
                contact=contact,
                created_at=_now(),
            )
        )


def record_onsite_outcome(
    session: Session,
    case: MaintenanceCase,
    *,
    actor: User,
    outcome: str,
    soft_fix_method: Optional[str] = None,
    notes: Optional[str] = None,
    occurrence_date: Any = None,
    fault_type: Optional[str] = None,
    confirmation_channel: Optional[str] = None,
    confirmation_reference: Optional[str] = None,
    attachments: Optional[Sequence[dict[str, Any]]] = None,
    officers: Optional[Sequence[dict[str, Any]]] = None,
    confirm_close_nff: bool = False,
) -> MaintenanceCase:
    """
    Persist Occurrence Report fields on the case.
    Soft-fix / NFF resolve+close is applied by the router after this call.
    """
    outcome_key = (outcome or "").strip().lower()
    try:
        outcome_enum = OnsiteOutcome(outcome_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "onsite_outcome must be soft_fix, fault_identified, "
                "inconclusive, or no_fault_found"
            ),
        ) from exc

    method_key = (soft_fix_method or "").strip().lower() or None
    if outcome_enum == OnsiteOutcome.SOFT_FIX:
        if not method_key:
            raise HTTPException(
                status_code=400,
                detail="onsite_soft_fix_method is required when outcome is soft_fix",
            )
        try:
            SoftFixMethod(method_key)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="onsite_soft_fix_method must be reboot, hard_reset, reconnect, or other",
            ) from exc
    else:
        method_key = None

    fault_key = (fault_type or "").strip().lower() or None
    channel_key = (confirmation_channel or "").strip().lower() or None
    reference = (confirmation_reference or "").strip() or None

    if outcome_enum == OnsiteOutcome.FAULT_IDENTIFIED:
        if not fault_key:
            raise HTTPException(
                status_code=400,
                detail="fault_type is required when outcome is fault_identified",
            )
        try:
            FaultType(fault_key)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"fault_type must be a valid FaultType value; got {fault_key!r}",
            ) from exc
        if not channel_key:
            raise HTTPException(
                status_code=400,
                detail="confirmation_channel is required when outcome is fault_identified",
            )
        try:
            ConfirmationChannel(channel_key)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="confirmation_channel must be email, letter, or call",
            ) from exc
        if not reference:
            raise HTTPException(
                status_code=400,
                detail="confirmation_reference is required when outcome is fault_identified",
            )
    else:
        # Soft fix / NFF / inconclusive: clear fault confirmation unless provided
        if outcome_enum != OnsiteOutcome.FAULT_IDENTIFIED:
            fault_key = fault_key  # allow optional fault_type on non-fault
            if channel_key:
                try:
                    ConfirmationChannel(channel_key)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail="confirmation_channel must be email, letter, or call",
                    ) from exc
            else:
                channel_key = None
                reference = None

    parsed_occurrence = _parse_occurrence_date(occurrence_date)

    case.onsite_outcome = outcome_enum.value
    case.onsite_soft_fix_method = method_key
    case.onsite_notes = (notes or "").strip() or None
    case.onsite_recorded_at = _now()
    case.onsite_recorded_by_id = int(actor.id) if actor.id else None
    case.occurrence_date = parsed_occurrence
    case.occurrence_fault_type = fault_key
    case.confirmation_channel = channel_key
    case.confirmation_reference = reference
    case.updated_at = _now()
    session.add(case)
    session.flush()

    _replace_occurrence_attachments(session, case, attachments)
    _replace_occurrence_officers(session, case, officers)
    session.flush()

    # confirm_close_nff is interpreted by the router; acknowledged here for API clarity
    _ = confirm_close_nff
    return case


def list_occurrence_attachments(
    session: Session, case_id: int
) -> list[MaintenanceOccurrenceAttachment]:
    return list(
        session.exec(
            select(MaintenanceOccurrenceAttachment)
            .where(MaintenanceOccurrenceAttachment.case_id == case_id)
            .order_by(MaintenanceOccurrenceAttachment.id.asc())
        ).all()
    )


def list_occurrence_officers(
    session: Session, case_id: int
) -> list[MaintenanceOccurrenceOfficer]:
    return list(
        session.exec(
            select(MaintenanceOccurrenceOfficer)
            .where(MaintenanceOccurrenceOfficer.case_id == case_id)
            .order_by(MaintenanceOccurrenceOfficer.id.asc())
        ).all()
    )


def _find_inventory_for_removed_unit(
    session: Session,
    *,
    entity_type: str,
    entity_id: int,
    part_number: Optional[str],
    serial_number: Optional[str],
) -> tuple[Optional[Inventory], Optional[InventoryInstance]]:
    # Prefer inventory rows linked to this hierarchy entity id.
    by_entity = session.exec(
        select(Inventory).where(Inventory.entity_id == entity_id)
    ).all()
    inventory: Optional[Inventory] = by_entity[0] if by_entity else None

    if inventory is None and part_number:
        inventory = session.exec(
            select(Inventory).where(
                Inventory.part_number == part_number,
                Inventory.inventory_type == str(entity_type).lower(),
            )
        ).first()

    instance: Optional[InventoryInstance] = None
    if inventory and serial_number:
        instances = session.exec(
            select(InventoryInstance).where(
                InventoryInstance.inventory_id == inventory.id
            )
        ).all()
        needle = serial_number.strip().lower()
        instance = next(
            (
                row
                for row in instances
                if (row.serial_number or "").strip().lower() == needle
                or (row.original_serial_number or "").strip().lower() == needle
            ),
            None,
        )
        if instance is None and instances:
            instance = instances[0]

    return inventory, instance


def create_returned_unit_rework(
    session: Session,
    *,
    case: MaintenanceCase,
    faulty_entity_id: int,
    entity_type: str,
    entity_id: int,
    part_number: Optional[str],
    serial_number: Optional[str],
    actor: User,
    notes: Optional[str] = None,
    initial_stage: Optional[str] = None,
) -> Optional[InventoryReworkCase]:
    """
    After a field replacement, open an IM inspect rework case for the removed unit.
    Dual-track approve path may pass initial_stage=awaiting_faulty_arrival (NR-003).
    """
    inventory, instance = _find_inventory_for_removed_unit(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        part_number=part_number,
        serial_number=serial_number,
    )
    if inventory is None:
        return None

    existing = session.exec(
        select(InventoryReworkCase).where(
            InventoryReworkCase.maintenance_case_id == case.id,
            InventoryReworkCase.faulty_entity_id == faulty_entity_id,
            InventoryReworkCase.status == ReworkCaseStatus.OPEN.value,
        )
    ).first()
    if existing:
        stage_key = (initial_stage or "").strip().lower() or None
        if stage_key and existing.stage != stage_key:
            existing.stage = stage_key
            existing.updated_at = _now()
            session.add(existing)
            session.flush()
        return existing

    stage_value = (initial_stage or "").strip().lower() or ReworkStage.RETURNED.value
    now = _now()
    rework = InventoryReworkCase(
        project_id=case.project_id,
        target_entity_type=str(entity_type).lower(),
        target_entity_id=int(entity_id),
        inventory_id=int(inventory.id),
        original_instance_id=int(instance.id) if instance and instance.id else None,
        current_instance_id=int(instance.id) if instance and instance.id else None,
        status=ReworkCaseStatus.OPEN.value,
        stage=stage_value,
        attempt_count=1,
        opened_at=now,
        opened_by_id=int(actor.id) if actor.id else None,
        notes=notes
        or (
            "Awaiting faulty return (dual-track)"
            if stage_value == ReworkStage.AWAITING_FAULTY_ARRIVAL.value
            else "Returned from field replacement (maintenance case)"
        ),
        maintenance_case_id=case.id,
        faulty_entity_id=faulty_entity_id,
        investigating_pd_id=case.reported_by,
        created_at=now,
        updated_at=now,
    )
    session.add(rework)

    # Move unit toward inspection when we can touch instance/catalog status.
    try:
        if instance and hasattr(instance, "status_id"):
            pass
        if inventory:
            # Best-effort: mark catalog attention via notes only if status helpers unavailable.
            inventory.updated_at = now
            session.add(inventory)
    except Exception:
        pass

    session.flush()
    return rework


def list_case_returned_units(
    session: Session, case_id: int
) -> list[InventoryReworkCase]:
    return list(
        session.exec(
            select(InventoryReworkCase)
            .where(InventoryReworkCase.maintenance_case_id == case_id)
            .order_by(InventoryReworkCase.id.desc())
        ).all()
    )


def assign_investigating_pd(
    session: Session,
    rework_id: int,
    *,
    pd_user_id: int,
) -> InventoryReworkCase:
    rework = session.get(InventoryReworkCase, rework_id)
    if not rework:
        raise HTTPException(status_code=404, detail="Returned unit / rework case not found")
    rework.investigating_pd_id = pd_user_id
    rework.updated_at = _now()
    session.add(rework)
    session.flush()
    return rework


def warranty_active(expires_at: Optional[datetime]) -> bool:
    if not expires_at:
        return False
    exp = expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp >= _now()


def create_or_require_warranty_claim(
    session: Session,
    *,
    rework: InventoryReworkCase,
    actor: User,
    force_discard: bool = False,
    notes: Optional[str] = None,
) -> tuple[Optional[OemWarrantyClaim], str]:
    """
    After not-repairable / scrapped disposition:
    - active warranty → open claim (unless force_discard)
    - expired/none → discard path (no claim)
    Returns (claim_or_none, action) where action is 'claim'|'discard'|'existing_claim'
    """
    inventory = session.get(Inventory, rework.inventory_id) if rework.inventory_id else None
    instance = (
        session.get(InventoryInstance, rework.current_instance_id)
        if rework.current_instance_id
        else None
    )
    expires = None
    if instance and getattr(instance, "warranty_expires_at", None):
        expires = instance.warranty_expires_at
    elif inventory and getattr(inventory, "warranty_expires_at", None):
        expires = inventory.warranty_expires_at

    oem_name = None
    if inventory and getattr(inventory, "oem_name", None):
        oem_name = inventory.oem_name

    existing = session.exec(
        select(OemWarrantyClaim).where(
            OemWarrantyClaim.rework_case_id == rework.id,
            OemWarrantyClaim.status.in_(  # type: ignore[attr-defined]
                (
                    OemWarrantyClaimStatus.OPEN.value,
                    OemWarrantyClaimStatus.SUBMITTED.value,
                )
            ),
        )
    ).first()
    if existing:
        return existing, "existing_claim"

    if warranty_active(expires) and not force_discard:
        claim = OemWarrantyClaim(
            maintenance_case_id=rework.maintenance_case_id,
            faulty_entity_id=rework.faulty_entity_id,
            inventory_id=rework.inventory_id,
            inventory_instance_id=rework.current_instance_id,
            rework_case_id=rework.id,
            oem_name=oem_name,
            part_number=inventory.part_number if inventory else None,
            serial_number=instance.serial_number if instance else None,
            warranty_expires_at=expires,
            status=OemWarrantyClaimStatus.OPEN.value,
            notes=notes,
            created_by_id=int(actor.id) if actor.id else None,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(claim)
        session.flush()
        return claim, "claim"

    return None, "discard"
