"""Upload / resolve user profile avatars under uploads/user/{id}/."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlmodel import Session

from app.models.tables import User
from app.routers.attachments import UPLOAD_ROOT

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
}

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _user_avatar_dir(user_id: int) -> Path:
    path = UPLOAD_ROOT / "user" / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _avatar_path(user_id: int, ext: str) -> Path:
    return _user_avatar_dir(user_id) / f"avatar{ext}"


def resolve_avatar_file(avatar_url: Optional[str]) -> Optional[Path]:
    if not avatar_url or avatar_url.startswith(("http://", "https://")):
        return None
    path = Path(avatar_url)
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    if path.is_file():
        return path
    return None


def delete_avatar_files(user_id: int, avatar_url: Optional[str] = None) -> None:
    owner_dir = _user_avatar_dir(user_id)
    for existing in owner_dir.glob("avatar.*"):
        if existing.is_file():
            existing.unlink()
    if avatar_url:
        file_path = resolve_avatar_file(avatar_url)
        if file_path and file_path.is_file():
            file_path.unlink()


async def save_user_avatar(session: Session, user: User, file: UploadFile) -> User:
    content_type = (file.content_type or "").lower()
    ext = Path(file.filename or "upload").suffix.lower()
    if content_type not in ALLOWED_IMAGE_TYPES and ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail="File must be an image.")
    if not ext:
        ext = ".jpg"

    dest_path = _avatar_path(user.id, ext)
    delete_avatar_files(user.id, user.avatar_url)

    content = await file.read()
    dest_path.write_bytes(content)

    user.avatar_url = str(dest_path.as_posix())
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def clear_user_avatar(session: Session, user: User) -> User:
    delete_avatar_files(user.id, user.avatar_url)
    user.avatar_url = None
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
