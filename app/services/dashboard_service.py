from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import and_, case, func, or_
from sqlmodel import Session, select

from app.models.base import CaseStatus, EntityType, FaultyEntityStatus
from app.domain.workflow_status import ProjectWorkflowStatus
from app.models.tables import (
    Component,
    ConfigurationHistory,
    Customer,
    Entity,
    EntityStatusHistory,
    FaultyEntity,
    MaintenanceAction,
    MaintenanceCase,
    Module,
    Order,
    Project,
    Status,
    Subsystem,
    System,
    Unit,
    User,
)
from app.schemas.dashboard import (
    ActivityItem,
    ChartDataPoint,
    ConfigurationSection,
    ExecutiveDashboardResponse,
    ExecutiveKpisSection,
    GaugeMetric,
    KpiMetric,
    MaintenanceAnalyticsSection,
    ProductStructureSection,
    ProjectAnalyticsSection,
    ProjectProgressItem,
    RecentActivitiesSection,
    ReliabilitySection,
    ResourcesSection,
    StackedBarGroup,
    StackedBarSeries,
    TreemapNode,
)

STATUS_PROGRESS = {
    "Initiation": 10,
    "Planning": 25,
    "Execution": 50,
    "Monitoring": 75,
    "Completed": 100,
    "On Hold": 0,
}

# Active lifecycle statuses (schedule-derived On Track / Delayed apply only here).
LIFECYCLE_STATUSES = ["Initiation", "Planning", "Execution", "Monitoring"]

OPEN_CASE_STATUSES = [
    CaseStatus.OPEN,
    CaseStatus.UNDER_INSPECTION,
    CaseStatus.UNDER_REPAIR,
]

ACTIVE_FAULT_STATUSES = [
    FaultyEntityStatus.IDENTIFIED,
    FaultyEntityStatus.UNDER_INSPECTION,
    FaultyEntityStatus.CONFIRMED_FAULTY,
]


@dataclass
class DashboardFilters:
    customer_id: Optional[int] = None
    order_id: Optional[int] = None
    project_id: Optional[int] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    project_status: Optional[str] = None
    maintenance_status: Optional[str] = None
    configuration_status: Optional[str] = None
    search: Optional[str] = None
    kpi_filter: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _pct_change(current: int, previous: int) -> Optional[float]:
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


def _scoped_project_ids(session: Session, filters: DashboardFilters) -> Optional[set[int]]:
    stmt = select(Project.id).join(Order, Project.order_id == Order.id, isouter=True)
    stmt = stmt.join(Status, Project.status_id == Status.id, isouter=True)

    conditions = []
    if filters.customer_id:
        conditions.append(Order.customer_id == filters.customer_id)
    if filters.order_id:
        conditions.append(Project.order_id == filters.order_id)
    if filters.project_id:
        conditions.append(Project.id == filters.project_id)
    if filters.project_status:
        conditions.append(Status.status_name == filters.project_status)
    if filters.date_from:
        conditions.append(Project.created_at >= filters.date_from)
    if filters.date_to:
        conditions.append(Project.created_at <= filters.date_to)
    if filters.search:
        term = f"%{filters.search.strip()}%"
        conditions.append(or_(Project.name.ilike(term), Project.description.ilike(term)))

    if conditions:
        stmt = stmt.where(and_(*conditions))

    if not any(
        [
            filters.customer_id,
            filters.order_id,
            filters.project_id,
            filters.project_status,
            filters.date_from,
            filters.date_to,
            filters.search,
        ]
    ):
        return None

    return set(session.exec(stmt).all())


def _scoped_customer_ids(session: Session, filters: DashboardFilters) -> Optional[set[int]]:
    if filters.customer_id:
        return {filters.customer_id}
    if filters.order_id:
        order = session.get(Order, filters.order_id)
        return {order.customer_id} if order else set()
    if filters.project_id:
        project = session.get(Project, filters.project_id)
        if project and project.order_id:
            order = session.get(Order, project.order_id)
            return {order.customer_id} if order else set()
    project_ids = _scoped_project_ids(session, filters)
    if project_ids is not None:
        rows = session.exec(
            select(Order.customer_id)
            .join(Project, Project.order_id == Order.id)
            .where(Project.id.in_(project_ids))
        ).all()
        return set(rows)
    return None


def _count_query(session: Session, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    return session.exec(stmt).one()


def _enum_str(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _build_kpis(session: Session, filters: DashboardFilters) -> ExecutiveKpisSection:
    now = _now()
    month_start = _month_start(now)
    prev_month_start = _month_start(month_start - timedelta(days=1))
    prev_month_end = month_start

    project_ids = _scoped_project_ids(session, filters)
    customer_ids = _scoped_customer_ids(session, filters)

    customer_cond = []
    if customer_ids is not None:
        customer_cond.append(Customer.id.in_(customer_ids) if customer_ids else Customer.id == -1)

    order_cond = []
    if customer_ids is not None:
        order_cond.append(Order.customer_id.in_(customer_ids) if customer_ids else Order.id == -1)
    if filters.order_id:
        order_cond.append(Order.id == filters.order_id)

    project_cond = []
    if project_ids is not None:
        project_cond.append(Project.id.in_(project_ids) if project_ids else Project.id == -1)

    total_customers = _count_query(session, Customer, *customer_cond)
    total_orders = _count_query(session, Order, *order_cond)
    total_projects = _count_query(session, Project, *project_cond)

    active_projects = session.exec(
        select(func.count())
        .select_from(Project)
        .join(Status, Project.status_id == Status.id, isouter=True)
        .where(*(project_cond or []), Status.status_name.notin_(["Completed", "On Hold"]))
    ).one()

    completed_projects = session.exec(
        select(func.count())
        .select_from(Project)
        .join(Status, Project.status_id == Status.id, isouter=True)
        .where(*(project_cond or []), Status.status_name == "Completed")
    ).one()

    delayed_projects = session.exec(
        select(func.count())
        .select_from(Project)
        .join(Status, Project.status_id == Status.id, isouter=True)
        .where(
            *(project_cond or []),
            Status.status_name.in_(LIFECYCLE_STATUSES),
            Project.end_date.isnot(None),
            Project.end_date < now,
        )
    ).one()

    case_cond = []
    if project_ids is not None:
        case_cond.append(
            MaintenanceCase.project_id.in_(project_ids) if project_ids else MaintenanceCase.id == -1
        )
    if filters.maintenance_status:
        case_cond.append(MaintenanceCase.status == filters.maintenance_status)

    open_cases = session.exec(
        select(func.count())
        .select_from(MaintenanceCase)
        .where(*(case_cond or []), MaintenanceCase.status.in_(OPEN_CASE_STATUSES))
    ).one()

    fe_cond = []
    if project_ids is not None:
        fe_cond.append(
            MaintenanceCase.project_id.in_(project_ids) if project_ids else MaintenanceCase.id == -1
        )

    open_faulty = session.exec(
        select(func.count())
        .select_from(FaultyEntity)
        .join(MaintenanceCase, FaultyEntity.case_id == MaintenanceCase.id)
        .where(*(fe_cond or []), FaultyEntity.status.in_(ACTIVE_FAULT_STATUSES))
    ).one()

    components_investigation = session.exec(
        select(func.count())
        .select_from(FaultyEntity)
        .join(MaintenanceCase, FaultyEntity.case_id == MaintenanceCase.id)
        .where(
            *(fe_cond or []),
            FaultyEntity.entity_type == EntityType.COMPONENT,
            FaultyEntity.status.in_(ACTIVE_FAULT_STATUSES),
        )
    ).one()

    config_cond = [ConfigurationHistory.change_date >= month_start]
    if filters.configuration_status:
        config_cond.append(ConfigurationHistory.resolution_type == filters.configuration_status)
    if project_ids is not None:
        config_cond.append(
            ConfigurationHistory.maintenance_case_id.in_(
                select(MaintenanceCase.id).where(MaintenanceCase.project_id.in_(project_ids))
            )
        )

    config_this_month = _count_query(session, ConfigurationHistory, *config_cond)

    # Prior-month program health (as of month_start) for MoM % point change.
    # Portfolio that existed before this month:
    prev_total = session.exec(
        select(func.count())
        .select_from(Project)
        .where(*(project_cond or []), Project.created_at < month_start)
    ).one()
    # Delayed as of month_start: past end date by then, and either still not completed
    # or completed during the current month (was open/overdue entering this month).
    prev_delayed = session.exec(
        select(func.count())
        .select_from(Project)
        .join(Status, Project.status_id == Status.id, isouter=True)
        .where(
            *(project_cond or []),
            Project.created_at < month_start,
            Project.end_date.isnot(None),
            Project.end_date < month_start,
            or_(
                Status.status_name.in_(LIFECYCLE_STATUSES),
                and_(Status.status_name == "Completed", Project.updated_at >= month_start),
            ),
        )
    ).one()

    health_now = (
        round(((total_projects - delayed_projects) / total_projects) * 100)
        if total_projects > 0
        else None
    )
    health_prev = (
        round(((prev_total - prev_delayed) / prev_total) * 100) if prev_total > 0 else None
    )
    health_change = (
        round(float(health_now - health_prev), 1)
        if health_now is not None and health_prev is not None
        else None
    )

    prev_customers = session.exec(
        select(func.count())
        .select_from(Customer)
        .where(
            *(customer_cond or []),
            Customer.created_at >= prev_month_start,
            Customer.created_at < prev_month_end,
        )
    ).one()
    curr_customers = session.exec(
        select(func.count())
        .select_from(Customer)
        .where(*(customer_cond or []), Customer.created_at >= month_start)
    ).one()

    metrics = [
        KpiMetric(
            key="total_customers",
            label="Total Customers",
            value=total_customers,
            change_percent=_pct_change(curr_customers, prev_customers),
        ),
        KpiMetric(key="total_orders", label="Total Orders", value=total_orders),
        KpiMetric(key="total_projects", label="Total Projects", value=total_projects),
        KpiMetric(key="active_projects", label="Active Projects", value=active_projects),
        KpiMetric(key="completed_projects", label="Completed Projects", value=completed_projects),
        KpiMetric(
            key="delayed_projects",
            label="Delayed Projects",
            value=delayed_projects,
            change_value=float(delayed_projects - prev_delayed) if prev_total > 0 else None,
        ),
        KpiMetric(
            key="program_health",
            label="Overall Program Health",
            value=int(health_now) if health_now is not None else 0,
            change_percent=health_change,
        ),
        KpiMetric(
            key="open_maintenance_cases",
            label="Open Maintenance Cases",
            value=open_cases,
            change_value=(
                float(
                    session.exec(
                        select(func.count())
                        .select_from(MaintenanceCase)
                        .where(*(case_cond or []), MaintenanceCase.reported_at >= month_start)
                    ).one()
                    - session.exec(
                        select(func.count())
                        .select_from(MaintenanceCase)
                        .where(
                            *(case_cond or []),
                            MaintenanceCase.reported_at >= prev_month_start,
                            MaintenanceCase.reported_at < month_start,
                        )
                    ).one()
                )
            ),
        ),
        KpiMetric(key="open_faulty_entities", label="Open Faulty Entities", value=open_faulty),
        KpiMetric(
            key="components_under_investigation",
            label="Components Under Investigation",
            value=components_investigation,
        ),
        KpiMetric(
            key="config_changes_this_month",
            label="Configuration Changes This Month",
            value=config_this_month,
        ),
    ]
    return ExecutiveKpisSection(metrics=metrics)


def _build_projects(session: Session, filters: DashboardFilters) -> ProjectAnalyticsSection:
    project_ids = _scoped_project_ids(session, filters)
    cond = []
    if project_ids is not None:
        cond.append(Project.id.in_(project_ids) if project_ids else Project.id == -1)

    now = _now()

    # Executive buckets (not raw lifecycle names):
    # Completed / On Hold from status; Delayed / On Track from end_date among lifecycle statuses.
    completed_count = session.exec(
        select(func.count())
        .select_from(Project)
        .join(Status, Project.status_id == Status.id, isouter=True)
        .where(*(cond or []), Status.status_name == "Completed")
    ).one()
    on_hold_count = session.exec(
        select(func.count())
        .select_from(Project)
        .join(Status, Project.status_id == Status.id, isouter=True)
        .where(*(cond or []), Status.status_name == "On Hold")
    ).one()
    delayed_count = session.exec(
        select(func.count())
        .select_from(Project)
        .join(Status, Project.status_id == Status.id, isouter=True)
        .where(
            *(cond or []),
            Status.status_name.in_(LIFECYCLE_STATUSES),
            Project.end_date.isnot(None),
            Project.end_date < now,
        )
    ).one()
    on_track_count = session.exec(
        select(func.count())
        .select_from(Project)
        .join(Status, Project.status_id == Status.id, isouter=True)
        .where(
            *(cond or []),
            Status.status_name.in_(LIFECYCLE_STATUSES),
            or_(Project.end_date.is_(None), Project.end_date >= now),
        )
    ).one()

    status_distribution = [
        ChartDataPoint(name=name, value=float(value))
        for name, value in (
            ("On Track", on_track_count),
            ("Delayed", delayed_count),
            ("On Hold", on_hold_count),
            ("Completed", completed_count),
        )
        if value > 0
    ]

    timeline_rows = session.exec(
        select(func.to_char(Project.created_at, "YYYY-MM"), func.count(Project.id))
        .where(*(cond or []))
        .group_by(func.to_char(Project.created_at, "YYYY-MM"))
        .order_by(func.to_char(Project.created_at, "YYYY-MM"))
    ).all()
    timeline = [ChartDataPoint(name=row[0], value=float(row[1])) for row in timeline_rows]

    completed_cond = list(cond or [])
    completed_timeline_rows = session.exec(
        select(func.to_char(Project.end_date, "YYYY-MM"), func.count(Project.id))
        .join(Status, Project.status_id == Status.id, isouter=True)
        .where(
            *completed_cond,
            Status.status_name.in_(
                ["Completed", ProjectWorkflowStatus.COMPLETED.value]
            ),
            Project.end_date.isnot(None),
        )
        .group_by(func.to_char(Project.end_date, "YYYY-MM"))
        .order_by(func.to_char(Project.end_date, "YYYY-MM"))
    ).all()
    completed_timeline = [
        ChartDataPoint(name=row[0], value=float(row[1])) for row in completed_timeline_rows
    ]

    window_start = _month_start(now)
    window_end = window_start + timedelta(days=186)

    delayed_rows = session.exec(
        select(
            Project.id,
            Project.name,
            Status.status_name,
            Project.end_date,
            Project.progress,
        )
        .join(Status, Project.status_id == Status.id, isouter=True)
        .where(
            *(cond or []),
            Status.status_name.in_(LIFECYCLE_STATUSES),
            Project.end_date.isnot(None),
            Project.end_date < now,
        )
        .order_by(Project.end_date.asc())
    ).all()

    milestone_rows = session.exec(
        select(
            Project.id,
            Project.name,
            Status.status_name,
            Project.end_date,
            Project.progress,
        )
        .join(Status, Project.status_id == Status.id, isouter=True)
        .where(
            *(cond or []),
            Status.status_name.in_(LIFECYCLE_STATUSES),
            Project.end_date.isnot(None),
            Project.end_date >= window_start,
            Project.end_date < window_end,
        )
        .order_by(Project.end_date.asc())
        .limit(60)
    ).all()

    progress = []
    seen: set[int] = set()
    for row in list(delayed_rows) + list(milestone_rows):
        project_id = row[0]
        if project_id in seen:
            continue
        seen.add(project_id)
        end_date = row[3]
        status_name = row[2]
        days_overdue = None
        days_until_due = None
        if end_date is not None:
            aware_end = _as_utc(end_date)
            delta_days = int((aware_end - now).total_seconds() // 86400)
            if delta_days < 0:
                days_overdue = abs(delta_days)
            else:
                days_until_due = delta_days
        progress.append(
            ProjectProgressItem(
                id=project_id,
                name=row[1],
                status_name=status_name,
                progress=float(
                    row[4]
                    if row[4] is not None
                    else STATUS_PROGRESS.get(status_name or "", 0)
                ),
                end_date=end_date,
                days_overdue=days_overdue,
                days_until_due=days_until_due,
            )
        )

    return ProjectAnalyticsSection(
        status_distribution=status_distribution,
        timeline=timeline,
        completed_timeline=completed_timeline,
        progress=progress,
    )


def _build_maintenance(session: Session, filters: DashboardFilters) -> MaintenanceAnalyticsSection:
    project_ids = _scoped_project_ids(session, filters)
    case_cond = []
    if project_ids is not None:
        case_cond.append(
            MaintenanceCase.project_id.in_(project_ids) if project_ids else MaintenanceCase.id == -1
        )
    if filters.maintenance_status:
        case_cond.append(MaintenanceCase.status == filters.maintenance_status)

    status_rows = session.exec(
        select(MaintenanceCase.status, func.count(MaintenanceCase.id))
        .where(*(case_cond or []))
        .group_by(MaintenanceCase.status)
    ).all()
    cases_by_status = [
        ChartDataPoint(name=_enum_str(row[0]), value=float(row[1])) for row in status_rows
    ]

    fault_rows = session.exec(
        select(Project.name, func.count(FaultyEntity.id))
        .join(MaintenanceCase, FaultyEntity.case_id == MaintenanceCase.id)
        .join(Project, MaintenanceCase.project_id == Project.id)
        .where(*(case_cond or []))
        .group_by(Project.name)
        .order_by(func.count(FaultyEntity.id).desc())
        .limit(10)
    ).all()
    fault_by_project = [
        StackedBarGroup(
            group="By Project",
            series=[
                StackedBarSeries(
                    name="Faults",
                    data=[ChartDataPoint(name=row[0], value=float(row[1])) for row in fault_rows],
                )
            ],
        )
    ]

    trend_rows = session.exec(
        select(func.to_char(MaintenanceCase.reported_at, "YYYY-MM"), func.count(MaintenanceCase.id))
        .where(*(case_cond or []))
        .group_by(func.to_char(MaintenanceCase.reported_at, "YYYY-MM"))
        .order_by(func.to_char(MaintenanceCase.reported_at, "YYYY-MM"))
    ).all()
    monthly_trend = [ChartDataPoint(name=row[0], value=float(row[1])) for row in trend_rows]

    return MaintenanceAnalyticsSection(
        cases_by_status=cases_by_status,
        fault_by_project=fault_by_project,
        monthly_trend=monthly_trend,
    )


def _build_product_structure(session: Session, filters: DashboardFilters) -> ProductStructureSection:
    customer_ids = _scoped_customer_ids(session, filters)
    project_ids = _scoped_project_ids(session, filters)

    customer_cond = []
    if customer_ids is not None:
        customer_cond.append(Customer.id.in_(customer_ids) if customer_ids else Customer.id == -1)

    customers = session.exec(
        select(Customer.id, Customer.name).where(*(customer_cond or [])).limit(15)
    ).all()

    tree: List[TreemapNode] = []
    for cid, cname in customers:
        order_cond = [Order.customer_id == cid]
        if filters.order_id:
            order_cond.append(Order.id == filters.order_id)
        orders = session.exec(select(Order.id, Order.order_number).where(*order_cond).limit(10)).all()

        order_nodes: List[TreemapNode] = []
        for oid, onum in orders:
            proj_cond = [Project.order_id == oid]
            if project_ids is not None:
                proj_cond.append(Project.id.in_(project_ids) if project_ids else Project.id == -1)
            projects = session.exec(select(Project.id, Project.name).where(*proj_cond).limit(10)).all()

            project_nodes: List[TreemapNode] = []
            for pid, pname in projects:
                sys_count = session.exec(
                    select(func.count()).select_from(System).where(System.project_id == pid)
                ).one()
                project_nodes.append(
                    TreemapNode(
                        name=pname,
                        value=int(sys_count or 0),
                        entity_type="project",
                        id=pid,
                        href_key="projects",
                    )
                )

            order_nodes.append(
                TreemapNode(
                    name=onum or f"Order {oid}",
                    value=len(project_nodes),
                    entity_type="order",
                    id=oid,
                    href_key="orders",
                    children=project_nodes,
                )
            )

        tree.append(
            TreemapNode(
                name=cname,
                value=len(order_nodes),
                entity_type="customer",
                id=cid,
                href_key="customers",
                children=order_nodes,
            )
        )

    return ProductStructureSection(tree=tree)


def _build_configuration(session: Session, filters: DashboardFilters) -> ConfigurationSection:
    project_ids = _scoped_project_ids(session, filters)
    cond = []
    if filters.configuration_status:
        cond.append(ConfigurationHistory.resolution_type == filters.configuration_status)
    if project_ids is not None:
        cond.append(
            ConfigurationHistory.maintenance_case_id.in_(
                select(MaintenanceCase.id).where(MaintenanceCase.project_id.in_(project_ids))
            )
        )

    month_rows = session.exec(
        select(func.to_char(ConfigurationHistory.change_date, "YYYY-MM"), func.count(ConfigurationHistory.id))
        .where(*(cond or []))
        .group_by(func.to_char(ConfigurationHistory.change_date, "YYYY-MM"))
        .order_by(func.to_char(ConfigurationHistory.change_date, "YYYY-MM"))
    ).all()
    changes_by_month = [ChartDataPoint(name=row[0], value=float(row[1])) for row in month_rows]

    # Resolve real hierarchy names (System - ACU, Harness Antenna, …), not Entity placeholders.
    entity_type_norm = func.lower(Entity.entity_type)
    hierarchy_types = ("system", "subsystem", "module", "unit")
    hierarchy_name = func.coalesce(
        case(
            (entity_type_norm == "system", System.name),
            (entity_type_norm == "subsystem", Subsystem.name),
            (entity_type_norm == "module", Module.name),
            (entity_type_norm == "unit", Unit.name),
        ),
        Entity.display_name,
        Entity.name,
        "Unknown",
    )
    top_rows = session.exec(
        select(hierarchy_name, entity_type_norm, func.count(ConfigurationHistory.id))
        .select_from(ConfigurationHistory)
        .join(Entity, ConfigurationHistory.entity_id == Entity.id)
        .outerjoin(
            System,
            and_(entity_type_norm == "system", Entity.entity_pk == System.id),
        )
        .outerjoin(
            Subsystem,
            and_(entity_type_norm == "subsystem", Entity.entity_pk == Subsystem.id),
        )
        .outerjoin(
            Module,
            and_(entity_type_norm == "module", Entity.entity_pk == Module.id),
        )
        .outerjoin(
            Unit,
            and_(entity_type_norm == "unit", Entity.entity_pk == Unit.id),
        )
        .where(*(cond or []), entity_type_norm.in_(hierarchy_types))
        .group_by(hierarchy_name, entity_type_norm)
        .order_by(func.count(ConfigurationHistory.id).desc())
        .limit(120)
    ).all()
    top_modified = [
        ChartDataPoint(name=row[0], value=float(row[2]), label=str(row[1]))
        for row in top_rows
        if row[0]
    ]

    recent_rows = session.exec(
        select(ConfigurationHistory, Entity, hierarchy_name)
        .join(Entity, ConfigurationHistory.entity_id == Entity.id)
        .outerjoin(
            System,
            and_(entity_type_norm == "system", Entity.entity_pk == System.id),
        )
        .outerjoin(
            Subsystem,
            and_(entity_type_norm == "subsystem", Entity.entity_pk == Subsystem.id),
        )
        .outerjoin(
            Module,
            and_(entity_type_norm == "module", Entity.entity_pk == Module.id),
        )
        .outerjoin(
            Unit,
            and_(entity_type_norm == "unit", Entity.entity_pk == Unit.id),
        )
        .where(*(cond or []), entity_type_norm.in_(hierarchy_types))
        .order_by(ConfigurationHistory.change_date.desc())
        .limit(40)
    ).all()
    recent_timeline = [
        ActivityItem(
            id=hist.id,
            title=(
                resolved_name
                or ent.display_name
                or ent.name
                or hist.new_part_number
                or hist.old_part_number
                or f"Config #{hist.id}"
            ),
            subtitle=hist.reason,
            status=_enum_str(hist.resolution_type),
            timestamp=hist.change_date,
            link_type="maintenance_case",
            link_id=hist.maintenance_case_id or 0,
            entity_type=str(ent.entity_type or "").lower() or None,
        )
        for hist, ent, resolved_name in recent_rows
    ]

    return ConfigurationSection(
        changes_by_month=changes_by_month,
        top_modified_components=top_modified,
        recent_timeline=recent_timeline,
    )


def _build_reliability(session: Session, filters: DashboardFilters) -> ReliabilitySection:
    project_ids = _scoped_project_ids(session, filters)
    fe_cond = []
    if project_ids is not None:
        fe_cond.append(
            MaintenanceCase.project_id.in_(project_ids) if project_ids else MaintenanceCase.id == -1
        )

    top_rows = session.exec(
        select(Component.name, func.count(FaultyEntity.id))
        .join(
            FaultyEntity,
            and_(FaultyEntity.entity_id == Component.id, FaultyEntity.entity_type == EntityType.COMPONENT),
        )
        .join(MaintenanceCase, FaultyEntity.case_id == MaintenanceCase.id)
        .where(*(fe_cond or []))
        .group_by(Component.name)
        .order_by(func.count(FaultyEntity.id).desc())
        .limit(10)
    ).all()
    top_faulty = [ChartDataPoint(name=row[0], value=float(row[1])) for row in top_rows]

    fault_type_rows = session.exec(
        select(FaultyEntity.fault_type, func.count(FaultyEntity.id))
        .join(MaintenanceCase, FaultyEntity.case_id == MaintenanceCase.id)
        .where(*(fe_cond or []))
        .group_by(FaultyEntity.fault_type)
    ).all()
    fault_types = [ChartDataPoint(name=_enum_str(row[0]), value=float(row[1])) for row in fault_type_rows]

    mttr_hours = session.exec(
        select(
            func.avg(func.extract("epoch", FaultyEntity.resolved_at - FaultyEntity.identified_at) / 3600.0)
        )
        .join(MaintenanceCase, FaultyEntity.case_id == MaintenanceCase.id)
        .where(*(fe_cond or []), FaultyEntity.resolved_at.isnot(None))
    ).one()
    mttr_val = float(mttr_hours or 0)

    now = _now()
    month_start = _month_start(now)
    prev_month_start = _month_start(month_start - timedelta(days=1))

    mttr_curr = session.exec(
        select(
            func.avg(func.extract("epoch", FaultyEntity.resolved_at - FaultyEntity.identified_at) / 3600.0)
        )
        .join(MaintenanceCase, FaultyEntity.case_id == MaintenanceCase.id)
        .where(
            *(fe_cond or []),
            FaultyEntity.resolved_at.isnot(None),
            FaultyEntity.resolved_at >= month_start,
        )
    ).one()
    mttr_prev = session.exec(
        select(
            func.avg(func.extract("epoch", FaultyEntity.resolved_at - FaultyEntity.identified_at) / 3600.0)
        )
        .join(MaintenanceCase, FaultyEntity.case_id == MaintenanceCase.id)
        .where(
            *(fe_cond or []),
            FaultyEntity.resolved_at.isnot(None),
            FaultyEntity.resolved_at >= prev_month_start,
            FaultyEntity.resolved_at < month_start,
        )
    ).one()
    mttr_curr_val = float(mttr_curr or 0)
    mttr_prev_val = float(mttr_prev or 0)
    mttr_change = (
        round(mttr_curr_val - mttr_prev_val, 1)
        if mttr_curr_val > 0 and mttr_prev_val > 0
        else None
    )

    # MTBF: average gap (days) between successive *resolved* fault identifications.
    fault_times = session.exec(
        select(FaultyEntity.identified_at)
        .join(MaintenanceCase, FaultyEntity.case_id == MaintenanceCase.id)
        .where(
            *(fe_cond or []),
            FaultyEntity.resolved_at.isnot(None),
            FaultyEntity.identified_at.isnot(None),
        )
        .order_by(FaultyEntity.identified_at.asc())
    ).all()
    gaps: list[float] = []
    gap_ends: list[datetime] = []
    prev_t = None
    for t in fault_times:
        if t is None:
            continue
        aware = _as_utc(t)
        if prev_t is not None:
            gap_days = (aware - prev_t).total_seconds() / 86400.0
            # Ignore sub-day noise from bulk imports / same-session cascades
            if gap_days >= 1.0:
                gaps.append(gap_days)
                gap_ends.append(aware)
        prev_t = aware
    mtbf_val = round(sum(gaps) / len(gaps), 1) if gaps else 0.0

    gaps_curr = [g for g, end in zip(gaps, gap_ends) if end >= month_start]
    gaps_prev = [
        g for g, end in zip(gaps, gap_ends) if prev_month_start <= end < month_start
    ]
    mtbf_curr = sum(gaps_curr) / len(gaps_curr) if gaps_curr else 0.0
    mtbf_prev = sum(gaps_prev) / len(gaps_prev) if gaps_prev else 0.0
    mtbf_change = (
        round(mtbf_curr - mtbf_prev, 1) if mtbf_curr > 0 and mtbf_prev > 0 else None
    )

    return ReliabilitySection(
        top_faulty_components=top_faulty,
        fault_type_distribution=fault_types,
        mttr=GaugeMetric(
            label="MTTR",
            value=round(mttr_val, 1),
            unit="hours",
            max_value=max(mttr_val * 1.25, 24),
            change_value=mttr_change,
        ),
        mtbf=GaugeMetric(
            label="MTBF",
            value=round(mtbf_val, 1),
            unit="days",
            max_value=max(mtbf_val * 1.25, 30),
            change_value=mtbf_change,
        ),
    )


def _build_resources(session: Session, filters: DashboardFilters) -> ResourcesSection:
    project_ids = _scoped_project_ids(session, filters)
    cond = []
    if project_ids is not None:
        cond.append(Project.id.in_(project_ids) if project_ids else Project.id == -1)

    owner_rows = session.exec(
        select(User.id, User.full_name, func.count(Project.id))
        .join(Project, Project.owner_id == User.id, isouter=True)
        .where(*(cond or []))
        .group_by(User.id, User.full_name)
        .order_by(func.count(Project.id).desc())
        .limit(10)
    ).all()
    by_owner = [
        ChartDataPoint(
            name=row[1] or "Unassigned",
            value=float(row[2]),
            id=row[0],
        )
        for row in owner_rows
    ]

    customer_rows = session.exec(
        select(Customer.id, Customer.name, func.count(Project.id))
        .join(Order, Project.order_id == Order.id)
        .join(Customer, Order.customer_id == Customer.id)
        .where(*(cond or []))
        .group_by(Customer.id, Customer.name)
        .order_by(func.count(Project.id).desc())
        .limit(10)
    ).all()
    by_customer = [
        ChartDataPoint(name=row[1], value=float(row[2]), id=row[0]) for row in customer_rows
    ]

    order_rows = session.exec(
        select(Order.id, Order.order_number, func.count(Project.id))
        .join(Project, Project.order_id == Order.id)
        .where(*(cond or []))
        .group_by(Order.id, Order.order_number)
        .order_by(func.count(Project.id).desc())
        .limit(10)
    ).all()
    by_order = [
        ChartDataPoint(name=row[1] or "Unknown", value=float(row[2]), id=row[0])
        for row in order_rows
    ]

    return ResourcesSection(
        projects_by_owner=by_owner,
        projects_by_customer=by_customer,
        projects_by_order=by_order,
    )


def _build_activities(session: Session, filters: DashboardFilters) -> RecentActivitiesSection:
    project_ids = _scoped_project_ids(session, filters)
    case_cond = []
    if project_ids is not None:
        case_cond.append(
            MaintenanceCase.project_id.in_(project_ids) if project_ids else MaintenanceCase.id == -1
        )

    case_rows = session.exec(
        select(MaintenanceCase)
        .where(*(case_cond or []))
        .order_by(MaintenanceCase.reported_at.desc())
        .limit(5)
    ).all()
    maintenance_cases = [
        ActivityItem(
            id=c.id,
            title=c.case_number,
            subtitle=c.project_name,
            status=_enum_str(c.status),
            timestamp=c.reported_at,
            link_type="maintenance_case",
            link_id=c.id,
        )
        for c in case_rows
    ]

    config_rows = session.exec(
        select(ConfigurationHistory).order_by(ConfigurationHistory.change_date.desc()).limit(5)
    ).all()
    configuration_changes = [
        ActivityItem(
            id=r.id,
            title=r.new_part_number or r.old_part_number or f"Change #{r.id}",
            status=_enum_str(r.resolution_type),
            timestamp=r.change_date,
            link_type="maintenance_case",
            link_id=r.maintenance_case_id or 0,
        )
        for r in config_rows
    ]

    proj_cond = []
    if project_ids is not None:
        proj_cond.append(Project.id.in_(project_ids) if project_ids else Project.id == -1)
    project_rows = session.exec(
        select(Project).where(*proj_cond).order_by(Project.created_at.desc()).limit(5)
    ).all()
    projects = [
        ActivityItem(
            id=p.id,
            title=p.name,
            timestamp=p.created_at,
            link_type="project",
            link_id=p.id,
        )
        for p in project_rows
    ]

    fault_rows = session.exec(
        select(FaultyEntity)
        .join(MaintenanceCase, FaultyEntity.case_id == MaintenanceCase.id)
        .where(*(case_cond or []), FaultyEntity.status == FaultyEntityStatus.CONFIRMED_FAULTY)
        .order_by(FaultyEntity.identified_at.desc())
        .limit(5)
    ).all()
    fault_confirmations = [
        ActivityItem(
            id=f.id,
            title=f"{_enum_str(f.entity_type)} #{f.entity_id}",
            status=_enum_str(f.status),
            timestamp=f.identified_at,
            link_type="maintenance_case",
            link_id=f.case_id,
        )
        for f in fault_rows
    ]

    user_activities: List[ActivityItem] = []
    history_rows = session.exec(
        select(EntityStatusHistory).order_by(EntityStatusHistory.changed_at.desc()).limit(3)
    ).all()
    for h in history_rows:
        user_activities.append(
            ActivityItem(
                id=h.id,
                title="Status change",
                timestamp=h.changed_at,
                link_type="entity",
                link_id=h.entity_id or 0,
            )
        )
    action_rows = session.exec(
        select(MaintenanceAction).order_by(MaintenanceAction.performed_at.desc()).limit(3)
    ).all()
    for a in action_rows:
        user_activities.append(
            ActivityItem(
                id=a.id,
                title=f"Maintenance action: {_enum_str(a.action_type)}",
                timestamp=a.performed_at,
                link_type="faulty_entity",
                link_id=a.faulty_entity_id,
            )
        )
    user_activities.sort(key=lambda x: x.timestamp, reverse=True)
    user_activities = user_activities[:5]

    return RecentActivitiesSection(
        maintenance_cases=maintenance_cases,
        configuration_changes=configuration_changes,
        projects=projects,
        fault_confirmations=fault_confirmations,
        user_activities=user_activities,
    )


def build_executive_dashboard(session: Session, filters: DashboardFilters) -> ExecutiveDashboardResponse:
    return ExecutiveDashboardResponse(
        kpis=_build_kpis(session, filters),
        projects=_build_projects(session, filters),
        maintenance=_build_maintenance(session, filters),
        product_structure=_build_product_structure(session, filters),
        configuration=_build_configuration(session, filters),
        reliability=_build_reliability(session, filters),
        resources=_build_resources(session, filters),
        activities=_build_activities(session, filters),
        generated_at=_now(),
    )
