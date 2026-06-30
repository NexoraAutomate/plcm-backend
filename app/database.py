import os
from sqlmodel import create_engine, Session, SQLModel
from sqlalchemy import text
from dotenv import load_dotenv
from app.models.tables import *  # Ensure all models are imported so they are registered with SQLModel
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

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