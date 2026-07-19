from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.models.base import CaseStatus
from app.models.tables import (
    Component,
    ConfigurationHistory,
    Customer,
    Entity,
    EntityAttachment,
    EntityStatusHistory,
    FaultyEntity,
    Inventory,
    MaintenanceAction,
    MaintenanceCase,
    MaintenanceDelivery,
    Module,
    Order,
    Project,
    ReportHistory,
    Status,
    Subsystem,
    System,
    Unit,
    User,
)
from app.schemas.reports import (
    AttachmentItem,
    BuildHistoryDossierResponse,
    ConfigHistoryItem,
    ExecutiveReportResponse,
    FaultyEntityItem,
    HierarchyEntityNode,
    ImageItem,
    InventoryReportItem,
    InventoryReportResponse,
    MaintenanceActionItem,
    MaintenanceDeliveryItem,
    MaintenanceHistoryDossierResponse,
    MaintenanceSummaryResponse,
    ReportHistoryItem,
    ReportHistoryListResponse,
    ReportRegisterRequest,
    ReportRegisterResponse,
    ReportVerifyResponse,
    TimelineEvent,
)
from app.services.dashboard_service import DashboardFilters, build_executive_dashboard


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> datetime:
    """Normalize naive/aware datetimes for safe comparison/sorting."""
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _user_name(user: Optional[User]) -> Optional[str]:
    if not user:
        return None
    return user.full_name or user.username


def _status_name(status: Optional[Status]) -> Optional[str]:
    return status.status_name if status else None


def register_report(
    session: Session,
    payload: ReportRegisterRequest,
    current_user: User,
) -> ReportRegisterResponse:
    report_uuid = str(payload.report_uuid or uuid4())
    filters_json = json.dumps(payload.filters) if payload.filters is not None else None
    row = ReportHistory(
        report_uuid=report_uuid,
        report_type=payload.report_type.value if hasattr(payload.report_type, "value") else str(payload.report_type),
        report_title=payload.report_title,
        generated_by=current_user.id,
        generated_at=_now(),
        filters_json=filters_json,
        file_name=payload.file_name,
        checksum=payload.checksum,
        software_version=payload.software_version or "0.1.0",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return ReportRegisterResponse(
        id=row.id,
        report_uuid=row.report_uuid,
        report_type=row.report_type,
        report_title=row.report_title,
        generated_by=row.generated_by,
        generated_by_name=_user_name(current_user),
        generated_at=row.generated_at,
        filters_json=row.filters_json,
        file_name=row.file_name,
        checksum=row.checksum,
        software_version=row.software_version,
        verify_payload=row.report_uuid,
    )


def verify_report(session: Session, report_uuid: str) -> ReportVerifyResponse:
    row = session.exec(
        select(ReportHistory).where(ReportHistory.report_uuid == report_uuid)
    ).first()
    if not row:
        return ReportVerifyResponse(
            valid=False,
            report_uuid=report_uuid,
            message="Report not found",
        )
    user = session.get(User, row.generated_by) if row.generated_by else None
    return ReportVerifyResponse(
        valid=True,
        report_uuid=row.report_uuid,
        report_type=row.report_type,
        report_title=row.report_title,
        generated_by=row.generated_by,
        generated_by_name=_user_name(user),
        generated_at=row.generated_at,
        filters_json=row.filters_json,
        file_name=row.file_name,
        checksum=row.checksum,
        software_version=row.software_version,
        message="Report verified",
    )


def list_report_history(
    session: Session,
    page: int = 1,
    page_size: int = 20,
    report_type: Optional[str] = None,
) -> ReportHistoryListResponse:
    count_stmt = select(func.count(ReportHistory.id))
    stmt = select(ReportHistory)
    if report_type:
        count_stmt = count_stmt.where(ReportHistory.report_type == report_type)
        stmt = stmt.where(ReportHistory.report_type == report_type)
    total = session.exec(count_stmt).one()
    rows = session.exec(
        stmt.order_by(ReportHistory.generated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items: List[ReportHistoryItem] = []
    for row in rows:
        user = session.get(User, row.generated_by) if row.generated_by else None
        items.append(
            ReportHistoryItem(
                id=row.id,
                report_uuid=row.report_uuid,
                report_type=row.report_type,
                report_title=row.report_title,
                generated_by=row.generated_by,
                generated_by_name=_user_name(user),
                generated_at=row.generated_at,
                file_name=row.file_name,
                checksum=row.checksum,
                software_version=row.software_version,
            )
        )
    return ReportHistoryListResponse(
        items=items, total=total or 0, page=page, page_size=page_size
    )


def _entity_tracker(
    session: Session, entity_type: str, entity_pk: int
) -> Optional[Entity]:
    return session.exec(
        select(Entity).where(
            Entity.entity_type == entity_type,
            Entity.entity_pk == entity_pk,
        )
    ).first()


def _previous_status(
    session: Session, entity: Optional[Entity]
) -> Tuple[Optional[str], Optional[datetime]]:
    if not entity:
        return None, None
    history = session.exec(
        select(EntityStatusHistory)
        .where(EntityStatusHistory.entity_id == entity.id)
        .order_by(EntityStatusHistory.changed_at.desc())
    ).all()
    if len(history) < 2:
        return None, history[0].changed_at if history else None
    prev = history[1]
    status = session.get(Status, prev.status_id)
    return _status_name(status), prev.changed_at


def _node_from_hw(
    session: Session,
    entity_type: str,
    row: Any,
    children: Optional[List[HierarchyEntityNode]] = None,
) -> HierarchyEntityNode:
    tracker = _entity_tracker(session, entity_type, row.id)
    prev_status, modified = _previous_status(session, tracker)
    return HierarchyEntityNode(
        entity_type=entity_type,
        id=row.id,
        name=row.name,
        part_number=getattr(row, "part_number", None),
        serial_number=getattr(row, "serial_number", None),
        installation_date=getattr(row, "installation_date", None),
        configuration_item=getattr(row, "configuration_item", None),
        current_status=_status_name(getattr(row, "status", None)),
        previous_status=prev_status,
        created_date=getattr(row, "created_at", None),
        modified_date=modified,
        description=getattr(row, "description", None),
        picture_url=getattr(row, "picture_url", None),
        children=children or [],
    )


def _build_hierarchy(session: Session, project_id: int) -> List[HierarchyEntityNode]:
    systems = session.exec(
        select(System).where(System.project_id == project_id).order_by(System.id)
    ).all()
    tree: List[HierarchyEntityNode] = []
    for system in systems:
        subsystems = session.exec(
            select(Subsystem).where(Subsystem.system_id == system.id).order_by(Subsystem.id)
        ).all()
        subsystem_nodes: List[HierarchyEntityNode] = []
        for subsystem in subsystems:
            modules = session.exec(
                select(Module).where(Module.subsystem_id == subsystem.id).order_by(Module.id)
            ).all()
            module_nodes: List[HierarchyEntityNode] = []
            for module in modules:
                units = session.exec(
                    select(Unit).where(Unit.module_id == module.id).order_by(Unit.id)
                ).all()
                unit_nodes: List[HierarchyEntityNode] = []
                for unit in units:
                    components = session.exec(
                        select(Component).where(Component.unit_id == unit.id).order_by(Component.id)
                    ).all()
                    component_nodes = [
                        _node_from_hw(session, "component", c) for c in components
                    ]
                    unit_nodes.append(_node_from_hw(session, "unit", unit, component_nodes))
                module_nodes.append(_node_from_hw(session, "module", module, unit_nodes))
            subsystem_nodes.append(
                _node_from_hw(session, "subsystem", subsystem, module_nodes)
            )
        tree.append(_node_from_hw(session, "system", system, subsystem_nodes))
    return tree


def _collect_images(nodes: List[HierarchyEntityNode]) -> List[ImageItem]:
    images: List[ImageItem] = []

    def walk(node: HierarchyEntityNode) -> None:
        if node.picture_url:
            images.append(
                ImageItem(
                    url=node.picture_url,
                    caption=f"{node.entity_type}: {node.name}",
                    entity_name=node.name,
                )
            )
        for child in node.children:
            walk(child)

    for n in nodes:
        walk(n)
    return images


def _attachments_for_owners(
    session: Session, owners: List[Tuple[str, int]]
) -> List[AttachmentItem]:
    if not owners:
        return []
    items: List[AttachmentItem] = []
    for owner_type, owner_id in owners:
        rows = session.exec(
            select(EntityAttachment).where(
                EntityAttachment.owner_type == owner_type,
                EntityAttachment.owner_id == owner_id,
            )
        ).all()
        for row in rows:
            items.append(
                AttachmentItem(
                    id=row.id,
                    file_name=row.file_name,
                    mime_type=row.mime_type,
                    attachment_type=_str(row.attachment_type),
                    description=row.description,
                    uploaded_at=row.uploaded_at,
                )
            )
    return items


def _flatten_hierarchy_ids(nodes: List[HierarchyEntityNode]) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []

    def walk(node: HierarchyEntityNode) -> None:
        out.append((node.entity_type, node.id))
        for child in node.children:
            walk(child)

    for n in nodes:
        walk(n)
    return out


def _config_history_for_entities(
    session: Session, entity_ids: List[int]
) -> List[ConfigHistoryItem]:
    if not entity_ids:
        return []
    rows = session.exec(
        select(ConfigurationHistory)
        .where(ConfigurationHistory.entity_id.in_(entity_ids))
        .order_by(ConfigurationHistory.change_date.desc())
    ).all()
    items: List[ConfigHistoryItem] = []
    for row in rows:
        performer = session.get(User, row.performed_by) if row.performed_by else None
        items.append(
            ConfigHistoryItem(
                id=row.id,
                change_type=_str(row.resolution_type),
                fault_type=_str(row.fault_type),
                resolution_type=_str(row.resolution_type),
                old_part_number=row.old_part_number,
                old_serial_number=getattr(row, "old_serial_number", None),
                new_part_number=row.new_part_number,
                new_serial_number=getattr(row, "new_serial_number", None),
                change_date=row.change_date,
                installation_date=row.installation_date,
                removal_date=row.removal_date,
                reason=row.reason,
                corrective_action=row.corrective_action,
                remarks=row.remarks,
                performed_by=_user_name(performer),
                work_order_number=row.work_order_number,
            )
        )
    return items


def _build_timeline_events(
    project: Project,
    order: Optional[Order],
    hierarchy: List[HierarchyEntityNode],
    config_history: List[ConfigHistoryItem],
) -> List[TimelineEvent]:
    events: List[TimelineEvent] = []
    events.append(
        TimelineEvent(
            event_type="creation",
            title="Project Created",
            description=project.name,
            occurred_at=project.created_at,
        )
    )
    if project.start_date:
        events.append(
            TimelineEvent(
                event_type="assembly",
                title="Project Start",
                occurred_at=project.start_date
                if isinstance(project.start_date, datetime)
                else datetime.combine(project.start_date, datetime.min.time(), tzinfo=timezone.utc),
            )
        )

    def walk(node: HierarchyEntityNode) -> None:
        if node.created_date:
            events.append(
                TimelineEvent(
                    event_type="creation",
                    title=f"{node.entity_type.title()} Created",
                    description=node.name,
                    occurred_at=node.created_date,
                )
            )
        if node.installation_date:
            events.append(
                TimelineEvent(
                    event_type="installation",
                    title=f"{node.entity_type.title()} Installed",
                    description=node.name,
                    occurred_at=node.installation_date,
                )
            )
        for child in node.children:
            walk(child)

    for n in hierarchy:
        walk(n)

    for ch in config_history:
        events.append(
            TimelineEvent(
                event_type="modification",
                title="Configuration Change",
                description=ch.reason or ch.resolution_type,
                occurred_at=ch.change_date,
                actor=ch.performed_by,
            )
        )

    if order and order.delivery_date:
        events.append(
            TimelineEvent(
                event_type="delivery",
                title="Order Delivery Date",
                description=order.order_number,
                occurred_at=datetime.combine(
                    order.delivery_date, datetime.min.time(), tzinfo=timezone.utc
                ),
            )
        )
    if project.end_date:
        events.append(
            TimelineEvent(
                event_type="approval",
                title="Project Completion",
                occurred_at=project.end_date
                if isinstance(project.end_date, datetime)
                else datetime.combine(project.end_date, datetime.min.time(), tzinfo=timezone.utc),
            )
        )

    events.sort(key=lambda e: _as_utc(e.occurred_at))
    return events


def build_history_dossier(session: Session, project_id: int) -> BuildHistoryDossierResponse:
    project = session.get(Project, project_id)
    if not project:
        raise ValueError("Project not found")

    order = session.get(Order, project.order_id) if project.order_id else None
    customer = session.get(Customer, order.customer_id) if order else None
    owner = session.get(User, project.owner_id) if project.owner_id else None
    project_status = session.get(Status, project.status_id) if project.status_id else None
    order_status = (
        session.get(Status, order.status_id) if order and order.status_id else None
    )

    hierarchy = _build_hierarchy(session, project_id)
    owner_pairs = _flatten_hierarchy_ids(hierarchy)
    tracker_ids: List[int] = []
    for etype, eid in owner_pairs:
        tracker = _entity_tracker(session, etype, eid)
        if tracker:
            tracker_ids.append(tracker.id)

    config_history = _config_history_for_entities(session, tracker_ids)
    images = _collect_images(hierarchy)
    attachments = _attachments_for_owners(session, owner_pairs)
    timeline = _build_timeline_events(project, order, hierarchy, config_history)

    return BuildHistoryDossierResponse(
        project={
            "id": project.id,
            "name": project.name,
            "project_number": f"PRJ-{project.id}",
            "description": project.description,
            "start_date": _str(project.start_date),
            "completion_date": _str(project.end_date),
            "status": _status_name(project_status),
            "project_manager": _user_name(owner) or (order.project_manager if order else None),
            "progress": project.progress,
        },
        customer={
            "name": customer.name if customer else None,
            "address": customer.address if customer else None,
            "contact_person": customer.primary_contact_name if customer else None,
            "country": customer.country if customer else None,
            "phone": customer.phone if customer else None,
            "email": customer.email if customer else None,
            "customer_code": customer.customer_code if customer else None,
        }
        if customer
        else None,
        order={
            "order_number": order.order_number,
            "order_date": _str(order.order_date),
            "delivery_date": _str(order.delivery_date),
            "status": _status_name(order_status),
            "quantity": None,
            "remarks": order.remarks,
            "title": order.title,
            "total_value": _str(order.total_value),
            "currency": order.currency,
        }
        if order
        else None,
        delivery={
            "delivery_date": _str(order.delivery_date) if order else None,
            "delivered_by": None,
            "received_by": None,
            "acceptance_status": None,
            "delivery_notes": order.remarks if order else None,
        },
        hierarchy=hierarchy,
        configuration_history=config_history,
        timeline=timeline,
        images=images,
        attachments=attachments,
        signatures={
            "prepared_by": None,
            "reviewed_by": None,
            "approved_by": None,
        },
    )


def maintenance_history_dossier(
    session: Session, case_id: int
) -> MaintenanceHistoryDossierResponse:
    case = session.get(MaintenanceCase, case_id)
    if not case:
        raise ValueError("Maintenance case not found")

    project = session.get(Project, case.project_id)
    reporter = session.get(User, case.reported_by) if case.reported_by else None
    m_status = session.get(Status, case.status_id) if case.status_id else None

    faulty_entities = session.exec(
        select(FaultyEntity).where(FaultyEntity.case_id == case_id)
    ).all()

    fe_items: List[FaultyEntityItem] = []
    all_actions_for_timeline: List[MaintenanceActionItem] = []
    primary_fault: Optional[Dict[str, Any]] = None

    for fe in faulty_entities:
        actions = session.exec(
            select(MaintenanceAction)
            .where(MaintenanceAction.faulty_entity_id == fe.id)
            .order_by(MaintenanceAction.performed_at)
        ).all()
        action_items: List[MaintenanceActionItem] = []
        for action in actions:
            performer = (
                session.get(User, action.performed_by) if action.performed_by else None
            )
            item = MaintenanceActionItem(
                id=action.id,
                action_type=_str(action.action_type),
                outcome=_str(action.outcome),
                notes=action.notes,
                performed_by=_user_name(performer),
                performed_at=action.performed_at,
                duration=None,
                replacement_entity_type=_str(action.replacement_entity_type),
                replacement_entity_id=action.replacement_entity_id,
            )
            action_items.append(item)
            all_actions_for_timeline.append(item)

        fe_item = FaultyEntityItem(
            id=fe.id,
            entity_name=fe.entity_name,
            entity_type=_str(fe.entity_type),
            entity_id=fe.entity_id,
            part_number=fe.part_number,
            serial_number=fe.serial_number,
            fault_type=_str(fe.fault_type),
            fault_description=fe.fault_description,
            status=_str(fe.status),
            resolution_type=_str(fe.resolution_type),
            system=None,
            subsystem=None,
            module=None,
            unit=None,
            component=None,
            actions=action_items,
        )
        # Map hierarchy level into named slots when available
        et = _str(fe.entity_type)
        if et == "system":
            fe_item.system = fe.entity_name
        elif et == "subsystem":
            fe_item.subsystem = fe.entity_name
        elif et == "module":
            fe_item.module = fe.entity_name
        elif et == "unit":
            fe_item.unit = fe.entity_name
        elif et == "component":
            fe_item.component = fe.entity_name

        fe_items.append(fe_item)
        if primary_fault is None:
            primary_fault = {
                "fault_description": fe.fault_description or case.description,
                "fault_category": None,
                "fault_type": _str(fe.fault_type),
                "root_cause": None,
                "failure_mode": None,
                "severity": None,
            }

    config_rows = session.exec(
        select(ConfigurationHistory)
        .where(ConfigurationHistory.maintenance_case_id == case_id)
        .order_by(ConfigurationHistory.change_date.desc())
    ).all()
    replacements: List[ConfigHistoryItem] = []
    for row in config_rows:
        performer = session.get(User, row.performed_by) if row.performed_by else None
        replacements.append(
            ConfigHistoryItem(
                id=row.id,
                change_type=_str(row.resolution_type),
                fault_type=_str(row.fault_type),
                resolution_type=_str(row.resolution_type),
                old_part_number=row.old_part_number,
                old_serial_number=getattr(row, "old_serial_number", None),
                new_part_number=row.new_part_number,
                new_serial_number=getattr(row, "new_serial_number", None),
                change_date=row.change_date,
                installation_date=row.installation_date,
                removal_date=row.removal_date,
                reason=row.reason,
                corrective_action=row.corrective_action,
                remarks=row.remarks,
                performed_by=_user_name(performer),
                work_order_number=row.work_order_number,
            )
        )

    deliveries_db = session.exec(
        select(MaintenanceDelivery).where(MaintenanceDelivery.case_id == case_id)
    ).all()
    deliveries: List[MaintenanceDeliveryItem] = []
    for d in deliveries_db:
        deliverer = session.get(User, d.delivered_by) if d.delivered_by else None
        deliveries.append(
            MaintenanceDeliveryItem(
                id=d.id,
                delivery_type=_str(d.delivery_type),
                status=_str(d.status),
                delivered_by=_user_name(deliverer),
                received_by=d.received_by,
                notes=d.notes,
                delivered_at=d.delivered_at,
                returned_date=None,
                received_date=_str(d.delivered_at),
                acceptance=_str(d.status),
            )
        )

    timeline: List[TimelineEvent] = [
        TimelineEvent(
            event_type="creation",
            title="Case Opened",
            description=case.case_number,
            occurred_at=case.reported_at,
            actor=_user_name(reporter),
        )
    ]
    for action in all_actions_for_timeline:
        timeline.append(
            TimelineEvent(
                event_type=action.action_type or "action",
                title=f"Action: {action.action_type}",
                description=action.notes,
                occurred_at=action.performed_at,
                actor=action.performed_by,
            )
        )
    for d in deliveries:
        timeline.append(
            TimelineEvent(
                event_type="delivery",
                title=f"Delivery: {d.delivery_type}",
                description=d.notes,
                occurred_at=d.delivered_at,
                actor=d.delivered_by,
            )
        )
    if case.closed_at:
        timeline.append(
            TimelineEvent(
                event_type="approval",
                title="Case Closed",
                occurred_at=case.closed_at,
            )
        )
    timeline.sort(key=lambda e: _as_utc(e.occurred_at))

    # Attachments linked to hierarchy entities referenced by faulty entities
    owner_pairs: List[Tuple[str, int]] = []
    for fe in faulty_entities:
        if fe.entity_type and fe.entity_id:
            owner_pairs.append((_str(fe.entity_type) or "component", fe.entity_id))
    attachments = _attachments_for_owners(session, owner_pairs)

    engineer = None
    if all_actions_for_timeline:
        engineer = all_actions_for_timeline[-1].performed_by
    if not engineer:
        engineer = _user_name(reporter)

    return MaintenanceHistoryDossierResponse(
        case={
            "id": case.id,
            "maintenance_number": case.case_number,
            "current_status": _str(case.status),
            "status_name": _status_name(m_status),
            "priority": None,
            "opened_date": _str(case.reported_at),
            "closed_date": _str(case.closed_at),
            "engineer": engineer,
            "description": case.description,
            "resolution_notes": case.resolution_notes,
            "project_id": case.project_id,
            "project_name": case.project_name or (project.name if project else None),
            "part_number": case.part_number,
        },
        fault=primary_fault
        or {
            "fault_description": case.description,
            "fault_category": None,
            "fault_type": None,
            "root_cause": None,
            "failure_mode": None,
            "severity": None,
        },
        faulty_entities=fe_items,
        replacements=replacements,
        timeline=timeline,
        deliveries=deliveries,
        attachments=attachments,
        signatures={
            "prepared_by": engineer,
            "reviewed_by": None,
            "approved_by": None,
        },
    )


def inventory_report(
    session: Session,
    mode: str = "current",
    search: Optional[str] = None,
    location: Optional[str] = None,
    project_id: Optional[int] = None,
    part_number: Optional[str] = None,
    serial_number: Optional[str] = None,
    status_name: Optional[str] = None,
) -> InventoryReportResponse:
    placeholders: List[str] = []
    stmt = select(Inventory)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Inventory.name.ilike(like),
                Inventory.part_number.ilike(like),
                Inventory.serial_number.ilike(like),
                Inventory.sku.ilike(like),
            )
        )
    if location:
        stmt = stmt.where(Inventory.location.ilike(f"%{location}%"))
    if part_number:
        stmt = stmt.where(Inventory.part_number.ilike(f"%{part_number}%"))
    if serial_number:
        stmt = stmt.where(Inventory.serial_number.ilike(f"%{serial_number}%"))
    if project_id:
        # Inventory.entity_id stores the linked hierarchy row PK after install.
        system_ids = [
            s.id
            for s in session.exec(select(System).where(System.project_id == project_id)).all()
        ]
        subsystem_ids = [
            s.id
            for s in session.exec(
                select(Subsystem).where(Subsystem.system_id.in_(system_ids))
            ).all()
        ] if system_ids else []
        module_ids = [
            m.id
            for m in session.exec(
                select(Module).where(Module.subsystem_id.in_(subsystem_ids))
            ).all()
        ] if subsystem_ids else []
        unit_ids = [
            u.id
            for u in session.exec(select(Unit).where(Unit.module_id.in_(module_ids))).all()
        ] if module_ids else []
        component_ids = [
            c.id
            for c in session.exec(select(Component).where(Component.unit_id.in_(unit_ids))).all()
        ] if unit_ids else []
        all_ids = set(system_ids + subsystem_ids + module_ids + unit_ids + component_ids)
        if all_ids:
            stmt = stmt.where(Inventory.entity_id.in_(list(all_ids)))
        else:
            stmt = stmt.where(Inventory.id == -1)

    rows = session.exec(stmt.order_by(Inventory.id)).all()
    items: List[InventoryReportItem] = []
    for row in rows:
        status = session.get(Status, row.status_id) if row.status_id else None
        sname = _status_name(status)
        if status_name and (not sname or status_name.lower() not in sname.lower()):
            continue
        qty = row.quantity or 0
        sname_l = (sname or "").lower()

        include = True
        if mode == "low":
            include = 0 < qty <= 5
        elif mode == "out":
            include = qty <= 0
        elif mode == "reserved":
            include = "reserv" in sname_l
        elif mode == "issued":
            include = "issu" in sname_l
        elif mode == "available":
            include = qty > 0 and "issu" not in sname_l and "reserv" not in sname_l
        elif mode == "movements":
            include = False
            placeholders = ["Inventory movement ledger is not available in the current schema"]
        elif mode == "valuation":
            include = False
            placeholders = ["Stock valuation / unit cost is not available in the current schema"]
        elif mode in ("by_project", "by_system", "by_location", "current", "lookup"):
            include = True

        if not include:
            continue

        items.append(
            InventoryReportItem(
                id=row.id,
                name=row.name,
                inventory_type=_str(row.inventory_type),
                part_number=row.part_number,
                serial_number=row.serial_number,
                quantity=row.quantity,
                location=row.location,
                status_name=sname,
                sku=row.sku,
                oem_name=row.oem_name,
                entity_id=row.entity_id,
                configuration_item=row.configuration_item,
                added_date=row.added_date,
            )
        )

    summary = {
        "total_items": len(items),
        "total_quantity": sum(i.quantity or 0 for i in items),
        "mode": mode,
    }
    return InventoryReportResponse(
        mode=mode, items=items, summary=summary, placeholders=placeholders
    )


def maintenance_summary_report(
    session: Session,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    search: Optional[str] = None,
) -> MaintenanceSummaryResponse:
    stmt = select(MaintenanceCase)
    if project_id:
        stmt = stmt.where(MaintenanceCase.project_id == project_id)
    if status:
        try:
            stmt = stmt.where(MaintenanceCase.status == CaseStatus(status))
        except ValueError:
            pass
    if date_from:
        stmt = stmt.where(MaintenanceCase.reported_at >= date_from)
    if date_to:
        stmt = stmt.where(MaintenanceCase.reported_at <= date_to)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                MaintenanceCase.case_number.ilike(like),
                MaintenanceCase.description.ilike(like),
            )
        )

    cases = session.exec(stmt.order_by(MaintenanceCase.reported_at.desc())).all()
    now = _now()
    overdue_threshold = timedelta(days=30)

    case_rows: List[Dict[str, Any]] = []
    by_status: Dict[str, int] = defaultdict(int)
    aging_buckets = {"0-7d": 0, "8-30d": 0, "31-90d": 0, "90d+": 0}
    engineer_counts: Dict[str, int] = defaultdict(int)
    monthly: Dict[str, int] = defaultdict(int)
    open_count = closed_count = overdue_count = 0
    under_inspection = under_repair = 0

    mttr_samples: List[float] = []

    for case in cases:
        st = _str(case.status) or "unknown"
        by_status[st] += 1
        age_days = (now - case.reported_at).days if case.reported_at else 0
        if age_days <= 7:
            aging_buckets["0-7d"] += 1
        elif age_days <= 30:
            aging_buckets["8-30d"] += 1
        elif age_days <= 90:
            aging_buckets["31-90d"] += 1
        else:
            aging_buckets["90d+"] += 1

        if case.status == CaseStatus.CLOSED:
            closed_count += 1
        else:
            open_count += 1
            if case.reported_at and (now - case.reported_at) > overdue_threshold:
                overdue_count += 1
        if case.status == CaseStatus.UNDER_INSPECTION:
            under_inspection += 1
        if case.status == CaseStatus.UNDER_REPAIR:
            under_repair += 1

        if case.reported_at and case.closed_at:
            delta = (case.closed_at - case.reported_at).total_seconds() / 3600.0
            if delta >= 0:
                mttr_samples.append(delta)
        elif case.reported_at and getattr(case, "resolved_at", None):
            resolved = getattr(case, "resolved_at")
            if resolved:
                delta = (resolved - case.reported_at).total_seconds() / 3600.0
                if delta >= 0:
                    mttr_samples.append(delta)

        if case.reported_at:
            monthly[case.reported_at.strftime("%Y-%m")] += 1

        reporter = session.get(User, case.reported_by) if case.reported_by else None
        eng = _user_name(reporter) or "Unassigned"
        engineer_counts[eng] += 1

        case_rows.append(
            {
                "id": case.id,
                "case_number": case.case_number,
                "status": st,
                "project_id": case.project_id,
                "project_name": case.project_name,
                "reported_at": _str(case.reported_at),
                "closed_at": _str(case.closed_at),
                "age_days": age_days,
                "engineer": eng,
                "description": case.description,
            }
        )

    # Fault type distribution
    fault_counts: Dict[str, int] = defaultdict(int)
    case_ids = [c.id for c in cases]
    if case_ids:
        faults = session.exec(
            select(FaultyEntity).where(FaultyEntity.case_id.in_(case_ids))
        ).all()
        for f in faults:
            fault_counts[_str(f.fault_type) or "unclassified"] += 1

    mttr = round(sum(mttr_samples) / len(mttr_samples), 2) if mttr_samples else None

    return MaintenanceSummaryResponse(
        summary={
            "total_cases": len(cases),
            "open_cases": open_count,
            "closed_cases": closed_count,
            "under_inspection": under_inspection,
            "under_repair": under_repair,
            "waiting_parts": 0,
            "overdue_cases": overdue_count,
        },
        cases=case_rows,
        by_status=[{"name": k, "value": v} for k, v in sorted(by_status.items())],
        by_fault_type=[{"name": k, "value": v} for k, v in sorted(fault_counts.items())],
        engineer_workload=[
            {"name": k, "value": v} for k, v in sorted(engineer_counts.items())
        ],
        aging=[{"name": k, "value": v} for k, v in aging_buckets.items()],
        monthly_trends=[
            {"name": k, "value": v} for k, v in sorted(monthly.items())
        ],
        mttr_hours=mttr,
        placeholders=["Waiting Parts status is not modeled; shown as 0"],
    )


def executive_report(
    session: Session, filters: DashboardFilters
) -> ExecutiveReportResponse:
    dashboard = build_executive_dashboard(session, filters)
    # Financial slice from orders
    order_stmt = select(Order)
    if filters.customer_id:
        order_stmt = order_stmt.where(Order.customer_id == filters.customer_id)
    if filters.order_id:
        order_stmt = order_stmt.where(Order.id == filters.order_id)
    orders = session.exec(order_stmt).all()
    total_value = sum((o.total_value or Decimal("0")) for o in orders)
    currencies = {o.currency or "PKR" for o in orders}

    financial = {
        "order_value": float(total_value),
        "currency": next(iter(currencies)) if len(currencies) == 1 else "MIXED",
        "order_count": len(orders),
        "project_cost": None,
        "inventory_value": None,
        "maintenance_cost": None,
        "revenue": None,
        "budget_utilization": None,
    }

    # Serialize dashboard pydantic model to dict
    dashboard_dict = (
        dashboard.model_dump()
        if hasattr(dashboard, "model_dump")
        else dashboard.dict()
    )

    return ExecutiveReportResponse(
        dashboard=dashboard_dict,
        financial=financial,
        placeholders=[
            "Project Cost",
            "Inventory Value",
            "Maintenance Cost",
            "Revenue",
            "Budget Utilization",
        ],
    )
