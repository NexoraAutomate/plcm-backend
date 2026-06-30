# PLCM System - API Documentation

**Version:** 1.0  
**Last Updated:** February 23, 2026

---

## Table of Contents
1. [Overview](#overview)
2. [Base URL & Authentication](#base-url--authentication)
3. [Error Handling](#error-handling)
4. [Data Models](#data-models)
5. [Endpoints](#endpoints)
   - [Users](#users)
   - [Customers](#customers)
   - [Orders](#orders)
   - [Projects](#projects)
   - [Systems](#systems)
   - [Subsystems](#subsystems)
   - [Modules](#modules)
   - [Units](#units)
   - [Components](#components)
   - [Inventory](#inventory)
   - [Status](#status)
   - [Entities](#entities)
   - [Entity Status History](#entity-status-history)
   - [Maintenance Logs](#maintenance-logs)

---

## Overview

The PLCM (Project Lifecycle Management) System API provides a RESTful interface for managing projects, systems, subsystems, modules, units, components, and inventory across your organization.

### Key Features
- Hierarchical project structure (Project → System → Subsystem → Module → Unit → Component)
- Inventory management for components
- User and customer management
- Order tracking
- Entity status history and maintenance logging
- Pagination support for list endpoints

---

## Base URL & Authentication

**Base URL:**
```
http://127.0.0.1:8000/api
```

### Query Parameters for Pagination
Most list endpoints support pagination:
- `skip` (integer, default: 0) - Number of items to skip
- `limit` (integer, default: 100) - Maximum number of items to return

**Example:**
```
GET /api/users/?skip=0&limit=10
```

---

## Error Handling

All endpoints return standardized error responses:

### 400 - Bad Request
```json
{
  "detail": "Invalid request parameters"
}
```

### 404 - Not Found
```json
{
  "detail": "Resource not found"
}
```

### 422 - Validation Error
```json
{
  "detail": [
    {
      "loc": ["field_name"],
      "msg": "error message",
      "type": "value_error"
    }
  ]
}
```

### 500 - Internal Server Error
```json
{
  "detail": "Internal Server Error"
}
```

---

## Data Models

### User
```json
{
  "id": 1,
  "username": "john.doe",
  "email": "john@example.com",
  "full_name": "John Doe",
  "is_active": true,
  "created_at": "2026-02-23T10:30:00Z",
  "projects": []
}
```

### Customer
```json
{
  "id": 1,
  "name": "Acme Corp",
  "contact_info": "contact@acme.com",
  "created_at": "2026-02-23T10:30:00Z",
  "orders": []
}
```

### Order
```json
{
  "id": 1,
  "customer_id": 1,
  "order_number": "ORD-001",
  "created_at": "2026-02-23T10:30:00Z",
  "status_id": 1,
  "projects": []
}
```

### Project
```json
{
  "id": 1,
  "name": "Project Alpha",
  "description": "Main project",
  "start_date": "2026-02-23T00:00:00Z",
  "end_date": "2026-12-31T00:00:00Z",
  "owner_id": 1,
  "order_id": 1,
  "status_id": 1,
  "created_at": "2026-02-23T10:30:00Z",
  "updated_at": "2026-02-23T10:30:00Z",
  "systems": []
}
```

### System
```json
{
  "id": 1,
  "name": "System One",
  "description": "Primary system",
  "project_id": 1,
  "status_id": 1,
  "created_at": "2026-02-23T10:30:00Z",
  "subsystems": []
}
```

### Status
```json
{
  "id": 1,
  "name": "Active",
  "description": "Resource is active"
}
```

### Entity
```json
{
  "id": 1,
  "entity_type": "Project",
  "entity_pk": 1,
  "display_name": "Project Alpha",
  "status_id": 1,
  "created_at": "2026-02-23T10:30:00Z"
}
```

---

## Endpoints

### Users

#### Create User
```http
POST /api/users/
Content-Type: application/json

{
  "username": "john.doe",
  "email": "john@example.com",
  "full_name": "John Doe",
  "is_active": true
}
```

**Response:** `200 OK`
```json
{
  "id": 1,
  "username": "john.doe",
  "email": "john@example.com",
  "full_name": "John Doe",
  "is_active": true,
  "created_at": "2026-02-23T10:30:00Z",
  "projects": []
}
```

#### List Users
```http
GET /api/users/?skip=0&limit=10
```

**Response:** `200 OK` - Array of User objects

#### Get User by ID
```http
GET /api/users/{user_id}/
```

**Response:** `200 OK` - User object

#### Update User
```http
PUT /api/users/{user_id}/
Content-Type: application/json

{
  "username": "john.doe.updated",
  "email": "john.new@example.com",
  "full_name": "John Doe Updated",
  "is_active": true
}
```

**Response:** `200 OK` - Updated User object

#### Delete User
```http
DELETE /api/users/{user_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

#### List User's Projects
```http
GET /api/users/{user_id}/projects/
```

**Response:** `200 OK` - Array of Project objects

---

### Customers

#### Create Customer
```http
POST /api/customers/
Content-Type: application/json

{
  "name": "Acme Corp",
  "contact_info": "contact@acme.com"
}
```

**Response:** `200 OK` - Customer object

#### List Customers
```http
GET /api/customers/?skip=0&limit=10
```

**Response:** `200 OK` - Array of Customer objects

#### Get Customer by ID
```http
GET /api/customers/{customer_id}/
```

**Response:** `200 OK` - Customer object

#### Update Customer
```http
PUT /api/customers/{customer_id}/
Content-Type: application/json

{
  "name": "Acme Corp Updated",
  "contact_info": "new.contact@acme.com"
}
```

**Response:** `200 OK` - Updated Customer object

#### Delete Customer
```http
DELETE /api/customers/{customer_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

#### List Customer's Orders
```http
GET /api/customers/{customer_id}/orders/
```

**Response:** `200 OK` - Array of Order objects

---

### Orders

#### Create Order
```http
POST /api/orders/
Content-Type: application/json

{
  "customer_id": 1,
  "order_number": "ORD-001",
  "status_id": 1
}
```

**Response:** `200 OK` - Order object

#### List Orders
```http
GET /api/orders/?skip=0&limit=10
```

**Response:** `200 OK` - Array of Order objects

#### Get Order by ID
```http
GET /api/orders/{order_id}/
```

**Response:** `200 OK` - Order object

#### Update Order
```http
PUT /api/orders/{order_id}/
Content-Type: application/json

{
  "customer_id": 1,
  "order_number": "ORD-001-UPDATED",
  "status_id": 2
}
```

**Response:** `200 OK` - Updated Order object

#### Delete Order
```http
DELETE /api/orders/{order_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

#### List Order's Projects
```http
GET /api/orders/{order_id}/projects/
```

**Response:** `200 OK` - Array of Project objects

---

### Projects

#### Create Project
```http
POST /api/projects/
Content-Type: application/json

{
  "name": "Project Alpha",
  "description": "Main project",
  "start_date": "2026-02-23T00:00:00Z",
  "end_date": "2026-12-31T00:00:00Z",
  "owner_id": 1
}
```

**Response:** `200 OK` - Project object

#### List Projects
```http
GET /api/projects/?skip=0&limit=10
```

**Response:** `200 OK` - Array of Project objects

#### Get Project by ID
```http
GET /api/projects/{project_id}/
```

**Response:** `200 OK` - Project object

#### Update Project
```http
PUT /api/projects/{project_id}/
Content-Type: application/json

{
  "name": "Project Alpha Updated",
  "description": "Updated description",
  "start_date": "2026-02-23T00:00:00Z",
  "end_date": "2026-12-31T00:00:00Z",
  "owner_id": 1,
  "status_id": 1
}
```

**Response:** `200 OK` - Updated Project object

#### Delete Project
```http
DELETE /api/projects/{project_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

#### List Project's Systems
```http
GET /api/projects/{project_id}/systems/
```

**Response:** `200 OK` - Array of System objects

---

### Systems

#### Create System
```http
POST /api/systems/
Content-Type: application/json

{
  "name": "System One",
  "description": "Primary system",
  "project_id": 1
}
```

**Response:** `200 OK` - System object

#### List Systems
```http
GET /api/systems/?skip=0&limit=10
```

**Response:** `200 OK` - Array of System objects

#### Get System by ID
```http
GET /api/systems/{system_id}/
```

**Response:** `200 OK` - System object

#### Update System
```http
PUT /api/systems/{system_id}/
Content-Type: application/json

{
  "name": "System One Updated",
  "description": "Updated description",
  "project_id": 1,
  "status_id": 1
}
```

**Response:** `200 OK` - Updated System object

#### Delete System
```http
DELETE /api/systems/{system_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

#### List System's Subsystems
```http
GET /api/systems/{system_id}/subsystems/
```

**Response:** `200 OK` - Array of Subsystem objects

---

### Subsystems

#### Create Subsystem
```http
POST /api/subsystems/
Content-Type: application/json

{
  "name": "Subsystem A",
  "description": "Part of System One",
  "system_id": 1
}
```

**Response:** `200 OK` - Subsystem object

#### List Subsystems
```http
GET /api/subsystems/?skip=0&limit=10
```

**Response:** `200 OK` - Array of Subsystem objects

#### Get Subsystem by ID
```http
GET /api/subsystems/{subsystem_id}/
```

**Response:** `200 OK` - Subsystem object

#### Update Subsystem
```http
PUT /api/subsystems/{subsystem_id}/
Content-Type: application/json

{
  "name": "Subsystem A Updated",
  "description": "Updated description",
  "system_id": 1,
  "status_id": 1
}
```

**Response:** `200 OK` - Updated Subsystem object

#### Delete Subsystem
```http
DELETE /api/subsystems/{subsystem_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

#### List Subsystem's Modules
```http
GET /api/subsystems/{subsystem_id}/modules/
```

**Response:** `200 OK` - Array of Module objects

---

### Modules

#### Create Module
```http
POST /api/modules/
Content-Type: application/json

{
  "name": "Module 1",
  "description": "Part of Subsystem A",
  "subsystem_id": 1
}
```

**Response:** `200 OK` - Module object

#### List Modules
```http
GET /api/modules/?skip=0&limit=10
```

**Response:** `200 OK` - Array of Module objects

#### Get Module by ID
```http
GET /api/modules/{module_id}/
```

**Response:** `200 OK` - Module object

#### Update Module
```http
PUT /api/modules/{module_id}/
Content-Type: application/json

{
  "name": "Module 1 Updated",
  "description": "Updated description",
  "subsystem_id": 1,
  "status_id": 1
}
```

**Response:** `200 OK` - Updated Module object

#### Delete Module
```http
DELETE /api/modules/{module_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

#### List Module's Units
```http
GET /api/modules/{module_id}/units/
```

**Response:** `200 OK` - Array of Unit objects

---

### Units

#### Create Unit
```http
POST /api/units/
Content-Type: application/json

{
  "name": "Unit 1",
  "description": "Part of Module 1",
  "module_id": 1
}
```

**Response:** `200 OK` - Unit object

#### List Units
```http
GET /api/units/?skip=0&limit=10
```

**Response:** `200 OK` - Array of Unit objects

#### Get Unit by ID
```http
GET /api/units/{unit_id}/
```

**Response:** `200 OK` - Unit object

#### Update Unit
```http
PUT /api/units/{unit_id}/
Content-Type: application/json

{
  "name": "Unit 1 Updated",
  "description": "Updated description",
  "module_id": 1,
  "status_id": 1
}
```

**Response:** `200 OK` - Updated Unit object

#### Delete Unit
```http
DELETE /api/units/{unit_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

#### List Unit's Components
```http
GET /api/units/{unit_id}/components/
```

**Response:** `200 OK` - Array of Component objects

---

### Components

#### Create Component
```http
POST /api/components/
Content-Type: application/json

{
  "name": "Component A",
  "description": "Part of Unit 1",
  "sku": "COMP-001",
  "unit_id": 1
}
```

**Response:** `200 OK` - Component object

#### List Components
```http
GET /api/components/?skip=0&limit=10
```

**Response:** `200 OK` - Array of Component objects

#### Get Component by ID
```http
GET /api/components/{component_id}/
```

**Response:** `200 OK` - Component object

#### Update Component
```http
PUT /api/components/{component_id}/
Content-Type: application/json

{
  "name": "Component A Updated",
  "description": "Updated description",
  "sku": "COMP-001-V2",
  "unit_id": 1,
  "status_id": 1
}
```

**Response:** `200 OK` - Updated Component object

#### Delete Component
```http
DELETE /api/components/{component_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

#### List Component's Inventory
```http
GET /api/components/{component_id}/inventory/
```

**Response:** `200 OK` - Array of Inventory objects

---

### Inventory

#### Create Inventory Item
```http
POST /api/inventory/
Content-Type: application/json

{
  "component_id": 1,
  "quantity": 50,
  "location": "Warehouse A"
}
```

**Response:** `200 OK` - Inventory object

#### List Inventory
```http
GET /api/inventory/?skip=0&limit=10
```

**Response:** `200 OK` - Array of Inventory objects

#### Get Inventory Item by ID
```http
GET /api/inventory/{inventory_id}/
```

**Response:** `200 OK` - Inventory object

#### Update Inventory Item
```http
PUT /api/inventory/{inventory_id}/
Content-Type: application/json

{
  "component_id": 1,
  "quantity": 75,
  "location": "Warehouse B"
}
```

**Response:** `200 OK` - Updated Inventory object

#### Delete Inventory Item
```http
DELETE /api/inventory/{inventory_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

---

### Status

#### Create Status
```http
POST /api/statuses/
Content-Type: application/json

{
  "name": "Active",
  "description": "Resource is active"
}
```

**Response:** `200 OK` - Status object

#### List Statuses
```http
GET /api/statuses/
```

**Response:** `200 OK` - Array of Status objects

#### Get Status by ID
```http
GET /api/statuses/{status_id}/
```

**Response:** `200 OK` - Status object

#### Update Status
```http
PUT /api/statuses/{status_id}/
Content-Type: application/json

{
  "name": "Inactive",
  "description": "Resource is inactive"
}
```

**Response:** `200 OK` - Updated Status object

#### Delete Status
```http
DELETE /api/statuses/{status_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

---

### Entities

#### Create Entity
```http
POST /api/entities/
Content-Type: application/json

{
  "entity_type": "Project",
  "entity_pk": 1,
  "display_name": "Project Alpha"
}
```

**Response:** `200 OK` - Entity object

#### List Entities
```http
GET /api/entities/?skip=0&limit=10
```

**Response:** `200 OK` - Array of Entity objects

#### Get Entity by ID
```http
GET /api/entities/{entity_id}/
```

**Response:** `200 OK` - Entity object

#### Update Entity
```http
PUT /api/entities/{entity_id}/
Content-Type: application/json

{
  "entity_type": "Project",
  "entity_pk": 1,
  "display_name": "Project Alpha Updated",
  "status_id": 1
}
```

**Response:** `200 OK` - Updated Entity object

#### Delete Entity
```http
DELETE /api/entities/{entity_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

#### List Entity's Status History
```http
GET /api/entities/{entity_id}/status-history/
```

**Response:** `200 OK` - Array of EntityStatusHistory objects

#### List Entity's Maintenance Logs
```http
GET /api/entities/{entity_id}/maintenance-logs/
```

**Response:** `200 OK` - Array of MaintenanceLog objects

---

### Entity Status History

#### Create Status History
```http
POST /api/entity-status-history/
Content-Type: application/json

{
  "entity_id": 1,
  "status_id": 1,
  "changed_by": 1,
  "notes": "Status updated to Active"
}
```

**Response:** `200 OK` - EntityStatusHistory object

#### List Status History
```http
GET /api/entity-status-history/?skip=0&limit=10
```

**Response:** `200 OK` - Array of EntityStatusHistory objects

#### Get Status History by ID
```http
GET /api/entity-status-history/{history_id}/
```

**Response:** `200 OK` - EntityStatusHistory object

#### Update Status History
```http
PUT /api/entity-status-history/{history_id}/
Content-Type: application/json

{
  "entity_id": 1,
  "status_id": 2,
  "changed_by": 1,
  "notes": "Updated notes"
}
```

**Response:** `200 OK` - Updated EntityStatusHistory object

#### Delete Status History
```http
DELETE /api/entity-status-history/{history_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

---

### Maintenance Logs

#### Create Maintenance Log
```http
POST /api/maintenance-logs/
Content-Type: application/json

{
  "entity_id": 1,
  "performed_by": 1,
  "notes": "Routine maintenance completed",
  "performed_at": "2026-02-23T10:00:00Z",
  "next_due": "2026-03-23T10:00:00Z"
}
```

**Response:** `200 OK` - MaintenanceLog object

#### List Maintenance Logs
```http
GET /api/maintenance-logs/?skip=0&limit=10
```

**Response:** `200 OK` - Array of MaintenanceLog objects

#### Get Maintenance Log by ID
```http
GET /api/maintenance-logs/{log_id}/
```

**Response:** `200 OK` - MaintenanceLog object

#### Update Maintenance Log
```http
PUT /api/maintenance-logs/{log_id}/
Content-Type: application/json

{
  "entity_id": 1,
  "performed_by": 1,
  "notes": "Updated maintenance notes",
  "next_due": "2026-03-25T10:00:00Z"
}
```

**Response:** `200 OK` - Updated MaintenanceLog object

#### Delete Maintenance Log
```http
DELETE /api/maintenance-logs/{log_id}/
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

---

## Usage Examples

### Example 1: Create a Complete Project Hierarchy

```javascript
// 1. Create a User
const createUser = async () => {
  const response = await fetch('http://127.0.0.1:8000/api/users/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username: 'john.doe',
      email: 'john@example.com',
      full_name: 'John Doe',
      is_active: true
    })
  });
  return response.json();
};

// 2. Create a Project
const createProject = async (userId) => {
  const response = await fetch('http://127.0.0.1:8000/api/projects/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: 'Project Alpha',
      description: 'Main project',
      start_date: new Date().toISOString(),
      end_date: new Date(Date.now() + 365*24*60*60*1000).toISOString(),
      owner_id: userId
    })
  });
  return response.json();
};

// 3. Create Systems under the Project
const createSystem = async (projectId) => {
  const response = await fetch('http://127.0.0.1:8000/api/systems/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: 'System One',
      description: 'Primary system',
      project_id: projectId
    })
  });
  return response.json();
};
```

### Example 2: Retrieve Full Project Structure

```javascript
const getProjectStructure = async (projectId) => {
  const response = await fetch(`http://127.0.0.1:8000/api/projects/${projectId}/`);
  const project = await response.json();
  
  // Project includes systems array if populated
  console.log('Project:', project);
  console.log('Systems:', project.systems);
};
```

### Example 3: Update with Pagination

```javascript
const getUsers = async (page = 1) => {
  const skip = (page - 1) * 10;
  const response = await fetch(`http://127.0.0.1:8000/api/users/?skip=${skip}&limit=10`);
  return response.json();
};
```

---

## Best Practices for Frontend Developers

1. **Always Check Status Codes**: Implement proper error handling for different HTTP status codes
2. **Use Pagination**: For list endpoints, implement pagination to manage large datasets
3. **Timestamps**: All timestamps are in ISO 8601 format (UTC)
4. **Null Values**: Optional fields may be null; check before using
5. **IDs**: All resource IDs are integers. Use them as path parameters
6. **Validation**: Validate data on the frontend before sending to the API
7. **Relationships**: Use the nested endpoints to fetch related resources
8. **Rate Limiting**: Implement request debouncing for frequently called endpoints

---

## Support

For API issues or questions, contact the backend team or refer to the FastAPI interactive documentation:
```
http://127.0.0.1:8000/docs
```

This Swagger UI provides interactive testing of all endpoints with real-time validation.
