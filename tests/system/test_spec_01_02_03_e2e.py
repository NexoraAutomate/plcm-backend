"""
System-level API tests for Specs 01 → 02 → 03.

Exercises the full HTTP surface (auth → config → draft → approve → generate → tree)
against the real database via FastAPI TestClient.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.auth import hash_password
from app.database import engine
from app.domain.workflow_status import ProjectWorkflowStatus
from app.main import app
from app.models.tables import Project, Role, User
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.workflow_foundation_seed import ensure_workflow_statuses


ADMIN_USER = "admin"
ADMIN_PASS = "password@82768243"


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    ensure_user_management_schema()
    with Session(engine) as session:
        ensure_workflow_statuses(session)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _login(client: TestClient, username: str, password: str) -> dict:
    res = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _template_nodes(prefix: str = "sys") -> list[dict]:
    return [
        {"client_key": f"{prefix}", "level": "system", "name": "Comm"},
        {
            "client_key": f"{prefix}-sub",
            "parent_client_key": prefix,
            "level": "subsystem",
            "name": "RF",
        },
        {
            "client_key": f"{prefix}-mod",
            "parent_client_key": f"{prefix}-sub",
            "level": "module",
            "name": "Modem",
        },
        {
            "client_key": f"{prefix}-unit",
            "parent_client_key": f"{prefix}-mod",
            "level": "unit",
            "name": "Board",
        },
        {
            "client_key": f"{prefix}-cmp",
            "parent_client_key": f"{prefix}-unit",
            "level": "component",
            "name": "Chip",
        },
    ]


@pytest.fixture()
def admin_headers(client: TestClient):
    return _login(client, ADMIN_USER, ADMIN_PASS)


@pytest.fixture()
def viewer_user(client: TestClient):
    """User with Viewer role only — no hierarchy_config.manage / project.approve / hierarchy.generate."""
    username = f"viewer_{uuid.uuid4().hex[:6]}"
    password = "Viewer@Test1"
    with Session(engine) as session:
        role = session.exec(select(Role).where(Role.name == "Viewer")).first()
        if not role:
            pytest.skip("Viewer role required")
        user = User(
            username=username,
            email=f"{username}@example.com",
            full_name="System Test Viewer",
            is_active=True,
            password=hash_password(password),
            updated_at=datetime.now(timezone.utc),
        )
        user.roles = [role]
        session.add(user)
        session.commit()
        uid = user.id
    headers = _login(client, username, password)
    yield headers, uid
    with Session(engine) as session:
        user = session.get(User, uid)
        if user:
            session.delete(user)
            session.commit()


class TestSpec01System:
    def test_admin_creates_two_configs_available_filter(self, client, admin_headers):
        code_a = _unique("CFG-A")
        code_b = _unique("CFG-B")
        body_a = {
            "code": code_a,
            "name": f"SSDLS-1 {code_a}",
            "product_types": [
                {"code": "SSDLS-1", "name": "High Data Rate"},
                {"code": "SSDLS-2", "name": "Low Data Rate"},
            ],
            "nodes": _template_nodes("a"),
        }
        body_b = {
            "code": code_b,
            "name": f"SSDLS-2 {code_b}",
            "product_types": [{"code": "SSDLS-2", "name": "Low Data Rate"}],
            "nodes": [
                {"client_key": "s1", "level": "system", "name": "Power"},
            ],
        }
        ra = client.post(
            "/api/hierarchy-configurations/", headers=admin_headers, json=body_a
        )
        rb = client.post(
            "/api/hierarchy-configurations/", headers=admin_headers, json=body_b
        )
        assert ra.status_code == 201, ra.text
        assert rb.status_code == 201, rb.text
        cfg_a, cfg_b = ra.json(), rb.json()
        assert cfg_a["is_available"] is True
        assert len(cfg_a["product_types"]) == 2
        assert len(cfg_a["nodes"]) == 5

        # Retire B
        retire = client.patch(
            f"/api/hierarchy-configurations/{cfg_b['id']}/availability",
            headers=admin_headers,
            params={"is_available": False},
        )
        assert retire.status_code == 200, retire.text
        assert retire.json()["is_available"] is False

        available = client.get(
            "/api/hierarchy-configurations/available", headers=admin_headers
        )
        assert available.status_code == 200
        ids = {c["id"] for c in available.json()}
        assert cfg_a["id"] in ids
        assert cfg_b["id"] not in ids

        meta = client.get(
            "/api/hierarchy-configurations/meta", headers=admin_headers
        )
        assert meta.status_code == 200
        levels = [lvl["code"] for lvl in meta.json().get("fixed_levels", meta.json().get("levels", []))]
        if not levels and isinstance(meta.json(), list):
            levels = [lvl.get("code") for lvl in meta.json()]
        # Accept either key shape from Spec 01 meta
        payload = meta.json()
        if "fixed_levels" in payload:
            assert [x["code"] for x in payload["fixed_levels"]][:3] == [
                "product_type",
                "flight",
                "sdls",
            ]

        for cfg_id in (cfg_a["id"], cfg_b["id"]):
            client.delete(
                f"/api/hierarchy-configurations/{cfg_id}?hard=true",
                headers=admin_headers,
            )

    def test_non_admin_cannot_create_config(self, client, viewer_user):
        headers, _ = viewer_user
        res = client.post(
            "/api/hierarchy-configurations/",
            headers=headers,
            json={
                "code": _unique("NOPE"),
                "name": "Denied",
                "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
                "nodes": [{"client_key": "s1", "level": "system", "name": "X"}],
            },
        )
        assert res.status_code in (401, 403)
        detail = str(res.json().get("detail", "")).lower()
        assert "permission" in detail or "forbidden" in detail or res.status_code == 403


class TestSpec02System:
    def test_bulk_draft_creates_one_project_per_flight(self, client, admin_headers):
        code = _unique("P2B")
        cfg = client.post(
            "/api/hierarchy-configurations/",
            headers=admin_headers,
            json={
                "code": code,
                "name": code,
                "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
                "nodes": [{"client_key": "s1", "level": "system", "name": "Comm"}],
            },
        ).json()

        bulk = client.post(
            "/api/projects/draft/bulk/",
            headers=admin_headers,
            json={
                "name": "ABC",
                "hierarchy_config_id": cfg["id"],
                "product_type": "SSDLS-1",
                "flight_count": 3,
                "sdls_counts_by_flight": [1, 3, 2],
            },
        )
        assert bulk.status_code == 201, bulk.text
        projects = bulk.json()["projects"]
        assert bulk.json()["count"] == 3
        assert [project["name"] for project in projects] == [
            "ABC - Flight 1",
            "ABC - Flight 2",
            "ABC - Flight 3",
        ]
        assert [project["flight_count"] for project in projects] == [1, 1, 1]
        assert [project["sdls_counts_by_flight"] for project in projects] == [
            [1],
            [3],
            [2],
        ]

        with Session(engine) as session:
            for project in projects:
                db_project = session.get(Project, project["id"])
                if db_project:
                    session.delete(db_project)
            session.commit()
        client.delete(
            f"/api/hierarchy-configurations/{cfg['id']}?hard=true",
            headers=admin_headers,
        )

    def test_draft_approve_generate_gate(self, client, admin_headers):
        code = _unique("P2")
        cfg = client.post(
            "/api/hierarchy-configurations/",
            headers=admin_headers,
            json={
                "code": code,
                "name": code,
                "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
                "nodes": _template_nodes(),
            },
        ).json()

        draft = client.post(
            "/api/projects/draft/",
            headers=admin_headers,
            json={
                "name": f"Draft-{code}",
                "hierarchy_config_id": cfg["id"],
                "product_type": "SSDLS-1",
                "flight_count": 2,
                "sdls_per_flight": 3,
            },
        )
        assert draft.status_code == 201, draft.text
        project = draft.json()
        assert project["status_name"] == ProjectWorkflowStatus.DRAFT.value
        assert project["hierarchy_config_id"] == cfg["id"]
        assert project["flight_count"] == 2

        blocked = client.post(
            f"/api/projects/{project['id']}/generate-hierarchy/",
            headers=admin_headers,
        )
        assert blocked.status_code in (400, 403, 422)
        assert "APPROVED" in blocked.json()["detail"]

        approved = client.post(
            f"/api/projects/{project['id']}/approve/",
            headers=admin_headers,
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status_name"] == ProjectWorkflowStatus.APPROVED.value
        # Spec 02: approve does not auto-generate
        assert approved.json().get("systems") in (None, [])

        client.delete(
            f"/api/hierarchy-configurations/{cfg['id']}?hard=true",
            headers=admin_headers,
        )

    def test_non_admin_cannot_approve(self, client, admin_headers, viewer_user):
        headers, _ = viewer_user
        code = _unique("P2N")
        cfg = client.post(
            "/api/hierarchy-configurations/",
            headers=admin_headers,
            json={
                "code": code,
                "name": code,
                "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
                "nodes": [{"client_key": "s1", "level": "system", "name": "Comm"}],
            },
        ).json()
        project = client.post(
            "/api/projects/draft/",
            headers=admin_headers,
            json={
                "name": f"Draft-{code}",
                "hierarchy_config_id": cfg["id"],
                "product_type": "SSDLS-1",
                "flight_count": 1,
                "sdls_per_flight": 1,
            },
        ).json()
        res = client.post(
            f"/api/projects/{project['id']}/approve/",
            headers=headers,
        )
        assert res.status_code in (401, 403)
        client.delete(
            f"/api/hierarchy-configurations/{cfg['id']}?hard=true",
            headers=admin_headers,
        )


class TestSpec03System:
    def test_full_generate_tree_and_idempotent(
        self, client, admin_headers
    ):
        code = _unique("P3")
        cfg = client.post(
            "/api/hierarchy-configurations/",
            headers=admin_headers,
            json={
                "code": code,
                "name": code,
                "product_types": [
                    {"code": "SSDLS-1", "name": "HDR"},
                    {"code": "SSDLS-2", "name": "LDR"},
                ],
                "nodes": _template_nodes(),
            },
        ).json()
        project = client.post(
            "/api/projects/draft/",
            headers=admin_headers,
            json={
                "name": f"Gen-{code}",
                "hierarchy_config_id": cfg["id"],
                "product_type": "SSDLS-1",
                "flight_count": 2,
                "sdls_per_flight": 3,
            },
        ).json()
        client.post(
            f"/api/projects/{project['id']}/approve/",
            headers=admin_headers,
        )

        gen = client.post(
            f"/api/projects/{project['id']}/generate-hierarchy/",
            headers=admin_headers,
        )
        assert gen.status_code == 200, gen.text
        body = gen.json()
        assert body["status"] == ProjectWorkflowStatus.READY_FOR_INVENTORY.value
        assert body["counts"]["flights"] == 2
        assert body["counts"]["sdls"] == 6
        assert body["counts"]["systems"] == 6
        assert body["counts"]["subsystems"] == 6
        assert body["counts"]["modules"] == 6
        assert body["counts"]["units"] == 6
        assert body["counts"]["components"] == 6

        tree = client.get(
            f"/api/projects/{project['id']}/hierarchy-tree/",
            headers=admin_headers,
        )
        assert tree.status_code == 200, tree.text
        tree_body = tree.json()
        assert len(tree_body["flights"]) == 2
        assert sum(len(f["sdls"]) for f in tree_body["flights"]) == 6
        for flight in tree_body["flights"]:
            for sdls in flight["sdls"]:
                assert len(sdls["systems"]) == 1
                system = sdls["systems"][0]
                assert system["name"] == "Comm"
                assert sdls["name"] == f"SDLS-{sdls['sequence']}"
                assert sdls["product_type"] == "SSDLS-1"
                assert system["subsystem_count"] >= 1
                assert len(system.get("subsystems") or []) >= 1
                subsystem = system["subsystems"][0]
                assert len(subsystem.get("modules") or []) >= 1
                module = subsystem["modules"][0]
                assert len(module.get("units") or []) >= 1
                unit = module["units"][0]
                assert len(unit.get("components") or []) >= 1

        again = client.post(
            f"/api/projects/{project['id']}/generate-hierarchy/",
            headers=admin_headers,
        )
        assert again.status_code in (400, 403, 422)
        assert "already" in again.json()["detail"].lower()

        # Concurrent double-submit should not create duplicate trees
        # (project already generated — both should fail cleanly)
        def _attempt():
            return client.post(
                f"/api/projects/{project['id']}/generate-hierarchy/",
                headers=admin_headers,
            ).status_code

        codes = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_attempt) for _ in range(2)]
            for fut in as_completed(futures):
                codes.append(fut.result())
        assert all(c in (400, 403, 422) for c in codes)

        with Session(engine) as session:
            db_project = session.get(Project, project["id"])
            if db_project:
                session.delete(db_project)
                session.commit()
        client.delete(
            f"/api/hierarchy-configurations/{cfg['id']}?hard=true",
            headers=admin_headers,
        )

    def test_non_hm_viewer_cannot_generate(
        self, client, admin_headers, viewer_user
    ):
        headers, _ = viewer_user
        code = _unique("P3N")
        cfg = client.post(
            "/api/hierarchy-configurations/",
            headers=admin_headers,
            json={
                "code": code,
                "name": code,
                "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
                "nodes": [{"client_key": "s1", "level": "system", "name": "Comm"}],
            },
        ).json()
        project = client.post(
            "/api/projects/draft/",
            headers=admin_headers,
            json={
                "name": f"Gen-{code}",
                "hierarchy_config_id": cfg["id"],
                "product_type": "SSDLS-1",
                "flight_count": 1,
                "sdls_per_flight": 1,
            },
        ).json()
        client.post(
            f"/api/projects/{project['id']}/approve/",
            headers=admin_headers,
        )
        res = client.post(
            f"/api/projects/{project['id']}/generate-hierarchy/",
            headers=headers,
        )
        assert res.status_code in (401, 403)
        with Session(engine) as session:
            db_project = session.get(Project, project["id"])
            if db_project:
                session.delete(db_project)
                session.commit()
        client.delete(
            f"/api/hierarchy-configurations/{cfg['id']}?hard=true",
            headers=admin_headers,
        )


class TestSpec010203EndToEnd:
    """Mini E2E from roadmap: Admin config → draft → approve → generate."""

    def test_happy_path_pipeline(self, client, admin_headers):
        code = _unique("E2E")
        cfg = client.post(
            "/api/hierarchy-configurations/",
            headers=admin_headers,
            json={
                "code": code,
                "name": f"Pipeline {code}",
                "product_types": [{"code": "SSDLS-2", "name": "LDR"}],
                "nodes": _template_nodes("e2e"),
            },
        )
        assert cfg.status_code == 201, cfg.text
        cfg_id = cfg.json()["id"]

        draft = client.post(
            "/api/projects/draft/",
            headers=admin_headers,
            json={
                "name": f"Pipeline-{code}",
                "hierarchy_config_id": cfg_id,
                "product_type": "SSDLS-2",
                "flight_count": 1,
                "sdls_per_flight": 2,
            },
        )
        assert draft.status_code == 201
        pid = draft.json()["id"]
        assert draft.json()["status_name"] == "DRAFT"

        assert (
            client.post(
                f"/api/projects/{pid}/generate-hierarchy/", headers=admin_headers
            ).status_code
            != 200
        )

        assert (
            client.post(
                f"/api/projects/{pid}/approve/", headers=admin_headers
            ).json()["status_name"]
            == "APPROVED"
        )

        gen = client.post(
            f"/api/projects/{pid}/generate-hierarchy/", headers=admin_headers
        )
        assert gen.status_code == 200
        assert gen.json()["status"] == "READY_FOR_INVENTORY"
        assert gen.json()["counts"]["sdls"] == 2
        assert gen.json()["product_type"] == "SSDLS-2"

        tree = client.get(
            f"/api/projects/{pid}/hierarchy-tree/", headers=admin_headers
        ).json()
        assert len(tree["flights"]) == 1
        assert len(tree["flights"][0]["sdls"]) == 2

        history = client.get(
            "/api/audit/",
            headers=admin_headers,
            params={"project_id": pid, "limit": 50},
        )
        assert history.status_code == 200, history.text
        actions = [row["action"] for row in reversed(history.json())]
        for code in (
            "PROJECT_CREATED",
            "PROJECT_APPROVED",
            "HIERARCHY_GENERATED",
        ):
            assert code in actions, f"missing {code} in {actions}"
        assert actions.index("PROJECT_CREATED") < actions.index("PROJECT_APPROVED")
        assert actions.index("PROJECT_APPROVED") < actions.index("HIERARCHY_GENERATED")

        with Session(engine) as session:
            p = session.get(Project, pid)
            if p:
                session.delete(p)
                session.commit()
        client.delete(
            f"/api/hierarchy-configurations/{cfg_id}?hard=true",
            headers=admin_headers,
        )
