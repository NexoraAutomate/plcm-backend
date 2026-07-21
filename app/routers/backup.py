"""Backup and restore endpoints for full application data."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.database import engine, get_session
from app.models.tables import User
from app.routers.auth import require_permission
from app.services.audit_service import write_audit_log
from app.services.backup_service import (
    RESTORE_CONFIRM_PHRASE,
    BackupError,
    create_backup_archive,
    get_alembic_revision,
    restore_from_archive,
)
from app.services.login_history_service import client_ip

router = APIRouter(prefix="/backup", tags=["Backup"])


def _cleanup_backup_file(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink(missing_ok=True)
        parent = path.parent
        if parent.exists() and parent.name.startswith("satlife-backup-out-"):
            shutil.rmtree(parent, ignore_errors=True)
    except OSError:
        pass


@router.post("/")
def create_backup(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("backup_database")),
):
    zip_path: Optional[Path] = None
    try:
        revision = get_alembic_revision(session)
        zip_path, filename = create_backup_archive(
            created_by=current_user.username or str(current_user.id),
            alembic_revision=revision,
        )
        write_audit_log(
            session,
            action="backup_database",
            actor=current_user,
            resource_type="backup",
            resource_id=filename,
            details=f"Created backup archive {filename}",
            ip_address=client_ip(request),
            commit=True,
        )
        background_tasks.add_task(_cleanup_backup_file, zip_path)
        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=filename,
        )
    except BackupError as exc:
        if zip_path is not None:
            _cleanup_backup_file(zip_path)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        if zip_path is not None:
            _cleanup_backup_file(zip_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backup failed: {exc}",
        ) from exc


@router.post("/restore/")
async def restore_backup(
    request: Request,
    file: UploadFile = File(...),
    confirm: str = Form(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("restore_database")),
):
    if confirm != RESTORE_CONFIRM_PHRASE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Confirmation required. Type "{RESTORE_CONFIRM_PHRASE}" to proceed.',
        )

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Backup file must be a .zip archive.",
        )

    actor_username = current_user.username
    tmp_path: Optional[Path] = None
    try:
        current_revision = get_alembic_revision(session)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            tmp_path = Path(tmp.name)
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)

        result = restore_from_archive(tmp_path, current_revision=current_revision)

        # Fresh session after restore; resolve actor only if still present
        with Session(engine) as audit_session:
            restored_actor = audit_session.exec(
                select(User).where(User.username == actor_username)
            ).first()
            write_audit_log(
                audit_session,
                action="restore_database",
                actor=restored_actor,
                resource_type="backup",
                resource_id=file.filename,
                details=(
                    f"Restored from {file.filename} by {actor_username} "
                    f"(revision={result.get('alembic_revision')})"
                ),
                ip_address=client_ip(request),
                commit=True,
            )

        return result
    except BackupError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Restore failed: {exc}",
        ) from exc
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            await file.close()
        except Exception:
            pass
