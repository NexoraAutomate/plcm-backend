from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models.tables import EntityAttachment, User
from app.routers.auth import require_permission
from app.schemas.schemas import EntityAttachmentRead

router = APIRouter()

UPLOAD_ROOT = Path(os.environ.get("PLCM_UPLOAD_DIR", "uploads"))


def _owner_dir(owner_type: str, owner_id: int) -> Path:
    path = UPLOAD_ROOT / owner_type.lower() / str(owner_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.get(
    "/attachments/",
    response_model=List[EntityAttachmentRead],
    tags=["attachments"],
)
def list_attachments(
    owner_type: str,
    owner_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_systems")),
):
    return session.exec(
        select(EntityAttachment).where(
            EntityAttachment.owner_type == owner_type.lower(),
            EntityAttachment.owner_id == owner_id,
        )
    ).all()


@router.post(
    "/attachments/",
    response_model=EntityAttachmentRead,
    status_code=201,
    tags=["attachments"],
)
async def upload_attachment(
    owner_type: str = Form(...),
    owner_id: int = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_systems")),
):
    owner_type_normalized = owner_type.lower()
    allowed = {"system", "subsystem", "module", "unit", "component", "inventory"}
    if owner_type_normalized not in allowed:
        raise HTTPException(status_code=400, detail="Invalid owner_type.")

    ext = Path(file.filename or "upload").suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest_dir = _owner_dir(owner_type_normalized, owner_id)
    dest_path = dest_dir / stored_name

    content = await file.read()
    dest_path.write_bytes(content)

    relative_path = str(dest_path.as_posix())
    attachment = EntityAttachment(
        owner_type=owner_type_normalized,
        owner_id=owner_id,
        file_name=file.filename or stored_name,
        file_path=relative_path,
        mime_type=file.content_type,
        uploaded_by_id=current_user.id,
    )
    session.add(attachment)
    session.commit()
    session.refresh(attachment)
    return attachment


@router.get(
    "/attachments/{attachment_id}/download/",
    tags=["attachments"],
)
def download_attachment(
    attachment_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("view_systems")),
):
    attachment = session.get(EntityAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found.")

    file_path = Path(attachment.file_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Attachment file missing on disk.")

    return FileResponse(
        path=file_path,
        filename=attachment.file_name,
        media_type=attachment.mime_type or "application/octet-stream",
    )


@router.delete(
    "/attachments/{attachment_id}/",
    status_code=204,
    tags=["attachments"],
)
def delete_attachment(
    attachment_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("edit_systems")),
):
    attachment = session.get(EntityAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found.")

    file_path = Path(attachment.file_path)
    if file_path.is_file():
        file_path.unlink()

    session.delete(attachment)
    session.commit()
