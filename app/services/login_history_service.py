"""Login history recording and client metadata helpers."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Request
from sqlmodel import Session, select

from app.models.tables import User, UserLoginHistory


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
        if entry.login_time:
            entry.session_duration = int((now - entry.login_time).total_seconds())
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
    if entry.login_time:
        entry.session_duration = int((now - entry.login_time).total_seconds())
    entry.last_activity = now
    session.add(entry)
    if commit:
        session.commit()
    else:
        session.flush()
    return True
