"""Normalize datetimes for API responses as UTC with an explicit offset/Z."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional, Any

from sqlalchemy import text

# Ensures IANA zones (e.g. America/Los_Angeles) resolve on Windows.
import tzdata  # noqa: F401


@lru_cache(maxsize=1)
def get_database_timezone() -> Any:
    """
    Timezone PostgreSQL uses when converting aware datetimes into
    TIMESTAMP WITHOUT TIME ZONE columns (stored as naive wall-clock values).

    Must match the DB session zone — not the OS local zone. On this project the
    DB is typically America/Los_Angeles while the Windows OS may be PKT, which
    alone creates a ~12h notification skew.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from app.database import engine

    try:
        with engine.connect() as conn:
            name = conn.execute(text("SHOW timezone")).scalar()
            now = conn.execute(text("SELECT now()")).scalar()
    except Exception:
        return timezone.utc

    if name:
        try:
            return ZoneInfo(str(name))
        except ZoneInfoNotFoundError:
            pass

    if isinstance(now, datetime) and now.tzinfo is not None:
        return now.tzinfo
    return timezone.utc


def to_api_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Convert DB/Python datetimes to UTC-aware values for JSON."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value.replace(tzinfo=get_database_timezone()).astimezone(timezone.utc)


def to_api_utc_iso(value: Optional[datetime]) -> Optional[str]:
    """UTC ISO-8601 string ending in Z (or None)."""
    dt = to_api_utc(value)
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")
