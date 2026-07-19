from sqlmodel import SQLModel, Field
from pydantic import ConfigDict
from app.models.base import (MaintenanceCaseBase, FaultyEntityBase, MaintenanceActionBase, MaintenanceDeliveryBase)
from typing import List, Optional
from app.models.base import EntityType, FaultType, CaseStatus, FaultyEntityStatus, ResolutionType, ActionOutcome, DeliveryStatus
from .schemas import EntityRead, MaintenanceUserRead
from datetime import datetime, datetime, timezone


# =============================================================================
# B. NEW SCHEMAS
# =============================================================================

class AncestorNode(SQLModel):
    """One level in the upward ancestry chain."""
    entity_type:             str # like Project, System, Subsystem, Module, Unit, Component
    entity_id:               int
    entity_name:             Optional[str]= None   # like SDLS1 (System), AOCS (subsystem), or TMTC (Module) or FPGA Card (unit), Rectifier (component)
    entity_PartNumber:       Optional[str] = None   # human-readable name / PN
    entity_SerialNumber:     Optional[str] = None

class DescendantNode(SQLModel):
    """One entity in the downward subtree."""
    entity_type:             str # like Project, System, Subsystem, Module, Unit, Component
    entity_id:               int
    entity_name:             Optional[str] = None   # like SDLS1 (System), AOCS (subsystem), or TMTC (Module) or FPGA Card (unit), Rectifier (component)
    entity_PartNumber:       Optional[str] = None   # human-readable name / PN
    entity_SerialNumber:     Optional[str] = None
    parent_ID:               Optional[int] = None   # immediate parent in the hierarchy (None for the matched entity itself)
    parent_type:             Optional[EntityType] = None
    parent_name:             Optional[str] = None   # for FE label; optional but saves a lookup
    depth:                   int = 0                # 0 = the entity itself, 1 = direct child, …
    hierarchy_parent_entity_id: Optional[int] = None
    hierarchy_parent_entity_type: Optional[EntityType] = None
class EntityLookupRead(SQLModel):
    """
    Response for GET /entities/lookup-by-SN/{serial_number}/
    Returns the matched entity plus its full ancestry (up to customer)
    and every descendant entity (down to components).
    """
    matched_entity_type: str
    matched_entity_id:   int
    matched_label:       Optional[str] = None
    matched_entity_serialNumber : Optional[str] = None
    matched_entity_PartNumber : Optional[str] = None


    # Upward chain — ordered from the matched entity to Customer
    ancestors: List[AncestorNode] = []

    # Downward tree — every child, grandchild, … leaf entity
    descendants: List[DescendantNode] = []

    # Convenience: project / order / customer extracted from ancestors
    project_id:    Optional[int] = None
    project_name:  Optional[str] = None
    order_id:      Optional[int] = None
    order_ref:     Optional[str] = None
    customer_id:   Optional[int] = None
    customer_name: Optional[str] = None

class FaultyEntityRead(FaultyEntityBase):
    id:                      int
    case_id:                 int
    identified_by:           Optional[int]                = None
    identified_by_user:      Optional[MaintenanceUserRead]           = None
    parent_faulty_entity_id: Optional[int]                = None
    actions:                 List["MaintenanceActionRead"] = []

    model_config = ConfigDict(from_attributes=True)


class SuspectChildrenPayload(SQLModel):
    """
    POST /maintenance-cases/{case_id}/suspect-children/
    Body: identify a mid-hierarchy faulty entity; the endpoint walks DOWN and
    creates provisional UNDER_INSPECTION faulty-entity rows for every descendant.
    """
    entity_type:       EntityType
    entity_id:         int
    fault_type:        FaultType
    entity_status:     Optional[FaultyEntityStatus] = FaultyEntityStatus.SUSPECTED
    fault_description: Optional[str]   = None
    entity_name:       Optional[str]   = None  # for FE label; optional but saves a lookup
    serial_number:     Optional[str]   = None
    part_number:       Optional[str]   = None

class SuspectChildrenRead(SQLModel):
    """Response for the suspect-children endpoint."""
    parent_faulty_entity_id: int
    suspect_entities_created: List[FaultyEntityRead] = []
    total_suspects:           int
    message:                  str

class ConfirmFaultPayload(SQLModel):
    """
    POST /maintenance-cases/{case_id}/confirm-fault/
    Body: the engineer has traced the fault to one exact entity.
    All sibling subtrees under the same parent are cleared (provisional rows
    deleted; no permanent log left for healthy entities).
    """
    confirmed_entity_type:  EntityType
    confirmed_entity_id:    int
    fault_type:             FaultType       = FaultType.UNCLASSIFIED
    fault_description:      Optional[str]   = None
    # The parent faulty-entity row that was created during suspect-children.
    # Required so the system knows which sibling rows to clear.
    parent_faulty_entity_id: int

class ConfirmFaultRead(SQLModel):
    """Response for the confirm-fault endpoint."""
    confirmed_faulty_entity: FaultyEntityRead
    cleared_suspect_count:   int
    message:                 str


# =============================================================================
# 1. MAINTENANCE CASE
# =============================================================================
# A top-level fault event opened against a delivered project.
# One project can accumulate many cases over its lifetime.
# =============================================================================


class MaintenanceCaseCreate(MaintenanceCaseBase):
    """
    POST /maintenance-cases/
    project_id and reported_by are supplied by the caller.
    case_number is auto-generated server-side; do not send it.
    """
    project_id:  int
    reported_by: Optional[int] = None
    project_name:     Optional[str]                 = None


class MaintenanceCaseRead(MaintenanceCaseBase):
    """
    Full case response, including nested faulty entities and deliveries.
    """
    id:               int
    case_number:      str
    project_id:       int
    reported_by:      Optional[int]                 = None
    reported_by_user: Optional[MaintenanceUserRead]            = None
    faulty_entities:  List["FaultyEntityRead"]       = []
    deliveries:       List["MaintenanceDeliveryRead"] = []

    model_config = ConfigDict(from_attributes=True)

class MaintenanceCaseUpdate(SQLModel):
    """
    PUT /maintenance-cases/{id}/
    All fields optional — only supplied fields are patched.
    """
    status:           Optional[CaseStatus] = None
    resolution_notes: Optional[str]        = None
    closed_at:        Optional[datetime]   = None

# ── Schemas ──────────────────────────────────────────────────────────────────

# =============================================================================
# 2. FAULTY ENTITY
# =============================================================================
# Polymorphic record pointing to any level of the hierarchy
# (project / system / subsystem / module / unit / component).
# parent_faulty_entity_id enables the fault cascade chain to be explicit:
#   component FE → parent unit FE → parent module FE → ...
# =============================================================================

# ── Schemas ──────────────────────────────────────────────────────────────────

class FaultyEntityCreate(FaultyEntityBase):
    """
    POST /maintenance-cases/{case_id}/faulty-entities/
    identified_by defaults to current_user server-side.
    """
    identified_by:           Optional[int] = None
    parent_faulty_entity_id: Optional[int] = None


class FaultyEntityUpdate(SQLModel):
    """
    PUT /faulty-entities/{id}/
    Use this for status transitions, resolution, and reclassification.
    """
    fault_type:        Optional[FaultType]          = None
    fault_description: Optional[str]                = None
    status:            Optional[FaultyEntityStatus] = None
    resolution_type:   Optional[ResolutionType]     = None
    resolved_at:       Optional[datetime]           = None
    old_part_number:   Optional[str]                = None
    new_part_number:   Optional[str]                = None
    old_serial_number: Optional[str]                = None
    new_serial_number: Optional[str]                = None
    remarks:           Optional[str]                = None


class FaultyEntityCascadeCreate(SQLModel):
    """
    POST /maintenance-cases/{case_id}/cascade-fault/
    Identifies the root faulty entity; the endpoint walks UP the hierarchy
    and auto-creates parent FaultyEntity rows for each ancestor.
    """
    root_entity_type:  EntityType
    root_entity_id:    int
    fault_type:        FaultType  = FaultType.UNCLASSIFIED
    fault_description: Optional[str] = None

class FaultyEntityCascadeRead(SQLModel):
    """Response returned by the cascade-fault endpoint."""
    created_faulty_entities:  List[FaultyEntityRead]
    total_levels_cascaded:    int
    message:                  str


# =============================================================================
# 3. MAINTENANCE ACTION
# =============================================================================
# Individual audit-log entries for every action taken on a faulty entity.
# Includes: inspection, repair, replacement, testing, cleaning, recalibration.
# On replacement, replacement_entity_id records the new entity that took over.
# =============================================================================

# ── Schemas ──────────────────────────────────────────────────────────────────

class MaintenanceActionCreate(MaintenanceActionBase):
    """POST /faulty-entities/{faulty_entity_id}/actions/"""
    faulty_entity_id: int
    performed_by: Optional[int] = None
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))

class MaintenanceActionRead(MaintenanceActionBase):
    id:                      int
    faulty_entity_id:        int
    performed_by:            Optional[int]     = None
    performed_by_user:       Optional[MaintenanceUserRead] = None
    replacement_entity_id:   Optional[int]     = None
    replacement_entity_type: Optional[EntityType] = None

    model_config = ConfigDict(from_attributes=True)

class MaintenanceActionUpdate(SQLModel):
    """PUT /maintenance-actions/{id}/"""
    notes:   Optional[str]           = None
    outcome: Optional[ActionOutcome] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))



# =============================================================================
# 4. MAINTENANCE DELIVERY
# =============================================================================
# Records every delivery event linked to a case:
#   - initial_delivery  → first time product goes to customer (optional use)
#   - re_delivery       → product returned after repair / replacement
#   - partial_re_delivery → only some entities were resolved and re-sent
# Confirming a delivery auto-closes the parent case when status = resolved.
# =============================================================================


# ── Schemas ──────────────────────────────────────────────────────────────────

class MaintenanceDeliveryCreate(MaintenanceDeliveryBase):
    """POST /maintenance-cases/{case_id}/deliveries/"""
    delivered_by: Optional[int] = None

class MaintenanceDeliveryRead(MaintenanceDeliveryBase):
    id:                int
    case_id:           int
    delivered_by:      Optional[int]     = None
    delivered_by_user: Optional[MaintenanceUserRead] = None
    created_at:        datetime

    model_config = ConfigDict(from_attributes=True)

class MaintenanceDeliveryUpdate(SQLModel):
    """PUT /maintenance-deliveries/{id}/"""
    status:       Optional[DeliveryStatus] = None
    delivered_at: Optional[datetime]       = None
    received_by:  Optional[str]            = None
    notes:        Optional[str]            = None



class ConfigurationHistoryCreate(SQLModel):

    entity_id: int

    maintenance_case_id: Optional[int] = None

    faulty_entity_id: Optional[int] = None

    performed_by: int

    approved_by: Optional[int] = None

    verified_by: Optional[int] = None

    installation_date: Optional[datetime] = None

    removal_date: Optional[datetime] = None

    fault_type: Optional[FaultType] = None

    resolution_type: ResolutionType

    old_part_number: Optional[str] = None
    new_part_number: Optional[str] = None

    old_serial_number: Optional[str] = None
    new_serial_number: Optional[str] = None

    old_revision: Optional[str] = None
    new_revision: Optional[str] = None

    old_batch_number: Optional[str] = None
    new_batch_number: Optional[str] = None

    operating_hours: Optional[float] = None

    operating_cycles: Optional[int] = None

    work_order_number: Optional[str] = None

    reason: Optional[str] = None

    corrective_action: Optional[str] = None

    remarks: Optional[str] = None

class ConfigurationHistoryUpdate(SQLModel):

    approved_by: Optional[int] = None

    verified_by: Optional[int] = None

    installation_date: Optional[datetime] = None

    removal_date: Optional[datetime] = None

    work_order_number: Optional[str] = None

    reason: Optional[str] = None

    corrective_action: Optional[str] = None

    remarks: Optional[str] = None

class ConfigurationHistoryRead(SQLModel):

    id: int

    entity_id: int

    maintenance_case_id: Optional[int] = None

    faulty_entity_id: Optional[int] = None

    performed_by: int
    approved_by: Optional[int] = None
    verified_by: Optional[int] = None

    change_date: datetime

    installation_date: Optional[datetime] = None

    removal_date: Optional[datetime] = None

    fault_type: Optional[FaultType] = None

    resolution_type: ResolutionType

    old_part_number: Optional[str] = None
    new_part_number: Optional[str] = None

    old_serial_number: Optional[str] = None
    new_serial_number: Optional[str] = None

    old_revision: Optional[str] = None
    new_revision: Optional[str] = None

    old_batch_number: Optional[str] = None
    new_batch_number: Optional[str] = None

    operating_hours: Optional[float] = None

    operating_cycles: Optional[int] = None

    work_order_number: Optional[str] = None

    reason: Optional[str] = None

    corrective_action: Optional[str] = None

    remarks: Optional[str] = None

    entity: Optional["EntityRead"] = None

    maintenance_case: Optional["MaintenanceCaseRead"] = None

    # performed_by_user: Optional["UserRead"] = None

    # approved_by_user: Optional["UserRead"] = None

    # verified_by_user: Optional["UserRead"] = None

    class Config:
        from_attributes = True


class AdminHierarchyReplacePayload(SQLModel):
    project_id: int
    entity_type: EntityType
    entity_id: int
    new_part_number: str
    new_serial_number: Optional[str] = None
    notes: Optional[str] = None
    inventory_item_id: Optional[int] = None
    inventory_instance_id: Optional[int] = None


class AdminHierarchyReplaceRead(SQLModel):
    case_id: int
    faulty_entity_id: int
    configuration_history_id: Optional[int] = None
    old_part_number: Optional[str] = None
    new_part_number: str
    new_entity_id: int
    old_entity_id: int
