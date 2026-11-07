"""
Shared helpers for MHD system tests (P6) — hierarchy + stock + Track A/B spines.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app.domain.workflow_status import ItemStatus
from app.models.base import CaseStatus, EntityType, FaultType, FaultyEntityStatus
from app.models.tables import (
    FaultyEntity,
    Hierarchy,
    Inventory,
    InventoryInstance,
    InventoryIssuance,
    InventoryIssuanceEvent,
    InventoryReservation,
    InventoryReworkCase,
    MaintenanceCase,
    Project,
    Status,
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
from app.services.inventory_service import create_inventory_instance
from app.services.project_workflow_service import approve_project, create_draft_project
from tests.functional.test_mhd_dual_track_ft import _ensure_me_user, _seed_fault_and_request
from tests.mhd_fixtures import cleanup_project, unique


def _item_status_id(session: Session, name: str) -> int:
    row = session.exec(
        select(Status).where(
            Status.status_name == name, Status.status_type == "inventory"
        )
    ).first()
    assert row and row.id
    return int(row.id)


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


def seed_spare_stock(
    session: Session,
    *,
    name: str,
    serials: list[str],
    inventory_type: str = "system",
    part_number: str | None = None,
) -> Inventory:
    """Create AVAILABLE inventory instances for Track A reserve/issue."""
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


def seed_faulty_unit_inventory(
    session: Session,
    *,
    entity_id: int,
    part_number: str,
    serial_number: str,
    inventory_type: str = "system",
    warranty_days: int | None = None,
) -> Inventory:
    """Inventory for the removed/faulty unit so Track B rework can open after IM issue."""
    available_id = _item_status_id(session, ItemStatus.AVAILABLE.value)
    inv = Inventory(
        name=unique("FAULTY"),
        inventory_type=inventory_type,
        quantity=0,
        part_number=part_number,
        entity_id=int(entity_id),
        status_id=available_id,
        warranty_expires_at=(
            datetime.now(timezone.utc) + timedelta(days=warranty_days)
            if warranty_days
            else None
        ),
        oem_name="OEM-MHD" if warranty_days else None,
    )
    session.add(inv)
    session.flush()
    create_inventory_instance(
        session,
        inv,
        serial_number=serial_number,
        status_id=available_id,
        warranty_expires_at=inv.warranty_expires_at,
    )
    session.commit()
    session.refresh(inv)
    return inv


def build_hierarchy_case(
    session: Session,
    admin: User,
    *,
    spare_serials: list[str] | None = None,
    with_faulty_inventory: bool = True,
    warranty_days: int | None = None,
) -> dict[str, Any]:
    """
    Hierarchy project + system + maintenance case + optional stock.

    Returns dict with keys: project, cfg, system, case, spare_inv, faulty_inv, me, system_name
    """
    system_name = unique("MHDSys")
    _ensure_catalog(session, system_name, "system")
    _ensure_catalog(session, "RF", "subsystem")
    code = f"MHD-{uuid.uuid4().hex[:8].upper()}"
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
            "name": f"MHD-{code}",
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

    system = session.exec(
        select(System).where(System.project_id == project.id).order_by(System.id)
    ).first()
    assert system and system.id

    part_number = unique("PN-MHD")
    now = datetime.now(timezone.utc)
    case = MaintenanceCase(
        case_number=unique("MC"),
        project_id=int(project.id),
        project_name=project.name,
        description="MHD ST dual-track case",
        status=CaseStatus.OPEN,
        reported_by=int(admin.id),
        entity_type="system",
        entity_id=int(system.id),
        part_number=part_number,
        reported_at=now,
    )
    session.add(case)
    session.commit()
    session.refresh(case)

    fe = FaultyEntity(
        case_id=int(case.id),
        entity_type=EntityType.SYSTEM,
        entity_id=int(system.id),
        fault_type=FaultType.HARDWARE,
        fault_description="MHD ST fault",
        status=FaultyEntityStatus.IDENTIFIED,
        identified_by=int(admin.id),
        part_number=part_number,
        serial_number=unique("OLD-SN"),
        entity_name=system_name,
    )
    session.add(fe)
    session.commit()
    session.refresh(fe)

    spare_inv = None
    if spare_serials is not None:
        spare_inv = seed_spare_stock(
            session,
            name=system_name,
            serials=spare_serials,
            inventory_type="system",
            part_number=part_number,
        )

    faulty_inv = None
    if with_faulty_inventory:
        faulty_inv = seed_faulty_unit_inventory(
            session,
            entity_id=int(system.id),
            part_number=part_number,
            serial_number=str(fe.serial_number),
            inventory_type="system",
            warranty_days=warranty_days,
        )

    me = _ensure_me_user(session)
    return {
        "project": project,
        "cfg": cfg,
        "system": system,
        "case": case,
        "fe": fe,
        "spare_inv": spare_inv,
        "faulty_inv": faulty_inv,
        "me": me,
        "system_name": system_name,
        "part_number": part_number,
    }


def cleanup_st_fixture(
    session: Session,
    *,
    project: Project,
    cfg: Any,
    inventories: list[Inventory | None] | None = None,
) -> None:
    """Best-effort cleanup for hierarchy + inventory ST fixtures."""
    try:
        cleanup_project(session, project)
    except Exception:
        session.rollback()

    invs = [i for i in (inventories or []) if i is not None]
    try:
        rows = session.exec(
            select(InventoryReservation).where(
                InventoryReservation.project_id == project.id
            )
        ).all()
        for row in rows:
            session.delete(row)
        session.commit()
    except Exception:
        session.rollback()

    for inv in invs:
        try:
            session.refresh(inv)
            issuances = session.exec(
                select(InventoryIssuance).where(InventoryIssuance.inventory_id == inv.id)
            ).all()
            for iss in issuances:
                events = session.exec(
                    select(InventoryIssuanceEvent).where(
                        InventoryIssuanceEvent.issuance_id == iss.id
                    )
                ).all()
                for ev in events:
                    session.delete(ev)
                session.delete(iss)
            session.commit()
            insts = session.exec(
                select(InventoryInstance).where(InventoryInstance.inventory_id == inv.id)
            ).all()
            for inst in insts:
                session.delete(inst)
            session.delete(inv)
            session.commit()
        except Exception:
            session.rollback()

    try:
        if cfg is not None and getattr(cfg, "id", None):
            delete_configuration(session, cfg.id, hard=True)
    except Exception:
        session.rollback()


def seed_request(client: TestClient, headers: dict, case_id: int) -> dict:
    return _seed_fault_and_request(client, headers, case_id)


def advance_track_a_to_im_issue_pending(
    client: TestClient,
    headers: dict,
    *,
    case_id: int,
    request_id: int,
    me_id: int,
    inventory_id: int,
    serial_number: str,
    target_entity_id: int,
    target_entity_type: str = "system",
) -> dict:
    """assign-me → reserve → PD approve → ME request-issue."""
    assign = client.post(
        f"/api/maintenance-cases/{case_id}/replacement-requests/{request_id}/assign-me/",
        headers=headers,
        json={"assigned_me_id": int(me_id)},
    )
    assert assign.status_code == 200, assign.text

    reserve = client.post(
        f"/api/maintenance-cases/{case_id}/replacement-requests/{request_id}/reserve/",
        headers=headers,
        json={
            "inventory_id": int(inventory_id),
            "serial_number": serial_number,
            "target_entity_type": target_entity_type,
            "target_entity_id": int(target_entity_id),
        },
    )
    assert reserve.status_code == 200, reserve.text

    decide = client.post(
        f"/api/maintenance-cases/{case_id}/replacement-requests/{request_id}/pd-decision/",
        headers=headers,
        json={"decision": "approve"},
    )
    assert decide.status_code == 200, decide.text
    assert decide.json()["status"] == "pd_approved"

    req_issue = client.post(
        f"/api/maintenance-cases/{case_id}/replacement-requests/{request_id}/request-issue/",
        headers=headers,
    )
    assert req_issue.status_code == 200, req_issue.text
    assert req_issue.json()["status"] == "im_issue_pending"
    return req_issue.json()


def im_issue_replacement(
    client: TestClient,
    headers: dict,
    *,
    case_id: int,
    request_id: int,
) -> dict:
    res = client.post(
        f"/api/maintenance-cases/{case_id}/replacement-requests/{request_id}/im-issue/",
        headers=headers,
        json={"signature_type": "HARD_COPY", "signature_payload": "ACK"},
    )
    return res


def complete_ait(
    client: TestClient,
    headers: dict,
    *,
    case_id: int,
    request_id: int,
    decision: str = "approve",
    reject_reason: str | None = None,
) -> dict:
    start = client.post(
        f"/api/maintenance-cases/{case_id}/replacement-requests/{request_id}/ait/start/",
        headers=headers,
    )
    assert start.status_code == 200, start.text

    attach = client.post(
        f"/api/maintenance-cases/{case_id}/replacement-requests/{request_id}/ait/attachments/",
        headers=headers,
        json={"display_name": "AIT Evidence", "file_id": 1},
    )
    assert attach.status_code == 200, attach.text

    payload: dict[str, Any] = {"decision": decision}
    if reject_reason:
        payload["reject_reason"] = reject_reason
    ait = client.post(
        f"/api/maintenance-cases/{case_id}/replacement-requests/{request_id}/ait/pd-decision/",
        headers=headers,
        json=payload,
    )
    assert ait.status_code == 200, ait.text
    return ait.json()


def walk_track_a_to_patch_delivered(
    client: TestClient,
    headers: dict,
    *,
    case_id: int,
    request_id: int,
    me_id: int,
    inventory_id: int,
    serial_number: str,
    target_entity_id: int,
    target_entity_type: str = "system",
) -> dict:
    advance_track_a_to_im_issue_pending(
        client,
        headers,
        case_id=case_id,
        request_id=request_id,
        me_id=me_id,
        inventory_id=inventory_id,
        serial_number=serial_number,
        target_entity_type=target_entity_type,
        target_entity_id=target_entity_id,
    )
    issued = im_issue_replacement(
        client, headers, case_id=case_id, request_id=request_id
    )
    assert issued.status_code == 200, issued.text
    assert issued.json()["status"] == "shipped_replaced_badge"
    assert issued.json().get("red_notified_at") is not None
    return complete_ait(
        client, headers, case_id=case_id, request_id=request_id, decision="approve"
    )


def get_track_b_rework(
    session: Session, case_id: int
) -> Optional[InventoryReworkCase]:
    return session.exec(
        select(InventoryReworkCase)
        .where(InventoryReworkCase.maintenance_case_id == case_id)
        .order_by(InventoryReworkCase.id.desc())
    ).first()


def walk_track_b_repair_restock(
    client: TestClient,
    headers: dict,
    session: Session,
    *,
    case_id: int,
    ie_user_id: int,
    rework_id: int | None = None,
) -> dict:
    """Reception → IE → disposition repairable → PD approve restock."""
    if rework_id is None:
        session.expire_all()
        rework = get_track_b_rework(session, case_id)
        assert rework is not None, "Track B rework missing after IM issue"
        rework_id = int(rework.id)

    reception = client.post(
        f"/api/maintenance-cases/{case_id}/returned-units/{rework_id}/reception/",
        headers=headers,
        json={},
    )
    assert reception.status_code == 200, reception.text

    assign = client.post(
        f"/api/maintenance-cases/{case_id}/returned-units/{rework_id}/assign-ie/",
        headers=headers,
        json={"ie_user_id": int(ie_user_id)},
    )
    assert assign.status_code == 200, assign.text

    hand = client.post(
        f"/api/maintenance-cases/{case_id}/returned-units/{rework_id}/handover-request/",
        headers=headers,
        json={},
    )
    assert hand.status_code == 200, hand.text

    issue = client.post(
        f"/api/maintenance-cases/{case_id}/returned-units/{rework_id}/im-issue-to-ie/",
        headers=headers,
        json={},
    )
    assert issue.status_code == 200, issue.text

    disp = client.post(
        f"/api/maintenance-cases/{case_id}/returned-units/{rework_id}/disposition/",
        headers=headers,
        json={"outcome": "repairable"},
    )
    assert disp.status_code == 200, disp.text

    submit = client.post(
        f"/api/maintenance-cases/{case_id}/returned-units/{rework_id}/repair-submit/",
        headers=headers,
        json={"notes": "ST repair ok"},
    )
    assert submit.status_code == 200, submit.text

    decide = client.post(
        f"/api/maintenance-cases/{case_id}/returned-units/{rework_id}/pd-repair-decision/",
        headers=headers,
        json={"decision": "approve"},
    )
    assert decide.status_code == 200, decide.text
    body = decide.json()
    assert body["is_track_b_terminal"] is True
    return body


def walk_track_b_to_inspection(
    client: TestClient,
    headers: dict,
    *,
    case_id: int,
    rework_id: int,
    ie_user_id: int,
) -> dict:
    for path, payload in (
        ("reception", {}),
        ("assign-ie", {"ie_user_id": int(ie_user_id)}),
        ("handover-request", {}),
        ("im-issue-to-ie", {}),
    ):
        res = client.post(
            f"/api/maintenance-cases/{case_id}/returned-units/{rework_id}/{path}/",
            headers=headers,
            json=payload,
        )
        assert res.status_code == 200, res.text
    return res.json()


def close_case(
    client: TestClient, headers: dict, *, case_id: int, notes: str = "ST close"
) -> Any:
    return client.put(
        f"/api/maintenance-cases/{case_id}/",
        headers=headers,
        json={"status": "closed", "resolution_notes": notes},
    )


__all__ = [
    "build_hierarchy_case",
    "cleanup_st_fixture",
    "seed_request",
    "seed_spare_stock",
    "advance_track_a_to_im_issue_pending",
    "im_issue_replacement",
    "complete_ait",
    "walk_track_a_to_patch_delivered",
    "walk_track_b_repair_restock",
    "walk_track_b_to_inspection",
    "get_track_b_rework",
    "close_case",
]
