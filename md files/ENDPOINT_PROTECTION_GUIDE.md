# Protecting Endpoints with RBAC

Quick reference for adding authentication and authorization to your existing endpoints.

## Basic Pattern

### 1. Require Authentication Only
User must be logged in, no specific role required:

```python
from fastapi import APIRouter, Depends
from app.routers.auth import get_current_user
from app.models.tables import User

router = APIRouter()

@router.get("/my-data")
def get_user_data(current_user: User = Depends(get_current_user)):
    """Returns data specific to the authenticated user."""
    return {"user_id": current_user.id, "username": current_user.username}
```

### 2. Require Specific Permission
User must have a specific permission:

```python
from app.routers.auth import require_permission

@router.post("/projects")
def create_project(
    project_data: ProjectCreate,
    current_user: User = Depends(require_permission("create_project"))
):
    """Only users with 'create_project' permission can create projects."""
    # Create project logic here
    pass
```

### 3. Require Specific Role
User must have a specific role:

```python
from app.routers.auth import require_role

@router.delete("/system/{system_id}")
def delete_system(
    system_id: int,
    current_user: User = Depends(require_role("Admin"))
):
    """Only Admin users can delete systems."""
    # Delete system logic here
    pass
```

### 4. Multiple Permission Checks
Can chain multiple dependencies for complex requirements:

```python
@router.put("/project/{project_id}")
def update_project(
    project_id: int,
    updated_data: ProjectUpdate,
    current_user: User = Depends(require_permission("edit_project")),
    admin_check: User = Depends(require_role("Admin"))
):
    """User must have edit_project permission AND be an Admin."""
    # Update project logic here
    pass
```

## Example: Protecting User Router

Before (no auth):
```python
from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import User
from app.schemas import schemas

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/")
def list_users(session: Session = Depends(get_session)):
    users = session.exec(select(User)).all()
    return users

@router.post("/")
def create_user(user: schemas.UserCreate, session: Session = Depends(get_session)):
    db_user = User.from_orm(user)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

@router.delete("/{user_id}")
def delete_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if user:
        session.delete(user)
        session.commit()
    return {"ok": True}
```

After (with auth):
```python
from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.database import get_session
from app.models.tables import User
from app.routers.auth import require_permission, require_role
from app.schemas import schemas

router = APIRouter(prefix="/users", tags=["users"])

@router.get("/")
def list_users(
    current_user: User = Depends(require_permission("view_user")),
    session: Session = Depends(get_session)
):
    """List all users. Requires view_user permission."""
    users = session.exec(select(User)).all()
    return users

@router.post("/")
def create_user(
    user: schemas.UserCreate,
    current_user: User = Depends(require_permission("create_user")),
    session: Session = Depends(get_session)
):
    """Create a new user. Requires create_user permission."""
    db_user = User.from_orm(user)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(require_role("Admin")),
    session: Session = Depends(get_session)
):
    """Delete a user. Requires Admin role."""
    user = session.get(User, user_id)
    if user:
        session.delete(user)
        session.commit()
    return {"ok": True}
```

## Permission Names

Use these permission names in `require_permission()`:

### User Management
- `view_user` - View user information
- `create_user` - Create new users
- `edit_user` - Edit user details
- `delete_user` - Delete users

### Project Management
- `view_project` - View projects
- `create_project` - Create new projects
- `edit_project` - Edit existing projects
- `delete_project` - Delete projects

### System Management
- `view_system` - View systems
- `create_system` - Create new systems
- `edit_system` - Edit systems
- `delete_system` - Delete systems

### Component Management
- `view_component` - View components
- `create_component` - Create new components
- `edit_component` - Edit components
- `delete_component` - Delete components

### Other Operations
- `manage_inventory` - Manage inventory items
- `view_reports` - Generate and view reports
- `manage_maintenance` - Manage maintenance logs

## Role Names

Use these role names in `require_role()`:

1. **Admin** - Full system access
2. **ProjectManager** - Project and team management
3. **Technician** - System and component management
4. **Viewer** - Read-only access

## Advanced Patterns

### Get Current User in Endpoint
```python
@router.get("/profile")
def get_profile(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get profile of currently logged-in user."""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "roles": [role.name for role in current_user.roles]
    }
```

### Check User's Permissions in Code
```python
from app.auth import get_user_permissions

@router.get("/project/{project_id}")
def get_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Get project only if user has view_project permission."""
    permissions = get_user_permissions(current_user, session)
    
    if "view_project" not in permissions:
        raise HTTPException(status_code=403, detail="Access denied")
    
    project = session.get(Project, project_id)
    return project
```

### Owner-Based Access Control
```python
@router.delete("/project/{project_id}")
def delete_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Delete project only if user is owner or admin."""
    project = session.get(Project, project_id)
    
    is_owner = project.owner_id == current_user.id
    is_admin = any(role.name == "Admin" for role in current_user.roles)
    
    if not (is_owner or is_admin):
        raise HTTPException(status_code=403, detail="Only owner or admin can delete")
    
    session.delete(project)
    session.commit()
    return {"ok": True}
```

## Testing Authentication

### Using cURL

1. **Register user**:
```bash
curl -X POST "http://localhost:8000/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john",
    "email": "john@example.com",
    "full_name": "John Doe",
    "password": "password123"
  }'
```

2. **Login and get token**:
```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john",
    "password": "password123"
  }'
# Returns: {"access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...", ...}
```

3. **Use token to access protected endpoint**:
```bash
curl -X GET "http://localhost:8000/api/users/" \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..."
```

### Using Python Requests

```python
import requests

BASE_URL = "http://localhost:8000/api"

# Register
response = requests.post(f"{BASE_URL}/auth/register", json={
    "username": "john",
    "email": "john@example.com",
    "full_name": "John Doe",
    "password": "password123"
})
print("Register:", response.status_code)

# Login
response = requests.post(f"{BASE_URL}/auth/login", json={
    "username": "john",
    "password": "password123"
})
token = response.json()["access_token"]
print("Login:", response.status_code, "Token:", token[:20] + "...")

# Use token
headers = {"Authorization": f"Bearer {token}"}
response = requests.get(f"{BASE_URL}/users/", headers=headers)
print("Get users:", response.status_code, response.json())
```

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| 401 Unauthorized | Missing or invalid token | Ensure Authorization header is included with valid token |
| 403 Forbidden | User doesn't have permission | Assign required permission/role to user |
| 422 Unprocessable Entity | Token validation failed | Re-login to get new token (old one expired) |
| 500 Internal Server Error | Missing authorization import | Verify imports: `from app.routers.auth import ...` |

## Summary

1. Import the dependency: `from app.routers.auth import require_permission`
2. Add to endpoint: `current_user: User = Depends(require_permission("permission_name"))`
3. Test with valid token in Authorization header

That's it! Your endpoint is now protected.
