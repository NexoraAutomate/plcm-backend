from .base import *
from typing import List, Optional
from sqlmodel import Column, Field, Relationship
import sqlalchemy as sa
from enum import Enum
from sqlalchemy import Enum as SQLEnum
from app.models.base import ConfigurationHistoryBase

class UserRole(SQLModel, table=True):
    user_id: Optional[int] = Field(default=None, foreign_key="user.id", primary_key=True)
    role_id: Optional[int] = Field(default=None, foreign_key="role.id", primary_key=True)

class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    roles: List["Role"] = Relationship(back_populates="users", link_model=UserRole)
    projects: List["Project"] = Relationship(back_populates="owner")
    status_changes: List["EntityStatusHistory"] = Relationship(back_populates="changed_by_user")
    maintenances: List["MaintenanceLog"] = Relationship(back_populates="performed_by_user")
    reported_cases: List["MaintenanceCase"] = Relationship(back_populates="reported_by_user")
    maintenance_actions: List["MaintenanceAction"] = Relationship(back_populates="performed_by_user")
    deliveries: List["MaintenanceDelivery"] = Relationship(back_populates="delivered_by_user")
    identified_faults: List["FaultyEntity"] = Relationship(back_populates="identified_by_user")

class RolePermission(SQLModel, table=True):
    role_id: Optional[int] = Field(default=None, foreign_key="role.id", primary_key=True)
    permission_id: Optional[int] = Field(default=None, foreign_key="permission.id", primary_key=True)

class Role(RoleBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    permissions: List["Permission"] = Relationship(back_populates="roles", link_model=RolePermission)
    users: List["User"] = Relationship(back_populates="roles", link_model=UserRole)

class Permission(PermissionBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    roles: List["Role"] = Relationship(back_populates="permissions", link_model=RolePermission)

class Hierarchy(HierarchyBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    parent_id: Optional[int] = Field(default=None, foreign_key="hierarchy.id")

class Status(StatusBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # reverse relationships
    orders: List["Order"] = Relationship(back_populates="status")
    customers: List["Customer"] = Relationship(back_populates="status")
    projects: List["Project"] = Relationship(back_populates="status")
    systems: List["System"] = Relationship(back_populates="status")
    subsystems: List["Subsystem"] = Relationship(back_populates="status")
    modules: List["Module"] = Relationship(back_populates="status")
    units: List["Unit"] = Relationship(back_populates="status")
    components: List["Component"] = Relationship(back_populates="status")
    entities: List["Entity"] = Relationship(back_populates="status")
    history_records: List["EntityStatusHistory"] = Relationship(back_populates="status")
    maintenance_cases: List["MaintenanceCase"]= Relationship(back_populates="m_status")
    maintenance_deliveries: List["MaintenanceDelivery"]= Relationship(back_populates="m_status")
    faulty_entities: List["FaultyEntity"]= Relationship(back_populates="m_status")

class Customer(CustomerBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_code: Optional[str] = Field(index=True, unique=True)
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")
    orders: List["Order"] = Relationship(back_populates="customer", 
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)
    status: Optional[Status] = Relationship(back_populates="customers")

class Order(OrderBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_number: Optional[str] = Field(index=True, unique=True)
    customer_id: int = Field(foreign_key="customer.id", ondelete="CASCADE")
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")
    customer: Optional[Customer] = Relationship(back_populates="orders")
    status: Optional[Status] = Relationship(back_populates="orders")
    projects: List["Project"] = Relationship(back_populates="order", 
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            }, )

class Project(ProjectBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: Optional[int] = Field(default=None, foreign_key="order.id", ondelete="CASCADE")
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")
    owner_id: Optional[int] = Field(default=None, foreign_key="user.id")
    owner: Optional["User"] = Relationship(back_populates="projects")
    order: Optional["Order"] = Relationship(back_populates="projects")
    status: Optional[Status] = Relationship(back_populates="projects")
    systems: List["System"] = Relationship(back_populates="project",
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)
    maintenance_cases: List["MaintenanceCase"] = Relationship(back_populates="project", 
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)

class System(SystemBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", ondelete="CASCADE")
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")
    project: Optional[Project] = Relationship(back_populates="systems")
    
    status: Optional[Status] = Relationship(back_populates="systems")
    subsystems: List["Subsystem"] = Relationship(back_populates="system", 
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)

class Subsystem(SubsystemBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    system_id: int = Field(foreign_key="system.id", ondelete="CASCADE")
    status_id: Optional[int] = Field(default=None, foreign_key="status.id", ondelete="CASCADE")
    system: Optional[System] = Relationship(back_populates="subsystems")
    status: Optional[Status] = Relationship(back_populates="subsystems")
    modules: List["Module"] = Relationship(back_populates="subsystem", 
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)

class Module(ModuleBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    subsystem_id: int = Field(foreign_key="subsystem.id", ondelete="CASCADE")
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")
    subsystem: Optional[Subsystem] = Relationship(back_populates="modules")
    status: Optional[Status] = Relationship(back_populates="modules")
    units: List["Unit"] = Relationship(back_populates="module", 
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)

class Unit(UnitBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    module_id: int = Field(foreign_key="module.id", ondelete="CASCADE")
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")
    module: Optional[Module] = Relationship(back_populates="units")
    status: Optional[Status] = Relationship(back_populates="units")
    components: List["Component"] = Relationship(back_populates="unit", 
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)

class Component(ComponentBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    unit_id: int = Field(foreign_key="unit.id", ondelete="CASCADE")
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")
    unit: Optional[Unit] = Relationship(back_populates="components")
    status: Optional[Status] = Relationship(back_populates="components")

class Entity(EntityBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")
    status: Optional["Status"] = Relationship(back_populates="entities")
    configuration_history: list["ConfigurationHistory"] = Relationship(back_populates="entity",sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)
    status_history: List["EntityStatusHistory"] = Relationship(back_populates="entity", 
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)
    maintenance_logs: List["MaintenanceLog"] = Relationship(back_populates="entity")

class MaintenanceLog(MaintenanceLogBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="entity.id")
    # test case
    performed_by: Optional[int] = Field(default=None, foreign_key="user.id")
    entity: Optional[Entity] = Relationship(back_populates="maintenance_logs")
    performed_by_user: Optional[User] = Relationship(back_populates="maintenances")

class EntityStatusHistory(EntityStatusHistoryBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: int = Field(foreign_key="entity.id")
    status_id: int = Field(foreign_key="status.id")
    status: Optional["Status"] = Relationship(back_populates="history_records")
    changed_by: Optional[int] = Field(default=None, foreign_key="user.id")
    entity: Optional[Entity] = Relationship(back_populates="status_history")
    changed_by_user: Optional[User] = Relationship(back_populates="status_changes")

class Inventory(InventoryBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entity_id: Optional[int] = Field(default=None, index=True)

class MaintenanceCase(MaintenanceCaseBase, table=True):
    """
    PostgreSQL table: maintenance_case
    One row per fault event reported against a delivered project.
    """ 
    __tablename__ = "maintenance_case"

    id:            Optional[int] = Field(default=None, primary_key=True)
    case_number:   str           = Field(unique=False, index=True, max_length=50, description="Auto-generated. Format: MC-YYYY-NNNN")
    project_id:    int           = Field(foreign_key="project.id", ondelete="CASCADE")
    reported_by:   Optional[int] = Field(default=None, foreign_key="user.id")
    configuration_history: List["ConfigurationHistory"] = Relationship(
    back_populates="maintenance_case",sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },
)
    status:        CaseStatus    = Field(sa_column=sa.Column(sa.Enum(CaseStatus,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="casestatus",
                native_enum=True,
            ),
            nullable=False,
            server_default=sa.text("'open'::casestatus"),
        ),
        default=CaseStatus.OPEN,
    )
    status_id: Optional[int]   = Field(default=None, foreign_key="status.id")
    m_status: Optional[Status]   = Relationship(back_populates="maintenance_cases")

    # Relationships
    project:          Optional[Project]           = Relationship(back_populates="maintenance_cases")
    reported_by_user: Optional[User]              = Relationship(back_populates="reported_cases")
    faulty_entities:  List["FaultyEntity"]        = Relationship(back_populates="case", 
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)
    deliveries:       List["MaintenanceDelivery"] = Relationship(back_populates="case", 
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)
    
class MaintenanceAction(MaintenanceActionBase, table=True):
    """
    PostgreSQL table: maintenance_action
    One row per action performed on a faulty entity.
    """
    __tablename__ = "maintenance_action"

    id:               Optional[int] = Field(default=None, primary_key=True)
    faulty_entity_id: int           = Field(foreign_key="faulty_entity.id", index=True,  ondelete="CASCADE")
    performed_by:     Optional[int] = Field(default=None, foreign_key="user.id")
    action_type:      ActionType    = Field(
        sa_column=sa.Column(
            sa.Enum(
                ActionType,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="actiontype",
                native_enum=True,
            ),
            nullable=False,
        ),
    )
    outcome:          Optional[ActionOutcome] = Field(
        sa_column=sa.Column(
            sa.Enum(
                ActionOutcome,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="actionoutcome",
                native_enum=True,
            ),
            nullable=True,
        ),
        default=None,
    )
    replacement_entity_type: Optional[EntityType] = Field(
        sa_column=sa.Column(
            sa.Enum(
                EntityType,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="entitytype",
                native_enum=True,
            ),
            nullable=True,
        ),
        default=None,
    )
    
    # Relationships
    faulty_entity:    Optional[FaultyEntity] = Relationship(back_populates="actions")
    performed_by_user: Optional[User]        = Relationship(back_populates="maintenance_actions")

class MaintenanceDelivery(MaintenanceDeliveryBase, table=True):
    """
    PostgreSQL table: maintenance_delivery
    One row per dispatch/delivery event against a maintenance case.
    """
    __tablename__ = "maintenance_delivery"

    id:           Optional[int] = Field(default=None, primary_key=True)
    case_id:      int           = Field(foreign_key="maintenance_case.id", index=True, ondelete="CASCADE")
    delivered_by: Optional[int] = Field(default=None, foreign_key="user.id")
    delivery_type: DeliveryType = Field(
        sa_column=sa.Column(
            sa.Enum(
                DeliveryType,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="deliverytype",
                native_enum=True,
            ),
            nullable=False,
            server_default=sa.text("'re_delivery'::deliverytype"),
        ),
        default=DeliveryType.RE_DELIVERY,
    )
    status: DeliveryStatus = Field(
        sa_column=sa.Column(
            sa.Enum(
                DeliveryStatus,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="deliverystatus",
                native_enum=True,
            ),
            nullable=False,
            server_default=sa.text("'pending'::deliverystatus"),
        ),
        default=DeliveryStatus.PENDING,
    )
    created_at:   datetime      = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    status_id: Optional[int] = Field(default=None, foreign_key="status.id")
    m_status: Optional[Status] = Relationship(back_populates="maintenance_deliveries")

    # Relationships
    case:              Optional[MaintenanceCase] = Relationship(back_populates="deliveries")
    delivered_by_user: Optional[User]           = Relationship(back_populates="deliveries")

class FaultyEntity(FaultyEntityBase, table=True):
    
    """
    PostgreSQL table: faulty_entity
    One row per affected entity within a maintenance case.+

    Self-referencing via parent_faulty_entity_id to model the cascade chain.
    SQLModel requires sa_relationship_kwargs with remote_side for self-refs.
    """
    __tablename__ = "faulty_entity"

    id: Optional[int]                      = Field(default=None, primary_key=True)
    status: FaultyEntityStatus             = Field(
        default=FaultyEntityStatus.IDENTIFIED,
        sa_column=sa.Column(
            sa.Enum(
                FaultyEntityStatus,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="faultyentitystatus",
                native_enum=True,
            ),
            nullable=False,
        ),
    )
    status_id: Optional[int]               = Field(default=None, foreign_key="status.id")
    m_status: Optional[Status]             = Relationship(back_populates="faulty_entities")
    case_id:int                            = Field(foreign_key="maintenance_case.id", index=True, ondelete="CASCADE")
    identified_by:Optional[int]            = Field(default=None, foreign_key="user.id")
    parent_faulty_entity_id: Optional[int] = Field(
        default=None,
        foreign_key="faulty_entity.id",
        description="FK to self — links this row to its parent in the cascade chain."
    )
    parent_entity_id: Optional[int] = Field(default=None)
    parent_entity_type: Optional[EntityType] = Field(
        default=None,
        sa_column=sa.Column(
            sa.Enum(
                EntityType,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="entitytype",
                native_enum=True,
            ),
            nullable=True,
        ),
    )
    hierarchy_parent_entity_id: Optional[int] = Field(default=None)
    hierarchy_parent_entity_type: Optional[EntityType] = Field(
        default=None,
        sa_column=sa.Column(
            sa.Enum(
                EntityType,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="entitytype",
                native_enum=True,
            ),
            nullable=True,
        ),
    )
    depth: Optional[int] = Field(default=None)
    entity_type: EntityType = Field(
        sa_column=sa.Column(
            sa.Enum(
                EntityType,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="entitytype",
                native_enum=True,
            ),
            nullable=False,
        ),
    )
    fault_type: FaultType = Field(
        sa_column=sa.Column(
            sa.Enum(
                FaultType,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="faulttype",
                native_enum=True,
            ),
            nullable=False,
        ),
    )

    # Relationships
    case:             Optional[MaintenanceCase]  = Relationship(back_populates="faulty_entities")
    identified_by_user: Optional[User]           = Relationship(back_populates="identified_faults")
    actions:          List["MaintenanceAction"]  = Relationship(back_populates="faulty_entity", 
                                         sa_relationship_kwargs={
                                            "cascade": "all, delete-orphan",
                                            "passive_deletes": True,
                                            },)

    # Self-referential: parent / children
    # remote_side points to the PK column (the "one" side of one-to-many).
    children: List["FaultyEntity"] = Relationship(
        back_populates="parent",
        sa_relationship_kwargs={
            "foreign_keys":  "[FaultyEntity.parent_faulty_entity_id]",
        }
    )
    parent: Optional["FaultyEntity"] = Relationship(
        back_populates="children",
        sa_relationship_kwargs={
            "foreign_keys": "[FaultyEntity.parent_faulty_entity_id]",
            "remote_side":  "[FaultyEntity.id]",
        }
    )

# Table created to maintain history of items replaced of a given project
class ConfigurationHistory(ConfigurationHistoryBase,table=True):

    __tablename__ = "configuration_history"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Override base fields so PostgreSQL faulttype receives lowercase values (electrical), not names (ELECTRICAL).
    fault_type: Optional[FaultType] = Field(
        default=None,
        sa_column=sa.Column(
            sa.Enum(
                FaultType,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="faulttype",
                native_enum=True,
            ),
            nullable=True,
        ),
    )

    entity: "Entity" = Relationship(back_populates="configuration_history")

    maintenance_case: Optional["MaintenanceCase"] = Relationship(back_populates="configuration_history")

    performed_by_user: Optional["User"] = Relationship(sa_relationship_kwargs=dict(foreign_keys="[ConfigurationHistory.performed_by]")    )

    approved_by_user: Optional["User"] = Relationship(sa_relationship_kwargs=dict(foreign_keys="[ConfigurationHistory.approved_by]")    )

    verified_by_user: Optional["User"] = Relationship(sa_relationship_kwargs=dict(foreign_keys="[ConfigurationHistory.verified_by]")    )


class EntityAttachment(SQLModel, table=True):
    __tablename__ = "entity_attachment"

    id: Optional[int] = Field(default=None, primary_key=True)
    owner_type: str = Field(index=True)
    owner_id: int = Field(index=True)
    file_name: str
    file_path: str
    mime_type: Optional[str] = None
    attachment_type: AttachmentType = Field(
        sa_column=sa.Column(
            sa.Enum(
                AttachmentType,
                values_callable=lambda entries: [entry.value for entry in entries],
                name="attachmenttype",
                native_enum=True,
            ),
            nullable=False,
            server_default=sa.text("'other'::attachmenttype"),
        ),
        default=AttachmentType.OTHER,
    )
    description: Optional[str] = None
    uploaded_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

