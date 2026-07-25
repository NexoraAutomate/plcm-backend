---
name: Installer Inventory Scoping
overview: Scope inventory so Admin/SubAdmin see the full warehouse, installers see only items issued to them; installer-only hierarchical revert returns assemblies to their issued list; return-to-admin clears their list and notifies Admin/SubAdmin.
todos:
  - id: role-helpers-perms
    content: Add is_inventory_manager; Technician loses issue_inventory; gate issue/return/revert endpoints
    status: completed
  - id: scope-lists
    content: "Scope inventory + issuances lists: managers see all, installers see issued-to-them only"
    status: completed
  - id: return-notices
    content: Return ownership checks + InventoryReturnNotice table/API for admin notifications
    status: completed
  - id: hierarchical-revert
    content: Cascade soft-remove children; restore assembly; reopen issued to installer
    status: completed
  - id: fe-gating-notify
    content: Frontend manager/installer gating, Return UX, revert hide for managers, bell notifications
    status: completed
isProject: false
---

# Installer-scoped inventory, hierarchical revert, return notify

## Confirmed rules
- **Warehouse visibility:** Admin **and** SubAdmin see all inventory (available / issued / zero stock).
- **Installer visibility:** Non-admin/SubAdmin users see **only** items with an open issuance (`status=issued`) where `issued_to_user_id = current_user`.
- **Issue / accept returns:** Admin/SubAdmin only.
- **Revert:** Installers/non-admins only (hide + reject for Admin/SubAdmin).
- **Revert outcome:** Soft-remove installed parent **and children** from hierarchy UI; restore assembly to installer’s issued list; clear/update install metadata.
- **Return to admin:** Closes issuance → disappears from installer list → back in admin warehouse → **notification** to Admin/SubAdmin.

```mermaid
sequenceDiagram
  participant Admin
  participant Installer
  participant Inventory
  participant Hierarchy
  Admin->>Inventory: Issue A to Installer
  Note over Inventory: A reserved; Installer list shows A
  Installer->>Hierarchy: Install A plus children
  Note over Inventory: A consumed; issuance installed
  Installer->>Inventory: Revert A
  Note over Hierarchy: A and descendants soft-removed
  Note over Inventory: A restored; issuance reopened issued to Installer
  Installer->>Inventory: Return A to admin
  Note over Inventory: issuance returned; Admin notified
```

## Backend

### 1. Role helpers
In [`app/auth.py`](c:\Project files\Jul-2026\plcm-backend\app\auth.py) / inventory router:
- `is_inventory_manager(user)` → Admin or SubAdmin
- Use on issue + list scoping + return (managers can return any; installers only own)

Update default roles:
- **Technician:** keep `revert_inventory_install` + `view_inventory`; **remove** `issue_inventory`
- Issue/return remain Admin/SubAdmin (all perms / SubAdmin set)

### 2. Scope inventory reads
In [`_10_inventory.py`](c:\Project files\Jul-2026\plcm-backend\app\routers\_10_inventory.py) list/get-by-type:
- If manager → current behavior (all rows)
- Else → only inventory IDs that have open `InventoryIssuance` for `issued_to_user_id=current_user.id`
- Same filter on instances / available flags for those rows (installer sees their issued units)

Issuances list: non-managers auto-filter to `issued_to_user_id=current_user` (cannot query others).

### 3. Return ownership + notify hook
[`return_issuance`](c:\Project files\Jul-2026\plcm-backend\app\services\inventory_issuance_service.py):
- Installer may return only if `issued_to_user_id == current_user` and status `issued`
- Manager may return any open issuance
- On success: leave `status=returned` (already removes from installer scoped list)

Add lightweight persistent notices for admins (minimal schema):
- Table `inventoryreturnnotice` (or reuse a generic `appnotification` if preferred): `issuance_id`, `inventory_name`, `part_number`, `serial_number`, `returned_by_user_id`, `returned_by_name`, `created_at`, `read_at` nullable
- Create row on return
- `GET /inventory/return-notices/` for managers; `POST .../read/` to dismiss
- Frontend bell consumes these (see below)

### 4. Hierarchical revert → installer issued list
Rewrite `revert_entity_to_inventory` in [`inventory_issuance_service.py`](c:\Project files\Jul-2026\plcm-backend\app\services\inventory_issuance_service.py):

1. **Authorize:** reject if `is_inventory_manager`; require `revert_inventory_install`; prefer ownership via prior issuance `issued_to` / `installed_by` = current user (managers never call this).
2. Soft-remove root: `is_current_install=False`, clear `installation_date` / `installed_by_id` (and originals kept for audit).
3. Collect descendants via [`_collect_descendants`](c:\Project files\Jul-2026\plcm-backend\app\models\helpers.py); soft-remove each the same way (so they vanish from hierarchy UI filters that use current install).
4. Restore **parent** to inventory group (same part/serial) via `restore_inventory_unit`.
5. For each descendant with part/serial: restore as child stock and **recompose** under parent via `InventoryChildLink` (`stock_consumed=True`) so the installer receives the full assembly, not orphan children.
6. **Reopen issuance** as `issued` to the original `issued_to_user_id` (fallback: reverting user), link restored parent instance — so it appears again on the installer’s inventory list. Do **not** leave terminal-only `reverted` without a new/open issued row (keep a `reverted` history row or flip the prior installed row back to `issued` after restore — prefer: close installed as `reverted` + create new open `issued` for clarity in movements report).

### 5. Endpoint guards
- `POST .../issue/` → manager only  
- `POST .../issuances/{id}/return/` → owner or manager  
- `POST .../revert-to-stock/` → non-manager + `revert_inventory_install`  
- Create/update/delete inventory → keep existing perms but managers are the ones with create/edit in practice; optionally reject non-managers on create for clarity

## Frontend

### 1. Role helpers
Add `isInventoryManager()` (Admin **or** SubAdmin) in [`auth-context.tsx`](c:\Project files\Jul-2026\plcm-frontend\lib\auth-context.tsx) (today `isAdmin()` is Admin-only).

### 2. Inventory UI gating
[`inventory/page.tsx`](c:\Project files\Jul-2026\plcm-frontend\app\(dashboard)\inventory\page.tsx):
- Issue / Add Item / Add More / Delete: managers only  
- Installers: list is backend-scoped (their issued items); show **Return to admin** on their open issued rows  
- Hide warehouse actions that don’t apply

[`issuances/page.tsx`](c:\Project files\Jul-2026\plcm-frontend\app\(dashboard)\inventory\issuances\page.tsx):
- Managers: full ledger + accept returns  
- Installers: own issuances + Return  

### 3. Revert button
[`revert-to-inventory-button.tsx`](c:\Project files\Jul-2026\plcm-frontend\components\revert-to-inventory-button.tsx) / [`entity-install-metadata-card.tsx`](c:\Project files\Jul-2026\plcm-frontend\components\entity-install-metadata-card.tsx):
- Render only when `!isInventoryManager()` and `can(revert_inventory_install)`  
- After success: toast + navigate away / refresh parent (children gone)

### 4. Admin notification popup
Extend [`app-notifications.ts`](c:\Project files\Jul-2026\plcm-frontend\lib\app-notifications.ts) + [`use-app-notifications.ts`](c:\Project files\Jul-2026\plcm-frontend\hooks\use-app-notifications.ts):
- New type `inventory_returned`  
- Managers fetch unread return notices; message like “Installer X returned inventory A” → href `/inventory` or issuances  
- Mark read via API when opened/cleared  

## Implementation order
1. Role helpers + permission defaults (Technician loses issue)  
2. Scope list/issuance APIs  
3. Return ownership + return-notice table/API  
4. Hierarchical revert + re-issue to installer  
5. Frontend gating, Return UX, notification bell  
6. Smoke: Admin issues → installer sees only A → install → revert (tree gone, A on installer list) → return → admin notified, A in warehouse  

## Out of scope
- Changing maintenance replace flows beyond auto-match of open issuances already in place  
- Full general-purpose notification service beyond inventory return notices  
