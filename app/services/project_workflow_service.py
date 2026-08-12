"""
Spec 02 — project draft creation, HM assignment, and Admin approval.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.domain.status_transitions import assert_transition
from app.domain.workflow_roles import WorkflowRole, has_workflow_role, normalize_workflow_role
from app.domain.workflow_status import ProjectWorkflowStatus
from app.models.tables import HierarchyConfiguration, Project, Status, User
from app.services.create_entity import New_entity
from app.services.update_entity import update_entity_status
from app.config.entities import ENTITY_CONFIG


class ProjectWorkflowError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _role_names(user: User) -> list[str]:
    return [r.name for r in (user.roles or [])]


def _is_admin(user: User) -> bool:
    return has_workflow_role(_role_names(user), WorkflowRole.ADMIN)


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
        sdls_per_flight = int(payload.get("sdls_per_flight"))
    except (TypeError, ValueError) as exc:
        raise ProjectWorkflowError(
            "flight_count and sdls_per_flight must be positive integers"
        ) from exc
    if flight_count < 1 or sdls_per_flight < 1:
        raise ProjectWorkflowError(
            "flight_count and sdls_per_flight must be >= 1"
        )

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
    session.commit()
    session.refresh(project)
    return project


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

    project.assigned_hm_id = hm_user_id
    project.owner_id = hm_user_id
    project.updated_at = _now()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def approve_project(
    session: Session,
    project_id: int,
    *,
    actor: User,
) -> Project:
    if not _is_admin(actor):
        # Permission decorator also gates; keep domain guard for tests
        raise ProjectWorkflowError("Only Admin can approve projects")

    project = session.get(Project, project_id)
    if not project:
        raise ProjectWorkflowError("Project not found")

    current = project_status_name(project) or ProjectWorkflowStatus.DRAFT.value
    try:
        assert_transition(
            "project",
            current,
            ProjectWorkflowStatus.APPROVED.value,
            actor_role=WorkflowRole.ADMIN,
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
    session.commit()
    session.refresh(project)
    return project


def assert_can_generate_hierarchy(project: Project) -> None:
    """
    Spec 02 guard: generation blocked for DRAFT.
    Spec 03 will implement generation for APPROVED projects.
    """
    status = project_status_name(project)
    if status != ProjectWorkflowStatus.APPROVED.value:
        raise ProjectWorkflowError(
            "Generate Hierarchy requires project status APPROVED "
            f"(current: {status or 'unknown'})"
        )
    # Spec 03 not implemented yet
    raise ProjectWorkflowError(
        "Generate Hierarchy is not available until Spec 03 is implemented"
    )


def is_structural_frozen(project: Project) -> bool:
    status = project_status_name(project)
    return status in {
        ProjectWorkflowStatus.APPROVED.value,
        ProjectWorkflowStatus.HIERARCHY_GENERATED.value,
        ProjectWorkflowStatus.READY_FOR_INVENTORY.value,
        ProjectWorkflowStatus.COMPLETED.value,
        ProjectWorkflowStatus.READY_TO_DELIVER.value,
    }


STRUCTURAL_FIELDS = frozenset(
    {
        "hierarchy_config_id",
        "hierarchy_config_version",
        "product_type",
        "flight_count",
        "sdls_per_flight",
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
