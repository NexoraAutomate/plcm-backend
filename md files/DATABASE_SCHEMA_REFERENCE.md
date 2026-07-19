# PLCM Database Schema Reference

**Version:** 1.0  
**Last Updated:** March 28, 2026  
**Purpose:** Complete field reference for frontend developers to validate JSON against SQLModel fields

---

## Table of Contents
1. [Quick Schema Overview](#quick-schema-overview)
2. [Authentication & Authorization Tables](#authentication--authorization-tables)
3. [Core Entity Tables](#core-entity-tables)
4. [Project Hierarchy Tables](#project-hierarchy-tables)
5. [Supporting Tables](#supporting-tables)
6. [Relationship Diagram](#relationship-diagram)
7. [Field Type Reference](#field-type-reference)
8. [API Response Examples](#api-response-examples)

---

## Quick Schema Overview

```
Total Tables: 19
- Authentication & Authorization: 5 tables (User, Role, Permission, UserRole, RolePermission)
- Core Entities: 5 tables (Entity, Status, Order, Customer, MaintenanceLog)
- Project Hierarchy: 6 tables (Project, System, Subsystem, Module, Unit, Component)
- Supporting: 3 tables (Inventory, EntityStatusHistory, (implicitly through relationships))
```

---

## Authentication & Authorization Tables

### 1. User
**Primary Table for User Authentication**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique user identifier |
| `username` | String | ✓ | No | None | None | Username for login (must be unique) |
| `email` | String | ✗ | Yes | None | None | User email address |
| `full_name` | String | ✗ | Yes | None | None | User's full name |
| `password` | String | ✓ | No | None | None | Bcrypt-hashed password (72 bytes max) |
| `is_active` | Boolean | ✗ | No | True | None | Account active status |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Account creation timestamp |

**Relationships:**
- `roles` → [Role] (Many-to-Many via UserRole junction table)
- `projects` → [Project] (One-to-Many: user owns projects)
- `status_changes` → [EntityStatusHistory] (One-to-Many: user changed statuses)
- `maintenances` → [MaintenanceLog] (One-to-Many: user performed maintenance)

**Example JSON Response:**
```json
{
  "id": 1,
  "username": "john.doe",
  "email": "john@example.com",
  "full_name": "John Doe",
  "is_active": true,
  "created_at": "2026-03-28T10:30:00Z",
  "roles": [
    {
      "id": 1,
      "name": "Admin",
      "description": "Full system access",
      "created_at": "2026-03-28T10:00:00Z",
      "permissions": [...]
    }
  ],
  "projects": [...]
}
```

---

### 2. Role
**Authorization Role Definition**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique role identifier |
| `name` | String | ✓ | No | None | None | Role name (e.g., "Admin", "Viewer") |
| `description` | String | ✗ | Yes | None | None | Role description |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Role creation timestamp |

**Relationships:**
- `permissions` → [Permission] (Many-to-Many via RolePermission junction table)
- `users` → [User] (Many-to-Many via UserRole junction table)

**Default Roles (Auto-created):**
1. **Admin** - Full system access, all permissions
2. **ProjectManager** - Project and team management
3. **Technician** - System and component management
4. **Viewer** - Read-only access (default for new users)

**Example JSON Response:**
```json
{
  "id": 1,
  "name": "Admin",
  "description": "Full system access",
  "created_at": "2026-03-28T10:00:00Z",
  "permissions": [
    {
      "id": 1,
      "name": "view_users",
      "description": "Can view all users",
      "created_at": "2026-03-28T10:00:00Z"
    }
  ]
}
```

---

### 3. Permission
**Fine-Grained Access Control**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique permission identifier |
| `name` | String | ✓ | No | None | None | Permission name (e.g., "create_project") |
| `description` | String | ✗ | Yes | None | None | Permission description |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Permission creation timestamp |

**Relationships:**
- `roles` → [Role] (Many-to-Many via RolePermission junction table)

**Default Permissions (20+):**
```
User Management:
  - view_users, create_users, edit_users, delete_users

Project Management:
  - view_projects, create_projects, edit_projects, delete_projects, assign_project_manager

System Management:
  - view_systems, create_systems, edit_systems, delete_systems

Component Management:
  - view_components, create_components, edit_components, delete_components

Inventory Management:
  - view_inventory, create_inventory, edit_inventory, delete_inventory

Maintenance Management:
  - view_maintenance, create_maintenance, edit_maintenance, delete_maintenance

Entity Management:
  - view_entities, create_entities, edit_entities, delete_entities

Status Management:
  - view_statuses, create_statuses, edit_statuses, delete_statuses
  - view_status_history, create_status_history, edit_status_history, delete_status_history

Reports:
  - view_reports, export_reports

Roles:
  - view_roles, create_roles, edit_roles, delete_roles
```

---

### 4. UserRole (Junction Table)
**Many-to-Many: User ↔ Role**

| Field | Type | Required | Nullable | Primary Key | Foreign Key | Description |
|-------|------|----------|----------|-------------|-------------|-------------|
| `user_id` | Integer | ✓ | No | Yes (composite) | user.id | Reference to User |
| `role_id` | Integer | ✓ | No | Yes (composite) | role.id | Reference to Role |

**Example:** User 1 has Role 1 and Role 2

---

### 5. RolePermission (Junction Table)
**Many-to-Many: Role ↔ Permission**

| Field | Type | Required | Nullable | Primary Key | Foreign Key | Description |
|-------|------|----------|----------|-------------|-------------|-------------|
| `role_id` | Integer | ✓ | No | Yes (composite) | role.id | Reference to Role |
| `permission_id` | Integer | ✓ | No | Yes (composite) | permission.id | Reference to Permission |

**Example:** Role 1 (Admin) has all permissions, Role 4 (Viewer) has only view permissions

---

## Core Entity Tables

### 6. Customer
**Customer Information**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique customer identifier |
| `name` | String | ✓ | No | None | None | Customer company/organization name |
| `contact_info` | String | ✗ | Yes | None | None | Contact info (email, phone, address) |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Record creation timestamp |

**Relationships:**
- `orders` → [Order] (One-to-Many: customer has multiple orders)

**Example JSON Response:**
```json
{
  "id": 1,
  "name": "Acme Corporation",
  "contact_info": "contact@acme.com | 555-1234",
  "created_at": "2026-03-28T10:30:00Z",
  "orders": [
    {
      "id": 1,
      "order_number": "ORD-001",
      "status_id": 1,
      "status_name": "Active"
    }
  ]
}
```

---

### 7. Status
**Entity Status/State Information**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique status identifier |
| `name` | String | ✓ | No | None | None | Status name (e.g., "Active", "Inactive") |
| `description` | String | ✗ | Yes | None | None | Status description |
| `status_type` | String | ✗ | Yes | None | None | Type of status (internal classifier) |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Record creation timestamp |

**Relationships:**
- `orders` → [Order] (One-to-Many)
- `projects` → [Project] (One-to-Many)
- `systems` → [System] (One-to-Many)
- `subsystems` → [Subsystem] (One-to-Many)
- `modules` → [Module] (One-to-Many)
- `units` → [Unit] (One-to-Many)
- `components` → [Component] (One-to-Many)
- `entities` → [Entity] (One-to-Many)
- `history_records` → [EntityStatusHistory] (One-to-Many)

**Example JSON Response:**
```json
{
  "id": 1,
  "name": "Active",
  "description": "Resource is currently active and operational",
  "status_type": "operational",
  "created_at": "2026-03-28T10:00:00Z"
}
```

---

### 8. Order
**Customer Order/Request**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique order identifier |
| `customer_id` | Integer | ✓ | No | None | customer.id | Reference to Customer |
| `order_number` | String | ✗ | Yes | None | None | Custom order reference number |
| `status_id` | Integer | ✗ | Yes | None | status.id | Current order status |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Order creation timestamp |

**Relationships:**
- `customer` → Customer (Many-to-One)
- `status` → Status (Many-to-One)
- `projects` → [Project] (One-to-Many: order contains projects)

**Example JSON Response:**
```json
{
  "id": 1,
  "customer_id": 1,
  "order_number": "ORD-2026-001",
  "status_id": 1,
  "status_name": "Active",
  "created_at": "2026-03-28T10:30:00Z",
  "customer": {
    "id": 1,
    "name": "Acme Corp",
    "contact_info": "contact@acme.com"
  },
  "status": {
    "id": 1,
    "name": "Active"
  },
  "projects": [...]
}
```

---

### 9. Entity
**Generic Entity for Tracking Status History**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique entity identifier |
| `name` | String | ✓ | No | None | None | Entity name |
| `display_name` | String | ✗ | Yes | None | None | Human-readable display name |
| `entity_type` | String | ✓ | No | None | None | Type of entity (Project, System, etc.) |
| `entity_pk` | Integer | ✓ | No | None | None | Primary key of actual entity |
| `status_id` | Integer | ✗ | Yes | None | status.id | Current entity status |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Record creation timestamp |

**Relationships:**
- `status` → Status (Many-to-One)
- `status_history` → [EntityStatusHistory] (One-to-Many)
- `maintenance_logs` → [MaintenanceLog] (One-to-Many)

**Usage:** Tracks entities like Projects, Systems, etc. for historical purposes

---

### 10. MaintenanceLog
**Maintenance Activity Record**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique log identifier |
| `entity_id` | Integer | ✓ | No | None | entity.id | Reference to Entity being maintained |
| `notes` | String | ✗ | Yes | None | None | Maintenance notes/description |
| `next_due` | DateTime | ✗ | Yes | None | None | Next scheduled maintenance date |
| `performed_at` | DateTime | ✗ | No | UTC Now | None | When maintenance was performed |
| `performed_by` | Integer | ✗ | Yes | None | user.id | User who performed maintenance |

**Relationships:**
- `entity` → Entity (Many-to-One)
- `performed_by_user` → User (Many-to-One)

**Example JSON Response:**
```json
{
  "id": 1,
  "entity_id": 1,
  "notes": "Routine maintenance completed. All systems operational.",
  "performed_at": "2026-03-28T14:00:00Z",
  "next_due": "2026-04-28T14:00:00Z",
  "performed_by": 1,
  "performed_by_user": {
    "id": 1,
    "username": "john.doe",
    "full_name": "John Doe"
  }
}
```

---

## Project Hierarchy Tables

The PLCM system follows a strict hierarchical structure:
```
Project
  └─ System
      └─ Subsystem
          └─ Module
              └─ Unit
                  └─ Component
                      └─ Inventory
```

### 11. Project
**Top-Level Project**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique project identifier |
| `name` | String | ✓ | No | None | None | Project name |
| `description` | String | ✗ | Yes | None | None | Project description |
| `start_date` | DateTime | ✓ | No | None | None | Project start date |
| `end_date` | DateTime | ✗ | Yes | None | None | Project end date |
| `owner_id` | Integer | ✗ | Yes | None | user.id | Project owner/manager |
| `order_id` | Integer | ✗ | Yes | None | order.id | Associated customer order |
| `status_id` | Integer | ✗ | Yes | None | status.id | Current project status |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Record creation timestamp |
| `updated_at` | DateTime | ✗ | No | UTC Now | None | Last update timestamp |

**Relationships:**
- `owner` → User (Many-to-One)
- `order` → Order (Many-to-One)
- `status` → Status (Many-to-One)
- `systems` → [System] (One-to-Many: project contains systems)

---

### 12. System
**System within Project**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique system identifier |
| `name` | String | ✓ | No | None | None | System name |
| `description` | String | ✗ | Yes | None | None | System description |
| `project_id` | Integer | ✓ | No | None | project.id | Parent project |
| `status_id` | Integer | ✗ | Yes | None | status.id | Current system status |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Record creation timestamp |

**Relationships:**
- `project` → Project (Many-to-One)
- `status` → Status (Many-to-One)
- `subsystems` → [Subsystem] (One-to-Many)

---

### 13. Subsystem
**Subsystem within System**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique subsystem identifier |
| `name` | String | ✓ | No | None | None | Subsystem name |
| `description` | String | ✗ | Yes | None | None | Subsystem description |
| `system_id` | Integer | ✓ | No | None | system.id | Parent system |
| `status_id` | Integer | ✗ | Yes | None | status.id | Current subsystem status |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Record creation timestamp |

**Relationships:**
- `system` → System (Many-to-One)
- `status` → Status (Many-to-One)
- `modules` → [Module] (One-to-Many)

---

### 14. Module
**Module within Subsystem**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique module identifier |
| `name` | String | ✓ | No | None | None | Module name |
| `description` | String | ✗ | Yes | None | None | Module description |
| `subsystem_id` | Integer | ✓ | No | None | subsystem.id | Parent subsystem |
| `status_id` | Integer | ✗ | Yes | None | status.id | Current module status |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Record creation timestamp |

**Relationships:**
- `subsystem` → Subsystem (Many-to-One)
- `status` → Status (Many-to-One)
- `units` → [Unit] (One-to-Many)

---

### 15. Unit
**Unit within Module**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique unit identifier |
| `name` | String | ✓ | No | None | None | Unit name |
| `description` | String | ✗ | Yes | None | None | Unit description |
| `module_id` | Integer | ✓ | No | None | module.id | Parent module |
| `status_id` | Integer | ✗ | Yes | None | status.id | Current unit status |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Record creation timestamp |

**Relationships:**
- `module` → Module (Many-to-One)
- `status` → Status (Many-to-One)
- `components` → [Component] (One-to-Many)

---

### 16. Component
**Component within Unit**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique component identifier |
| `name` | String | ✓ | No | None | None | Component name (part name) |
| `description` | String | ✗ | Yes | None | None | Component description |
| `sku` | String | ✗ | Yes | None | None | Stock Keeping Unit (part number) |
| `unit_id` | Integer | ✓ | No | None | unit.id | Parent unit |
| `status_id` | Integer | ✗ | Yes | None | status.id | Current component status |
| `created_at` | DateTime | ✗ | No | UTC Now | None | Record creation timestamp |

**Relationships:**
- `unit` → Unit (Many-to-One)
- `status` → Status (Many-to-One)
- `inventory_items` → [Inventory] (One-to-Many)

---

## Supporting Tables

### 17. Inventory
**Stock Management for Components**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique inventory record ID |
| `component_id` | Integer | ✓ | No | None | component.id | Reference to Component |
| `quantity` | Integer | ✓ | No | 0 | None | Current stock quantity |
| `location` | String | ✗ | Yes | None | None | Storage location (warehouse, shelf, etc.) |
| `updated_at` | DateTime | ✗ | No | UTC Now | None | Last update timestamp |

**Relationships:**
- `component` → Component (Many-to-One)

**Example JSON Response:**
```json
{
  "id": 1,
  "component_id": 1,
  "quantity": 50,
  "location": "Warehouse A - Shelf B3",
  "updated_at": "2026-03-28T14:15:00Z"
}
```

---

### 18. EntityStatusHistory
**Status Change History Tracking**

| Field | Type | Required | Nullable | Default | Foreign Key | Description |
|-------|------|----------|----------|---------|-------------|-------------|
| `id` | Integer | ✓ | No | Auto-increment | Primary Key | Unique history record ID |
| `entity_id` | Integer | ✓ | No | None | entity.id | Reference to Entity |
| `status_id` | Integer | ✓ | No | None | status.id | New status |
| `changed_by` | Integer | ✗ | Yes | None | user.id | User who made the change |
| `notes` | String | ✗ | Yes | None | None | Reason or notes for status change |
| `changed_at` | DateTime | ✗ | No | UTC Now | None | When status changed |

**Relationships:**
- `entity` → Entity (Many-to-One)
- `status` → Status (Many-to-One)
- `changed_by_user` → User (Many-to-One)

**Example JSON Response:**
```json
{
  "id": 1,
  "entity_id": 1,
  "status_id": 2,
  "changed_by": 1,
  "notes": "Project moved to in-progress status",
  "changed_at": "2026-03-28T10:45:00Z",
  "changed_by_user": {
    "id": 1,
    "username": "john.doe"
  },
  "status": {
    "id": 2,
    "name": "In Progress"
  }
}
```

---

## Relationship Diagram

```
                          ┌─────────────────────────────────────────┐
                          │         AUTHENTICATION LAYER             │
                          ├─────────────────────────────────────────┤
                          │                                           │
        ┌─────────────┐   │   ┌────────────┐  ┌────────────┐        │
        │ UserRole    │───┼───│   User     │  │    Role    │        │
        │  (M2M)      │   │   └────────────┘  └────────────┘        │
        └─────────────┘   │         │               │                │
                          │         │          RolePermission        │
                          │     (owns)         (M2M)                 │
                          │         │               │                │
                          │         └───────┬───────┘                │
                          │                 │                         │
                          │           ┌─────────────┐                │
                          │           │ Permission  │                │
                          │           └─────────────┘                │
                          │                                           │
                          └─────────────────────────────────────────┘
                                          │
                                          ▼
                    ┌─────────────────────────────────────┐
                    │      CUSTOMER & ORDER MANAGEMENT    │
                    ├─────────────────────────────────────┤
    ┌──────────┐    │                                     │
    │Customer  │◄───┼──────────┐                          │
    └──────────┘    │          │                          │
        │ (has)     │      ┌─────────┐                    │
        │           │      │ Order   │                    │
        └──────────►└──────│         │◄─────┐             │
                   │      └─────────┘       │             │
                   │          │      (has many)          │
                   │          │             │             │
                   └──────────┼─────────────┴─────────────┘
                              │
                              ▼
                    ┌─────────────────────────────────────┐
                    │   PROJECT HIERARCHY (Main Structure)│
                    ├─────────────────────────────────────┤
                    │                                     │
                    │  ┌─────────────────────────────┐   │
                    │  │     Project (L1)            │   │
                    │  │  owner_id → User            │   │
                    │  │  order_id → Order           │   │
                    │  │  status_id → Status         │   │
                    │  └──────────┬──────────────────┘   │
                    │             │                      │
                    │             ├─(has many)─► System (L2)
                    │             │              │
                    │             │              ├─(has many)─► Subsystem (L3)
                    │             │              │              │
                    │             │              │              ├─(has many)─► Module (L4)
                    │             │              │              │             │
                    │             │              │              │             ├─(has many)─► Unit (L5)
                    │             │              │              │             │             │
                    │             │              │              │             │             ├─(has many)─► Component (L6)
                    │             │              │              │             │             │             │
                    │             ▼              ▼              ▼             ▼             ▼             ▼
                    │         ┌────────┐    ┌──────────┐  ┌────────────┐  ┌──────┐  ┌─────────┐  ┌────────┐
                    │         │ Status │    │ System   │  │ Subsystem  │  │Module│  │  Unit   │  │Component
                    │         └────────┘    │ status_id│  │ status_id  │  │      │  │  status │  │ status_id
                    │             ▲         └──────────┘  └────────────┘  └──────┘  │  _id    │  └────────┘
                    │             │                                                  └─────────┘       │
                    │             │                                                                    │
                    │             └────────────────────────────────────────────────────────────────────┘
                    │
                    └─────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────────────────────────┐
                    │      SUPPORTING FEATURES            │
                    ├─────────────────────────────────────┤
                    │                                     │
        ┌──────────────────────┐    ┌─────────────────┐ │
        │ Component (L6)       │◄───┼─ Inventory      │ │
        │ has many inventory   │    │ quantity        │ │
        └──────────────────────┘    │ location        │ │
              │                     └─────────────────┘ │
              │                                          │
              │                                          │
              │         ┌─────────────────────┐         │
              └────────►│ Entity              │         │
                        │ entity_type: string │         │
                        │ entity_pk: int      │         │
                        │ status_id: int      │         │
                        └────────────┬────────┘         │
                                     │                  │
              ┌──────────────────────┴──────────────────┤
              │                                          │
              ├─(has many)─► EntityStatusHistory        │
              │              • changed_by → User         │
              │              • status_id → Status        │
              │              • changed_at: timestamp    │
              │                                          │
              └─(has many)─► MaintenanceLog              │
                             • performed_by → User       │
                             • performed_at: timestamp   │
                             • next_due: timestamp       │
                             • notes: string             │
                                                         │
                    └─────────────────────────────────────┘
```

---

## Field Type Reference

### Data Types Used

| Type | Description | Example | SQL Type |
|------|-------------|---------|----------|
| `Integer` | Whole numbers | 1, 100, -5 | INTEGER / BIGINT |
| `String` | Text data | "John Doe", "ORD-001" | VARCHAR / TEXT |
| `Boolean` | True/False | true, false | BOOLEAN |
| `DateTime` | Date and time | "2026-03-28T10:30:00Z" | TIMESTAMP |
| `Optional[T]` | Can be null | null or value | TYPE NULL |
| `List[T]` | Array of objects | [...] | Relationship |

### Field Constraints

- **` ✓ Required`**: Must be provided in create request
- **`✗ Optional`**: Can be omitted (will use default or null)
- **`Nullable`**: Can explicitly be null in database
- **`Default`**: Automatic value if not provided
- **`Primary Key`**: Unique identifier for the record
- **`Foreign Key`**: References another table

---

## API Response Examples

### Full Nested Response (Project with all children)

```json
{
  "id": 1,
  "name": "Project Alpha",
  "description": "Main project for 2026",
  "start_date": "2026-01-01T00:00:00Z",
  "end_date": "2026-12-31T23:59:59Z",
  "owner_id": 1,
  "order_id": 1,
  "status_id": 1,
  "created_at": "2026-03-28T10:30:00Z",
  "updated_at": "2026-03-28T10:30:00Z",
  "owner": {
    "id": 1,
    "username": "john.doe",
    "email": "john@example.com",
    "full_name": "John Doe",
    "is_active": true,
    "created_at": "2026-03-28T10:00:00Z",
    "roles": [
      {
        "id": 1,
        "name": "Admin",
        "description": "Full system access",
        "created_at": "2026-03-28T10:00:00Z",
        "permissions": [
          {
            "id": 1,
            "name": "view_projects",
            "description": "Can view projects",
            "created_at": "2026-03-28T10:00:00Z"
          }
        ]
      }
    ]
  },
  "order": {
    "id": 1,
    "customer_id": 1,
    "order_number": "ORD-2026-001",
    "status_id": 1,
    "created_at": "2026-03-28T10:30:00Z",
    "customer": {
      "id": 1,
      "name": "Acme Corp",
      "contact_info": "contact@acme.com",
      "created_at": "2026-03-28T10:30:00Z"
    },
    "status": {
      "id": 1,
      "name": "Active",
      "description": "Order is active",
      "status_type": "operational",
      "created_at": "2026-03-28T10:00:00Z"
    }
  },
  "status": {
    "id": 1,
    "name": "Active",
    "description": "Project is active",
    "status_type": "operational",
    "created_at": "2026-03-28T10:00:00Z"
  },
  "systems": [
    {
      "id": 1,
      "name": "System One",
      "description": "Primary system",
      "project_id": 1,
      "status_id": 1,
      "created_at": "2026-03-28T10:30:00Z",
      "status": {
        "id": 1,
        "name": "Active"
      },
      "subsystems": [
        {
          "id": 1,
          "name": "Subsystem A",
          "description": "Part of System One",
          "system_id": 1,
          "status_id": 1,
          "created_at": "2026-03-28T10:30:00Z",
          "modules": [
            {
              "id": 1,
              "name": "Module 1",
              "description": "Part of Subsystem A",
              "subsystem_id": 1,
              "status_id": 1,
              "created_at": "2026-03-28T10:30:00Z",
              "units": [
                {
                  "id": 1,
                  "name": "Unit 1",
                  "description": "Part of Module 1",
                  "module_id": 1,
                  "status_id": 1,
                  "created_at": "2026-03-28T10:30:00Z",
                  "components": [
                    {
                      "id": 1,
                      "name": "Component A",
                      "description": "Part of Unit 1",
                      "sku": "COMP-001",
                      "unit_id": 1,
                      "status_id": 1,
                      "created_at": "2026-03-28T10:30:00Z",
                      "inventory_items": [
                        {
                          "id": 1,
                          "component_id": 1,
                          "quantity": 50,
                          "location": "Warehouse A",
                          "updated_at": "2026-03-28T14:00:00Z"
                        }
                      ]
                    }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

---

## JSON Validation Checklist for Frontend

When sending data to the API, ensure:

### User Object
- [ ] `username` is provided and unique
- [ ] `password` is provided (will be hashed server-side)
- [ ] `email` is valid format (optional)
- [ ] `full_name` is a string (optional)
- [ ] `is_active` is boolean (optional, defaults to true)

### Project Object
- [ ] `name` is provided
- [ ] `start_date` is valid ISO datetime
- [ ] `end_date` is valid ISO datetime (optional, but should be after start_date)
- [ ] `owner_id` references valid user
- [ ] `order_id` references valid order (optional)
- [ ] `status_id` references valid status (optional)

### Hierarchy Objects (System, Subsystem, Module, Unit, Component)
- [ ] `name` is provided
- [ ] Parent ID exists in database (project_id, system_id, subsystem_id, module_id, unit_id)
- [ ] `status_id` references valid status (optional)

### Status History
- [ ] `entity_id` references valid entity
- [ ] `status_id` references valid status
- [ ] `changed_by` references valid user (optional)
- [ ] `notes` provides context (optional)

---

## SQL Query Examples for Reference

### Get User with all Roles and Permissions
```sql
SELECT u.*, r.name as role_name, p.name as permission_name
FROM user u
LEFT JOIN user_role ur ON u.id = ur.user_id
LEFT JOIN role r ON ur.role_id = r.id
LEFT JOIN role_permission rp ON r.id = rp.role_id
LEFT JOIN permission p ON rp.permission_id = p.id
WHERE u.id = 1;
```

### Get Full Project Hierarchy
```sql
SELECT p.*, s.*, sub.*, m.*, u.*, c.*, i.*
FROM project p
LEFT JOIN system s ON p.id = s.project_id
LEFT JOIN subsystem sub ON s.id = sub.system_id
LEFT JOIN module m ON sub.id = m.subsystem_id
LEFT JOIN unit u ON m.id = u.module_id
LEFT JOIN component c ON u.id = c.unit_id
LEFT JOIN inventory i ON c.id = i.component_id
WHERE p.id = 1;
```

---

**Last Updated:** March 28, 2026  
**Maintained By:** Development Team  
**For Questions:** Contact your database administrator
