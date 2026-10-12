#!/usr/bin/env python3
"""Container entrypoint: wait for Postgres, sync schema/migrations, then exec CMD.

Strategy (matches how this app historically bootstrapped with create_all):
- Empty database: create_all, then alembic stamp head
- Existing alembic_version: alembic upgrade head, then create_all for any new tables
- Legacy DB with tables but no alembic_version: create_all, stamp head
  (column gaps are filled by ensure_user_management_schema on app startup)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from urllib.parse import unquote, urlparse


def _database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise SystemExit("DATABASE_URL is required before starting the backend.")
    return url


def _pg_isready_args(url: str) -> list[str]:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    user = unquote(parsed.username or "postgres")
    dbname = unquote((parsed.path or "/postgres").lstrip("/") or "postgres")
    return [
        "pg_isready",
        "-h",
        host,
        "-p",
        port,
        "-U",
        user,
        "-d",
        dbname,
    ]


def wait_for_database(url: str, *, attempts: int = 60, delay_seconds: float = 2.0) -> None:
    args = _pg_isready_args(url)
    last_error = ""
    for attempt in range(1, attempts + 1):
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Database is ready (attempt {attempt}/{attempts}).", flush=True)
            return
        last_error = (result.stderr or result.stdout or "").strip()
        print(f"Waiting for database ({attempt}/{attempts})...", flush=True)
        time.sleep(delay_seconds)
    raise SystemExit(
        f"Database did not become ready in time. Last pg_isready output: {last_error}"
    )


def _sqlalchemy_url(url: str) -> str:
    """Keep URL as-is; SQLAlchemy 2.1 maps postgresql:// to psycopg."""
    return url


def _connect(url: str):
    from sqlalchemy import create_engine

    return create_engine(_sqlalchemy_url(url), pool_pre_ping=True)


def database_has_app_tables(url: str) -> bool:
    from sqlalchemy import inspect

    engine = _connect(url)
    try:
        inspector = inspect(engine)
        names = set(inspector.get_table_names())
        # Any of these means the app has bootstrapped before.
        return bool(names & {"user", "inventory", "project", "alembic_version"})
    finally:
        engine.dispose()


def database_has_alembic_version(url: str) -> bool:
    from sqlalchemy import text

    engine = _connect(url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = 'alembic_version'
                    LIMIT 1
                    """
                )
            ).first()
            if not row:
                return False
            version = conn.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).first()
            return version is not None
    finally:
        engine.dispose()


def bootstrap_schema() -> None:
    print("Ensuring base schema (SQLModel create_all)...", flush=True)
    from app.database import init_db

    init_db()
    print("Base schema ready.", flush=True)


def run_migrations_upgrade() -> None:
    print("Applying database migrations (alembic upgrade head)...", flush=True)
    subprocess.check_call(["alembic", "upgrade", "head"])
    print("Migrations complete.", flush=True)


def stamp_migrations_head() -> None:
    print(
        "Stamping alembic head (schema already present via create_all)...",
        flush=True,
    )
    subprocess.check_call(["alembic", "stamp", "head"])
    print("Alembic stamp complete.", flush=True)


def sync_database(url: str) -> None:
    has_tables = database_has_app_tables(url)
    has_alembic = database_has_alembic_version(url)

    if has_alembic:
        run_migrations_upgrade()
        bootstrap_schema()
        return

    # Fresh or legacy create_all DB with no migration history.
    bootstrap_schema()
    stamp_migrations_head()
    if not has_tables:
        print("Fresh database initialized and stamped at alembic head.", flush=True)
    else:
        print(
            "Legacy database stamped at alembic head "
            "(column bootstrap runs on app startup).",
            flush=True,
        )


def main(argv: list[str]) -> None:
    url = _database_url()
    wait_for_database(url)
    sync_database(url)

    if not argv:
        argv = [
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ]

    print(f"Starting: {' '.join(argv)}", flush=True)
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main(sys.argv[1:])
