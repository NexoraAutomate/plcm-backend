from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Type

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session, SQLModel

from app.database import get_session
from app.models.tables import (
    Component,
    Inventory,
    InventoryInstance,
    Module,
    Subsystem,
    System,
    Unit,
    User,
)
from app.routers.attachments import UPLOAD_ROOT, _owner_dir
from app.routers.auth import require_permission

router = APIRouter()

OWNER_MODELS: dict[str, Type[SQLModel]] = {
    "system": System,
    "subsystem": Subsystem,
    "module": Module,
    "unit": Unit,
    "component": Component,
    "inventory": Inventory,
    "inventory_instance": InventoryInstance,
}

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
}


def _get_owner(session: Session, owner_type: str, owner_id: int):
    owner_type_normalized = owner_type.lower()
    model = OWNER_MODELS.get(owner_type_normalized)
    if not model:
        raise HTTPException(status_code=400, detail="Invalid owner_type.")
    entity = session.get(model, owner_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found.")
    return owner_type_normalized, entity


def _picture_path(owner_type: str, owner_id: int, ext: str) -> Path:
    return _owner_dir(owner_type, owner_id) / f"picture{ext}"


def _resolve_picture_file(picture_url: str) -> Optional[Path]:
    if not picture_url or picture_url.startswith(("http://", "https://")):
        return None
    path = Path(picture_url)
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    if path.is_file():
        return path
    return None


def _delete_picture_files(owner_type: str, owner_id: int, picture_url: Optional[str]) -> None:
    owner_dir = _owner_dir(owner_type, owner_id)
    for existing in owner_dir.glob("picture.*"):
        if existing.is_file():
            existing.unlink()

    if picture_url:
        file_path = _resolve_picture_file(picture_url)
        if file_path and file_path.is_file():
            file_path.unlink()


@router.post("/pictures/", tags=["pictures"])
async def upload_picture(
    owner_type: str = Form(...),
    owner_id: int = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_systems")),
):
    owner_type_normalized, entity = _get_owner(session, owner_type, owner_id)

    content_type = (file.content_type or "").lower()
    ext = Path(file.filename or "upload").suffix.lower()
    if content_type not in ALLOWED_IMAGE_TYPES and ext not in {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".bmp",
    }:
        raise HTTPException(status_code=400, detail="File must be an image.")

    if not ext:
        ext = ".jpg"

    dest_path = _picture_path(owner_type_normalized, owner_id, ext)
    if dest_path.exists():
        dest_path.unlink()

    for existing in dest_path.parent.glob("picture.*"):
        if existing != dest_path:
            existing.unlink()

    content = await file.read()
    dest_path.write_bytes(content)

    relative_path = str(dest_path.as_posix())
    entity.picture_url = relative_path
    session.add(entity)
    session.commit()
    session.refresh(entity)

    return {"picture_url": entity.picture_url}


@router.post("/pictures/copy/", tags=["pictures"])
def copy_picture(
    from_owner_type: str = Form(...),
    from_owner_id: int = Form(...),
    to_owner_type: str = Form(...),
    to_owner_id: int = Form(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_systems")),
):
    _, source_entity = _get_owner(session, from_owner_type, from_owner_id)
    to_owner_type_normalized, target_entity = _get_owner(session, to_owner_type, to_owner_id)

    source_picture_url = getattr(source_entity, "picture_url", None)
    if not source_picture_url:
        return {"picture_url": getattr(target_entity, "picture_url", None)}

    source_path = _resolve_picture_file(source_picture_url)
    if not source_path:
        return {"picture_url": getattr(target_entity, "picture_url", None)}

    ext = source_path.suffix or ".jpg"
    dest_path = _picture_path(to_owner_type_normalized, to_owner_id, ext)
    if dest_path.exists():
        dest_path.unlink()
    for existing in dest_path.parent.glob("picture.*"):
        if existing != dest_path:
            existing.unlink()

    dest_path.write_bytes(source_path.read_bytes())
    relative_path = str(dest_path.as_posix())
    target_entity.picture_url = relative_path
    session.add(target_entity)
    session.commit()
    session.refresh(target_entity)
    return {"picture_url": target_entity.picture_url}


@router.delete("/pictures/", status_code=204, tags=["pictures"])
def delete_picture(
    owner_type: str,
    owner_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_systems")),
):
    owner_type_normalized, entity = _get_owner(session, owner_type, owner_id)
    picture_url = getattr(entity, "picture_url", None)
    if not picture_url:
        return None

    _delete_picture_files(owner_type_normalized, owner_id, picture_url)
    entity.picture_url = None
    session.add(entity)
    session.commit()
    return None


@router.get("/pictures/", tags=["pictures"])
def get_picture(
    owner_type: str,
    owner_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_systems")),
):
    _, entity = _get_owner(session, owner_type, owner_id)
    picture_url = getattr(entity, "picture_url", None)
    if not picture_url:
        raise HTTPException(status_code=404, detail="Picture not found.")

    if picture_url.startswith(("http://", "https://")):
        return RedirectResponse(picture_url)

    file_path = _resolve_picture_file(picture_url)
    if not file_path:
        raise HTTPException(status_code=404, detail="Picture file missing on disk.")

    media_type = "image/jpeg"
    suffix = file_path.suffix.lower()
    if suffix == ".png":
        media_type = "image/png"
    elif suffix == ".gif":
        media_type = "image/gif"
    elif suffix == ".webp":
        media_type = "image/webp"
    elif suffix == ".bmp":
        media_type = "image/bmp"

    return FileResponse(path=file_path, media_type=media_type)
