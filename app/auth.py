"""
Authentication and Authorization Modules
Handles JWT token generation, password hashing, and role-based access control
Works entirely offline - no internet required
"""

import os
from datetime import datetime, timedelta, timezone, UTC
from typing import Optional, List
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import HTTPException, status
from sqlmodel import Session, select
from pwdlib import PasswordHash
from app.models.tables import User

# Configuration (override via environment variables)
SECRET_KEY = os.getenv(
    "AUTH_SECRET_KEY",
    "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7",
)
ALGORITHM = os.getenv("AUTH_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(30 * 24)))

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
password_hash = PasswordHash.recommended()

# ==================== PASSWORD HANDLING ====================
def hash_password(password: str) -> str:
    return password_hash.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash. Truncate to 72 bytes (bcrypt limit) for consistency."""
    return password_hash.verify(plain_password, hashed_password)

# ==================== JWT TOKEN HANDLING ====================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# ==================== USER RETRIEVAL ====================
def get_user_from_token(token: str, session: Session):
    """Get user object from JWT token."""
    # print("Getting user from token:", token)
    from app.models.tables import User
    payload = decode_token(token)
    user_id = payload.get("sub")
    # print("USER ID FROM TOKEN:", user_id)
    
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user

# ==================== DECODE TOKEN ====================
def decode_token(token: str) -> dict:
    """Decode and validate a JWT token."""
    # print("compiler reached in decode_token")

    try:
        # print("compiler reached in Try statement")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # print("DECODED PAYLOAD:", payload)
        user_id = payload.get("sub")
        # print("USER ID FROM PAYLOAD:", user_id)  
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )
        payload["sub"] = int(user_id)
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

# ==================== PERMISSION CHECKING ====================
def get_user_permissions(user) -> List[str]:
    """Get all permissions for a user based on their roles."""
    permissions = set()
    
    for role in user.roles:
        for permission in role.permissions:
            permissions.add(permission.name)
    
    return list(permissions)

def check_permission(user, required_permission: str) -> bool:
    """Check if user has a specific permission."""
    permissions = get_user_permissions(user)
    return required_permission in permissions

def check_role(user:User, required_role: str) -> bool:
    return any(role.name == required_role for role in user.roles)

# ==================== DEFAULT ROLES & PERMISSIONS ====================
DEFAULT_PERMISSIONS = [
    # ==================== USERS MANAGEMENT ====================
    {"name": "view_users", "description": "View users list and details"},
    {"name": "create_users", "description": "Create new users"},
    {"name": "edit_users", "description": "Edit user information"},
    {"name": "delete_users", "description": "Delete users"},
    {"name": "assign_roles", "description": "Assign roles to users"},
    {"name": "remove_roles", "description": "Remove roles from users"},
    
    # ==================== CUSTOMERS MANAGEMENT ====================
    {"name": "view_customers", "description": "View customers"},
    {"name": "create_customers", "description": "Create customers"},
    {"name": "edit_customers", "description": "Edit customers"},
    {"name": "delete_customers", "description": "Delete customers"},
    {"name": "customers", "description": "list all customers"},
    
    # ==================== ORDERS MANAGEMENT ====================
    {"name": "view_orders", "description": "View orders"},
    {"name": "create_orders", "description": "Create orders"},
    {"name": "edit_orders", "description": "Edit orders"},
    {"name": "delete_orders", "description": "Delete orders"},
    {"name": "approve_orders", "description": "Approve orders"},
    
    # ==================== PROJECTS MANAGEMENT ====================
    {"name": "view_projects", "description": "View projects"},
    {"name": "create_projects", "description": "Create projects"},
    {"name": "edit_projects", "description": "Edit projects"},
    {"name": "delete_projects", "description": "Delete projects"},
    {"name": "assign_project_manager", "description": "Assign project managers"},

    # ==================== SYSTEMS MANAGEMENT ====================
    {"name": "view_systems", "description": "View systems"},
    {"name": "create_systems", "description": "Create systems"},
    {"name": "edit_systems", "description": "Edit systems"},
    {"name": "delete_systems", "description": "Delete systems"},

    # ==================== SUBSYSTEMS MANAGEMENT ====================
    {"name": "view_subsystems", "description": "View subsystems"},
    {"name": "create_subsystems", "description": "Create subsystems"},
    {"name": "edit_subsystems", "description": "Edit subsystems"},
    {"name": "delete_subsystems", "description": "Delete subsystems"},
    
    # ==================== MODULES MANAGEMENT ====================
    {"name": "view_modules", "description": "View modules"},
    {"name": "create_modules", "description": "Create modules"},
    {"name": "edit_modules", "description": "Edit modules"},
    {"name": "delete_modules", "description": "Delete modules"},
    
    # ==================== UNITS MANAGEMENT ====================
    {"name": "view_units", "description": "View units"},
    {"name": "create_units", "description": "Create units"},
    {"name": "edit_units", "description": "Edit units"},
    {"name": "delete_units", "description": "Delete units"},

    # ==================== COMPONENTS MANAGEMENT ====================
    {"name": "view_components", "description": "View components"},
    {"name": "create_components", "description": "Create components"},
    {"name": "edit_components", "description": "Edit components"},
    {"name": "delete_components", "description": "Delete components"},

    # ==================== INVENTORY MANAGEMENT ====================
    {"name": "view_inventory", "description": "View inventory"},
    {"name": "create_inventory", "description": "Create inventory items"},
    {"name": "edit_inventory", "description": "Edit inventory items"},
    {"name": "delete_inventory", "description": "Delete inventory items"},

    # ==================== MAINTENANCE MANAGEMENT ====================
    {"name": "view_maintenance", "description": "View maintenance logs"},
    {"name": "create_maintenance", "description": "Create maintenance logs"},
    {"name": "edit_maintenance", "description": "Edit maintenance logs"},
    {"name": "approve_maintenance", "description": "Approve maintenance"},
    {"name": "close_maintenance", "description": "Close maintenance"},
    
    # ==================== ENTITIES & STATUS ====================
    {"name": "view_entities", "description": "View entities"},
    {"name": "create_entities", "description": "Create entities"},
    {"name": "edit_entities", "description": "Edit entities"},
    {"name": "delete_entities", "description": "Delete entities"},
    
    {"name": "view_statuses", "description": "View statuses"},
    {"name": "create_statuses", "description": "Create statuses"},
    {"name": "edit_statuses", "description": "Edit statuses"},
    {"name": "delete_statuses", "description": "Delete statuses"},
    {"name": "view_hierarchy", "description": "View hierarchy entries"},
    {"name": "create_hierarchy", "description": "Create hierarchy entries"},
    {"name": "edit_hierarchy", "description": "Edit hierarchy entries"},
    {"name": "delete_hierarchy", "description": "Delete hierarchy entries"},
    
    {"name": "view_status_history", "description": "View entity status history"},
    {"name": "create_status_history", "description": "Create status history"},
    {"name": "edit_status_history", "description": "Edit status history"},
    {"name": "delete_status_history", "description": "Delete status history"},
    
    # ==================== REPORTS & ANALYTICS ====================
    {"name": "view_reports", "description": "View reports"},
    {"name": "view_executive_dashboard", "description": "View executive dashboard analytics"},
    {"name": "export_reports", "description": "Export reports"},
    
    # ==================== ROLE MANAGEMENT ====================
    {"name": "view_roles", "description": "View roles"},
    {"name": "create_roles", "description": "Create roles"},
    {"name": "edit_roles", "description": "Edit roles"},
    {"name": "delete_roles", "description": "Delete roles"},

    # ==================== MAINTENANCE CASES ====================
    {"name": "view_maintenance_cases", "description": "View maintenance cases"},
    {"name": "create_maintenance_cases", "description": "Create maintenance cases"},
    {"name": "edit_maintenance_cases", "description": "Edit maintenance cases"},
    {"name": "delete_maintenance_cases", "description": "Delete maintenance cases"},

    # ==================== FAULTY ENTITIES ====================
    {"name": "view_faulty_entities", "description": "View faulty entities"},
    {"name": "create_faulty_entities", "description": "Create faulty entities"},
    {"name": "edit_faulty_entities", "description": "Edit faulty entities"},
    {"name": "delete_faulty_entities", "description": "Delete faulty entities"},
    {"name": "cascade_faults", "description": "Cascade faults to child entities"},
    {"name": "suspect_children", "description": "Mark children as suspected faulty"},
    {"name": "confirm_faults", "description": "Confirm entity faults"},
    {"name": "view_entity_maintenance_history", "description": "View entity maintenance history"},
    {"name": "lookup_entities_by_part_number", "description": "Lookup entities by part number"},

    # ==================== MAINTENANCE ACTIONS ====================
    {"name": "view_maintenance_actions", "description": "View maintenance actions"},
    {"name": "create_maintenance_actions", "description": "Create maintenance actions"},
    {"name": "edit_maintenance_actions", "description": "Edit maintenance actions"},
    {"name": "delete_maintenance_actions", "description": "Delete maintenance actions"},

    # ==================== MAINTENANCE DELIVERIES ====================
    {"name": "view_maintenance_deliveries", "description": "View maintenance deliveries"},
    {"name": "create_maintenance_deliveries", "description": "Create maintenance deliveries"},
    {"name": "edit_maintenance_deliveries", "description": "Edit maintenance deliveries"},
    {"name": "delete_maintenance_deliveries", "description": "Delete maintenance deliveries"},
    {"name": "confirm_maintenance_deliveries", "description": "Confirm maintenance deliveries"},

    # ==================== MAINTENANCE DELIVERIES ====================
    {"name": "view_configuration_history", "description": "View configuration history"},
    {"name": "create_configuration_history", "description": "Create_configuration history"},
    {"name": "edit_configuration_history", "description": "Edit configuration history"},
    {"name": "delete_configuration_history", "description": "Delete configuration history"},
]

DEFAULT_ROLES = [
    {
        "name": "Admin",
        "description": "Full access to all features and endpoints",
        "permissions": [p["name"] for p in DEFAULT_PERMISSIONS]
    },
    {
        "name": "ProjectManager",
        "description": "Can manage projects, systems, subsystems and teams",
        "permissions": [
            # Users
            "view_users", 
            # Projects
            "view_projects", "create_projects", "edit_projects",
            # Systems
            "view_systems", "create_systems", "edit_systems",
            # Subsystems
            "view_subsystems", "create_subsystems", "edit_subsystems",
            # Modules
            "view_modules", "create_modules", "edit_modules",
            # Units
            "view_units", "view_units",
            # Components
            "view_components",
            # Maintenance
            "view_maintenance", "create_maintenance", "edit_maintenance",
            # Reports
            "view_reports",
            "view_executive_dashboard",
            # Entities
            "view_entities", "create_entities", "edit_entities",
            # Status
            "view_statuses", "view_status_history",
            # Hierarchy
            "view_hierarchy", "create_hierarchy", "edit_hierarchy",

            # Maintenance Cases
            "view_maintenance_cases",
            "create_maintenance_cases",
            "edit_maintenance_cases",

            # Faulty Entities
            "view_faulty_entities",
            "create_faulty_entities",
            "edit_faulty_entities",
            "cascade_faults",
            "suspect_children",
            "confirm_faults",
            "view_entity_maintenance_history",
            "lookup_entities_by_part_number",

            # Maintenance Actions
            "view_maintenance_actions",
            "create_maintenance_actions",
            "edit_maintenance_actions",

            # Maintenance Deliveries
            "view_maintenance_deliveries",
            "create_maintenance_deliveries",
            "edit_maintenance_deliveries",
            "confirm_maintenance_deliveries",

            # Configuration History
            "view_configuration_history",
            "create_configuration_history",
        ]
    },
    {
        "name": "Technician",
        "description": "Can view and manage subsystems, modules, units, components and maintenance",
        "permissions": [
            # Users
            "view_users",
            # Projects
            "view_projects",
            # Systems
            "view_systems",
            # Subsystems
            "view_subsystems", "edit_subsystems",
            # Modules
            "view_modules", "edit_modules",
            # Units
            "view_units", "edit_units",
            # Components
            "view_components", "edit_components",
            # Inventory
            "view_inventory",
            # Maintenance
            "view_maintenance", "create_maintenance", "edit_maintenance", "close_maintenance",
            # Entities
            "view_entities", "edit_entities",
            # Status
            "view_statuses", "view_status_history",
            # Reports
            "view_reports",
            "view_executive_dashboard",

            # Maintenance Cases
            "view_maintenance_cases",

            # Faulty Entities
            "view_faulty_entities",
            "create_faulty_entities",
            "edit_faulty_entities",
            "cascade_faults",
            "suspect_children",
            "confirm_faults",
            "view_entity_maintenance_history",
            "lookup_entities_by_part_number",

            # Maintenance Actions
            "view_maintenance_actions",
            "create_maintenance_actions",
            "edit_maintenance_actions",

            # Maintenance Deliveries
            "view_maintenance_deliveries",
            "create_maintenance_deliveries",
            "edit_maintenance_deliveries",
            "confirm_maintenance_deliveries",

            # Configuration History
            "view_configuration_history",
            "create_configuration_history",
        ]
    },
    {
        "name": "Maintenance",
        "description": "Can manage maintenance logs and close maintenance tickets",
        "permissions": [
            # Users
            "view_users",
            # Projects
            "view_projects",
            # Systems
            "view_systems",
            # Subsystems
            "view_subsystems",
            # Modules
            "view_modules",
            # Units
            "view_units",
            # Components
            "view_components",
            # Maintenance
            "view_maintenance", "create_maintenance", "edit_maintenance", "close_maintenance",
            # Entities
            "view_entities",
            # Status
            "view_statuses", "view_status_history",
            # Reports
            "view_reports",
            "view_executive_dashboard",

            # Maintenance Cases
            "view_maintenance_cases",
            "create_maintenance_cases",
            "edit_maintenance_cases",
            "delete_maintenance_cases",

            # Faulty Entities
            "view_faulty_entities",
            "create_faulty_entities",
            "edit_faulty_entities",
            "delete_faulty_entities",
            "cascade_faults",
            "suspect_children",
            "confirm_faults",
            "view_entity_maintenance_history",
            "lookup_entities_by_part_number",

            # Maintenance Actions
            "view_maintenance_actions",
            "create_maintenance_actions",
            "edit_maintenance_actions",
            "delete_maintenance_actions",

            # Maintenance Deliveries
            "view_maintenance_deliveries",
            "create_maintenance_deliveries",
            "edit_maintenance_deliveries",
            "delete_maintenance_deliveries",
            "confirm_maintenance_deliveries",

            # Configuration History
            "view_configuration_history",
            "create_configuration_history",
        ]
    },
    {
        "name": "Viewer",
        "description": "Read-only access to all resources",
        "permissions": [
            # Users
            "view_users",
            # Customers
            "view_customers",
            # Orders
            "view_orders",
            # Projects
            "view_projects",
            # Systems
            "view_systems",
            # Subsystems
            "view_subsystems",
            # Modules
            "view_modules",
            # Units
            "view_units",
            # Components
            "view_components",
            # Inventory
            "view_inventory",
            # Maintenance
            "view_maintenance",
            # Entities
            "view_entities",
            # Status
            "view_statuses",
            # Status History
            "view_status_history",
            # Hierarchy
            "view_hierarchy",
            # Reports
            "view_reports",
            "view_executive_dashboard",

            # Maintenance Cases
            "view_maintenance_cases",

            # Faulty Entities
            "view_faulty_entities",
            "view_entity_maintenance_history",

            # Maintenance Actions
            "view_maintenance_actions",

            # Maintenance Deliveries
            "view_maintenance_deliveries",
        ]
    }
]

def initialize_roles_and_permissions(session: Session):
    """Initialize default roles and permissions in the database."""
    from app.models.tables import Role, Permission
    
    existing_roles = session.exec(select(Role)).all()
    if existing_roles:
        return
    
    permission_map = {}
    for perm_data in DEFAULT_PERMISSIONS:
        perm = Permission(**perm_data)
        session.add(perm)
        session.flush()
        permission_map[perm.name] = perm
    
    for role_data in DEFAULT_ROLES:
        role = Role(name=role_data["name"], description=role_data["description"])
        role.permissions = [permission_map[perm_name] for perm_name in role_data["permissions"]]
        session.add(role)
    
    session.commit()


# ==================== SYNC ROLES & PERMISSIONS ====================
def sync_roles_and_permissions(session: Session):
    """
    Sync the database roles and permissions with DEFAULT_PERMISSIONS and DEFAULT_ROLES.
    - Adds new permissions and roles.
    - Updates role permissions to match DEFAULT_ROLES.
    - Does NOT delete existing roles/permissions not in defaults.
    """
    from app.models.tables import Role, Permission

    # 1. Sync permissions
    existing_permissions = {p.name: p for p in session.exec(select(Permission)).all()}
    for perm_data in DEFAULT_PERMISSIONS:
        if perm_data["name"] not in existing_permissions:
            perm = Permission(**perm_data)
            session.add(perm)
            session.flush()
            existing_permissions[perm.name] = perm

    # 2. Sync roles
    existing_roles = {r.name: r for r in session.exec(select(Role)).all()}
    for role_data in DEFAULT_ROLES:
        role = existing_roles.get(role_data["name"])
        if not role:
            role = Role(name=role_data["name"], description=role_data["description"])
            session.add(role)
            session.flush()
            existing_roles[role.name] = role
        # Update role description if changed
        if role.description != role_data["description"]:
            role.description = role_data["description"]
        # Set permissions to match DEFAULT_ROLES
        perms = [existing_permissions[perm_name] for perm_name in role_data["permissions"] if perm_name in existing_permissions]
        role.permissions = perms

    session.commit()
