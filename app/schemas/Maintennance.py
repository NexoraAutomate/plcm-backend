from sqlmodel import SQLModel, Field
from pydantic import ConfigDict
from app.models.base import (MaintenanceCaseBase, FaultyEntityBase, MaintenanceActionBase, MaintenanceDeliveryBase, OemWarrantyClaimBase)
from typing import List, Optional
from app.models.base import EntityType, FaultType, CaseStatus, FaultyEntityStatus, ResolutionType, ActionOutcome, DeliveryStatus
from .schemas import EntityRead, MaintenanceUserRead
from datetime import date, datetime, timezone


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


class ProductFaultHistoryItem(FaultyEntityRead):
    """Faulty-entity row enriched with the hierarchy OEM at lookup time."""
    oem_name: Optional[str] = None
    same_oem: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


class ProductFaultHistoryRead(SQLModel):
    """
    Aggregate fault history for a product (part number), split by OEM.
    Used by maintenance entity stocking detail → Fault History tab.
    """
    part_number: str
    current_oem: Optional[str] = None
    same_oem_fault_count: int = 0
    different_oem_fault_count: int = 0
    unknown_oem_fault_count: int = 0
    total_fault_count: int = 0
    last_fault_at: Optional[datetime] = None
    last_fault_id: Optional[int] = None
    history: List[ProductFaultHistoryItem] = []


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
    # Soft-block when order production support has ended
    support_override_reason: Optional[str] = None


class ProductionSupportPreview(SQLModel):
    """GET /projects/{id}/production-support/ — used before opening a case."""
    project_id: int
    order_id: Optional[int] = None
    production_support_date: Optional[date] = None
    in_production_support: Optional[bool] = None
    requires_override: bool = False


class OccurrenceAttachmentIn(SQLModel):
    """Named attachment on Occurrence Report."""
    display_name: str
    file_id: Optional[int] = None
    category: Optional[str] = None
    # Alias accepted by service via dict: name
    name: Optional[str] = None


class OccurrenceOfficerIn(SQLModel):
    """Field officer on Occurrence Report."""
    user_id: Optional[int] = None
    guest_name: Optional[str] = None
    role_onsite: str
    contact: Optional[str] = None


class OccurrenceAttachmentRead(SQLModel):
    id: int
    case_id: int
    display_name: str
    file_id: Optional[int] = None
    category: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OccurrenceOfficerRead(SQLModel):
    id: int
    case_id: int
    user_id: Optional[int] = None
    guest_name: Optional[str] = None
    role_onsite: str
    contact: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OnsiteOutcomePayload(SQLModel):
    """POST /maintenance-cases/{id}/onsite-outcome/ — Occurrence Report (additive)."""
    onsite_outcome: str
    onsite_soft_fix_method: Optional[str] = None
    notes: Optional[str] = None
    # When soft_fix: also resolve the primary/open faulty entity as soft_fixed
    resolve_soft_fixed: bool = True
    # When no_fault_found: Yes on confirm modal → resolve/close as NFF
    confirm_close_nff: bool = False
    occurrence_date: Optional[datetime] = None
    fault_type: Optional[str] = None
    confirmation_channel: Optional[str] = None
    confirmation_reference: Optional[str] = None
    attachments: Optional[List[OccurrenceAttachmentIn]] = None
    officers: Optional[List[OccurrenceOfficerIn]] = None


class ReturnedUnitRead(SQLModel):
    """Maintenance-linked inventory rework / returned faulty unit."""
    id: int
    maintenance_case_id: Optional[int] = None
    faulty_entity_id: Optional[int] = None
    investigating_pd_id: Optional[int] = None
    investigating_pd_name: Optional[str] = None
    assigned_ie_id: Optional[int] = None
    assigned_ie_name: Optional[str] = None
    project_id: int
    inventory_id: int
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    status: str
    stage: str
    disposition: Optional[str] = None
    notes: Optional[str] = None
    opened_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    reception_date: Optional[datetime] = None
    warranty_expires_at: Optional[datetime] = None
    warranty_active: Optional[bool] = None
    oem_name: Optional[str] = None
    is_track_b_terminal: bool = False
    discarded: bool = False

    model_config = ConfigDict(from_attributes=True)


class AssignInvestigatingPdPayload(SQLModel):
    pd_user_id: int


class TrackBReceptionPayload(SQLModel):
    reception_date: Optional[datetime] = None
    notes: Optional[str] = None


class TrackBAssignIePayload(SQLModel):
    ie_user_id: int


class TrackBNotesPayload(SQLModel):
    notes: Optional[str] = None


class TrackBDispositionPayload(SQLModel):
    """outcome: repairable | warranty | discard | reusable"""

    outcome: str
    notes: Optional[str] = None


class TrackBPdRepairDecisionPayload(SQLModel):
    decision: str  # approve | reject
    reject_reason: Optional[str] = None


class ReplacementRequestCreate(SQLModel):
    """POST /maintenance-cases/{id}/replacement-requests/"""

    faulty_entity_id: Optional[int] = None
    notes: Optional[str] = None


class ReplacementRequestAssignMePayload(SQLModel):
    """POST .../replacement-requests/{id}/assign-me/"""

    assigned_me_id: int


class ReplacementRequestReservePayload(SQLModel):
    """POST .../replacement-requests/{id}/reserve/"""

    inventory_id: Optional[int] = None
    inventory_instance_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    target_entity_type: Optional[str] = None
    target_entity_id: Optional[int] = None
    notes: Optional[str] = None


class ReplacementRequestPdDecisionPayload(SQLModel):
    """POST .../replacement-requests/{id}/pd-decision/"""

    decision: str  # approve | reject
    reject_reason: Optional[str] = None


class ReplacementRequestImIssuePayload(SQLModel):
    """POST .../replacement-requests/{id}/im-issue/"""

    signature_type: str  # DIGITAL | HARD_COPY
    signature_payload: Optional[str] = None
    notes: Optional[str] = None


class ReplacementRequestAitAttachmentPayload(SQLModel):
    """POST .../replacement-requests/{id}/ait/attachments/"""

    display_name: str
    file_id: Optional[int] = None
    occurrence_attachment_id: Optional[int] = None


class ReplacementRequestAitDecisionPayload(SQLModel):
    """POST .../replacement-requests/{id}/ait/pd-decision/"""

    decision: str  # approve | reject
    reject_reason: Optional[str] = None


class ReplacementRequestAbortPayload(SQLModel):
    """POST .../replacement-requests/{id}/abort/ — RA-017"""

    reason: str


class ReplacementRequestReservationRead(SQLModel):
    id: int
    replacement_request_id: int
    inventory_reservation_id: Optional[int] = None
    inventory_instance_id: Optional[int] = None
    serial_number: Optional[str] = None
    part_number: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ReplacementRequestAitAttachmentRead(SQLModel):
    id: int
    replacement_request_id: int
    display_name: str
    file_id: Optional[int] = None
    occurrence_attachment_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ReplacementRequestRead(SQLModel):
    id: int
    case_id: int
    faulty_entity_id: Optional[int] = None
    faulty_entity_type: Optional[str] = None
    faulty_entity_ref_id: Optional[int] = None
    requested_by_id: int
    assigned_me_id: Optional[int] = None
    assigned_me_name: Optional[str] = None
    status: str
    pd_decision: Optional[str] = None
    reject_reason: Optional[str] = None
    abort_reason: Optional[str] = None
    issued_serial: Optional[str] = None
    issued_instance_id: Optional[int] = None
    issued_at: Optional[datetime] = None
    shortage_held: bool = False
    red_notified_at: Optional[datetime] = None
    quarantined_instance_id: Optional[int] = None
    ait_decision: Optional[str] = None
    ait_reject_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    reservations: List[ReplacementRequestReservationRead] = []
    ait_attachments: List[ReplacementRequestAitAttachmentRead] = []

    model_config = ConfigDict(from_attributes=True)


class DualTrackBoardRead(SQLModel):
    """GET /maintenance-cases/{id}/dual-track/ — Track A + Track B skeleton."""

    case_id: int
    track_a: Optional[ReplacementRequestRead] = None
    track_a_status: Optional[str] = None
    track_b_status: Optional[str] = None  # idle | MHD Track B spine stage
    track_b_rework_id: Optional[int] = None
    track_b_reception_date: Optional[datetime] = None
    track_b_discarded: bool = False
    track_b_terminal: bool = False


class MaintenanceAssignedWorkRead(SQLModel):
    """GET /maintenance-assignments/mine/ — personal MMHD dual-track inbox row."""

    id: str
    track: str  # a | b
    task_type: str
    case_id: int
    case_number: Optional[str] = None
    replacement_request_id: Optional[int] = None
    rework_id: Optional[int] = None
    status: str
    status_label: str
    lifecycle: str = "needs_action"  # needs_action | in_progress | closed
    needs_action: bool = False
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    assigned_me_id: Optional[int] = None
    assigned_me_name: Optional[str] = None
    assigned_ie_id: Optional[int] = None
    assigned_ie_name: Optional[str] = None
    investigating_pd_id: Optional[int] = None
    investigating_pd_name: Optional[str] = None
    updated_at: Optional[datetime] = None
    href: str
    has_reservation: bool = False
    can_pd_decide: bool = False
    can_assign_me: bool = False
    can_me_request_issue: bool = False
    can_im_issue: bool = False
    can_start_ait: bool = False
    can_upload_ait: bool = False
    can_pd_ait: bool = False
    can_reception: bool = False
    can_assign_ie: bool = False
    can_handover: bool = False
    can_im_issue_to_ie: bool = False
    can_disposition: bool = False
    can_repair_submit: bool = False
    can_pd_repair: bool = False
    can_confirm_discard: bool = False


class OemWarrantyClaimCreate(SQLModel):
    rework_case_id: int
    notes: Optional[str] = None
    force_discard: bool = False


class OemWarrantyClaimUpdate(SQLModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    shipped_at: Optional[datetime] = None


class OemWarrantyClaimRead(OemWarrantyClaimBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


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
    returned_units:   List[ReturnedUnitRead]         = []
    warranty_claims:  List[OemWarrantyClaimRead]     = []
    occurrence_attachments: List[OccurrenceAttachmentRead] = []
    occurrence_officers: List[OccurrenceOfficerRead] = []
    # Convenience alias for occurrence_fault_type
    fault_type: Optional[str] = None

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
