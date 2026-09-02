"""Persist inventory issuance signatures and proforma scans as entity attachments."""

from __future__ import annotations

import base64
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.base import AttachmentType, SignatureType
from app.models.tables import EntityAttachment, InventoryIssuance

UPLOAD_ROOT = Path(os.environ.get("PLCM_UPLOAD_DIR", "uploads"))
ISSUANCE_OWNER_TYPE = "inventory_issuance"
_DATA_URL_RE = re.compile(r"^data:([^;]+);base64,(.+)$", re.DOTALL)


def _owner_dir(issuance_id: int) -> Path:
    path = UPLOAD_ROOT / ISSUANCE_OWNER_TYPE / str(issuance_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _decode_data_url(payload: str) -> tuple[bytes, str]:
    match = _DATA_URL_RE.match(payload.strip())
    if not match:
        raise HTTPException(status_code=400, detail="Invalid digital signature payload")
    mime = match.group(1).strip() or "image/png"
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid digital signature payload") from exc
    if not data:
        raise HTTPException(status_code=400, detail="Digital signature payload is empty")
    return data, mime


def _ext_for_mime(mime: str) -> str:
    normalized = mime.lower().strip()
    if "png" in normalized:
        return ".png"
    if "jpeg" in normalized or "jpg" in normalized:
        return ".jpg"
    if "webp" in normalized:
        return ".webp"
    return ".png"


def save_digital_signature_attachment(
    session: Session,
    issuance: InventoryIssuance,
    payload: str,
    *,
    uploaded_by_id: Optional[int] = None,
) -> EntityAttachment:
    """Store canvas signature PNG as an entity attachment linked to the issuance."""
    if not issuance.id:
        raise HTTPException(status_code=400, detail="Issuance must be persisted first")

    existing = session.exec(
        select(EntityAttachment).where(
            EntityAttachment.owner_type == ISSUANCE_OWNER_TYPE,
            EntityAttachment.owner_id == issuance.id,
            EntityAttachment.attachment_type == AttachmentType.ISSUANCE_SIGNATURE,
        )
    ).first()
    if existing:
        return existing

    content, mime = _decode_data_url(payload)
    stored_name = f"{uuid.uuid4().hex}{_ext_for_mime(mime)}"
    dest_path = _owner_dir(int(issuance.id)) / stored_name
    dest_path.write_bytes(content)

    attachment = EntityAttachment(
        owner_type=ISSUANCE_OWNER_TYPE,
        owner_id=int(issuance.id),
        file_name=f"issuance-{issuance.id}-signature{dest_path.suffix}",
        file_path=str(dest_path.as_posix()),
        mime_type=mime,
        attachment_type=AttachmentType.ISSUANCE_SIGNATURE,
        description="Digital issue signature",
        uploaded_by_id=uploaded_by_id,
    )
    session.add(attachment)
    session.flush()
    return attachment


def get_issuance_attachment(
    session: Session,
    issuance_id: int,
    attachment_type: AttachmentType,
) -> Optional[EntityAttachment]:
    return session.exec(
        select(EntityAttachment).where(
            EntityAttachment.owner_type == ISSUANCE_OWNER_TYPE,
            EntityAttachment.owner_id == issuance_id,
            EntityAttachment.attachment_type == attachment_type,
        )
    ).first()


def issuance_signature_summary(session: Session, issuance: InventoryIssuance) -> dict:
    if not issuance.id:
        return {
            "signature_type": issuance.signature_type,
            "has_signature_attachment": False,
            "has_proforma_attachment": False,
            "signature_attachment_id": None,
            "proforma_attachment_id": None,
        }

    signature_attachment = get_issuance_attachment(
        session, int(issuance.id), AttachmentType.ISSUANCE_SIGNATURE
    )
    proforma_attachment = get_issuance_attachment(
        session, int(issuance.id), AttachmentType.ISSUANCE_PROFORMA
    )
    sig_type = (issuance.signature_type or "").strip().upper() or None
    has_signature = signature_attachment is not None
    has_proforma = proforma_attachment is not None

    # Legacy rows may still have inline payload without attachment yet.
    if sig_type == SignatureType.DIGITAL.value and not has_signature:
        payload = (issuance.signature_payload or "").strip()
        has_signature = payload.startswith("data:")

    return {
        "signature_type": sig_type,
        "has_signature_attachment": has_signature,
        "has_proforma_attachment": has_proforma,
        "signature_attachment_id": signature_attachment.id if signature_attachment else None,
        "proforma_attachment_id": proforma_attachment.id if proforma_attachment else None,
    }
