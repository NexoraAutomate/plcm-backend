# 02 — Requirements Catalog

**ID scheme:** `REQ-MHD-<AREA>-<nnn>`  
**Priority:** Must | Should | Could  
**Source:** MHD.drawio pages 01–06 + FSD 01

Status for each REQ is maintained in the [Conformance Matrix](./06-conformance-matrix.md).

---

## OR — Occurrence Report

| ID | Priority | Requirement | Phase |
|----|----------|-------------|-------|
| REQ-MHD-OR-001 | Must | UI label “Occurrence Report” / button “Record Occurrence Report” (rename from onsite outcome) | P1 |
| REQ-MHD-OR-002 | Must | Capture user `occurrence_date` separate from immutable `onsite_recorded_at` | P1 |
| REQ-MHD-OR-003 | Must | Persist `onsite_recorded_by_id` on record | P1 |
| REQ-MHD-OR-004 | Must | Outcome required: Soft fix \| Fault identified \| Inconclusive \| No Fault Found | P1 |
| REQ-MHD-OR-005 | Must | Soft fix requires soft-fix method; save triggers resolve soft_fixed (existing behavior) | P1 |
| REQ-MHD-OR-006 | Must | NFF presents confirm Close/Resolve modal; Yes → NFF resolve/close; No → note, case remains open | P1 |
| REQ-MHD-OR-007 | Must | Inconclusive leaves case open | P1 |
| REQ-MHD-OR-008 | Must | Fault identified requires Fault Type from FaultType enum | P1 |
| REQ-MHD-OR-009 | Must | Fault identified captures confirmation channel (email/letter/call) + reference/evidence | P1 |
| REQ-MHD-OR-010 | Must | Named attachments[] with user-defined display name per file | P1 |
| REQ-MHD-OR-011 | Must | Officers[] dialog: user or guest + onsite role (+ optional contact) | P1 |
| REQ-MHD-OR-012 | Should | At least one FSE recommended when outcome = fault_identified | P1 |
| REQ-MHD-OR-013 | Must | Fault identified enables Track A “Request immediate replacement” CTA | P1 |
| REQ-MHD-OR-014 | Must | Investigation tree continues in parallel after fault identified | P1 |
| REQ-MHD-OR-015 | Must | Preserve existing onsite_* API compatibility (additive fields) | P1 |
| REQ-MHD-OR-016 | Should | Notify PD/ME on occurrence_recorded | P1 |

---

## DT — Dual-track & principles

| ID | Priority | Requirement | Phase |
|----|----------|-------------|-------|
| REQ-MHD-DT-001 | Must | Augment only; CaseStatus spine unchanged (open→under_inspection→under_repair→resolved→closed) | P0 |
| REQ-MHD-DT-002 | Must | After fault confirmation, Track A and Track B run in parallel; Track A does not wait for faulty return | P2 |
| REQ-MHD-DT-003 | Must | Case close requires Track A patch_delivered/AIT approved AND Track B terminal, OR Soft/NFF early exit | P5 |
| REQ-MHD-DT-004 | Must | Existing delivery-confirm close still allowed when dual-track not applicable | P5 |
| REQ-MHD-DT-005 | Must | Case detail shows dual-track progress board | P2 |
| REQ-MHD-DT-006 | Must | Soft-fix, tree investigation, IM rework, warranty, delivery-close paths have no regression | P0–P5 |

---

## RA — Replacement / AIT (Track A)

| ID | Priority | Requirement | Phase |
|----|----------|-------------|-------|
| REQ-MHD-RA-001 | Must | Replacement Request entity linked to maintenance case + entity S/N | P2 |
| REQ-MHD-RA-002 | Must | Case opener (authorized) can create request; mark to HM; notify PD | P2 |
| REQ-MHD-RA-003 | Must | HM assigns ME; selects/reserves replacement PN/S/N; marks case to ME | P2 |
| REQ-MHD-RA-004 | Must | PD Approve/Reject replacement request (pre-issue) with reason on reject | P3 |
| REQ-MHD-RA-005 | Must | ME requests IM ISSUE of reserved inventory (same-spec) | P3 |
| REQ-MHD-RA-006 | Must | IM stock check; on shortage escalate PD/HM and hold (no fake issue) | P3 |
| REQ-MHD-RA-007 | Must | IM ISSUE updates hierarchy; shows new S/N; sets Replaced badge | P3 |
| REQ-MHD-RA-008 | Must | RED notification on Project/Order/Flight/SDLS while replacement case open | P3 |
| REQ-MHD-RA-009 | Must | On ship, faulty auto-queued awaiting_faulty_arrival (Track B) | P3 |
| REQ-MHD-RA-010 | Must | ME notifies PD AIT in progress; uploads AIT results/attachments | P3 |
| REQ-MHD-RA-011 | Must | ME + FSE perform site replace/integrate | P3 |
| REQ-MHD-RA-012 | Must | PD Approve/Reject AIT based on test results | P3 |
| REQ-MHD-RA-013 | Must | AIT Reject → IM issues new S/N to same ME; failed unit quarantined; ME loops | P3 |
| REQ-MHD-RA-014 | Must | AIT Approve → patch_delivered / Track A complete | P3 |
| REQ-MHD-RA-015 | Must | Replacement sub-status spine per FSD §4.2 | P2–P3 |
| REQ-MHD-RA-016 | Should | Clear RED on patch_delivered or abort | P5 |
| REQ-MHD-RA-017 | Should | Abort Track A if later NFF proven; cancel request; keep audit | P5 |
| REQ-MHD-RA-018 | Should | ME reassignment when unavailable | P5 |
| REQ-MHD-RA-019 | Should | Link Occurrence attachments as evidence on Replacement Request | P3 |
| REQ-MHD-RA-020 | Could | Customer reception ack for delivered patch | P5 |

---

## IE — Inspection / Track B

| ID | Priority | Requirement | Phase |
|----|----------|-------------|-------|
| REQ-MHD-IE-001 | Must | Extend returned-unit rework with awaiting_faulty_arrival + reception_date | P2/P4 |
| REQ-MHD-IE-002 | Must | IM records reception; notifies PD | P4 |
| REQ-MHD-IE-003 | Must | PD assigns Inspection Engineer | P4 |
| REQ-MHD-IE-004 | Must | IE requests handover; IM issues faulty to IE; status inspection_under_process | P4 |
| REQ-MHD-IE-005 | Must | IE disposition: repairable → repair_under_progress | P4 |
| REQ-MHD-IE-006 | Must | Irreparable + under warranty → OEM warranty claim (existing statuses) | P4 |
| REQ-MHD-IE-007 | Must | Irreparable + not under warranty → IE recommends discard; IM executes trash | P4 |
| REQ-MHD-IE-008 | Must | Discarded badge on inventory; never selectable for reserve/issue | P4 |
| REQ-MHD-IE-009 | Must | Repair path: IE repair + evidence; PD verify Approve/Reject | P4 |
| REQ-MHD-IE-010 | Must | PD Approve repair → restock via IM; Reject → remain repair_under_progress | P4 |
| REQ-MHD-IE-011 | Must | Track B terminal = restocked \| discarded \| claim_closed | P4 |
| REQ-MHD-IE-012 | Must | Inspection sub-status spine per FSD §4.3 | P4 |
| REQ-MHD-IE-013 | Should | Reusable outcome restocks without full repair (existing) | P4 |
| REQ-MHD-IE-014 | Should | Faulty-never-returned SLA + PD escalation; optional Track A close with caveat | P5 |
| REQ-MHD-IE-015 | Could | QR custody scan at receive/issue | P5 |

---

## RL — Roles, badges, notifications

| ID | Priority | Requirement | Phase |
|----|----------|-------------|-------|
| REQ-MHD-RL-001 | Must | Seed/wire roles ME, FSE, IE alongside PD, IM, HM, Admin | P0 |
| REQ-MHD-RL-002 | Must | Enforce additive permissions for occurrence, replacement, AIT, inspection | P1–P4 |
| REQ-MHD-RL-003 | Must | Legacy Maintenance remains notify target until ME adopted | P0 |
| REQ-MHD-RL-004 | Must | Notification matrix events per FSD §7 | P5 |
| REQ-MHD-RL-005 | Must | Replaced and Discarded badges visible where S/N shown / inventory tables | P3–P4 |

---

## NR — Non-regression / quality

| ID | Priority | Requirement | Phase |
|----|----------|-------------|-------|
| REQ-MHD-NR-001 | Must | Soft fix path unchanged | P1 |
| REQ-MHD-NR-002 | Must | FaultType enum values remain Electrical…Other (surface on report) | P1 |
| REQ-MHD-NR-003 | Must | create_returned_unit_rework retained and extended | P2 |
| REQ-MHD-NR-004 | Must | Unit, functional, and system tests cover Must REQs before release | P6 |
| REQ-MHD-NR-005 | Must | Conformance Matrix 100% Must = Satisfied or Accepted Deviation before sign-off | P6 |

---

## GAP — Optional backlog (track as Could / Should)

Map GAP-01…GAP-12 from FSD §9 into Accepted Deviation or scheduled backlog during P5 product review with the user.
