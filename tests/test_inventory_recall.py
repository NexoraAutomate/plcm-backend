"""Spec 11 — inventory recall when a project is cancelled."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.auth import hash_password
from app.database import engine
from app.domain.workflow_status import ItemStatus, ProjectWorkflowStatus
from app.models.base import (
    InventoryReservationStatus,
    RecallStage,
    RecallTaskStatus,
    ShortageStatus,
)
from app.models.tables import (
    Inventory,
    InventoryInstance,
    InventoryIssuance,
    InventoryIssuanceEvent,
    InventoryInstallerNotice,
    InventoryItemRequest,
    InventoryRecallTask,
    InventoryReservation,
    InventoryReworkCase,
    InventoryShortage,
    Project,
    Role,
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
)
from app.services.hierarchy_generation_service import generate_project_hierarchy
from app.services.inventory_recall_service import (
    InventoryRecallError,
    cancel_project,
    confirm_developer_return,
    disposition_recall,
    force_admin_return,
    list_recall_tasks,
    start_recall_inspection,
)
from app.services.inventory_reservation_service import (
    InventoryReservationError,
    get_item_status_id,
    item_status_name,
    reserve_inventory,
)
from app.services.inventory_service import create_inventory_instance
from app.services.item_install_verify_service import (
    ItemInstallVerifyError,
    start_install,
    submit_test,
)
from app.services.item_request_service import (
    create_item_request,
    issue_item_request,
)
from app.services.project_workflow_service import (
    approve_project,
    assert_hierarchy_mutable,
    create_draft_project,
    ProjectWorkflowError,
)
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
    user = _make_role_user(session, role_name="Developer", full_name="Spec11 Developer")
    yield user
    session.delete(user)
    session.commit()


SIGNATURE = {
    "signature_type": "DIGITAL",
    "signature_payload": "data:image/png;base64,aaa",
}


def _ready_named_project(session: Session, admin: User, system_names: list[str]):
    code = f"R11-{uuid.uuid4().hex[:8].upper()}"
    nodes = []
    for i, name in enumerate(system_names):
        nodes.append({"client_key": f"s{i}", "level": "system", "name": name})
        nodes.append(
            {
                "client_key": f"sub{i}",
                "parent_client_key": f"s{i}",
                "level": "subsystem",
                "name": "RF",
            }
        )
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
            "name": f"Recall-{code}",
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


def _cleanup(session: Session, project: Project, cfg, inventories: list[Inventory]):
    try:
        session.rollback()
    except Exception:
        pass
    recalls = session.exec(
        select(InventoryRecallTask).where(InventoryRecallTask.project_id == project.id)
    ).all()
    for row in recalls:
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
    shortages = session.exec(
        select(InventoryShortage).where(InventoryShortage.project_id == project.id)
    ).all()
    for row in shortages:
        session.delete(row)
    session.flush()
    inv_ids = [int(inv.id) for inv in inventories if inv.id]
    if inv_ids:
        issuances = session.exec(
            select(InventoryIssuance).where(InventoryIssuance.inventory_id.in_(inv_ids))
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
    for inventory in inventories:
        session.refresh(inventory)
        for inst in list(inventory.instances or []):
            session.delete(inst)
        session.delete(inventory)
        session.commit()
    delete_configuration(session, cfg.id, hard=True)


def _systems(session: Session, project_id: int) -> list[System]:
    return list(
        session.exec(
            select(System)
            .where(System.project_id == project_id)
            .order_by(System.id)
        ).all()
    )


def _reserve(session, project_id, target, serial, actor):
    return reserve_inventory(
        session,
        project_id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target.id),
            "serial_number": serial,
        },
        actor=actor,
    )


def _issue(session, target, developer, admin):
    assign_developer(
        session, "system", int(target.id), int(developer.id), actor=admin
    )
    req = create_item_request(
        session, entity_type="system", entity_id=int(target.id), actor=developer
    )
    return issue_item_request(session, int(req.id), actor=admin, **SIGNATURE)


def test_mixed_inventory_accounted_after_cancel(
    session: Session, admin_user: User, developer_user: User
):
    names = [f"RecA-{uuid.uuid4().hex[:5]}-{i}" for i in range(6)]
    serials = [f"SN-RA-{uuid.uuid4().hex[:6]}-{i}" for i in range(5)]
    project, cfg = _ready_named_project(session, admin_user, names)
    inventories = [
        _stock_for_system(session, name=names[i], serials=[serials[i]])
        for i in range(5)
    ]
    try:
        systems = {s.name: s for s in _systems(session, project.id)}
        assert len(systems) >= 6
        for i in range(5):
            _reserve(session, project.id, systems[names[i]], serials[i], admin_user)
        # 6th node has no stock → shortage
        with pytest.raises(InventoryReservationError):
            reserve_inventory(
                session,
                project.id,
                {
                    "target_entity_type": "system",
                    "target_entity_id": int(systems[names[5]].id),
                    "serial_number": "MISSING",
                },
                actor=admin_user,
            )

        _issue(session, systems[names[2]], developer_user, admin_user)
        _issue(session, systems[names[3]], developer_user, admin_user)
        _issue(session, systems[names[4]], developer_user, admin_user)
        start_install(session, "system", int(systems[names[4]].id), actor=developer_user)
        submit_test(
            session, "system", int(systems[names[4]].id), result="pass", actor=developer_user
        )

        result = cancel_project(
            session, int(project.id), actor=admin_user, confirm=True
        )
        session.refresh(project)
        assert project.status.status_name == ProjectWorkflowStatus.CANCELLED.value
        assert result["reserved_released"] == 2
        assert result["recall_tasks_created"] == 3
        assert result["shortages_cancelled"] == 1

        active = session.exec(
            select(InventoryReservation).where(
                InventoryReservation.project_id == project.id,
                InventoryReservation.status
                == InventoryReservationStatus.ACTIVE.value,
            )
        ).all()
        assert active == []
        for i in range(2):
            inst = session.exec(
                select(InventoryInstance).where(
                    InventoryInstance.serial_number == serials[i]
                )
            ).first()
            assert item_status_name(session, inst.status_id) == ItemStatus.AVAILABLE.value

        tasks = list_recall_tasks(session, project_id=int(project.id))
        assert len(tasks) == 3
        assert {t.stage for t in tasks} == {RecallStage.REQUESTED.value}

        shortages = session.exec(
            select(InventoryShortage).where(InventoryShortage.project_id == project.id)
        ).all()
        assert shortages
        assert all(s.status == ShortageStatus.CANCELLED.value for s in shortages)

        with pytest.raises(InventoryReservationError, match="READY_FOR_INVENTORY"):
            _reserve(session, project.id, systems[names[0]], serials[0], admin_user)
        with pytest.raises(HierarchyDeveloperError, match="Cancelled projects"):
            assign_developer(
                session,
                "system",
                int(systems[names[0]].id),
                int(developer_user.id),
                actor=admin_user,
            )
        with pytest.raises(ProjectWorkflowError, match="hierarchy changes"):
            assert_hierarchy_mutable(session, systems[names[0]])
        tree_systems = _systems(session, project.id)
        assert len(tree_systems) >= 6
    finally:
        _cleanup(session, project, cfg, inventories)


def test_reusable_unit_free_for_another_project(
    session: Session, admin_user: User, developer_user: User
):
    name = f"RecB-{uuid.uuid4().hex[:6]}"
    serial = f"SN-RB-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_named_project(session, admin_user, [name])
    other, other_cfg = _ready_named_project(session, admin_user, [name])
    inv = _stock_for_system(session, name=name, serials=[serial])
    try:
        target = _systems(session, project.id)[0]
        _reserve(session, project.id, target, serial, admin_user)
        _issue(session, target, developer_user, admin_user)
        cancel_project(session, int(project.id), actor=admin_user, confirm=True)
        task = list_recall_tasks(session, project_id=int(project.id))[0]
        confirm_developer_return(session, int(task.id), actor=developer_user)
        start_recall_inspection(session, int(task.id), actor=admin_user)
        disposition_recall(
            session, int(task.id), actor=admin_user, outcome="reusable"
        )
        inst = session.exec(
            select(InventoryInstance).where(InventoryInstance.serial_number == serial)
        ).first()
        assert item_status_name(session, inst.status_id) == ItemStatus.AVAILABLE.value
        session.refresh(task)
        assert task.status == RecallTaskStatus.CLOSED.value
        assert task.disposition == "reusable"

        other_target = _systems(session, other.id)[0]
        reserved = _reserve(session, other.id, other_target, serial, admin_user)
        assert reserved.status == InventoryReservationStatus.ACTIVE.value
        session.refresh(inst)
        assert item_status_name(session, inst.status_id) == ItemStatus.RESERVED.value
    finally:
        _cleanup(session, other, other_cfg, [])
        _cleanup(session, project, cfg, [inv])


def test_scrapped_unit_unavailable(
    session: Session, admin_user: User, developer_user: User
):
    name = f"RecC-{uuid.uuid4().hex[:6]}"
    serial = f"SN-RC-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_named_project(session, admin_user, [name])
    other, other_cfg = _ready_named_project(session, admin_user, [name])
    inv = _stock_for_system(session, name=name, serials=[serial])
    try:
        target = _systems(session, project.id)[0]
        _reserve(session, project.id, target, serial, admin_user)
        _issue(session, target, developer_user, admin_user)
        cancel_project(session, int(project.id), actor=admin_user, confirm=True)
        task = list_recall_tasks(session, project_id=int(project.id))[0]
        confirm_developer_return(session, int(task.id), actor=developer_user)
        start_recall_inspection(session, int(task.id), actor=admin_user)
        disposition_recall(
            session, int(task.id), actor=admin_user, outcome="scrapped"
        )
        inst = session.exec(
            select(InventoryInstance).where(InventoryInstance.serial_number == serial)
        ).first()
        assert item_status_name(session, inst.status_id) == ItemStatus.SCRAPPED.value
        other_target = _systems(session, other.id)[0]
        with pytest.raises(InventoryReservationError, match="not available"):
            _reserve(session, other.id, other_target, serial, admin_user)
    finally:
        _cleanup(session, other, other_cfg, [])
        _cleanup(session, project, cfg, [inv])


def test_unauthorised_role_cannot_cancel(
    session: Session, admin_user: User, developer_user: User
):
    name = f"RecD-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_named_project(session, admin_user, [name])
    try:
        with pytest.raises(InventoryRecallError, match="explicit confirmation"):
            cancel_project(session, int(project.id), actor=admin_user, confirm=False)
        with pytest.raises(InventoryRecallError, match="Illegal project status"):
            cancel_project(
                session, int(project.id), actor=developer_user, confirm=True
            )
        session.refresh(project)
        assert project.status.status_name == ProjectWorkflowStatus.READY_FOR_INVENTORY.value
    finally:
        _cleanup(session, project, cfg, [])


def test_force_return_when_developer_unresponsive(
    session: Session, admin_user: User, developer_user: User
):
    name = f"RecE-{uuid.uuid4().hex[:6]}"
    serial = f"SN-RE-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_named_project(session, admin_user, [name])
    inv = _stock_for_system(session, name=name, serials=[serial])
    try:
        target = _systems(session, project.id)[0]
        _reserve(session, project.id, target, serial, admin_user)
        _issue(session, target, developer_user, admin_user)
        cancel_project(session, int(project.id), actor=admin_user, confirm=True)
        task = list_recall_tasks(session, project_id=int(project.id))[0]
        forced = force_admin_return(session, int(task.id), actor=admin_user)
        assert forced.forced_return is True
        assert forced.stage == RecallStage.RETURNED.value
        inst = session.exec(
            select(InventoryInstance).where(InventoryInstance.serial_number == serial)
        ).first()
        assert item_status_name(session, inst.status_id) == ItemStatus.RETURNED.value
    finally:
        _cleanup(session, project, cfg, [inv])


def test_issue_blocked_on_cancelled_project(
    session: Session, admin_user: User, developer_user: User
):
    name = f"RecF-{uuid.uuid4().hex[:6]}"
    serial = f"SN-RF-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_named_project(session, admin_user, [name])
    inv = _stock_for_system(session, name=name, serials=[serial])
    try:
        target = _systems(session, project.id)[0]
        _reserve(session, project.id, target, serial, admin_user)
        _issue(session, target, developer_user, admin_user)
        cancel_project(session, int(project.id), actor=admin_user, confirm=True)
        with pytest.raises(ItemInstallVerifyError, match="Cancelled projects"):
            start_install(
                session, "system", int(target.id), actor=developer_user
            )
    finally:
        _cleanup(session, project, cfg, [inv])
