# Inventory QR/barcode labels

## Security model

The backend creates an opaque, random label ID and signs it with `AUTH_SECRET_KEY`.
The QR and Code 128 payload has the form `PLCM1.<label-id>.<signature>` and contains
no inventory, user, or location data. Every generation, print, replacement,
deactivation, and scan operation validates the assignment and signature server-side.

Changing a payload, inventing a label ID, using an unassigned label, or scanning a
deactivated/replaced label is rejected. Label IDs and active assignments are protected
by database uniqueness constraints and indexes.

Software cannot detect a physically copied sticker by itself. The practical controls
are signed IDs, server-side validation, scan history, user/time/location comparison,
and optional activation or investigation by an administrator.

## IM workflow

1. Open Inventory and select the label action for an item or a serialized unit.
2. Choose QR, barcode, or both and generate the label. Bulk generation is available
   from a serialized inventory group and creates one label per serial number.
3. Use Print for the first print. Reprint requires a reason such as damaged,
   wasted, or unreadable and never creates another inventory item.
4. Use History to review first-print/reprint events, quantities, users, timestamps,
   and scan events.

Administrators or authorized inventory managers can mark a label for investigation,
deactivate it, or replace it. Replacement keeps the old event history and assigns a
new signed label to the same inventory serial.

## API

- `POST /api/labels/generate` — generate or return active labels for target inventory
  instances; body includes `targets` and `label_type`.
- `GET /api/labels/` — list visible active labels, optionally filtered by inventory
  or instance. `include_inactive=true` is restricted by inventory visibility.
- `POST /api/labels/print` — atomically record first prints and reprints; body includes
  `label_ids`, `label_format`, `quantity`, and a required `reason` for reprints.
- `GET /api/labels/{label_id}/history` — print and scan history.
- `POST /api/labels/scan` — validate and resolve a payload, optionally with observed
  location and source.
- `POST /api/labels/{label_id}/investigate` — flag a suspicious label.
- `POST /api/labels/{label_id}/deactivate` — disable a compromised label.
- `POST /api/labels/{label_id}/replace` — atomically deactivate the old label and
  create a replacement for the same inventory assignment.

Label events are written in the same transaction as the state change and workflow
audit events are append-only.
