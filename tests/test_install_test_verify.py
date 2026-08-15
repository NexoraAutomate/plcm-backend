"""Spec 08 — install, test, report complete, HM verify."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.auth import hash_password
from app.database import engine
from app.domain.workflow_status import ItemStatus
from app.models.base import IssuanceEventType, ItemTestResult
from app.models.tables import (
    InventoryIssuance,
    InventoryIssuanceEvent,
    Role,
    System,
    User,
)
from app.services.hierarchy_developer_service import assign_developer, list_assigned_work
from app.services.inventory_reservation_service import reserve_inventory
from app.services.item_install_verify_service import (
    ItemInstallVerifyError,
    list_verification_queue,
    report_complete,
    start_install,
    submit_test,
    verify_issuance,
)
from app.services.item_request_service import create_item_request, issue_item_request
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.workflow_foundation_seed import ensure_workflow_statuses
from tests.test_issue_to_developer import _cleanup, _ready_project, _stock_for_system


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
    user = _make_role_user(session, role_name="Developer", full_name="Spec08 Developer")
    yield user
    session.delete(user)
    session.commit()


@pytest.fixture()
def other_developer(session: Session):
    user = _make_role_user(session, role_name="Developer", full_name="Other Developer")
    yield user
    session.delete(user)
    session.commit()


def _issue_to_developer(session: Session, admin: User, developer: User, serial: str):
    sys_name = f"Inst-{uuid.uuid4().hex[:6]}"
    project, cfg = _ready_project(session, admin, system_name=sys_name)
    inv = _stock_for_system(session, name=sys_name, serials=[serial])
    target = session.exec(select(System).where(System.project_id == project.id)).first()
    assign_developer(
        session, "system", int(target.id), int(developer.id), actor=admin
    )
    reserve_inventory(
        session,
        project.id,
        {
            "target_entity_type": "system",
            "target_entity_id": int(target.id),
            "serial_number": serial,
        },
        actor=admin,
    )
    req = create_item_request(
        session, entity_type="system", entity_id=int(target.id), actor=developer
    )
    issued = issue_item_request(
        session,
        int(req.id),
        actor=admin,
        signature_type="DIGITAL",
        signature_payload="data:image/png;base64,aaa",
    )
    return project, cfg, inv, target, issued


def _event_types(session: Session, issuance_id: int) -> list[str]:
    rows = session.exec(
        select(InventoryIssuanceEvent)
        .where(InventoryIssuanceEvent.issuance_id == issuance_id)
        .order_by(InventoryIssuanceEvent.created_at, InventoryIssuanceEvent.id)
    ).all()
    return [row.event_type for row in rows]


def test_happy_path_pass_and_verify(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-ITV-1"
    )
    try:
        start = start_install(
            session, "system", int(target.id), actor=developer_user
        )
        assert start.item_lifecycle_status == ItemStatus.INSTALLATION_IN_PROGRESS.value
        assert start.installed_at is not None

        tested = submit_test(
            session, "system", int(target.id), result="pass", actor=developer_user
        )
        assert tested.test_result == ItemTestResult.PASS.value
        assert tested.item_lifecycle_status == ItemStatus.UNDER_TESTING_REVIEW.value
        assert tested.defect_pending is False

        completed = report_complete(
            session, "system", int(target.id), actor=developer_user
        )
        assert completed.complete_reported_at is not None
        assert completed.item_lifecycle_status == ItemStatus.UNDER_TESTING_REVIEW.value

        queue = list_verification_queue(session, admin_user)
        assert any(row["issuance_id"] == issued.issued_issuance_id for row in queue)

        verified = verify_issuance(
            session, int(issued.issued_issuance_id), actor=admin_user
        )
        assert verified.verified_at is not None
        assert verified.item_lifecycle_status == ItemStatus.INSTALLED_VERIFIED.value

        work = list_assigned_work(session, int(developer_user.id))
        row = next(r for r in work if r["entity_id"] == int(target.id))
        assert row["item_status"] == ItemStatus.INSTALLED_VERIFIED.value
        assert row["verified"] is True
        assert row["can_install"] is False
    finally:
        _cleanup(session, project, cfg, inv)


def test_verify_before_complete_rejected(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-ITV-2"
    )
    try:
        start_install(session, "system", int(target.id), actor=developer_user)
        submit_test(
            session, "system", int(target.id), result="pass", actor=developer_user
        )
        with pytest.raises(ItemInstallVerifyError, match="reports complete"):
            verify_issuance(session, int(issued.issued_issuance_id), actor=admin_user)
        row = session.get(InventoryIssuance, issued.issued_issuance_id)
        assert row.verified_at is None
        assert row.item_lifecycle_status == ItemStatus.UNDER_TESTING_REVIEW.value
    finally:
        _cleanup(session, project, cfg, inv)


def test_fail_marks_defect_pending_never_verified(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-ITV-3"
    )
    try:
        start_install(session, "system", int(target.id), actor=developer_user)
        failed = submit_test(
            session, "system", int(target.id), result="fail", actor=developer_user
        )
        assert failed.test_result == ItemTestResult.FAIL.value
        assert failed.defect_pending is True
        assert failed.item_lifecycle_status == ItemStatus.UNDER_TESTING_REVIEW.value

        with pytest.raises(ItemInstallVerifyError, match="Pass test"):
            report_complete(session, "system", int(target.id), actor=developer_user)
        with pytest.raises(ItemInstallVerifyError, match="Pass test"):
            verify_issuance(session, int(issued.issued_issuance_id), actor=admin_user)

        queue = list_verification_queue(session, admin_user)
        assert not any(row["issuance_id"] == issued.issued_issuance_id for row in queue)

        types = _event_types(session, int(issued.issued_issuance_id))
        assert IssuanceEventType.TEST_FAILED.value in types
        assert IssuanceEventType.DEFECT_PENDING.value in types
        assert IssuanceEventType.VERIFIED.value not in types
    finally:
        _cleanup(session, project, cfg, inv)


def test_non_assigned_developer_blocked(
    session: Session,
    admin_user: User,
    developer_user: User,
    other_developer: User,
):
    project, cfg, inv, target, _issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-ITV-4"
    )
    try:
        with pytest.raises(ItemInstallVerifyError, match="assigned developer"):
            start_install(session, "system", int(target.id), actor=other_developer)
    finally:
        _cleanup(session, project, cfg, inv)


def test_event_order_on_pass_path(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-ITV-5"
    )
    try:
        start_install(session, "system", int(target.id), actor=developer_user)
        submit_test(
            session, "system", int(target.id), result="pass", actor=developer_user
        )
        report_complete(session, "system", int(target.id), actor=developer_user)
        verify_issuance(session, int(issued.issued_issuance_id), actor=admin_user)
        types = _event_types(session, int(issued.issued_issuance_id))
        expected = [
            IssuanceEventType.ISSUED.value,
            IssuanceEventType.INSTALL_STARTED.value,
            IssuanceEventType.TEST_PASSED.value,
            IssuanceEventType.COMPLETE_REPORTED.value,
            IssuanceEventType.VERIFIED.value,
        ]
        assert types == expected
    finally:
        _cleanup(session, project, cfg, inv)
