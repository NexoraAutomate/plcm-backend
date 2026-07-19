# PLCM Business Logic & Data Flow Guide

**Version:** 1.0  
**Last Updated:** March 28, 2026  
**Purpose:** Complete guide for understanding system logic and data flow for frontend developers

---

## Table of Contents
1. [System Overview](#system-overview)
2. [Authentication & Authorization Flow](#authentication--authorization-flow)
3. [Data Creation Flow](#data-creation-flow)
4. [Project Hierarchy Creation](#project-hierarchy-creation)
5. [Status & History Tracking](#status--history-tracking)
6. [User Interaction Workflows](#user-interaction-workflows)
7. [API Request-Response Cycle](#api-request-response-cycle)
8. [Business Rules & Constraints](#business-rules--constraints)
9. [Error Handling & Validation](#error-handling--validation)

---

## System Overview

### What is PLCM?
**P**roject **L**ifecycle **C**omponent **M**anagement system - A comprehensive platform for:
- Managing projects from initiation to completion
- Organizing hierarchical structures (Projects → Systems → Components)
- Tracking component maintenance and status changes
- Managing inventory for all components
- Controlling access through role-based authorization

### Core Business Concept

```
A Customer places Orders
  ↓
Orders contain Projects
  ↓
Projects are divided into Systems
  ↓
Systems break down into Subsystems → Modules → Units → Components
  ↓
Components have Inventory (quantity tracking)
  ↓
All entities track Status History and Maintenance Logs
  ↓
Everything is secured through User Roles & Permissions
```

---

## Authentication & Authorization Flow

### 1. USER REGISTRATION FLOW

```
┌─────────────────────────────────────────────────────────────┐
│                  USER REGISTRATION FLOW                      │
└─────────────────────────────────────────────────────────────┘

Frontend                           Backend API                 Database
    │                                  │                          │
    │  1. POST /auth/register          │                          │
    │  (username, email,               │                          │
    │   full_name, password)           │                          │
    ├─────────────────────────────────►│                          │
    │                                   │  2. Check if username    │
    │                                   │     already exists       │
    │                                   ├─────────────────────────►│
    │                                   │◄─────────────────────────┤
    │                                   │     (user not found ✓)   │
    │                                   │                          │
    │                                   │  3. Hash password        │
    │                                   │     using bcrypt         │
    │                                   │                          │
    │                                   │  4. Create User record   │
    │                                   │     with hashed password │
    │                                   ├─────────────────────────►│
    │                                   │     INSERT into user     │
    │                                   │◄─────────────────────────┤
    │                                   │     user_id: 1           │
    │                                   │                          │
    │                                   │  5. Assign default role  │
    │                                   │     ("Viewer")           │
    │                                   ├─────────────────────────►│
    │                                   │  INSERT into user_role   │
    │                                   │◄─────────────────────────┤
    │                                   │                          │
    │  6. 200 OK + User Object          │                          │
    │◄─────────────────────────────────┤                          │
    │  {                                │                          │
    │    "id": 1,                       │                          │
    │    "username": "john",            │                          │
    │    "roles": ["Viewer"],           │                          │
    │    "password": "HASHED"           │                          │
    │  }                                │                          │
    │                                   │                          │

LOGIC:
- New users get "Viewer" role automatically (read-only)
- Password is NEVER stored in plain text
- Username must be UNIQUE in entire system
- Email is optional but recommended
```

### 2. LOGIN & TOKEN GENERATION FLOW

```
┌─────────────────────────────────────────────────────────────┐
│                   LOGIN & TOKEN FLOW                         │
└─────────────────────────────────────────────────────────────┘

Frontend                           Backend API                 Database
    │                                  │                          │
    │  1. POST /auth/login             │                          │
    │  (username, password)            │                          │
    ├─────────────────────────────────►│                          │
    │                                   │  2. Find user by         │
    │                                   │     username             │
    │                                   ├─────────────────────────►│
    │                                   │    SELECT * FROM user    │
    │                                   │◄─────────────────────────┤
    │                                   │  user_id: 1              │
    │                                   │  password_hash: ***      │
    │                                   │  is_active: true         │
    │                                   │                          │
    │                                   │  3. Verify password:     │
    │                                   │  bcrypt.verify(          │
    │                                   │    provided_pwd,         │
    │                                   │    stored_hash)          │
    │                                   │                          │
    │                                   │  4. Get user roles       │
    │                                   ├─────────────────────────►│
    │                                   │  SELECT roles ...        │
    │                                   │◄─────────────────────────┤
    │                                   │  ["Admin", "Manager"]    │
    │                                   │                          │
    │                                   │  5. Get user permissions │
    │                                   │  (from all assigned roles)
    │                                   ├─────────────────────────►│
    │                                   │  SELECT permissions ...  │
    │                                   │◄─────────────────────────┤
    │                                   │  [view_projects,         │
    │                                   │   create_projects, ...]  │
    │                                   │                          │
    │                                   │  6. Create JWT Token:    │
    │                                   │  token = jwt.encode({    │
    │                                   │    sub: "1",             │
    │                                   │    username: "john",     │
    │                                   │    roles: [...],         │
    │                                   │    permissions: [...],   │
    │                                   │    exp: now + 30 days    │
    │                                   │  }, SECRET_KEY)          │
    │                                   │                          │
    │  7. 200 OK + Token + User Info    │                          │
    │◄─────────────────────────────────┤                          │
    │  {                                │                          │
    │    "access_token": "eyJ0...",     │                          │
    │    "token_type": "bearer",        │                          │
    │    "user_id": 1,                  │                          │
    │    "username": "john",            │                          │
    │    "roles": ["Admin"],            │                          │
    │    "permissions": [...]           │                          │
    │  }                                │                          │
    │                                   │                          │
    │  8. Store token in                │                          │
    │     localStorage/sessionStorage   │                          │
    │                                   │                          │

TOKEN STRUCTURE (JWT):
{
  "header": {
    "typ": "JWT",
    "alg": "HS256"
  },
  "payload": {
    "sub": "1",                    // user_id
    "username": "john",
    "roles": ["Admin"],
    "permissions": ["view_*", "create_*", ...],
    "exp": 1800000000             // Expires in 30 days
  },
  "signature": "HMAC-SHA256(header.payload, SECRET_KEY)"
}

TOKEN USAGE:
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
(Sent with EVERY request to protected endpoint)

TOKEN VALIDATION:
1. Check signature (verify has correct SECRET_KEY)
2. Check expiration (current time < exp)
3. Extract user data from payload
4. Check user is_active = true
5. Check required permission/role exists
```

### 3. PROTECTED ENDPOINT ACCESS FLOW

```
┌─────────────────────────────────────────────────────────────┐
│         ACCESSING PROTECTED ENDPOINT WITH TOKEN              │
└─────────────────────────────────────────────────────────────┘

Frontend                           Backend API                 Database
    │                                  │                          │
    │  1. GET /api/projects/           │                          │
    │     (with Authorization header)  │                          │
    │     Authorization: Bearer token  │                          │
    ├─────────────────────────────────►│                          │
    │                                   │  2. Extract token        │
    │                                   │     from header          │
    │                                   │                          │
    │                                   │  3. Validate token:      │
    │                                   │     - signature valid?   │
    │                                   │     - not expired?       │
    │                                   │     - user_id exists?    │
    │                                   │                          │
    │                                   │  4. Check permission:    │
    │                                   │     require_permission   │
    │                                   │     ("view_projects")    │
    │                                   │                          │
    │                                   │     Does user_token have │
    │                                   │     "view_projects"? ✓   │
    │                                   │                          │
    │                                   │  5. Execute endpoint     │
    │                                   │     Get user from token  │
    │                                   │     (no DB lookup needed)│
    │                                   │                          │
    │                                   │  6. Query database for   │
    │                                   │     projects             │
    │                                   ├─────────────────────────►│
    │                                   │    SELECT * FROM project │
    │                                   │◄─────────────────────────┤
    │                                   │    [project1, ...]       │
    │                                   │                          │
    │  7. 200 OK + Projects List        │                          │
    │◄─────────────────────────────────┤                          │
    │  [                                │                          │
    │    {id: 1, name: "Project A"},   │                          │
    │    {id: 2, name: "Project B"}    │                          │
    │  ]                                │                          │

ERROR SCENARIOS:
1. No Authorization header
   → 401 Unauthorized: "Missing authorization header"

2. Token expired
   → 401 Unauthorized: "Token expired. Please login again."

3. Invalid token signature
   → 401 Unauthorized: "Invalid token signature"

4. User doesn't have permission
   → 403 Forbidden: "User does not have permission: view_projects"

5. User is inactive
   → 401 Unauthorized: "User is inactive"
```

---

## Data Creation Flow

### CREATE PROJECT WORKFLOW

```
┌──────────────────────────────────────────────────────────────┐
│           CREATING A PROJECT - BUSINESS FLOW                 │
└──────────────────────────────────────────────────────────────┘

Step 1: FRONTEND VALIDATION
━━━━━━━━━━━━━━━━━━━━━━━━━
User fills form:
{
  "name": "Project Alpha",
  "description": "Main project for 2026",
  "start_date": "2026-01-01T00:00:00Z",
  "end_date": "2026-12-31T23:59:59Z",
  "owner_id": 1,
  "order_id": 1
}

Frontend validates:
✓ name is not empty
✓ start_date is before end_date
✓ owner_id exists (lookup from user list)
✓ order_id exists (optional, but validate if provided)


Step 2: API SUBMISSION
━━━━━━━━━━━━━━━━━━━━━
POST /api/projects/
Authorization: Bearer {token}
{...project data...}


Step 3: BACKEND AUTHORIZATION
━━━━━━━━━━━━━━━━━━━━━━━━━
1. Validate token is valid
2. Check user has permission: "create_projects"
   If missing → 403 Forbidden


Step 4: DATABASE OPERATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━

a) CREATE PROJECT RECORD
   ┌────────────────────────────────┐
   │ INSERT INTO project (           │
   │   name: "Project Alpha",        │
   │   description: "...",           │
   │   start_date: "2026-01-01",     │
   │   end_date: "2026-12-31",       │
   │   owner_id: 1,                  │
   │   order_id: 1,                  │
   │   status_id: NULL,              │
   │   created_at: NOW(),            │
   │   updated_at: NOW()             │
   │ )                               │
   │ RETURNING id                    │
   └────────────────────────────────┘
   Result: project_id = 5

b) CREATE ENTITY RECORD (for tracking)
   ┌────────────────────────────────┐
   │ INSERT INTO entity (            │
   │   name: "Project Alpha",        │
   │   display_name: "Project Alpha",│
   │   entity_type: "Project",       │
   │   entity_pk: 5,  ←──────────────┼─ Links entity to project
   │   status_id: NULL,              │
   │   created_at: NOW()             │
   │ )                               │
   └────────────────────────────────┘
   Result: entity_id = 42

c) CREATE INITIAL STATUS HISTORY
   ┌────────────────────────────────┐
   │ INSERT INTO entity_status_      │
   │ history (                       │
   │   entity_id: 42,                │
   │   status_id: NULL,              │
   │   changed_by: 1,    ←───────────┼─ Current user
   │   notes: "Project created",     │
   │   changed_at: NOW()             │
   │ )                               │
   └────────────────────────────────┘
   Result: history_id = 100


Step 5: RESPONSE
━━━━━━━━━━━━━━━
200 Created
{
  "id": 5,
  "name": "Project Alpha",
  "description": "Main project for 2026",
  "start_date": "2026-01-01T00:00:00Z",
  "end_date": "2026-12-31T23:59:59Z",
  "owner_id": 1,
  "order_id": 1,
  "status_id": null,
  "created_at": "2026-03-28T15:30:00Z",
  "updated_at": "2026-03-28T15:30:00Z",
  "owner": {
    "id": 1,
    "username": "john.doe"
  },
  "order": {
    "id": 1,
    "order_number": "ORD-001"
  },
  "systems": []  ← empty initially
}


BUSINESS LOGIC APPLIED:
━━━━━━━━━━━━━━━━━━━━━━
1. Project created in "pending" state (no status assigned)
2. Entity created automatically for history tracking
3. Status history record created showing "Project created"
4. Project can now have Systems added to it
5. Owner can be changed later by authorized users
6. Status can be updated which triggers history records
```

---

## Project Hierarchy Creation

### THE HIERARCHY STRUCTURE

```
┌─────────────────────────────────────────────────────────────┐
│             PROJECT HIERARCHY - 6 LEVELS DEEP                │
└─────────────────────────────────────────────────────────────┘

LEVEL 1: PROJECT
┌──────────────────────────────────────────┐
│ Project: "Manufacturing Line A"          │
│ (Customer's big initiative)              │
│ owner_id → User                          │
│ order_id → Customer Order                │
│ status_id → Current Status               │
└──────────────────┬───────────────────────┘
                   │
                   ├─ Systems (one-to-many)
                   │
                   ▼

LEVEL 2: SYSTEM
┌────────────────────────────────────────────────────┐
│ System: "Assembly Station 1"                       │
│ (Physical/logical grouping within project)         │
│ project_id → Project [REQUIRED]                    │
│ status_id → Current Status                         │
└────────────────────────┬────────────────────────────┘
                         │
                         ├─ Subsystems
                         │
                         ▼

LEVEL 3: SUBSYSTEM
┌────────────────────────────────────────────────────┐
│ Subsystem: "Power Distribution"                    │
│ (Functional subdivision of system)                 │
│ system_id → System [REQUIRED]                      │
│ status_id → Current Status                         │
└────────────────────────┬────────────────────────────┘
                         │
                         ├─ Modules
                         │
                         ▼

LEVEL 4: MODULE
┌────────────────────────────────────────────────────┐
│ Module: "Main Power Supply Board"                  │
│ (Major component grouping)                         │
│ subsystem_id → Subsystem [REQUIRED]                │
│ status_id → Current Status                         │
└────────────────────────┬────────────────────────────┘
                         │
                         ├─ Units
                         │
                         ▼

LEVEL 5: UNIT
┌────────────────────────────────────────────────────┐
│ Unit: "Primary Transformer"                        │
│ (Specific physical unit)                           │
│ module_id → Module [REQUIRED]                      │
│ status_id → Current Status                         │
└────────────────────────┬────────────────────────────┘
                         │
                         ├─ Components
                         │
                         ▼

LEVEL 6: COMPONENT
┌────────────────────────────────────────────────────┐
│ Component: "Copper Coil"                           │
│ (Individual part/item)                             │
│ unit_id → Unit [REQUIRED]                          │
│ sku → Part Number (e.g., "COIL-001")               │
│ status_id → Current Status                         │
└────────────────────────┬────────────────────────────┘
                         │
                         ├─ Inventory
                         │
                         ▼

INVENTORY
┌────────────────────────────────────────────────────┐
│ Inventory Item: "Copper Coil Stock"                │
│ component_id → Component [REQUIRED]                │
│ quantity → 150 units                               │
│ location → "Warehouse A - Shelf B3"                │
│ updated_at → Last stock update                     │
└────────────────────────────────────────────────────┘

REQUIRED PARAMETERS WHEN CREATING:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Project: Needs order_id, owner_id
✓ System: Needs project_id
✓ Subsystem: Needs system_id
✓ Module: Needs subsystem_id
✓ Unit: Needs module_id
✓ Component: Needs unit_id
✓ Inventory: Needs component_id

Can't create subsystem without System!
Can't create component without going through entire hierarchy!
```

### EXAMPLE: CREATING COMPLETE HIERARCHY

```
Frontend User Actions:
━━━━━━━━━━━━━━━━━━━━━

1. Create Project "Manufacturing A"
   POST /api/projects/
   {
     "name": "Manufacturing A",
     "start_date": "2026-01-01T00:00:00Z",
     "end_date": "2026-12-31T23:59:59Z",
     "owner_id": 1,
     "order_id": 1
   }
   → Returns project_id: 5

2. Create System under Project 5
   POST /api/systems/
   {
     "name": "Assembly Station",
     "project_id": 5
   }
   → Returns system_id: 12

3. Create Subsystem under System 12
   POST /api/subsystems/
   {
     "name": "Power Distribution",
     "system_id": 12
   }
   → Returns subsystem_id: 18

4. Create Module under Subsystem 18
   POST /api/modules/
   {
     "name": "Power Supply Board",
     "subsystem_id": 18
   }
   → Returns module_id: 25

5. Create Unit under Module 25
   POST /api/units/
   {
     "name": "Transformer",
     "module_id": 25
   }
   → Returns unit_id: 31

6. Create Component under Unit 31
   POST /api/components/
   {
     "name": "Copper Coil",
     "sku": "COIL-001",
     "unit_id": 31
   }
   → Returns component_id: 42

7. Create Inventory for Component 42
   POST /api/inventory/
   {
     "component_id": 42,
     "quantity": 150,
     "location": "Warehouse A - Shelf B3"
   }
   → Returns inventory_id: 1


PARENT-CHILD RELATIONSHIPS CREATED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Project 5
  └─ System 12
      └─ Subsystem 18
          └─ Module 25
              └─ Unit 31
                  └─ Component 42
                      └─ Inventory 1

DATABASE STATE:
project.id = 5, project.order_id = 1
system.id = 12, system.project_id = 5
subsystem.id = 18, subsystem.system_id = 12
module.id = 25, module.subsystem_id = 18
unit.id = 31, unit.module_id = 25
component.id = 42, component.unit_id = 31
inventory.id = 1, inventory.component_id = 42
```

---

## Status & History Tracking

### AUTOMATIC STATUS TRACKING

```
┌─────────────────────────────────────────────────────────────┐
│          ENTITY STATUS HISTORY TRACKING SYSTEM                │
└─────────────────────────────────────────────────────────────┘

When a Project is created:
━━━━━━━━━━━━━━━━━━━━━━━━━
1. Project record created (status_id = NULL)
2. Entity record created (entity_type = "Project", entity_pk = {project_id})
3. EntityStatusHistory record created (demonstrates creation)

Example Timeline:
┌──────────────────────────────────────────┐
│ Entity: Project Alpha (entity_id: 42)    │
│ Initial status_id: NULL                  │
└──────────────────────────────────────────┘
         │
         ▼

Time: 2026-03-28 10:30:00
Event: Project Created
┌──────────────────────────────────────────┐
│ EntityStatusHistory:                     │
│  id: 1                                   │
│  entity_id: 42                           │
│  status_id: NULL                         │
│  changed_by: 1 (John Doe)               │
│  notes: "Project created"                │
│  changed_at: 2026-03-28 10:30:00        │
└──────────────────────────────────────────┘
         │
         ▼

Admin updates status to "Active"
Time: 2026-03-28 11:00:00
┌──────────────────────────────────────────┐
│ UPDATE project                           │
│ SET status_id = 1                        │
│ WHERE id = 5                             │
│                                          │
│ INSERT EntityStatusHistory               │
│  entity_id: 42                           │
│  status_id: 1 (Active)                   │
│  changed_by: 1                           │
│  notes: "Approved and activated"         │
│  changed_at: 2026-03-28 11:00:00        │
└──────────────────────────────────────────┘
         │
         ▼

TIME: 2026-03-28 15:45:00
Event: Status changed to "On Hold"
┌──────────────────────────────────────────┐
│ UPDATE project                           │
│ SET status_id = 3                        │
│ WHERE id = 5                             │
│                                          │
│ INSERT EntityStatusHistory               │
│  entity_id: 42                           │
│  status_id: 3 (On Hold)                  │
│  changed_by: 2 (Manager)                 │
│  notes: "Awaiting customer approval"     │
│  changed_at: 2026-03-28 15:45:00        │
└──────────────────────────────────────────┘


GET /api/entities/42/status-history/
Returns full audit trail:
[
  {
    "id": 3,
    "entity_id": 42,
    "status_id": 3,
    "status": {
      "id": 3,
      "name": "On Hold"
    },
    "changed_by": 2,
    "changed_by_user": {
      "id": 2,
      "username": "manager",
      "full_name": "Manager User"
    },
    "notes": "Awaiting customer approval",
    "changed_at": "2026-03-28T15:45:00Z"
  },
  {
    "id": 2,
    "entity_id": 42,
    "status_id": 1,
    "status": {
      "id": 1,
      "name": "Active"
    },
    "changed_by": 1,
    "changed_by_user": {
      "id": 1,
      "username": "john.doe",
      "full_name": "John Doe"
    },
    "notes": "Approved and activated",
    "changed_at": "2026-03-28T11:00:00Z"
  },
  {
    "id": 1,
    "entity_id": 42,
    "status_id": null,
    "status": null,
    "changed_by": 1,
    "changed_by_user": {
      "id": 1,
      "username": "john.doe",
      "full_name": "John Doe"
    },
    "notes": "Project created",
    "changed_at": "2026-03-28T10:30:00Z"
  }
]

BENEFITS:
✓ Complete audit trail of all changes
✓ Know WHO changed what and WHEN
✓ Can track project history over time
✓ Useful for compliance and debugging
✓ Status changes are immutable (history can't be deleted)
```

### MAINTENANCE LOG TRACKING

```
┌─────────────────────────────────────────────────────────────┐
│         MAINTENANCE LOG - TRACKING MAINTENANCE                │
└─────────────────────────────────────────────────────────────┘

Purpose: Track maintenance activities on entities (Projects, Systems, etc.)

Workflow:
━━━━━━━
1. Technician performs maintenance
2. Creates MaintenanceLog record
3. Specifies what was done and next due date
4. Can view all maintenance history for an entity


Example: Maintaining Assembly System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/entities/42/maintenance-logs/
[
  {
    "id": 5,
    "entity_id": 42,
    "notes": "Changed hydraulic fluid and inspected seals. All operational.",
    "performed_at": "2026-03-28T09:00:00Z",
    "next_due": "2026-06-28T09:00:00Z",
    "performed_by": 3,
    "performed_by_user": {
      "id": 3,
      "username": "technician_1",
      "full_name": "Tom Technician"
    }
  },
  {
    "id": 4,
    "entity_id": 42,
    "notes": "Routine inspection. Replaced oil filter.",
    "performed_at": "2026-03-15T10:00:00Z",
    "next_due": "2026-06-15T10:00:00Z",
    "performed_by": 3,
    "performed_by_user": {
      "id": 3,
      "username": "technician_1",
      "full_name": "Tom Technician"
    }
  }
]

CREATE MAINTENANCE LOG:
┌────────────────────────────────────────┐
│ POST /api/maintenance-logs/            │
│ {                                      │
│   "entity_id": 42,                     │
│   "notes": "Annual maintenance",       │
│   "next_due": "2026-09-28T10:00:00Z"  │
│ }                                      │
└────────────────────────────────────────┘

Returns:
{
  "id": 6,
  "entity_id": 42,
  "notes": "Annual maintenance",
  "performed_at": "2026-03-28T14:30:00Z",  ← Current time
  "next_due": "2026-09-28T10:00:00Z",
  "performed_by": 1  ← Current user from token
}

BUSINESS LOGIC:
✓ performed_at = current timestamp (automatic)
✓ performed_by = current user (from token, automatic)
✓ next_due = when to perform next maintenance
✓ Helps track service intervals
✓ Prevents missed maintenance schedules
```

---

## User Interaction Workflows

### TYPICAL ADMIN WORKFLOW

```
┌─────────────────────────────────────────────────────────────┐
│              TYPICAL ADMIN USER WORKFLOW                      │
└─────────────────────────────────────────────────────────────┘

MORNING: System Setup
━━━━━━━━━━━━━━━━━━━━

1. Admin logs in
   POST /auth/login
   → Receives token with "Admin" role and ALL permissions

2. Admin creates new customer
   POST /api/customers/
   {
     "name": "New Factory Inc",
     "contact_info": "contact@factory.com"
   }
   → customer_id: 5

3. Admin creates order for customer
   POST /api/orders/
   {
     "customer_id": 5,
     "order_number": "ORD-2026-001"
   }
   → order_id: 10

4. Admin creates project for order
   POST /api/projects/
   {
     "name": "Production Line Setup",
     "start_date": "2026-04-01T00:00:00Z",
     "end_date": "2026-06-30T23:59:59Z",
     "owner_id": 1,
     "order_id": 10
   }
   → project_id: 7


AFTERNOON: Role Management
━━━━━━━━━━━━━━━━━━━━━━━━

5. Admin promotes technician to Manager role
   POST /api/auth/assign-role
   {
     "user_id": 3,
     "role_id": 2  (ProjectManager)
   }
   → User 3 now has ProjectManager permissions

6. Admin views all roles and permissions
   GET /api/auth/roles
   → Shows: Admin, ProjectManager, Technician, Viewer


LATE AFTERNOON: Monitoring
━━━━━━━━━━━━━━━━━━━━━━━━

7. Admin checks project status progress
   GET /api/projects/7
   → Sees: 0% complete, status = "Planning"

8. Admin updates project status to "Active"
   PUT /api/projects/7
   {
     "status_id": 1  (Active)
   }
   → Creates EntityStatusHistory record
   → Calls changed_at, changed_by automatically


AUTHORIZATION CHECK AT EACH STEP:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All endpoints validate:
✓ Token is valid and not expired
✓ User has "create_customers" permission (step 2)
✓ User has "create_orders" permission (step 3)
✓ User has "create_projects" permission (step 4)
✓ User has "view_roles" and "assign_role" permissions (steps 5-6)
✓ User has "view_projects" and "edit_projects" permissions (steps 7-8)

If ANY check fails → 403 Forbidden error
```

### TYPICAL PROJECT MANAGER WORKFLOW

```
┌─────────────────────────────────────────────────────────────┐
│         TYPICAL PROJECT MANAGER WORKFLOW                      │
└─────────────────────────────────────────────────────────────┘

START OF WEEK:
━━━━━━━━━━━━

1. Login
   POST /auth/login
   → Token with "ProjectManager" role
   → Permissions: view_projects, create_projects, view_systems, create_systems, etc.

2. View all my projects (owned by me)
   GET /api/projects/?skip=0&limit=10
   → Can see only projects I have view permission for

3. View specific project details
   GET /api/projects/7
   → See full hierarchy
   → See status history
   → See who owns it, what order it's for


MID-WEEK: Creating Hierarchy
━━━━━━━━━━━━━━━━━━━━━━━━━━

4. Create System under project
   POST /api/systems/
   {
     "project_id": 7,
     "name": "Assembly System 1",
     "description": "First assembly line"
   }
   → system_id: 12

5. Create Subsystem under system
   POST /api/subsystems/
   {
     "system_id": 12,
     "name": "Power Distribution",
     "description": "Electrical subsystem"
   }
   → subsystem_id: 18

6. Continue creating Module, Unit, Component hierarchy...

7. Create inventory for components
   POST /api/inventory/
   {
     "component_id": 42,
     "quantity": 100,
     "location": "Warehouse A"
   }


END OF WEEK: Reporting
━━━━━━━━━━━━━━━━━━━

8. Get status history for project
   GET /api/entities/{entity_id}/status-history/
   → See all status changes throughout week

9. Update project status
   PUT /api/projects/7
   {
     "status_id": 1  (Active/In Progress)
   }
   → Creates history record showing change


PERMISSIONS ENFORCED:
━━━━━━━━━━━━━━━━━━━
✓ create_projects ✓
✗ delete_projects ✗ (denied, needs Admin)
✓ create_systems ✓
✓ view_systems ✓
✗ delete_systems ✗ (denied)
✓ view_components ✓
✗ delete_components ✗ (denied)
✓ manage_inventory ✓
✓ view_maintenance ✓
✓ create_maintenance ✓

Trying to create a customer?
✗ Denied: "User does not have permission: create_customers"
```

---

## API Request-Response Cycle

### COMPLETE REQUEST LIFECYCLE

```
┌──────────────────────────────────────────────────────────────┐
│          COMPLETE REQUEST - RESPONSE CYCLE                    │
└──────────────────────────────────────────────────────────────┘

CLIENT (Frontend)              NETWORK                SERVER (Backend)
    │                              │                        │
    │────────── 1. BUILD REQUEST ──────────────────────►   │
    │                              │                        │
    │  POST /api/projects/         │                        │
    │  Content-Type: application/json                       │
    │  Authorization: Bearer token │                        │
    │                              │                        │
    │  {                           │                        │
    │    "name": "Project X",     │                        │
    │    "start_date": "...",     │                        │
    │    "end_date": "...",       │                        │
    │    "owner_id": 1,           │                        │
    │    "order_id": 1            │                        │
    │  }                           │                        │
    │                              │                        │
    │                              │   2. PARSE REQUEST      │
    │                              │   ┌─────────────────┐   │
    │                              │───┤ Extract headers │   │
    │                              │   │ Extract body    │   │
    │                              │   └─────────────────┘   │
    │                              │                        │
    │                              │   3. AUTHENTICATE       │
    │                              │   ┌─────────────────┐   │
    │                              │───┤ Verify token    │   │
    │                              │   │ Check expiry    │   │
    │                              │   │ Extract user    │   │
    │                              │   └─────────────────┘   │
    │                              │                        │
    │                              │   4. AUTHORIZE          │
    │                              │   ┌─────────────────┐   │
    │                              │───┤ Check permission│   │
    │                              │   │ "create_        │   │
    │                              │   │  projects"      │   │
    │                              │   └─────────────────┘   │
    │                              │                        │
    │                              │   5. VALIDATE DATA      │
    │                              │   ┌─────────────────┐   │
    │                              │───┤ Validate fields │   │
    │                              │   │ Check types     │   │
    │                              │   │ Check refs exist│   │
    │                              │   └─────────────────┘   │
    │                              │                        │
    │                              │   6. DATABASE OPS       │
    │                              │   ┌─────────────────┐   │
    │                              │───┤ INSERT project  │   │
    │                              │   │ INSERT entity   │   │
    │                              │   │ INSERT history  │   │
    │                              │   │ COMMIT trans.   │   │
    │                              │   └─────────────────┘   │
    │                              │                        │
    │                              │   7. BUILD RESPONSE     │
    │                              │   ┌─────────────────┐   │
    │                              │───┤ Fetch created   │   │
    │                              │   │ record with     │   │
    │                              │   │ relationships   │   │
    │                              │   │ Serialize JSON  │   │
    │                              │   └─────────────────┘   │
    │                              │                        │
    │◄─────── 8. SEND RESPONSE ────────────────────────────  │
    │                              │                        │
    │  HTTP/1.1 200 Created        │                        │
    │  Content-Type: application/json                       │
    │                              │                        │
    │  {                           │                        │
    │    "id": 5,                 │                        │
    │    "name": "Project X",     │                        │
    │    "created_at": "2026-...",│                        │
    │    "owner": {...},          │                        │
    │    "order": {...},          │                        │
    │    "systems": []             │                        │
    │  }                           │                        │
    │                              │                        │
    │  9. PARSE RESPONSE           │                        │
    │  ┌───────────────────┐       │                        │
    │  │ Parse JSON       │       │                        │
    │  │ Extract data     │       │                        │
    │  │ Update local state       │                        │
    │  │ Show success UI  │       │                        │
    │  └───────────────────┘       │                        │
    │                              │                        │


ERROR RESPONSE EXAMPLES:
━━━━━━━━━━━━━━━━━━━━━━

Missing Authorization Header:
HTTP/1.1 401 Unauthorized
{
  "detail": "Missing authorization header"
}

Invalid Permission:
HTTP/1.1 403 Forbidden
{
  "detail": "User does not have permission: create_projects"
}

Validation Error (missing required field):
HTTP/1.1 422 Unprocessable Entity
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}

Resource Not Found:
HTTP/1.1 404 Not Found
{
  "detail": "Project not found"
}

Bad Request (logic error):
HTTP/1.1 400 Bad Request
{
  "detail": "End date must be after start date"
}
```

---

## Business Rules & Constraints

### DATA VALIDATION RULES

```
┌──────────────────────────────────────────────────────────────┐
│              BUSINESS RULES & CONSTRAINTS                     │
└──────────────────────────────────────────────────────────────┘

USER MANAGEMENT:
━━━━━━━━━━━━━━━━
Rule 1: Only ONE Admin user can exist
   ✗ Cannot create second Admin user
   ✗ Can only demote Admin before creating new one
   Logic: Security - prevents accidental admin lockout

Rule 2: New users default to "Viewer" role
   ✓ Automatically assigned on registration
   Logic: Principle of least privilege

Rule 3: Passwords are hashed before storage
   ✓ bcrypt with cost factor 12
   ✗ Never stored in plain text
   Logic: Security

Rule 4: Username must be unique
   ✗ Cannot create two users with same username
   Logic: Authentication requires unique login identifier

Rule 5: Inactive users cannot login
   ✓ is_active = false blocks all access
   Logic: Account disabling

PROJECT HIERARCHY:
━━━━━━━━━━━━━━━━━
Rule 6: Complete parent chain required
   ✗ Cannot create Module without System, Subsystem
   ✓ Must follow hierarchy: Project > System > Subsystem > Module > Unit > Component
   Logic: Structural integrity

Rule 7: Parent records must exist
   ✗ Cannot create System for non-existent Project
   ✓ system.project_id must match existing project
   Logic: Referential integrity (Foreign key constraint)

Rule 8: Project dates must be logical
   ✗ end_date cannot be before start_date
   ✓ Must be chronologically valid
   Logic: Business sense

Rule 9: One owner per project
   ✓ owner_id points to single User
   ✗ Cannot have multiple owners (use roles for permissions)
   Logic: Clear responsibility

INVENTORY:
━━━━━━━━━
Rule 10: Quantity cannot be negative
   ✗ quantity < 0 not allowed
   ✓ quantity = 0 allowed
   Logic: Cannot have negative stock

Rule 11: Component must exist for inventory
   ✗ Cannot create inventory for non-existent component
   ✓ component_id must reference valid component
   Logic: Referential integrity

STATUS & HISTORY:
━━━━━━━━━━━━━━━━
Rule 12: Status history is immutable
   ✗ Cannot delete or edit history records
   ✓ Can only create new records
   Logic: Audit trail integrity

Rule 13: Entity status tracked for all entities
   ✓ System, Project, etc. all track status
   ✓ Status changes create history records
   Logic: Complete audit trail

AUTHORIZATION:
━━━━━━━━━━━━━
Rule 14: Permissions are role-based
   ✗ Cannot grant individual permissions
   ✓ Users get permissions through roles
   Logic: Scalable RBAC

Rule 15: Token expiration (30 days)
   ✗ Tokens older than 30 days invalid
   ✓ Must re-login to get new token
   Logic: Security - limit token lifetime

Rule 16: Role changes take effect immediately
   ✓ Permission added/removed instantly
   ✗ But token still valid until expiration
   Workaround: User must re-login for new token to reflect changes
   Logic: Performance vs consistency trade-off

MAINTENANCE:
━━━━━━━━━━━
Rule 17: Maintenance performed_by is current user
   ✓ Automatically set to current authenticated user
   ✗ Cannot manually set to different user
   Logic: Audit trail accuracy

Rule 18: Maintenance performed_at is current timestamp
   ✓ Automatically set to current time
   ✗ Cannot manually set past date
   Logic: Ensures chronological accuracy

DELETION:
━━━━━━━━
Rule 19: Admin user cannot be deleted
   ✗ Cannot delete user with Admin role
   ✓ Must remove Admin role first, then delete
   Logic: Security - prevent admin removal

Rule 20: Cascade delete relationships
   ✓ Deleting project cascades to systems
   ✓ Deleting system cascades to subsystems
   Logic: Referential integrity
```

---

## Error Handling & Validation

### COMMON ERROR SCENARIOS

```
┌──────────────────────────────────────────────────────────────┐
│            ERROR HANDLING & VALIDATION GUIDE                  │
└──────────────────────────────────────────────────────────────┘

ERROR 1: MISSING REQUIRED FIELD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Request:
POST /api/projects/
{
  "start_date": "2026-01-01T00:00:00Z",
  "end_date": "2026-12-31T23:59:59Z",
  "owner_id": 1
  /* Missing "name" field */
}

Response:
HTTP/1.1 422 Unprocessable Entity
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}

Frontend Action:
- Validate all required fields before sending
- Show user which field is missing
- Example: "Project name is required"


ERROR 2: INVALID DATA TYPE
━━━━━━━━━━━━━━━━━━━━━━━━

Request:
POST /api/projects/
{
  "name": "Project X",
  "start_date": "invalid-date",  /* Should be ISO datetime */
  "end_date": "2026-12-31T23:59:59Z",
  "owner_id": 1,
  "order_id": 1
}

Response:
HTTP/1.1 422 Unprocessable Entity
{
  "detail": [
    {
      "loc": ["body", "start_date"],
      "msg": "invalid datetime format",
      "type": "value_error"
    }
  ]
}

Frontend Action:
- Use date/time picker instead of free text
- Validate format before sending
- Use ISO 8601 format: "YYYY-MM-DDTHH:MM:SSZ"


ERROR 3: INVALID REFERENCE (Foreign Key)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Request:
POST /api/systems/
{
  "name": "System A",
  "project_id": 999  /* Project 999 doesn't exist */
}

Response:
HTTP/1.1 400 Bad Request
{
  "detail": "Project with id 999 not found"
}

Frontend Action:
- Validate parent exists before submitting
- Use dropdowns for parent selection (not free text IDs)
- Load available parent list from API: GET /api/projects/


ERROR 4: MISSING AUTHENTICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Request:
GET /api/projects/
/* Missing Authorization header */

Response:
HTTP/1.1 401 Unauthorized
{
  "detail": "Missing authorization header"
}

Frontend Action:
- Check if user is logged in
- If not, redirect to login page
- Store token and include in all requests


ERROR 5: TOKEN EXPIRED
━━━━━━━━━━━━━━━━━━━

Request:
GET /api/projects/
Authorization: Bearer {expired_token}

Response:
HTTP/1.1 401 Unauthorized
{
  "detail": "Token expired. Please login again."
}

Frontend Action:
- Clear stored token
- Redirect to login page
- Prompt user to re-authenticate


ERROR 6: INSUFFICIENT PERMISSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Request:
DELETE /api/projects/5
Authorization: Bearer {viewer_token}

Response:
HTTP/1.1 403 Forbidden
{
  "detail": "User does not have permission: delete_projects"
}

Frontend Action:
- Hide delete button from non-admin users
- Check user.permissions before showing UI elements
- Show friendly message: "You don't have permission to delete projects"


ERROR 7: RESOURCE NOT FOUND
━━━━━━━━━━━━━━━━━━━━━━━

Request:
GET /api/projects/999

Response:
HTTP/1.1 404 Not Found
{
  "detail": "Project not found"
}

Frontend Action:
- Show friendly error message
- Redirect to list page or home
- Example: "The project you're looking for doesn't exist"


ERROR 8: BUSINESS LOGIC VIOLATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Request:
POST /api/users/
{
  "username": "anotherAdmin",
  "password": "password123"
}
/* But Admin already exists */

Response:
HTTP/1.1 400 Bad Request
{
  "detail": "An Admin user already exists. Cannot create another user with Admin role."
}

Frontend Action:
- Read error message carefully
- Explain to user what rule was violated
- Show step to fix: "Remove existing Admin role before creating new Admin"


ERROR 9: INVALID LOGICAL STATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Request:
PUT /api/projects/5
{
  "start_date": "2026-12-31T23:59:59Z",
  "end_date": "2026-01-01T00:00:00Z"  /* End before start */
}

Response:
HTTP/1.1 400 Bad Request
{
  "detail": "End date must be after start date"
}

Frontend Action:
- Validate dates on frontend before submitting
- Use date picker that enforces this rule
- Show error: "Project end date must be after start date"


FRONTEND ERROR HANDLING BEST PRACTICES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Always wrap API calls in try-catch:
   try {
     const response = await fetch(url, options);
     if (!response.ok) {
       const error = await response.json();
       throw new Error(error.detail);
     }
     return await response.json();
   } catch (error) {
     showErrorMessage(error.message);
   }

2. Check user permissions before showing UI:
   if (user.permissions.includes('create_projects')) {
     showCreateButton();
   }

3. Validate before sending:
   if (!form.name) {
     showError("Project name required");
     return;
   }

4. Handle 401 globally (token expired):
   if (error.status === 401) {
     clearToken();
     redirectToLogin();
   }

5. Log errors for debugging:
   console.error('API Error:', error);
   /* Send to logging service */
```

---

## Summary

This comprehensive guide covers:

✓ **Complete hierarchy structure** - Understanding 6-level deep project decomposition
✓ **Authentication flow** - Registration, login, token generation
✓ **Authorization check** - Permission-based access control on every request
✓ **Data creation workflows** - How frontend data becomes database records
✓ **Status tracking** - Automatic entity history and audit trails
✓ **Maintenance logging** - Tracking service intervals and activities
✓ **Error handling** - Common errors and how to handle them
✓ **Business rules** - Constraints and validation logic

**For Frontend Developers:**
- Use this as reference when designing JSON request/response structures
- Understand validation requirements before sending data
- Check permissions from token before showing UI elements
- Handle all error scenarios gracefully

**For Backend Development:**
- Understand the business logic flow
- Know which validations are enforced
- Understand why certain rules exist
- Use as documentation for new features

---

**Last Updated:** March 28, 2026  
**Questions?** Contact the development team
