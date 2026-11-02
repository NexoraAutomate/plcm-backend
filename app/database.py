import logging
import os
import threading
from pathlib import Path
from sqlmodel import create_engine, Session, SQLModel
from sqlalchemy import text
from dotenv import load_dotenv
from fastapi import HTTPException, status
from app.models.tables import *  # Ensure all models are imported so they are registered with SQLModel

logger = logging.getLogger(__name__)

dotenv_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        f"Missing DATABASE_URL environment variable. "
        f"Create a .env file at '{dotenv_path}' with DATABASE_URL=postgresql://... or set the env var before running."
    )

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Set while pg_restore --clean runs so other requests do not grab locks.
_restore_lock = threading.Lock()
_restore_in_progress = False


def begin_database_restore() -> None:
    global _restore_in_progress
    with _restore_lock:
        _restore_in_progress = True


def end_database_restore() -> None:
    global _restore_in_progress
    with _restore_lock:
        _restore_in_progress = False


def is_database_restore_in_progress() -> bool:
    with _restore_lock:
        return _restore_in_progress

def init_db() -> None:
    """Create any missing tables from SQLModel metadata (idempotent).

    Note: create_all only creates *new tables*. It does not add/alter columns on
    existing tables — use Alembic (`alembic upgrade head`) or schema_bootstrap for that.
    """
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        db_name = conn.execute(text("SELECT current_database()")).scalar()
        conn.commit()
    before = set(SQLModel.metadata.tables)
    SQLModel.metadata.create_all(engine)
    logger.info(
        "init_db: connected to database %r; ensure %d model table(s) exist "
        "(create_all does not alter existing columns)",
        db_name,
        len(before),
    )

def close_db() -> None:
    """Dispose engine (cleanup)."""
    engine.dispose()

def get_session():
    if is_database_restore_in_progress():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database restore in progress. Please wait and retry.",
        )
    with Session(engine) as session:
        yield session