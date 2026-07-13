"""Admin one-shot hierarchy replacement — full maintenance case lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.base import (
    ActionOutcome,
    ActionType,
    CaseStatus,
    EntityType,
    FaultType,
    FaultyEntityStatus,
    ResolutionType,
)
from app.models.helpers import (
    _ENTITY_MODEL_MAP,
    _PARENT_MAP,
    _collect_descendants,
    _generate_case_number,
    _get_label,
)
from app.models.tables import (
    FaultyEntity,
    Inventory,
    MaintenanceAction,
    MaintenanceCase,
    User,
)
from app.services.configuration_history import (
    create_configuration_history_for_resolve,
    get_hardware_part_serial,
)


def _normalize_entity_type(entity_type: EntityType | str) -> EntityType:
    if isinstance(entity_type, EntityType):
        return entity_type
    return EntityType(str(entity_type).lower())


def _get_entity_row(session: Session, entity_type: EntityType, entity_id: int):
    entry = _ENTITY_MODEL_MAP.get(entity_type)
    if not entry:
        raise HTTPException(status_code=400, detail=f"Unsupported entity type: {entity_type}")
    model_cls = entry[0]
    row = session.get(model_cls, entity_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"{entity_type.value} {entity_id} not found")
    return row


def _entity_belongs_to_project(session: Session, entity_type: EntityType, entity_id: int, project_id: int) -> bool:
    """Walk up to system and verify project_id."""
    current_type = entity_type
    current_id = entity_id

    while True:
        if current_type == EntityType.SYSTEM:
            row = session.get(_ENTITY_MODEL_MAP[EntityType.SYSTEM][0], current_id)
            return row is not None and getattr(row, "project_id", None) == project_id

        if current_type not in _PARENT_MAP:
            return False

        parent_type, model_cls, fk_attr = _PARENT_MAP[current_type]
        row = session.get(model_cls, current_id)
        if not row:
            return False
        parent_id = getattr(row, fk_attr, None)
        if parent_id is None:
            return False
        current_type = parent_type
        current_id = parent_id


def _siblings_same_type(session: Session, entity_type: EntityType, entity_id: int):
    if entity_type not in _PARENT_MAP:
        target = _get_entity_row(session, entity_type, entity_id)
        return [target]

    _, model_cls, fk_attr = _PARENT_MAP[entity_type]
    target = session.get(model_cls, entity_id)
    if not target:
        return []

    parent_id = getattr(target, fk_attr, None)
    if parent_id is None:
        return [target]

    return list(
        session.exec(
            select(model_cls).where(
                getattr(model_cls, fk_attr) == parent_id,
                model_cls.is_current_install == True,  # noqa: E712
            )
        ).all()
    )


def _log_action(
    session: Session,
    *,
    faulty_entity_id: int,
    action_type: ActionType,
    outcome: ActionOutcome,
    performed_by: int,
    notes: Optional[str] = None,
) -> None:
    session.add(
        MaintenanceAction(
            faulty_entity_id=faulty_entity_id,
            action_type=action_type,
            outcome=outcome,
            performed_by=performed_by,
            performed_at=datetime.now(timezone.utc),
            notes=notes,
        )
    )
    session.flush()


def _update_hardware_part_serial(
    session: Session,
    entity_type: EntityType,
    entity_id: int,
    new_part_number: str,
    new_serial_number: Optional[str],
    *,
    performed_by_id: int,
    inventory: Optional[Inventory] = None,
    inventory_instance_id: Optional[int] = None,
):
    from app.services.entity_replacement_service import (
        apply_inventory_to_replacement,
        create_replacement_entity,
    )

    row = _get_entity_row(session, entity_type, entity_id)
    config_item = new_part_number
    picture_url = None
    installation_date = None
    installed_by_id = performed_by_id

    if inventory is not None:
        inv_part, inv_serial, inv_config, inv_picture = apply_inventory_to_replacement(
            session, inventory, inventory_instance_id
        )
        new_part_number = inv_part or new_part_number
        new_serial_number = inv_serial or new_serial_number
        config_item = inv_config or new_part_number
        picture_url = inv_picture
        if inventory.installation_date:
            installation_date = inventory.installation_date
        if inventory.installed_by_id:
            installed_by_id = inventory.installed_by_id

    return create_replacement_entity(
        session,
        entity_type=entity_type,
        old_row=row,
        new_part_number=new_part_number,
        new_serial_number=new_serial_number,
        new_configuration_item=config_item,
        performed_by_id=performed_by_id,
        installation_date=installation_date,
        installed_by_id=installed_by_id,
        picture_url=picture_url,
    )


def admin_hierarchy_replace(
    session: Session,
    *,
    project_id: int,
    entity_type: EntityType | str,
    entity_id: int,
    new_part_number: str,
    performed_by: User,
    new_serial_number: Optional[str] = None,
    notes: Optional[str] = None,
    inventory_item_id: Optional[int] = None,
    inventory_instance_id: Optional[int] = None,
) -> dict:
    entity_type = _normalize_entity_type(entity_type)

    if not _entity_belongs_to_project(session, entity_type, entity_id, project_id):
        raise HTTPException(
            status_code=400,
            detail="Entity does not belong to the specified project.",
        )

    from app.services.entity_replacement_service import resolve_current_install_row

    try:
        current_row = resolve_current_install_row(session, entity_type, entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    current_entity_id = current_row.id

    target_info = _get_label(session, entity_type.value, current_entity_id) or {}
    target_name = target_info.get("entity_name") or f"{entity_type.value} #{current_entity_id}"
    old_part, old_serial = get_hardware_part_serial(session, entity_type, current_entity_id)

    case = MaintenanceCase(
        case_number=_generate_case_number(session),
        project_id=project_id,
        description=notes or f"Admin hierarchy replacement — {target_name}",
        status=CaseStatus.OPEN,
        entity_type=entity_type.value,
        entity_id=current_entity_id,
        part_number=old_part,
        reported_by=performed_by.id,
    )
    session.add(case)
    session.flush()

    target_fe = FaultyEntity(
        case_id=case.id,
        entity_type=entity_type,
        entity_id=current_entity_id,
        entity_name=target_name,
        part_number=old_part,
        serial_number=old_serial,
        fault_type=FaultType.HARDWARE,
        fault_description=notes or f"Admin replacement for {target_name}",
        status=FaultyEntityStatus.CONFIRMED_FAULTY,
        identified_by=performed_by.id,
    )
    session.add(target_fe)
    session.flush()

    siblings = _siblings_same_type(session, entity_type, current_entity_id)
    for sibling in siblings:
        if sibling.id == current_entity_id:
            continue
        sibling_info = _get_label(session, entity_type.value, sibling.id) or {}
        session.add(
            FaultyEntity(
                case_id=case.id,
                entity_type=entity_type,
                entity_id=sibling.id,
                entity_name=sibling_info.get("entity_name"),
                part_number=sibling_info.get("part_number"),
                serial_number=sibling_info.get("serial_number"),
                fault_type=FaultType.HARDWARE,
                status=FaultyEntityStatus.NO_FAULT_FOUND,
                resolution_type=ResolutionType.NO_FAULT_FOUND,
                identified_by=performed_by.id,
                parent_faulty_entity_id=target_fe.id,
            )
        )

    descendants = _collect_descendants(session, entity_type.value, current_entity_id)
    for desc in descendants:
        desc_type = _normalize_entity_type(desc.entity_type)
        session.add(
            FaultyEntity(
                case_id=case.id,
                entity_type=desc_type,
                entity_id=desc.entity_id,
                entity_name=desc.entity_name,
                part_number=desc.entity_PartNumber,
                serial_number=desc.entity_SerialNumber,
                fault_type=FaultType.HARDWARE,
                status=FaultyEntityStatus.NO_FAULT_FOUND,
                resolution_type=ResolutionType.NO_FAULT_FOUND,
                identified_by=performed_by.id,
                parent_faulty_entity_id=target_fe.id,
            )
        )

    session.flush()

    case.status = CaseStatus.UNDER_INSPECTION
    session.add(case)
    _log_action(
        session,
        faulty_entity_id=target_fe.id,
        action_type=ActionType.INSPECTION,
        outcome=ActionOutcome.PASS,
        performed_by=performed_by.id,
        notes="Admin auto: investigation started",
    )

    case.status = CaseStatus.UNDER_REPAIR
    session.add(case)
    _log_action(
        session,
        faulty_entity_id=target_fe.id,
        action_type=ActionType.REPAIR,
        outcome=ActionOutcome.PASS,
        performed_by=performed_by.id,
        notes="Admin auto: repair in progress",
    )

    _log_action(
        session,
        faulty_entity_id=target_fe.id,
        action_type=ActionType.TESTING,
        outcome=ActionOutcome.PASS,
        performed_by=performed_by.id,
        notes="Admin auto: verification passed",
    )

    target_fe.status = FaultyEntityStatus.RESOLVED
    target_fe.resolution_type = ResolutionType.REPLACED
    target_fe.resolved_at = datetime.now(timezone.utc)
    session.add(target_fe)

    inventory = None
    if inventory_item_id is not None:
        inventory = session.get(Inventory, inventory_item_id)

    resolved_part_number = new_part_number
    resolved_serial_number = new_serial_number
    if inventory is not None:
        from app.services.entity_replacement_service import apply_inventory_to_replacement

        inv_part, inv_serial, _, _ = apply_inventory_to_replacement(
            session, inventory, inventory_instance_id
        )
        resolved_part_number = inv_part or new_part_number
        resolved_serial_number = inv_serial or new_serial_number

    history = create_configuration_history_for_resolve(
        session,
        entity_type=entity_type,
        entity_pk=current_entity_id,
        maintenance_case_id=case.id,
        performed_by=performed_by.id,
        faulty_entity_id=target_fe.id,
        resolution_type=ResolutionType.REPLACED,
        fault_type=FaultType.HARDWARE,
        old_part_number=old_part,
        new_part_number=resolved_part_number,
        old_serial_number=old_serial,
        new_serial_number=resolved_serial_number,
        remarks=notes,
    )

    new_row = _update_hardware_part_serial(
        session,
        entity_type,
        current_entity_id,
        resolved_part_number,
        resolved_serial_number,
        performed_by_id=performed_by.id,
        inventory=inventory,
        inventory_instance_id=inventory_instance_id,
    )

    if inventory is not None:
        from app.services.inventory_service import consume_inventory_unit

        consume_inventory_unit(session, inventory, instance_id=inventory_instance_id)

    # Point configuration history at the slot's original generic entity for continuity.
    if history and new_row:
        from app.services.entity_replacement_service import resolve_slot_generic_entity_id

        slot_entity_id = resolve_slot_generic_entity_id(session, entity_type, new_row.id)
        if slot_entity_id and history.entity_id != slot_entity_id:
            history.entity_id = slot_entity_id
            session.add(history)

    _log_action(
        session,
        faulty_entity_id=target_fe.id,
        action_type=ActionType.REPLACEMENT,
        outcome=ActionOutcome.PASS,
        performed_by=performed_by.id,
        notes=f"Replaced {old_part or 'unknown'} with {resolved_part_number}",
    )

    new_part_number = new_row.part_number or resolved_part_number
    new_serial_number = new_row.serial_number or resolved_serial_number

    case.status = CaseStatus.RESOLVED
    case.resolution_notes = notes or f"Admin replacement: {old_part} → {new_part_number}"
    session.add(case)

    case.status = CaseStatus.CLOSED
    case.closed_at = datetime.now(timezone.utc)
    session.add(case)

    session.commit()
    session.refresh(case)
    session.refresh(target_fe)

    config_history_id = history.id if history else None

    return {
        "case_id": case.id,
        "faulty_entity_id": target_fe.id,
        "configuration_history_id": config_history_id,
        "old_part_number": old_part,
        "new_part_number": new_part_number,
        "new_entity_id": new_row.id if new_row else current_entity_id,
        "old_entity_id": current_entity_id,
    }
