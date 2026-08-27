"""Spec 09 — compute weighted project progress and apply the completion gate."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, col, select

from app.domain.project_progress import (
    NOT_STARTED_STATUS,
    STAGE_POLICY,
    ProgressNode,
    collect_bottlenecks,
    progress_pct,
    rollup_progress,
)
from app.domain.status_transitions import assert_transition
from app.domain.workflow_status import ItemStatus, ProjectWorkflowStatus
from app.models.base import InventoryReservationStatus, ReworkCaseStatus
from app.models.tables import (
    AssembledInventory,
    Component,
    Flight,
    InventoryInstance,
    InventoryIssuance,
    InventoryReservation,
    InventoryReworkCase,
    Module,
    Project,
    Sdls,
    Status,
    Subsystem,
    System,
    Unit,
)
from app.services.hierarchy_developer_service import PHYSICAL_ISSUE_STATUSES
from app.services.inventory_reservation_service import item_status_name
from app.services.project_workflow_service import (
    ProjectWorkflowError,
    get_project_status_id,
    project_status_name,
)

Coverage = dict[tuple[str, int], dict[str, Any]]


class ProjectProgressError(ValueError):
    pass


def _issuance_lifecycle_status(session: Session, issuance: InventoryIssuance) -> str:
    if issuance.inventory_instance_id:
        instance = session.get(InventoryInstance, issuance.inventory_instance_id)
        if instance is not None:
            name = item_status_name(session, instance.status_id)
            if name:
                return name.strip().upper()
    return (issuance.item_lifecycle_status or ItemStatus.ISSUED.value).strip().upper()


def _load_coverage(session: Session, project_id: int) -> Coverage:
    coverage: Coverage = {}
    issuances = session.exec(
        select(InventoryIssuance)
        .where(
            InventoryIssuance.project_id == project_id,
            InventoryIssuance.status.in_(PHYSICAL_ISSUE_STATUSES),
        )
        .order_by(col(InventoryIssuance.issued_at).desc())
    ).all()
    for issuance in issuances:
        et = (issuance.target_entity_type or "").strip().lower()
        eid = issuance.target_entity_id
        if not et or eid is None:
            continue
        key = (et, int(eid))
        if key in coverage:
            continue
        coverage[key] = {
            "status": _issuance_lifecycle_status(session, issuance),
            "defect_pending": bool(issuance.defect_pending),
        }

    reworks = session.exec(
        select(InventoryReworkCase).where(
            InventoryReworkCase.project_id == project_id,
            InventoryReworkCase.status == ReworkCaseStatus.OPEN.value,
        )
    ).all()
    for case in reworks:
        et = (case.target_entity_type or "").strip().lower()
        eid = case.target_entity_id
        if not et or eid is None:
            continue
        key = (et, int(eid))
        item_status = None
        if case.current_instance_id:
            instance = session.get(InventoryInstance, case.current_instance_id)
            if instance is not None:
                item_status = item_status_name(session, instance.status_id)
        if key in coverage:
            coverage[key]["defect_pending"] = True
            if item_status:
                coverage[key]["status"] = item_status.strip().upper()
            continue
        coverage[key] = {
            "status": (item_status or ItemStatus.UNDER_TESTING_REVIEW.value).strip().upper(),
            "defect_pending": True,
        }

    reservations = session.exec(
        select(InventoryReservation).where(
            InventoryReservation.project_id == project_id,
            InventoryReservation.status == InventoryReservationStatus.ACTIVE.value,
        )
    ).all()
    for reservation in reservations:
        et = (reservation.target_entity_type or "").strip().lower()
        key = (et, int(reservation.target_entity_id))
        if key in coverage:
            continue
        coverage[key] = {
            "status": ItemStatus.RESERVED.value,
            "defect_pending": False,
        }

    assembled_rows = session.exec(
        select(AssembledInventory).where(
            AssembledInventory.project_id == project_id
        )
    ).all()
    for assembled in assembled_rows:
        et = (assembled.target_entity_type or "").strip().lower()
        if not et or assembled.target_entity_id is None:
            continue
        key = (et, int(assembled.target_entity_id))
        coverage[key] = {
            "status": ItemStatus.INSTALLED_VERIFIED.value,
            "defect_pending": False,
        }
    return coverage


def _apply_coverage(
    node: ProgressNode,
    coverage: Coverage,
    inherited: Optional[dict[str, Any]] = None,
) -> None:
    own = coverage.get((node.entity_type, node.entity_id))
    if own is not None:
        node.status = own["status"]
        node.defect_pending = bool(own["defect_pending"])
        node.cover_entity_type = node.entity_type
        node.cover_entity_id = node.entity_id
        node.cover_name = node.name
        passed = {
            "status": node.status,
            "defect_pending": node.defect_pending,
            "cover_entity_type": node.cover_entity_type,
            "cover_entity_id": node.cover_entity_id,
            "cover_name": node.cover_name,
        }
    elif inherited is not None:
        node.status = inherited["status"]
        node.defect_pending = bool(inherited["defect_pending"])
        node.cover_entity_type = inherited["cover_entity_type"]
        node.cover_entity_id = inherited["cover_entity_id"]
        node.cover_name = inherited["cover_name"]
        passed = inherited
    else:
        node.status = NOT_STARTED_STATUS
        node.defect_pending = False
        passed = None
    for child in node.children:
        _apply_coverage(child, coverage, passed)


def _index_by(fk: str, rows: list[Any]) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = {}
    for row in rows:
        parent_id = getattr(row, fk)
        if parent_id is None:
            continue
        grouped.setdefault(int(parent_id), []).append(row)
    return grouped


def _build_hardware_tree(
    system: System,
    subsystems_by_system: dict[int, list[Subsystem]],
    modules_by_subsystem: dict[int, list[Module]],
    units_by_module: dict[int, list[Unit]],
    components_by_unit: dict[int, list[Component]],
) -> ProgressNode:
    subsystem_nodes: list[ProgressNode] = []
    for subsystem in subsystems_by_system.get(int(system.id), []):
        module_nodes: list[ProgressNode] = []
        for module in modules_by_subsystem.get(int(subsystem.id), []):
            unit_nodes: list[ProgressNode] = []
            for unit in units_by_module.get(int(module.id), []):
                component_nodes = [
                    ProgressNode(
                        entity_type="component",
                        entity_id=int(component.id),
                        name=component.name,
                    )
                    for component in components_by_unit.get(int(unit.id), [])
                ]
                unit_nodes.append(
                    ProgressNode(
                        entity_type="unit",
                        entity_id=int(unit.id),
                        name=unit.name,
                        children=component_nodes,
                    )
                )
            module_nodes.append(
                ProgressNode(
                    entity_type="module",
                    entity_id=int(module.id),
                    name=module.name,
                    children=unit_nodes,
                )
            )
        subsystem_nodes.append(
            ProgressNode(
                entity_type="subsystem",
                entity_id=int(subsystem.id),
                name=subsystem.name,
                children=module_nodes,
            )
        )
    return ProgressNode(
        entity_type="system",
        entity_id=int(system.id),
        name=system.name,
        children=subsystem_nodes,
    )


def _load_progress_tree(session: Session, project: Project) -> ProgressNode:
    project_id = int(project.id)
    flights = session.exec(
        select(Flight)
        .where(Flight.project_id == project_id)
        .order_by(Flight.sequence, Flight.id)
    ).all()
    flight_ids = [int(row.id) for row in flights if row.id is not None]
    sdls_rows = (
        session.exec(
            select(Sdls)
            .where(col(Sdls.flight_id).in_(flight_ids))
            .order_by(Sdls.sequence, Sdls.id)
        ).all()
        if flight_ids
        else []
    )
    sdls_by_flight = _index_by("flight_id", sdls_rows)

    systems = session.exec(
        select(System).where(System.project_id == project_id).order_by(System.id)
    ).all()
    system_ids = [int(row.id) for row in systems if row.id is not None]
    subsystems = (
        session.exec(
            select(Subsystem)
            .where(col(Subsystem.system_id).in_(system_ids))
            .order_by(Subsystem.id)
        ).all()
        if system_ids
        else []
    )
    subsystem_ids = [int(row.id) for row in subsystems if row.id is not None]
    modules = (
        session.exec(
            select(Module)
            .where(col(Module.subsystem_id).in_(subsystem_ids))
            .order_by(Module.id)
        ).all()
        if subsystem_ids
        else []
    )
    module_ids = [int(row.id) for row in modules if row.id is not None]
    units = (
        session.exec(
            select(Unit).where(col(Unit.module_id).in_(module_ids)).order_by(Unit.id)
        ).all()
        if module_ids
        else []
    )
    unit_ids = [int(row.id) for row in units if row.id is not None]
    components = (
        session.exec(
            select(Component)
            .where(col(Component.unit_id).in_(unit_ids))
            .order_by(Component.id)
        ).all()
        if unit_ids
        else []
    )

    subsystems_by_system = _index_by("system_id", subsystems)
    modules_by_subsystem = _index_by("subsystem_id", modules)
    units_by_module = _index_by("module_id", units)
    components_by_unit = _index_by("unit_id", components)

    systems_by_sdls: dict[int, list[System]] = {}
    orphan_systems: list[System] = []
    for system in systems:
        if system.sdls_id is None:
            orphan_systems.append(system)
        else:
            systems_by_sdls.setdefault(int(system.sdls_id), []).append(system)

    flight_nodes: list[ProgressNode] = []
    for flight in flights:
        sdls_nodes: list[ProgressNode] = []
        for sdls in sdls_by_flight.get(int(flight.id), []):
            system_nodes = [
                _build_hardware_tree(
                    system,
                    subsystems_by_system,
                    modules_by_subsystem,
                    units_by_module,
                    components_by_unit,
                )
                for system in systems_by_sdls.get(int(sdls.id), [])
            ]
            sdls_nodes.append(
                ProgressNode(
                    entity_type="sdls",
                    entity_id=int(sdls.id),
                    name=sdls.name,
                    code=sdls.code,
                    product_type=sdls.product_type,
                    children=system_nodes,
                )
            )
        flight_nodes.append(
            ProgressNode(
                entity_type="flight",
                entity_id=int(flight.id),
                name=flight.name,
                code=flight.code,
                children=sdls_nodes,
            )
        )

    if orphan_systems:
        flight_nodes.append(
            ProgressNode(
                entity_type="flight",
                entity_id=0,
                name="Unassigned",
                children=[
                    ProgressNode(
                        entity_type="sdls",
                        entity_id=0,
                        name="Unassigned",
                        children=[
                            _build_hardware_tree(
                                system,
                                subsystems_by_system,
                                modules_by_subsystem,
                                units_by_module,
                                components_by_unit,
                            )
                            for system in orphan_systems
                        ],
                    )
                ],
            )
        )

    return ProgressNode(
        entity_type="project",
        entity_id=project_id,
        name=project.name,
        children=flight_nodes,
    )


def _system_payload(node: ProgressNode) -> dict[str, Any]:
    return {
        "entity_type": node.entity_type,
        "entity_id": node.entity_id,
        "name": node.name,
        "weight": node.weight,
        "progress_pct": progress_pct(node.progress),
        "verified_leaves": node.verified_leaves,
        "status": None if node.status == NOT_STARTED_STATUS else node.status,
    }


def _to_payload(project: Project, root: ProgressNode) -> dict[str, Any]:
    flights: list[dict[str, Any]] = []
    for flight in root.children:
        sdls_payload: list[dict[str, Any]] = []
        for sdls in flight.children:
            sdls_payload.append(
                {
                    "entity_type": sdls.entity_type,
                    "entity_id": sdls.entity_id,
                    "name": sdls.name,
                    "code": sdls.code,
                    "product_type": sdls.product_type,
                    "weight": sdls.weight,
                    "progress_pct": progress_pct(sdls.progress),
                    "verified_leaves": sdls.verified_leaves,
                    "systems": [_system_payload(system) for system in sdls.children],
                }
            )
        flights.append(
            {
                "entity_type": flight.entity_type,
                "entity_id": flight.entity_id,
                "name": flight.name,
                "code": flight.code,
                "weight": flight.weight,
                "progress_pct": progress_pct(flight.progress),
                "verified_leaves": flight.verified_leaves,
                "sdls": sdls_payload,
            }
        )
    return {
        "project_id": int(project.id),
        "project_status": project_status_name(project),
        "progress_pct": progress_pct(root.progress),
        "weight": root.weight,
        "verified_leaves": root.verified_leaves,
        "can_complete": root.weight > 0 and root.verified_leaves == root.weight,
        "stage_policy": STAGE_POLICY,
        "flights": flights,
        "bottlenecks": collect_bottlenecks(root),
    }


def compute_project_progress(session: Session, project_id: int) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectProgressError("Project not found")
    root = _load_progress_tree(session, project)
    coverage = _load_coverage(session, int(project.id))
    _apply_coverage(root, coverage)
    rollup_progress(root)
    return _to_payload(project, root)


def _apply_completion_gate(
    session: Session, project: Project, snapshot: dict[str, Any]
) -> None:
    current = project_status_name(project)
    if current in {
        ProjectWorkflowStatus.CANCELLED.value,
        ProjectWorkflowStatus.READY_TO_DELIVER.value,
    }:
        return
    if not snapshot["can_complete"]:
        return
    if current == ProjectWorkflowStatus.COMPLETED.value:
        return
    if current != ProjectWorkflowStatus.READY_FOR_INVENTORY.value:
        return
    try:
        assert_transition(
            "project",
            current,
            ProjectWorkflowStatus.COMPLETED.value,
            actor_role="System",
        )
    except ValueError as exc:
        raise ProjectProgressError(str(exc)) from exc
    project.status_id = get_project_status_id(
        session, ProjectWorkflowStatus.COMPLETED.value
    )
    session.add(project)
    snapshot["project_status"] = ProjectWorkflowStatus.COMPLETED.value


def sync_project_progress(session: Session, project_id: int) -> dict[str, Any]:
    """Recompute, persist Project.progress, and complete when the gate is met.

    Does not commit — callers own the transaction.
    """
    snapshot = compute_project_progress(session, project_id)
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectProgressError("Project not found")
    project.progress = int(snapshot["progress_pct"])
    session.add(project)
    try:
        _apply_completion_gate(session, project, snapshot)
    except ProjectWorkflowError as exc:
        raise ProjectProgressError(str(exc)) from exc
    snapshot["progress_pct"] = int(project.progress or 0)
    return snapshot


def touch_project_progress(
    session: Session, project_id: Optional[int]
) -> Optional[dict[str, Any]]:
    if project_id is None:
        return None
    return sync_project_progress(session, int(project_id))


def assert_completion_allowed(session: Session, project: Project) -> None:
    snapshot = compute_project_progress(session, int(project.id))
    if snapshot["can_complete"]:
        return
    raise ProjectProgressError(
        "Project cannot be marked complete while required items are unverified"
    )


def status_is_completion_target(session: Session, status_id: Optional[int]) -> bool:
    if status_id is None:
        return False
    status = session.get(Status, status_id)
    name = (status.status_name if status else "") or ""
    return name in {
        ProjectWorkflowStatus.COMPLETED.value,
        ProjectWorkflowStatus.READY_TO_DELIVER.value,
        "Completed",
    }
