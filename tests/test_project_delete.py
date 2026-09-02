"""Project hard-delete releases reserved stock; blocks after issue."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.auth import hash_password
from app.database import engine
from app.domain.hierarchy_config import InventorySource
from app.domain.workflow_status import ItemStatus
from app.models.tables import (
    Hierarchy,
    Inventory,
    InventoryInstance,
    InventoryItemRequest,
    InventoryIssuance,
    InventoryIssuanceEvent,
    InventoryInstallerNotice,
    InventoryReservation,
    InventoryReworkCase,
    InventoryShortage,
    InventoryShortageNotice,
    Project,
    Role,
    System,
    User,
)
from app.services.entity_list_service import find_entity_list_entry
from app.services.hierarchy_config_service import (
    create_configuration,
    delete_configuration,
)
from app.services.hierarchy_developer_service import assign_developer
from app.services.hierarchy_generation_service import generate_project_hierarchy
from app.services.hierarchy_service import get_next_hierarchy_id, sync_hierarchy_id_sequence
from app.services.inventory_reservation_service import (
    item_status_name,
    reserve_inventory,
)
from app.services.item_request_service import create_item_request, issue_item_request
from app.services.project_delete_service import (
    PROJECT_DELETE_BLOCKED_MESSAGE,
    ProjectDeleteError,
    delete_project,
)
from app.services.project_workflow_service import approve_project, create_draft_project
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.workflow_foundation_seed import ensure_workflow_statuses
from tests.test_issue_to_developer import _stock_for_system


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    ensure_user_management_schema()
    with Session(engine) as session:
        ensure_workflow_statuses(session)


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s


@pytest.fixture()
def admin_user(session: Session):
    user = session.exec(select(User).where(User.username == "admin")).first()
    if not user:
        pytest.skip("admin user required")
    return user


def _make_role_user(session: Session, *, role_name: str, full_name: str) -> User:
    role = session.exec(select(Role).where(Role.name == role_name)).first()
    if not role:
        pytest.skip(f"{role_name} role required")
    username = f"{role_name.lower()[:3]}_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name=full_name,
        is_active=True,
        password=hash_password("Dev@Test1"),
        updated_at=datetime.now(timezone.utc),
    )
    user.roles = [role]
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture()
def developer_user(session: Session):
    user = _make_role_user(session, role_name="Developer", full_name="Delete Dev")
    yield user
    session.delete(user)
    session.commit()


SIGNATURE = {
    "signature_type": "DIGITAL",
    "signature_payload": "data:image/png;base64,aaa",
}


def _ensure_catalog(session: Session, name: str, hierarchy_type: str) -> None:
    if find_entity_list_entry(session, name=name, hierarchy_type=hierarchy_type):
        return
    row = Hierarchy(
        id=get_next_hierarchy_id(session),
        name=name,
        hierarchy_type=hierarchy_type,
        abbreviation=name[:4].upper(),
    )
    session.add(row)
    session.commit()
    sync_hierarchy_id_sequence(session)


def _ready_project(session: Session, admin: User, system_name: str):
    _ensure_catalog(session, system_name, "system")
    code = f"DEL-{uuid.uuid4().hex[:8].upper()}"
    cfg = create_configuration(
        session,
        {
            "code": code,
            "name": code,
            "is_available": True,
            "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
            "nodes": [
                {
                    "client_key": "s1",
                    "level": "system",
                    "name": system_name,
                    "inventory_source": InventorySource.TURNKEY.value,
                },
            ],
        },
    )
    project = create_draft_project(
        session,
        {
            "name": f"Del-{code}",
            "hierarchy_config_id": cfg.id,
            "product_type": "SSDLS-1",
            "flight_count": 1,
            "sdls_per_flight": 1,
            "start_date": datetime.now(timezone.utc),
        },
        actor=admin,
    )
    approve_project(session, project.id, actor=admin)
    generate_project_hierarchy(session, project.id, actor=admin)
    session.refresh(project)
    return project, cfg


def _first_system(session: Session, project_id: int) -> System:
    row = session.exec(
        select(System).where(System.project_id == project_id).order_by(System.id)
    ).first()
    assert row is not None
    return row


def _cleanup_leftovers(session: Session, project_id: int | None, cfg, inventory: Inventory):
    try:
        session.rollback()
    except Exception:
        pass
    if project_id is not None and session.get(Project, project_id) is not None:
        for model in (
            InventoryItemRequest,
            InventoryReworkCase,
        ):
            rows = session.exec(select(model).where(model.project_id == project_id)).all()
            for row in rows:
                session.delete(row)
        session.flush()
        shortages = session.exec(
            select(InventoryShortage).where(InventoryShortage.project_id == project_id)
        ).all()
        shortage_ids = [row.id for row in shortages if row.id]
        if shortage_ids:
            for row in session.exec(
                select(InventoryShortageNotice).where(
                    InventoryShortageNotice.shortage_id.in_(shortage_ids)
                )
            ).all():
                session.delete(row)
            session.flush()
            for row in shortages:
                row.fulfilled_reservation_id = None
                session.add(row)
            session.flush()
            for row in shortages:
                session.delete(row)
            session.flush()
        for row in session.exec(
            select(InventoryReservation).where(
                InventoryReservation.project_id == project_id
            )
        ).all():
            session.delete(row)
        session.flush()
        issuances = session.exec(
            select(InventoryIssuance).where(InventoryIssuance.project_id == project_id)
        ).all()
        issuance_ids = [row.id for row in issuances if row.id]
        if issuance_ids:
            for row in session.exec(
                select(InventoryIssuanceEvent).where(
                    InventoryIssuanceEvent.issuance_id.in_(issuance_ids)
                )
            ).all():
                session.delete(row)
            for row in session.exec(
                select(InventoryInstallerNotice).where(
                    InventoryInstallerNotice.issuance_id.in_(issuance_ids)
                )
            ).all():
                session.delete(row)
            session.flush()
            for row in issuances:
                session.delete(row)
            session.flush()
        project = session.get(Project, project_id)
        if project:
            session.delete(project)
            session.commit()
    session.refresh(inventory)
    for inst in list(inventory.instances or []):
        session.delete(inst)
    session.delete(inventory)
    session.commit()
    delete_configuration(session, cfg.id, hard=True)


def test_delete_releases_reserved_and_assigned_inventory(
    session: Session, admin_user: User, developer_user: User
):
    name = f"DelSys-{uuid.uuid4().hex[:6]}"
    serial = f"SN-DEL-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, name)
    inventory = _stock_for_system(session, name=name, serials=[serial])
    project_id = int(project.id)
    try:
        system = _first_system(session, project_id)
        assign_developer(
            session, "system", int(system.id), int(developer_user.id), actor=admin_user
        )
        reservation = reserve_inventory(
            session,
            project_id,
            {
                "target_entity_type": "system",
                "target_entity_id": int(system.id),
                "serial_number": serial,
            },
            actor=admin_user,
        )
        assert reservation.inventory_instance_id
        instance = session.get(InventoryInstance, reservation.inventory_instance_id)
        assert instance is not None
        assert (
            item_status_name(session, instance.status_id) == ItemStatus.RESERVED.value
        )

        result = delete_project(session, project_id, actor=admin_user)
        assert result["ok"] is True
        assert result["reserved_released"] == 1
        assert session.get(Project, project_id) is None

        session.refresh(instance)
        assert (
            item_status_name(session, instance.status_id) == ItemStatus.AVAILABLE.value
        )
        project_id = None
    finally:
        _cleanup_leftovers(session, project_id, cfg, inventory)


def test_delete_blocked_after_issue_to_developer(
    session: Session, admin_user: User, developer_user: User
):
    name = f"DelIss-{uuid.uuid4().hex[:6]}"
    serial = f"SN-ISS-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, name)
    inventory = _stock_for_system(session, name=name, serials=[serial])
    project_id = int(project.id)
    try:
        system = _first_system(session, project_id)
        reserve_inventory(
            session,
            project_id,
            {
                "target_entity_type": "system",
                "target_entity_id": int(system.id),
                "serial_number": serial,
            },
            actor=admin_user,
        )
        assign_developer(
            session, "system", int(system.id), int(developer_user.id), actor=admin_user
        )
        req = create_item_request(
            session, entity_type="system", entity_id=int(system.id), actor=developer_user
        )
        issue_item_request(session, int(req.id), actor=admin_user, **SIGNATURE)

        with pytest.raises(ProjectDeleteError, match="cannot be deleted"):
            delete_project(session, project_id, actor=admin_user)

        assert session.get(Project, project_id) is not None
        assert PROJECT_DELETE_BLOCKED_MESSAGE
    finally:
        _cleanup_leftovers(session, project_id, cfg, inventory)


def test_delete_project_without_inventory(session: Session, admin_user: User):
    name = f"DelEmpty-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, name)
    project_id = int(project.id)
    try:
        result = delete_project(session, project_id, actor=admin_user)
        assert result["ok"] is True
        assert result["reserved_released"] == 0
        assert session.get(Project, project_id) is None
        project_id = None
    finally:
        if project_id is not None and session.get(Project, project_id) is not None:
            session.delete(session.get(Project, project_id))
            session.commit()
        delete_configuration(session, cfg.id, hard=True)
