from fastapi import APIRouter
from importlib import import_module

# Create a main router that will include all sub-routers
router = APIRouter()

# Import numbered modules using importlib (they have numeric prefixes)
users = import_module('._1_users', package='app.routers')
customers = import_module('._2_customers', package='app.routers')
orders = import_module('._3_orders', package='app.routers')
projects = import_module('._4_projects', package='app.routers')
systems = import_module('._5_systems', package='app.routers')
subsystem = import_module('._6_subsystem', package='app.routers')
module = import_module('._7_module', package='app.routers')
unit = import_module('._8_unit', package='app.routers')
component = import_module('._9_component', package='app.routers')
inventory = import_module('._10_inventory', package='app.routers')
# maintenancelog = import_module('.maintenance_module', package='app.routers')

# Import regular named modules using relative imports
from . import entity, entitystatushistory, maintenanceLog, status, auth, maintenance_module, hierarchy, configuraitonHistory, dashboard, attachments, pictures, reports, backup

# Include all routers
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(customers.router)
router.include_router(orders.router)
router.include_router(projects.router)
router.include_router(systems.router)
router.include_router(subsystem.router)
router.include_router(module.router)
router.include_router(unit.router)
router.include_router(component.router)
router.include_router(inventory.router)
router.include_router(entity.router)
router.include_router(entitystatushistory.router)
router.include_router(status.router)
router.include_router(maintenanceLog.router)
router.include_router(maintenance_module.router)
router.include_router(hierarchy.router)
router.include_router(configuraitonHistory.router)
router.include_router(dashboard.router)
router.include_router(attachments.router)
router.include_router(pictures.router)
router.include_router(reports.router)
router.include_router(backup.router)

