import os
from pathlib import Path
from sqlmodel import create_engine, Session, SQLModel
from sqlalchemy import text
from dotenv import load_dotenv
from app.models.tables import *  # Ensure all models are imported so they are registered with SQLModel

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

def init_db() -> None:
    """Create any missing tables from SQLModel metadata (idempotent)."""
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
        conn.commit()
    SQLModel.metadata.create_all(engine)

def close_db() -> None:
    """Dispose engine (cleanup)."""
    engine.dispose()

def get_session():
    with Session(engine) as session:
        yield session