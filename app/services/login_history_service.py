"""Login history recording and client metadata helpers."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Request
from sqlmodel import Session, select

from app.models.tables import User, UserLoginHistory


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize DB datetimes so aware/naive values can be compared safely."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _session_duration_seconds(login_time: Optional[datetime], now: datetime) -> Optional[int]:
    started = _as_utc(login_time)
    if started is None:
        return None
    return int((_as_utc(now) - started).total_seconds())


def client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def parse_user_agent(user_agent: Optional[str]) -> dict[str, Optional[str]]:
    ua = user_agent or ""
    browser = "Unknown"
    operating_system = "Unknown"
    device_name = "Desktop"

    ua_lower = ua.lower()
    if "edg/" in ua_lower or "edge/" in ua_lower:
        browser = "Microsoft Edge"
    elif "chrome/" in ua_lower and "chromium" not in ua_lower:
        browser = "Chrome"
    elif "firefox/" in ua_lower:
        browser = "Firefox"
    elif "safari/" in ua_lower and "chrome/" not in ua_lower:
        browser = "Safari"
    elif "msie" in ua_lower or "trident/" in ua_lower:
        browser = "Internet Explorer"
    elif ua:
        browser = ua.split(" ")[0][:64]

    if "windows" in ua_lower:
        operating_system = "Windows"
    elif "android" in ua_lower:
        operating_system = "Android"
        device_name = "Mobile"
    elif "iphone" in ua_lower or "ipad" in ua_lower:
        operating_system = "iOS"
        device_name = "Mobile" if "iphone" in ua_lower else "Tablet"
    elif "mac os" in ua_lower or "macintosh" in ua_lower:
        operating_system = "macOS"
    elif "linux" in ua_lower:
        operating_system = "Linux"

    if "mobile" in ua_lower and device_name == "Desktop":
        device_name = "Mobile"

    return {
        "browser": browser,
        "operating_system": operating_system,
        "device_name": device_name,
    }


def record_login_attempt(
    session: Session,
    *,
    username: str,
    login_status: str,
    user: Optional[User] = None,
    failure_reason: Optional[str] = None,
    request: Optional[Request] = None,
    session_id: Optional[str] = None,
    authentication_method: str = "password",
    commit: bool = False,
) -> UserLoginHistory:
    now = datetime.now(timezone.utc)
    ua = request.headers.get("user-agent") if request else None
    meta = parse_user_agent(ua)
    entry = UserLoginHistory(
        user_id=user.id if user else None,
        username=username,
        login_time=now,
        logout_time=None,
        session_id=session_id,
        ip_address=client_ip(request),
        device_name=meta["device_name"],
        browser=meta["browser"],
        operating_system=meta["operating_system"],
        login_status=login_status,
        failure_reason=failure_reason,
        last_activity=now if login_status == "Success" else None,
        session_duration=None,
        authentication_method=authentication_method,
    )
    session.add(entry)
    if commit:
        session.commit()
        session.refresh(entry)
    else:
        session.flush()
    return entry


def new_session_id() -> str:
    return uuid.uuid4().hex


def close_open_sessions_for_user(
    session: Session,
    user_id: int,
    *,
    commit: bool = False,
) -> int:
    """Mark open successful sessions as logged out (e.g. on deactivate)."""
    now = datetime.now(timezone.utc)
    open_sessions = session.exec(
        select(UserLoginHistory).where(
            UserLoginHistory.user_id == user_id,
            UserLoginHistory.login_status == "Success",
            UserLoginHistory.logout_time.is_(None),  # type: ignore[union-attr]
        )
    ).all()
    for entry in open_sessions:
        entry.logout_time = now
        duration = _session_duration_seconds(entry.login_time, now)
        if duration is not None:
            entry.session_duration = duration
        entry.last_activity = now
        session.add(entry)
    if commit:
        session.commit()
    else:
        session.flush()
    return len(open_sessions)


def close_session_by_id(
    session: Session,
    session_id: str,
    *,
    commit: bool = False,
) -> bool:
    entry = session.exec(
        select(UserLoginHistory).where(
            UserLoginHistory.session_id == session_id,
            UserLoginHistory.logout_time.is_(None),  # type: ignore[union-attr]
        )
    ).first()
    if not entry:
        return False
    now = datetime.now(timezone.utc)
    entry.logout_time = now
    duration = _session_duration_seconds(entry.login_time, now)
    if duration is not None:
        entry.session_duration = duration
    entry.last_activity = now
    session.add(entry)
    if commit:
        session.commit()
    else:
        session.flush()
    return True


def is_session_active(session: Session, session_id: str) -> bool:
    """Return True when the session_id has an open successful login row."""
    if not session_id:
        return False
    entry = session.exec(
        select(UserLoginHistory).where(
            UserLoginHistory.session_id == session_id,
            UserLoginHistory.login_status == "Success",
            UserLoginHistory.logout_time.is_(None),  # type: ignore[union-attr]
        )
    ).first()
    return entry is not None


def list_active_sessions(
    session: Session,
    *,
    user_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[UserLoginHistory]:
    stmt = select(UserLoginHistory).where(
        UserLoginHistory.login_status == "Success",
        UserLoginHistory.logout_time.is_(None),  # type: ignore[union-attr]
    )
    if user_id is not None:
        stmt = stmt.where(UserLoginHistory.user_id == user_id)
    stmt = stmt.order_by(UserLoginHistory.login_time.desc()).offset(skip).limit(limit)
    return list(session.exec(stmt).all())


def touch_session_activity(session: Session, session_id: str) -> None:
    entry = session.exec(
        select(UserLoginHistory).where(
            UserLoginHistory.session_id == session_id,
            UserLoginHistory.logout_time.is_(None),  # type: ignore[union-attr]
        )
    ).first()
    if not entry:
        return
    entry.last_activity = datetime.now(timezone.utc)
    session.add(entry)
    session.flush()
