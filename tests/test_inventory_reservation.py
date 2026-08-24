"""Spec 04 — inventory reservation against Flight → SDLS → hierarchy."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.database import engine
from app.domain.workflow_status import ItemStatus, ProjectWorkflowStatus
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryReservation,
    Project,
    Status,
    System,
    User,
)
from app.services.hierarchy_config_service import (
    create_configuration,
    delete_configuration,
)
from app.services.hierarchy_generation_service import generate_project_hierarchy
from app.services.inventory_reservation_service import (
    InventoryReservationError,
    build_reservation_plan,
    check_availability,
    list_project_reservations,
    release_reservation,
    reserve_inventory,
)
from app.services.inventory_service import create_inventory_instance
from app.services.project_workflow_service import approve_project, create_draft_project
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.workflow_foundation_seed import ensure_workflow_statuses


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


def _item_status_id(session: Session, name: str) -> int:
    row = session.exec(
        select(Status).where(
            Status.status_name == name, Status.status_type == "inventory"
        )
    ).first()
    assert row and row.id
    return int(row.id)


def _ready_project(
    session: Session,
    admin: User,
    *,
    flights: int = 1,
    sdls: int = 2,
    system_name: str = "Comm",
):
    code = f"R4-{uuid.uuid4().hex[:8].upper()}"
    cfg = create_configuration(
        session,
        {
            "code": code,
            "name": code,
            "is_available": True,
            "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
            "nodes": [
                {"client_key": "s1", "level": "system", "name": system_name},
                {
                    "client_key": "sub1",
                    "parent_client_key": "s1",
                    "level": "subsystem",
                    "name": "RF",
                },
            ],
        },
    )
    project = create_draft_project(
        session,
        {
            "name": f"Res-{code}",
            "hierarchy_config_id": cfg.id,
            "product_type": "SSDLS-1",
            "flight_count": flights,
            "sdls_per_flight": sdls,
            "start_date": datetime.now(timezone.utc),
        },
        actor=admin,
    )
    approve_project(session, project.id, actor=admin)
    generate_project_hierarchy(session, project.id, actor=admin)
    session.refresh(project)
    return project, cfg


def _stock_for_system(
    session: Session, *, name: str, serials: list[str]
) -> Inventory:
    from sqlalchemy import text

    available_id = _item_status_id(session, ItemStatus.AVAILABLE.value)
    session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('inventory', 'id'), "
            "GREATEST(COALESCE((SELECT MAX(id) FROM inventory), 1), 1))"
        )
    )
    session.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('inventoryinstance', 'id'), "
            "GREATEST(COALESCE((SELECT MAX(id) FROM inventoryinstance), 1), 1))"
        )
    )
    inv = Inventory(
        name=name,
        inventory_type="system",
        quantity=0,
        part_number=None,
        status_id=available_id,
    )
    session.add(inv)
    session.flush()
    for sn in serials:
        create_inventory_instance(
            session,
            inv,
            serial_number=sn,
            status_id=available_id,
        )
    session.commit()
    session.refresh(inv)
    return inv


def _cleanup(session: Session, project: Project, cfg, inventory: Inventory | None = None):
    rows = session.exec(
        select(InventoryReservation).where(
            InventoryReservation.project_id == project.id
        )
    ).all()
    for row in rows:
        session.delete(row)
    session.delete(project)
    session.commit()
    if inventory:
        for inst in list(inventory.instances or []):
            session.delete(inst)
        session.delete(inventory)
        session.commit()
    delete_configuration(session, cfg.id, hard=True)


def test_cannot_reserve_before_ready(session: Session, admin_user: User):
    code = f"R4D-{uuid.uuid4().hex[:6].upper()}"
    cfg = create_configuration(
        session,
        {
            "code": code,
            "name": code,
            "is_available": True,
            "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
            "nodes": [{"client_key": "s1", "level": "system", "name": "Comm"}],
        },
    )
    project = create_draft_project(
        session,
        {
            "name": f"Draft-{code}",
            "hierarchy_config_id": cfg.id,
            "product_type": "SSDLS-1",
            "flight_count": 1,
            "sdls_per_flight": 1,
        },
        actor=admin_user,
    )
    with pytest.raises(InventoryReservationError, match="READY_FOR_INVENTORY"):
        reserve_inventory(
            session,
            project.id,
            {
                "target_entity_type": "system",
                "target_entity_id": 1,
            },
            actor=admin_user,
        )
    session.delete(project)
    session.commit()
    delete_configuration(session, cfg.id, hard=True)


def test_reserve_and_release_serialized_unit(session: Session, admin_user: User):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(
        session, admin_user, flights=1, sdls=2, system_name=sys_name
    )
    inv = _stock_for_system(
        session, name=sys_name, serials=["SN-A1", "SN-A2", "SN-A3"]
    )
    systems = session.exec(
        select(System).where(System.project_id == project.id)
    ).all()
    assert len(systems) == 2
    target = systems[0]

    avail = check_availability(
        session,
        project_id=project.id,
        target_entity_type="system",
        target_entity_id=int(target.id),
    )
    assert avail["available"] is True
    assert avail["free_quantity"] == 3

    row = reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target.id),
            "serial_number": "SN-A1",
        },
        actor=admin_user,
    )
    assert row.status == "active"
    assert row.serial_number == "SN-A1"
    assert row.flight_id is not None
    assert row.sdls_id is not None
    assert row.expires_at is not None
    assert row.reserved_by_user_id == admin_user.id

    session.refresh(row)
    inst = session.get(InventoryInstance, row.inventory_instance_id)
    assert inst is not None
    status_name = session.get(Status, inst.status_id).status_name
    assert status_name == ItemStatus.RESERVED.value

    # Same serial cannot be reserved again
    other = systems[1]
    with pytest.raises(InventoryReservationError, match="not available|already"):
        reserve_inventory(
            session,
            project.id,
            {
                "target_entity_type": "system",
                "target_entity_id": int(other.id),
                "serial_number": "SN-A1",
            },
            actor=admin_user,
        )

    released = release_reservation(
        session, project.id, int(row.id), actor=admin_user
    )
    assert released.status == "released"
    session.refresh(inst)
    assert session.get(Status, inst.status_id).status_name == ItemStatus.AVAILABLE.value

    _cleanup(session, project, cfg, inv)


def test_two_projects_compete_for_one_unit(session: Session, admin_user: User):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    p1, cfg1 = _ready_project(
        session, admin_user, flights=1, sdls=1, system_name=sys_name
    )
    p2, cfg2 = _ready_project(
        session, admin_user, flights=1, sdls=1, system_name=sys_name
    )
    inv = _stock_for_system(session, name=sys_name, serials=["SN-ONLY"])

    s1 = session.exec(select(System).where(System.project_id == p1.id)).first()
    s2 = session.exec(select(System).where(System.project_id == p2.id)).first()

    reserve_inventory(
        session,
        p1.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(s1.id),
            "serial_number": "SN-ONLY",
        },
        actor=admin_user,
    )
    with pytest.raises(InventoryReservationError):
        reserve_inventory(
            session,
            p2.id,
            {
                "target_entity_type": "system",
                "target_entity_id": int(s2.id),
                "serial_number": "SN-ONLY",
            },
            actor=admin_user,
        )

    _cleanup(session, p1, cfg1)
    _cleanup(session, p2, cfg2, inv)


def test_reserve_three_units_across_sdls(session: Session, admin_user: User):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(
        session, admin_user, flights=1, sdls=3, system_name=sys_name
    )
    inv = _stock_for_system(
        session, name=sys_name, serials=["SN-1", "SN-2", "SN-3"]
    )
    systems = session.exec(
        select(System).where(System.project_id == project.id).order_by(System.id)
    ).all()
    assert len(systems) == 3

    for idx, system in enumerate(systems):
        reserve_inventory(
            session,
            project.id,
            {
                "target_entity_type": "system",
                "target_entity_id": int(system.id),
                "serial_number": f"SN-{idx + 1}",
            },
            actor=admin_user,
        )

    active = list_project_reservations(session, project.id, active_only=True)
    assert len(active) == 3
    assert {r.serial_number for r in active} == {"SN-1", "SN-2", "SN-3"}
    assert project.status.status_name == ProjectWorkflowStatus.READY_FOR_INVENTORY.value

    _cleanup(session, project, cfg, inv)


def test_reserved_serial_exposes_project_hold(session: Session, admin_user: User):
    sys_name = f"Hold-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(
        session, admin_user, flights=1, sdls=1, system_name=sys_name
    )
    inv = _stock_for_system(session, name=sys_name, serials=["SN-HOLD"])
    target = session.exec(select(System).where(System.project_id == project.id)).first()
    row = reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target.id),
            "serial_number": "SN-HOLD",
        },
        actor=admin_user,
    )
    from app.services.inventory_reservation_service import (
        item_status_name,
        project_holds_by_instance_id,
    )

    inst = session.get(InventoryInstance, row.inventory_instance_id)
    assert item_status_name(session, inst.status_id) == ItemStatus.RESERVED.value
    holds = project_holds_by_instance_id(session, int(inv.id))
    hold = holds[int(row.inventory_instance_id)]
    assert hold["flight_id"] == row.flight_id
    assert hold["sdls_id"] == row.sdls_id
    assert hold["target_entity_id"] == int(target.id)
    assert hold["target_entity_type"] == "system"
    assert hold["serial_number"] == "SN-HOLD"

    _cleanup(session, project, cfg, inv)


def test_reservation_plan_matches_available_and_short(
    session: Session, admin_user: User
):
    project, cfg = _ready_project(
        session, admin_user, flights=1, sdls=1, system_name="Comm"
    )
    inv = _stock_for_system(session, name="Comm", serials=["SN-PLAN-1"])
    plan = build_reservation_plan(session, int(project.id))
    assert plan["total"] >= 1
    system_rows = [
        row for row in plan["items"] if row["target_entity_type"] == "system"
    ]
    assert len(system_rows) == 1
    assert system_rows[0]["status"] == "available"
    assert system_rows[0]["suggested_serial"] == "SN-PLAN-1"
    assert plan["available_count"] >= 1
    _cleanup(session, project, cfg, inv)
