"""Spec 06 — reservation expiry (idle reminder + grace auto-release)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app.database import engine
from app.domain.workflow_status import ItemStatus
from app.models.base import AUTO_RELEASE_EXPIRY_REASON, ReservationExpiryNoticeType
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
from app.services.inventory_reservation_expiry_service import (
    auto_release_deadline,
    evaluate_reservation_expiry,
    idle_deadline,
    list_expiry_notices,
)
from app.services.inventory_reservation_service import (
    _aware,
    extend_reservation,
    get_item_status_id,
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
    sdls: int = 1,
    system_name: str = "Comm",
):
    code = f"R6-{uuid.uuid4().hex[:8].upper()}"
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
            "name": f"Exp-{code}",
            "hierarchy_config_id": cfg.id,
            "product_type": "SSDLS-1",
            "flight_count": flights,
            "sdls_per_flight": sdls,
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
        part_number="PN-EXP",
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
    session.commit()
    session.delete(project)
    session.commit()
    if inventory:
        session.refresh(inventory)
        for inst in list(inventory.instances or []):
            session.delete(inst)
        session.delete(inventory)
        session.commit()
    delete_configuration(session, cfg.id, hard=True)


def _reserve(session: Session, project: Project, admin: User, serial: str):
    system = session.exec(select(System).where(System.project_id == project.id)).first()
    assert system is not None
    row = reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(system.id),
            "serial_number": serial,
        },
        actor=admin,
    )
    session.refresh(row)
    return row, system


def test_day0_no_reminder(session: Session, admin_user: User):
    sys_name = f"Exp-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-E0"])
    row, _ = _reserve(session, project, admin_user, "SN-E0")

    result = evaluate_reservation_expiry(
        session, now=_aware(row.reserved_at), project_id=project.id
    )
    assert result["reminded"] == 0
    assert result["released"] == 0
    session.refresh(row)
    assert row.status == "active"
    assert row.last_reminder_at is None
    notices = list_expiry_notices(session, user_id=int(admin_user.id))
    assert all(n.reservation_id != row.id for n in notices)

    _cleanup(session, project, cfg, inv)


def test_day30_reminder_to_hm(session: Session, admin_user: User):
    sys_name = f"Exp-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-E30"])
    row, _ = _reserve(session, project, admin_user, "SN-E30")

    result = evaluate_reservation_expiry(
        session, now=idle_deadline(row), project_id=project.id
    )
    assert result["reminded"] == 1
    assert result["released"] == 0
    session.refresh(row)
    assert row.status == "active"
    assert row.last_reminder_at is not None

    notices = [
        n
        for n in list_expiry_notices(session, user_id=int(admin_user.id))
        if n.reservation_id == row.id
    ]
    assert len(notices) == 1
    assert notices[0].notice_type == ReservationExpiryNoticeType.REMINDER.value

    again = evaluate_reservation_expiry(
        session, now=idle_deadline(row), project_id=project.id
    )
    assert again["reminded"] == 0
    notices_after = [
        n
        for n in list_expiry_notices(session, user_id=int(admin_user.id))
        if n.reservation_id == row.id
    ]
    assert len(notices_after) == 1

    inst = session.get(InventoryInstance, row.inventory_instance_id)
    assert session.get(Status, inst.status_id).status_name == ItemStatus.RESERVED.value

    _cleanup(session, project, cfg, inv)


def test_day37_auto_release_available(session: Session, admin_user: User):
    sys_name = f"Exp-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-E37"])
    row, _ = _reserve(session, project, admin_user, "SN-E37")
    inst_id = row.inventory_instance_id

    result = evaluate_reservation_expiry(
        session, now=auto_release_deadline(row), project_id=project.id
    )
    assert result["released"] == 1
    session.refresh(row)
    assert row.status == "released"
    assert row.last_reminder_at is not None
    assert AUTO_RELEASE_EXPIRY_REASON in (row.notes or "")

    inst = session.get(InventoryInstance, inst_id)
    assert session.get(Status, inst.status_id).status_name == ItemStatus.AVAILABLE.value

    types = {
        n.notice_type
        for n in list_expiry_notices(session, user_id=int(admin_user.id))
        if n.reservation_id == row.id
    }
    assert ReservationExpiryNoticeType.REMINDER.value in types
    assert ReservationExpiryNoticeType.AUTO_RELEASED.value in types

    _cleanup(session, project, cfg, inv)


def test_issued_not_auto_released(session: Session, admin_user: User):
    sys_name = f"Exp-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-ISS"])
    row, _ = _reserve(session, project, admin_user, "SN-ISS")
    inst = session.get(InventoryInstance, row.inventory_instance_id)
    inst.status_id = get_item_status_id(session, ItemStatus.ISSUED.value)
    session.add(inst)
    session.commit()

    result = evaluate_reservation_expiry(
        session, now=auto_release_deadline(row), project_id=project.id
    )
    assert result["released"] == 0
    assert result["skipped_progressed"] >= 1
    session.refresh(row)
    assert row.status == "active"
    session.refresh(inst)
    assert session.get(Status, inst.status_id).status_name == ItemStatus.ISSUED.value

    _cleanup(session, project, cfg, inv)


def test_released_stock_reservable_by_other_project(session: Session, admin_user: User):
    sys_name = f"Exp-{uuid.uuid4().hex[:6]}"
    p1, cfg1 = _ready_project(session, admin_user, system_name=sys_name)
    p2, cfg2 = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-SHARE"])
    row, _ = _reserve(session, p1, admin_user, "SN-SHARE")

    evaluate_reservation_expiry(
        session, now=auto_release_deadline(row), project_id=p1.id
    )
    session.refresh(row)
    assert row.status == "released"

    s2 = session.exec(select(System).where(System.project_id == p2.id)).first()
    second = reserve_inventory(
        session,
        p2.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(s2.id),
            "serial_number": "SN-SHARE",
        },
        actor=admin_user,
    )
    assert second.status == "active"
    assert second.serial_number == "SN-SHARE"

    _cleanup(session, p1, cfg1)
    _cleanup(session, p2, cfg2, inv)


def test_extension_delays_expiry(session: Session, admin_user: User):
    sys_name = f"Exp-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-EXT"])
    row, _ = _reserve(session, project, admin_user, "SN-EXT")
    original_idle = idle_deadline(row)

    extended = extend_reservation(
        session, project.id, int(row.id), actor=admin_user
    )
    assert extended.extension_count == 1
    assert extended.last_reminder_at is None
    assert idle_deadline(extended) > original_idle

    still_idle = evaluate_reservation_expiry(
        session, now=original_idle, project_id=project.id
    )
    assert still_idle["reminded"] == 0
    session.refresh(extended)
    assert extended.status == "active"
    assert extended.last_reminder_at is None

    due = evaluate_reservation_expiry(
        session, now=idle_deadline(extended), project_id=project.id
    )
    assert due["reminded"] == 1
    session.refresh(extended)
    assert extended.last_reminder_at is not None

    _cleanup(session, project, cfg, inv)


def test_multiple_reservations_evaluated_independently(
    session: Session, admin_user: User
):
    sys_name = f"Exp-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, sdls=2, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-I1", "SN-I2"])
    systems = session.exec(
        select(System).where(System.project_id == project.id).order_by(System.id)
    ).all()
    a = reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(systems[0].id),
            "serial_number": "SN-I1",
        },
        actor=admin_user,
    )
    b = reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(systems[1].id),
            "serial_number": "SN-I2",
        },
        actor=admin_user,
    )
    session.refresh(a)
    session.refresh(b)
    b.expires_at = _aware(b.reserved_at) + timedelta(days=365)
    session.add(b)
    session.commit()
    session.refresh(b)

    result = evaluate_reservation_expiry(
        session, now=idle_deadline(a), project_id=project.id
    )
    assert result["reminded"] == 1
    session.refresh(a)
    session.refresh(b)
    assert a.last_reminder_at is not None
    assert b.last_reminder_at is None
    assert a.status == "active"
    assert b.status == "active"

    _cleanup(session, project, cfg, inv)
