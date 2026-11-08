"""Personal MMHD / maintenance dual-track assignment inbox.

Aggregates Track A ReplacementRequest and Track B maintenance-linked rework
rows into a normalized list for My Assignments → MMHD.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.auth import check_permission
from app.models.base import ReplacementRequestStatus, ReworkStage
from app.models.tables import (
    AppNotification,
    Inventory,
    InventoryInstance,
    InventoryReworkCase,
    MaintenanceCase,
    Project,
    ReplacementRequest,
    ReplacementRequestReservation,
    User,
)
from app.services.track_b_inspection_service import TRACK_B_TERMINAL, is_track_b_terminal

TRACK_A_CLOSED = frozenset(
    {
        ReplacementRequestStatus.TRACK_A_CLOSED.value,
        ReplacementRequestStatus.PD_REJECTED.value,
    }
)

STATUS_LABELS: dict[str, str] = {
    ReplacementRequestStatus.REPLACEMENT_REQUESTED.value: "Awaiting PD approval",
    ReplacementRequestStatus.PD_APPROVED.value: "PD approved — ME request issue",
    ReplacementRequestStatus.PD_REJECTED.value: "PD rejected",
    ReplacementRequestStatus.IM_ISSUE_PENDING.value: "Awaiting IM issue",
    ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value: "Shipped — start AIT",
    ReplacementRequestStatus.AIT_IN_PROGRESS.value: "AIT in progress",
    ReplacementRequestStatus.AIT_APPROVED.value: "AIT approved",
    ReplacementRequestStatus.AIT_REJECTED.value: "AIT rejected — re-issue",
    ReplacementRequestStatus.PATCH_DELIVERED.value: "Patch delivered",
    ReplacementRequestStatus.TRACK_A_CLOSED.value: "Track A closed",
    ReworkStage.AWAITING_FAULTY_ARRIVAL.value: "Awaiting faulty arrival",
    ReworkStage.RECEIVED.value: "Received — assign IE",
    ReworkStage.IE_ASSIGNED.value: "IE assigned — request handover",
    ReworkStage.ISSUED_TO_IE.value: "Awaiting IM issue to IE",
    ReworkStage.INSPECTION_UNDER_PROCESS.value: "Inspection under process",
    ReworkStage.REPAIR_UNDER_PROGRESS.value: "Repair under progress",
    ReworkStage.WARRANTY_CLAIM.value: "Warranty claim",
    ReworkStage.DISCARD_PENDING.value: "Discard pending IM confirm",
    ReworkStage.RESTOCKED.value: "Restocked",
    ReworkStage.DISCARDED.value: "Discarded",
    ReworkStage.CLAIM_CLOSED.value: "Claim closed",
}


def _user_display(user: Optional[User]) -> Optional[str]:
    if not user:
        return None
    return user.full_name or user.username


def _perm(user: User, *codes: str) -> bool:
    return any(check_permission(user, code) for code in codes)


def _status_label(status: Optional[str]) -> str:
    key = (status or "").strip().lower()
    if not key:
        return "Unknown"
    return STATUS_LABELS.get(key, key.replace("_", " ").title())


def _track_a_task_type(status: str) -> str:
    if status == ReplacementRequestStatus.REPLACEMENT_REQUESTED.value:
        return "pd_approval"
    if status == ReplacementRequestStatus.PD_APPROVED.value:
        return "me_request_issue"
    if status == ReplacementRequestStatus.IM_ISSUE_PENDING.value:
        return "im_issue"
    if status in (
        ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value,
        ReplacementRequestStatus.AIT_IN_PROGRESS.value,
    ):
        return "me_ait"
    if status == ReplacementRequestStatus.AIT_IN_PROGRESS.value:
        return "pd_ait"
    if status == ReplacementRequestStatus.AIT_REJECTED.value:
        return "im_issue"
    if status == ReplacementRequestStatus.PATCH_DELIVERED.value:
        return "track_a_close"
    return "track_a"


def _track_b_task_type(stage: str) -> str:
    mapping = {
        ReworkStage.AWAITING_FAULTY_ARRIVAL.value: "reception",
        ReworkStage.RECEIVED.value: "assign_ie",
        ReworkStage.IE_ASSIGNED.value: "ie_handover",
        ReworkStage.ISSUED_TO_IE.value: "im_issue_to_ie",
        ReworkStage.INSPECTION_UNDER_PROCESS.value: "ie_disposition",
        ReworkStage.REPAIR_UNDER_PROGRESS.value: "pd_repair_decision",
        ReworkStage.DISCARD_PENDING.value: "im_confirm_discard",
        ReworkStage.WARRANTY_CLAIM.value: "warranty_claim",
    }
    return mapping.get(stage, "track_b")


def _row_needs_action(row: dict[str, Any]) -> bool:
    return any(
        bool(row.get(key))
        for key in (
            "can_pd_decide",
            "can_assign_me",
            "can_me_request_issue",
            "can_im_issue",
            "can_start_ait",
            "can_upload_ait",
            "can_pd_ait",
            "can_reception",
            "can_assign_ie",
            "can_handover",
            "can_im_issue_to_ie",
            "can_disposition",
            "can_repair_submit",
            "can_pd_repair",
            "can_confirm_discard",
        )
    )


def maintenance_assignment_needs_action(row: dict[str, Any]) -> bool:
    """Public helper for pending-action badge counts."""
    return _row_needs_action(row)


def _lifecycle(row: dict[str, Any]) -> str:
    status = (row.get("status") or "").strip().lower()
    track = row.get("track")
    if track == "a" and status in TRACK_A_CLOSED:
        return "closed"
    if track == "b" and (status in TRACK_B_TERMINAL or is_track_b_terminal(status)):
        return "closed"
    if _row_needs_action(row):
        return "needs_action"
    return "in_progress"


def _acted_maintenance_case_ids(session: Session, user_id: int) -> set[int]:
    """Case IDs where ``user_id`` previously took an action (notification actor)."""
    rows = session.exec(
        select(AppNotification.entity_id).where(
            AppNotification.actor_user_id == int(user_id),
            AppNotification.entity_type == "maintenance_case",
            AppNotification.entity_id.is_not(None),
        )
    ).all()
    return {int(eid) for eid in rows if eid is not None}


def list_maintenance_assigned_work(
    session: Session,
    actor: User,
) -> list[dict[str, Any]]:
    """Return MMHD inbox rows visible / actionable for ``actor``.

    A row appears only when the user is assigned / previously acted on it,
    or currently authorized to act (e.g. PD approval queue).
    """
    uid = int(actor.id)
    can_pd = _perm(actor, "maintenance.replacement_approve")
    can_assign_me_perm = _perm(actor, "maintenance.assign_me")
    can_request_issue_perm = _perm(actor, "maintenance.request_issue")
    can_ait_upload = _perm(actor, "maintenance.ait_upload")
    can_ait_approve = _perm(actor, "maintenance.ait_approve")
    can_im = _perm(actor, "maintenance.im_issue", "inventory.issue", "issue_inventory")
    can_ie = _perm(actor, "maintenance.inspection_disposition", "item.inspect")
    can_reception = _perm(actor, "maintenance.reception")
    can_assign_ie_perm = _perm(actor, "maintenance.assign_ie")
    can_im_issue_to_ie_perm = _perm(
        actor, "maintenance.im_issue_to_ie", "inventory.issue", "issue_inventory"
    )
    can_repair_approve = _perm(actor, "maintenance.repair_approve")
    can_confirm_discard_perm = _perm(
        actor, "maintenance.confirm_discard", "inventory.issue", "issue_inventory"
    )
    acted_case_ids = _acted_maintenance_case_ids(session, uid)

    rows: list[dict[str, Any]] = []
    case_cache: dict[int, MaintenanceCase] = {}
    project_cache: dict[int, Optional[Project]] = {}

    def case_for(case_id: int) -> Optional[MaintenanceCase]:
        if case_id not in case_cache:
            case_cache[case_id] = session.get(MaintenanceCase, case_id)
        return case_cache.get(case_id)

    def project_name_for(project_id: Optional[int]) -> Optional[str]:
        if not project_id:
            return None
        pid = int(project_id)
        if pid not in project_cache:
            project_cache[pid] = session.get(Project, pid)
        project = project_cache.get(pid)
        return project.name if project else None

    # --- Track A ---
    track_a_reqs = session.exec(select(ReplacementRequest)).all()
    for req in track_a_reqs:
        if req.id is None:
            continue
        status = (req.status or "").strip().lower()
        is_me = req.assigned_me_id is not None and int(req.assigned_me_id) == uid
        is_requester = int(req.requested_by_id) == uid

        can_pd_decide = can_pd and status == ReplacementRequestStatus.REPLACEMENT_REQUESTED.value
        can_assign_me = can_assign_me_perm and status in (
            ReplacementRequestStatus.REPLACEMENT_REQUESTED.value,
            ReplacementRequestStatus.PD_APPROVED.value,
            ReplacementRequestStatus.IM_ISSUE_PENDING.value,
        )
        can_me_request_issue = (
            can_request_issue_perm
            and is_me
            and status == ReplacementRequestStatus.PD_APPROVED.value
        )
        can_im_issue = can_im and status == ReplacementRequestStatus.IM_ISSUE_PENDING.value
        can_start_ait = (
            can_ait_upload
            and is_me
            and status == ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value
        )
        can_upload_ait = can_ait_upload and is_me and status in (
            ReplacementRequestStatus.SHIPPED_REPLACED_BADGE.value,
            ReplacementRequestStatus.AIT_IN_PROGRESS.value,
        )
        can_pd_ait = can_ait_approve and status == ReplacementRequestStatus.AIT_IN_PROGRESS.value

        actionable = any(
            (
                can_pd_decide,
                can_assign_me and not req.assigned_me_id,
                can_me_request_issue,
                can_im_issue,
                can_start_ait,
                can_upload_ait,
                can_pd_ait,
            )
        )
        previously_acted = int(req.case_id) in acted_case_ids
        involved = is_me or is_requester or previously_acted
        # Visible only if assigned / previously acted, or currently authorized to act.
        if not (actionable or involved):
            continue
        # Skip fully closed unless the user was involved (Closed tab)
        if status in TRACK_A_CLOSED and not involved:
            continue

        case = case_for(int(req.case_id))
        if not case:
            continue

        me_user = session.get(User, req.assigned_me_id) if req.assigned_me_id else None
        reservation = session.exec(
            select(ReplacementRequestReservation).where(
                ReplacementRequestReservation.replacement_request_id == int(req.id)
            )
        ).first()
        serial = req.issued_serial
        part_number = case.part_number
        if reservation and reservation.inventory_instance_id:
            inst = session.get(InventoryInstance, reservation.inventory_instance_id)
            if inst:
                serial = serial or inst.serial_number
                part_number = part_number or getattr(inst, "configuration_item", None)

        row: dict[str, Any] = {
            "id": f"a:{int(req.id)}",
            "track": "a",
            "task_type": _track_a_task_type(status),
            "case_id": int(req.case_id),
            "case_number": case.case_number,
            "replacement_request_id": int(req.id),
            "rework_id": None,
            "status": status,
            "status_label": _status_label(status),
            "project_id": int(case.project_id) if case.project_id else None,
            "project_name": case.project_name or project_name_for(case.project_id),
            "entity_type": req.faulty_entity_type or case.entity_type,
            "entity_id": req.faulty_entity_ref_id or case.entity_id,
            "part_number": part_number,
            "serial_number": serial,
            "assigned_me_id": req.assigned_me_id,
            "assigned_me_name": _user_display(me_user),
            "assigned_ie_id": None,
            "assigned_ie_name": None,
            "investigating_pd_id": None,
            "investigating_pd_name": None,
            "updated_at": req.updated_at or req.created_at,
            "href": f"/maintenance/cases/{int(req.case_id)}",
            "can_pd_decide": bool(can_pd_decide),
            "can_assign_me": bool(can_assign_me),
            "can_me_request_issue": bool(can_me_request_issue),
            "can_im_issue": bool(can_im_issue),
            "can_start_ait": bool(can_start_ait),
            "can_upload_ait": bool(can_upload_ait),
            "can_pd_ait": bool(can_pd_ait),
            "can_reception": False,
            "can_assign_ie": False,
            "can_handover": False,
            "can_im_issue_to_ie": False,
            "can_disposition": False,
            "can_repair_submit": False,
            "can_pd_repair": False,
            "can_confirm_discard": False,
            "has_reservation": reservation is not None,
        }
        row["lifecycle"] = _lifecycle(row)
        row["needs_action"] = _row_needs_action(row)
        rows.append(row)

    # --- Track B ---
    track_b_reworks = session.exec(
        select(InventoryReworkCase).where(
            InventoryReworkCase.maintenance_case_id.is_not(None)
        )
    ).all()
    for rework in track_b_reworks:
        if rework.id is None or not rework.maintenance_case_id:
            continue
        stage = (rework.stage or "").strip().lower()
        is_ie = (
            rework.assigned_developer_id is not None
            and int(rework.assigned_developer_id) == uid
        )
        is_pd = (
            rework.investigating_pd_id is not None
            and int(rework.investigating_pd_id) == uid
        )

        can_reception_flag = (
            can_reception and stage == ReworkStage.AWAITING_FAULTY_ARRIVAL.value
        )
        can_assign_ie = can_assign_ie_perm and stage == ReworkStage.RECEIVED.value
        can_handover = (
            can_ie
            and is_ie
            and stage == ReworkStage.IE_ASSIGNED.value
        )
        can_im_issue_to_ie = (
            can_im_issue_to_ie_perm and stage == ReworkStage.ISSUED_TO_IE.value
        )
        can_disposition = (
            can_ie
            and is_ie
            and stage == ReworkStage.INSPECTION_UNDER_PROCESS.value
        )
        can_repair_submit = (
            can_ie
            and is_ie
            and stage == ReworkStage.REPAIR_UNDER_PROGRESS.value
        )
        can_pd_repair = (
            (can_repair_approve or is_pd)
            and stage == ReworkStage.REPAIR_UNDER_PROGRESS.value
        )
        can_confirm_discard = (
            can_confirm_discard_perm and stage == ReworkStage.DISCARD_PENDING.value
        )

        actionable = any(
            (
                can_reception_flag,
                can_assign_ie,
                can_handover,
                can_im_issue_to_ie,
                can_disposition,
                can_repair_submit,
                can_pd_repair,
                can_confirm_discard,
            )
        )
        previously_acted = int(rework.maintenance_case_id) in acted_case_ids
        involved = is_ie or is_pd or previously_acted
        # Visible only if assigned / previously acted, or currently authorized to act.
        if not (actionable or involved):
            continue
        if is_track_b_terminal(stage) and not involved:
            continue

        case = case_for(int(rework.maintenance_case_id))
        if not case:
            continue

        ie_user = (
            session.get(User, rework.assigned_developer_id)
            if rework.assigned_developer_id
            else None
        )
        pd_user = (
            session.get(User, rework.investigating_pd_id)
            if rework.investigating_pd_id
            else None
        )
        inventory = session.get(Inventory, rework.inventory_id) if rework.inventory_id else None
        instance = (
            session.get(InventoryInstance, rework.current_instance_id)
            if rework.current_instance_id
            else None
        )
        part_number = (
            (getattr(instance, "configuration_item", None) if instance else None)
            or (inventory.part_number if inventory else None)
            or case.part_number
        )
        serial = instance.serial_number if instance else None

        row = {
            "id": f"b:{int(rework.id)}",
            "track": "b",
            "task_type": _track_b_task_type(stage),
            "case_id": int(rework.maintenance_case_id),
            "case_number": case.case_number,
            "replacement_request_id": None,
            "rework_id": int(rework.id),
            "status": stage,
            "status_label": _status_label(stage),
            "project_id": int(rework.project_id) if rework.project_id else None,
            "project_name": case.project_name or project_name_for(rework.project_id),
            "entity_type": rework.target_entity_type or case.entity_type,
            "entity_id": rework.target_entity_id or case.entity_id,
            "part_number": part_number,
            "serial_number": serial,
            "assigned_me_id": None,
            "assigned_me_name": None,
            "assigned_ie_id": rework.assigned_developer_id,
            "assigned_ie_name": _user_display(ie_user),
            "investigating_pd_id": rework.investigating_pd_id,
            "investigating_pd_name": _user_display(pd_user),
            "updated_at": rework.updated_at or rework.opened_at,
            "href": f"/maintenance/cases/{int(rework.maintenance_case_id)}",
            "can_pd_decide": False,
            "can_assign_me": False,
            "can_me_request_issue": False,
            "can_im_issue": False,
            "can_start_ait": False,
            "can_upload_ait": False,
            "can_pd_ait": False,
            "can_reception": bool(can_reception_flag),
            "can_assign_ie": bool(can_assign_ie),
            "can_handover": bool(can_handover),
            "can_im_issue_to_ie": bool(can_im_issue_to_ie),
            "can_disposition": bool(can_disposition),
            "can_repair_submit": bool(can_repair_submit),
            "can_pd_repair": bool(can_pd_repair),
            "can_confirm_discard": bool(can_confirm_discard),
            "has_reservation": False,
        }
        row["lifecycle"] = _lifecycle(row)
        row["needs_action"] = _row_needs_action(row)
        rows.append(row)

    rows.sort(
        key=lambda r: (
            0 if r.get("needs_action") else 1,
            (r.get("updated_at") is None),
            -(r["updated_at"].timestamp() if r.get("updated_at") else 0),
            (r.get("case_number") or ""),
        )
    )
    return rows
