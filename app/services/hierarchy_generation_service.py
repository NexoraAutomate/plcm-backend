"""
Spec 03 — generate Flight → SDLS → System…Component tree for APPROVED projects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.config.entities import ENTITY_CONFIG
from app.domain.hierarchy_config import HierarchyConfigLevel, normalize_inventory_source
from app.domain.status_transitions import assert_transition
from app.domain.workflow_roles import WorkflowRole, has_workflow_role
from app.domain.workflow_status import ProjectWorkflowStatus
from app.models.tables import (
    Component,
    Flight,
    HierarchyConfigNode,
    HierarchyConfiguration,
    Module,
    Project,
    Sdls,
    Subsystem,
    System,
    Unit,
    User,
)
from app.services.create_entity import New_entity
from app.services.project_workflow_service import (
    ProjectWorkflowError,
    get_project_status_id,
    project_status_name,
)
from app.services.update_entity import update_entity_status
from app.domain.workflow_audit import WorkflowAuditAction
from app.services.workflow_audit_service import write_workflow_audit

LEVEL_ORDER = {
    HierarchyConfigLevel.SYSTEM.value: 0,
    HierarchyConfigLevel.SUBSYSTEM.value: 1,
    HierarchyConfigLevel.MODULE.value: 2,
    HierarchyConfigLevel.UNIT.value: 3,
    HierarchyConfigLevel.COMPONENT.value: 4,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role_names(user: User) -> list[str]:
    return [r.name for r in (user.roles or [])]


def _actor_role(user: User) -> WorkflowRole:
    if has_workflow_role(_role_names(user), WorkflowRole.ADMIN):
        return WorkflowRole.ADMIN
    if has_workflow_role(_role_names(user), WorkflowRole.HM):
        return WorkflowRole.HM
    return WorkflowRole.HM  # permission decorator already gated hierarchy.generate


def _register_entity(session: Session, entity: Any, key: str, actor_id: int) -> None:
    display = ENTITY_CONFIG[key]["display_name"]
    New_entity(
        session=session,
        entity=entity,
        entity_name=display,
        changed_by_user=actor_id,
    )


def _sorted_template_nodes(
    nodes: list[HierarchyConfigNode],
) -> list[HierarchyConfigNode]:
    return sorted(
        nodes or [],
        key=lambda n: (
            LEVEL_ORDER.get(str(n.level).lower(), 99),
            int(n.sort_order or 0),
            int(n.id or 0),
        ),
    )


def _source_for_node(node: HierarchyConfigNode) -> str:
    try:
        return normalize_inventory_source(getattr(node, "inventory_source", None))
    except ValueError:
        from app.domain.hierarchy_config import InventorySource

        return InventorySource.TURNKEY.value


def _clone_template_under_sdls(
    session: Session,
    *,
    project: Project,
    sdls: Sdls,
    template_nodes: list[HierarchyConfigNode],
    actor_id: int,
    counts: dict[str, int],
) -> None:
    """Clone System→Component template once under a single SDLS."""
    # config node id → created entity id at that level
    created: dict[int, Any] = {}

    for node in template_nodes:
        level = str(node.level).strip().lower()
        name = str(node.name).strip()
        description = node.description

        if level == HierarchyConfigLevel.SYSTEM.value:
            entity = System(
                name=name,
                description=description,
                project_id=int(project.id),
                sdls_id=int(sdls.id),
                inventory_source=_source_for_node(node),
            )
            session.add(entity)
            session.flush()
            _register_entity(session, entity, "system", actor_id)
            created[int(node.id)] = entity
            counts["systems"] += 1
            continue

        if node.parent_id is None or int(node.parent_id) not in created:
            raise ProjectWorkflowError(
                f"Template node '{name}' ({level}) is missing a valid parent"
            )
        parent = created[int(node.parent_id)]

        if level == HierarchyConfigLevel.SUBSYSTEM.value:
            entity = Subsystem(
                name=name,
                description=description,
                system_id=int(parent.id),
                inventory_source=_source_for_node(node),
            )
            session.add(entity)
            session.flush()
            _register_entity(session, entity, "subsystem", actor_id)
            created[int(node.id)] = entity
            counts["subsystems"] += 1
        elif level == HierarchyConfigLevel.MODULE.value:
            entity = Module(
                name=name,
                description=description,
                subsystem_id=int(parent.id),
                inventory_source=_source_for_node(node),
            )
            session.add(entity)
            session.flush()
            _register_entity(session, entity, "module", actor_id)
            created[int(node.id)] = entity
            counts["modules"] += 1
        elif level == HierarchyConfigLevel.UNIT.value:
            entity = Unit(
                name=name,
                description=description,
                module_id=int(parent.id),
                inventory_source=_source_for_node(node),
            )
            session.add(entity)
            session.flush()
            _register_entity(session, entity, "unit", actor_id)
            created[int(node.id)] = entity
            counts["units"] += 1
        elif level == HierarchyConfigLevel.COMPONENT.value:
            entity = Component(
                name=name,
                description=description,
                unit_id=int(parent.id),
                inventory_source=_source_for_node(node),
            )
            session.add(entity)
            session.flush()
            _register_entity(session, entity, "component", actor_id)
            created[int(node.id)] = entity
            counts["components"] += 1
        else:
            raise ProjectWorkflowError(f"Unsupported template level: {level}")


def assert_can_generate_hierarchy(project: Project, session: Optional[Session] = None) -> None:
    """
    Spec 02/03 gate: only APPROVED projects that have not been generated yet.
    """
    status = project_status_name(project)
    if status in {
        ProjectWorkflowStatus.HIERARCHY_GENERATED.value,
        ProjectWorkflowStatus.READY_FOR_INVENTORY.value,
    }:
        raise ProjectWorkflowError(
            "Hierarchy has already been generated for this project"
        )
    if status != ProjectWorkflowStatus.APPROVED.value:
        raise ProjectWorkflowError(
            "Generate Hierarchy requires project status APPROVED "
            f"(current: {status or 'unknown'})"
        )
    if session is not None and project.id is not None:
        existing = session.exec(
            select(Flight).where(Flight.project_id == project.id).limit(1)
        ).first()
        if existing:
            raise ProjectWorkflowError(
                "Hierarchy has already been generated for this project"
            )


def generate_project_hierarchy(
    session: Session,
    project_id: int,
    *,
    actor: User,
) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if not project:
        raise ProjectWorkflowError("Project not found")

    assert_can_generate_hierarchy(project, session)
    if project.id is not None:
        from app.services.config_change_service import (
            ConfigChangeError,
            assert_no_open_config_change,
        )

        try:
            assert_no_open_config_change(
                session, int(project.id), action="hierarchy generation"
            )
        except ConfigChangeError as exc:
            raise ProjectWorkflowError(str(exc)) from exc

    if not project.hierarchy_config_id:
        raise ProjectWorkflowError(
            "Project has no hierarchy configuration; cannot generate"
        )
    if not project.flight_count or not project.sdls_per_flight:
        raise ProjectWorkflowError(
            "Project flight_count and sdls_per_flight are required"
        )

    config = session.get(HierarchyConfiguration, project.hierarchy_config_id)
    if not config:
        raise ProjectWorkflowError("Hierarchy configuration not found")

    template_nodes = _sorted_template_nodes(list(config.nodes or []))
    system_nodes = [
        n
        for n in template_nodes
        if str(n.level).lower() == HierarchyConfigLevel.SYSTEM.value
    ]
    if not system_nodes:
        raise ProjectWorkflowError(
            "Hierarchy configuration has no System-level template nodes"
        )

    flight_count = int(project.flight_count)
    sdls_per_flight = int(project.sdls_per_flight)
    product_type = project.product_type or ""
    actor_id = int(actor.id)
    role = _actor_role(actor)

    counts = {
        "flights": 0,
        "sdls": 0,
        "systems": 0,
        "subsystems": 0,
        "modules": 0,
        "units": 0,
        "components": 0,
    }

    for f_idx in range(1, flight_count + 1):
        flight = Flight(
            name=f"Flight-{f_idx}",
            code=f"F{f_idx:02d}",
            sequence=f_idx,
            project_id=int(project.id),
            description=f"Generated flight {f_idx} for {project.name}",
        )
        session.add(flight)
        session.flush()
        _register_entity(session, flight, "flight", actor_id)
        counts["flights"] += 1

        for s_idx in range(1, sdls_per_flight + 1):
            sdls_name = (
                f"{product_type}-{s_idx}" if product_type else f"SDLS-{s_idx}"
            )
            sdls = Sdls(
                name=sdls_name,
                code=f"F{f_idx:02d}-S{s_idx:02d}",
                sequence=s_idx,
                flight_id=int(flight.id),
                product_type=product_type or None,
                description=(
                    f"Generated SDLS {s_idx} under {flight.code} "
                    f"({product_type or 'product'})"
                ),
            )
            session.add(sdls)
            session.flush()
            _register_entity(session, sdls, "sdls", actor_id)
            counts["sdls"] += 1

            _clone_template_under_sdls(
                session,
                project=project,
                sdls=sdls,
                template_nodes=template_nodes,
                actor_id=actor_id,
                counts=counts,
            )

    # Status: APPROVED → HIERARCHY_GENERATED → READY_FOR_INVENTORY
    current = ProjectWorkflowStatus.APPROVED.value
    try:
        assert_transition(
            "project",
            current,
            ProjectWorkflowStatus.HIERARCHY_GENERATED.value,
            actor_role=role,
        )
        assert_transition(
            "project",
            ProjectWorkflowStatus.HIERARCHY_GENERATED.value,
            ProjectWorkflowStatus.READY_FOR_INVENTORY.value,
            actor_role=role,
        )
    except ValueError as exc:
        raise ProjectWorkflowError(str(exc)) from exc

    project.status_id = get_project_status_id(
        session, ProjectWorkflowStatus.READY_FOR_INVENTORY.value
    )
    project.updated_at = _now()
    session.add(project)
    session.flush()

    entity_config = ENTITY_CONFIG.get("project")
    update_entity_status(
        session=session,
        entity=project,
        entity_name=entity_config["display_name"],
        changed_by_user=actor_id,
    )
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.HIERARCHY_GENERATED,
        entity_type="project",
        entity_id=int(project.id),
        actor=actor,
        project_id=int(project.id),
        old_value={"status": ProjectWorkflowStatus.APPROVED.value},
        new_value={
            "status": ProjectWorkflowStatus.READY_FOR_INVENTORY.value,
            "counts": counts,
        },
    )
    session.commit()
    session.refresh(project)

    return {
        "ok": True,
        "project_id": int(project.id),
        "status": project_status_name(project)
        or ProjectWorkflowStatus.READY_FOR_INVENTORY.value,
        "config_code": config.code,
        "config_name": config.name,
        "product_type": product_type,
        "counts": counts,
    }
