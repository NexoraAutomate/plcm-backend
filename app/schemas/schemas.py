from decimal import Decimal
from typing import Optional, List
from datetime import datetime
from sqlmodel import SQLModel
from pydantic import ConfigDict, Field
from app.models.base import (
    UserBase,
    CustomerBase,
    StatusBase,
    OrderBase,
    ProjectBase,
    SystemBase,
    SubsystemBase,
    ModuleBase,
    UnitBase,
    ComponentBase,
    InventoryBase,
    EntityBase,
    EntityStatusHistoryBase,
    MaintenanceLogBase,
    UserCommon,
    ProjectCommon,
    CustomerCommon,
    StatusCommon,
    OrderCommon,
    SystemCommon,
    SubsystemCommon,
    ModuleCommon,
    UnitCommon,
    ComponentCommon,
    InventoryCommon,
    InventoryInstanceCommon,
    InventoryInstanceBase,
    EntityCommon,
    EntityStatusHistoryCommon,
    MaintenanceLogCommon,
    HierarchyBase,
)


# ---- User ----

class UserCreate(UserBase):
    pass


class UserSignup(SQLModel):
    """Public self-registration payload. Accounts are always created inactive."""

    username: str
    password: str
    full_name: str
    email: Optional[str] = None


class UserSignupResponse(SQLModel):
    message: str
    username: str


class UserRead(UserBase):
    id: int
    projects: Optional[List["ProjectRead"]] = None
    roles: Optional[List["RoleRead"]] = None
    permissions: List[str] = []

    class Config:
        orm_mode = True

class UserUpdate(SQLModel):
    username: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class UserWithRoles(UserCommon):
    id: int
    roles: List[str]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    last_logout_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    failed_login_count: int = 0
    created_by_id: Optional[int] = None


class UserActivitySummary(SQLModel):
    last_login: Optional[datetime] = None
    last_logout: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    last_ip_address: Optional[str] = None
    last_device: Optional[str] = None
    browser: Optional[str] = None
    operating_system: Optional[str] = None
    total_login_count: int = 0
    failed_login_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by_id: Optional[int] = None
    is_active: bool = True


class UserStatsSummary(SQLModel):
    total_users: int = 0
    active_users: int = 0
    inactive_users: int = 0
    currently_logged_in: int = 0
    failed_logins_today: int = 0


class UserLoginHistoryRead(SQLModel):
    id: int
    user_id: Optional[int] = None
    username: str
    login_time: datetime
    logout_time: Optional[datetime] = None
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    device_name: Optional[str] = None
    browser: Optional[str] = None
    operating_system: Optional[str] = None
    login_status: str
    failure_reason: Optional[str] = None
    last_activity: Optional[datetime] = None
    session_duration: Optional[int] = None
    authentication_method: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class SecuritySettingsRead(SQLModel):
    id: int
    min_password_length: int
    password_expiry_days: int
    require_uppercase: bool
    require_lowercase: bool
    require_numbers: bool
    require_special: bool
    password_history_length: int
    max_login_attempts: int
    lockout_duration_minutes: int
    inactivity_deactivate_days: int
    two_factor_enabled: bool
    two_factor_require_all: bool
    two_factor_require_admins_only: bool
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class SecuritySettingsUpdate(SQLModel):
    min_password_length: Optional[int] = None
    password_expiry_days: Optional[int] = None
    require_uppercase: Optional[bool] = None
    require_lowercase: Optional[bool] = None
    require_numbers: Optional[bool] = None
    require_special: Optional[bool] = None
    password_history_length: Optional[int] = None
    max_login_attempts: Optional[int] = None
    lockout_duration_minutes: Optional[int] = None
    inactivity_deactivate_days: Optional[int] = None
    two_factor_enabled: Optional[bool] = None
    two_factor_require_all: Optional[bool] = None
    two_factor_require_admins_only: Optional[bool] = None


class AppDefinitionsRead(SQLModel):
    id: int
    serial_number_template: str
    part_number_template: str
    configuration_item_template: str
    sku_template: str
    label_project: str = "Project"
    label_projects: str = "Projects"
    abbrev_project: str = "PROJ"
    label_system: str
    label_systems: str
    label_subsystem: str
    label_subsystems: str
    label_module: str
    label_modules: str
    label_unit: str
    label_units: str
    label_component: str
    label_components: str
    abbrev_system: str = "SYS"
    abbrev_subsystem: str = "SUB"
    abbrev_module: str = "MOD"
    abbrev_unit: str = "UNIT"
    abbrev_component: str = "COMP"
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
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class AppDefinitionsUpdate(SQLModel):
    serial_number_template: Optional[str] = None
    part_number_template: Optional[str] = None
    configuration_item_template: Optional[str] = None
    sku_template: Optional[str] = None
    label_project: Optional[str] = None
    label_projects: Optional[str] = None
    abbrev_project: Optional[str] = None
    label_system: Optional[str] = None
    label_systems: Optional[str] = None
    label_subsystem: Optional[str] = None
    label_subsystems: Optional[str] = None
    label_module: Optional[str] = None
    label_modules: Optional[str] = None
    label_unit: Optional[str] = None
    label_units: Optional[str] = None
    label_component: Optional[str] = None
    label_components: Optional[str] = None
    abbrev_system: Optional[str] = None
    abbrev_subsystem: Optional[str] = None
    abbrev_module: Optional[str] = None
    abbrev_unit: Optional[str] = None
    abbrev_component: Optional[str] = None
    part_template_system: Optional[str] = None
    serial_template_system: Optional[str] = None
    part_template_subsystem: Optional[str] = None
    serial_template_subsystem: Optional[str] = None
    part_template_module: Optional[str] = None
    serial_template_module: Optional[str] = None
    part_template_unit: Optional[str] = None
    serial_template_unit: Optional[str] = None
    part_template_component: Optional[str] = None
    serial_template_component: Optional[str] = None
    inventory_label_code_type: Optional[str] = None
    inventory_qr_size_in: Optional[float] = None
    inventory_barcode_width_in: Optional[float] = None
    inventory_barcode_height_in: Optional[float] = None
    inventory_qr_sticker_width_in: Optional[float] = None
    inventory_qr_sticker_height_in: Optional[float] = None
    inventory_barcode_sticker_width_in: Optional[float] = None
    inventory_barcode_sticker_height_in: Optional[float] = None


class AuditLogRead(SQLModel):
    id: int
    actor_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    previous_value: Optional[str] = None
    new_value: Optional[str] = None
    details: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        orm_mode = True


class WorkflowAuditEventRead(SQLModel):
    id: str
    occurred_at: datetime
    actor_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    actor_role: str
    action: str
    action_label: Optional[str] = None
    entity_type: str
    entity_id: str
    project_id: Optional[int] = None
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
    remarks: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    correlation_id: Optional[str] = None

    class Config:
        orm_mode = True


class EntityLifecycleHistoryRead(SQLModel):
    """Unified history row for a hardware node's status and workflow lifecycle."""

    id: str
    occurred_at: datetime
    actor_user_id: Optional[int] = None
    actor_username: Optional[str] = None
    actor_role: str = "SYSTEM"
    action: str
    action_label: Optional[str] = None
    entity_type: str
    entity_id: str
    project_id: Optional[int] = None
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
    remarks: Optional[str] = None

    class Config:
        orm_mode = True


class WorkflowAuditActionCatalogItem(SQLModel):
    code: str
    label: str


class MaintenanceUserRead(UserCommon):
    """Nested user on maintenance endpoints — avoids loading projects/password."""
    id: int

    model_config = ConfigDict(from_attributes=True)


class CurrentUserRead(UserCommon):
    """Lightweight /auth/me response — no nested projects."""
    id: int
    created_at: datetime
    roles: List[str] = []
    permissions: List[str] = []

    model_config = ConfigDict(from_attributes=True)

# ---- Customer ----
class CustomerCreate(CustomerBase):
    status_id: Optional[int] = None 
    pass

class CustomerRead(CustomerBase):
    id: int
    customer_code: Optional[str] = None
    status_id: Optional[int] = None 
    name: str 
    status_name: Optional[str] = None 
    updated_at: Optional[datetime] = None
    orders: Optional[List["OrderRead"]] = None
    class Config:
        orm_mode = True

class CustomerUpdate(SQLModel):
    name: Optional[str] = None
    contact_info: Optional[str] = None
    status_id: Optional[int] = None 
    status_name: Optional[str] = None 
    organization_type: Optional[str] = None
    primary_contact_name: Optional[str] = None
    designation: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    address: Optional[str] = None
    country: Optional[str] = None
    notes: Optional[str] = None

# ---- Status ----
class StatusCreate(StatusBase):
    pass

class StatusRead(StatusBase):
    id: int
    class Config:
        orm_mode = True

class StatusUpdate(SQLModel):
    status_name: Optional[str] = None
    description: Optional[str] = None
    status_type: Optional[str] = None
    color: Optional[str] = None


class PasswordPolicyPublic(SQLModel):
    """Public subset of password rules for signup / change-password forms."""
    min_password_length: int
    require_uppercase: bool
    require_lowercase: bool
    require_numbers: bool
    require_special: bool
    password_history_length: int
    password_expiry_days: int


class ActiveSessionRead(SQLModel):
    id: int
    session_id: str
    user_id: Optional[int] = None
    username: str
    device_name: Optional[str] = None
    browser: Optional[str] = None
    operating_system: Optional[str] = None
    ip_address: Optional[str] = None
    login_time: datetime
    last_activity: Optional[datetime] = None
    status: str = "Active"
    is_current: bool = False

    class Config:
        orm_mode = True


class HierarchyCreate(HierarchyBase):
    pass

class HierarchyRead(HierarchyBase):
    id: int
    parent_name: Optional[str] = None
    class Config:
        orm_mode = True

class HierarchyUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    hierarchy_type: Optional[str] = None
    parent_id: Optional[int] = None
    abbreviation: Optional[str] = None

# ---- Order ----
class OrderCreate(OrderBase):
    pass

class OrderRead(OrderBase):
    id: int
    status_id: Optional[int] = None
    customer_id: int
    status_name: Optional[str] = None
    projects: Optional[List["ProjectRead"]] = None
    order_number: Optional[str] = None


    class Config:
        orm_mode = True

class OrderUpdate(SQLModel):
    customer_id: Optional[int] = None
    order_number: Optional[str] = None
    status_id: Optional[int] = None
    description: Optional[str] = None
    contract_number: Optional[str] = None
    po_number: Optional[str] = None
    order_date: Optional[datetime] = None
    delivery_date: Optional[datetime] = None
    total_value: Optional[Decimal] = None
    currency: Optional[str] = None
    project_manager: Optional[str] = None
    remarks: Optional[str] = None
    status_name: Optional[str] = None

# ---- Project ----
class ProjectCreate(ProjectBase):
    pass

class ProjectRead(ProjectBase):
    id: int
    order_id: Optional[int] = None
    status_id: Optional[int] = None
    status_name: Optional[str] = None
    owner_id: Optional[int] = None
    hierarchy_config_id: Optional[int] = None
    hierarchy_config_version: Optional[int] = None
    product_type: Optional[str] = None
    flight_count: Optional[int] = None
    sdls_per_flight: Optional[int] = None
    sdls_counts_by_flight: Optional[List[int]] = None
    assigned_hm_id: Optional[int] = None
    created_by_id: Optional[int] = None
    approved_by_id: Optional[int] = None
    approved_at: Optional[datetime] = None
    successor_project_id: Optional[int] = None
    predecessor_project_id: Optional[int] = None
    is_existing_project: bool = False
    systems: Optional[List["SystemRead"]] = None
    class Config:
        orm_mode = True

class ProjectUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    owner_id: Optional[int] = None
    order_id: Optional[int] = None
    status_id: Optional[int] = None
    progress: Optional[int] = Field(default=None, ge=0, le=100)
    hierarchy_config_id: Optional[int] = None
    hierarchy_config_version: Optional[int] = None
    product_type: Optional[str] = None
    flight_count: Optional[int] = None
    sdls_per_flight: Optional[int] = None
    sdls_counts_by_flight: Optional[List[int]] = None
    assigned_hm_id: Optional[int] = None
    is_existing_project: Optional[bool] = None


class ProjectDraftCreate(SQLModel):
    name: str
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    owner_id: Optional[int] = None
    order_id: Optional[int] = None
    assigned_hm_id: Optional[int] = None
    hierarchy_config_id: int
    product_type: str
    flight_count: int = Field(ge=1)
    sdls_per_flight: Optional[int] = Field(default=None, ge=1)
    sdls_counts_by_flight: Optional[List[int]] = None
    is_existing_project: bool = False


class ProjectDraftBulkCreateResponse(SQLModel):
    projects: List[ProjectRead]
    count: int


class ProjectAssignHmRequest(SQLModel):
    hm_user_id: int


class ProjectCancelRequest(SQLModel):
    confirm: bool = False
    notes: Optional[str] = None


class ProjectCancelPreview(SQLModel):
    project_id: int
    project_name: Optional[str] = None
    project_status: Optional[str] = None
    progress_pct: int = 0
    critical_path_unfinished: bool = False
    reserved_count: int = 0
    issued_count: int = 0
    in_progress_count: int = 0
    testing_count: int = 0
    verified_count: int = 0
    returned_pending_count: int = 0
    shortage_count: int = 0
    pending_request_count: int = 0
    open_rework_count: int = 0
    recall_units_total: int = 0


class ProjectCancelResult(SQLModel):
    project_id: int
    project_status: str
    critical_path_unfinished: bool = False
    reserved_released: int = 0
    shortages_cancelled: int = 0
    pending_requests_cancelled: int = 0
    rework_closed: int = 0
    recall_tasks_created: int = 0
    preview: Optional[ProjectCancelPreview] = None
    project: Optional["ProjectRead"] = None


class ConfigChangeRequestCreate(SQLModel):
    notes: Optional[str] = None


class ConfigChangeCancelRequest(SQLModel):
    notes: Optional[str] = None


class ConfigChangeSubmitRequest(SQLModel):
    target_hierarchy_config_id: int
    reason_remarks: str
    product_type: Optional[str] = None
    flight_count: Optional[int] = Field(default=None, ge=1)
    sdls_per_flight: Optional[int] = Field(default=None, ge=1)


class ConfigChangeCreateProjectRequest(SQLModel):
    name: Optional[str] = None
    product_type: Optional[str] = None
    flight_count: Optional[int] = Field(default=None, ge=1)
    sdls_per_flight: Optional[int] = Field(default=None, ge=1)


class ConfigChangeRequestRead(SQLModel):
    id: int
    source_project_id: int
    source_project_name: Optional[str] = None
    source_project_status: Optional[str] = None
    target_hierarchy_config_id: Optional[int] = None
    target_hierarchy_config_code: Optional[str] = None
    target_hierarchy_config_name: Optional[str] = None
    target_product_type: Optional[str] = None
    target_flight_count: Optional[int] = None
    target_sdls_per_flight: Optional[int] = None
    reason_remarks: Optional[str] = None
    status: str
    successor_project_id: Optional[int] = None
    successor_project_name: Optional[str] = None
    requested_by_id: Optional[int] = None
    requested_at: Optional[datetime] = None
    submitted_by_id: Optional[int] = None
    submitted_at: Optional[datetime] = None
    approved_by_id: Optional[int] = None
    approved_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    inventory_cleared: bool = False
    inventory_preview: Optional[ProjectCancelPreview] = None
    structural_frozen: bool = False
    project: Optional["ProjectRead"] = None
    successor_project: Optional["ProjectRead"] = None


class ConfigChangeCreateProjectResult(SQLModel):
    change: ConfigChangeRequestRead
    project: Optional["ProjectRead"] = None


class HierarchyGenerationCounts(SQLModel):
    flights: int = 0
    sdls: int = 0
    systems: int = 0
    subsystems: int = 0
    modules: int = 0
    units: int = 0
    components: int = 0


class HierarchyGenerationResult(SQLModel):
    ok: bool = True
    project_id: int
    status: str
    config_code: Optional[str] = None
    config_name: Optional[str] = None
    product_type: Optional[str] = None
    counts: HierarchyGenerationCounts
    shortages_created: int = 0
    project: Optional["ProjectRead"] = None


class HierarchyTreeComponentNode(SQLModel):
    id: int
    name: str


class HierarchyTreeUnitNode(SQLModel):
    id: int
    name: str
    components: List[HierarchyTreeComponentNode] = []


class HierarchyTreeModuleNode(SQLModel):
    id: int
    name: str
    units: List[HierarchyTreeUnitNode] = []


class HierarchyTreeSubsystemNode(SQLModel):
    id: int
    name: str
    modules: List[HierarchyTreeModuleNode] = []


class HierarchyTreeSystemNode(SQLModel):
    id: int
    name: str
    subsystem_count: int = 0
    subsystems: List[HierarchyTreeSubsystemNode] = []


class SdlsTreeNode(SQLModel):
    id: int
    name: str
    code: Optional[str] = None
    sequence: int = 1
    product_type: Optional[str] = None
    systems: List[HierarchyTreeSystemNode] = []


class FlightTreeNode(SQLModel):
    id: int
    name: str
    code: Optional[str] = None
    sequence: int = 1
    sdls: List[SdlsTreeNode] = []


class ProjectHierarchyTree(SQLModel):
    project_id: int
    status: Optional[str] = None
    flights: List[FlightTreeNode] = []


class ProgressSystemNode(SQLModel):
    entity_type: str = "system"
    entity_id: int
    name: str
    weight: int = 0
    progress_pct: int = 0
    verified_leaves: int = 0
    status: Optional[str] = None


class ProgressSdlsNode(SQLModel):
    entity_type: str = "sdls"
    entity_id: int
    name: str
    code: Optional[str] = None
    product_type: Optional[str] = None
    weight: int = 0
    progress_pct: int = 0
    verified_leaves: int = 0
    systems: List[ProgressSystemNode] = []


class ProgressFlightNode(SQLModel):
    entity_type: str = "flight"
    entity_id: int
    name: str
    code: Optional[str] = None
    weight: int = 0
    progress_pct: int = 0
    verified_leaves: int = 0
    sdls: List[ProgressSdlsNode] = []


class ProgressBottleneck(SQLModel):
    entity_type: str
    entity_id: int
    name: str
    path: str
    status: Optional[str] = None
    defect_pending: bool = False
    weight: int = 0
    reason: str


class ProjectProgressRead(SQLModel):
    project_id: int
    project_status: Optional[str] = None
    progress_pct: int = 0
    weight: int = 0
    verified_leaves: int = 0
    can_complete: bool = False
    stage_policy: str = "lifecycle_fractions"
    flights: List[ProgressFlightNode] = []
    bottlenecks: List[ProgressBottleneck] = []


# ---- System / Subsystem / Module / Unit / Component ----
class SystemCreate(SystemBase):
    status_id: Optional[int] = None
    status_name: Optional[str] = None

class SystemRead(SystemBase):
    id: int
    project_id: int
    sdls_id: Optional[int] = None
    sdls_number: Optional[int] = None
    status_id: Optional[int] = None
    status_name: Optional[str] = None
    subsystems: Optional[List["SubsystemRead"]] = None

    class Config:
        orm_mode = True

class SystemUpdate(SQLModel):
    project_id: Optional[int] = None
    sdls_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    status_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None
    installation_date: Optional[datetime] = None
    installed_by_id: Optional[int] = None
    picture_url: Optional[str] = None
    original_part_number: Optional[str] = None
    original_serial_number: Optional[str] = None

class SubsystemCreate(SubsystemBase):
    system_id: int
    status_id: Optional[int] = None


class SubsystemRead(SubsystemBase):
    id: int
    system_id: int
    status_id: Optional[int] = None
    status_name: Optional[str] = None
    modules: Optional[List["ModuleRead"]] = None

    class Config:
        orm_mode = True

class SubsystemUpdate(SQLModel):
    system_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    status_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None
    installation_date: Optional[datetime] = None
    installed_by_id: Optional[int] = None
    picture_url: Optional[str] = None
    original_part_number: Optional[str] = None
    original_serial_number: Optional[str] = None

class ModuleCreate(ModuleBase):
    subsystem_id: int
    status_id: Optional[int] = None

class ModuleRead(ModuleBase):
    id: int
    subsystem_id: int
    status_id: Optional[int] = None
    status_name: Optional[str] = None
    units: Optional[List["UnitRead"]] = None

    class Config:
        orm_mode = True

class ModuleUpdate(SQLModel):
    subsystem_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    status_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None
    installation_date: Optional[datetime] = None
    installed_by_id: Optional[int] = None
    picture_url: Optional[str] = None
    original_part_number: Optional[str] = None
    original_serial_number: Optional[str] = None

class UnitCreate(UnitBase):
    module_id: Optional[int] = None
    status_id: Optional[int] = None

class UnitRead(UnitBase):
    id: int
    module_id: Optional[int] = None
    status_id: Optional[int] = None
    status_name: Optional[str] = None
    components: Optional[List["ComponentRead"]] = None

    class Config:
        orm_mode = True

class UnitUpdate(SQLModel):
    module_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    status_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None
    installation_date: Optional[datetime] = None
    installed_by_id: Optional[int] = None
    picture_url: Optional[str] = None
    original_part_number: Optional[str] = None
    original_serial_number: Optional[str] = None

class ComponentCreate(ComponentBase):
    unit_id: Optional[int] = None
    status_id: Optional[int] = None

class ComponentRead(ComponentBase):
    id: int
    unit_id: Optional[int] = None
    status_id: Optional[int] = None
    status_name: Optional[str] = None
    inventory_items: Optional[List["InventoryRead"]] = None

    class Config:
        orm_mode = True

class ComponentUpdate(SQLModel):
    unit_id: Optional[int] = None
    name: Optional[str] = None
    sku: Optional[str] = None
    description: Optional[str] = None
    status_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None
    installation_date: Optional[datetime] = None
    installed_by_id: Optional[int] = None
    picture_url: Optional[str] = None
    original_part_number: Optional[str] = None
    original_serial_number: Optional[str] = None

# ---- Inventory ----
class InventoryInstanceCreate(InventoryInstanceCommon):
    pass


class FCFSFulfillmentRead(SQLModel):
    shortage_id: int
    reservation_id: Optional[int] = None
    project_id: int
    project_name: Optional[str] = None
    part_number: Optional[str] = None
    qty_applied: int = 1
    shortage_status: str
    serial_number: Optional[str] = None
    flight_name: Optional[str] = None
    sdls_name: Optional[str] = None
    lru_name: Optional[str] = None


class InventoryProjectHoldRead(SQLModel):
    """Active Spec 04/06 HM reservation attached to a serialized inventory unit."""
    id: int
    project_id: int
    project_name: Optional[str] = None
    flight_id: int
    flight_code: Optional[str] = None
    flight_name: Optional[str] = None
    sdls_id: int
    sdls_code: Optional[str] = None
    sdls_name: Optional[str] = None
    target_entity_type: str
    target_entity_id: int
    target_entity_name: Optional[str] = None
    reserved_by_user_id: int
    reserved_by_name: Optional[str] = None
    reserved_at: datetime
    expires_at: datetime
    last_reminder_at: Optional[datetime] = None
    serial_number: Optional[str] = None
    part_number: Optional[str] = None
    inventory_name: Optional[str] = None

    class Config:
        orm_mode = True


class InventoryInstanceRead(InventoryInstanceBase):
    id: int
    inventory_id: int
    is_reserved: bool = False
    is_project_reserved: bool = False
    status_name: Optional[str] = None
    project_reservation: Optional[InventoryProjectHoldRead] = None
    open_issuance_id: Optional[int] = None
    open_issuance_status: Optional[str] = None
    fcfs_fulfillments: Optional[List[FCFSFulfillmentRead]] = None

    class Config:
        orm_mode = True


class InventoryInstanceUpdate(SQLModel):
    serial_number: Optional[str] = None
    configuration_item: Optional[str] = None
    status_id: Optional[int] = None
    holder_user_id: Optional[int] = None
    location: Optional[str] = None
    added_date: Optional[datetime] = None
    shelf_life_expires_at: Optional[datetime] = None
    picture_url: Optional[str] = None
    installation_date: Optional[datetime] = None
    installed_by_id: Optional[int] = None
    original_part_number: Optional[str] = None
    original_serial_number: Optional[str] = None


class InventoryLabelTarget(SQLModel):
    inventory_id: int
    inventory_instance_id: Optional[int] = None
    serial_number: Optional[str] = None


class InventoryLabelGenerateRequest(SQLModel):
    targets: List[InventoryLabelTarget] = Field(default_factory=list, min_length=1)
    label_type: str = Field(default="qr", pattern="^(qr|barcode|both)$")


class InventoryLabelGenerateAllRequest(SQLModel):
    label_type: str = Field(default="both", pattern="^(qr|barcode|both)$")


class InventoryLabelRead(SQLModel):
    id: int
    label_id: str
    signed_payload: str
    barcode_payload: str
    inventory_id: int
    inventory_instance_id: Optional[int] = None
    serial_number: Optional[str] = None
    inventory_name: Optional[str] = None
    part_number: Optional[str] = None
    label_type: str
    status: str
    print_count: int
    first_printed_at: Optional[datetime] = None
    last_printed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class InventoryLabelPrintRequest(SQLModel):
    label_ids: List[str] = Field(default_factory=list, min_length=1)
    label_format: str = Field(default="standard", min_length=1, max_length=32)
    quantity: int = Field(default=1, ge=1, le=1000)
    reason: Optional[str] = Field(default=None, max_length=500)


class InventoryLabelPrintEventRead(SQLModel):
    id: int
    label_id: str
    user_id: int
    printed_at: datetime
    reason: Optional[str] = None
    label_type: str
    label_format: str
    quantity: int
    is_first_print: bool


class InventoryLabelHistoryRead(SQLModel):
    label: InventoryLabelRead
    print_events: List[InventoryLabelPrintEventRead] = Field(default_factory=list)
    scan_events: List[dict] = Field(default_factory=list)


class InventoryLabelScanRequest(SQLModel):
    payload: str = Field(min_length=1, max_length=2048)
    location: Optional[str] = Field(default=None, max_length=255)
    source: str = Field(default="web", max_length=32)


class InventoryLabelActionRequest(SQLModel):
    reason: str = Field(min_length=1, max_length=500)


class InventoryLabelReplaceRequest(InventoryLabelActionRequest):
    label_type: str = Field(default="qr", pattern="^(qr|barcode|both)$")


class InventoryLabelScanResponse(SQLModel):
    valid: bool
    status: str
    message: str
    warnings: List[str] = Field(default_factory=list)
    label: Optional[InventoryLabelRead] = None
    inventory: Optional[dict] = None
    stock_history: List[dict] = Field(default_factory=list)
    build_history: List[dict] = Field(default_factory=list)
    maintenance_history: List[dict] = Field(default_factory=list)
    ownership_location_history: List[dict] = Field(default_factory=list)
    hierarchy: Optional[dict] = None
    print_history: List[InventoryLabelPrintEventRead] = Field(default_factory=list)


class InventoryCreate(InventoryBase):
    pass


class InventoryShortageReceiveRequest(SQLModel):
    quantity: int = Field(default=1, ge=1)
    part_number: Optional[str] = None
    serial_numbers: List[str] = Field(default_factory=list)
    location: Optional[str] = None


class InventoryRead(InventoryBase):
    id: int
    instances: Optional[List[InventoryInstanceRead]] = None
    reserved_quantity: int = 0
    available_quantity: Optional[int] = None
    total_used: int = 0
    fcfs_fulfillments: Optional[List[FCFSFulfillmentRead]] = None

    class Config:
        orm_mode = True

class InventoryConsumeRequest(SQLModel):
    instance_id: Optional[int] = None
    issuance_id: Optional[int] = None
    installed_entity_type: Optional[str] = None
    installed_entity_id: Optional[int] = None


class InventoryIssueRequest(SQLModel):
    issued_to_user_id: int
    quantity: int = 1
    instance_id: Optional[int] = None
    target_entity_type: Optional[str] = None
    target_entity_id: Optional[int] = None
    notes: Optional[str] = None
    signature_type: str
    signature_payload: Optional[str] = None
    item_request_id: Optional[int] = None


class InventoryIssuanceRead(SQLModel):
    id: int
    inventory_id: int
    inventory_instance_id: Optional[int] = None
    quantity: int
    issued_to_user_id: int
    issued_by_user_id: int
    issued_at: datetime
    status: str
    target_entity_type: Optional[str] = None
    target_entity_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    inventory_name: Optional[str] = None
    inventory_type: Optional[str] = None
    notes: Optional[str] = None
    installed_at: Optional[datetime] = None
    installed_entity_type: Optional[str] = None
    installed_entity_id: Optional[int] = None
    installed_by_id: Optional[int] = None
    closed_at: Optional[datetime] = None
    closed_by_id: Optional[int] = None
    return_requested_at: Optional[datetime] = None
    signature_type: Optional[str] = None
    display_status: Optional[str] = None
    has_signature_attachment: bool = False
    has_proforma_attachment: bool = False
    signature_attachment_id: Optional[int] = None
    proforma_attachment_id: Optional[int] = None
    item_request_id: Optional[int] = None
    reservation_id: Optional[int] = None
    project_id: Optional[int] = None
    flight_id: Optional[int] = None
    sdls_id: Optional[int] = None
    item_lifecycle_status: Optional[str] = None
    verified_at: Optional[datetime] = None
    issued_to_name: Optional[str] = None
    issued_by_name: Optional[str] = None
    installed_by_name: Optional[str] = None
    closed_by_name: Optional[str] = None

    class Config:
        orm_mode = True


class InventoryIssuanceReturnRequest(SQLModel):
    notes: str


class InventoryIssuanceSignatureRead(SQLModel):
    signature_type: Optional[str] = None
    has_signature_attachment: bool = False
    has_proforma_attachment: bool = False
    signature_attachment_id: Optional[int] = None
    proforma_attachment_id: Optional[int] = None
    signature_file_name: Optional[str] = None
    proforma_file_name: Optional[str] = None
    signature_mime_type: Optional[str] = None
    proforma_mime_type: Optional[str] = None


class InventoryIssuanceEventRead(SQLModel):
    id: Optional[int] = None
    issuance_id: int
    inventory_id: Optional[int] = None
    inventory_instance_id: Optional[int] = None
    event_type: str
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
    created_at: datetime

    class Config:
        orm_mode = True


class InventoryIssuanceLinkInstallRequest(SQLModel):
    installed_entity_type: str
    installed_entity_id: int


class InventoryRevertToStockRequest(SQLModel):
    entity_type: str
    entity_id: int
    notes: Optional[str] = None


class InventoryRevertToStockRead(SQLModel):
    inventory: InventoryRead
    restored_instance: Optional[InventoryInstanceRead] = None
    issuance: Optional[InventoryIssuanceRead] = None


class InventoryReturnNoticeRead(SQLModel):
    id: int
    issuance_id: int
    inventory_id: Optional[int] = None
    inventory_name: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    returned_by_user_id: int
    returned_by_name: Optional[str] = None
    created_at: datetime
    read_at: Optional[datetime] = None
    decision: Optional[str] = None
    decided_at: Optional[datetime] = None
    decided_by_id: Optional[int] = None
    decision_notes: Optional[str] = None
    request_notes: Optional[str] = None

    class Config:
        orm_mode = True


class InventoryInstallerNoticeRead(SQLModel):
    id: int
    user_id: int
    notice_type: str
    issuance_id: Optional[int] = None
    inventory_id: Optional[int] = None
    inventory_name: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    message: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    read_at: Optional[datetime] = None
    user_name: Optional[str] = None

    class Config:
        orm_mode = True


class InventoryChildLinkItem(SQLModel):
    child_category_name: str
    child_inventory_id: int
    child_instance_id: Optional[int] = None
    parent_instance_serial: Optional[str] = None
    child_instance_serial: Optional[str] = None
    stock_consumed: bool = False


class InventoryChildLinkRead(InventoryChildLinkItem):
    id: int
    parent_inventory_id: int
    parent_instance_id: Optional[int] = None

    class Config:
        orm_mode = True


class InventoryChildrenReplace(SQLModel):
    parent_instance_id: Optional[int] = None
    parent_instance_serial: Optional[str] = None
    children: List[InventoryChildLinkItem] = []


class InventoryConsumeRead(SQLModel):
    inventory: InventoryRead
    consumed_instance: Optional[InventoryInstanceRead] = None
    issuance: Optional[InventoryIssuanceRead] = None

class InventoryIdsRead(SQLModel):
    ids: List[int] = Field(default_factory=list)


class InventoryStatsSummary(SQLModel):
    total_catalog_items: int = 0
    available_units: int = 0
    reserved_issued_open_units: int = 0
    out_of_stock_catalog_items: int = 0
    out_of_stock_top_names: List[str] = Field(default_factory=list)
    open_shortages: int = 0
    open_shortage_top_names: List[str] = Field(default_factory=list)
    pending_issue_requests: int = 0
    return_pending_inspect: int = 0


class InventoryBulkDeleteRequest(SQLModel):
    ids: List[int] = Field(default_factory=list)


class InventoryBulkDeleteRead(SQLModel):
    deleted: int = 0
    not_found: List[int] = Field(default_factory=list)


class InventoryUpdate(SQLModel):
    name: Optional[str] = None
    inventory_type: Optional[str] = None
    serial_number: Optional[str] = None
    quantity: Optional[int] = None
    description: Optional[str] = None
    oem_name: Optional[str] = None
    part_number: Optional[str] = None
    configuration_item: Optional[str] = None
    status_id: Optional[int] = None
    sku: Optional[str] = None
    location: Optional[str] = None
    entity_id: Optional[int] = None
    holder_user_id: Optional[int] = None
    added_date: Optional[datetime] = None
    shelf_life_expires_at: Optional[datetime] = None
    picture_url: Optional[str] = None
    installation_date: Optional[datetime] = None
    installed_by_id: Optional[int] = None
    original_part_number: Optional[str] = None
    original_serial_number: Optional[str] = None

class EntityAttachmentRead(SQLModel):
    id: int
    owner_type: str
    owner_id: int
    file_name: str
    file_path: str
    mime_type: Optional[str] = None
    attachment_type: str
    description: Optional[str] = None
    uploaded_by_id: Optional[int] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True

class EntityAttachmentUpdate(SQLModel):
    attachment_type: Optional[str] = None
    description: Optional[str] = None

# ---- Entity / History / Maintenance ----
class EntityCreate(EntityBase):
    status_id: Optional[int] = None
    pass

class EntityRead(EntityBase):
    id: int
    status_id: Optional[int] = None
    status_history: Optional[List["EntityStatusHistoryRead"]] = None
    maintenance_logs: Optional[List["MaintenanceLogRead"]] = None
    class Config:
        orm_mode = True

class EntityUpdate(SQLModel):
    entity_type: Optional[str] = None
    entity_pk: Optional[int] = None
    display_name: Optional[str] = None
    status_id: Optional[int] = None

class EntityStatusHistoryCreate(EntityStatusHistoryBase):
    pass

class EntityStatusHistoryRead(EntityStatusHistoryBase):
    id: int
    class Config:
        orm_mode = True

class EntityStatusHistoryUpdate(SQLModel):
    entity_id: Optional[int] = None
    status_id: Optional[int] = None
    changed_by: Optional[int] = None
    notes: Optional[str] = None

class MaintenanceLogCreate(MaintenanceLogBase):
    pass

class MaintenanceLogRead(MaintenanceLogBase):
    id: int
    entity_id: Optional[int] = None
    performed_by: Optional[int] = None
    notes: Optional[str] = None
    performed_at: Optional[datetime] = None
    next_due: Optional[datetime] = None
    performed_by_user: Optional[UserRead] = None

    class Config:
        orm_mode = True

class MaintenanceLogUpdate(SQLModel):
    entity_id: Optional[int] = None
    performed_by: Optional[int] = None
    notes: Optional[str] = None
    next_due: Optional[datetime] = None






# ---- Authentication & Authorization ----

class PermissionRead(SQLModel):
    id: int
    name: str
    description: Optional[str] = None
    
    class Config:
        orm_mode = True


class PermissionCreate(SQLModel):
    name: str
    description: Optional[str] = None


class PermissionUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None


class RoleCreate(SQLModel):
    name: str
    description: Optional[str] = None
    permission_ids: Optional[List[int]] = None


class RoleRead(SQLModel):
    id: int
    name: str
    description: Optional[str] = None
    permissions: Optional[List[PermissionRead]] = None
    user_count: Optional[int] = None
    
    class Config:
        orm_mode = True


class RoleUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission_ids: Optional[List[int]] = None


class RolePermissionsUpdate(SQLModel):
    permission_ids: List[int] = []


class TokenResponse(SQLModel):
    access_token: str
    token_type: str
    user_id: int
    username: str
    email: Optional[str] = None
    roles: List[str] = []
    permissions: List[str] = []
    session_id: Optional[str] = None


class LoginRequest(SQLModel):
    username: str
    password: str


class ChangePasswordRequest(SQLModel):
    old_password: str
    new_password: str


class AssignRoleRequest(SQLModel):
    user_id: int
    role_id: int


class UserReadWithRoles(UserRead):
    roles: Optional[List[RoleRead]] = None
    
    class Config:
        orm_mode = True

# ---- Spec 01 Hierarchy Configuration ----
class HierarchyConfigProductTypeIn(SQLModel):
    code: str
    name: str
    description: Optional[str] = None
    sort_order: int = 0


class HierarchyConfigNodeIn(SQLModel):
    client_key: str
    parent_client_key: Optional[str] = None
    level: str
    name: str
    description: Optional[str] = None
    abbreviation: Optional[str] = None
    sort_order: int = 0
    inventory_source: str = "turnkey"


class HierarchyConfigurationCreate(SQLModel):
    code: str
    name: str
    description: Optional[str] = None
    notes: Optional[str] = None
    is_available: bool = True
    product_types: List[HierarchyConfigProductTypeIn]
    nodes: List[HierarchyConfigNodeIn] = []


class HierarchyConfigurationUpdate(SQLModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    is_available: Optional[bool] = None
    product_types: Optional[List[HierarchyConfigProductTypeIn]] = None
    nodes: Optional[List[HierarchyConfigNodeIn]] = None


class HierarchyConfigProductTypeRead(SQLModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    sort_order: int = 0

    class Config:
        orm_mode = True


class HierarchyConfigNodeRead(SQLModel):
    id: int
    client_key: Optional[str] = None
    parent_id: Optional[int] = None
    parent_client_key: Optional[str] = None
    level: str
    name: str
    description: Optional[str] = None
    abbreviation: Optional[str] = None
    sort_order: int = 0
    inventory_source: str = "turnkey"

    class Config:
        orm_mode = True


class HierarchyConfigurationRead(SQLModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    notes: Optional[str] = None
    is_available: bool
    version: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by_id: Optional[int] = None
    product_types: List[HierarchyConfigProductTypeRead] = []
    nodes: List[HierarchyConfigNodeRead] = []

    class Config:
        orm_mode = True


class HierarchyConfigurationSummary(SQLModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    is_available: bool
    version: int
    product_type_codes: List[str] = []

    class Config:
        orm_mode = True


# ---- Spec 04 — Inventory reservations ----
class InventoryReservationCreate(SQLModel):
    target_entity_type: str
    target_entity_id: int
    flight_id: Optional[int] = None
    sdls_id: Optional[int] = None
    inventory_id: Optional[int] = None
    inventory_instance_id: Optional[int] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    expires_at: Optional[datetime] = None
    notes: Optional[str] = None


class InventoryReservationRead(SQLModel):
    id: int
    project_id: int
    flight_id: int
    sdls_id: int
    target_entity_type: str
    target_entity_id: int
    inventory_id: int
    inventory_instance_id: Optional[int] = None
    reserved_by_user_id: int
    reserved_at: datetime
    expires_at: datetime
    last_reminder_at: Optional[datetime] = None
    extension_count: int = 0
    auto_release_at: Optional[datetime] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    status: str
    released_at: Optional[datetime] = None
    released_by_user_id: Optional[int] = None
    notes: Optional[str] = None
    flight_code: Optional[str] = None
    flight_name: Optional[str] = None
    sdls_code: Optional[str] = None
    sdls_name: Optional[str] = None
    inventory_name: Optional[str] = None
    reserved_by_name: Optional[str] = None

    class Config:
        orm_mode = True


class InventoryShortageRead(SQLModel):
    id: int
    project_id: int
    flight_id: int
    sdls_id: int
    target_entity_type: str
    target_entity_id: int
    inventory_id: Optional[int] = None
    part_number: Optional[str] = None
    suggested_part_number: Optional[str] = None
    suggested_serial_number: Optional[str] = None
    qty_short: int
    qty_original: int
    lru_name: Optional[str] = None
    requested_by_user_id: int
    requested_at: datetime
    status: str
    last_notified_at: Optional[datetime] = None
    fulfilled_reservation_id: Optional[int] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by_user_id: Optional[int] = None
    notes: Optional[str] = None
    project_name: Optional[str] = None
    flight_code: Optional[str] = None
    flight_name: Optional[str] = None
    sdls_code: Optional[str] = None
    sdls_name: Optional[str] = None
    requested_by_name: Optional[str] = None

    class Config:
        orm_mode = True


class InventoryShortageNoticeRead(SQLModel):
    id: int
    user_id: int
    shortage_id: int
    notice_type: str
    part_number: Optional[str] = None
    qty: int = 1
    flight_code: Optional[str] = None
    flight_name: Optional[str] = None
    sdls_code: Optional[str] = None
    sdls_name: Optional[str] = None
    lru_name: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    message: Optional[str] = None
    created_at: datetime
    read_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class InventoryReservationExpiryNoticeRead(SQLModel):
    id: int
    user_id: int
    reservation_id: int
    notice_type: str
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    flight_code: Optional[str] = None
    flight_name: Optional[str] = None
    sdls_code: Optional[str] = None
    sdls_name: Optional[str] = None
    inventory_name: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    message: Optional[str] = None
    created_at: datetime
    read_at: Optional[datetime] = None

    class Config:
        orm_mode = True


class ReservationExpiryJobResult(SQLModel):
    examined: int = 0
    reminded: int = 0
    released: int = 0
    skipped_progressed: int = 0


class ReserveOutcome(SQLModel):
    outcome: str
    reservation: Optional[InventoryReservationRead] = None
    shortage: Optional[InventoryShortageRead] = None


class InventoryAvailabilityCheck(SQLModel):
    available: bool
    free_quantity: Optional[int] = None
    inventory_id: Optional[int] = None
    inventory_name: Optional[str] = None
    part_number: Optional[str] = None
    serial_numbers: Optional[List[str]] = None
    flight_id: Optional[int] = None
    sdls_id: Optional[int] = None
    system_id: Optional[int] = None
    reservation_id: Optional[int] = None
    issuance_id: Optional[int] = None
    item_status: Optional[str] = None
    plan_status: Optional[str] = None
    reason: Optional[str] = None
    assemble: bool = False
    inventory_source: Optional[str] = None


class ReservationPlanItem(SQLModel):
    target_entity_type: str
    target_entity_id: int
    entity_name: str
    path: str
    depth: int = 0
    status: str  # available | short | reserved | assemble | issued | installing | testing | verified
    available: bool = False
    reason: Optional[str] = None
    free_quantity: Optional[int] = None
    inventory_id: Optional[int] = None
    inventory_name: Optional[str] = None
    part_number: Optional[str] = None
    serial_numbers: Optional[List[str]] = None
    suggested_serial: Optional[str] = None
    reservation_id: Optional[int] = None
    issuance_id: Optional[int] = None
    item_status: Optional[str] = None
    flight_id: Optional[int] = None
    sdls_id: Optional[int] = None
    system_id: Optional[int] = None
    inventory_source: Optional[str] = None
    children_total: Optional[int] = None
    children_complete: Optional[int] = None
    assigned_developer_id: Optional[int] = None
    assigned_developer_name: Optional[str] = None
    can_assign_developer: bool = False
    assembled: bool = False
    issued: bool = False


class ReservationPlan(SQLModel):
    project_id: int
    project_status: Optional[str] = None
    total: int = 0
    available_count: int = 0
    short_count: int = 0
    reserved_count: int = 0
    assemble_count: int = 0
    items: List[ReservationPlanItem] = []


class HierarchyAssignDeveloperRequest(SQLModel):
    developer_user_id: Optional[int] = None


class HierarchyAssignDeveloperRead(SQLModel):
    entity_type: str
    id: int
    name: Optional[str] = None
    assigned_developer_id: Optional[int] = None
    assigned_developer_name: Optional[str] = None
    issued: Optional[bool] = None


class HierarchyAssignmentStatusRead(SQLModel):
    entity_type: str
    id: int
    name: Optional[str] = None
    assigned_developer_id: Optional[int] = None
    assigned_developer_name: Optional[str] = None
    issued: bool = False
    issuance_id: Optional[int] = None
    item_status: Optional[str] = None
    test_result: Optional[str] = None
    complete_reported: bool = False
    defect_pending: bool = False
    verified: bool = False
    can_install: bool = False
    can_test: bool = False
    can_report_complete: bool = False
    rework_id: Optional[int] = None
    rework_status: Optional[str] = None
    rework_stage: Optional[str] = None
    rework_attempt_count: Optional[int] = None
    rework_cycle_warning: bool = False
    rework_disposition: Optional[str] = None
    can_remove: bool = False
    can_return: bool = False


class DeveloperAssignedWorkRead(SQLModel):
    entity_type: str
    entity_id: int
    name: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    assigned_developer_id: int
    reserved: bool = False
    reservation_id: Optional[int] = None
    request_status: str = "none"
    issued: bool = False
    can_request: bool = False
    pending_request_id: Optional[int] = None
    issuance_id: Optional[int] = None
    item_status: Optional[str] = None
    test_result: Optional[str] = None
    complete_reported: bool = False
    complete_reported_at: Optional[datetime] = None
    defect_pending: bool = False
    verified: bool = False
    verified_at: Optional[datetime] = None
    installed_at: Optional[datetime] = None
    can_install: bool = False
    can_test: bool = False
    can_report_complete: bool = False
    rework_id: Optional[int] = None
    rework_status: Optional[str] = None
    rework_stage: Optional[str] = None
    rework_attempt_count: Optional[int] = None
    rework_cycle_warning: bool = False
    rework_disposition: Optional[str] = None
    can_remove: bool = False
    can_return: bool = False


class ItemInstallNotesBody(SQLModel):
    notes: Optional[str] = None


class ItemInstallTestBody(SQLModel):
    result: str
    notes: Optional[str] = None


class ItemInstallStateRead(SQLModel):
    issuance_id: int
    entity_type: str
    entity_id: int
    entity_name: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    serial_number: Optional[str] = None
    part_number: Optional[str] = None
    assigned_developer_id: Optional[int] = None
    assigned_developer_name: Optional[str] = None
    item_status: Optional[str] = None
    test_result: Optional[str] = None
    complete_reported: bool = False
    complete_reported_at: Optional[datetime] = None
    defect_pending: bool = False
    verified: bool = False
    verified_at: Optional[datetime] = None
    installed_at: Optional[datetime] = None
    can_install: bool = False
    can_test: bool = False
    can_report_complete: bool = False
    rework_id: Optional[int] = None
    rework_status: Optional[str] = None
    rework_stage: Optional[str] = None
    rework_attempt_count: Optional[int] = None
    rework_cycle_warning: bool = False
    rework_disposition: Optional[str] = None
    can_remove: bool = False
    can_return: bool = False


class ItemReworkNotesBody(SQLModel):
    notes: Optional[str] = None


class ItemReworkDispositionBody(SQLModel):
    outcome: str
    notes: Optional[str] = None


class ItemReworkReissueBody(SQLModel):
    signature_type: str
    signature_payload: Optional[str] = None
    replacement_instance_id: Optional[int] = None
    notes: Optional[str] = None


class ItemReworkEventRead(SQLModel):
    id: int
    issuance_id: int
    event_type: str
    actor_name: Optional[str] = None
    notes: Optional[str] = None
    serial_number: Optional[str] = None
    created_at: Optional[datetime] = None


class ItemReworkCaseRead(SQLModel):
    id: int
    project_id: int
    project_name: Optional[str] = None
    flight_id: Optional[int] = None
    sdls_id: Optional[int] = None
    target_entity_type: str
    target_entity_id: int
    target_entity_name: Optional[str] = None
    inventory_id: int
    inventory_name: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    original_instance_id: Optional[int] = None
    current_instance_id: Optional[int] = None
    current_issuance_id: Optional[int] = None
    assigned_developer_id: Optional[int] = None
    assigned_developer_name: Optional[str] = None
    status: str
    stage: str
    attempt_count: int
    cycle_warning: bool = False
    disposition: Optional[str] = None
    repaired_at: Optional[datetime] = None
    item_status: Optional[str] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    notes: Optional[str] = None
    updated_at: Optional[datetime] = None
    events: Optional[List[ItemReworkEventRead]] = None


class InventoryRecallNotesBody(SQLModel):
    notes: Optional[str] = None


class InventoryRecallDispositionBody(SQLModel):
    outcome: str
    notes: Optional[str] = None


class InventoryRecallTaskRead(SQLModel):
    id: int
    project_id: int
    project_name: Optional[str] = None
    flight_id: Optional[int] = None
    sdls_id: Optional[int] = None
    target_entity_type: Optional[str] = None
    target_entity_id: Optional[int] = None
    target_entity_name: Optional[str] = None
    inventory_id: int
    inventory_name: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    inventory_instance_id: Optional[int] = None
    issuance_id: Optional[int] = None
    assigned_developer_id: Optional[int] = None
    assigned_developer_name: Optional[str] = None
    status: str
    stage: str
    disposition: Optional[str] = None
    forced_return: bool = False
    item_status: Optional[str] = None
    opened_at: Optional[datetime] = None
    returned_at: Optional[datetime] = None
    inspected_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    notes: Optional[str] = None
    updated_at: Optional[datetime] = None
    can_return: bool = False
    can_inspect: bool = False
    can_disposition: bool = False


class ItemIssueRequestTarget(SQLModel):
    entity_type: str
    entity_id: int


class ItemIssueRequestBulkCreate(SQLModel):
    mode: str
    items: Optional[List[ItemIssueRequestTarget]] = None
    notes: Optional[str] = None


class ItemIssueRequestBulkSkipped(SQLModel):
    entity_type: str
    entity_id: int
    reason: str


class ItemIssueRequestCreate(SQLModel):
    entity_type: str
    entity_id: int
    notes: Optional[str] = None


class ItemIssueRequestIssueBody(SQLModel):
    signature_type: str
    signature_payload: Optional[str] = None
    notes: Optional[str] = None


class ItemIssueRequestRead(SQLModel):
    id: int
    project_id: int
    project_name: Optional[str] = None
    flight_id: int
    flight_code: Optional[str] = None
    flight_name: Optional[str] = None
    sdls_id: int
    sdls_code: Optional[str] = None
    sdls_name: Optional[str] = None
    target_entity_type: str
    target_entity_id: int
    target_entity_name: Optional[str] = None
    assigned_developer_id: int
    assigned_developer_name: Optional[str] = None
    requested_by_user_id: int
    requested_by_name: Optional[str] = None
    inventory_id: int
    inventory_instance_id: Optional[int] = None
    inventory_name: Optional[str] = None
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    reservation_id: int
    status: str
    requested_at: datetime
    issued_at: Optional[datetime] = None
    issued_issuance_id: Optional[int] = None
    notes: Optional[str] = None

    class Config:
        orm_mode = True


class ItemIssueRequestBulkResult(SQLModel):
    created: List[ItemIssueRequestRead] = []
    skipped: List[ItemIssueRequestBulkSkipped] = []


class IssueProgressJobResult(SQLModel):
    examined: int = 0
    flipped: int = 0
    skipped: int = 0
