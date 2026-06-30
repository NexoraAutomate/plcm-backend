# RBAC Implementation Summary - Endpoints & Permissions

## Overview
Successfully updated the DEFAULT_ROLES array with comprehensive endpoint-to-role-permission mappings and added permission checks to all endpoints in the PLCM API.

## Changes Made

### 1. Updated DEFAULT_PERMISSIONS (app/auth.py)
Added comprehensive permissions for all entity types and operations:

#### User Management
- `view_users`, `create_users`, `edit_users`, `delete_users`, `assign_roles`, `remove_roles`

#### Customers Management
- `view_customers`, `create_customers`, `edit_customers`, `delete_customers`

#### Orders Management
- `view_orders`, `create_orders`, `edit_orders`, `delete_orders`, `approve_orders`

#### Projects Management
- `view_projects`, `create_projects`, `edit_projects`, `delete_projects`, `assign_project_manager`

#### Systems Management
- `view_systems`, `create_systems`, `edit_systems`, `delete_systems`

#### Subsystems Management
- `view_subsystems`, `create_subsystems`, `edit_subsystems`, `delete_subsystems`

#### Modules Management
- `view_modules`, `create_modules`, `edit_modules`, `delete_modules`

#### Units Management
- `view_units`, `create_units`, `edit_units`, `delete_units`

#### Components Management
- `view_components`, `create_components`, `edit_components`, `delete_components`

#### Inventory Management
- `view_inventory`, `create_inventory`, `edit_inventory`, `delete_inventory`

#### Maintenance Management
- `view_maintenance`, `create_maintenance`, `edit_maintenance`, `approve_maintenance`, `close_maintenance`

#### Entities & Status
- `view_entities`, `create_entities`, `edit_entities`, `delete_entities`
- `view_statuses`, `create_statuses`, `edit_statuses`, `delete_statuses`
- `view_status_history`, `create_status_history`, `edit_status_history`, `delete_status_history`

#### Reports & Role Management
- `view_reports`, `export_reports`
- `view_roles`, `create_roles`, `edit_roles`, `delete_roles`

### 2. Updated DEFAULT_ROLES (app/auth.py)

#### Admin Role
- **Description**: Full access to all features and endpoints
- **Permissions**: All permissions in DEFAULT_PERMISSIONS

#### ProjectManager Role
- **Description**: Can manage projects, systems, subsystems and teams
- **Permissions**: 
  - View users, projects (view/create/edit), systems (view/create/edit)
  - Subsystems, modules, units (view/create/edit)
  - View components and inventory
  - Maintenance (view/create/edit), reports, entities, statuses

#### Technician Role
- **Description**: Can view and manage subsystems, modules, units, components and maintenance
- **Permissions**:
  - View all resources
  - Edit subsystems, modules, units, components
  - Manage maintenance (create/edit/close)
  - Access to status history

#### Maintenance Role
- **Description**: Can manage maintenance logs and close maintenance tickets
- **Permissions**:
  - View all resources
  - Maintenance (create/edit/close)
  - Limited to maintenance-related operations

#### Viewer Role
- **Description**: Read-only access to all resources
- **Permissions**: All view permissions only

### 3. Added Permission Checks to All Endpoints

Permission decorators added using `@Depends(require_permission("permission_name"))` to all endpoints:

#### Users Router (_1_users.py)
- POST /users/ → `create_users`
- GET /users/ → `view_users`
- GET /users/{user_id}/ → `view_users`
- PUT /users/{user_id}/ → `edit_users`
- DELETE /users/{user_id}/ → `delete_users`
- GET /users/{user_id}/projects/ → `view_users`

#### Customers Router (_2_customers.py)
- POST /customers/ → `create_customers`
- GET /customers/ → `view_customers`
- GET /customers/{customer_id}/ → `view_customers`
- PUT /customers/{customer_id}/ → `edit_customers`
- DELETE /customers/{customer_id}/ → `delete_customers`

#### Orders Router (_3_orders.py)
- POST /orders/ → `create_orders`
- GET /orders/ → `view_orders`
- GET /orders/{order_id}/ → `view_orders`
- PUT /orders/{order_id}/ → `edit_orders`
- DELETE /orders/{order_id}/ → `delete_orders`
- GET /orders/{order_id}/projects/ → `view_orders`

#### Projects Router (_4_projects.py)
- POST /projects/ → `create_projects`
- GET /projects/ → `view_projects`
- GET /projects/{project_id}/ → `view_projects`
- PUT /projects/{project_id}/ → `edit_projects`
- DELETE /projects/{project_id}/ → `delete_projects`
- GET /projects/{project_id}/systems/ → `view_projects`

#### Systems Router (_5_systems.py)
- POST /systems/ → `create_systems`
- GET /systems/ → `view_systems`
- GET /systems/{system_id}/ → `view_systems`
- PUT /systems/{system_id}/ → `edit_systems`
- DELETE /systems/{system_id}/ → `delete_systems`
- GET /systems/{system_id}/subsystems/ → `view_systems`

#### Subsystems Router (_6_subsystem.py)
- POST /subsystems/ → `create_subsystems`
- GET /subsystems/ → `view_subsystems`
- GET /subsystems/{subsystem_id}/ → `view_subsystems`
- PUT /subsystems/{subsystem_id}/ → `edit_subsystems`
- DELETE /subsystems/{subsystem_id}/ → `delete_subsystems`
- GET /subsystems/{subsystem_id}/modules/ → `view_subsystems`

#### Modules Router (_7_module.py)
- POST /modules/ → `create_modules`
- GET /modules/ → `view_modules`
- GET /modules/{module_id}/ → `view_modules`
- PUT /modules/{module_id}/ → `edit_modules`
- DELETE /modules/{module_id}/ → `delete_modules`
- GET /modules/{module_id}/units/ → `view_modules`

#### Units Router (_8_unit.py)
- POST /units/ → `create_units`
- GET /units/ → `view_units`
- GET /units/{unit_id}/ → `view_units`
- PUT /units/{unit_id}/ → `edit_units`
- DELETE /units/{unit_id}/ → `delete_units`
- GET /units/{unit_id}/components/ → `view_units`

#### Components Router (_9_component.py)
- POST /components/ → `create_components`
- GET /components/ → `view_components`
- GET /components/{component_id}/ → `view_components`
- PUT /components/{component_id}/ → `edit_components`
- DELETE /components/{component_id}/ → `delete_components`
- GET /components/{component_id}/inventory/ → `view_components`

#### Inventory Router (_10_inventory.py)
- POST /inventory/ → `create_inventory`
- GET /inventory/ → `view_inventory`
- GET /inventory/{inventory_id}/ → `view_inventory`
- PUT /inventory/{inventory_id}/ → `edit_inventory`
- DELETE /inventory/{inventory_id}/ → `delete_inventory`

#### Maintenance Logger Router (maintenanceLog.py)
- POST /maintenance-logs/ → `create_maintenance`
- GET /maintenance-logs/ → `view_maintenance`
- GET /maintenance-logs/{log_id}/ → `view_maintenance`
- PUT /maintenance-logs/{log_id}/ → `edit_maintenance`
- DELETE /maintenance-logs/{log_id}/ → `delete_maintenance`

#### Status Router (status.py)
- POST /statuses/ → `create_statuses`
- GET /statuses/ → `view_statuses`
- GET /statuses/{status_id}/ → `view_statuses`
- PUT /statuses/{status_id}/ → `edit_statuses`
- DELETE /statuses/{status_id}/ → `delete_statuses`

#### Entity Status History Router (entitystatushistory.py)
- POST /entity-status-history/ → `create_status_history`
- GET /entity-status-history/ → `view_status_history`
- GET /entity-status-history/{history_id}/ → `view_status_history`
- PUT /entity-status-history/{history_id}/ → `edit_status_history`
- DELETE /entity-status-history/{history_id}/ → `delete_status_history`

#### Entity Router (entity.py)
- POST /entities/ → `create_entities`
- GET /entities/ → `view_entities`
- GET /entities/{entity_id}/ → `view_entities`
- PUT /entities/{entity_id}/ → `edit_entities`
- DELETE /entities/{entity_id}/ → `delete_entities`
- GET /entities/{entity_id}/status-history/ → `view_entities`
- GET /entities/{entity_id}/maintenance-logs/ → `view_entities`

## How Permission Checks Work

### Implementation Pattern
Each endpoint now uses the `require_permission` dependency:

```python
@router.post("/endpoint/", ...)
def endpoint_function(
    param: ParamType, 
    session: Session = Depends(get_session),
    current_user: User = Depends(require_permission("permission_name"))
):
    # endpoint logic
```

### Permission Resolution Flow
1. **Authentication**: `get_current_user()` verifies JWT token and retrieves user
2. **Authorization**: `require_permission("name")` checks if user has required permission
3. **Access**: If permission exists, endpoint executes; otherwise returns 403 Forbidden

### Error Handling
- Missing/expired token: `401 Unauthorized`
- Insufficient permissions: `403 Forbidden` with message: `"User does not have permission: {permission_name}"`

## Auth Router Endpoints

### Public Endpoints (No Permission Required)
- POST /auth/login - Login with credentials
- POST /auth/register - Register new user (gets Viewer role by default)

### Protected Endpoints
- POST /auth/change-password - Current user only
- GET /auth/me - Get current user info
- GET /auth/permissions - Get current user permissions

### Admin-Only Endpoints
- GET /auth/roles - List all roles
- GET /auth/roles/{role_id} - Get specific role
- POST /auth/roles - Create new role
- PUT /auth/roles/{role_id} - Update role
- POST /auth/assign-role - Assign role to user
- DELETE /auth/remove-role - Remove role from user
- GET /auth/updateDefaultpermissions - Update default permissions

## Testing the RBAC System

### Step 1: Initialize Database
The system automatically initializes permissions and roles on startup via `initialize_roles_and_permissions()`.

### Step 2: Create Test Users
```bash
# Register as new user (gets Viewer role)
POST /api/auth/register
{
  "username": "testuser",
  "email": "test@example.com",
  "password": "password123",
  "full_name": "Test User"
}

# Login
POST /api/auth/login
{
  "username": "testuser",
  "password": "password123"
}
```

### Step 3: Test Endpoint Permissions
Different users have different access levels based on their roles:

**Admin User**: Full access to all endpoints
**ProjectManager**: Can view/create/edit projects and related entities
**Technician**: Can manage subsystems, modules, and maintenance
**Maintenance User**: Can manage maintenance logs
**Viewer**: Read-only access to all endpoints

## Database Persistence

The system uses `sync_roles_and_permissions()` to:
1. Add new permissions to database
2. Add new roles to database
3. Update role-permission mappings
4. Preserve existing roles/permissions not in defaults

This allows for:
- Manual role/permission management
- Custom permissions for specific business needs
- Backward compatibility with existing data

## Future Enhancements

Consider implementing:
1. **Endpoint-level audit logging** - Track who accessed what endpoints
2. **Dynamic permissions** - Create custom permissions at runtime
3. **Permission groups** - Bundle related permissions
4. **Endpoint-specific role requirements** - Different roles per endpoint
5. **Resource-level permissions** - Control access to specific resources
6. **Permission caching** - Improve performance for permission checks

## Files Modified

- `app/auth.py` - Updated DEFAULT_PERMISSIONS and DEFAULT_ROLES
- `app/routers/_1_users.py` - Added permission checks
- `app/routers/_2_customers.py` - Added permission checks
- `app/routers/_3_orders.py` - Added permission checks
- `app/routers/_4_projects.py` - Added permission checks
- `app/routers/_5_systems.py` - Added permission checks
- `app/routers/_6_subsystem.py` - Added permission checks
- `app/routers/_7_module.py` - Added permission checks
- `app/routers/_8_unit.py` - Added permission checks
- `app/routers/_9_component.py` - Added permission checks
- `app/routers/_10_inventory.py` - Added permission checks
- `app/routers/maintenanceLog.py` - Added permission checks
- `app/routers/status.py` - Added permission checks
- `app/routers/entitystatushistory.py` - Added permission checks
- `app/routers/entity.py` - Added permission checks
