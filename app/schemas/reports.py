from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ReportType(str, Enum):
    BUILD_HISTORY_DOSSIER = "build_history_dossier"
    MAINTENANCE_HISTORY_DOSSIER = "maintenance_history_dossier"
    HIERARCHY = "hierarchy"
    INVENTORY = "inventory"
    MAINTENANCE = "maintenance"
    EXECUTIVE = "executive"


class HierarchyReportMode(str, Enum):
    BHD = "bhd"
    MMHD = "mmhd"


class ReportRegisterRequest(BaseModel):
    report_type: ReportType
    report_title: str
    filters: Optional[Dict[str, Any]] = None
    file_name: Optional[str] = None
    checksum: Optional[str] = None
    software_version: Optional[str] = "0.1.0"
    report_uuid: Optional[UUID] = None


class ReportRegisterResponse(BaseModel):
    id: int
    report_uuid: str
    report_type: str
    report_title: str
    generated_by: Optional[int] = None
    generated_by_name: Optional[str] = None
    generated_at: datetime
    filters_json: Optional[str] = None
    file_name: Optional[str] = None
    checksum: Optional[str] = None
    software_version: str
    verify_payload: str


class ReportVerifyResponse(BaseModel):
    valid: bool
    report_uuid: str
    report_type: Optional[str] = None
    report_title: Optional[str] = None
    generated_by: Optional[int] = None
    generated_by_name: Optional[str] = None
    generated_at: Optional[datetime] = None
    filters_json: Optional[str] = None
    file_name: Optional[str] = None
    checksum: Optional[str] = None
    software_version: Optional[str] = None
    message: Optional[str] = None


class ReportHistoryItem(BaseModel):
    id: int
    report_uuid: str
    report_type: str
    report_title: str
    generated_by: Optional[int] = None
    generated_by_name: Optional[str] = None
    generated_at: datetime
    file_name: Optional[str] = None
    checksum: Optional[str] = None
    software_version: str


class ReportHistoryListResponse(BaseModel):
    items: List[ReportHistoryItem]
    total: int
    page: int
    page_size: int


# --- Shared dossier building blocks ---


class KeyValueItem(BaseModel):
    label: str
    value: Optional[str] = None


class AttachmentItem(BaseModel):
    id: int
    file_name: str
    mime_type: Optional[str] = None
    attachment_type: Optional[str] = None
    description: Optional[str] = None
    uploaded_at: Optional[datetime] = None


class ImageItem(BaseModel):
    url: Optional[str] = None
    caption: Optional[str] = None
    entity_name: Optional[str] = None


class TimelineEvent(BaseModel):
    event_type: str
    title: str
    description: Optional[str] = None
    occurred_at: Optional[datetime] = None
    actor: Optional[str] = None


class HierarchyEntityNode(BaseModel):
    entity_type: str
    id: int
    name: str
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    original_part_number: Optional[str] = None
    original_serial_number: Optional[str] = None
    installation_date: Optional[datetime] = None
    installed_by: Optional[str] = None
    configuration_item: Optional[str] = None
    current_status: Optional[str] = None
    previous_status: Optional[str] = None
    created_date: Optional[datetime] = None
    modified_date: Optional[datetime] = None
    description: Optional[str] = None
    picture_url: Optional[str] = None
    sku: Optional[str] = None
    is_current_install: Optional[bool] = None
    replacement_sequence: Optional[int] = None
    replaced_at: Optional[datetime] = None
    was_replaced: Optional[bool] = None
    children: List["HierarchyEntityNode"] = Field(default_factory=list)


HierarchyEntityNode.model_rebuild()


class HierarchyReportResponse(BaseModel):
    mode: str
    project: Dict[str, Any]
    hierarchy: List[HierarchyEntityNode] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)


class ConfigHistoryItem(BaseModel):
    id: int
    change_type: Optional[str] = None
    fault_type: Optional[str] = None
    resolution_type: Optional[str] = None
    old_part_number: Optional[str] = None
    old_serial_number: Optional[str] = None
    new_part_number: Optional[str] = None
    new_serial_number: Optional[str] = None
    change_date: Optional[datetime] = None
    installation_date: Optional[datetime] = None
    removal_date: Optional[datetime] = None
    reason: Optional[str] = None
    corrective_action: Optional[str] = None
    remarks: Optional[str] = None
    performed_by: Optional[str] = None
    work_order_number: Optional[str] = None


class BuildHistoryDossierResponse(BaseModel):
    project: Dict[str, Any]
    customer: Optional[Dict[str, Any]] = None
    order: Optional[Dict[str, Any]] = None
    delivery: Optional[Dict[str, Any]] = None
    hierarchy: List[HierarchyEntityNode] = Field(default_factory=list)
    configuration_history: List[ConfigHistoryItem] = Field(default_factory=list)
    timeline: List[TimelineEvent] = Field(default_factory=list)
    images: List[ImageItem] = Field(default_factory=list)
    attachments: List[AttachmentItem] = Field(default_factory=list)
    signatures: Dict[str, Optional[str]] = Field(
        default_factory=lambda: {
            "prepared_by": None,
            "reviewed_by": None,
            "approved_by": None,
        }
    )


class MaintenanceActionItem(BaseModel):
    id: int
    action_type: Optional[str] = None
    outcome: Optional[str] = None
    notes: Optional[str] = None
    performed_by: Optional[str] = None
    performed_at: Optional[datetime] = None
    duration: Optional[str] = None
    replacement_entity_type: Optional[str] = None
    replacement_entity_id: Optional[int] = None


class FaultyEntityItem(BaseModel):
    id: int
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    fault_type: Optional[str] = None
    fault_description: Optional[str] = None
    status: Optional[str] = None
    resolution_type: Optional[str] = None
    system: Optional[str] = None
    subsystem: Optional[str] = None
    module: Optional[str] = None
    unit: Optional[str] = None
    component: Optional[str] = None
    actions: List[MaintenanceActionItem] = Field(default_factory=list)


class MaintenanceDeliveryItem(BaseModel):
    id: int
    delivery_type: Optional[str] = None
    status: Optional[str] = None
    delivered_by: Optional[str] = None
    received_by: Optional[str] = None
    notes: Optional[str] = None
    delivered_at: Optional[datetime] = None
    returned_date: Optional[str] = None
    received_date: Optional[str] = None
    acceptance: Optional[str] = None


class MaintenanceHistoryDossierResponse(BaseModel):
    case: Dict[str, Any]
    fault: Optional[Dict[str, Any]] = None
    faulty_entities: List[FaultyEntityItem] = Field(default_factory=list)
    replacements: List[ConfigHistoryItem] = Field(default_factory=list)
    timeline: List[TimelineEvent] = Field(default_factory=list)
    deliveries: List[MaintenanceDeliveryItem] = Field(default_factory=list)
    attachments: List[AttachmentItem] = Field(default_factory=list)
    signatures: Dict[str, Optional[str]] = Field(
        default_factory=lambda: {
            "prepared_by": None,
            "reviewed_by": None,
            "approved_by": None,
        }
    )


class InventoryReportItem(BaseModel):
    id: int
    name: str
    inventory_type: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    quantity: Optional[int] = None
    location: Optional[str] = None
    status_name: Optional[str] = None
    sku: Optional[str] = None
    oem_name: Optional[str] = None
    entity_id: Optional[int] = None
    configuration_item: Optional[str] = None
    added_date: Optional[datetime] = None


class InventoryReportResponse(BaseModel):
    mode: str
    items: List[InventoryReportItem] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    placeholders: List[str] = Field(default_factory=list)


class MaintenanceSummaryResponse(BaseModel):
    summary: Dict[str, Any] = Field(default_factory=dict)
    cases: List[Dict[str, Any]] = Field(default_factory=list)
    by_status: List[Dict[str, Any]] = Field(default_factory=list)
    by_fault_type: List[Dict[str, Any]] = Field(default_factory=list)
    engineer_workload: List[Dict[str, Any]] = Field(default_factory=list)
    aging: List[Dict[str, Any]] = Field(default_factory=list)
    monthly_trends: List[Dict[str, Any]] = Field(default_factory=list)
    mttr_hours: Optional[float] = None
    placeholders: List[str] = Field(default_factory=list)


class ExecutiveReportResponse(BaseModel):
    dashboard: Dict[str, Any]
    financial: Dict[str, Any] = Field(default_factory=dict)
    placeholders: List[str] = Field(default_factory=list)
