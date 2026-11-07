"""Shared fixtures/helpers for MHD Occurrence + Dual-Track FT/ST (P0–P2)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import engine
from app.main import app
from app.models.base import CaseStatus, EntityType, FaultType, FaultyEntityStatus
from app.models.tables import FaultyEntity, MaintenanceCase, Project, User
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.workflow_foundation_seed import ensure_workflow_statuses

ADMIN_USER = "admin"
ADMIN_PASS = "password@82768243"

FRONTEND_FIELD_PANEL = (
    Path(__file__).resolve().parents[2]
    / "plcm-frontend"
    / "components"
    / "maintenance"
    / "field-service-panels.tsx"
)


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_mhd():
    ensure_user_management_schema()
    with Session(engine) as session:
        ensure_workflow_statuses(session)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s


def login(client: TestClient, username: str = ADMIN_USER, password: str = ADMIN_PASS) -> dict:
    from app.services.security_settings_service import DEFAULT_ADMIN_SESSION_SUPER_PASSWORD

    res = client.post("/api/auth/login", data={"username": username, "password": password})
    if res.status_code == 409:
        # Force takeover when another device/session holds the account (common for admin).
        res = client.post(
            "/api/auth/login",
            data={
                "username": username,
                "password": password,
                "super_password": DEFAULT_ADMIN_SESSION_SUPER_PASSWORD,
            },
            params={"force_session_takeover": True},
        )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def admin_headers(client: TestClient):
    return login(client)


@pytest.fixture()
def admin_user(session: Session):
    user = session.exec(select(User).where(User.username == ADMIN_USER)).first()
    if not user:
        pytest.skip("admin user required")
    return user


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_project_and_case(
    session: Session,
    admin: User,
    *,
    description: str | None = None,
    entity_type: str = "unit",
    entity_id: int | None = None,
) -> tuple[Project, MaintenanceCase]:
    now = datetime.now(timezone.utc)
    project = Project(
        name=unique("MHD-P"),
        description="MHD verification fixture",
        start_date=now,
        owner_id=int(admin.id),
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    eid = entity_id if entity_id is not None else int(uuid.uuid4().int % 900000) + 1000
    case = MaintenanceCase(
        case_number=unique("MC"),
        project_id=int(project.id),
        project_name=project.name,
        description=description or "MHD occurrence/dual-track fixture case",
        status=CaseStatus.OPEN,
        reported_by=int(admin.id),
        entity_type=entity_type,
        entity_id=eid,
        part_number="PN-MHD-100",
        reported_at=now,
    )
    session.add(case)
    session.commit()
    session.refresh(case)
    return project, case


def add_faulty_entity(session: Session, case: MaintenanceCase, *, actor_id: int) -> FaultyEntity:
    fe = FaultyEntity(
        case_id=int(case.id),
        entity_type=EntityType.UNIT,
        entity_id=int(case.entity_id or 1),
        fault_type=FaultType.HARDWARE,
        fault_description="MHD fixture fault",
        status=FaultyEntityStatus.IDENTIFIED,
        identified_by=actor_id,
        part_number=case.part_number,
        serial_number=unique("SN"),
        entity_name="MHD Unit",
    )
    session.add(fe)
    session.commit()
    session.refresh(fe)
    return fe


def cleanup_project(session: Session, project: Project) -> None:
    """Delete MHD fixture project and related rows that lack ON DELETE CASCADE."""
    from app.models.tables import (
        MaintenanceCase,
        MaintenanceOccurrenceAttachment,
        MaintenanceOccurrenceOfficer,
        ReplacementRequest,
        ReplacementRequestReservation,
        AppNotification,
        InventoryReworkCase,
    )

    try:
        cases = session.exec(
            select(MaintenanceCase).where(MaintenanceCase.project_id == project.id)
        ).all()
        case_ids = [int(c.id) for c in cases if c.id is not None]
        for cid in case_ids:
            reqs = session.exec(
                select(ReplacementRequest).where(ReplacementRequest.case_id == cid)
            ).all()
            for req in reqs:
                links = session.exec(
                    select(ReplacementRequestReservation).where(
                        ReplacementRequestReservation.replacement_request_id == req.id
                    )
                ).all()
                for link in links:
                    session.delete(link)
                session.delete(req)
            for row in session.exec(
                select(MaintenanceOccurrenceAttachment).where(
                    MaintenanceOccurrenceAttachment.case_id == cid
                )
            ).all():
                session.delete(row)
            for row in session.exec(
                select(MaintenanceOccurrenceOfficer).where(
                    MaintenanceOccurrenceOfficer.case_id == cid
                )
            ).all():
                session.delete(row)
            for row in session.exec(
                select(InventoryReworkCase).where(
                    InventoryReworkCase.maintenance_case_id == cid
                )
            ).all():
                session.delete(row)
            for row in session.exec(
                select(AppNotification).where(
                    AppNotification.entity_type == "maintenance_case",
                    AppNotification.entity_id == cid,
                )
            ).all():
                session.delete(row)
        session.commit()
        row = session.get(Project, project.id)
        if row:
            session.delete(row)
            session.commit()
    except Exception:
        session.rollback()
        # Best-effort; leave fixture rows if DB constraints block cleanup
        pass


def occurrence_payload(**overrides) -> dict:
    base = {
        "onsite_outcome": "inconclusive",
        "notes": "mhd ft",
    }
    base.update(overrides)
    return base


def fault_identified_payload(**overrides) -> dict:
    base = {
        "onsite_outcome": "fault_identified",
        "fault_type": "hardware",
        "confirmation_channel": "email",
        "confirmation_reference": "REF-MHD-1",
        "notes": "fault found",
        "occurrence_date": "2026-03-15T00:00:00Z",
    }
    base.update(overrides)
    return base
