from __future__ import annotations

from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.base import EntityType, ResolutionType
from app.models.helpers import _ENTITY_MODEL_MAP
from app.models.tables import ConfigurationHistory, Entity, MaintenanceCase, User
from app.schemas.Maintennance import ConfigurationHistoryCreate

ENTITY_TYPE_LABELS = {
    EntityType.SYSTEM: "System",
    EntityType.SUBSYSTEM: "Subsystem",
    EntityType.MODULE: "Module",
    EntityType.UNIT: "Unit",
    EntityType.COMPONENT: "Component",
    EntityType.PROJECT: "Project",
    EntityType.ORDER: "Order",
    EntityType.CUSTOMER: "Customer",
}


def _entity_type_candidates(entity_type: str | EntityType) -> set[str]:
    raw = entity_type.value if isinstance(entity_type, EntityType) else str(entity_type)
    lowered = raw.lower()
    candidates = {raw, lowered, raw.capitalize()}
    try:
        enum_type = EntityType(lowered)
        candidates.add(enum_type.value)
        candidates.add(ENTITY_TYPE_LABELS[enum_type])
    except ValueError:
        pass
    return candidates


def resolve_generic_entity(
    session: Session,
    entity_type: str | EntityType,
    entity_pk: int,
) -> Optional[Entity]:
    for candidate in _entity_type_candidates(entity_type):
        match = session.exec(
            select(Entity).where(
                Entity.entity_type == candidate,
                Entity.entity_pk == entity_pk,
            )
        ).first()
        if match:
            return match
    return None


def get_hardware_part_serial(
    session: Session,
    entity_type: str | EntityType,
    entity_pk: int,
) -> Tuple[Optional[str], Optional[str]]:
    if isinstance(entity_type, EntityType):
        map_key: EntityType | str = entity_type
    else:
        try:
            map_key = EntityType(str(entity_type).lower())
        except ValueError:
            return None, None

    entry = _ENTITY_MODEL_MAP.get(map_key)
    if not entry:
        return None, None

    model = entry[0]
    row = session.get(model, entity_pk)
    if not row:
        return None, None

    return getattr(row, "part_number", None), getattr(row, "serial_number", None)


def validate_configuration_history_refs(
    session: Session,
    payload: ConfigurationHistoryCreate,
) -> None:
    entity = session.get(Entity, payload.entity_id)
    if not entity:
        raise HTTPException(
            status_code=404,
            detail=f"Entity id {payload.entity_id} not found for configuration history.",
        )

    performer = session.get(User, payload.performed_by)
    if not performer:
        raise HTTPException(
            status_code=404,
            detail=f"User id {payload.performed_by} not found for performed_by.",
        )

    if payload.maintenance_case_id is not None:
        case = session.get(MaintenanceCase, payload.maintenance_case_id)
        if not case:
            raise HTTPException(
                status_code=404,
                detail=f"Maintenance case id {payload.maintenance_case_id} not found.",
            )


def create_configuration_history_record(
    session: Session,
    payload: ConfigurationHistoryCreate,
) -> ConfigurationHistory:
    validate_configuration_history_refs(session, payload)

    history = ConfigurationHistory.model_validate(payload)
    session.add(history)

    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Could not create configuration history: {exc.orig}",
        ) from exc

    session.refresh(history)
    return history


def create_configuration_history_for_resolve(
    session: Session,
    *,
    entity_type: EntityType,
    entity_pk: int,
    maintenance_case_id: int,
    performed_by: int,
    resolution_type: ResolutionType,
    faulty_entity_id: Optional[int] = None,
    fault_type=None,
    old_part_number: Optional[str] = None,
    new_part_number: Optional[str] = None,
    old_serial_number: Optional[str] = None,
    new_serial_number: Optional[str] = None,
    remarks: Optional[str] = None,
) -> Optional[ConfigurationHistory]:
    if faulty_entity_id is not None:
        existing = session.exec(
            select(ConfigurationHistory).where(
                ConfigurationHistory.faulty_entity_id == faulty_entity_id
            )
        ).first()
        if existing:
            return existing

    generic_entity = resolve_generic_entity(session, entity_type, entity_pk)
    if not generic_entity:
        return None

    if old_part_number is None and old_serial_number is None:
        old_part_number, old_serial_number = get_hardware_part_serial(
            session, entity_type, entity_pk
        )

    payload = ConfigurationHistoryCreate(
        entity_id=generic_entity.id,
        maintenance_case_id=maintenance_case_id,
        performed_by=performed_by,
        faulty_entity_id=faulty_entity_id,
        fault_type=fault_type,
        resolution_type=resolution_type,
        old_part_number=old_part_number,
        new_part_number=new_part_number,
        old_serial_number=old_serial_number,
        new_serial_number=new_serial_number,
        remarks=remarks,
    )

    return create_configuration_history_record(session, payload)
