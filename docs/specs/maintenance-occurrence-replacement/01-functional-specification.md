# 01 — Functional Specification (FSD)

**Baseline:** [00-requirements-baseline.md](./00-requirements-baseline.md)  
**Diagram:** `PLCM_Maintenance_Occurrence_Replacement_Workflow.drawio`

---

## 1. Purpose

Specify behaviour for:

1. **Occurrence Report** (augmented onsite outcome).
2. **Track A** — immediate same-spec replacement + AIT (ME-led).
3. **Track B** — faulty return, IE inspection, warranty/discard/repair.
4. Close gate, badges, notifications — without breaking existing maintenance.

---

## 2. Actors

| Actor | Code | Primary actions |
|-------|------|-----------------|
| Field Service Engineer | FSE | Occurrence officers; site replace/integrate with ME |
| Maintenance Engineer | ME | Replacement request; IM issue request; custody; AIT upload; site work |
| Project Director | PD | Approve/reject replacement; assign ME/IE; AIT gate; repair verify |
| Inventory Manager | IM | Issue replacement; receive faulty; issue to IE; discard; restock |
| Inspection Engineer | IE | Request handover; inspect; disposition; repair updates |
| System | SYS | Recorded timestamps; notifications; badge rules; close gate checks |

---

## 3. Occurrence Report

### 3.1 Preconditions

- Maintenance case exists and is not `closed`.
- User has permission equivalent to today’s `edit_maintenance_cases` (or FSE/ME as configured).

### 3.2 Data contract

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| `occurrence_date` | date/datetime | User | **Required**; distinct from recorded |
| `recorded_at` | datetime | SYS | Immutable on create |
| `recorded_by_id` | FK user | SYS | Immutable on create |
| `outcome` | enum | User | `soft_fix` \| `fault_identified` \| `inconclusive` \| `no_fault_found` |
| `fault_type` | FaultType | User | Required if `fault_identified`; optional otherwise |
| `soft_fix_method` | SoftFixMethod | User | Required if soft_fix |
| `notes` | text | User | Optional |
| `confirmation_channel` | enum | User | email \| letter \| call (S) |
| `confirmation_ref` | string | User | Optional |
| `attachments[]` | `{name, file_id, …}` | User | `name` required per file |
| `officers[]` | `{user_id?, display_name, onsite_role}` | User | Dialog |

### 3.3 Postconditions by outcome

| Outcome | Behaviour |
|---------|-----------|
| Soft fix | Existing soft_fixed resolve path |
| NFF | Modal confirm close/resolve; Yes → NFF resolve/close; No → note, stay open |
| Inconclusive | Persist report; case stays open |
| Fault identified | Persist; enable **Request immediate replacement**; investigation continues |

### 3.4 UI

- Rename panel/button per REQ-OR-001.
- Officers: modal multi-row editor.
- Attachments: upload + mandatory display name before accept.

---

## 4. Track A — Replacement & AIT

### 4.1 Entity: `ReplacementRequest` (logical)

| Field | Notes |
|-------|-------|
| `id`, `maintenance_case_id`, `faulty_entity_id` | Links |
| `requested_by_id` (ME), `assigned_me_id` | Actors |
| `status` | Sub-status (below) |
| `requested_pn_specs` | Same-spec constraint |
| `issued_serials[]` | History of issued S/Ns (for reject loops) |
| `current_serial_number` | Active replacement S/N |
| `ait_attachments[]`, `ait_notes` | Evidence |
| `pd_decision`, `pd_decision_at`, `pd_reason` | Gate |
| `red_notification_active` | Bool |

### 4.2 Sub-status machine

```
replacement_requested
  → pd_approved | pd_rejected (terminal for this request version)
pd_approved → im_issue_pending → shipped_replaced_badge
  → ait_in_progress → ait_approved | ait_rejected
ait_rejected → im_issue_pending (new S/N) … loop
ait_approved → patch_delivered → track_a_closed
[+ abort → track_a_aborted]
```

### 4.3 Key rules

1. **No wait for faulty** before issue (REQ-TA-001).
2. On first successful issue/ship: set Replaced badge; raise RED notify; enqueue Track B `awaiting_faulty_arrival`.
3. Reject loop uses **same ME**; prior failed unit → IM quarantine (S).
4. Shortage → no issue; escalate (S).

---

## 5. Track B — Faulty inspection

### 5.1 Sub-status machine

```
awaiting_faulty_arrival → received → ie_assigned
  → issued_to_ie → inspection_under_process
  → repair_under_progress | warranty_claim | discard_pending
  → restocked | discarded | claim_closed
```

### 5.2 Disposition rules

| IE finding | Next |
|------------|------|
| Repairable | `repair_under_progress` → PD verify → restock or repair loop |
| Irreparable + warranty active | OEM claim / ship supplier |
| Irreparable + no/expired warranty | IE comment → IM trash → Discarded |
| Reusable (S) | Restock without full repair |

### 5.3 Segregation

IE cannot execute trash; IM confirms discard (REQ-TB-009).

---

## 6. Close gate

Case may move to `resolved`/`closed` when:

**Early exit:** Soft fix or confirmed NFF close (no dual track required).

**Dual-track exit:**

- Track A = `patch_delivered` or `track_a_closed` (or waived abort), **AND**
- Track B = terminal (`restocked` | `discarded` | `claim_closed`) **OR** TB waived under SLA caveat (S).

Existing delivery-confirm close remains if product rules already allow it without dual track for legacy cases.

---

## 7. Notifications (minimum)

| Event | Audience | Priority |
|-------|----------|----------|
| `occurrence_recorded` | PD, ME | normal |
| `replacement_requested` | PD | high |
| `replacement_approved` | ME, IM | high |
| `replacement_shipped` | Project/Order/Flight/SDLS watchers, ME, FSE | **high (RED)** |
| `ait_in_progress` | PD | normal |
| `ait_approved` / `ait_rejected` | ME, IM | high on reject |
| `faulty_received` | PD | high |
| `ie_assigned` | IE, IM | normal |
| `discard_completed` | PD, IM | normal |
| `repaired_restocked` | PD, IM | normal |
| `case_closed` | watchers | normal |
| Clear RED | on patch_delivered / abort | — |

---

## 8. Badges

| Badge | When | Effect |
|-------|------|--------|
| Replaced | After replacement S/N issued/shipped | Show on entity/hierarchy/project views for that slot |
| Discarded | After IM trash | Inventory row badge; block reserve/issue forever |

---

## 9. Non-functional (minimum)

| ID | Spec |
|----|------|
| NF-001 | All Track A/B transitions audited (who/when/from/to). |
| NF-002 | Attachment storage uses existing PLCM file service patterns. |
| NF-003 | Role checks enforced server-side (not UI-only). |
| NF-004 | Discarded inventory queries exclude items from allocatable stock. |

---

## 10. Out of scope (this FSD)

- Changing hierarchy config / reservation FCFS rules.
- Replacing generic RMA SOP diagram (`Maintenance_Faulty_Item_Return_Repair_Lifecycle.drawio`).
- Rewriting CaseStatus enum values.
