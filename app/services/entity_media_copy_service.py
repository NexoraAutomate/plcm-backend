"""Copy pictures and attachments between polymorphic owners (inventory → hierarchy)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional, Type

from sqlmodel import Session, SQLModel, select

from app.models.tables import (
    Component,
    EntityAttachment,
    Inventory,
    InventoryInstance,
    Module,
    Subsystem,
    System,
    Unit,
    User,
)
from app.routers.attachments import _owner_dir

OWNER_MODELS: dict[str, Type[SQLModel]] = {
    "system": System,
    "subsystem": Subsystem,
    "module": Module,
    "unit": Unit,
    "component": Component,
    "inventory": Inventory,
    "inventory_instance": InventoryInstance,
}


def _get_owner(session: Session, owner_type: str, owner_id: int):
    owner_type_normalized = owner_type.lower()
    model = OWNER_MODELS.get(owner_type_normalized)
    if not model:
        return None, None
    entity = session.get(model, owner_id)
    if not entity:
        return None, None
    return owner_type_normalized, entity


def _resolve_picture_file(picture_url: str) -> Optional[Path]:
    if not picture_url or picture_url.startswith(("http://", "https://")):
        return None
    path = Path(picture_url)
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    if path.is_file():
        return path
    return None


def _picture_path(owner_type: str, owner_id: int, ext: str) -> Path:
    return _owner_dir(owner_type, owner_id) / f"picture{ext}"


def copy_picture_between_owners(
    session: Session,
    *,
    from_owner_type: str,
    from_owner_id: int,
    to_owner_type: str,
    to_owner_id: int,
    overwrite: bool = False,
) -> Optional[str]:
    """Copy picture file + picture_url. Returns target picture_url or None."""
    _, source_entity = _get_owner(session, from_owner_type, from_owner_id)
    to_owner_type_normalized, target_entity = _get_owner(
        session, to_owner_type, to_owner_id
    )
    if not source_entity or not target_entity or not to_owner_type_normalized:
        return None

    existing = getattr(target_entity, "picture_url", None)
    if existing and not overwrite:
        return existing

    source_picture_url = getattr(source_entity, "picture_url", None)
    if not source_picture_url:
        return existing

    source_path = _resolve_picture_file(source_picture_url)
    if not source_path:
        return existing

    ext = source_path.suffix or ".jpg"
    dest_path = _picture_path(to_owner_type_normalized, to_owner_id, ext)
    if dest_path.exists():
        dest_path.unlink()
    for existing_file in dest_path.parent.glob("picture.*"):
        if existing_file != dest_path:
            existing_file.unlink()

    dest_path.write_bytes(source_path.read_bytes())
    relative_path = str(dest_path.as_posix())
    target_entity.picture_url = relative_path
    session.add(target_entity)
    return relative_path


def copy_attachments_between_owners(
    session: Session,
    *,
    from_owner_type: str,
    from_owner_id: int,
    to_owner_type: str,
    to_owner_id: int,
    uploaded_by_id: Optional[int] = None,
    skip_if_target_has_any: bool = True,
) -> list[EntityAttachment]:
    """Copy attachment rows + files. Optionally skip when target already has files."""
    from_owner_type_normalized = from_owner_type.lower()
    to_owner_type_normalized = to_owner_type.lower()
    allowed = set(OWNER_MODELS.keys()) | {"inventory_issuance"}
    if (
        from_owner_type_normalized not in allowed
        or to_owner_type_normalized not in allowed
    ):
        return []

    if skip_if_target_has_any:
        existing = session.exec(
            select(EntityAttachment).where(
                EntityAttachment.owner_type == to_owner_type_normalized,
                EntityAttachment.owner_id == to_owner_id,
            )
        ).first()
        if existing:
            return []

    source_attachments = session.exec(
        select(EntityAttachment).where(
            EntityAttachment.owner_type == from_owner_type_normalized,
            EntityAttachment.owner_id == from_owner_id,
        )
    ).all()

    copied: list[EntityAttachment] = []
    dest_dir = _owner_dir(to_owner_type_normalized, to_owner_id)
    for source in source_attachments:
        source_path = Path(source.file_path)
        if not source_path.is_absolute():
            source_path = Path(os.getcwd()) / source_path
        if not source_path.is_file():
            continue
        ext = source_path.suffix or Path(source.file_name).suffix
        stored_name = f"{uuid.uuid4().hex}{ext}"
        dest_path = dest_dir / stored_name
        dest_path.write_bytes(source_path.read_bytes())
        attachment = EntityAttachment(
            owner_type=to_owner_type_normalized,
            owner_id=to_owner_id,
            file_name=source.file_name,
            file_path=str(dest_path.as_posix()),
            mime_type=source.mime_type,
            attachment_type=source.attachment_type,
            description=source.description,
            uploaded_by_id=uploaded_by_id or source.uploaded_by_id,
        )
        session.add(attachment)
        copied.append(attachment)
    return copied


def copy_inventory_media_to_entity(
    session: Session,
    *,
    entity_type: str,
    entity_id: int,
    inventory_id: int,
    inventory_instance_id: Optional[int] = None,
    actor: Optional[User] = None,
) -> None:
    """Copy catalog (+ optional instance) picture/attachments onto a hierarchy entity."""
    entity_type_normalized = entity_type.lower()
    already_has_attachments = (
        session.exec(
            select(EntityAttachment).where(
                EntityAttachment.owner_type == entity_type_normalized,
                EntityAttachment.owner_id == entity_id,
            )
        ).first()
        is not None
    )

    sources: list[tuple[str, int]] = [("inventory", inventory_id)]
    if inventory_instance_id:
        sources.append(("inventory_instance", inventory_instance_id))

    uploaded_by_id = int(actor.id) if actor and actor.id is not None else None
    for owner_type, owner_id in sources:
        copy_picture_between_owners(
            session,
            from_owner_type=owner_type,
            from_owner_id=owner_id,
            to_owner_type=entity_type_normalized,
            to_owner_id=entity_id,
            overwrite=False,
        )
        if already_has_attachments:
            continue
        copy_attachments_between_owners(
            session,
            from_owner_type=owner_type,
            from_owner_id=owner_id,
            to_owner_type=entity_type_normalized,
            to_owner_id=entity_id,
            uploaded_by_id=uploaded_by_id,
            skip_if_target_has_any=False,
        )
