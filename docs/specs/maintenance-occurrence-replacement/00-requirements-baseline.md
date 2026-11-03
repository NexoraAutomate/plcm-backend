# 00 — Requirements Baseline

**ID prefix:** `REQ-`  
**Priority:** M = Must, S = Should, C = Could  
**Trace:** Diagram page referenced in *Source*

---

## 1. Cross-cutting / non-regression

| ID | Priority | Requirement | Source |
|----|----------|-------------|--------|
| REQ-NR-001 | M | Existing `CaseStatus` spine (`open` → `under_inspection` → `under_repair` → `resolved` → `closed`) remains valid and is not replaced by Track A/B sub-statuses. | 01 Overview |
| REQ-NR-002 | M | Soft-fix path (`soft_fix` + `resolve_soft_fixed`) continues to resolve/close without opening Track A/B. | 02 |
| REQ-NR-003 | M | Faulty-entity tree investigation (suspect/confirm/cascade) remains available after fault identification. | 01, 03 |
| REQ-NR-004 | M | Existing OEM warranty claim statuses and IM inspect outcomes (`repairable` / `reusable` / `scrapped`) remain usable; new flow augments them. | 05 |
| REQ-NR-005 | M | Delivery-confirm → case close path remains available where applicable. | 03 Close gate |
| REQ-NR-006 | M | Production-support gate / override on case open remains unchanged. | Existing PLCM |

---

## 2. Roles

| ID | Priority | Requirement | Source |
|----|----------|-------------|--------|
| REQ-ROLE-001 | M | Seed/wire role **Maintenance Engineer (ME)** with permissions for replacement request, IM issue request, AIT upload, site actions. | 01, 06 |
| REQ-ROLE-002 | M | Seed/wire role **Field Service Engineer (FSE)** for Occurrence officers and site assist. | 01, 02 |
| REQ-ROLE-003 | M | Seed/wire role **Inspection Engineer (IE)** for handover request, disposition, repair updates. | 01, 05 |
| REQ-ROLE-004 | M | Existing **PD** approves replacement, assigns ME/IE, gates AIT and repair verification. | 04, 05 |
| REQ-ROLE-005 | M | Existing **IM** issues replacement, receives faulty, issues to IE, discards/trash, restocks. | 04, 05 |
| REQ-ROLE-006 | S | Legacy role `Maintenance` remains a notification target until ME migration complete. | 01 |

---

## 3. Occurrence Report

| ID | Priority | Requirement | Source |
|----|----------|-------------|--------|
| REQ-OR-001 | M | UI label “Onsite visit outcome” renamed to **Occurrence Report**; button to **Record Occurrence Report**. | 02 |
| REQ-OR-002 | M | **Occurrence Date** (user-entered) is stored separately from system **Recorded Date/Time**. | 02 |
| REQ-OR-003 | M | System sets `recorded_at` / `recorded_by` immutably on save. | 02 |
| REQ-OR-004 | M | Outcome dropdown includes: Soft fix, PN/hardware fault (`fault_identified`), Inconclusive, **No Fault Found**. | 02 |
| REQ-OR-005 | M | Fault Type selectable from: Electrical, Mechanical, Environmental, Hardware, Manufacturing Defect, Physical Damage, Software, Unclassified, Wear, Other (existing `FaultType`). | 02 + image |
| REQ-OR-006 | M | Soft-fix method required when outcome = Soft fix (existing methods). | 02 |
| REQ-OR-007 | M | Notes / narrative free text supported. | 02 |
| REQ-OR-008 | M | Attachments: multiple files; each requires a **user-defined display name**. | 02 |
| REQ-OR-009 | M | Field officers dialog: add list of officers with designated onsite role (FSE lead, FSE, etc.). | 02 |
| REQ-OR-010 | M | Selecting **No Fault Found** prompts user to confirm close/resolve case as NFF; Yes → resolve/close path; No → note only, case stays open. | 02 |
| REQ-OR-011 | M | Soft fix after record still auto-resolves soft_fixed (non-regression). | 02 |
| REQ-OR-012 | M | Inconclusive leaves case open. | 02 |
| REQ-OR-013 | M | Fault identified enables Track A CTA (Request immediate replacement) and allows continued investigation. | 02, 03 |
| REQ-OR-014 | S | Optional confirmation channel (email/letter/call) + reference when fault identified. | 02 |
| REQ-OR-015 | C | Attachment category tags + size/virus policy (ops). | 02 gap |

---

## 4. Track A — Immediate replacement & AIT

| ID | Priority | Requirement | Source |
|----|----------|-------------|--------|
| REQ-TA-001 | M | After fault confirmation, replacement may start **without waiting** for faulty item arrival. | 03 |
| REQ-TA-002 | M | ME creates **Replacement Request** linked to maintenance case + faulty entity / S/N. | 03, 04 |
| REQ-TA-003 | M | PD reviews request: Approve (assign/confirm ME) or Reject (with reason). | 04 |
| REQ-TA-004 | M | After PD approve, ME requests IM to **issue** same-spec fresh inventory. | 04 |
| REQ-TA-005 | M | IM issues and ships replacement S/N; hierarchy/project record shows **new serial** with **Replaced** badge. | 03, 04 |
| REQ-TA-006 | M | On ship/issue: **red (high) notification** on Project / Order / Flight / SDLS that replacement case is open. | 03, 06 |
| REQ-TA-007 | M | On ship/issue: faulty item automatically queued for IM return (`awaiting_faulty_arrival`) — Track B may start later. | 03, 05 |
| REQ-TA-008 | M | ME takes custody; notifies PD **Shipment/AIT in Progress**. | 04 |
| REQ-TA-009 | M | ME + FSE perform site replace / repair / integrate. | 04 |
| REQ-TA-010 | M | ME uploads AIT / integration test results (attachments). | 04 |
| REQ-TA-011 | M | PD Approves or Rejects replacement based on test results. | 04 |
| REQ-TA-012 | M | On Reject: IM issues **new** replacement to **same ME**; loop until AIT pass / Approve. | 04 |
| REQ-TA-013 | M | On Approve: mark **patch delivered** / Track A complete. | 04 |
| REQ-TA-014 | M | Track A sub-statuses persisted (see FSD §4); do not overwrite `CaseStatus` enum values. | 06 |
| REQ-TA-015 | S | Stock shortage / no matching S/N → escalate PD/HM; hold issue. | 04 gaps |
| REQ-TA-016 | S | Failed/rejected unit returned to IM quarantine before next issue. | 04 gaps |
| REQ-TA-017 | S | Abort Track A if later NFF; clear red notification; keep audit. | 04 gaps |
| REQ-TA-018 | S | ME reassignment when unavailable. | 04 gaps |
| REQ-TA-019 | C | Customer reception acknowledgement for delivered patch. | 04 |

---

## 5. Track B — Faulty return & inspection

| ID | Priority | Requirement | Source |
|----|----------|-------------|--------|
| REQ-TB-001 | M | IM records **reception date** when faulty arrives; notifies PD. | 05 |
| REQ-TB-002 | M | PD assigns **Inspection Engineer (IE)**. | 05 |
| REQ-TB-003 | M | IE requests IM handover; IM issues faulty item to IE. | 05 |
| REQ-TB-004 | M | Status updates to **Inspection under process**. | 05 |
| REQ-TB-005 | M | If irreparable and **under warranty** → ship to supplier / OEM claim path. | 05 |
| REQ-TB-006 | M | If irreparable and warranty expired/none → IE comments + IM discard/trash → **Discarded** badge; item never reusable. | 05 |
| REQ-TB-007 | M | If repairable → status **Repair under progress**; IE notifies actual issue. | 05 |
| REQ-TB-008 | M | After repair, PD verifies tests; Approve → repaired + reports → IM restock; Reject → remain in repair loop. | 05 |
| REQ-TB-009 | M | IE recommends discard; **only IM** executes trash (segregation of duties). | 05 gaps |
| REQ-TB-010 | S | Reusable disposition → restock without full repair (existing). | 05 |
| REQ-TB-011 | S | Faulty never returned → SLA timeout + PD escalation; Track A may close with caveat flag. | 05 gaps |
| REQ-TB-012 | C | QR/custody scan at receive/issue. | 05 |

---

## 6. Close gate, badges, notifications

| ID | Priority | Requirement | Source |
|----|----------|-------------|--------|
| REQ-CL-001 | M | Case close when Track A complete **and** Track B terminal (restocked / discarded / claim closed), **or** early Soft/NFF exit. | 03 |
| REQ-CL-002 | M | Red replacement-open notification cleared when Track A `patch_delivered` or aborted. | 06 |
| REQ-BDG-001 | M | **Replaced** badge visible wherever the new S/N is shown for that entity/project context. | 06 |
| REQ-BDG-002 | M | **Discarded** badge on inventory row after trash; discarded S/N blocked from reserve/issue. | 06 |
| REQ-NTF-001 | M | Notification events per matrix in FSD §7 (at least: replacement_requested, shipped/red, ait_*, faulty_received, ie_assigned, case_closed). | 06 |

---

## 7. Dual-track UX

| ID | Priority | Requirement | Source |
|----|----------|-------------|--------|
| REQ-UX-001 | M | Case detail shows dual-track progress board (Track A + Track B). | 06 backlog |
| REQ-UX-002 | S | Occurrence attachments reusable as evidence on Replacement Request / IE / PD gates. | 04 |

---

## Requirement counts

| Priority | Count |
|----------|------:|
| M (Must) | 52 |
| S (Should) | 12 |
| C (Could) | 4 |
| **Total** | **68** |

> Counts may be adjusted only by change-control; matrix version must match this baseline version.
