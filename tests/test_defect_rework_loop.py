"""Spec 10 — defect / rework loop."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from app.auth import hash_password
from app.database import engine
from app.domain.workflow_status import ItemStatus
from app.models.base import IssuanceEventType, ReworkCaseStatus, ReworkStage
from app.models.tables import InventoryInstance, InventoryIssuance, Role, User
from app.services.inventory_reservation_service import get_item_status_id, item_status_name
from app.services.inventory_service import create_inventory_instance
from app.services.item_install_verify_service import (
    ItemInstallVerifyError,
    report_complete,
    start_install,
    submit_test,
    verify_issuance,
)
from app.services.item_rework_service import (
    ItemReworkError,
    disposition_item,
    open_rework_for_entity,
    reissue_item,
    remove_item,
    repair_complete,
    return_item,
    rework_events,
    start_inspection,
)
from app.services.project_progress_service import compute_project_progress
from app.services.schema_bootstrap import ensure_user_management_schema
from app.services.workflow_foundation_seed import ensure_workflow_statuses
from tests.test_install_test_verify import _issue_to_developer
from tests.test_issue_to_developer import _cleanup


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
    user = _make_role_user(session, role_name="Developer", full_name="Spec10 Developer")
    yield user
    session.delete(user)
    session.commit()


SIGNATURE = {
    "signature_type": "DIGITAL",
    "signature_payload": "data:image/png;base64,aaa",
}


def _fail_and_return(session: Session, target, developer: User):
    start_install(session, "system", int(target.id), actor=developer)
    submit_test(session, "system", int(target.id), result="fail", actor=developer)
    case = open_rework_for_entity(session, "system", int(target.id))
    assert case is not None
    remove_item(session, int(case.id), actor=developer)
    return return_item(session, int(case.id), actor=developer)


def _repair_and_reissue(session: Session, case, actor: User):
    start_inspection(session, int(case.id), actor=actor)
    disposition_item(session, int(case.id), actor=actor, outcome="repairable")
    repair_complete(session, int(case.id), actor=actor)
    return reissue_item(session, int(case.id), actor=actor, **SIGNATURE)


def test_pass_path_after_one_rework(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-RW-1"
    )
    try:
        case = _fail_and_return(session, target, developer_user)
        case = _repair_and_reissue(session, case, admin_user)
        assert case.stage == ReworkStage.REISSUED.value
        assert case.status == ReworkCaseStatus.OPEN.value

        start_install(session, "system", int(target.id), actor=developer_user)
        passed = submit_test(
            session, "system", int(target.id), result="pass", actor=developer_user
        )
        assert passed.defect_pending is False
        report_complete(session, "system", int(target.id), actor=developer_user)
        verified = verify_issuance(
            session, int(passed.id), actor=admin_user
        )
        assert verified.item_lifecycle_status == ItemStatus.INSTALLED_VERIFIED.value
        session.refresh(case)
        assert case.status == ReworkCaseStatus.CLOSED.value
        types = [ev.event_type for ev in rework_events(session, case)]
        assert IssuanceEventType.REWORK_OPENED.value in types
        assert IssuanceEventType.ITEM_RETURNED.value in types
        assert IssuanceEventType.REISSUED.value in types
        assert IssuanceEventType.REWORK_CLOSED.value in types
    finally:
        _cleanup(session, project, cfg, inv)


def test_double_fail_preserves_history(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, _issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-RW-2"
    )
    try:
        case = _fail_and_return(session, target, developer_user)
        case = _repair_and_reissue(session, case, admin_user)
        start_install(session, "system", int(target.id), actor=developer_user)
        submit_test(session, "system", int(target.id), result="fail", actor=developer_user)
        session.refresh(case)
        assert case.attempt_count == 2
        assert case.stage == ReworkStage.FAILED.value
        assert case.status == ReworkCaseStatus.OPEN.value
        types = [ev.event_type for ev in rework_events(session, case)]
        assert types.count(IssuanceEventType.REWORK_OPENED.value) == 2
        assert IssuanceEventType.TEST_FAILED.value in types
    finally:
        _cleanup(session, project, cfg, inv)


def test_scrap_cannot_reissue_same_serial_replace_issues_new(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, _issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-RW-OLD"
    )
    try:
        extra = create_inventory_instance(
            session,
            inv,
            serial_number="SN-RW-NEW",
            status_id=get_item_status_id(session, ItemStatus.AVAILABLE.value),
        )
        session.commit()
        session.refresh(extra)

        case = _fail_and_return(session, target, developer_user)
        start_inspection(session, int(case.id), actor=admin_user)
        disposition_item(session, int(case.id), actor=admin_user, outcome="scrapped")
        old_id = case.current_instance_id
        with pytest.raises(ItemReworkError, match="Scrap disposition cannot re-issue"):
            reissue_item(session, int(case.id), actor=admin_user, **SIGNATURE)

        case = reissue_item(
            session,
            int(case.id),
            actor=admin_user,
            replacement_instance_id=int(extra.id),
            **SIGNATURE,
        )
        assert case.current_instance_id == extra.id
        assert case.stage == ReworkStage.REISSUED.value
        old = session.get(InventoryInstance, old_id)
        assert item_status_name(session, old.status_id) == ItemStatus.SCRAPPED.value
        new_iss = session.get(InventoryIssuance, case.current_issuance_id)
        assert new_iss is not None
        assert new_iss.serial_number == "SN-RW-NEW"
        assert new_iss.defect_pending is False
    finally:
        _cleanup(session, project, cfg, inv)


def test_reissue_requires_signature(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, _issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-RW-3"
    )
    try:
        case = _fail_and_return(session, target, developer_user)
        start_inspection(session, int(case.id), actor=admin_user)
        disposition_item(session, int(case.id), actor=admin_user, outcome="repairable")
        repair_complete(session, int(case.id), actor=admin_user)
        with pytest.raises(ItemReworkError, match="Signature is required"):
            reissue_item(
                session,
                int(case.id),
                actor=admin_user,
                signature_type=None,
                signature_payload=None,
            )
    finally:
        _cleanup(session, project, cfg, inv)


def test_open_rework_excluded_from_verified_progress(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, _issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-RW-4"
    )
    try:
        _fail_and_return(session, target, developer_user)
        snapshot = compute_project_progress(session, int(project.id))
        assert snapshot["verified_leaves"] == 0
        assert snapshot["can_complete"] is False
        reasons = {row["reason"] for row in snapshot["bottlenecks"]}
        assert "fail_loop" in reasons
    finally:
        _cleanup(session, project, cfg, inv)


def test_fail_still_blocks_verify_without_loop(
    session: Session, admin_user: User, developer_user: User
):
    project, cfg, inv, target, issued = _issue_to_developer(
        session, admin_user, developer_user, "SN-RW-5"
    )
    try:
        start_install(session, "system", int(target.id), actor=developer_user)
        submit_test(session, "system", int(target.id), result="fail", actor=developer_user)
        with pytest.raises(ItemInstallVerifyError):
            report_complete(session, "system", int(target.id), actor=developer_user)
        with pytest.raises(ItemInstallVerifyError):
            verify_issuance(session, int(issued.issued_issuance_id), actor=admin_user)
    finally:
        _cleanup(session, project, cfg, inv)
