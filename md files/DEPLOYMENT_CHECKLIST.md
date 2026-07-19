# RBAC Implementation - Deployment Checklist

## Pre-Production Checklist

### ⚠️ CRITICAL - Must Do Before Production
- [ ] **Change SECRET_KEY** in `app/auth.py` line 15
  - Current: `SECRET_KEY = "your-secret-key-change-in-production"`
  - Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
  - Store in environment variable (`AUTH_SECRET_KEY`)
  - Update code to use environment variable

### Configuration
- [ ] Set DATABASE_URL in `.env` file (if using external database)
- [ ] Set JWT token expiration time if needed (default: 30 days in `app/auth.py`)
- [ ] Configure ALGORITHM if needed (default: HS256)
- [ ] Review and customize default permissions if needed
- [ ] Review and customize default roles if needed

### Database
- [ ] Verify database is created and accessible
- [ ] Ensure all tables are created (happens on startup)
- [ ] Backup existing database before first production run
- [ ] Verify default roles and permissions were created (`SELECT * FROM role;`)

### Dependencies
- [ ] Run `pip install -r requirements.txt`
- [ ] Verify all packages installed correctly
- [ ] Check specific versions: python-jose, passlib, pydantic-settings, pyjwt

### Application
- [ ] Start application and check for errors
- [ ] Verify default roles created in database
- [ ] Test login endpoint with curl or Postman
- [ ] Test protected endpoint with valid token
- [ ] Test protected endpoint with invalid token (should return 403)

### Security
- [ ] All passwords are hashed (never stored plain text)
- [ ] TOKEN_EXPIRE_MINUTES is set correctly (default: 30 days = 43200 minutes)
- [ ] HTTPS enabled in production
- [ ] CORS configured appropriately for your frontend
- [ ] Auth secret key changed and stored securely

---

## Post-Deployment Checklist

### Initial Setup
- [ ] Create admin user (register endpoint, then promote to Admin role)
- [ ] Create users for each team member(s)
- [ ] Assign appropriate roles to users
- [ ] Verify each user can login and access appropriate data
- [ ] Test permission checking works correctly

### Testing
- [ ] Test login with correct credentials → success
- [ ] Test login with wrong password → 401 error
- [ ] Test protected endpoint with token → success
- [ ] Test protected endpoint without token → 401 error
- [ ] Test protected endpoint with wrong role → 403 error
- [ ] Test changing password endpoint
- [ ] Test role assignment (admin only)
- [ ] Test role removal (admin only)
- [ ] Test user list returns only appropriate data

### Monitoring
- [ ] Check logs for authentication failures
- [ ] Monitor for suspicious login attempts
- [ ] Verify token expiration works correctly
- [ ] Check that inactive users cannot login
- [ ] Verify password hashing is working (compare database entries)

---

## File Structure Verification

```
app/
├── __init__.py
├── main.py                 ← Updated with role initialization
├── database.py             ← Unchanged, working
├── auth.py                 ← ✅ Core auth module (NEW/RECOVERED)
│
├── models/
│   ├── __init__.py
│   ├── base.py             ← ✅ Has UserCommon.password, PermissionBase, RoleBase
│   └── tables.py           ← ✅ Has User, Role, Permission, UserRole, RolePermission
│
├── schemas/
│   ├── __init__.py
│   └── schemas.py          ← ✅ Has all auth schemas (TokenResponse, LoginRequest, etc.)
│
├── routers/
│   ├── __init__.py         ← ✅ Updated to include auth router
│   ├── auth.py             ← ✅ Auth endpoints (NEW/RECOVERED)
│   ├── 1_users.py
│   ├── 2_customers.py
│   ├── 3_orders.py
│   ├── 4_projects.py
│   ├── 5_systems.py
│   ├── 6_subsystem.py
│   ├── 7_module.py
│   ├── 8_unit.py
│   ├── 9_component.py
│   ├── 10_inventory.py
│   ├── entity.py
│   ├── entitystatushistory.py
│   ├── maintenanceLog.py
│   └── status.py
│
└── __pycache__/            ← Automatically generated

requirements.txt            ← ✅ Updated with auth packages
.env                        ← Important: Set DATABASE_URL here
.gitignore                  ← Important: Keep .env out of version control
```

---

## Quick Verification Steps

### 1. Check Python Syntax
```bash
python -m py_compile app/auth.py
python -m py_compile app/routers/auth.py
echo "✓ Syntax OK"
```

### 2. Verify Imports Work
```python
python -c "from app.auth import hash_password, create_access_token, initialize_roles_and_permissions; print('✓ Imports OK')"
python -c "from app.routers.auth import router; print('✓ Router OK')"
```

### 3. Check Database Initialization
```python
python -c "
from app.database import init_db, engine
from app.auth import initialize_roles_and_permissions
from sqlmodel import Session

init_db()
with Session(engine) as session:
    initialize_roles_and_permissions(session)
    from sqlmodel import select
    from app.models.tables import Role, Permission
    roles = session.exec(select(Role)).all()
    perms = session.exec(select(Permission)).all()
    print(f'✓ Roles: {len(roles)} created')
    print(f'✓ Permissions: {len(perms)} created')
"
```

### 4. Test Application Startup
```bash
python -m uvicorn app.main:app --reload
# Check for errors, should see:
# - Database tables created
# - Roles initialized
# - API ready at http://localhost:8000
```

### 5. Test API Endpoints
```bash
# Get OpenAPI docs
curl http://localhost:8000/docs

# Register user
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "email": "admin@example.com", "full_name": "Admin", "password": "admin123"}'

# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'

# Test protected endpoint (use token from login response)
curl -X GET http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'passlib'"
**Solution**: Run `pip install -r requirements.txt`

### Issue: "ModuleNotFoundError: No module named 'app.auth'"
**Solution**: Ensure you're running from workspace root directory

### Issue: "Secret key not found"
**Solution**: Change SECRET_KEY in `app/auth.py` line 15

### Issue: "Database error during initialization"
**Solution**: 
1. Check DATABASE_URL is set in .env
2. Ensure database server is running
3. Check database permissions

### Issue: "401 Unauthorized" on protected endpoint
**Solution**:
1. Verify token is in Authorization header
2. Check token hasn't expired (login again)
3. Verify token format: `Authorization: Bearer <token>`

### Issue: "403 Forbidden" on protected endpoint
**Solution**:
1. User doesn't have required permission/role
2. Assign permission to user via admin endpoint
3. Check user's roles: GET `/api/auth/permissions`

---

## Default Roles Setup

When application starts, these roles are automatically created:

| Role | Permissions | Use Case |
|------|-------------|----------|
| **Admin** | All 20+ | System administrators, full access |
| **ProjectManager** | Project, Team, Inventory, System (view/create/edit/delete) | Project leads, managers |
| **Technician** | System, Subsystem, Module, Unit, Component, Maintenance (all) | Field technicians, maintenance staff |
| **Viewer** | All resources (view only) | Stakeholders, auditors, default for new users |

---

## First Production User

1. **Register the first admin user**:
```bash
curl -X POST "http://localhost:8000/api/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "email": "admin@company.com",
    "full_name": "System Administrator",
    "password": "ComplexPassword123!"
  }'
```

2. **Login to get token**:
```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "ComplexPassword123!"
  }'
# Save the access_token from response
```

3. **Verify admin user created** (user_id should be 1):
```bash
curl -X GET "http://localhost:8000/api/auth/me" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

4. **Promote user to Admin role** (using database directly):
```sql
-- Get role IDs
SELECT id, name FROM role;

-- Assign Admin role (usually role_id=1)
INSERT INTO user_role (user_id, role_id) VALUES (1, 1);
```

Or via API (admin endpoint):
```bash
curl -X POST "http://localhost:8000/api/auth/assign-role" \
  -H "Authorization: Bearer ANOTHER_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 1,
    "role_id": 1
  }'
```

---

## Maintenance Tasks

### Regular Backups
```bash
# Backup database
cp database.db database.db.backup.$(date +%Y%m%d_%H%M%S)
```

### Monitor Logs
```bash
# Check for auth failures
grep -i "unauthorized\|forbidden\|401\|403" app.log

# Check for unexpected errors
grep "ERROR" app.log
```

### User Management
```bash
# List all users
SELECT username, email, is_active, created_at FROM user;

# List user roles
SELECT u.username, r.name FROM user u
JOIN user_role ur ON u.id = ur.user_id
JOIN role r ON ur.role_id = r.id;

# Deactivate user (prevent login)
UPDATE user SET is_active = FALSE WHERE username = 'username';

# Remove role from user
DELETE FROM user_role WHERE user_id = 1 AND role_id = 2;
```

### Token Expiration
- Default: 30 days
- Configurable in `app/auth.py` line 16: `ACCESS_TOKEN_EXPIRE_MINUTES`
- Users need to re-login when tokens expire
- Consider shorter expiration (1-7 days) for higher security

---

## Support Resources

### Documentation Files
- `RECOVERY_COMPLETE.md` - Overview of recovery
- `RBAC_RECOVERY_SUMMARY.md` - Detailed tech specs
- `ENDPOINT_PROTECTION_GUIDE.md` - How to protect endpoints

### Code References
- `app/auth.py` - All auth functions
- `app/routers/auth.py` - All endpoints
- `app/models/tables.py` - Database schema

### Testing
- Use `/docs` endpoint for Swagger UI (interactive API testing)
- Use Postman or Insomnia for API testing
- Write unit tests for custom endpoints

---

## Sign-Off

- [ ] All checklist items reviewed
- [ ] SECRET_KEY changed
- [ ] Database configured
- [ ] Application tested
- [ ] Default admin user created
- [ ] Team members can login
- [ ] Protected endpoints work correctly
- [ ] Documentation accessible to team

**Deployment Date**: ___________
**Deployed By**: ___________
**Notes**: _______________________________

---

**Ready for Production Use!**
