from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class KpiMetric(BaseModel):
    key: str
    label: str
    value: int
    change_percent: Optional[float] = None


class ChartDataPoint(BaseModel):
    name: str
    value: float
    label: Optional[str] = None
    id: Optional[int] = None


class StackedBarSeries(BaseModel):
    name: str
    data: List[ChartDataPoint]


class StackedBarGroup(BaseModel):
    group: str
    series: List[StackedBarSeries]


class ProjectProgressItem(BaseModel):
    id: int
    name: str
    progress: float
    status_name: Optional[str] = None


class TreemapNode(BaseModel):
    name: str
    value: int
    entity_type: str
    id: Optional[int] = None
    href_key: Optional[str] = None
    children: List[TreemapNode] = Field(default_factory=list)


class GaugeMetric(BaseModel):
    label: str
    value: float
    unit: str
    max_value: float = 100


class ActivityItem(BaseModel):
    id: int
    title: str
    subtitle: Optional[str] = None
    status: Optional[str] = None
    timestamp: datetime
    link_type: str
    link_id: int


class ExecutiveKpisSection(BaseModel):
    metrics: List[KpiMetric]


class ProjectAnalyticsSection(BaseModel):
    status_distribution: List[ChartDataPoint]
    timeline: List[ChartDataPoint]
    progress: List[ProjectProgressItem]


class MaintenanceAnalyticsSection(BaseModel):
    cases_by_status: List[ChartDataPoint]
    fault_by_project: List[StackedBarGroup]
    monthly_trend: List[ChartDataPoint]


class ProductStructureSection(BaseModel):
    tree: List[TreemapNode]


class ConfigurationSection(BaseModel):
    changes_by_month: List[ChartDataPoint]
    top_modified_components: List[ChartDataPoint]
    recent_timeline: List[ActivityItem]


class ReliabilitySection(BaseModel):
    top_faulty_components: List[ChartDataPoint]
    fault_type_distribution: List[ChartDataPoint]
    mttr: GaugeMetric
    mtbf: GaugeMetric


class ResourcesSection(BaseModel):
    projects_by_owner: List[ChartDataPoint]
    projects_by_customer: List[ChartDataPoint]
    projects_by_order: List[ChartDataPoint]


class RecentActivitiesSection(BaseModel):
    maintenance_cases: List[ActivityItem]
    configuration_changes: List[ActivityItem]
    projects: List[ActivityItem]
    fault_confirmations: List[ActivityItem]
    user_activities: List[ActivityItem]


class ExecutiveDashboardResponse(BaseModel):
    kpis: ExecutiveKpisSection
    projects: ProjectAnalyticsSection
    maintenance: MaintenanceAnalyticsSection
    product_structure: ProductStructureSection
    configuration: ConfigurationSection
    reliability: ReliabilitySection
    resources: ResourcesSection
    activities: RecentActivitiesSection
    generated_at: datetime
