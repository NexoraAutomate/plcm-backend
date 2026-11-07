# 01 — Functional Specification (FSD)

**Feature:** PLCM Maintenance Augmentation — Occurrence Report + Parallel Replacement / Inspection  
**Source:** `docs/diagrams/MHD.drawio` pages 01–06  
**Audience:** Backend, Frontend, QA, Product Owner  
**Baseline:** Existing CaseStatus spine and field-service onsite outcome remain; this FSD specifies the augmentation.

---

## 1. Goals

1. Capture field facts via an **Occurrence Report** (rename of onsite visit outcome) with occurrence date ≠ system recorded time, named attachments, officers, fault type, and confirmation channel.
2. After **fault identified**, start **Track A Immediate Replacement** without waiting for the faulty item.
3. Run **Track B Faulty Return & Inspection** in parallel (may start later on reception).
4. Gate case close on **Track A AIT pass + Track B terminal** (or Soft/NFF early exit).
5. Preserve soft-fix, investigation tree, IM rework, warranty, and delivery-close paths (no regressions).

---

## 2. Out of scope

- Replacing or redesigning Soft fix / tree investigation / delivery-confirm close.
- External OEM portal automation beyond existing warranty claim statuses.
- Mandatory QR custody (optional gap fill).
- Virus-scan productization details beyond documenting size/category limits.

---

## 3. Actors & permissions (additive)

| Actor | Can |
|-------|-----|
| Anyone with rights to open maintenance case | Create Replacement Request; mark to HM; notify PD |
| HM | Assign ME; select/reserve replacement PN/S/N; mark case to ME |
| PD | Approve/Reject replacement request; assign IE; Approve/Reject AIT; verify repair tests |
| ME | Request IM issue; take custody; notify AIT in progress; site replace/integrate; upload AIT |
| FSE | Listed on Occurrence Report; assist site replace/integrate |
| IM | Stock check; ISSUE S/N; reception; issue faulty to IE; discard/trash; restock |
| IE | Request handover; inspect; disposition (repairable / warranty / discard recommend); repair + evidence |
| System | Sub-status transitions, badges, RED notifications, close-gate enforcement |

Permission codes (already stubbed for later enforcement):  
`maintenance.occurrence_report`, `maintenance.replacement_request`, `maintenance.ait_upload`, `maintenance.inspection_disposition`.

---

## 4. Data model (target)

### 4.1 Occurrence Report (extend MaintenanceCase / onsite)

| Field | Type | Notes |
|-------|------|-------|
| `occurrence_date` | date/datetime (user) | When field event happened |
| `onsite_recorded_at` | datetime (system) | Immutable (existing) |
| `onsite_recorded_by_id` | FK user | Existing |
| `onsite_outcome` | enum | Add `no_fault_found` **or** map NFF via resolution + modal |
| `fault_type` | FaultType | Required if fault; optional otherwise |
| `onsite_soft_fix_method` | SoftFixMethod | If soft_fix (existing) |
| `onsite_notes` | text | Existing |
| `attachments[]` | `{name, file_id, optional category}` | User-defined display name required |
| `officers[]` | `{user_id? \| guest_name, role_onsite, contact?}` | FSE+ dialog |
| `confirmation_channel` | email \| letter \| call | If fault |
| `confirmation_reference` | string / attachment link | If fault |

### 4.2 ReplacementRequest (NEW entity, linked to case + entity S/N)

Sub-status spine (do **not** break CaseStatus):

```
replacement_requested → pd_approved | pd_rejected
→ im_issue_pending → shipped_replaced_badge
→ ait_in_progress → ait_approved | ait_rejected
→ (reject loop) → patch_delivered → track_a_closed
```

Key fields: `case_id`, `faulty_entity_id`, `requested_by`, `assigned_me_id`, `reserved_inventory_ids[]`, `issued_serial`, `ait_attachments[]`, `pd_decision`, `reject_reason`, `abort_reason`.

### 4.3 Inspection / returned-unit sub-status (extend rework)

```
awaiting_faulty_arrival → received → ie_assigned → issued_to_ie
→ inspection_under_process
→ repair_under_progress | warranty_claim | discard_pending
→ restocked | discarded | claim_closed
```

Add `reception_date`; keep CaseStatus `under_inspection` / `under_repair` as case-level spine.

---

## 5. Step-by-step functional flows

### 5.1 Case open (existing — P0 preserve)

1. Lookup S/N; project gate; production-support check.
2. CaseStatus = `open`.
3. **Acceptance:** Existing open path unchanged.

### 5.2 Record Occurrence Report (P1)

1. User opens case → **Occurrence Report** panel (was “Onsite visit outcome”).
2. Enter occurrence date, outcome, notes; optionally officers, attachments.
3. If outcome = Soft fix → soft-fix method required; on save → `resolve_soft_fixed` (existing).
4. If outcome = NFF → modal: Close/resolve as NFF? Yes → resolve+close path; No → note only, stay open.
5. If Inconclusive → stay open.
6. If Fault identified → require fault type + confirmation channel/evidence; enable **Request immediate replacement** CTA; investigation tree continues in parallel.
7. System sets `onsite_recorded_at` / `onsite_recorded_by_id`; notify PD (and ME if assigned) `occurrence_recorded`.

### 5.3 Dual-track split (P2)

On fault confirmation (Occurrence Report + email/letter/call evidence):

| Track A | Track B |
|---------|---------|
| Starts immediately | May start later when customer ships / IM receives |
| Replacement from SUPARCO stock (same specs) | Faulty return, inspect, warranty/discard/repair |
| Does not wait for faulty | Auto-queue `awaiting_faulty_arrival` when replacement shipped |

**Case close gate:** Track A `patch_delivered` (AIT approved) **AND** Track B terminal (`restocked` \| `discarded` \| `claim_closed`), **OR** Soft/NFF early exit. Existing delivery-confirm close remains when applicable and dual-track not required.

### 5.4 Track A — Replacement & AIT (P3)

| Step | Actor | Action |
|------|-------|--------|
| A1 | Case opener | Create Replacement Request linked to case + entity S/N; mark to HM; notify PD |
| A2 | HM | Assign ME; select available replacement PN/S/N (one or more); reserve; mark case to ME |
| A3 | PD | Review: Approve / Reject request; on approve continue; on reject stop with reason |
| A4 | ME | Request IM to ISSUE reserved inventory (same procedure as build-time issue to developer) |
| A5 | IM | Stock check same P/N; if shortage → escalate PD/HM, hold Track A (no fake issue) |
| A6 | IM | ISSUE S/N; ship to ME/site; update hierarchy; **Replaced** badge; **RED** flag on Project/Order/Flight/SDLS; auto-queue faulty for return |
| A7 | ME | Take custody |
| A8 | ME | Notify PD: Shipment / AIT in Progress (`ait_in_progress`) |
| A9 | ME + FSE | Site: remove faulty if present, install replacement, integrate |
| A10 | ME | Upload AIT test results / attachments |
| A11 | PD | Approve or Reject based on results |
| A12a | IM | On Reject: issue **next** replacement S/N to **same** ME; failed unit → IM quarantine before next issue |
| A12b | ME | On Reject: receive new unit; repeat A7–A10 |
| A13 | System | On Approve → `patch_delivered` / Track A complete; clear RED when patch delivered or abort |

### 5.5 Track B — Faulty inspection (P4)

| Step | Actor | Action |
|------|-------|--------|
| B1 | System | Faulty auto-queued when replacement shipped |
| B2 | Customer | Ships faulty item |
| B3 | IM | Record Reception Date; notify PD |
| B4 | PD | Assign IE |
| B5 | IE | Request handover from IM |
| B6 | IM | Issue faulty to IE; status → `inspection_under_process` |
| B7 | IE | Disposition: Repairable? |
| B7a | | **No** → Under warranty? Yes → OEM claim (existing); No → recommend discard → IM trash → **Discarded** badge |
| B7b | | **Yes** → `repair_under_progress`; IE repairs + test evidence |
| B8 | PD | Verify repair tests Approve / Reject |
| B9 | | Approve → mark repaired + reports → IM restock; Reject → remain repair under progress |
| B10 | | Track B terminal when restocked / discarded / claim_closed |

**Segregation of duties:** IE recommends discard; IM confirms trash.

### 5.6 Close case (P5)

1. Soft/NFF early exit without dual track (as §5.2).
2. Else enforce close gate §5.3.
3. Notify watchers `case_closed`.
4. Clear RED notification if still set.

---

## 6. UI / UX requirements

1. Rename labels to **Occurrence Report** / **Record Occurrence Report** (prefer correct English; if product mandates “Occurance”, document as Accepted Deviation).
2. Case detail **dual-track board**: Track A + Track B progress and sub-statuses.
3. Badges: **Replaced** (new S/N), **Discarded** (never reusable / not selectable for reserve/issue), **RED** chip while replacement case open.
4. NFF confirm-close modal.
5. Field officers dialog; named attachment uploads.
6. AIT Approve/Reject screens for PD; repair verify screens for PD.

---

## 7. Notifications (priority)

| Event | Audience | Priority |
|-------|----------|----------|
| occurrence_recorded | PD, ME | normal |
| replacement_requested | PD | high |
| replacement_approved / ME assigned | ME, IM | high |
| replacement_shipped / S/N swapped | Project/Order/Flight/SDLS watchers, ME, FSE | high (RED) |
| ait_in_progress | PD | normal |
| ait_approved / ait_rejected | ME, IM | high on reject |
| faulty_received | PD | high |
| ie_assigned / issued_to_ie | IE, IM | normal |
| inspection_disposition | PD | normal |
| discard_completed | PD, IM | normal |
| repaired_restocked | PD, IM | normal |
| case_closed | watchers | normal |

---

## 8. Phased implementation steps

### Phase P0 — Foundations

1. Confirm CaseStatus enum untouched.
2. Ensure ME / FSE / IE in `WorkflowRole` + `DEFAULT_ROLES` + seed demo users.
3. Wire permission checks on new endpoints as they land.
4. Add feature flag or capability marker if needed for dual-track UI.
5. **Exit:** Role/permission unit tests updated for 8 workflow roles + maintenance.* permissions.

### Phase P1 — Occurrence Report

1. Backend: extend schema + `record_onsite_outcome` (occurrence_date, attachments, officers, fault_type, confirmation_*, NFF).
2. Migration for new columns / attachment & officer tables.
3. Frontend: rename panel; form fields; NFF modal; fault confirmation UI.
4. Notifications: `occurrence_recorded`.
5. **Exit:** UT-OR-* and FT-OR-* Pass; REQ-MHD-OR-* Verified.

### Phase P2 — Dual-track wiring

1. Create `ReplacementRequest` model + APIs (create, assign ME, reserve).
2. On fault_identified CTA → create request.
3. On ship (or request approved path): set Track B `awaiting_faulty_arrival` without requiring physical return.
4. Dual-track board skeleton on case detail.
5. **Exit:** FT-DT-* Pass.

### Phase P3 — Replacement / AIT

1. IM issue path from reserved replacement; Replaced badge; RED hierarchy notify.
2. ME custody + AIT upload; PD AIT gate; reject loop + quarantine.
3. Stock shortage escalation; abort Track A if later NFF (optional but recommended).
4. **Exit:** UT-RA-*, FT-RA-*, ST-A happy path ready.

### Phase P4 — Inspection / IE

1. Reception date + PD→IE assign + IE handover/issue.
2. Disposition branches: repair / warranty / discard (IM confirms).
3. PD repair verify; restock.
4. **Exit:** UT-IE-*, FT-IE-* Pass.

### Phase P5 — Close gate & polish

1. Enforce dual-track close gate in resolve/close APIs.
2. Complete notification matrix; Discarded badge; clear RED.
3. Gap fills product decides: shortage, abort, customer ack, never-returned SLA, attachment categories.
4. **Exit:** ST-* suite Pass; Matrix updated.

### Phase P6 — Verification & sign-off

1. Execute UT → FT → ST; fill Test Report.
2. Update Conformance Matrix; open NCRs for any Fail.
3. User review of NCRs / Accepted Deviations.
4. Conformance Report Approved.

---

## 9. Gap fills (recommended — productize or Accept Deviation)

| ID | Gap | Default recommendation |
|----|-----|------------------------|
| GAP-01 | Stock shortage | Escalate; hold Track A |
| GAP-02 | PD reject pre-issue vs AIT reject | Separate reason codes |
| GAP-03 | Failed unit disposition | Quarantine before next issue |
| GAP-04 | Abort Track A if later NFF | Cancel request; clear RED; keep audit |
| GAP-05 | ME reassignment | HM/PD can reassign |
| GAP-06 | Link Occurrence attachments to Replacement Request | Evidence reuse |
| GAP-07 | Customer reception ack for patch | Recommended |
| GAP-08 | Faulty never returned SLA | Timeout + PD escalate; Track A may close with caveat |
| GAP-09 | IE cannot discard directly | IM confirms |
| GAP-10 | Attachment category + size limits | Ops |
| GAP-11 | QR custody | Optional |
| GAP-12 | OEM return restock path | Map to existing claim outcomes |

---

## 10. Non-regression checklist

- Soft fix → `resolve_soft_fixed` still works.
- Investigation tree unchanged when fault identified.
- `create_returned_unit_rework` still created on replace; extended, not removed.
- OEM warranty claim statuses unchanged.
- Delivery-confirm close still allowed when dual-track not active.
- Legacy Maintenance role remains notify target until ME fully adopted.

---

## 11. Traceability

Every functional behavior above maps to REQ-IDs in [02-requirements-catalog.md](./02-requirements-catalog.md) and rows in [06-conformance-matrix.md](./06-conformance-matrix.md).
