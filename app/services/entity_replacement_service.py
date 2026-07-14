"""Entity replacement versioning — preserve originals, tag current install."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from sqlmodel import Session, select

from app.config.entities import ENTITY_CONFIG
from app.models.base import EntityType
from app.models.helpers import _CHILD_MAP, _ENTITY_MODEL_MAP
from app.models.tables import Inventory, InventoryInstance, Status
from app.services.configuration_history import resolve_generic_entity
from app.services.create_entity import New_entity

_STATUS_TYPE_BY_ENTITY = {
    EntityType.SYSTEM: "systems",
    EntityType.SUBSYSTEM: "subsystems",
    EntityType.MODULE: "modules",
    EntityType.UNIT: "units",
    EntityType.COMPONENT: "components",
}


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


def resolve_current_install_row(
    session: Session,
    entity_type: EntityType | str,
    entity_id: int,
) -> Any:
    """Return the active install for a slot; any chain member id may be passed."""
    entity_type = _normalize_entity_type(entity_type)
    model_cls = _model_for(entity_type)
    target = session.get(model_cls, entity_id)
    if not target:
        raise ValueError(f"{entity_type.value} {entity_id} not found")

    chain = get_replacement_chain(session, entity_type, entity_id)
    if not chain:
        return target

    current_rows = [row for row in chain if is_current_install_row(row)]
    if not current_rows:
        return chain[-1]

    return max(
        current_rows,
        key=lambda row: (row.replacement_sequence or 0, row.id),
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


def _clone_descendant_tree(
    session: Session,
    entity_type: EntityType,
    old_entity_id: int,
    new_entity_id: int,
    performed_by_id: int,
) -> int:
    """Copy current-install descendants from ``old_entity_id`` onto ``new_entity_id``.

    Originals stay under the superseded parent for build history. New rows are
    fresh install slots (not chained to the source children's replacement history).
    Avoids reparenting, which can delete children under SQLAlchemy delete-orphan.
    """
    if entity_type not in _CHILD_MAP:
        return 0

    child_type_raw, child_model, fk_attr = _CHILD_MAP[entity_type.value]
    child_type = _normalize_entity_type(child_type_raw)

    children = list(
        session.exec(
            select(child_model).where(
                getattr(child_model, fk_attr) == old_entity_id,
                child_model.is_current_install == True,  # noqa: E712
            )
        ).all()
    )
    if not children:
        return 0

    display_name = ENTITY_CONFIG.get(child_type.value, {}).get(
        "display_name", child_type.value
    )
    cloned = 0

    for child in children:
        exclude = {
            "id",
            "created_at",
            "is_current_install",
            "root_entity_id",
            "replaced_entity_id",
            "replacement_sequence",
            "replaced_at",
            fk_attr,
        }
        payload = _copy_scalar_fields(child, exclude=exclude)
        payload.update(
            {
                fk_attr: new_entity_id,
                "is_current_install": True,
                "root_entity_id": None,
                "replaced_entity_id": None,
                "replacement_sequence": 0,
                "replaced_at": None,
            }
        )

        new_child = child_model(**payload)
        session.add(new_child)
        session.flush()

        new_child.root_entity_id = new_child.id
        session.add(new_child)

        New_entity(
            session=session,
            entity=new_child,
            entity_name=display_name,
            changed_by_user=performed_by_id,
        )

        cloned += 1
        cloned += _clone_descendant_tree(
            session,
            child_type,
            child.id,
            new_child.id,
            performed_by_id,
        )

    return cloned


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


def _default_status_id(session: Session, entity_type: EntityType) -> Optional[int]:
    status_type = _STATUS_TYPE_BY_ENTITY.get(entity_type)
    if not status_type:
        return None
    row = session.exec(
        select(Status).where(Status.status_type == status_type).order_by(Status.id)
    ).first()
    return row.id if row else None


def _create_fielded_child_from_inventory(
    session: Session,
    *,
    child_type: EntityType,
    parent_entity_id: int,
    fk_attr: str,
    name: str,
    child_inventory: Inventory,
    part_number: str,
    serial_number: Optional[str],
    configuration_item: Optional[str],
    picture_url: Optional[str],
    performed_by_id: int,
    installation_date: Optional[datetime] = None,
    installed_by_id: Optional[int] = None,
) -> Any:
    """Create a new fielded child under ``parent_entity_id`` from inventory stock."""
    model_cls = _model_for(child_type)
    now = datetime.now(timezone.utc)
    status_id = child_inventory.status_id or _default_status_id(session, child_type)

    payload: dict[str, Any] = {
        "name": name,
        "description": getattr(child_inventory, "description", None),
        fk_attr: parent_entity_id,
        "status_id": status_id,
        "part_number": part_number,
        "serial_number": serial_number,
        "configuration_item": configuration_item or part_number,
        "is_current_install": True,
        "root_entity_id": None,
        "replaced_entity_id": None,
        "replacement_sequence": 0,
        "replaced_at": None,
        "installation_date": installation_date
        or getattr(child_inventory, "installation_date", None)
        or now,
        "installed_by_id": installed_by_id
        or getattr(child_inventory, "installed_by_id", None)
        or performed_by_id,
        "picture_url": picture_url or child_inventory.picture_url,
        "original_part_number": part_number,
        "original_serial_number": serial_number,
    }
    if child_type == EntityType.COMPONENT:
        payload["sku"] = getattr(child_inventory, "sku", None)

    new_child = model_cls(**payload)
    session.add(new_child)
    session.flush()

    new_child.root_entity_id = new_child.id
    session.add(new_child)

    display_name = ENTITY_CONFIG.get(child_type.value, {}).get(
        "display_name", child_type.value
    )
    New_entity(
        session=session,
        entity=new_child,
        entity_name=display_name,
        changed_by_user=performed_by_id,
    )
    return new_child


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
    copy_children: bool = True,
) -> Any:
    """Mark old row superseded and create a new current-install row in the same slot.

    When ``copy_children`` is True, current-install children of the old row are
    cloned under the new row (originals stay on the superseded parent). Skip this
    when inventory composition will install children instead.
    """
    model_cls = _model_for(entity_type)
    now = datetime.now(timezone.utc)

    old_row = resolve_current_install_row(session, entity_type, old_row.id)
    root_id = ensure_root_entity_id(session, old_row)
    chain = get_replacement_chain(session, entity_type, root_id)

    for row in chain:
        if row.id != old_row.id and is_current_install_row(row):
            row.is_current_install = False
            row.replaced_at = now
            session.add(row)

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

    next_sequence = max((row.replacement_sequence or 0) for row in chain) + 1

    payload = _copy_scalar_fields(old_row, exclude=exclude)
    payload.update(
        {
            "part_number": new_part_number,
            "serial_number": new_serial_number,
            "configuration_item": new_configuration_item or new_part_number,
            "is_current_install": True,
            "root_entity_id": root_id,
            "replaced_entity_id": old_row.id,
            "replacement_sequence": next_sequence,
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

    if copy_children:
        _clone_descendant_tree(
            session,
            entity_type,
            old_row.id,
            new_row.id,
            performed_by_id,
        )
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


def resolve_inventory_instance_serial(
    session: Session,
    inventory: Inventory,
    instance_id: Optional[int],
) -> Optional[str]:
    """Stable serial for inventory composition lookup (survives instance delete)."""
    if instance_id is not None:
        instance = session.get(InventoryInstance, instance_id)
        if instance and instance.inventory_id == inventory.id:
            serial = (
                instance.original_serial_number or instance.serial_number or ""
            ).strip()
            if serial:
                return serial
    serial = (getattr(inventory, "original_serial_number", None) or inventory.serial_number or "").strip()
    return serial or None


def _is_composed_child_link(link: Any) -> bool:
    """True when child stock was removed at compose time (do not consume again)."""
    if getattr(link, "stock_consumed", False):
        return True
    return (
        getattr(link, "child_instance_id", None) is None
        and bool((getattr(link, "child_instance_serial", None) or "").strip())
    )


def replace_children_from_inventory_composition(
    session: Session,
    *,
    parent_entity_type: EntityType | str,
    parent_entity_id: int,
    parent_inventory_id: int,
    performed_by_id: int,
    parent_instance_id: Optional[int] = None,
    parent_instance_serial: Optional[str] = None,
    prefetched_links: Optional[List[Any]] = None,
) -> int:
    """Apply inventory composition under ``parent_entity_id``.

    Each ``InventoryChildLink`` is matched to a current-install child by
    ``child_category_name`` ↔ entity ``name``. Matches are versioned; missing
    slots are created (install parity). Nested links apply recursively.
    Already-composed child stock is not consumed again.
    """
    from app.services.inventory_service import consume_inventory_unit, list_inventory_child_links

    parent_entity_type = _normalize_entity_type(parent_entity_type)
    if parent_entity_type == EntityType.COMPONENT or parent_entity_type not in _CHILD_MAP:
        return 0

    links = prefetched_links
    if links is None:
        links = list_inventory_child_links(
            session,
            parent_inventory_id=parent_inventory_id,
            parent_instance_id=parent_instance_id,
            parent_instance_serial=parent_instance_serial,
        )
    if not links:
        return 0

    child_type_raw, child_model, fk_attr = _CHILD_MAP[parent_entity_type.value]
    child_type = _normalize_entity_type(child_type_raw)

    fielded_children = list(
        session.exec(
            select(child_model).where(
                getattr(child_model, fk_attr) == parent_entity_id,
                child_model.is_current_install == True,  # noqa: E712
            )
        ).all()
    )
    used_ids: set[int] = set()
    applied = 0

    for link in links:
        child_inventory = session.get(Inventory, link.child_inventory_id)
        if not child_inventory:
            continue

        category_name = (
            (link.child_category_name or "").strip()
            or (child_inventory.name or "").strip()
        )
        if not category_name:
            continue
        category_key = category_name.lower()

        match = None
        for child in fielded_children:
            if child.id in used_ids:
                continue
            if (getattr(child, "name", None) or "").strip().lower() == category_key:
                match = child
                break

        composed = _is_composed_child_link(link)
        instance_id = None if composed else link.child_instance_id
        composed_serial = (link.child_instance_serial or "").strip() or None
        # Capture serial before any consume — instance FKs on nested links are cleared.
        nested_serial = composed_serial or resolve_inventory_instance_serial(
            session, child_inventory, instance_id
        )

        inv_part, inv_serial, inv_config, inv_picture = apply_inventory_to_replacement(
            session, child_inventory, instance_id
        )
        if nested_serial and (composed or not inv_serial):
            inv_serial = nested_serial

        new_part = inv_part or child_inventory.part_number or child_inventory.name

        if match is not None:
            used_ids.add(match.id)
            new_child = create_replacement_entity(
                session,
                entity_type=child_type,
                old_row=match,
                new_part_number=new_part,
                new_serial_number=inv_serial,
                new_configuration_item=inv_config or new_part,
                performed_by_id=performed_by_id,
                installation_date=getattr(child_inventory, "installation_date", None),
                installed_by_id=getattr(child_inventory, "installed_by_id", None)
                or performed_by_id,
                picture_url=inv_picture,
                # Nested composition installs below; don't duplicate by cloning then creating.
                copy_children=False,
            )
        else:
            new_child = _create_fielded_child_from_inventory(
                session,
                child_type=child_type,
                parent_entity_id=parent_entity_id,
                fk_attr=fk_attr,
                name=category_name,
                child_inventory=child_inventory,
                part_number=new_part,
                serial_number=inv_serial,
                configuration_item=inv_config or new_part,
                picture_url=inv_picture,
                performed_by_id=performed_by_id,
                installation_date=getattr(child_inventory, "installation_date", None),
                installed_by_id=getattr(child_inventory, "installed_by_id", None)
                or performed_by_id,
            )
            fielded_children.append(new_child)
            used_ids.add(new_child.id)

        applied += 1

        if not composed:
            consume_inventory_unit(
                session,
                child_inventory,
                instance_id=link.child_instance_id,
                instance_serial=composed_serial if link.child_instance_id is None else None,
            )

        applied += replace_children_from_inventory_composition(
            session,
            parent_entity_type=child_type,
            parent_entity_id=new_child.id,
            parent_inventory_id=child_inventory.id,
            performed_by_id=performed_by_id,
            parent_instance_id=None,
            parent_instance_serial=nested_serial,
        )

    return applied
