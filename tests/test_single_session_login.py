"""One active session per user; takeover closes the previous session."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.auth import hash_password
from app.database import engine
from app.main import app
from app.models.tables import Role, User
from app.services.schema_bootstrap import ensure_user_management_schema


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    ensure_user_management_schema()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s


def _make_user(session: Session) -> tuple[str, str]:
    role = session.exec(select(Role).where(Role.name == "Viewer")).first()
    if not role:
        pytest.skip("Viewer role required")
    username = f"single_sess_{uuid.uuid4().hex[:10]}"
    password = "SingleSess@Test1"
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name="Single Session Test",
        is_active=True,
        password=hash_password(password),
    )
    user.roles = [role]
    session.add(user)
    session.commit()
    return username, password


def test_second_login_requires_takeover(client: TestClient, session: Session):
    username, password = _make_user(session)

    first = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )
    assert first.status_code == 200, first.text
    first_token = first.json()["access_token"]

    second = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )
    assert second.status_code == 409, second.text
    body = second.json()
    assert body["detail"]["code"] == "ACTIVE_SESSION_EXISTS"

    me_old = client.get(
        "/api/auth/me/",
        headers={"Authorization": f"Bearer {first_token}"},
    )
    assert me_old.status_code == 200

    takeover = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
        params={"force_session_takeover": True},
    )
    assert takeover.status_code == 200, takeover.text
    new_token = takeover.json()["access_token"]

    me_old_after = client.get(
        "/api/auth/me/",
        headers={"Authorization": f"Bearer {first_token}"},
    )
    assert me_old_after.status_code == 401

    me_new = client.get(
        "/api/auth/me/",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert me_new.status_code == 200
