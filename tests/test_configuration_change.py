"""Spec 12 — configuration change after hierarchy / reservation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.auth import hash_password
from app.database import engine
from app.domain.workflow_status import ItemStatus, ProjectWorkflowStatus
from app.models.base import (
    ConfigChangeRequestStatus,
    InventoryReservationStatus,
)
from app.models.tables import (
    ConfigChangeRequest,
    Inventory,
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
from app.services.config_change_service import (
    ConfigChangeError,
    approve_config_change,
    cancel_config_change,
    create_successor_project,
    get_open_config_change,
    request_config_change,
    return_config_change_inventory,
    submit_config_change,
)
from app.services.hierarchy_config_service import (
    create_configuration,
    delete_configuration,
)
from app.services.hierarchy_developer_service import assign_developer
from app.services.hierarchy_generation_service import generate_project_hierarchy
from app.services.inventory_recall_service import (
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
from app.services.item_request_service import create_item_request, issue_item_request
from app.services.project_workflow_service import (
    ProjectWorkflowError,
    approve_project,
    create_draft_project,
    guard_structural_update,
    project_status_name,
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
    user = _make_role_user(session, role_name="Developer", full_name="Spec12 Developer")
    yield user
    session.delete(user)
    session.commit()


SIGNATURE = {
    "signature_type": "DIGITAL",
    "signature_payload": "data:image/png;base64,aaa",
}


def _available_config(
    session: Session,
    admin: User,
    system_names: list[str],
    code: str,
    product_types: list[dict] | None = None,
):
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
    return create_configuration(
        session,
        {
            "code": code,
            "name": code,
            "is_available": True,
            "product_types": product_types
            or [{"code": "SSDLS-1", "name": "HDR"}],
            "nodes": nodes,
        },
        actor=admin,
    )


def _ready_named_project(session: Session, admin: User, system_names: list[str]):
    code = f"C12-{uuid.uuid4().hex[:8].upper()}"
    cfg = _available_config(session, admin, system_names, code)
    project = create_draft_project(
        session,
        {
            "name": f"CfgChange-{code}",
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


def _cleanup(
    session: Session,
    project: Project,
    cfg,
    inventories: list[Inventory],
    extra_projects: list[Project] | None = None,
    extra_cfgs=None,
):
    try:
        session.rollback()
    except Exception:
        pass
    projects = [project, *(extra_projects or [])]
    for proj in projects:
        if proj.id is None:
            continue
        crs = session.exec(
            select(ConfigChangeRequest).where(
                ConfigChangeRequest.source_project_id == proj.id
            )
        ).all()
        for row in crs:
            session.delete(row)
        session.flush()
        recalls = session.exec(
            select(InventoryRecallTask).where(InventoryRecallTask.project_id == proj.id)
        ).all()
        for row in recalls:
            session.delete(row)
        session.flush()
        reqs = session.exec(
            select(InventoryItemRequest).where(InventoryItemRequest.project_id == proj.id)
        ).all()
        for row in reqs:
            session.delete(row)
        session.flush()
        reworks = session.exec(
            select(InventoryReworkCase).where(InventoryReworkCase.project_id == proj.id)
        ).all()
        for row in reworks:
            session.delete(row)
        session.flush()
        shortages = session.exec(
            select(InventoryShortage).where(InventoryShortage.project_id == proj.id)
        ).all()
        for row in shortages:
            session.delete(row)
        session.flush()
        inv_ids = [int(inv.id) for inv in inventories if inv.id]
        if inv_ids:
            issuances = session.exec(
                select(InventoryIssuance).where(
                    InventoryIssuance.inventory_id.in_(inv_ids),
                    InventoryIssuance.project_id == proj.id,
                )
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
            select(InventoryReservation).where(
                InventoryReservation.project_id == proj.id
            )
        ).all()
        for row in rows:
            session.delete(row)
        session.delete(proj)
        session.commit()
    for inventory in inventories:
        session.refresh(inventory)
        for inst in list(inventory.instances or []):
            session.delete(inst)
        session.delete(inventory)
        session.commit()
    delete_configuration(session, cfg.id, hard=True)
    for extra in extra_cfgs or []:
        delete_configuration(session, extra.id, hard=True)


def _systems(session: Session, project_id: int) -> list[System]:
    return list(
        session.exec(
            select(System).where(System.project_id == project_id).order_by(System.id)
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


def _close_recalls(session, project_id, admin):
    tasks = list_recall_tasks(session, project_id=project_id)
    for task in tasks:
        if task.stage == "requested":
            force_admin_return(session, int(task.id), actor=admin)
            task = session.get(InventoryRecallTask, task.id)
        if task.stage == "returned":
            start_recall_inspection(session, int(task.id), actor=admin)
            task = session.get(InventoryRecallTask, task.id)
        if task.stage == "inspection":
            disposition_recall(
                session, int(task.id), actor=admin, outcome="reusable"
            )


def test_sealed_project_rejects_in_place_config_update(
    session: Session, admin_user: User
):
    names = [f"Seal-{uuid.uuid4().hex[:5]}"]
    project, cfg = _ready_named_project(session, admin_user, names)
    other = _available_config(
        session, admin_user, [f"Alt-{uuid.uuid4().hex[:5]}"], f"ALT-{uuid.uuid4().hex[:6]}"
    )
    try:
        with pytest.raises(ProjectWorkflowError, match="frozen"):
            guard_structural_update(
                project, {"hierarchy_config_id": int(other.id)}
            )
    finally:
        _cleanup(session, project, cfg, [], extra_cfgs=[other])


def test_config_change_flow_creates_successor_and_frees_inventory(
    session: Session, admin_user: User, developer_user: User
):
    names = [f"CcA-{uuid.uuid4().hex[:5]}-{i}" for i in range(2)]
    serials = [f"SN-CC-{uuid.uuid4().hex[:6]}-{i}" for i in range(2)]
    project, cfg = _ready_named_project(session, admin_user, names)
    target = _available_config(
        session,
        admin_user,
        [f"New-{uuid.uuid4().hex[:5]}"],
        f"NEW-{uuid.uuid4().hex[:6]}",
    )
    inventories = [
        _stock_for_system(session, name=names[i], serials=[serials[i]])
        for i in range(2)
    ]
    successor = None
    extra_projects: list[Project] = []
    extra_cfgs = [target]
    try:
        systems = {s.name: s for s in _systems(session, project.id)}
        _reserve(session, project.id, systems[names[0]], serials[0], admin_user)
        _reserve(session, project.id, systems[names[1]], serials[1], admin_user)
        _issue(session, systems[names[1]], developer_user, admin_user)

        with pytest.raises(ProjectWorkflowError, match="frozen"):
            guard_structural_update(project, {"hierarchy_config_id": int(target.id)})

        cr = request_config_change(session, int(project.id), actor=admin_user)
        assert cr.status == ConfigChangeRequestStatus.REQUESTED.value

        with pytest.raises(InventoryReservationError, match="configuration change"):
            _reserve(session, project.id, systems[names[0]], serials[0], admin_user)

        with pytest.raises(ConfigChangeError, match="inventory is returned"):
            submit_config_change(
                session,
                int(cr.id),
                actor=admin_user,
                target_hierarchy_config_id=int(target.id),
                reason_remarks="Need SSDLS-1 alt tree",
            )

        cr = return_config_change_inventory(session, int(cr.id), actor=admin_user)
        reserved = session.exec(
            select(InventoryReservation).where(
                InventoryReservation.project_id == project.id,
                InventoryReservation.status
                == InventoryReservationStatus.ACTIVE.value,
            )
        ).all()
        assert reserved == []
        assert cr.status == ConfigChangeRequestStatus.REQUESTED.value

        with pytest.raises(ConfigChangeError, match="inventory is returned"):
            submit_config_change(
                session,
                int(cr.id),
                actor=admin_user,
                target_hierarchy_config_id=int(target.id),
                reason_remarks="Need SSDLS-1 alt tree",
            )

        _close_recalls(session, project.id, admin_user)
        session.refresh(cr)
        cr = session.get(ConfigChangeRequest, cr.id)
        assert cr.status == ConfigChangeRequestStatus.INVENTORY_RETURNED.value

        cr = submit_config_change(
            session,
            int(cr.id),
            actor=admin_user,
            target_hierarchy_config_id=int(target.id),
            reason_remarks="Need SSDLS-1 alt tree",
            product_type="SSDLS-1",
            flight_count=1,
            sdls_per_flight=1,
        )
        assert cr.status == ConfigChangeRequestStatus.SUBMITTED.value

        with pytest.raises(ConfigChangeError, match="Admin approval"):
            create_successor_project(session, int(cr.id), actor=admin_user)

        cr = approve_config_change(session, int(cr.id), actor=admin_user)
        assert cr.status == ConfigChangeRequestStatus.APPROVED.value

        cr, successor = create_successor_project(
            session,
            int(cr.id),
            actor=admin_user,
            name=f"Successor-{target.code}",
        )
        assert cr.status == ConfigChangeRequestStatus.NEW_PROJECT_CREATED.value
        session.refresh(project)
        assert project_status_name(project) == ProjectWorkflowStatus.SUPERSEDED.value
        assert project.successor_project_id == successor.id
        assert successor.predecessor_project_id == project.id
        assert successor.hierarchy_config_id == target.id
        assert project_status_name(successor) == ProjectWorkflowStatus.DRAFT.value

        approve_project(session, successor.id, actor=admin_user)
        result = generate_project_hierarchy(session, successor.id, actor=admin_user)
        assert result["status"] == ProjectWorkflowStatus.READY_FOR_INVENTORY.value

        other_name = names[1]
        other, other_cfg = _ready_named_project(session, admin_user, [other_name])
        extra_projects.append(other)
        extra_cfgs.append(other_cfg)
        inv = inventories[1]
        session.refresh(inv)
        instance = (inv.instances or [None])[0]
        status_name = item_status_name(session, instance.status_id) if instance else None
        assert status_name == ItemStatus.AVAILABLE.value
        other_systems = _systems(session, other.id)
        _reserve(
            session,
            other.id,
            other_systems[0],
            serials[1],
            admin_user,
        )
    finally:
        extra = [successor] if successor is not None and successor.id else []
        extra.extend(extra_projects)
        _cleanup(
            session,
            project,
            cfg,
            inventories,
            extra_projects=extra,
            extra_cfgs=extra_cfgs,
        )


def test_approve_blocked_until_inventory_cleared(
    session: Session, admin_user: User, developer_user: User
):
    names = [f"Blk-{uuid.uuid4().hex[:5]}-{i}" for i in range(2)]
    serials = [f"SN-BLK-{uuid.uuid4().hex[:6]}-{i}" for i in range(2)]
    project, cfg = _ready_named_project(session, admin_user, names)
    target = _available_config(
        session, admin_user, [f"T-{uuid.uuid4().hex[:5]}"], f"TGT-{uuid.uuid4().hex[:6]}"
    )
    inventories = [
        _stock_for_system(session, name=names[i], serials=[serials[i]])
        for i in range(2)
    ]
    try:
        systems = {s.name: s for s in _systems(session, project.id)}
        _reserve(session, project.id, systems[names[0]], serials[0], admin_user)
        _reserve(session, project.id, systems[names[1]], serials[1], admin_user)
        _issue(session, systems[names[1]], developer_user, admin_user)
        cr = request_config_change(session, int(project.id), actor=admin_user)
        cr = return_config_change_inventory(session, int(cr.id), actor=admin_user)
        assert cr.status == ConfigChangeRequestStatus.REQUESTED.value
        tasks = list_recall_tasks(session, project_id=int(project.id))
        assert tasks, "issued unit must open a recall before submit/approve"
        with pytest.raises(ConfigChangeError, match="inventory is returned"):
            submit_config_change(
                session,
                int(cr.id),
                actor=admin_user,
                target_hierarchy_config_id=int(target.id),
                reason_remarks="blocked until inspect",
            )
    finally:
        _cleanup(session, project, cfg, inventories, extra_cfgs=[target])


def test_generate_blocked_while_config_change_open(
    session: Session, admin_user: User
):
    names = [f"Gen-{uuid.uuid4().hex[:5]}"]
    code = f"C12G-{uuid.uuid4().hex[:8].upper()}"
    cfg = _available_config(session, admin_user, names, code)
    project = create_draft_project(
        session,
        {
            "name": f"CfgGen-{code}",
            "hierarchy_config_id": cfg.id,
            "product_type": "SSDLS-1",
            "flight_count": 1,
            "sdls_per_flight": 1,
            "start_date": datetime.now(timezone.utc),
        },
        actor=admin_user,
    )
    approve_project(session, project.id, actor=admin_user)
    try:
        cr = request_config_change(session, int(project.id), actor=admin_user)
        assert cr.status in {
            ConfigChangeRequestStatus.REQUESTED.value,
            ConfigChangeRequestStatus.INVENTORY_RETURNED.value,
        }
        with pytest.raises(ProjectWorkflowError, match="configuration change"):
            generate_project_hierarchy(session, project.id, actor=admin_user)
    finally:
        _cleanup(session, project, cfg, [])


def test_cancel_config_change_unblocks_operations(
    session: Session, admin_user: User
):
    # Use Entity List catalog names (Settings → Definitions).
    names = ["Comm"]
    code = f"C12X-{uuid.uuid4().hex[:8].upper()}"
    cfg = _available_config(session, admin_user, names, code)
    project = create_draft_project(
        session,
        {
            "name": f"CfgCancel-{code}",
            "hierarchy_config_id": cfg.id,
            "product_type": "SSDLS-1",
            "flight_count": 1,
            "sdls_per_flight": 1,
            "start_date": datetime.now(timezone.utc),
        },
        actor=admin_user,
    )
    approve_project(session, project.id, actor=admin_user)
    try:
        cr = request_config_change(session, int(project.id), actor=admin_user)
        assert cr.status in {
            ConfigChangeRequestStatus.REQUESTED.value,
            ConfigChangeRequestStatus.INVENTORY_RETURNED.value,
        }
        assert get_open_config_change(session, int(project.id)) is not None

        with pytest.raises(ProjectWorkflowError, match="configuration change"):
            generate_project_hierarchy(session, project.id, actor=admin_user)

        cancelled = cancel_config_change(session, int(cr.id), actor=admin_user)
        assert cancelled.status == ConfigChangeRequestStatus.CANCELLED.value
        assert get_open_config_change(session, int(project.id)) is None

        # Withdrawal unblocks hierarchy generation again.
        result = generate_project_hierarchy(session, project.id, actor=admin_user)
        assert result["status"] == ProjectWorkflowStatus.READY_FOR_INVENTORY.value

        again = request_config_change(session, int(project.id), actor=admin_user)
        assert again.id != cr.id
        assert again.status in {
            ConfigChangeRequestStatus.REQUESTED.value,
            ConfigChangeRequestStatus.INVENTORY_RETURNED.value,
        }
    finally:
        _cleanup(session, project, cfg, [])


def test_submit_accepts_target_config_product_type(
    session: Session, admin_user: User
):
    names = [f"Pt-{uuid.uuid4().hex[:5]}"]
    project, cfg = _ready_named_project(session, admin_user, names)
    target = _available_config(
        session,
        admin_user,
        [f"T2-{uuid.uuid4().hex[:5]}"],
        f"PT2-{uuid.uuid4().hex[:6]}",
        product_types=[{"code": "SSDLS-2", "name": "LDR"}],
    )
    try:
        cr = request_config_change(session, int(project.id), actor=admin_user)
        session.refresh(cr)
        assert cr.status == ConfigChangeRequestStatus.INVENTORY_RETURNED.value

        with pytest.raises(ConfigChangeError, match="Product type"):
            submit_config_change(
                session,
                int(cr.id),
                actor=admin_user,
                target_hierarchy_config_id=int(target.id),
                reason_remarks="Need SSDLS-2 tree",
                product_type="SSDLS-1",
            )

        cr = submit_config_change(
            session,
            int(cr.id),
            actor=admin_user,
            target_hierarchy_config_id=int(target.id),
            reason_remarks="Need SSDLS-2 tree",
            product_type="SSDLS-2",
        )
        assert cr.status == ConfigChangeRequestStatus.SUBMITTED.value
        assert cr.target_product_type == "SSDLS-2"
    finally:
        _cleanup(session, project, cfg, [], extra_cfgs=[target])
