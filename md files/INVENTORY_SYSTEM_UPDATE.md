# Inventory System Update - Multi-Entity Support

## Overview

The inventory system has been updated to support inventory tracking for **all entity types** (system, subsystem, module, unit, component) instead of being limited to components only.

## Database Schema Changes

### Inventory Table Structure

The inventory table now includes the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | Integer (PK) | Unique inventory identifier (auto-generated) |
| `name` | String (Required) | Item name/label |
| `inventory_type` | String (Required) | Type of item: `system`, `subsystem`, `module`, `unit`, or `component` |
| `serial_number` | String (Optional) | Unique serial number of the physical item |
| `quantity` | Integer | Number of items in inventory (default: 0) |
| `description` | String (Optional) | Detailed description of the item |
| `oem_name` | String (Optional) | Original Equipment Manufacturer name |
| `manufacturer_part_number` | String (Optional) | Official part number from manufacturer |
| `location` | String (Optional) | Storage location or warehouse location |
| `entity_id` | Integer (Optional) | ID of the associated entity (system_id, subsystem_id, module_id, unit_id, or component_id) |
| `updated_at` | Timestamp | Last update timestamp |

## API Endpoints

### 1. Create Inventory Item
```http
POST /inventory/
Content-Type: application/json

{
  "name": "Power Supply Unit",
  "inventory_type": "component",
  "serial_number": "PSU-2024-001234",
  "quantity": 5,
  "description": "Industrial power supply 500W",
  "oem_name": "Siemens",
  "manufacturer_part_number": "6SL3210-1KE12-0UF1",
  "location": "Warehouse A - Rack 3",
  "entity_id": 42
}
```

### 2. List All Inventory
```http
GET /inventory/?skip=0&limit=100
```

### 3. List Inventory by Type
```http
GET /inventory/?inventory_type=system&skip=0&limit=100
```

Or use the dedicated endpoint:
```http
GET /inventory/by-type/module/?skip=0&limit=100
```

### 4. Get Inventory for Specific Entity
```http
GET /inventory/by-entity/42/
```

Returns all inventory items associated with entity ID 42 (regardless of entity type).

### 5. Get Single Inventory Item
```http
GET /inventory/123/
```

### 6. Update Inventory Item
```http
PUT /inventory/123/
Content-Type: application/json

{
  "quantity": 3,
  "location": "Warehouse B - Rack 1",
  "description": "Updated description"
}
```

### 7. Delete Inventory Item
```http
DELETE /inventory/123/
```

## Usage Examples

### Example 1: Create System-Level Inventory
```json
{
  "name": "Solar Array System",
  "inventory_type": "system",
  "serial_number": "SYS-2024-SA-001",
  "quantity": 1,
  "description": "Primary satellite solar array system",
  "oem_name": "SpaceX",
  "manufacturer_part_number": "SA-2024-V2",
  "location": "Storage Building C",
  "entity_id": 1
}
```

### Example 2: Create Component Inventory
```json
{
  "name": "Thermal Sensor",
  "inventory_type": "component",
  "serial_number": "SENSOR-2024-TH-5432",
  "quantity": 12,
  "description": "High-precision thermal sensor for temperature monitoring",
  "oem_name": "Honeywell",
  "manufacturer_part_number": "HT-101-24V",
  "location": "Component Storage - Shelf F",
  "entity_id": 156
}
```

## Data Migration

The migration script (`e8f4a9c1d2e3_update_inventory_multiple_types.py`) automatically:
- Removes the `component_id` foreign key constraint
- Adds all new fields
- Creates an index on `entity_id` for query optimization
- Sets appropriate default values during migration

## Backward Compatibility

To downgrade to the previous component-only inventory system, run:
```bash
alembic downgrade -1
```

This will:
- Remove the new columns
- Restore the `component_id` foreign key constraint
- Recreate the component relationship

## Permissions Required

The following permission checks are in place:
- `create_inventory` - Required to create new inventory items
- `view_inventory` - Required to view inventory items
- `edit_inventory` - Required to update inventory items
- `delete_inventory` - Required to delete inventory items

## Benefits

1. **Unified Inventory Management** - Track inventory for all entity types from a single interface
2. **Flexible Tracking** - Support for serial numbers, OEM details, and manufacturer part numbers
3. **Better Organization** - Location tracking and type-based filtering
4. **Entity Relationship** - Links inventory to specific entities for better traceability
5. **Quantity Management** - Track stock levels for spare parts and components

## Database Constraints

- `entity_id` is indexed for fast queries
- All new fields are nullable except `name` and `inventory_type`
- `updated_at` is automatically managed on updates

## Notes

- The `entity_id` field should reference the primary key of the corresponding entity table based on the `inventory_type`
- For component inventory, `entity_id` should match a component record's ID
- For system inventory, `entity_id` should match a system record's ID
- And so on for each entity type

## Testing

Test the inventory endpoints using the Swagger UI at:
```
http://localhost:8000/docs
```

Search for "inventory" to see all available endpoints.
