from typing import Any, Optional
from datetime import date, datetime, timezone
from sqlalchemy import Column, JSON
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
    avatar_url: Optional[str] = None
  # Password hash, required for auth

class UserBase(UserCommon):
    password: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_login_at: Optional[datetime] = None
    last_logout_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    failed_login_count: int = 0
    locked_until: Optional[datetime] = None
    password_changed_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    # JSON array of previous password hashes (newest first), for history policy
    password_history: Optional[str] = None
    created_by_id: Optional[int] = Field(default=None, foreign_key="user.id")


class UserLoginHistoryCommon(SQLModel):
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    username: str
    login_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    logout_time: Optional[datetime] = None
    session_id: Optional[str] = Field(default=None, index=True, max_length=64)
    ip_address: Optional[str] = Field(default=None, max_length=64)
    device_name: Optional[str] = Field(default=None, max_length=255)
    browser: Optional[str] = Field(default=None, max_length=255)
    operating_system: Optional[str] = Field(default=None, max_length=255)
    login_status: str = Field(default="Failed", max_length=32)  # Success | Failed
    failure_reason: Optional[str] = Field(default=None, max_length=255)
    last_activity: Optional[datetime] = None
    session_duration: Optional[int] = None  # seconds
    authentication_method: str = Field(default="password", max_length=64)
    country: Optional[str] = Field(default=None, max_length=128)
    city: Optional[str] = Field(default=None, max_length=128)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class UserLoginHistoryBase(UserLoginHistoryCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AuditLogCommon(SQLModel):
    actor_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    actor_username: Optional[str] = Field(default=None, max_length=255)
    action: str = Field(max_length=128)
    resource_type: Optional[str] = Field(default=None, max_length=64)
    resource_id: Optional[str] = Field(default=None, max_length=64)
    previous_value: Optional[str] = None
    new_value: Optional[str] = None
    details: Optional[str] = None
    ip_address: Optional[str] = Field(default=None, max_length=64)


class AuditLogBase(AuditLogCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowAuditEventCommon(SQLModel):
    """Spec 13 — append-only workflow audit envelope."""

    actor_user_id: Optional[int] = Field(default=None, index=True)
    actor_username: Optional[str] = Field(default=None, max_length=255)
    actor_role: str = Field(max_length=32, index=True)
    action: str = Field(max_length=64, index=True)
    entity_type: str = Field(max_length=64, index=True)
    entity_id: str = Field(max_length=64, index=True)
    project_id: Optional[int] = Field(default=None, index=True)
    old_value: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    new_value: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    remarks: Optional[str] = None
    ip_address: Optional[str] = Field(default=None, max_length=64)
    user_agent: Optional[str] = Field(default=None, max_length=512)
    correlation_id: Optional[str] = Field(default=None, max_length=64, index=True)


class WorkflowAuditEventBase(WorkflowAuditEventCommon):
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), index=True
    )


class SecuritySettingsCommon(SQLModel):
    """Singleton row storing enterprise security policy values."""
    min_password_length: int = 8
    password_expiry_days: int = 90
    require_uppercase: bool = True
    require_lowercase: bool = True
    require_numbers: bool = True
    require_special: bool = False
    password_history_length: int = 5
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 30
    inactivity_deactivate_days: int = 90
    two_factor_enabled: bool = False
    two_factor_require_all: bool = False
    two_factor_require_admins_only: bool = True


class SecuritySettingsBase(SecuritySettingsCommon):
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by_id: Optional[int] = Field(default=None, foreign_key="user.id")


class AppDefinitionsCommon(SQLModel):
    """Singleton row for admin naming templates and entity display labels."""
    serial_number_template: str = "{project}-{name}{seq}"
    part_number_template: str = "{project}-{name}{seq}-PN"
    configuration_item_template: str = "{project}-{name}{seq}-CI"
    sku_template: str = "{serial}-SKU"
    label_project: str = "Project"
    label_projects: str = "Projects"
    abbrev_project: str = "PROJ"
    label_system: str = "System"
    label_systems: str = "Systems"
    label_subsystem: str = "Subsystem"
    label_subsystems: str = "Subsystems"
    label_module: str = "Module"
    label_modules: str = "Modules"
    label_unit: str = "Unit"
    label_units: str = "Units"
    label_component: str = "Component"
    label_components: str = "Components"
    # Level short codes used in templates as {levelAbbr}
    abbrev_system: str = "SYS"
    abbrev_subsystem: str = "SUB"
    abbrev_module: str = "MOD"
    abbrev_unit: str = "UNIT"
    abbrev_component: str = "COMP"
    # Per-level PN/SN templates (admin selects what tokens to include)
    part_template_system: str = "PN-{levelAbbr}-{entityAbbr}-{year}-{vendor}-{seq:5}"
    serial_template_system: str = "SN-{levelAbbr}-{entityAbbr}-{year}-{pnSeq:5}-{seq:5}"
    part_template_subsystem: str = "PN-{levelAbbr}-{entityAbbr}-{year}-{vendor}-{seq:5}"
    serial_template_subsystem: str = "SN-{levelAbbr}-{entityAbbr}-{year}-{pnSeq:5}-{seq:5}"
    part_template_module: str = "PN-{levelAbbr}-{entityAbbr}-{year}-{vendor}-{seq:5}"
    serial_template_module: str = "SN-{levelAbbr}-{entityAbbr}-{year}-{pnSeq:5}-{seq:5}"
    part_template_unit: str = "PN-{levelAbbr}-{entityAbbr}-{year}-{vendor}-{seq:5}"
    serial_template_unit: str = "SN-{levelAbbr}-{entityAbbr}-{year}-{pnSeq:5}-{seq:5}"
    part_template_component: str = "PN-{levelAbbr}-{entityAbbr}-{year}-{vendor}-{seq:5}"
    serial_template_component: str = "SN-{levelAbbr}-{entityAbbr}-{year}-{pnSeq:5}-{seq:5}"
    inventory_label_code_type: str = "qr"
    inventory_qr_size_in: float = 0.65
    inventory_barcode_width_in: float = 2.0
    inventory_barcode_height_in: float = 0.5
    inventory_qr_sticker_width_in: float = 1.25
    inventory_qr_sticker_height_in: float = 1.25
    inventory_barcode_sticker_width_in: float = 2.25
    inventory_barcode_sticker_height_in: float = 0.9


class AppDefinitionsBase(AppDefinitionsCommon):
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by_id: Optional[int] = Field(default=None, foreign_key="user.id")


class ProjectCommon(SQLModel):
    name: str
    description: Optional[str] = None
    start_date: datetime
    end_date: Optional[datetime] = None
    owner_id: int
    order_id: int = None
    status_id: Optional[int] = None
    progress: int = Field(default=0, ge=0, le=100)
    # Spec 02 — workflow fields
    hierarchy_config_id: Optional[int] = Field(
        default=None, foreign_key="hierarchyconfiguration.id", index=True
    )
    hierarchy_config_version: Optional[int] = None
    product_type: Optional[str] = Field(default=None, max_length=64)
    flight_count: Optional[int] = Field(default=None, ge=1)
    sdls_per_flight: Optional[int] = Field(default=None, ge=1)
    assigned_hm_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    created_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    approved_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    approved_at: Optional[datetime] = None
    successor_project_id: Optional[int] = Field(
        default=None, foreign_key="project.id", index=True
    )
    predecessor_project_id: Optional[int] = Field(
        default=None, foreign_key="project.id", index=True
    )

class ProjectBase(ProjectCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Spec 03 — project-scoped Flight / SDLS containers
class FlightCommon(SQLModel):
    name: str = Field(max_length=255)
    code: Optional[str] = Field(default=None, max_length=64)
    sequence: int = Field(default=1, ge=1)
    description: Optional[str] = None
    project_id: int = Field(foreign_key="project.id", index=True)
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")


class FlightBase(FlightCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SdlsCommon(SQLModel):
    name: str = Field(max_length=255)
    code: Optional[str] = Field(default=None, max_length=64)
    sequence: int = Field(default=1, ge=1)
    description: Optional[str] = None
    product_type: Optional[str] = Field(default=None, max_length=64)
    flight_id: int = Field(foreign_key="flight.id", index=True)
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")


class SdlsBase(SdlsCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    # Hex color for badges across the UI (e.g. #059669)
    color: Optional[str] = None
    
class StatusBase(StatusCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class HierarchyCommon(SQLModel):
    name: str
    description: Optional[str] = None
    hierarchy_type: str
    parent_id: Optional[int] = None
    # Short code used in PN/SN templates (e.g. ACU -> SA, Harness Antenna -> HA)
    abbreviation: Optional[str] = None


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


class HardwareReplacementFields(SQLModel):
    """Replacement chain on installed hierarchy rows only (not inventory)."""
    is_current_install: bool = True
    root_entity_id: Optional[int] = None
    replaced_entity_id: Optional[int] = None
    replacement_sequence: int = 0
    replaced_at: Optional[datetime] = None


class HardwareEntityFields(HierarchyInstallFields, HardwareReplacementFields):
    """Install metadata + replacement tracking for fielded hardware entities."""
    # Spec 07 — HM assigns a Developer to this hierarchy node
    assigned_developer_id: Optional[int] = Field(
        default=None, foreign_key="user.id", index=True
    )
    # Snapshot of the template node's inventory source at hierarchy generation.
    # NULL on legacy rows is treated as turnkey.
    inventory_source: Optional[str] = Field(default=None, max_length=32)


class SystemCommon(HardwareEntityFields):
    name: str
    description: Optional[str] = None
    project_id: int
    # Spec 03 — optional link when generated under an SDLS
    sdls_id: Optional[int] = Field(default=None, foreign_key="sdls.id", index=True)
    status_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None

class SystemBase(SystemCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class SubsystemCommon(HardwareEntityFields):
    name: str
    description: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None

class SubsystemBase(SubsystemCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ModuleCommon(HardwareEntityFields):
    name: str
    description: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None

class ModuleBase(ModuleCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UnitCommon(HardwareEntityFields):
    name: str
    description: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None

class UnitBase(UnitCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ComponentCommon(HardwareEntityFields):
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

class InventoryCommon(HierarchyInstallFields):
    """Inventory catalog row — fields mirror hierarchy entities for install-from-stock."""
    name: str
    inventory_type: str  # 'system', 'subsystem', 'module', 'unit', 'component'
    serial_number: Optional[str] = None
    quantity: int = 0
    description: Optional[str] = None
    oem_name: Optional[str] = None
    part_number: Optional[str] = None
    configuration_item: Optional[str] = None
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")
    sku: Optional[str] = None
    location: Optional[str] = None
    entity_id: Optional[int] = None  # PK of linked hierarchy row after install
    holder_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    added_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    shelf_life_expires_at: Optional[datetime] = None

class InventoryBase(InventoryCommon):
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InventoryInstanceCommon(HierarchyInstallFields):
    """Serialized inventory unit — per-unit fields mirror a single hierarchy entity."""
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")
    holder_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    location: Optional[str] = None
    added_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    shelf_life_expires_at: Optional[datetime] = None


class InventoryInstanceBase(InventoryInstanceCommon):
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InventoryLabelStatus(str, Enum):
    ACTIVE = "active"
    DEACTIVATED = "deactivated"
    REPLACED = "replaced"
    INVESTIGATION = "investigation"


class InventoryLabelCommon(SQLModel):
    """Opaque, server-validated label assigned to an inventory unit."""

    label_id: str = Field(index=True, unique=True, max_length=64)
    inventory_id: int = Field(foreign_key="inventory.id", index=True)
    inventory_instance_id: Optional[int] = Field(
        default=None, foreign_key="inventoryinstance.id", index=True
    )
    serial_number: Optional[str] = Field(default=None, index=True, max_length=128)
    label_type: str = Field(default="qr", max_length=16)
    status: str = Field(
        default=InventoryLabelStatus.ACTIVE.value, index=True, max_length=32
    )
    signature_version: str = Field(default="v1", max_length=16)
    print_count: int = Field(default=0, ge=0)
    first_printed_at: Optional[datetime] = None
    last_printed_at: Optional[datetime] = None
    activated_at: Optional[datetime] = None
    activated_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    deactivated_at: Optional[datetime] = None
    deactivated_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    replacement_label_id: Optional[str] = Field(default=None, max_length=64)


class InventoryLabelBase(InventoryLabelCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InventoryLabelPrintEventBase(SQLModel):
    label_id: str = Field(foreign_key="inventorylabel.label_id", index=True, max_length=64)
    user_id: int = Field(foreign_key="user.id", index=True)
    printed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    reason: Optional[str] = None
    label_type: str = Field(max_length=16)
    label_format: str = Field(max_length=32)
    quantity: int = Field(default=1, ge=1)
    is_first_print: bool = False


class InventoryLabelScanEventBase(SQLModel):
    label_id: Optional[str] = Field(
        default=None,
        foreign_key="inventorylabel.label_id",
        index=True,
        max_length=64,
    )
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    location: Optional[str] = Field(default=None, max_length=255)
    source: str = Field(default="web", max_length=32)
    valid: bool = False
    suspicious: bool = False
    reason: Optional[str] = None
    payload_fingerprint: Optional[str] = Field(default=None, max_length=128)


class InventoryReservationStatus(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    CONSUMED = "consumed"


class InventoryReservationCommon(SQLModel):
    """Spec 04 — HM project hierarchy reservation ledger (Flight → SDLS → item)."""
    project_id: int = Field(foreign_key="project.id", index=True)
    flight_id: int = Field(foreign_key="flight.id", index=True)
    sdls_id: int = Field(foreign_key="sdls.id", index=True)
    target_entity_type: str = Field(max_length=32, index=True)
    target_entity_id: int = Field(index=True)
    inventory_id: int = Field(foreign_key="inventory.id", index=True)
    inventory_instance_id: Optional[int] = Field(
        default=None, foreign_key="inventoryinstance.id", index=True
    )
    reserved_by_user_id: int = Field(foreign_key="user.id", index=True)
    reserved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    last_reminder_at: Optional[datetime] = None
    extension_count: int = Field(default=0, ge=0)
    part_number: Optional[str] = Field(default=None, max_length=128)
    serial_number: Optional[str] = Field(default=None, max_length=128)
    status: str = Field(
        default=InventoryReservationStatus.ACTIVE.value, index=True, max_length=32
    )
    released_at: Optional[datetime] = None
    released_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    notes: Optional[str] = None


class InventoryReservationBase(InventoryReservationCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReservationExpiryNoticeType(str, Enum):
    REMINDER = "reservation_idle_reminder"
    AUTO_RELEASED = "reservation_auto_released"


AUTO_RELEASE_EXPIRY_REASON = "AUTO_RELEASE_EXPIRY"


class InventoryReservationExpiryNoticeBase(SQLModel):
    """In-app idle-reservation reminder / auto-release notice for the reserving HM."""
    user_id: int = Field(foreign_key="user.id", index=True)
    reservation_id: int = Field(index=True)
    notice_type: str = Field(index=True, max_length=32)
    part_number: Optional[str] = Field(default=None, max_length=128)
    serial_number: Optional[str] = Field(default=None, max_length=128)
    flight_code: Optional[str] = Field(default=None, max_length=64)
    flight_name: Optional[str] = Field(default=None, max_length=255)
    sdls_code: Optional[str] = Field(default=None, max_length=64)
    sdls_name: Optional[str] = Field(default=None, max_length=255)
    inventory_name: Optional[str] = Field(default=None, max_length=255)
    project_id: Optional[int] = Field(default=None, index=True)
    project_name: Optional[str] = Field(default=None, max_length=255)
    message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    read_at: Optional[datetime] = None


class ShortageStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ShortageNoticeType(str, Enum):
    CREATED = "shortage_created"
    PARTIAL = "shortage_partial"
    FULFILLED = "shortage_fulfilled"


class InventoryShortageCommon(SQLModel):
    """Spec 05 — waiting demand while stock is short (FCFS key = requested_at)."""
    project_id: int = Field(foreign_key="project.id", index=True)
    flight_id: int = Field(foreign_key="flight.id", index=True)
    sdls_id: int = Field(foreign_key="sdls.id", index=True)
    target_entity_type: str = Field(max_length=32, index=True)
    target_entity_id: int = Field(index=True)
    inventory_id: Optional[int] = Field(default=None, foreign_key="inventory.id", index=True)
    part_number: Optional[str] = Field(default=None, max_length=128, index=True)
    qty_short: int = Field(default=1, ge=0)
    qty_original: int = Field(default=1, ge=1)
    lru_name: Optional[str] = Field(default=None, max_length=255)
    requested_by_user_id: int = Field(foreign_key="user.id", index=True)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    status: str = Field(default=ShortageStatus.OPEN.value, index=True, max_length=32)
    last_notified_at: Optional[datetime] = None
    fulfilled_reservation_id: Optional[int] = Field(
        default=None, foreign_key="inventoryreservation.id"
    )
    cancelled_at: Optional[datetime] = None
    cancelled_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    notes: Optional[str] = None


class InventoryShortageBase(InventoryShortageCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InventoryShortageNoticeBase(SQLModel):
    """In-app shortage notice for HM and IM (PN, Qty, Flight, SDLS, LRU)."""
    user_id: int = Field(foreign_key="user.id", index=True)
    shortage_id: int = Field(index=True)
    notice_type: str = Field(index=True, max_length=32)
    part_number: Optional[str] = Field(default=None, max_length=128)
    qty: int = 1
    flight_code: Optional[str] = Field(default=None, max_length=64)
    flight_name: Optional[str] = Field(default=None, max_length=255)
    sdls_code: Optional[str] = Field(default=None, max_length=64)
    sdls_name: Optional[str] = Field(default=None, max_length=255)
    lru_name: Optional[str] = Field(default=None, max_length=255)
    project_id: Optional[int] = Field(default=None, index=True)
    project_name: Optional[str] = Field(default=None, max_length=255)
    message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    read_at: Optional[datetime] = None


class InventoryChildLinkBase(SQLModel):
    """Child inventory stock assigned to a parent inventory item (optionally per serial)."""
    child_category_name: str
    child_inventory_id: int
    child_instance_id: Optional[int] = None
    parent_instance_serial: Optional[str] = None
    child_instance_serial: Optional[str] = None
    # True when child stock was removed from available inventory at compose time.
    stock_consumed: bool = False


class IssuanceStatus(str, Enum):
    ISSUED = "issued"
    RETURN_PENDING = "return_pending"
    INSTALLED = "installed"
    RETURNED = "returned"
    REVERTED = "reverted"


# ==================== WORKFLOW FOUNDATIONS (Spec 00) ====================
# Stable API / seed codes — used by status_transitions and Status table seeds.


class WorkflowRole(str, Enum):
    """Five first-class workflow roles. DB Role.name matches these values except Admin."""

    ADMIN = "Admin"  # existing privileged name
    PD = "PD"
    HM = "HM"
    IM = "IM"
    DEV = "DEV"


class ItemStatus(str, Enum):
    """Canonical inventory / item lifecycle statuses."""

    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    INSTALLATION_IN_PROGRESS = "INSTALLATION_IN_PROGRESS"
    UNDER_TESTING_REVIEW = "UNDER_TESTING_REVIEW"
    INSTALLED_VERIFIED = "INSTALLED_VERIFIED"
    RETURNED = "RETURNED"
    INSPECTION = "INSPECTION"
    REUSABLE = "REUSABLE"
    REPAIRABLE = "REPAIRABLE"
    SCRAPPED = "SCRAPPED"


class ProjectWorkflowStatus(str, Enum):
    """Project workflow statuses (Spec 02–03 + reserved later codes)."""

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    HIERARCHY_GENERATED = "HIERARCHY_GENERATED"
    READY_FOR_INVENTORY = "READY_FOR_INVENTORY"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    READY_TO_DELIVER = "READY_TO_DELIVER"
    SUPERSEDED = "SUPERSEDED"


# Status.status_type values for workflow seed rows
STATUS_TYPE_INVENTORY_ITEM = "inventory"
STATUS_TYPE_PROJECT_WORKFLOW = "projects"


class InventoryIssuanceBase(SQLModel):
    """Ledger row for issue → reserve → install / return / revert."""
    inventory_id: int
    inventory_instance_id: Optional[int] = None
    quantity: int = 1
    issued_to_user_id: int
    issued_by_user_id: int
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = Field(default=IssuanceStatus.ISSUED.value, index=True)
    # Planned / target entity detail at issue time
    target_entity_type: Optional[str] = None
    target_entity_id: Optional[int] = None
    # Snapshots for reporting after instance is consumed
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    inventory_name: Optional[str] = None
    inventory_type: Optional[str] = None
    notes: Optional[str] = None
    # Install link
    installed_at: Optional[datetime] = None
    installed_entity_type: Optional[str] = None
    installed_entity_id: Optional[int] = None
    installed_by_id: Optional[int] = None
    # Return / revert close
    closed_at: Optional[datetime] = None
    closed_by_id: Optional[int] = None
    # When installer requested return (pending admin accept/reject)
    return_requested_at: Optional[datetime] = None
    # Spec 07 — signature + reservation context
    signature_type: Optional[str] = Field(default=None, max_length=32)
    signature_payload: Optional[str] = None
    item_request_id: Optional[int] = Field(default=None, index=True)
    reservation_id: Optional[int] = Field(default=None, index=True)
    project_id: Optional[int] = Field(default=None, index=True)
    flight_id: Optional[int] = None
    sdls_id: Optional[int] = None
    item_lifecycle_status: Optional[str] = Field(default=None, max_length=64, index=True)
    # Spec 08 — install / test / HM verify (item lifecycle, not consume-install)
    test_result: Optional[str] = Field(default=None, max_length=16, index=True)
    test_recorded_at: Optional[datetime] = None
    test_recorded_by_id: Optional[int] = None
    complete_reported_at: Optional[datetime] = None
    complete_reported_by_id: Optional[int] = None
    verified_at: Optional[datetime] = None
    verified_by_id: Optional[int] = None
    defect_pending: bool = Field(default=False, index=True)


class InventoryReturnNoticeBase(SQLModel):
    """Admin/SubAdmin notification when an installer returns issued stock."""
    issuance_id: int
    inventory_id: Optional[int] = None
    inventory_name: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    returned_by_user_id: int
    returned_by_name: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    read_at: Optional[datetime] = None
    # pending | accepted | rejected — pending until admin decides
    decision: Optional[str] = Field(default="pending", index=True)
    decided_at: Optional[datetime] = None
    decided_by_id: Optional[int] = None
    decision_notes: Optional[str] = None
    # Installer's reason when requesting return
    request_notes: Optional[str] = None


class SignatureType(str, Enum):
    DIGITAL = "DIGITAL"
    HARD_COPY = "HARD_COPY"


HARD_COPY_ACKNOWLEDGMENT = "HARD_COPY_CONFIRMED"


class ItemRequestStatus(str, Enum):
    PENDING = "pending"
    ISSUED = "issued"
    CANCELLED = "cancelled"


class InventoryItemRequestBase(SQLModel):
    """Spec 07 — Developer request-to-issue queue for IM."""
    project_id: int = Field(foreign_key="project.id", index=True)
    flight_id: int = Field(foreign_key="flight.id", index=True)
    sdls_id: int = Field(foreign_key="sdls.id", index=True)
    target_entity_type: str = Field(max_length=32, index=True)
    target_entity_id: int = Field(index=True)
    assigned_developer_id: int = Field(foreign_key="user.id", index=True)
    requested_by_user_id: int = Field(foreign_key="user.id", index=True)
    inventory_id: int = Field(foreign_key="inventory.id", index=True)
    inventory_instance_id: Optional[int] = Field(
        default=None, foreign_key="inventoryinstance.id", index=True
    )
    reservation_id: int = Field(foreign_key="inventoryreservation.id", index=True)
    status: str = Field(
        default=ItemRequestStatus.PENDING.value, index=True, max_length=32
    )
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    issued_at: Optional[datetime] = None
    issued_issuance_id: Optional[int] = Field(
        default=None, foreign_key="inventoryissuance.id", index=True
    )
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ItemTestResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class IssuanceEventType(str, Enum):
    ISSUED = "issued"
    RETURN_REQUESTED = "return_requested"
    RETURN_ACCEPTED = "return_accepted"
    RETURN_REJECTED = "return_rejected"
    INSTALLED = "installed"
    REVERTED = "reverted"
    INSTALL_STARTED = "install_started"
    TEST_PASSED = "test_passed"
    TEST_FAILED = "test_failed"
    COMPLETE_REPORTED = "complete_reported"
    VERIFIED = "verified"
    DEFECT_PENDING = "defect_pending"
    REWORK_OPENED = "rework_opened"
    ITEM_REMOVED = "item_removed"
    ITEM_RETURNED = "item_returned"
    INSPECTION_STARTED = "inspection_started"
    DISPOSITIONED = "dispositioned"
    REISSUED = "reissued"
    REWORK_CLOSED = "rework_closed"
    RECALL_OPENED = "recall_opened"
    RECALL_FORCED_RETURN = "recall_forced_return"


class ReworkCaseStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class ReworkStage(str, Enum):
    FAILED = "failed"
    REMOVED = "removed"
    RETURNED = "returned"
    INSPECTION = "inspection"
    REPAIRABLE = "repairable"
    REUSABLE = "reusable"
    SCRAPPED = "scrapped"
    REISSUED = "reissued"
    RETESTING = "retesting"


class ReworkDisposition(str, Enum):
    REPAIRABLE = "repairable"
    REUSABLE = "reusable"
    SCRAPPED = "scrapped"


REWORK_CYCLE_WARNING_ATTEMPTS = 3


class InventoryReworkCaseBase(SQLModel):
    """Spec 10 — open defect/rework case for a hierarchy node (outlives a serial)."""
    project_id: int = Field(foreign_key="project.id", index=True)
    flight_id: Optional[int] = Field(default=None, foreign_key="flight.id")
    sdls_id: Optional[int] = Field(default=None, foreign_key="sdls.id")
    target_entity_type: str = Field(max_length=32, index=True)
    target_entity_id: int = Field(index=True)
    inventory_id: int = Field(foreign_key="inventory.id", index=True)
    original_instance_id: Optional[int] = Field(
        default=None, foreign_key="inventoryinstance.id", index=True
    )
    current_instance_id: Optional[int] = Field(
        default=None, foreign_key="inventoryinstance.id", index=True
    )
    current_issuance_id: Optional[int] = Field(
        default=None, foreign_key="inventoryissuance.id", index=True
    )
    assigned_developer_id: Optional[int] = Field(
        default=None, foreign_key="user.id", index=True
    )
    status: str = Field(
        default=ReworkCaseStatus.OPEN.value, index=True, max_length=32
    )
    stage: str = Field(
        default=ReworkStage.FAILED.value, index=True, max_length=32
    )
    attempt_count: int = Field(default=1)
    disposition: Optional[str] = Field(default=None, max_length=32)
    repaired_at: Optional[datetime] = None
    repaired_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    opened_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    closed_at: Optional[datetime] = None
    closed_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


PROJECT_CANCELLED_RELEASE_REASON = "PROJECT_CANCELLED"
CONFIG_CHANGE_RELEASE_REASON = "CONFIG_CHANGE"


class ConfigChangeRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    INVENTORY_RETURNED = "INVENTORY_RETURNED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    NEW_PROJECT_CREATED = "NEW_PROJECT_CREATED"
    CANCELLED = "CANCELLED"


class ConfigChangeRequestBase(SQLModel):
    """Spec 12 — configuration change request (no in-place config mutate)."""

    source_project_id: int = Field(foreign_key="project.id", index=True)
    target_hierarchy_config_id: Optional[int] = Field(
        default=None, foreign_key="hierarchyconfiguration.id", index=True
    )
    target_product_type: Optional[str] = Field(default=None, max_length=64)
    target_flight_count: Optional[int] = Field(default=None, ge=1)
    target_sdls_per_flight: Optional[int] = Field(default=None, ge=1)
    reason_remarks: Optional[str] = None
    status: str = Field(
        default=ConfigChangeRequestStatus.REQUESTED.value,
        index=True,
        max_length=32,
    )
    successor_project_id: Optional[int] = Field(
        default=None, foreign_key="project.id", index=True
    )
    requested_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    submitted_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    submitted_at: Optional[datetime] = None
    approved_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    approved_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RecallTaskStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class RecallStage(str, Enum):
    REQUESTED = "requested"
    RETURNED = "returned"
    INSPECTION = "inspection"
    REUSABLE = "reusable"
    REPAIRABLE = "repairable"
    SCRAPPED = "scrapped"


class RecallDisposition(str, Enum):
    REUSABLE = "reusable"
    REPAIRABLE = "repairable"
    SCRAPPED = "scrapped"


class InventoryRecallTaskBase(SQLModel):
    """Spec 11 — project-cancel recall of issued / in-progress inventory."""
    project_id: int = Field(foreign_key="project.id", index=True)
    flight_id: Optional[int] = Field(default=None, foreign_key="flight.id")
    sdls_id: Optional[int] = Field(default=None, foreign_key="sdls.id")
    target_entity_type: Optional[str] = Field(default=None, max_length=32, index=True)
    target_entity_id: Optional[int] = Field(default=None, index=True)
    inventory_id: int = Field(foreign_key="inventory.id", index=True)
    inventory_instance_id: Optional[int] = Field(
        default=None, foreign_key="inventoryinstance.id", index=True
    )
    issuance_id: Optional[int] = Field(
        default=None, foreign_key="inventoryissuance.id", index=True
    )
    assigned_developer_id: Optional[int] = Field(
        default=None, foreign_key="user.id", index=True
    )
    status: str = Field(
        default=RecallTaskStatus.OPEN.value, index=True, max_length=32
    )
    stage: str = Field(
        default=RecallStage.REQUESTED.value, index=True, max_length=32
    )
    disposition: Optional[str] = Field(default=None, max_length=32)
    forced_return: bool = Field(default=False)
    forced_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    opened_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    returned_at: Optional[datetime] = None
    returned_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    inspected_at: Optional[datetime] = None
    inspected_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    closed_at: Optional[datetime] = None
    closed_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InventoryIssuanceEventBase(SQLModel):
    """Immutable ledger of issue / return / reissue / install events for a unit."""
    issuance_id: int
    inventory_id: Optional[int] = None
    inventory_instance_id: Optional[int] = None
    event_type: str = Field(index=True)
    quantity: int = 1
    actor_user_id: Optional[int] = None
    actor_name: Optional[str] = None
    installer_user_id: Optional[int] = None
    installer_name: Optional[str] = None
    notes: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    inventory_name: Optional[str] = None
    inventory_type: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InstallerNoticeType(str, Enum):
    ISSUED = "issued"
    RETURN_ACCEPTED = "return_accepted"
    RETURN_REJECTED = "return_rejected"


class InventoryInstallerNoticeBase(SQLModel):
    """In-app notice for the installer (issue / return decision)."""
    user_id: int
    notice_type: str = Field(index=True)
    issuance_id: Optional[int] = None
    inventory_id: Optional[int] = None
    inventory_name: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    message: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    read_at: Optional[datetime] = None


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


# ===== Spec 01 — Hierarchy Configuration =====
class HierarchyConfigurationCommon(SQLModel):
    code: str = Field(index=True, max_length=64)
    name: str = Field(max_length=255)
    description: Optional[str] = None
    notes: Optional[str] = None
    is_available: bool = True
    version: int = 1


class HierarchyConfigurationBase(HierarchyConfigurationCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by_id: Optional[int] = Field(default=None, foreign_key="user.id")


class HierarchyConfigProductTypeCommon(SQLModel):
    code: str = Field(max_length=64)
    name: str = Field(max_length=255)
    description: Optional[str] = None
    sort_order: int = 0


class HierarchyConfigProductTypeBase(HierarchyConfigProductTypeCommon):
    configuration_id: int = Field(foreign_key="hierarchyconfiguration.id", index=True)


class HierarchyConfigNodeCommon(SQLModel):
    level: str = Field(max_length=32, index=True)  # system|subsystem|module|unit|component
    name: str = Field(max_length=255)
    description: Optional[str] = None
    abbreviation: Optional[str] = Field(default=None, max_length=32)
    sort_order: int = 0
    client_key: Optional[str] = Field(default=None, max_length=64)
    inventory_source: str = Field(default="turnkey", max_length=32)


class HierarchyConfigNodeBase(HierarchyConfigNodeCommon):
    configuration_id: int = Field(foreign_key="hierarchyconfiguration.id", index=True)
    parent_id: Optional[int] = Field(
        default=None, foreign_key="hierarchyconfignode.id", index=True
    )


class AssembledInventoryCommon(SQLModel):
    """Idempotent record of inventory auto-created from verified children."""
    target_entity_type: str = Field(max_length=32, index=True)
    target_entity_id: int = Field(index=True)
    inventory_id: int = Field(foreign_key="inventory.id", index=True)
    inventory_instance_id: Optional[int] = Field(
        default=None, foreign_key="inventoryinstance.id", index=True
    )
    project_id: Optional[int] = Field(default=None, foreign_key="project.id", index=True)
    flight_id: Optional[int] = Field(default=None, foreign_key="flight.id", index=True)
    sdls_id: Optional[int] = Field(default=None, foreign_key="sdls.id", index=True)
    configuration_id: Optional[int] = Field(
        default=None, foreign_key="hierarchyconfiguration.id", index=True
    )
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    source_summary: Optional[str] = None


class AssembledInventoryBase(AssembledInventoryCommon):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Token(SQLModel):
    access_token: str
    token_type: str

class TokenData(SQLModel):
    username: str | None = None