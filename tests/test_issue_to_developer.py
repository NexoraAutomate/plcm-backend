"""Spec 07 — assign developer, request item, signed issue, 24h progress job."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import hash_password
from app.database import engine
from app.domain.workflow_status import ItemStatus
from app.models.base import HARD_COPY_ACKNOWLEDGMENT, InventoryReservationStatus, ItemRequestStatus
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryIssuance,
    InventoryIssuanceEvent,
    InventoryInstallerNotice,
    InventoryItemRequest,
    InventoryReservation,
    Project,
    Role,
    Status,
    System,
    User,
)
from app.services.hierarchy_config_service import (
    create_configuration,
    delete_configuration,
)
from app.services.hierarchy_developer_service import (
    HierarchyDeveloperError,
    assign_developer,
    assignment_status_map,
    list_assigned_work,
)
from app.services.hierarchy_generation_service import generate_project_hierarchy
from app.services.inventory_issuance_service import issue_inventory_unit
from app.services.inventory_issue_progress_service import evaluate_issue_progress
from app.services.inventory_reservation_service import reserve_inventory, release_reservation
from app.services.inventory_service import create_inventory_instance
from app.services.item_request_service import (
    ItemRequestError,
    create_bulk_item_requests,
    create_item_request,
    issue_item_request,
)
from app.services.project_workflow_service import (
    approve_project,
    assign_hm,
    create_draft_project,
    user_can_view_project,
)
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


@pytest.fixture()
def developer_user(session: Session):
    role = session.exec(select(Role).where(Role.name == "Developer")).first()
    if not role:
        pytest.skip("Developer role required")
    username = f"dev_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@example.com",
        full_name="Spec07 Developer",
        is_active=True,
        password=hash_password("Dev@Test1"),
        updated_at=datetime.now(timezone.utc),
    )
    user.roles = [role]
    session.add(user)
    session.commit()
    session.refresh(user)
    yield user
    session.delete(user)
    session.commit()


def _item_status_id(session: Session, name: str) -> int:
    row = session.exec(
        select(Status).where(
            Status.status_name == name, Status.status_type == "inventory"
        )
    ).first()
    assert row and row.id
    return int(row.id)


def _ready_project(session: Session, admin: User, *, system_name: str):
    code = f"R7-{uuid.uuid4().hex[:8].upper()}"
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
            "name": f"Iss-{code}",
            "hierarchy_config_id": cfg.id,
            "product_type": "SSDLS-1",
            "flight_count": 1,
            "sdls_per_flight": 2,
            "start_date": datetime.now(timezone.utc),
        },
        actor=admin,
    )
    approve_project(session, project.id, actor=admin)
    generate_project_hierarchy(session, project.id, actor=admin)
    session.refresh(project)
    return project, cfg


def _stock_for_system(session: Session, *, name: str, serials: list[str]) -> Inventory:
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


def _cleanup(
    session: Session,
    project: Project,
    cfg,
    inventory: Inventory | None = None,
):
    reqs = session.exec(
        select(InventoryItemRequest).where(InventoryItemRequest.project_id == project.id)
    ).all()
    for row in reqs:
        session.delete(row)
    session.flush()
    if inventory:
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
    rows = session.exec(
        select(InventoryReservation).where(InventoryReservation.project_id == project.id)
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


def test_assign_request_issue_with_signature(
    session: Session, admin_user: User, developer_user: User
):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-ISSUE-1"])
    systems = session.exec(select(System).where(System.project_id == project.id)).all()
    target = systems[0]

    assigned = assign_developer(
        session, "system", int(target.id), int(developer_user.id), actor=admin_user
    )
    assert assigned.assigned_developer_id == developer_user.id

    reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target.id),
            "serial_number": "SN-ISSUE-1",
        },
        actor=admin_user,
    )

    req = create_item_request(
        session, entity_type="system", entity_id=int(target.id), actor=developer_user
    )
    assert req.status == ItemRequestStatus.PENDING.value

    with pytest.raises(HTTPException, match="Signature is required"):
        issue_inventory_unit(
            session,
            inv,
            issued_to_user_id=int(developer_user.id),
            issued_by_user_id=int(admin_user.id),
            instance_id=req.inventory_instance_id,
            item_request_id=int(req.id),
        )

    issued = issue_item_request(
        session,
        int(req.id),
        actor=admin_user,
        signature_type="DIGITAL",
        signature_payload="data:image/png;base64,aaa",
    )
    assert issued.status == ItemRequestStatus.ISSUED.value
    assert issued.issued_issuance_id is not None

    inst = session.get(InventoryInstance, req.inventory_instance_id)
    assert inst is not None
    assert session.get(Status, inst.status_id).status_name == ItemStatus.ISSUED.value

    reservation = session.get(InventoryReservation, req.reservation_id)
    assert reservation is not None
    assert reservation.status == InventoryReservationStatus.CONSUMED.value

    issuance = session.get(InventoryIssuance, issued.issued_issuance_id)
    assert issuance is not None
    assert issuance.signature_type == "DIGITAL"
    assert issuance.item_lifecycle_status == ItemStatus.ISSUED.value

    _cleanup(session, project, cfg, inv)


def test_job_flips_issued_after_24h(
    session: Session, admin_user: User, developer_user: User
):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-ISSUE-24"])
    target = session.exec(select(System).where(System.project_id == project.id)).first()
    assign_developer(
        session, "system", int(target.id), int(developer_user.id), actor=admin_user
    )
    reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target.id),
            "serial_number": "SN-ISSUE-24",
        },
        actor=admin_user,
    )
    req = create_item_request(
        session, entity_type="system", entity_id=int(target.id), actor=developer_user
    )
    issued = issue_item_request(
        session,
        int(req.id),
        actor=admin_user,
        signature_type="HARD_COPY",
        signature_payload=HARD_COPY_ACKNOWLEDGMENT,
    )
    issuance = session.get(InventoryIssuance, issued.issued_issuance_id)
    issuance.issued_at = datetime.now(timezone.utc) - timedelta(hours=25)
    session.add(issuance)
    session.commit()

    result = evaluate_issue_progress(session)
    assert result["flipped"] >= 1

    inst = session.get(InventoryInstance, req.inventory_instance_id)
    assert (
        session.get(Status, inst.status_id).status_name
        == ItemStatus.INSTALLATION_IN_PROGRESS.value
    )
    session.refresh(issuance)
    assert issuance.item_lifecycle_status == ItemStatus.INSTALLATION_IN_PROGRESS.value

    _cleanup(session, project, cfg, inv)


def test_reject_issue_if_not_reserved_to_hierarchy(
    session: Session, admin_user: User, developer_user: User
):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-ISSUE-X"])
    systems = session.exec(select(System).where(System.project_id == project.id)).all()
    target_a, target_b = systems[0], systems[1]

    assign_developer(
        session, "system", int(target_b.id), int(developer_user.id), actor=admin_user
    )
    with pytest.raises(ItemRequestError, match="No reserved inventory"):
        create_item_request(
            session, entity_type="system", entity_id=int(target_b.id), actor=developer_user
        )

    reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target_a.id),
            "serial_number": "SN-ISSUE-X",
        },
        actor=admin_user,
    )
    inst = session.exec(
        select(InventoryInstance).where(InventoryInstance.serial_number == "SN-ISSUE-X")
    ).first()
    with pytest.raises(HTTPException, match="Developer must request|different project"):
        issue_inventory_unit(
            session,
            inv,
            issued_to_user_id=int(developer_user.id),
            issued_by_user_id=int(admin_user.id),
            instance_id=int(inst.id),
            target_entity_type="system",
            target_entity_id=int(target_b.id),
            signature_type="DIGITAL",
            signature_payload="data:image/png;base64,aaa",
        )

    with pytest.raises(HierarchyDeveloperError, match="Developer"):
        other = User(
            username=f"notdev_{uuid.uuid4().hex[:6]}",
            email=None,
            full_name="Not a developer",
            is_active=True,
            password=hash_password("NotDev@Test1"),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(other)
        session.commit()
        session.refresh(other)
        try:
            assign_developer(
                session, "system", int(target_a.id), int(other.id), actor=admin_user
            )
        finally:
            session.delete(other)
            session.commit()

    _cleanup(session, project, cfg, inv)


def test_reassign_until_issued_then_lock(
    session: Session, admin_user: User, developer_user: User
):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-REASSIGN-1"])
    target = session.exec(select(System).where(System.project_id == project.id)).first()

    other_role = session.exec(select(Role).where(Role.name == "Developer")).first()
    other = User(
        username=f"dev2_{uuid.uuid4().hex[:8]}",
        email=f"dev2_{uuid.uuid4().hex[:8]}@example.com",
        full_name="Spec07 Developer B",
        is_active=True,
        password=hash_password("Dev@Test1"),
        updated_at=datetime.now(timezone.utc),
    )
    other.roles = [other_role]
    session.add(other)
    session.commit()
    session.refresh(other)

    assign_developer(
        session, "system", int(target.id), int(developer_user.id), actor=admin_user
    )
    reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target.id),
            "serial_number": "SN-REASSIGN-1",
        },
        actor=admin_user,
    )
    req = create_item_request(
        session, entity_type="system", entity_id=int(target.id), actor=developer_user
    )
    assert req.status == ItemRequestStatus.PENDING.value

    reassigned = assign_developer(
        session, "system", int(target.id), int(other.id), actor=admin_user
    )
    assert reassigned.assigned_developer_id == other.id
    session.refresh(req)
    assert req.status == ItemRequestStatus.CANCELLED.value

    cleared = assign_developer(
        session, "system", int(target.id), None, actor=admin_user
    )
    assert cleared.assigned_developer_id is None

    assign_developer(
        session, "system", int(target.id), int(developer_user.id), actor=admin_user
    )
    req2 = create_item_request(
        session, entity_type="system", entity_id=int(target.id), actor=developer_user
    )
    issue_item_request(
        session,
        int(req2.id),
        actor=admin_user,
        signature_type="DIGITAL",
        signature_payload="data:image/png;base64,aaa",
    )
    with pytest.raises(HierarchyDeveloperError, match="cannot be changed"):
        assign_developer(
            session, "system", int(target.id), int(other.id), actor=admin_user
        )

    session.delete(other)
    session.commit()
    _cleanup(session, project, cfg, inv)


def test_bulk_request_reserved_items(
    session: Session, admin_user: User, developer_user: User
):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(
        session, name=sys_name, serials=["SN-BULK-1", "SN-BULK-2"]
    )
    systems = session.exec(select(System).where(System.project_id == project.id)).all()
    target_a, target_b = systems[0], systems[1]
    for target, serial in ((target_a, "SN-BULK-1"), (target_b, "SN-BULK-2")):
        assign_developer(
            session, "system", int(target.id), int(developer_user.id), actor=admin_user
        )
        reserve_inventory(
            session,
            project.id,
            {
                "target_entity_type": "system",
                "target_entity_id": int(target.id),
                "serial_number": serial,
            },
            actor=admin_user,
        )

    work = list_assigned_work(session, int(developer_user.id))
    assert len([row for row in work if row["project_id"] == project.id]) == 2

    created, skipped = create_bulk_item_requests(
        session, actor=developer_user, mode="reserved"
    )
    mine = [row for row in created if row.project_id == project.id]
    assert len(mine) == 2
    assert skipped == []

    created_again, skipped_again = create_bulk_item_requests(
        session, actor=developer_user, mode="all"
    )
    mine_again = [row for row in created_again if row.project_id == project.id]
    assert len(mine_again) == 2
    assert {row.id for row in mine_again} == {row.id for row in mine}

    _cleanup(session, project, cfg, inv)


def test_hm_sees_only_owned_or_created_projects(session: Session, admin_user: User):
    hm_role = session.exec(select(Role).where(Role.name == "HierarchyManager")).first()
    if not hm_role:
        pytest.skip("HierarchyManager role required")

    def _hm(label: str) -> User:
        user = User(
            username=f"hm_{label}_{uuid.uuid4().hex[:6]}",
            email=f"hm_{label}_{uuid.uuid4().hex[:6]}@example.com",
            full_name=f"HM {label}",
            is_active=True,
            password=hash_password("Hm@Test1"),
            updated_at=datetime.now(timezone.utc),
        )
        user.roles = [hm_role]
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    hm_a = _hm("a")
    hm_b = _hm("b")
    project_a, cfg_a = _ready_project(
        session, admin_user, system_name=f"Ha-{uuid.uuid4().hex[:6]}"
    )
    project_b, cfg_b = _ready_project(
        session, admin_user, system_name=f"Hb-{uuid.uuid4().hex[:6]}"
    )
    assign_hm(session, project_a.id, int(hm_a.id), actor=admin_user)
    assign_hm(session, project_b.id, int(hm_b.id), actor=admin_user)
    session.refresh(project_a)
    session.refresh(project_b)

    created = create_draft_project(
        session,
        {
            "name": f"Created-{uuid.uuid4().hex[:6]}",
            "hierarchy_config_id": cfg_a.id,
            "product_type": "SSDLS-1",
            "flight_count": 1,
            "sdls_per_flight": 1,
            "start_date": datetime.now(timezone.utc),
        },
        actor=hm_a,
    )

    assert user_can_view_project(hm_a, project_a)
    assert not user_can_view_project(hm_a, project_b)
    assert user_can_view_project(hm_a, created)
    assert not user_can_view_project(hm_b, created)
    assert user_can_view_project(hm_b, project_b)
    assert user_can_view_project(admin_user, project_a)
    assert user_can_view_project(admin_user, project_b)

    session.delete(created)
    session.commit()
    _cleanup(session, project_a, cfg_a)
    _cleanup(session, project_b, cfg_b)
    session.delete(hm_a)
    session.delete(hm_b)
    session.commit()


def test_wrong_developer_cannot_request_assigned_item(
    session: Session, admin_user: User, developer_user: User
):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-OWN-1"])
    target = session.exec(select(System).where(System.project_id == project.id)).first()
    other_role = session.exec(select(Role).where(Role.name == "Developer")).first()
    other = User(
        username=f"devx_{uuid.uuid4().hex[:8]}",
        email=f"devx_{uuid.uuid4().hex[:8]}@example.com",
        full_name="Other Developer",
        is_active=True,
        password=hash_password("Dev@Test1"),
        updated_at=datetime.now(timezone.utc),
    )
    other.roles = [other_role]
    session.add(other)
    session.commit()
    session.refresh(other)

    assign_developer(
        session, "system", int(target.id), int(developer_user.id), actor=admin_user
    )
    reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target.id),
            "serial_number": "SN-OWN-1",
        },
        actor=admin_user,
    )
    with pytest.raises(ItemRequestError, match="assigned to you"):
        create_item_request(
            session, entity_type="system", entity_id=int(target.id), actor=other
        )

    other_work = list_assigned_work(session, int(other.id))
    assert not any(row["project_id"] == project.id for row in other_work)

    session.delete(other)
    session.commit()
    _cleanup(session, project, cfg, inv)


def test_bulk_selected_and_skip_unreserved(
    session: Session, admin_user: User, developer_user: User
):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-SEL-1"])
    systems = session.exec(select(System).where(System.project_id == project.id)).all()
    reserved_target, bare_target = systems[0], systems[1]
    assign_developer(
        session,
        "system",
        int(reserved_target.id),
        int(developer_user.id),
        actor=admin_user,
    )
    assign_developer(
        session, "system", int(bare_target.id), int(developer_user.id), actor=admin_user
    )
    reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(reserved_target.id),
            "serial_number": "SN-SEL-1",
        },
        actor=admin_user,
    )

    created, skipped = create_bulk_item_requests(
        session, actor=developer_user, mode="all"
    )
    mine_created = [row for row in created if row.project_id == project.id]
    mine_skipped = [row for row in skipped if row["entity_id"] == int(bare_target.id)]
    assert len(mine_created) == 1
    assert mine_created[0].target_entity_id == int(reserved_target.id)
    assert mine_skipped
    assert "reserved" in mine_skipped[0]["reason"].lower()

    created_sel, skipped_sel = create_bulk_item_requests(
        session,
        actor=developer_user,
        mode="selected",
        items=[
            {"entity_type": "system", "entity_id": int(bare_target.id)},
        ],
    )
    assert [row for row in created_sel if row.project_id == project.id] == []
    assert any(row["entity_id"] == int(bare_target.id) for row in skipped_sel)

    with pytest.raises(ItemRequestError, match="Select at least one"):
        create_bulk_item_requests(session, actor=developer_user, mode="selected", items=[])

    _cleanup(session, project, cfg, inv)


def test_assignment_status_locks_after_issue(
    session: Session, admin_user: User, developer_user: User
):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-STAT-1"])
    target = session.exec(select(System).where(System.project_id == project.id)).first()
    assign_developer(
        session, "system", int(target.id), int(developer_user.id), actor=admin_user
    )
    status_before = assignment_status_map(session, "system", [int(target.id)])
    assert status_before[int(target.id)]["assigned_developer_id"] == developer_user.id
    assert status_before[int(target.id)]["issued"] is False

    reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target.id),
            "serial_number": "SN-STAT-1",
        },
        actor=admin_user,
    )
    req = create_item_request(
        session, entity_type="system", entity_id=int(target.id), actor=developer_user
    )
    issue_item_request(
        session,
        int(req.id),
        actor=admin_user,
        signature_type="HARD_COPY",
        signature_payload=HARD_COPY_ACKNOWLEDGMENT,
    )
    status_after = assignment_status_map(session, "system", [int(target.id)])
    assert status_after[int(target.id)]["issued"] is True
    work = [
        row
        for row in list_assigned_work(session, int(developer_user.id))
        if row["entity_id"] == int(target.id)
    ]
    assert work
    assert work[0]["issued"] is True
    assert work[0]["can_request"] is False

    _cleanup(session, project, cfg, inv)


def test_release_reservation_clears_developer_assignment(
    session: Session, admin_user: User, developer_user: User
):
    sys_name = f"Comm-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin_user, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=["SN-REL-1"])
    target = session.exec(select(System).where(System.project_id == project.id)).first()
    assign_developer(
        session, "system", int(target.id), int(developer_user.id), actor=admin_user
    )
    reserved = reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target.id),
            "serial_number": "SN-REL-1",
        },
        actor=admin_user,
    )
    req = create_item_request(
        session, entity_type="system", entity_id=int(target.id), actor=developer_user
    )
    assert req.status == ItemRequestStatus.PENDING.value

    release_reservation(session, project.id, int(reserved.id), actor=admin_user)
    session.refresh(target)
    session.refresh(req)
    assert target.assigned_developer_id is None
    assert req.status == ItemRequestStatus.CANCELLED.value
    work = [
        row
        for row in list_assigned_work(session, int(developer_user.id))
        if row["project_id"] == project.id
    ]
    assert work == []

    _cleanup(session, project, cfg, inv)



