"""Turnkey vs build-from-children automatic inventory assembly."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import or_, text
from sqlmodel import Session, select

from app.auth import hash_password
from app.database import engine
from app.domain.hierarchy_config import InventorySource
from app.domain.workflow_status import ItemStatus
from app.models.base import ItemTestResult
from app.models.tables import (
    AssembledInventory,
    Hierarchy,
    Inventory,
    InventoryChildLink,
    InventoryInstance,
    InventoryIssuance,
    InventoryIssuanceEvent,
    InventoryInstallerNotice,
    InventoryItemRequest,
    InventoryReservation,
    InventoryReworkCase,
    Project,
    Role,
    Status,
    System,
    User,
)
from app.services.entity_list_service import find_entity_list_entry
from app.services.hierarchy_config_service import (
    configuration_to_dict,
    create_configuration,
    delete_configuration,
)
from app.services.hierarchy_service import get_next_hierarchy_id, sync_hierarchy_id_sequence
from app.services.hierarchy_developer_service import assign_developer
from app.services.hierarchy_generation_service import generate_project_hierarchy
from app.services.inventory_assembly_service import (
    evaluate_parent_assembly,
    get_assembled_inventory,
)
from app.services.inventory_reservation_service import (
    InventoryReservationError,
    build_reservation_plan,
    reserve_inventory,
)
from app.services.inventory_service import create_inventory_instance
from app.services.item_install_verify_service import (
    report_complete,
    start_install,
    submit_test,
    verify_issuance,
)
from app.services.item_request_service import create_item_request, issue_item_request
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
    user = _make_role_user(session, role_name="Developer", full_name="Assembly Developer")
    yield user
    session.delete(user)
    session.commit()


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


def _item_status_id(session: Session, name: str) -> int:
    row = session.exec(
        select(Status).where(
            Status.status_name == name, Status.status_type == "inventory"
        )
    ).first()
    assert row and row.id
    return int(row.id)


def _sync_inventory_sequences(session: Session) -> None:
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


def _stock_serialized(
    session: Session, *, name: str, inventory_type: str, serials: list[str]
) -> Inventory:
    available_id = _item_status_id(session, ItemStatus.AVAILABLE.value)
    _sync_inventory_sequences(session)
    inv = Inventory(
        name=name,
        inventory_type=inventory_type,
        quantity=0,
        part_number=f"PN-{inventory_type[:3].upper()}-{uuid.uuid4().hex[:6]}",
        status_id=available_id,
    )
    session.add(inv)
    session.flush()
    for sn in serials:
        create_inventory_instance(
            session, inv, serial_number=sn, status_id=available_id, location="Lab"
        )
    session.commit()
    session.refresh(inv)
    return inv


def _nodes(*rows: dict) -> list[dict]:
    return list(rows)


def _ready_project(
    session: Session,
    admin: User,
    nodes: list[dict],
    *,
    flights: int = 1,
    sdls: int = 1,
):
    for node in nodes:
        _ensure_catalog(session, str(node["name"]), str(node["level"]))
    code = f"ASM-{uuid.uuid4().hex[:8].upper()}"
    cfg = create_configuration(
        session,
        {
            "code": code,
            "name": code,
            "is_available": True,
            "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
            "nodes": nodes,
        },
    )
    project = create_draft_project(
        session,
        {
            "name": f"Asm-{code}",
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


def _cleanup(session: Session, project: Project, cfg, inventories: list[Inventory] | None = None):
    inventories = inventories or []
    assembled = session.exec(
        select(AssembledInventory).where(AssembledInventory.project_id == project.id)
    ).all()
    assembled_inv_ids = [row.inventory_id for row in assembled if row.inventory_id]
    for row in assembled:
        session.delete(row)
    session.flush()
    reqs = session.exec(
        select(InventoryItemRequest).where(InventoryItemRequest.project_id == project.id)
    ).all()
    for row in reqs:
        session.delete(row)
    session.flush()
    reworks = session.exec(
        select(InventoryReworkCase).where(InventoryReworkCase.project_id == project.id)
    ).all()
    for row in reworks:
        session.delete(row)
    session.flush()
    all_inv_ids = {inv.id for inv in inventories if inv.id} | set(assembled_inv_ids)
    extra = session.exec(
        select(Inventory).where(Inventory.id.in_(list(all_inv_ids)))
    ).all() if all_inv_ids else []
    for inventory in extra:
        issuances = session.exec(
            select(InventoryIssuance).where(InventoryIssuance.inventory_id == inventory.id)
        ).all()
        issuance_ids = [row.id for row in issuances if row.id]
        if issuance_ids:
            events = session.exec(
                select(InventoryIssuanceEvent).where(
                    InventoryIssuanceEvent.issuance_id.in_(issuance_ids)
                )
            ).all()
            for row in events:
                session.delete(row)
            notices = session.exec(
                select(InventoryInstallerNotice).where(
                    InventoryInstallerNotice.issuance_id.in_(issuance_ids)
                )
            ).all()
            for row in notices:
                session.delete(row)
            session.flush()
        for row in issuances:
            session.delete(row)
        session.flush()
        links = session.exec(
            select(InventoryChildLink).where(
                or_(
                    InventoryChildLink.parent_inventory_id == inventory.id,
                    InventoryChildLink.child_inventory_id == inventory.id,
                )
            )
        ).all()
        for row in links:
            session.delete(row)
        session.flush()
    rows = session.exec(
        select(InventoryReservation).where(InventoryReservation.project_id == project.id)
    ).all()
    for row in rows:
        session.delete(row)
    session.flush()
    for inventory in extra:
        instances = session.exec(
            select(InventoryInstance).where(InventoryInstance.inventory_id == inventory.id)
        ).all()
        for inst in instances:
            session.delete(inst)
        session.flush()
        session.delete(inventory)
    session.delete(project)
    session.commit()
    delete_configuration(session, cfg.id, hard=True)


def _first_system(session: Session, project: Project) -> System:
    system = session.exec(
        select(System).where(System.project_id == project.id).order_by(System.id)
    ).first()
    assert system is not None
    session.refresh(system)
    return system


def _complete_serialized_child(
    session: Session,
    *,
    admin: User,
    developer: User,
    project: Project,
    entity_type: str,
    entity_id: int,
    name: str,
    serial: str,
) -> Inventory:
    inv = _stock_serialized(
        session, name=name, inventory_type=entity_type, serials=[serial]
    )
    assign_developer(session, entity_type, int(entity_id), int(developer.id), actor=admin)
    reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": entity_type,
            "target_entity_id": int(entity_id),
            "serial_number": serial,
        },
        actor=admin,
    )
    req = create_item_request(
        session, entity_type=entity_type, entity_id=int(entity_id), actor=developer
    )
    issued = issue_item_request(
        session,
        int(req.id),
        actor=admin,
        signature_type="DIGITAL",
        signature_payload="data:image/png;base64,aaa",
    )
    start_install(session, entity_type, int(entity_id), actor=developer)
    submit_test(
        session, entity_type, int(entity_id), result=ItemTestResult.PASS.value, actor=developer
    )
    report_complete(session, entity_type, int(entity_id), actor=developer)
    verify_issuance(session, int(issued.id), actor=admin)
    return inv


def test_turnkey_parent_with_children_waits_and_assembles(
    session: Session, admin_user: User, developer_user: User
):
    """Parents with runtime children are BUILD even when config says turnkey."""
    project, cfg = _ready_project(
        session,
        admin_user,
        _nodes(
            {"client_key": "s1", "level": "system", "name": "Comm"},
            {
                "client_key": "ss1",
                "parent_client_key": "s1",
                "level": "subsystem",
                "name": "RF",
            },
        ),
    )
    inventories: list[Inventory] = []
    try:
        system = _first_system(session, project)
        sub = system.subsystems[0]
        plan = build_reservation_plan(session, int(project.id))
        system_row = next(
            row
            for row in plan["items"]
            if row["target_entity_type"] == "system"
            and row["target_entity_id"] == int(system.id)
        )
        assert system_row["status"] == "assemble"

        inventories.append(
            _complete_serialized_child(
                session,
                admin=admin_user,
                developer=developer_user,
                project=project,
                entity_type="subsystem",
                entity_id=int(sub.id),
                name="RF",
                serial=f"SN-S1-{uuid.uuid4().hex[:6]}",
            )
        )
        assert get_assembled_inventory(session, "system", int(system.id)) is not None
        session.refresh(system)
        assert system.inventory_source == InventorySource.BUILD_FROM_CHILDREN.value
    finally:
        _cleanup(session, project, cfg, inventories)


def test_s2_build_parent_created_after_one_child(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg = _ready_project(
        session,
        admin_user,
        _nodes(
            {
                "client_key": "s1",
                "level": "system",
                "name": "Comm",
                "inventory_source": InventorySource.BUILD_FROM_CHILDREN.value,
            },
            {
                "client_key": "ss1",
                "parent_client_key": "s1",
                "level": "subsystem",
                "name": "RF",
            },
        ),
    )
    inventories: list[Inventory] = []
    try:
        system = _first_system(session, project)
        assert system.inventory_source == InventorySource.BUILD_FROM_CHILDREN.value
        sub = system.subsystems[0]
        inventories.append(
            _complete_serialized_child(
                session,
                admin=admin_user,
                developer=developer_user,
                project=project,
                entity_type="subsystem",
                entity_id=int(sub.id),
                name="RF",
                serial=f"SN-S2-{uuid.uuid4().hex[:6]}",
            )
        )
        assembled = get_assembled_inventory(session, "system", int(system.id))
        assert assembled is not None
        session.refresh(system)
        assert system.part_number
        assert system.serial_number
        hold = session.exec(
            select(InventoryReservation).where(
                InventoryReservation.target_entity_type == "system",
                InventoryReservation.target_entity_id == int(system.id),
                InventoryReservation.status == "active",
            )
        ).first()
        assert hold is not None
        assert hold.flight_id == assembled.flight_id
        assert hold.sdls_id == assembled.sdls_id
        instance = session.get(InventoryInstance, assembled.inventory_instance_id)
        assert instance is not None
        assert instance.serial_number == system.serial_number
        plan = build_reservation_plan(session, int(project.id))
        system_row = next(
            row
            for row in plan["items"]
            if row["target_entity_type"] == "system"
            and row["target_entity_id"] == int(system.id)
        )
        assert system_row["status"] == "reserved"
        assert system_row["can_assign_developer"] is True
        assert system_row["assembled"] is True
        assert system_row["suggested_serial"] == system.serial_number
        assign_developer(
            session, "system", int(system.id), int(developer_user.id), actor=admin_user
        )
        session.refresh(system)
        assert system.assigned_developer_id == developer_user.id
    finally:
        _cleanup(session, project, cfg, inventories)


def test_s3_s7_partial_then_exactly_once(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg = _ready_project(
        session,
        admin_user,
        _nodes(
            {
                "client_key": "s1",
                "level": "system",
                "name": "Comm",
                "inventory_source": InventorySource.BUILD_FROM_CHILDREN.value,
            },
            {
                "client_key": "ss1",
                "parent_client_key": "s1",
                "level": "subsystem",
                "name": "RF",
            },
            {
                "client_key": "ss2",
                "parent_client_key": "s1",
                "level": "subsystem",
                "name": "PSU",
            },
        ),
    )
    inventories: list[Inventory] = []
    try:
        system = _first_system(session, project)
        rf = next(s for s in system.subsystems if s.name == "RF")
        psu = next(s for s in system.subsystems if s.name == "PSU")
        inventories.append(
            _complete_serialized_child(
                session,
                admin=admin_user,
                developer=developer_user,
                project=project,
                entity_type="subsystem",
                entity_id=int(rf.id),
                name="RF",
                serial=f"SN-RF-{uuid.uuid4().hex[:6]}",
            )
        )
        assert get_assembled_inventory(session, "system", int(system.id)) is None
        inventories.append(
            _complete_serialized_child(
                session,
                admin=admin_user,
                developer=developer_user,
                project=project,
                entity_type="subsystem",
                entity_id=int(psu.id),
                name="PSU",
                serial=f"SN-PSU-{uuid.uuid4().hex[:6]}",
            )
        )
        rows = session.exec(
            select(AssembledInventory).where(
                AssembledInventory.target_entity_type == "system",
                AssembledInventory.target_entity_id == int(system.id),
            )
        ).all()
        assert len(rows) == 1
    finally:
        _cleanup(session, project, cfg, inventories)


def test_s4_s10_recursive_build_chain(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg = _ready_project(
        session,
        admin_user,
        _nodes(
            {
                "client_key": "s1",
                "level": "system",
                "name": "Comm",
                "inventory_source": InventorySource.BUILD_FROM_CHILDREN.value,
            },
            {
                "client_key": "ss1",
                "parent_client_key": "s1",
                "level": "subsystem",
                "name": "RF",
                "inventory_source": InventorySource.BUILD_FROM_CHILDREN.value,
            },
            {
                "client_key": "m1",
                "parent_client_key": "ss1",
                "level": "module",
                "name": "Modem",
                "inventory_source": InventorySource.BUILD_FROM_CHILDREN.value,
            },
            {
                "client_key": "u1",
                "parent_client_key": "m1",
                "level": "unit",
                "name": "Baseband Unit",
            },
        ),
    )
    inventories: list[Inventory] = []
    try:
        system = _first_system(session, project)
        sub = system.subsystems[0]
        module = sub.modules[0]
        unit = module.units[0]
        inventories.append(
            _complete_serialized_child(
                session,
                admin=admin_user,
                developer=developer_user,
                project=project,
                entity_type="unit",
                entity_id=int(unit.id),
                name="Baseband Unit",
                serial=f"SN-U-{uuid.uuid4().hex[:6]}",
            )
        )
        assert get_assembled_inventory(session, "module", int(module.id)) is not None
        assert get_assembled_inventory(session, "subsystem", int(sub.id)) is not None
        assert get_assembled_inventory(session, "system", int(system.id)) is not None
        session.refresh(system)
        session.refresh(sub)
        session.refresh(module)
        assert system.serial_number and sub.serial_number and module.serial_number
        assert system.serial_number != sub.serial_number
    finally:
        _cleanup(session, project, cfg, inventories)


def test_s5_duplicate_event_creates_one_parent(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg = _ready_project(
        session,
        admin_user,
        _nodes(
            {
                "client_key": "s1",
                "level": "system",
                "name": "Comm",
                "inventory_source": InventorySource.BUILD_FROM_CHILDREN.value,
            },
            {
                "client_key": "ss1",
                "parent_client_key": "s1",
                "level": "subsystem",
                "name": "RF",
            },
        ),
    )
    inventories: list[Inventory] = []
    try:
        system = _first_system(session, project)
        sub = system.subsystems[0]
        inventories.append(
            _complete_serialized_child(
                session,
                admin=admin_user,
                developer=developer_user,
                project=project,
                entity_type="subsystem",
                entity_id=int(sub.id),
                name="RF",
                serial=f"SN-DUP-{uuid.uuid4().hex[:6]}",
            )
        )
        evaluate_parent_assembly(
            session, "subsystem", int(sub.id), actor=admin_user
        )
        session.commit()
        rows = session.exec(
            select(AssembledInventory).where(
                AssembledInventory.target_entity_type == "system",
                AssembledInventory.target_entity_id == int(system.id),
            )
        ).all()
        assert len(rows) == 1
        holds = session.exec(
            select(InventoryReservation).where(
                InventoryReservation.target_entity_type == "system",
                InventoryReservation.target_entity_id == int(system.id),
                InventoryReservation.status == "active",
            )
        ).all()
        assert len(holds) == 1
        instances = session.exec(
            select(InventoryInstance).where(
                InventoryInstance.inventory_id == rows[0].inventory_id
            )
        ).all()
        assert len(instances) == 1
    finally:
        _cleanup(session, project, cfg, inventories)


def test_s6_flights_do_not_cross_contaminate(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg = _ready_project(
        session,
        admin_user,
        _nodes(
            {
                "client_key": "s1",
                "level": "system",
                "name": "Comm",
                "inventory_source": InventorySource.BUILD_FROM_CHILDREN.value,
            },
            {
                "client_key": "ss1",
                "parent_client_key": "s1",
                "level": "subsystem",
                "name": "RF",
            },
        ),
        flights=2,
        sdls=1,
    )
    inventories: list[Inventory] = []
    try:
        systems = session.exec(
            select(System).where(System.project_id == project.id).order_by(System.id)
        ).all()
        assert len(systems) == 2
        first, second = systems
        session.refresh(first)
        session.refresh(second)
        inventories.append(
            _complete_serialized_child(
                session,
                admin=admin_user,
                developer=developer_user,
                project=project,
                entity_type="subsystem",
                entity_id=int(first.subsystems[0].id),
                name="RF",
                serial=f"SN-F1-{uuid.uuid4().hex[:6]}",
            )
        )
        assembled_first = get_assembled_inventory(session, "system", int(first.id))
        assembled_second = get_assembled_inventory(session, "system", int(second.id))
        assert assembled_first is not None
        assert assembled_second is None
        assert assembled_first.sdls_id == first.sdls_id
        assert assembled_first.sdls_id != second.sdls_id
    finally:
        _cleanup(session, project, cfg, inventories)


def test_s8_config_persist_inventory_source(session: Session, admin_user: User):
    _ensure_catalog(session, "Comm", "system")
    _ensure_catalog(session, "RF", "subsystem")
    code = f"ASM-CFG-{uuid.uuid4().hex[:6].upper()}"
    cfg = create_configuration(
        session,
        {
            "code": code,
            "name": code,
            "product_types": [{"code": "SSDLS-1", "name": "HDR"}],
            "nodes": [
                {
                    "client_key": "s1",
                    "level": "system",
                    "name": "Comm",
                    "inventory_source": "build_from_children",
                },
                {
                    "client_key": "ss1",
                    "parent_client_key": "s1",
                    "level": "subsystem",
                    "name": "RF",
                },
            ],
        },
    )
    try:
        payload = configuration_to_dict(cfg)
        by_name = {n["name"]: n["inventory_source"] for n in payload["nodes"]}
        assert by_name["Comm"] == InventorySource.BUILD_FROM_CHILDREN.value
        assert by_name["RF"] == InventorySource.TURNKEY.value
    finally:
        delete_configuration(session, cfg.id, hard=True)


def test_s9_build_node_rejects_procured_reserve(
    session: Session, admin_user: User
):
    project, cfg = _ready_project(
        session,
        admin_user,
        _nodes(
            {
                "client_key": "s1",
                "level": "system",
                "name": "Comm",
                "inventory_source": InventorySource.BUILD_FROM_CHILDREN.value,
            },
            {
                "client_key": "ss1",
                "parent_client_key": "s1",
                "level": "subsystem",
                "name": "RF",
            },
        ),
    )
    inventories: list[Inventory] = []
    try:
        system = _first_system(session, project)
        stock = _stock_serialized(
            session,
            name="Comm",
            inventory_type="system",
            serials=[f"SN-TK-{uuid.uuid4().hex[:6]}"],
        )
        inventories.append(stock)
        inst = session.exec(
            select(InventoryInstance).where(InventoryInstance.inventory_id == stock.id)
        ).first()
        assert inst is not None
        with pytest.raises(InventoryReservationError, match="build-from-children"):
            reserve_inventory(
                session,
                project.id,
                {
                    "target_entity_type": "system",
                    "target_entity_id": int(system.id),
                    "serial_number": inst.serial_number,
                },
                actor=admin_user,
            )
        rf = system.subsystems[0]
        rf_stock = _stock_serialized(
            session,
            name="RF",
            inventory_type="subsystem",
            serials=[f"SN-RF9-{uuid.uuid4().hex[:6]}"],
        )
        inventories.append(rf_stock)
        rf_inst = session.exec(
            select(InventoryInstance).where(InventoryInstance.inventory_id == rf_stock.id)
        ).first()
        assert rf_inst is not None
        hold = reserve_inventory(
            session,
            project.id,
            {
                "target_entity_type": "subsystem",
                "target_entity_id": int(rf.id),
                "serial_number": rf_inst.serial_number,
            },
            actor=admin_user,
        )
        assert hold.id is not None
    finally:
        _cleanup(session, project, cfg, inventories)
