"""Entity replacement versioning — preserve originals, tag current install."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from sqlmodel import Session, select

from app.config.entities import ENTITY_CONFIG
from app.models.base import EntityType
from app.models.helpers import _CHILD_MAP, _ENTITY_MODEL_MAP, _PARENT_MAP
from app.models.tables import Inventory, InventoryInstance
from app.services.configuration_history import resolve_generic_entity
from app.services.create_entity import New_entity


def _normalize_entity_type(entity_type: EntityType | str) -> EntityType:
    if isinstance(entity_type, EntityType):
        return entity_type
    return EntityType(str(entity_type).lower())


def _model_for(entity_type: EntityType):
    entry = _ENTITY_MODEL_MAP.get(entity_type)
    if not entry:
        raise ValueError(f"Unsupported entity type: {entity_type}")
    return entry[0]


def is_current_install_row(row: Any) -> bool:
    return getattr(row, "is_current_install", True) is not False


def filter_current_installs(rows: List[Any]) -> List[Any]:
    return [row for row in rows if is_current_install_row(row)]


def resolve_root_entity_id(row: Any) -> int:
    root_id = getattr(row, "root_entity_id", None)
    return root_id if root_id is not None else row.id


def ensure_root_entity_id(session: Session, row: Any) -> int:
    root_id = getattr(row, "root_entity_id", None)
    if root_id is None:
        row.root_entity_id = row.id
        session.add(row)
        session.flush()
        return row.id
    return root_id


def get_replacement_chain(
    session: Session,
    entity_type: EntityType | str,
    entity_id: int,
) -> List[Any]:
    """All versions for a slot, ordered by replacement_sequence ascending."""
    entity_type = _normalize_entity_type(entity_type)
    model_cls = _model_for(entity_type)
    target = session.get(model_cls, entity_id)
    if not target:
        return []

    root_id = resolve_root_entity_id(target)
    return list(
        session.exec(
            select(model_cls)
            .where(model_cls.root_entity_id == root_id)
            .order_by(model_cls.replacement_sequence)
        ).all()
    )


def resolve_slot_generic_entity_id(
    session: Session,
    entity_type: EntityType | str,
    entity_pk: int,
) -> Optional[int]:
    """Generic Entity.id for the original slot (used for configuration history)."""
    entity_type = _normalize_entity_type(entity_type)
    model_cls = _model_for(entity_type)
    row = session.get(model_cls, entity_pk)
    if not row:
        return None

    root_id = resolve_root_entity_id(row)
    chain = get_replacement_chain(session, entity_type, root_id)
    original = chain[0] if chain else row
    generic = resolve_generic_entity(session, entity_type, original.id)
    return generic.id if generic else None


def _copy_scalar_fields(source: Any, *, exclude: set[str]) -> dict:
    data: dict = {}
    for key, value in source.model_dump().items():
        if key in exclude:
            continue
        data[key] = value
    return data


def _reparent_direct_children(
    session: Session,
    entity_type: EntityType,
    old_entity_id: int,
    new_entity_id: int,
) -> None:
    if entity_type not in _CHILD_MAP:
        return

    child_type, child_model, fk_attr = _CHILD_MAP[entity_type.value]
    children = session.exec(
        select(child_model).where(getattr(child_model, fk_attr) == old_entity_id)
    ).all()
    for child in children:
        setattr(child, fk_attr, new_entity_id)
        session.add(child)


def _inventory_identity(
    session: Session,
    inventory: Inventory,
    instance_id: Optional[int],
) -> Tuple[str, Optional[str], Optional[str]]:
    part_number = inventory.part_number or inventory.name
    serial_number: Optional[str] = None
    configuration_item = inventory.configuration_item

    if instance_id is not None:
        instance = session.get(InventoryInstance, instance_id)
        if instance and instance.inventory_id == inventory.id:
            if instance.serial_number:
                serial_number = instance.serial_number
            if instance.configuration_item:
                configuration_item = instance.configuration_item
            if instance.original_part_number and not part_number:
                part_number = instance.original_part_number
            if instance.original_serial_number and not serial_number:
                serial_number = instance.original_serial_number

    if inventory.inventory_type == "component":
        serial_number = serial_number or inventory.serial_number

    return part_number or inventory.name, serial_number, configuration_item


def create_replacement_entity(
    session: Session,
    *,
    entity_type: EntityType,
    old_row: Any,
    new_part_number: str,
    new_serial_number: Optional[str],
    new_configuration_item: Optional[str],
    performed_by_id: int,
    installation_date: Optional[datetime] = None,
    installed_by_id: Optional[int] = None,
    picture_url: Optional[str] = None,
) -> Any:
    """Mark old row superseded and create a new current-install row in the same slot."""
    model_cls = _model_for(entity_type)
    now = datetime.now(timezone.utc)

    root_id = ensure_root_entity_id(session, old_row)
    if old_row.original_part_number is None and old_row.part_number:
        old_row.original_part_number = old_row.part_number
    if old_row.original_serial_number is None and old_row.serial_number:
        old_row.original_serial_number = old_row.serial_number

    old_row.is_current_install = False
    old_row.replaced_at = now
    session.add(old_row)

    exclude = {
        "id",
        "created_at",
        "is_current_install",
        "root_entity_id",
        "replaced_entity_id",
        "replacement_sequence",
        "replaced_at",
        "part_number",
        "serial_number",
        "configuration_item",
        "installation_date",
        "installed_by_id",
        "picture_url",
    }
    if entity_type == EntityType.COMPONENT:
        exclude.discard("sku")

    payload = _copy_scalar_fields(old_row, exclude=exclude)
    payload.update(
        {
            "part_number": new_part_number,
            "serial_number": new_serial_number,
            "configuration_item": new_configuration_item or new_part_number,
            "is_current_install": True,
            "root_entity_id": root_id,
            "replaced_entity_id": old_row.id,
            "replacement_sequence": (old_row.replacement_sequence or 0) + 1,
            "replaced_at": None,
            "original_part_number": old_row.original_part_number,
            "original_serial_number": old_row.original_serial_number,
            "installation_date": installation_date or now,
            "installed_by_id": installed_by_id or performed_by_id,
            "picture_url": picture_url if picture_url is not None else old_row.picture_url,
        }
    )

    new_row = model_cls(**payload)
    session.add(new_row)
    session.flush()

    display_name = ENTITY_CONFIG.get(entity_type.value, {}).get("display_name", entity_type.value)
    New_entity(
        session=session,
        entity=new_row,
        entity_name=display_name,
        changed_by_user=performed_by_id,
    )

    _reparent_direct_children(session, entity_type, old_row.id, new_row.id)
    session.flush()
    return new_row


def apply_inventory_to_replacement(
    session: Session,
    inventory: Inventory,
    instance_id: Optional[int],
) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    part_number, serial_number, configuration_item = _inventory_identity(
        session, inventory, instance_id
    )
    picture_url = inventory.picture_url
    if instance_id is not None:
        instance = session.get(InventoryInstance, instance_id)
        if instance and instance.picture_url:
            picture_url = instance.picture_url
    return part_number, serial_number, configuration_item, picture_url
