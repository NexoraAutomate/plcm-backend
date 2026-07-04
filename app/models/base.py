from typing import Optional
from datetime import date, datetime, timezone
from sqlmodel import SQLModel, Field, Relationship
from enum import Enum
from decimal import Decimal

# Base models for all entities, defining common fields and structure

# All Base models are immutable and include created_at timestamp. Updateable fields are defined in separate Common models.
# Common models are used for create/update operations and do not include created_at or primary key fields. They can be extended with additional fields as needed.
# Base models are used for database tables and include primary key fields. They can also include relationships if needed, but should not include updateable fields directly.

class UserCommon(SQLModel):    
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: bool = True
  # Password hash, required for auth

class UserBase(UserCommon):
    password:str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ProjectCommon(SQLModel):
    name: str
    description: Optional[str] = None
    start_date: datetime
    end_date: Optional[datetime] = None
    owner_id: int
    order_id: int = None
    status_id: Optional[int] = None
    progress: int = Field(default=0, ge=0, le=100)

class ProjectBase(ProjectCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class CustomerCommon(SQLModel):
    name: str

    organization_type: Optional[str] = None

    primary_contact_name: Optional[str] = None
    designation: Optional[str] = None

    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None

    address: Optional[str] = None
    country: Optional[str] = None

    notes: Optional[str] = None

    created_by: Optional[int] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class CustomerBase(CustomerCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCommon(SQLModel):
    status_name: str
    description: Optional[str] = None
    status_type: Optional[str] = None
    
class StatusBase(StatusCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class HierarchyCommon(SQLModel):
    name: str
    description: Optional[str] = None
    hierarchy_type: str
    parent_id: Optional[int] = None

class HierarchyBase(HierarchyCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class OrderCommon(SQLModel):
    customer_id: int

    order_number: str = Field(index=True, unique=True)
    title: str
    description: Optional[str] = None
    contract_number: Optional[str] = None
    po_number: Optional[str] = None
    order_date: date
    delivery_date: Optional[date] = None

    total_value: Optional[Decimal] = None
    currency: str = "PKR"

    status_id: Optional[int] = None

    project_manager: Optional[str] = None

    remarks: Optional[str] = None

class OrderBase(OrderCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class HierarchyInstallFields(SQLModel):
    installation_date: Optional[datetime] = None
    installed_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    picture_url: Optional[str] = None
    original_part_number: Optional[str] = None
    original_serial_number: Optional[str] = None


class SystemCommon(HierarchyInstallFields):
    name: str
    description: Optional[str] = None
    project_id: int
    status_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None

class SystemBase(SystemCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class SubsystemCommon(HierarchyInstallFields):
    name: str
    description: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None

class SubsystemBase(SubsystemCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ModuleCommon(HierarchyInstallFields):
    name: str
    description: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None

class ModuleBase(ModuleCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UnitCommon(HierarchyInstallFields):
    name: str
    description: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None

class UnitBase(UnitCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ComponentCommon(HierarchyInstallFields):
    name: str
    description: Optional[str] = None
    sku: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None

class ComponentBase(ComponentCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class EntityCommon(SQLModel):
    name: str
    display_name: Optional[str] = None
    entity_type: str
    entity_pk: int

class EntityBase(EntityCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class EntityStatusHistoryCommon(SQLModel):
    entity_id: Optional[int] = None
    status_id: Optional[int] = None
    changed_by: Optional[int] = None
    notes: Optional[str] = None

class EntityStatusHistoryBase(EntityStatusHistoryCommon):
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class MaintenanceLogCommon(SQLModel):
    entity_id: int
    notes: Optional[str] = None
    next_due: Optional[datetime] = None
    
class MaintenanceLogBase(MaintenanceLogCommon):
    performed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class InventoryCommon(SQLModel):
    name: str
    inventory_type: str  # 'system', 'subsystem', 'module', 'unit', 'component'
    serial_number: Optional[str] = None
    quantity: int = 0
    description: Optional[str] = None
    oem_name: Optional[str] = None
    manufacturer_part_number: Optional[str] = None
    location: Optional[str] = None
    entity_id: Optional[int] = None  # ID of the associated entity (system_id, subsystem_id, etc.)
    holder_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    added_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    shelf_life_expires_at: Optional[datetime] = None
    picture_url: Optional[str] = None

class InventoryBase(InventoryCommon):
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))   


class EntityType(str, Enum):
    PROJECT   = "project"
    SYSTEM    = "system"
    SUBSYSTEM = "subsystem"
    MODULE    = "module"
    UNIT      = "unit"
    COMPONENT = "component"
    ORDER     = "order"        
    CUSTOMER  = "customer"     


class CaseStatus(str, Enum):
    OPEN             = "open"
    UNDER_INSPECTION = "under_inspection"
    UNDER_REPAIR     = "under_repair"
    RESOLVED         = "resolved"
    CLOSED           = "closed"

class InventoryType(str, Enum):
    SYSTEM    = "system"
    SUBSYSTEM = "subsystem"
    MODULE    = "module"
    UNIT      = "unit"
    COMPONENT = "component"

class FaultType(str, Enum):
    HARDWARE             = "hardware"
    SOFTWARE             = "software"
    PHYSICAL_DAMAGE      = "physical_damage"
    WEAR                 = "wear"
    MANUFACTURING_DEFECT = "manufacturing_defect"
    UNCLASSIFIED         = "unclassified"
    ELECTRICAL           = 'electrical'
    MECHANICAL           = 'mechanical'
    ENVIRONMENTAL        = 'environmental'
    OTHER                = 'other'


class FaultyEntityStatus(str, Enum):
    IDENTIFIED       = "identified"
    SUSPECTED        = "suspected"
    UNDER_INSPECTION = "under_inspection"
    CONFIRMED_FAULTY = "confirmed_faulty"
    HEALTHY          = "healthy"
    RESOLVED         = "resolved"
    NO_FAULT_FOUND   = "no_fault_found"
    FALSEPOSITIVE    = 'false_positive'


class ResolutionType(str, Enum):
    REPAIRED       = "repaired"
    REPLACED       = "replaced"
    NO_FAULT_FOUND = "no_fault_found"
    DECOMMISSIONED = "decommissioned"
    CLEAR          = "clear"

class ActionType(str, Enum):
    INSPECTION    = "inspection"
    DISASSEMBLY   = "disassembly"
    REPAIR        = "repair"
    REPLACEMENT   = "replacement"
    TESTING       = "testing"
    CLEANING      = "cleaning"
    RECALIBRATION = "recalibration"

class ActionOutcome(str, Enum):
    PASS         = "pass"
    FAIL         = "fail"
    INCONCLUSIVE = "inconclusive"
    PENDING      = "pending"

class DeliveryType(str, Enum):
    INITIAL_DELIVERY    = "initial_delivery"
    RE_DELIVERY         = "re_delivery"
    PARTIAL_RE_DELIVERY = "partial_re_delivery"

class DeliveryStatus(str, Enum):
    PENDING               = "pending"
    DISPATCHED            = "dispatched"
    DELIVERED             = "delivered"
    CONFIRMED_BY_CUSTOMER = "confirmed_by_customer"

class AttachmentType(str, Enum):
    TEST_REPORT        = "test_report"
    DATASHEET          = "datasheet"
    MANUAL             = "manual"
    CERTIFICATE        = "certificate"
    DRAWING            = "drawing"
    PHOTO              = "photo"
    WARRANTY           = "warranty"
    INVOICE            = "invoice"
    INSTALLATION_GUIDE = "installation_guide"
    OTHER              = "other"

# =============================================================================
# 1. MAINTENANCE CASE
# =============================================================================
# A top-level fault event opened against a delivered project.
# One project can accumulate many cases over its lifetime.
# =============================================================================

class MaintenanceCaseCommon(SQLModel):
    """Shared fields — no auto-generated values, no PKs, no FKs."""
    description:      str
    status:           CaseStatus  = CaseStatus.OPEN
    resolution_notes: Optional[str] = None
    entity_id: Optional[int] = None
    entity_type: Optional[str] = None
    part_number: Optional[str] = None
    status_id: Optional[int]= None
    resolved_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] =Field(default_factory=lambda: datetime.now(timezone.utc))

class MaintenanceCaseBase(MaintenanceCaseCommon):
    """Adds server-side timestamps."""
    reported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    project_name: Optional[str] = None

# =============================================================================
# 2. FAULTY ENTITY
# =============================================================================
# Polymorphic record pointing to any level of the hierarchy
# (project / system / subsystem / module / unit / component).
# parent_faulty_entity_id enables the fault cascade chain to be explicit:
#   component FE → parent unit FE → parent module FE → ...
# =============================================================================

class FaultyEntityCommon(SQLModel):
    """Shared fields — entity discriminator, fault classification."""
    entity_type:       EntityType
    entity_id:         int
    fault_type:        FaultType          = FaultType.UNCLASSIFIED
    fault_description: Optional[str]      = None
    status_id: Optional[int]= None
    status:            FaultyEntityStatus = FaultyEntityStatus.IDENTIFIED
    resolution_type:   Optional[ResolutionType] = None

class FaultyEntityBase(FaultyEntityCommon):
    """Adds server-side timestamps."""
    identified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    entity_name: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    parent_entity_id: Optional[int]
    parent_entity_type: Optional[EntityType]
    parent_entity_name: Optional[str] = None
    confirmed_at: Optional[str] = None
    investigation_notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
        


# =============================================================================
# 3. MAINTENANCE ACTION
# =============================================================================
# Individual audit-log entries for every action taken on a faulty entity.
# Includes: inspection, repair, replacement, testing, cleaning, recalibration.
# On replacement, replacement_entity_id records the new entity that took over.
# =============================================================================

class MaintenanceActionCommon(SQLModel):
    action_type: ActionType
    notes:       Optional[str]          = None
    outcome:     Optional[ActionOutcome] = None
    # Populated only when action_type == ActionType.REPLACEMENT
    replacement_entity_id:   Optional[int]      = None
    replacement_entity_type: Optional[EntityType] = None
    created_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc))




class MaintenanceActionBase(MaintenanceActionCommon):
    performed_at: Optional[datetime] = Field(default_factory=lambda: datetime.now(timezone.utc)
    )

# =============================================================================
# 4. MAINTENANCE DELIVERY
# =============================================================================
# Records every delivery event linked to a case:
#   - initial_delivery  → first time product goes to customer (optional use)
#   - re_delivery       → product returned after repair / replacement
#   - partial_re_delivery → only some entities were resolved and re-sent
# Confirming a delivery auto-closes the parent case when status = resolved.
# =============================================================================

class MaintenanceDeliveryCommon(SQLModel):
    delivery_type: DeliveryType   = DeliveryType.RE_DELIVERY
    status:        DeliveryStatus = DeliveryStatus.PENDING
    status_id: Optional[int]= None
    received_by:   Optional[str]  = Field(
        default=None,
        description="Customer contact name or signature reference."
    )
    notes: Optional[str] = None

class MaintenanceDeliveryBase(MaintenanceDeliveryCommon):
    delivered_at: Optional[datetime] = None


class ConfigurationHistoryBase(SQLModel):

    entity_id: int = Field(foreign_key="entity.id", ondelete="CASCADE")

    maintenance_case_id: Optional[int] = Field(default=None,foreign_key="maintenance_case.id", ondelete="CASCADE"    )

    faulty_entity_id: Optional[int] = Field(
        default=None,
        foreign_key="faulty_entity.id",
        unique=True,
    )

    performed_by: int = Field(
        foreign_key="user.id"
    )

    approved_by: Optional[int] = Field(
        default=None,
        foreign_key="user.id"
    )

    verified_by: Optional[int] = Field(
        default=None,
        foreign_key="user.id"
    )

    change_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

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



# ===== AUTHENTICATION & AUTHORIZATION MODELS =====
class PermissionCommon(SQLModel):
    name: str  # e.g., "create_project", "delete_user", "view_inventory"
    description: Optional[str] = None

class PermissionBase(PermissionCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class RoleCommon(SQLModel):
    name: str  # e.g., "Admin", "ProjectManager", "Viewer"
    description: Optional[str] = None

class RoleBase(RoleCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Token(SQLModel):
    access_token: str
    token_type: str

class TokenData(SQLModel):
    username: str | None = None