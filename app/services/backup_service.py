"""Full application backup and restore (PostgreSQL + uploads)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from sqlalchemy import text
from sqlmodel import Session

from app.database import DATABASE_URL, engine

APP_LABEL = "satlife"
RESTORE_CONFIRM_PHRASE = "RESTORE"
MANIFEST_NAME = "manifest.json"
DUMP_NAME = "database.dump"
UPLOADS_ARCHIVE_PREFIX = "uploads/"
UPLOAD_ROOT = Path(os.environ.get("PLCM_UPLOAD_DIR", "uploads"))

_COPY_REVISION_RE = re.compile(
    r"COPY\s+(?:public\.)?alembic_version\s*\([^)]*\)\s+FROM\s+stdin;\s*\n([^\n\\]+)",
    re.IGNORECASE,
)
_INSERT_REVISION_RE = re.compile(
    r"INSERT\s+INTO\s+(?:public\.)?alembic_version\s*(?:\([^)]*\))?\s*VALUES\s*\(\s*'([^']+)'\s*\)",
    re.IGNORECASE,
)


class BackupError(Exception):
    """Raised when backup or restore fails with a user-facing message."""


def _parse_database_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"postgresql", "postgres", "postgresql+psycopg2"}:
        raise BackupError("DATABASE_URL must be a PostgreSQL connection string.")
    if not parsed.hostname or not parsed.path or parsed.path == "/":
        raise BackupError("DATABASE_URL is missing host or database name.")
    return {
        "host": parsed.hostname,
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "dbname": unquote(parsed.path.lstrip("/")),
    }


def _pg_env(db: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    if db["password"]:
        env["PGPASSWORD"] = db["password"]
    return env


_ENV_BINARY_KEYS = {
    "pg_dump": ("PG_DUMP_PATH", "PLCM_PG_DUMP"),
    "pg_restore": ("PG_RESTORE_PATH", "PLCM_PG_RESTORE"),
}


def _candidate_binary_paths(name: str) -> list[Path]:
    """Build ordered candidate paths for pg_dump / pg_restore."""
    candidates: list[Path] = []

    for key in _ENV_BINARY_KEYS.get(name, ()):
        override = os.environ.get(key)
        if override:
            candidates.append(Path(override))

    bin_dir = os.environ.get("PLCM_PG_BIN_DIR") or os.environ.get("PGBIN")
    if bin_dir:
        base = Path(bin_dir)
        candidates.append(base / name)
        candidates.append(base / f"{name}.exe")

    which = shutil.which(name)
    if which:
        candidates.append(Path(which))
    which_exe = shutil.which(f"{name}.exe")
    if which_exe:
        candidates.append(Path(which_exe))

    # Common Windows PostgreSQL installs (newest version first)
    program_files = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    ]
    version_dirs: list[Path] = []
    for pf in program_files:
        pg_root = pf / "PostgreSQL"
        if pg_root.is_dir():
            version_dirs.extend(p for p in pg_root.iterdir() if p.is_dir())
    version_dirs.sort(key=lambda p: p.name, reverse=True)
    for version_dir in version_dirs:
        candidates.append(version_dir / "bin" / f"{name}.exe")
        candidates.append(version_dir / "bin" / name)

    # Common Linux / macOS locations
    for prefix in ("/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"):
        candidates.append(Path(prefix) / name)

    return candidates


def _require_binary(name: str) -> str:
    seen: set[str] = set()
    for candidate in _candidate_binary_paths(name):
        resolved = str(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return str(candidate.resolve())

    raise BackupError(
        f"Required tool '{name}' was not found. "
        "Install PostgreSQL client tools, or set PG_DUMP_PATH / PG_RESTORE_PATH "
        "(or PLCM_PG_BIN_DIR) to the bin directory that contains them."
    )


def get_alembic_revision(session: Session) -> Optional[str]:
    try:
        row = session.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
        if row is None:
            return None
        return str(row[0]) if row[0] is not None else None
    except Exception:
        session.rollback()
        return None


def _parse_alembic_revision_sql(sql: str) -> Optional[str]:
    copy_match = _COPY_REVISION_RE.search(sql)
    if copy_match:
        value = copy_match.group(1).strip()
        return value or None
    insert_match = _INSERT_REVISION_RE.search(sql)
    if insert_match:
        value = insert_match.group(1).strip()
        return value or None
    return None


def get_alembic_revision_from_dump(dump_path: Path) -> Optional[str]:
    """Read alembic_version.version_num from a pg_dump custom-format archive."""
    pg_restore = _require_binary("pg_restore")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".sql") as tmp:
        sql_path = Path(tmp.name)
    try:
        result = subprocess.run(
            [
                pg_restore,
                "--data-only",
                "--table=alembic_version",
                "-f",
                str(sql_path),
                str(dump_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode not in (0, 1):
            return None
        try:
            sql = sql_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        return _parse_alembic_revision_sql(sql)
    finally:
        sql_path.unlink(missing_ok=True)


def create_backup_archive(*, created_by: str, alembic_revision: Optional[str]) -> tuple[Path, str]:
    """
    Build a ZIP backup containing manifest.json, database.dump, and uploads/.
    Returns (zip_path, filename). Caller must delete zip_path when finished.
    """
    if not alembic_revision:
        raise BackupError(
            "Cannot create backup: database has no alembic revision. "
            "Run migrations (alembic upgrade head) before backing up."
        )

    pg_dump = _require_binary("pg_dump")
    db = _parse_database_url(DATABASE_URL)
    created_at = datetime.now(timezone.utc)
    stamp = created_at.strftime("%Y%m%d-%H%M%S")
    filename = f"satlife-backup-{stamp}.zip"

    work_dir = Path(tempfile.mkdtemp(prefix="satlife-backup-"))
    try:
        dump_path = work_dir / DUMP_NAME
        cmd = [
            pg_dump,
            "-Fc",
            "-h",
            db["host"],
            "-p",
            db["port"],
            "-U",
            db["user"],
            "-d",
            db["dbname"],
            "-f",
            str(dump_path),
        ]
        result = subprocess.run(
            cmd,
            env=_pg_env(db),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip() or "unknown error"
            raise BackupError(f"pg_dump failed: {detail}")

        manifest = {
            "app": APP_LABEL,
            "created_at": created_at.isoformat(),
            "created_by": created_by,
            "alembic_revision": alembic_revision,
            "includes_uploads": True,
        }
        manifest_path = work_dir / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        zip_path = work_dir / filename
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(manifest_path, arcname=MANIFEST_NAME)
            zf.write(dump_path, arcname=DUMP_NAME)
            upload_root = Path(UPLOAD_ROOT)
            if upload_root.is_dir():
                for file_path in upload_root.rglob("*"):
                    if file_path.is_file():
                        arcname = f"{UPLOADS_ARCHIVE_PREFIX}{file_path.relative_to(upload_root).as_posix()}"
                        zf.write(file_path, arcname=arcname)

        # Move zip out of work_dir so we can clean staging files but keep the archive
        final_dir = Path(tempfile.mkdtemp(prefix="satlife-backup-out-"))
        final_path = final_dir / filename
        shutil.move(str(zip_path), str(final_path))
        return final_path, filename
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _safe_extract_member(zf: zipfile.ZipFile, member: zipfile.ZipInfo, dest: Path) -> None:
    target = (dest / member.filename).resolve()
    if not str(target).startswith(str(dest.resolve())):
        raise BackupError(f"Unsafe path in backup archive: {member.filename}")
    if member.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member) as src, open(target, "wb") as out:
        shutil.copyfileobj(src, out)


def restore_from_archive(
    archive_path: Path,
    *,
    current_revision: Optional[str],
) -> dict[str, Any]:
    """
    Restore database and uploads from a SatLife backup ZIP.
    Requires a schema revision in the archive (manifest or dump).
    If the live DB still has a revision, it must match the backup.
    """
    pg_restore = _require_binary("pg_restore")
    db = _parse_database_url(DATABASE_URL)

    if not zipfile.is_zipfile(archive_path):
        raise BackupError("Backup file must be a valid ZIP archive.")

    extract_dir = Path(tempfile.mkdtemp(prefix="satlife-restore-"))
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            names = set(zf.namelist())
            if MANIFEST_NAME not in names:
                raise BackupError("Backup is missing manifest.json.")
            if DUMP_NAME not in names:
                raise BackupError("Backup is missing database.dump.")

            for info in zf.infolist():
                _safe_extract_member(zf, info, extract_dir)

        manifest_path = extract_dir / MANIFEST_NAME
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BackupError(f"Invalid manifest.json: {exc}") from exc

        if manifest.get("app") != APP_LABEL:
            raise BackupError("Backup manifest is not a SatLife application backup.")

        dump_path = extract_dir / DUMP_NAME
        backup_revision = manifest.get("alembic_revision") or None
        if not backup_revision:
            backup_revision = get_alembic_revision_from_dump(dump_path)
        if not backup_revision:
            raise BackupError(
                "Backup is missing alembic_revision (manifest and database.dump). "
                "This archive was created from a database without migrations applied "
                "and cannot be restored safely. Use an earlier backup that includes "
                "a schema revision."
            )
        # Allow restore into a DB that lost alembic_version (recovery). When the
        # live DB still has a revision, require an exact match.
        if current_revision and backup_revision != current_revision:
            raise BackupError(
                f"Schema mismatch: backup revision '{backup_revision}' "
                f"does not match current '{current_revision}'. "
                "Upgrade or match application versions before restoring."
            )

        # Dispose pooled connections so --clean can drop objects safely
        engine.dispose()

        cmd = [
            pg_restore,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-acl",
            "-h",
            db["host"],
            "-p",
            db["port"],
            "-U",
            db["user"],
            "-d",
            db["dbname"],
            str(dump_path),
        ]
        result = subprocess.run(
            cmd,
            env=_pg_env(db),
            capture_output=True,
            text=True,
            check=False,
        )
        # pg_restore may return non-zero for non-fatal warnings with --clean;
        # treat as failure only when the database is unusable afterwards.
        if result.returncode not in (0, 1):
            detail = (result.stderr or result.stdout or "").strip() or "unknown error"
            raise BackupError(f"pg_restore failed: {detail}")

        engine.dispose()

        # Verify alembic_version still readable after restore
        with Session(engine) as verify_session:
            restored_revision = get_alembic_revision(verify_session)
        if restored_revision != backup_revision:
            raise BackupError(
                "Restore completed but alembic revision verification failed."
            )

        _replace_uploads(extract_dir / "uploads")

        return {
            "message": "Restore completed successfully.",
            "alembic_revision": restored_revision,
            "created_at": manifest.get("created_at"),
            "created_by": manifest.get("created_by"),
        }
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def _replace_uploads(source_uploads: Path) -> None:
    upload_root = Path(UPLOAD_ROOT).resolve()
    parent = upload_root.parent
    parent.mkdir(parents=True, exist_ok=True)

    staging = parent / f".uploads_restore_{os.getpid()}"
    backup_old = parent / f".uploads_old_{os.getpid()}"

    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    if backup_old.exists():
        shutil.rmtree(backup_old, ignore_errors=True)

    staging.mkdir(parents=True, exist_ok=True)
    if source_uploads.is_dir():
        for item in source_uploads.iterdir():
            dest = staging / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

    try:
        if upload_root.exists():
            upload_root.rename(backup_old)
        staging.rename(upload_root)
    except OSError as exc:
        # Best-effort rollback
        if not upload_root.exists() and backup_old.exists():
            backup_old.rename(upload_root)
        raise BackupError(f"Failed to replace uploads directory: {exc}") from exc
    finally:
        if backup_old.exists():
            shutil.rmtree(backup_old, ignore_errors=True)
        if staging.exists() and staging != upload_root:
            shutil.rmtree(staging, ignore_errors=True)
