"""
Spec 02 — project draft creation, HM assignment, and Admin/PD approval.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_
from sqlmodel import Session, select

from app.domain.status_transitions import assert_transition
from app.domain.workflow_roles import WorkflowRole, has_workflow_role, normalize_workflow_role
from app.domain.workflow_status import ProjectWorkflowStatus
from app.models.tables import HierarchyConfiguration, Project, Status, User
from app.services.create_entity import New_entity
from app.services.update_entity import update_entity_status
from app.config.entities import ENTITY_CONFIG
from app.domain.workflow_audit import WorkflowAuditAction
from app.services.workflow_audit_service import write_workflow_audit


class ProjectWorkflowError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role_names(user: User) -> list[str]:
    return [r.name for r in (user.roles or [])]


def _is_admin(user: User) -> bool:
    return has_workflow_role(_role_names(user), WorkflowRole.ADMIN)


def _actor_workflow_role(user: User) -> Optional[WorkflowRole]:
    names = _role_names(user)
    for role in (
        WorkflowRole.ADMIN,
        WorkflowRole.PD,
        WorkflowRole.HM,
        WorkflowRole.IM,
        WorkflowRole.DEV,
    ):
        if has_workflow_role(names, role):
            return role
    if names:
        return normalize_workflow_role(names[0])
    return None


def project_is_cancelled(project: Optional[Project]) -> bool:
    if project is None:
        return False
    return project_status_name(project) == ProjectWorkflowStatus.CANCELLED.value


def project_is_superseded(project: Optional[Project]) -> bool:
    if project is None:
        return False
    return project_status_name(project) == ProjectWorkflowStatus.SUPERSEDED.value


def assert_project_not_cancelled(
    project: Optional[Project], *, action: str = "inventory operations"
) -> None:
    if project_is_cancelled(project):
        raise ProjectWorkflowError(f"Cancelled projects block {action}")
    if project_is_superseded(project):
        raise ProjectWorkflowError(f"Superseded projects block {action}")


def project_for_hierarchy_entity(session: Session, entity: Any) -> Optional[Project]:
    """Walk a hierarchy row up to its project (system.project_id or ancestors)."""
    if entity is None:
        return None
    project_id = getattr(entity, "project_id", None)
    if project_id is not None:
        return session.get(Project, int(project_id))

    from app.models.tables import Module, Subsystem, System, Unit

    system_id = getattr(entity, "system_id", None)
    if system_id is not None:
        return project_for_hierarchy_entity(session, session.get(System, int(system_id)))

    subsystem_id = getattr(entity, "subsystem_id", None)
    if subsystem_id is not None:
        return project_for_hierarchy_entity(
            session, session.get(Subsystem, int(subsystem_id))
        )

    module_id = getattr(entity, "module_id", None)
    if module_id is not None:
        return project_for_hierarchy_entity(session, session.get(Module, int(module_id)))

    unit_id = getattr(entity, "unit_id", None)
    if unit_id is not None:
        return project_for_hierarchy_entity(session, session.get(Unit, int(unit_id)))

    return None


def assert_hierarchy_mutable(session: Session, entity: Any) -> None:
    assert_project_not_cancelled(
        project_for_hierarchy_entity(session, entity),
        action="hierarchy changes",
    )


def _unrestricted_project_viewer(user: User) -> bool:
    names = _role_names(user)
    return (
        has_workflow_role(names, WorkflowRole.ADMIN)
        or has_workflow_role(names, WorkflowRole.PD)
        or has_workflow_role(names, WorkflowRole.IM)
    )


def user_can_view_project(user: User, project: Project) -> bool:
    """HM sees only projects they own, created, or are assigned to."""
    if _unrestricted_project_viewer(user):
        return True
    if not has_workflow_role(_role_names(user), WorkflowRole.HM):
        return True
    uid = int(user.id)
    return uid in {
        project.owner_id,
        project.created_by_id,
        project.assigned_hm_id,
    }


def project_list_visibility_where(user: User) -> Any:
    if _unrestricted_project_viewer(user):
        return None
    if not has_workflow_role(_role_names(user), WorkflowRole.HM):
        return None
    uid = int(user.id)
    return or_(
        Project.owner_id == uid,
        Project.created_by_id == uid,
        Project.assigned_hm_id == uid,
    )


def get_project_status_id(session: Session, status_name: str) -> int:
    status = session.exec(
        select(Status).where(
            Status.status_name == status_name,
            Status.status_type == "projects",
        )
    ).first()
    if not status or status.id is None:
        raise ProjectWorkflowError(
            f"Required project status '{status_name}' is not seeded"
        )
    return int(status.id)


def project_status_name(project: Project) -> Optional[str]:
    if project.status and project.status.status_name:
        return project.status.status_name
    return None


def _require_available_config(
    session: Session, config_id: int, product_type: str
) -> HierarchyConfiguration:
    config = session.get(HierarchyConfiguration, config_id)
    if not config:
        raise ProjectWorkflowError("Hierarchy configuration not found")
    if not config.is_available:
        raise ProjectWorkflowError(
            "Hierarchy configuration is not available for selection"
        )
    codes = {pt.code for pt in (config.product_types or [])}
    if product_type not in codes:
        raise ProjectWorkflowError(
            f"Product type '{product_type}' is not defined on the selected configuration"
        )
    return config


def create_draft_project(
    session: Session,
    payload: dict[str, Any],
    *,
    actor: User,
    commit: bool = True,
) -> Project:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ProjectWorkflowError("name is required")

    config_id = payload.get("hierarchy_config_id")
    if not config_id:
        raise ProjectWorkflowError("hierarchy_config_id is required")

    product_type = str(payload.get("product_type") or "").strip()
    if not product_type:
        raise ProjectWorkflowError("product_type is required")

    try:
        flight_count = int(payload.get("flight_count"))
    except (TypeError, ValueError) as exc:
        raise ProjectWorkflowError(
            "flight_count must be a positive integer"
        ) from exc
    if flight_count < 1:
        raise ProjectWorkflowError("flight_count must be >= 1")

    raw_sdls_counts = payload.get("sdls_counts_by_flight")
    if raw_sdls_counts is None:
        try:
            legacy_sdls_per_flight = int(payload.get("sdls_per_flight"))
        except (TypeError, ValueError) as exc:
            raise ProjectWorkflowError(
                "sdls_per_flight or sdls_counts_by_flight is required"
            ) from exc
        sdls_counts_by_flight = [legacy_sdls_per_flight] * flight_count
    elif isinstance(raw_sdls_counts, (list, tuple)):
        try:
            sdls_counts_by_flight = [int(count) for count in raw_sdls_counts]
        except (TypeError, ValueError) as exc:
            raise ProjectWorkflowError(
                "sdls_counts_by_flight must contain positive integers"
            ) from exc
    else:
        raise ProjectWorkflowError("sdls_counts_by_flight must be a list")

    if len(sdls_counts_by_flight) != flight_count:
        raise ProjectWorkflowError(
            "sdls_counts_by_flight must contain one value for each flight"
        )
    if any(count < 1 for count in sdls_counts_by_flight):
        raise ProjectWorkflowError(
            "sdls_counts_by_flight values must be >= 1"
        )
    # Retain the legacy scalar as the maximum count for older consumers.
    sdls_per_flight = max(sdls_counts_by_flight)

    config = _require_available_config(session, int(config_id), product_type)
    draft_status_id = get_project_status_id(
        session, ProjectWorkflowStatus.DRAFT.value
    )

    assigned_hm_id = payload.get("assigned_hm_id")
    if assigned_hm_id is None:
        assigned_hm_id = actor.id
    else:
        assigned_hm_id = int(assigned_hm_id)
        hm_user = session.get(User, assigned_hm_id)
        if not hm_user:
            raise ProjectWorkflowError("assigned_hm_id user not found")

    owner_id = int(payload.get("owner_id") or assigned_hm_id)
    start_date = payload.get("start_date") or _now()
    order_id = payload.get("order_id")
    if order_id in (0, "", None):
        order_id = None
    else:
        order_id = int(order_id)

    project = Project(
        name=name,
        description=payload.get("description"),
        start_date=start_date,
        end_date=payload.get("end_date"),
        owner_id=owner_id,
        order_id=order_id,
        status_id=draft_status_id,
        progress=0,
        hierarchy_config_id=config.id,
        hierarchy_config_version=int(config.version or 1),
        product_type=product_type,
        flight_count=flight_count,
        sdls_per_flight=sdls_per_flight,
        sdls_counts_by_flight=sdls_counts_by_flight,
        assigned_hm_id=assigned_hm_id,
        created_by_id=actor.id,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(project)
    session.flush()

    entity_config = ENTITY_CONFIG.get("project")
    New_entity(
        session=session,
        entity=project,
        entity_name=entity_config["display_name"],
        changed_by_user=actor.id,
    )
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.PROJECT_CREATED,
        entity_type="project",
        entity_id=int(project.id),
        actor=actor,
        project_id=int(project.id),
        new_value={
            "name": project.name,
            "status": ProjectWorkflowStatus.DRAFT.value,
            "hierarchy_config_id": project.hierarchy_config_id,
            "product_type": project.product_type,
        },
    )
    if commit:
        session.commit()
        session.refresh(project)
    return project


def create_draft_projects_by_flight(
    session: Session,
    payload: dict[str, Any],
    *,
    actor: User,
) -> list[Project]:
    """Create one draft project for each requested flight.

    The whole operation shares one database transaction. Each resulting
    project owns exactly one flight, while its name retains the original
    project name and the source flight number.
    """
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ProjectWorkflowError("name is required")

    try:
        flight_count = int(payload.get("flight_count"))
    except (TypeError, ValueError) as exc:
        raise ProjectWorkflowError(
            "flight_count must be a positive integer"
        ) from exc
    if flight_count < 1:
        raise ProjectWorkflowError("flight_count must be >= 1")

    raw_sdls_counts = payload.get("sdls_counts_by_flight")
    if raw_sdls_counts is None:
        try:
            legacy_sdls_per_flight = int(payload.get("sdls_per_flight"))
        except (TypeError, ValueError) as exc:
            raise ProjectWorkflowError(
                "sdls_per_flight or sdls_counts_by_flight is required"
            ) from exc
        sdls_counts_by_flight = [legacy_sdls_per_flight] * flight_count
    elif isinstance(raw_sdls_counts, (list, tuple)):
        try:
            sdls_counts_by_flight = [int(count) for count in raw_sdls_counts]
        except (TypeError, ValueError) as exc:
            raise ProjectWorkflowError(
                "sdls_counts_by_flight must contain positive integers"
            ) from exc
    else:
        raise ProjectWorkflowError("sdls_counts_by_flight must be a list")

    if len(sdls_counts_by_flight) != flight_count:
        raise ProjectWorkflowError(
            "sdls_counts_by_flight must contain one value for each flight"
        )
    if any(count < 1 for count in sdls_counts_by_flight):
        raise ProjectWorkflowError("sdls_counts_by_flight values must be >= 1")

    projects: list[Project] = []
    try:
        for flight_number, sdls_count in enumerate(sdls_counts_by_flight, start=1):
            flight_payload = {
                **payload,
                "name": f"{name} - Flight {flight_number}",
                "flight_count": 1,
                "sdls_per_flight": sdls_count,
                "sdls_counts_by_flight": [sdls_count],
            }
            projects.append(
                create_draft_project(
                    session,
                    flight_payload,
                    actor=actor,
                    commit=False,
                )
            )

        session.commit()
        for project in projects:
            session.refresh(project)
        return projects
    except Exception:
        session.rollback()
        raise


def assign_hm(
    session: Session,
    project_id: int,
    hm_user_id: int,
    *,
    actor: User,
) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise ProjectWorkflowError("Project not found")

    hm_user = session.get(User, hm_user_id)
    if not hm_user:
        raise ProjectWorkflowError("HM user not found")

    assert_project_not_cancelled(project, action="hierarchy changes")

    # Prefer HM role when present; still allow assignment for Spec 02 flexibility
    role_names = _role_names(hm_user)
    if role_names and not (
        has_workflow_role(role_names, WorkflowRole.HM)
        or has_workflow_role(role_names, WorkflowRole.ADMIN)
        or any(n.lower() in ("projectmanager", "hierarchymanager") for n in role_names)
    ):
        raise ProjectWorkflowError(
            "Assigned user must have Hierarchy Manager (or Admin) role"
        )

    previous_hm_id = project.assigned_hm_id
    project.assigned_hm_id = hm_user_id
    project.owner_id = hm_user_id
    project.updated_at = _now()
    session.add(project)
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.HM_ASSIGNED,
        entity_type="project",
        entity_id=int(project.id),
        actor=actor,
        project_id=int(project.id),
        old_value={"assigned_hm_id": previous_hm_id},
        new_value={
            "assigned_hm_id": int(hm_user_id),
            "assigned_hm_name": hm_user.full_name or hm_user.username,
        },
    )
    session.commit()
    session.refresh(project)
    return project


def _can_approve_project(user: User) -> bool:
    names = _role_names(user)
    return has_workflow_role(names, WorkflowRole.ADMIN) or has_workflow_role(
        names, WorkflowRole.PD
    )


def approve_project(
    session: Session,
    project_id: int,
    *,
    actor: User,
) -> Project:
    if not _can_approve_project(actor):
        # Permission decorator also gates; keep domain guard for tests
        raise ProjectWorkflowError("Only Admin or Project Director can approve projects")

    project = session.get(Project, project_id)
    if not project:
        raise ProjectWorkflowError("Project not found")

    current = project_status_name(project) or ProjectWorkflowStatus.DRAFT.value
    try:
        assert_transition(
            "project",
            current,
            ProjectWorkflowStatus.APPROVED.value,
            actor_role=_actor_workflow_role(actor) or WorkflowRole.ADMIN,
        )
    except ValueError as exc:
        raise ProjectWorkflowError(str(exc)) from exc

    if not project.hierarchy_config_id:
        raise ProjectWorkflowError(
            "Cannot approve a project without a hierarchy configuration"
        )
    if not project.product_type or not project.flight_count or not project.sdls_per_flight:
        raise ProjectWorkflowError(
            "Cannot approve a project with incomplete product scope"
        )

    # Freeze config version at approval
    if project.hierarchy_config_id:
        config = session.get(HierarchyConfiguration, project.hierarchy_config_id)
        if config:
            project.hierarchy_config_version = int(config.version or 1)

    project.status_id = get_project_status_id(
        session, ProjectWorkflowStatus.APPROVED.value
    )
    project.approved_by_id = actor.id
    project.approved_at = _now()
    project.updated_at = _now()
    session.add(project)
    session.flush()

    entity_config = ENTITY_CONFIG.get("project")
    update_entity_status(
        session=session,
        entity=project,
        entity_name=entity_config["display_name"],
        changed_by_user=actor.id,
    )
    write_workflow_audit(
        session,
        action=WorkflowAuditAction.PROJECT_APPROVED,
        entity_type="project",
        entity_id=int(project.id),
        actor=actor,
        project_id=int(project.id),
        old_value={"status": current},
        new_value={"status": ProjectWorkflowStatus.APPROVED.value},
    )
    session.commit()
    session.refresh(project)
    return project


def assert_can_generate_hierarchy(project: Project, session=None) -> None:
    """Spec 02/03 gate — delegated to hierarchy generation service."""
    from app.services.hierarchy_generation_service import (
        assert_can_generate_hierarchy as _assert,
    )

    _assert(project, session)


def is_structural_frozen(project: Project) -> bool:
    status = project_status_name(project)
    return status in {
        ProjectWorkflowStatus.APPROVED.value,
        ProjectWorkflowStatus.HIERARCHY_GENERATED.value,
        ProjectWorkflowStatus.READY_FOR_INVENTORY.value,
        ProjectWorkflowStatus.COMPLETED.value,
        ProjectWorkflowStatus.READY_TO_DELIVER.value,
        ProjectWorkflowStatus.CANCELLED.value,
        ProjectWorkflowStatus.SUPERSEDED.value,
    }


STRUCTURAL_FIELDS = frozenset(
    {
        "hierarchy_config_id",
        "hierarchy_config_version",
        "product_type",
        "flight_count",
        "sdls_per_flight",
        "sdls_counts_by_flight",
    }
)


def guard_structural_update(project: Project, update_data: dict[str, Any]) -> None:
    """After approval, freeze config + core counts unless Admin reopens (not Spec 02)."""
    if not is_structural_frozen(project):
        return
    touched = STRUCTURAL_FIELDS.intersection(update_data.keys())
    if touched:
        raise ProjectWorkflowError(
            "Structural fields are frozen after approval: "
            + ", ".join(sorted(touched))
        )
