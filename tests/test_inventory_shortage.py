"""Spec 05 — shortage create, notify, FCFS auto-reserve on receipt."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.database import engine
from app.domain.workflow_status import ItemStatus
from app.models.base import ShortageStatus
from app.models.tables import (
    Inventory,
    InventoryReservation,
    InventoryShortage,
    InventoryShortageNotice,
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
    item_status_name,
    list_project_reservations,
    reserve_inventory,
)
from app.services.inventory_service import create_inventory_instance
from app.services.inventory_shortage_service import (
    InventoryShortageCreated,
    cancel_shortage,
    match_and_auto_reserve_on_receipt,
)
from app.services.project_workflow_service import approve_project, create_draft_project
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.workflow_foundation_seed import ensure_workflow_statuses

AUTO_NOTE_FRAGMENT = "shortage fulfillment"


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
    code = f"R5-{uuid.uuid4().hex[:8].upper()}"
    cfg = create_configuration(
        session,
        {
            "code": code,
            "name": code,
            "is_available": True,
            "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
            "nodes": [
                {"client_key": "s1", "level": "system", "name": system_name},
            ],
        },
    )
    project = create_draft_project(
        session,
        {
            "name": f"Short-{code}",
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
    session: Session,
    *,
    name: str,
    serials: list[str],
    part_number: str | None = "PN-SHORT",
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
        part_number=part_number,
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


def _first_system(session: Session, project: Project) -> System:
    systems = session.exec(
        select(System).where(System.project_id == project.id)
    ).all()
    assert systems
    return systems[0]


def _cleanup(
    session: Session,
    projects: list[Project],
    cfgs,
    inventory: Inventory | None = None,
):
    if not isinstance(cfgs, list):
        cfgs = [cfgs]
    project_ids = [int(p.id) for p in projects if p.id]
    shortages = session.exec(
        select(InventoryShortage).where(InventoryShortage.project_id.in_(project_ids))
    ).all()
    shortage_ids = [int(s.id) for s in shortages if s.id]
    if shortage_ids:
        notices = session.exec(
            select(InventoryShortageNotice).where(
                InventoryShortageNotice.shortage_id.in_(shortage_ids)
            )
        ).all()
        for notice in notices:
            session.delete(notice)
        session.commit()
        for row in shortages:
            session.delete(row)
        session.commit()
    for project in projects:
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
        session.refresh(inventory)
        for inst in list(inventory.instances or []):
            session.delete(inst)
        session.delete(inventory)
        session.commit()
    for cfg in cfgs:
        delete_configuration(session, cfg.id, hard=True)


def test_reserve_when_stock_zero_creates_shortage_and_notices(
    session: Session, admin_user: User
):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    target = _first_system(session, project)

    with pytest.raises(InventoryShortageCreated) as caught:
        reserve_inventory(
            session,
            project.id,
            {"target_entity_type": "system", "target_entity_id": int(target.id)},
            actor=admin_user,
        )

    shortage = caught.value.shortage
    assert shortage.status == ShortageStatus.OPEN.value
    assert shortage.qty_short == 1
    assert shortage.lru_name == sys_name
    notices = session.exec(
        select(InventoryShortageNotice).where(
            InventoryShortageNotice.shortage_id == shortage.id
        )
    ).all()
    assert notices
    payload = notices[0]
    assert payload.qty == 1
    assert payload.lru_name == sys_name
    assert payload.flight_name or payload.flight_code
    assert payload.sdls_name or payload.sdls_code
    assert "PN" in (payload.message or "")
    assert "Qty" in (payload.message or "")
    assert "Flight" in (payload.message or "")
    assert "SDLS" in (payload.message or "")
    assert "LRU" in (payload.message or "")
    _cleanup(session, [project], cfg)


def test_fcfs_earlier_shortage_wins_first_unit(session: Session, admin_user: User):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project_a, cfg_a = _ready_project(session, admin_user, system_name=sys_name)
    project_b, cfg_b = _ready_project(session, admin_user, system_name=sys_name)
    target_a = _first_system(session, project_a)
    target_b = _first_system(session, project_b)

    with pytest.raises(InventoryShortageCreated):
        reserve_inventory(
            session,
            project_a.id,
            {"target_entity_type": "system", "target_entity_id": int(target_a.id)},
            actor=admin_user,
        )
    with pytest.raises(InventoryShortageCreated):
        reserve_inventory(
            session,
            project_b.id,
            {"target_entity_type": "system", "target_entity_id": int(target_b.id)},
            actor=admin_user,
        )

    inv = _stock_for_system(session, name=sys_name, serials=["SN-FCFS-1"])
    session.refresh(inv)
    instance = inv.instances[0]
    fulfillments = match_and_auto_reserve_on_receipt(
        session, inv, actor=admin_user, instance=instance
    )
    assert len(fulfillments) == 1
    assert fulfillments[0]["project_id"] == project_a.id

    rows_a = list_project_reservations(session, project_a.id, active_only=True)
    rows_b = list_project_reservations(session, project_b.id, active_only=True)
    assert len(rows_a) == 1
    assert rows_b == []
    assert rows_a[0].serial_number == "SN-FCFS-1"
    assert rows_a[0].flight_id
    assert rows_a[0].sdls_id
    assert AUTO_NOTE_FRAGMENT in (rows_a[0].notes or "")
    session.refresh(instance)
    assert item_status_name(session, instance.status_id) == ItemStatus.RESERVED.value

    short_a = session.exec(
        select(InventoryShortage).where(InventoryShortage.project_id == project_a.id)
    ).first()
    short_b = session.exec(
        select(InventoryShortage).where(InventoryShortage.project_id == project_b.id)
    ).first()
    assert short_a and short_a.status == ShortageStatus.FULFILLED.value
    assert short_a.qty_short == 0
    assert short_b and short_b.status == ShortageStatus.OPEN.value
    _cleanup(session, [project_a, project_b], [cfg_a, cfg_b], inv)


def test_receive_two_units_fulfills_both_waiting(session: Session, admin_user: User):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project_a, cfg_a = _ready_project(session, admin_user, system_name=sys_name)
    project_b, cfg_b = _ready_project(session, admin_user, system_name=sys_name)
    target_a = _first_system(session, project_a)
    target_b = _first_system(session, project_b)
    with pytest.raises(InventoryShortageCreated):
        reserve_inventory(
            session,
            project_a.id,
            {"target_entity_type": "system", "target_entity_id": int(target_a.id)},
            actor=admin_user,
        )
    with pytest.raises(InventoryShortageCreated):
        reserve_inventory(
            session,
            project_b.id,
            {"target_entity_type": "system", "target_entity_id": int(target_b.id)},
            actor=admin_user,
        )

    inv = _stock_for_system(
        session, name=sys_name, serials=["SN-A", "SN-B"]
    )
    session.refresh(inv)
    all_fulfillments = []
    for inst in list(inv.instances):
        all_fulfillments.extend(
            match_and_auto_reserve_on_receipt(
                session, inv, actor=admin_user, instance=inst
            )
        )
    assert len(all_fulfillments) == 2
    assert {f["project_id"] for f in all_fulfillments} == {project_a.id, project_b.id}
    assert list_project_reservations(session, project_a.id, active_only=True)
    assert list_project_reservations(session, project_b.id, active_only=True)
    _cleanup(session, [project_a, project_b], [cfg_a, cfg_b], inv)


def test_cancel_stops_auto_reserve(session: Session, admin_user: User):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    target = _first_system(session, project)
    with pytest.raises(InventoryShortageCreated) as caught:
        reserve_inventory(
            session,
            project.id,
            {"target_entity_type": "system", "target_entity_id": int(target.id)},
            actor=admin_user,
        )
    cancel_shortage(session, int(caught.value.shortage.id), actor=admin_user)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-X"])
    session.refresh(inv)
    fulfillments = match_and_auto_reserve_on_receipt(
        session, inv, actor=admin_user, instance=inv.instances[0]
    )
    assert fulfillments == []
    assert list_project_reservations(session, project.id, active_only=True) == []
    _cleanup(session, [project], cfg, inv)


def test_wrong_pn_does_not_clear_unrelated_shortage(session: Session, admin_user: User):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    target = _first_system(session, project)
    with pytest.raises(InventoryShortageCreated):
        reserve_inventory(
            session,
            project.id,
            {"target_entity_type": "system", "target_entity_id": int(target.id)},
            actor=admin_user,
        )
    other = _stock_for_system(
        session,
        name=f"Other-{uuid.uuid4().hex[:6]}",
        serials=["SN-OTHER"],
        part_number="PN-OTHER",
    )
    session.refresh(other)
    fulfillments = match_and_auto_reserve_on_receipt(
        session, other, actor=admin_user, instance=other.instances[0]
    )
    assert fulfillments == []
    open_row = session.exec(
        select(InventoryShortage).where(InventoryShortage.project_id == project.id)
    ).first()
    assert open_row and open_row.status == ShortageStatus.OPEN.value
    _cleanup(session, [project], cfg, other)


def test_partial_receipt_decrements_qty(session: Session, admin_user: User):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    target = _first_system(session, project)
    with pytest.raises(InventoryShortageCreated) as caught:
        reserve_inventory(
            session,
            project.id,
            {"target_entity_type": "system", "target_entity_id": int(target.id)},
            actor=admin_user,
        )
    shortage = session.get(InventoryShortage, caught.value.shortage.id)
    assert shortage
    shortage.qty_short = 2
    shortage.qty_original = 2
    session.add(shortage)
    session.commit()

    inv = _stock_for_system(session, name=sys_name, serials=["SN-P1"])
    session.refresh(inv)
    fulfillments = match_and_auto_reserve_on_receipt(
        session, inv, actor=admin_user, instance=inv.instances[0]
    )
    assert len(fulfillments) == 1
    session.refresh(shortage)
    assert shortage.status == ShortageStatus.PARTIAL.value
    assert shortage.qty_short == 1
    assert fulfillments[0]["shortage_status"] == ShortageStatus.PARTIAL.value
    _cleanup(session, [project], cfg, inv)
