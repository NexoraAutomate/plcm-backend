"""Spec 04 — inventory reservation against Flight → SDLS → hierarchy."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.database import engine
from app.domain.hierarchy_config import InventorySource
from app.domain.workflow_status import ItemStatus, ProjectWorkflowStatus
from app.models.tables import (
    Hierarchy,
    Inventory,
    InventoryInstance,
    InventoryReservation,
    Project,
    Status,
    Subsystem,
    System,
    User,
)
from app.services.entity_list_service import find_entity_list_entry
from app.services.hierarchy_config_service import (
    create_configuration,
    delete_configuration,
)
from app.services.hierarchy_generation_service import generate_project_hierarchy
from app.services.hierarchy_service import get_next_hierarchy_id, sync_hierarchy_id_sequence
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
    _ensure_catalog(session, system_name, "system")
    _ensure_catalog(session, "RF", "subsystem")
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


def _stock_for_entity(
    session: Session, *, name: str, inventory_type: str, serials: list[str]
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
        inventory_type=inventory_type,
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


def _stock_for_system(
    session: Session, *, name: str, serials: list[str]
) -> Inventory:
    return _stock_for_entity(
        session, name=name, inventory_type="system", serials=serials
    )


def _subsystems(session: Session, project_id: int) -> list[Subsystem]:
    return list(
        session.exec(
            select(Subsystem)
            .join(System, Subsystem.system_id == System.id)
            .where(System.project_id == project_id)
            .order_by(Subsystem.id)
        ).all()
    )


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
    _ensure_catalog(session, "Comm", "system")
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
    project, cfg = _ready_project(session, admin_user, flights=1, sdls=2)
    inv = _stock_for_entity(
        session, name="RF", inventory_type="subsystem", serials=["SN-A1", "SN-A2", "SN-A3"]
    )
    subsystems = _subsystems(session, int(project.id))
    assert len(subsystems) == 2
    target = subsystems[0]

    avail = check_availability(
        session,
        project_id=project.id,
        target_entity_type="subsystem",
        target_entity_id=int(target.id),
    )
    assert avail["available"] is True
    assert avail["free_quantity"] == 3

    row = reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "subsystem",
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
    other = subsystems[1]
    with pytest.raises(InventoryReservationError, match="not available|already"):
        reserve_inventory(
            session,
            project.id,
            {
                "target_entity_type": "subsystem",
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
    p1, cfg1 = _ready_project(session, admin_user, flights=1, sdls=1)
    p2, cfg2 = _ready_project(session, admin_user, flights=1, sdls=1)
    inv = _stock_for_entity(
        session, name="RF", inventory_type="subsystem", serials=["SN-ONLY"]
    )

    s1 = _subsystems(session, int(p1.id))[0]
    s2 = _subsystems(session, int(p2.id))[0]

    reserve_inventory(
        session,
        p1.id,
        {
            "target_entity_type": "subsystem",
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
                "target_entity_type": "subsystem",
                "target_entity_id": int(s2.id),
                "serial_number": "SN-ONLY",
            },
            actor=admin_user,
        )

    _cleanup(session, p1, cfg1)
    _cleanup(session, p2, cfg2, inv)


def test_reserve_three_units_across_sdls(session: Session, admin_user: User):
    project, cfg = _ready_project(session, admin_user, flights=1, sdls=3)
    inv = _stock_for_entity(
        session, name="RF", inventory_type="subsystem", serials=["SN-1", "SN-2", "SN-3"]
    )
    subsystems = _subsystems(session, int(project.id))
    assert len(subsystems) == 3

    for idx, subsystem in enumerate(subsystems):
        reserve_inventory(
            session,
            project.id,
            {
                "target_entity_type": "subsystem",
                "target_entity_id": int(subsystem.id),
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
    project, cfg = _ready_project(session, admin_user, flights=1, sdls=1)
    inv = _stock_for_entity(
        session, name="RF", inventory_type="subsystem", serials=["SN-HOLD"]
    )
    target = _subsystems(session, int(project.id))[0]
    row = reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "subsystem",
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
    assert hold["target_entity_type"] == "subsystem"
    assert hold["serial_number"] == "SN-HOLD"

    _cleanup(session, project, cfg, inv)


def test_reservation_plan_hides_committed_units(session: Session, admin_user: User):
    project, cfg = _ready_project(session, admin_user, flights=1, sdls=1)
    inv = _stock_for_entity(
        session, name="RF", inventory_type="subsystem", serials=["SN-LOCK-1", "SN-LOCK-2"]
    )
    try:
        target = _subsystems(session, int(project.id))[0]
        reserve_inventory(
            session,
            int(project.id),
            {
                "target_entity_type": "subsystem",
                "target_entity_id": int(target.id),
                "serial_number": "SN-LOCK-1",
            },
            actor=admin_user,
        )
        plan = build_reservation_plan(session, int(project.id))
        row = next(
            item
            for item in plan["items"]
            if item["target_entity_type"] == "subsystem"
            and item["target_entity_id"] == int(target.id)
        )
        assert row["status"] == "reserved"
        assert row["available"] is False
        assert row["suggested_serial"] == "SN-LOCK-1"
        assert row["item_status"] == ItemStatus.RESERVED.value

        with pytest.raises(InventoryReservationError, match="Reserved"):
            reserve_inventory(
                session,
                int(project.id),
                {
                    "target_entity_type": "subsystem",
                    "target_entity_id": int(target.id),
                    "serial_number": "SN-LOCK-2",
                },
                actor=admin_user,
            )
    finally:
        _cleanup(session, project, cfg, inv)


def test_reservation_plan_matches_available_and_short(
    session: Session, admin_user: User
):
    project, cfg = _ready_project(session, admin_user, flights=1, sdls=1)
    inv = _stock_for_entity(
        session, name="RF", inventory_type="subsystem", serials=["SN-PLAN-1"]
    )
    plan = build_reservation_plan(session, int(project.id))
    assert plan["total"] >= 1
    system_rows = [
        row for row in plan["items"] if row["target_entity_type"] == "system"
    ]
    subsystem_rows = [
        row for row in plan["items"] if row["target_entity_type"] == "subsystem"
    ]
    assert len(system_rows) == 1
    assert system_rows[0]["status"] == "assemble"
    assert len(subsystem_rows) == 1
    assert subsystem_rows[0]["status"] == "available"
    assert subsystem_rows[0]["suggested_serial"] == "SN-PLAN-1"
    assert plan["available_count"] >= 1
    _cleanup(session, project, cfg, inv)


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


def _ready_build_project(session: Session, admin: User, *, system_name: str, child_name: str):
    _ensure_catalog(session, system_name, "system")
    _ensure_catalog(session, child_name, "subsystem")
    code = f"R4B-{uuid.uuid4().hex[:8].upper()}"
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
                    "inventory_source": InventorySource.BUILD_FROM_CHILDREN.value,
                },
                {
                    "client_key": "sub1",
                    "parent_client_key": "s1",
                    "level": "subsystem",
                    "name": child_name,
                    "inventory_source": InventorySource.TURNKEY.value,
                },
            ],
        },
    )
    project = create_draft_project(
        session,
        {
            "name": f"Build-{code}",
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


def test_build_node_plan_is_assemble_even_with_warehouse_stock(
    session: Session, admin_user: User
):
    """BUILD + existing inventory must NOT be Available / Reserve."""
    sys_name = f"BuildSys-{uuid.uuid4().hex[:6]}"
    child_name = f"Child-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_build_project(
        session, admin_user, system_name=sys_name, child_name=child_name
    )
    inv = _stock_for_system(
        session,
        name=sys_name,
        serials=[f"SN-B{i}" for i in range(1, 11)],
    )
    try:
        system = session.exec(
            select(System).where(System.project_id == project.id)
        ).first()
        assert system is not None
        assert system.inventory_source == InventorySource.BUILD_FROM_CHILDREN.value

        avail = check_availability(
            session,
            project_id=int(project.id),
            target_entity_type="system",
            target_entity_id=int(system.id),
        )
        assert avail["available"] is False
        assert avail["assemble"] is True
        assert avail["inventory_source"] == InventorySource.BUILD_FROM_CHILDREN.value
        assert avail["free_quantity"] == 0

        plan = build_reservation_plan(session, int(project.id))
        system_rows = [
            row for row in plan["items"] if row["target_entity_type"] == "system"
        ]
        assert len(system_rows) == 1
        assert system_rows[0]["status"] == "assemble"
        assert system_rows[0]["inventory_source"] == InventorySource.BUILD_FROM_CHILDREN.value
        assert system_rows[0]["children_total"] == 1
        assert system_rows[0]["children_complete"] == 0
        assert plan["assemble_count"] >= 1

        with pytest.raises(InventoryReservationError, match="build-from-children"):
            reserve_inventory(
                session,
                int(project.id),
                {
                    "target_entity_type": "system",
                    "target_entity_id": int(system.id),
                    "serial_number": "SN-B1",
                },
                actor=admin_user,
            )
    finally:
        _cleanup(session, project, cfg, inv)


def test_build_node_null_source_healed_from_config(
    session: Session, admin_user: User
):
    """Legacy NULL inventory_source must resolve from project config, not stock."""
    sys_name = f"NullSrc-{uuid.uuid4().hex[:6]}"
    child_name = f"Leaf-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_build_project(
        session, admin_user, system_name=sys_name, child_name=child_name
    )
    inv = _stock_for_system(session, name=sys_name, serials=["SN-NULL-1", "SN-NULL-2"])
    try:
        system = session.exec(
            select(System).where(System.project_id == project.id)
        ).first()
        assert system is not None
        system.inventory_source = None
        session.add(system)
        session.commit()
        session.refresh(system)
        assert system.inventory_source is None

        plan = build_reservation_plan(session, int(project.id))
        system_rows = [
            row for row in plan["items"] if row["target_entity_type"] == "system"
        ]
        assert len(system_rows) == 1
        assert system_rows[0]["status"] == "assemble"
        assert (
            system_rows[0]["inventory_source"]
            == InventorySource.BUILD_FROM_CHILDREN.value
        )

        session.refresh(system)
        assert system.inventory_source == InventorySource.BUILD_FROM_CHILDREN.value

        with pytest.raises(InventoryReservationError, match="build-from-children"):
            reserve_inventory(
                session,
                int(project.id),
                {
                    "target_entity_type": "system",
                    "target_entity_id": int(system.id),
                },
                actor=admin_user,
            )
    finally:
        _cleanup(session, project, cfg, inv)


def test_parent_with_children_shows_assemble_despite_turnkey_config(
    session: Session, admin_user: User
):
    """System/subsystem/module with runtime children must not match warehouse stock."""
    sys_name = f"Parent-{uuid.uuid4().hex[:6]}"
    sub_name = "RF"
    project, cfg = _ready_build_project(
        session, admin_user, system_name=sys_name, child_name=sub_name
    )
    inv = _stock_for_system(session, name=sys_name, serials=["SN-X1", "SN-X2"])
    try:
        system = session.exec(
            select(System).where(System.project_id == project.id)
        ).first()
        assert system is not None
        system.inventory_source = InventorySource.TURNKEY.value
        session.add(system)
        session.commit()

        plan = build_reservation_plan(session, int(project.id))
        system_row = next(
            row
            for row in plan["items"]
            if row["target_entity_type"] == "system"
        )
        assert system_row["status"] == "assemble"
        assert system_row["inventory_source"] == InventorySource.BUILD_FROM_CHILDREN.value
    finally:
        _cleanup(session, project, cfg, inv)


def test_build_node_zero_stock_is_assemble_not_short(
    session: Session, admin_user: User
):
    sys_name = f"ZeroBuild-{uuid.uuid4().hex[:6]}"
    child_name = f"ZChild-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_build_project(
        session, admin_user, system_name=sys_name, child_name=child_name
    )
    try:
        plan = build_reservation_plan(session, int(project.id))
        system_rows = [
            row for row in plan["items"] if row["target_entity_type"] == "system"
        ]
        assert len(system_rows) == 1
        assert system_rows[0]["status"] == "assemble"
        assert system_rows[0]["status"] != "short"
    finally:
        _cleanup(session, project, cfg)
