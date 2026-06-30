# RBAC Quick Reference Card

## Essential Commands

### Start Application
```bash
python -m uvicorn app.main:app --reload
```

### Register User
```bash
curl -X POST "http://localhost:8000/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"user1","email":"user1@example.com","full_name":"User One","password":"pass123"}'
```

### Login & Get Token
```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"user1","password":"pass123"}'
```

### Use Token in Request
```bash
curl -X GET "http://localhost:8000/api/auth/me" \
  -H "Authorization: Bearer <token_here>"
```

---

## API Endpoints

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | `/api/auth/register` | No | Register new user |
| POST | `/api/auth/login` | No | Login, get JWT token |
| POST | `/api/auth/change-password` | Yes | Change user password |
| GET | `/api/auth/me` | Yes | Get current user info |
| GET | `/api/auth/permissions` | Yes | List user permissions |
| GET | `/api/auth/roles` | Admin | List all roles |
| POST | `/api/auth/roles` | Admin | Create new role |
| PUT | `/api/auth/roles/{id}` | Admin | Update role |
| POST | `/api/auth/assign-role` | Admin | Add role to user |
| DELETE | `/api/auth/remove-role` | Admin | Remove role from user |

---

## Permissions for Endpoints

```python
# Require authentication only
@router.get("/data")
def get_data(user = Depends(get_current_user)):
    pass

# Require specific permission
@router.post("/projects")
def create_project(user = Depends(require_permission("create_project"))):
    pass

# Require specific role
@router.delete("/system/{id}")
def delete_system(user = Depends(require_role("Admin"))):
    pass
```

---

## Default Roles

| Role | Access Level |
|------|--------------|
| Admin | All resources, all operations |
| ProjectManager | Create/manage projects, teams, inventory |
| Technician | Manage systems, components, maintenance |
| Viewer | Read-only (default for new users) |

---

## Permission Names

**User Ops**: `view_user`, `create_user`, `edit_user`, `delete_user`
**Project Ops**: `view_project`, `create_project`, `edit_project`, `delete_project`
**System Ops**: `view_system`, `create_system`, `edit_system`, `delete_system`
**Component Ops**: `view_component`, `create_component`, `edit_component`, `delete_component`
**Other**: `manage_inventory`, `view_reports`, `manage_maintenance`

---

## Token Format

```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "user_id": 1,
  "username": "john",
  "email": "john@example.com",
  "roles": ["Admin"],
  "permissions": ["view_user", "create_user", ...]
}
```

Use in header: `Authorization: Bearer <access_token>`

---

## Important Files

| File | Purpose |
|------|---------|
| `app/auth.py` | Core auth logic |
| `app/routers/auth.py` | API endpoints |
| `app/models/tables.py` | Database schema |
| `app/main.py` | Application setup |
| `.env` | Database URL (required) |

---

## Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| 401 Unauthorized | Add token to Authorization header |
| 403 Forbidden | Assign required permission/role to user |
| Invalid token | Re-login to get new token |
| Token expired | Token valid for 30 days by default |
| Module not found | Run `pip install -r requirements.txt` |
| Database error | Check DATABASE_URL in .env |

---

## Required Before Production

⚠️ **CHANGE THIS**: `app/auth.py` line 15
```python
SECRET_KEY = "your-secret-key-change-in-production"
```

Generate new key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Database Queries

```sql
-- List all users
SELECT id, username, email, is_active FROM user;

-- List all roles
SELECT id, name, description FROM role;

-- List user roles
SELECT u.username, r.name 
FROM user u
JOIN user_role ur ON u.id = ur.user_id
JOIN role r ON ur.role_id = r.id;

-- List role permissions
SELECT r.name, p.name
FROM role r
JOIN role_permission rp ON r.id = rp.role_id
JOIN permission p ON rp.permission_id = p.id;

-- Deactivate user (prevents login)
UPDATE user SET is_active = FALSE WHERE username = 'username';

-- Assign role to user
INSERT INTO user_role (user_id, role_id) VALUES (1, 2);

-- Remove role from user
DELETE FROM user_role WHERE user_id = 1 AND role_id = 2;
```

---

## Configuration

| Setting | Default | Location |
|---------|---------|----------|
| SECRET_KEY | `"your-secret-key..."` | `app/auth.py:15` |
| ALGORITHM | `"HS256"` | `app/auth.py:16` |
| TOKEN_EXPIRE_MINUTES | 43200 (30 days) | `app/auth.py:17` |
| DATABASE_URL | `.env` file | `.env` |

---

## Testing Response

```json
LOGIN RESPONSE:
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "user_id": 1,
  "username": "john",
  "email": "john@example.com",
  "roles": ["Admin"],
  "permissions": ["..."]
}

GET /ME RESPONSE:
{
  "id": 1,
  "username": "john",
  "email": "john@example.com",
  "full_name": "John Doe",
  "is_active": true,
  "roles": [
    {
      "id": 1,
      "name": "Admin",
      "description": "...",
      "permissions": [...]
    }
  ]
}

ERROR RESPONSE:
{
  "detail": "Invalid username or password"  // 401
  "detail": "User does not have permission: create_user"  // 403
}
```

---

## Python Example

```python
import requests

BASE = "http://localhost:8000/api"

# Register
requests.post(f"{BASE}/auth/register", json={
    "username": "john",
    "email": "john@example.com",
    "full_name": "John",
    "password": "pass123"
})

# Login
resp = requests.post(f"{BASE}/auth/login", json={
    "username": "john",
    "password": "pass123"
})
token = resp.json()["access_token"]

# Use token
headers = {"Authorization": f"Bearer {token}"}
user = requests.get(f"{BASE}/auth/me", headers=headers).json()
print(user)

# Check permissions
perms = requests.get(f"{BASE}/auth/permissions", headers=headers).json()
print(perms)
```

---

## Documentation

- **Complete Docs**: `RECOVERY_COMPLETE.md`
- **Tech Specs**: `RBAC_RECOVERY_SUMMARY.md`
- **Endpoint Guide**: `ENDPOINT_PROTECTION_GUIDE.md`
- **Deploy Guide**: `DEPLOYMENT_CHECKLIST.md`

---

**Version**: 1.0 | **Date**: 2024 | **Status**: ✅ Production Ready
