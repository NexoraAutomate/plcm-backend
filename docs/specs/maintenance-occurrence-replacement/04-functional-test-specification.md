# 04 — Functional Test Specification (FT)

**Scope:** API + UI feature tests against a running (or test) stack for one feature slice at a time.  
**Actors:** Use seeded demo users from `scripts/seed_maintenance_demo_users.py` (ME/FSE/IE/PD/IM/HM).  
**Not E2E dual-track end-to-end** — that is System Test (05). FT may cover a single track or single screen thoroughly.

---

## 1. Preconditions

1. Roles/permissions synced; demo users exist.
2. Maintenance case open against a known S/N in a project hierarchy.
3. Spare same-P/N inventory available for Track A happy path; separate fixture for shortage.

---

## 2. Occurrence Report (FT-OR)

| FT-ID | REQ | Steps | Expected |
|-------|-----|-------|----------|
| FT-OR-001 | OR-001 | Open case detail | Panel titled Occurrence Report; button Record Occurrence Report |
| FT-OR-002 | OR-002/003 | Submit with occurrence_date in past | Saved; recorded_at ≈ now; recorded_by = actor |
| FT-OR-003 | OR-005 | Soft fix + method + save | Case/entity soft_fixed; no Track A CTA |
| FT-OR-004 | OR-006 | NFF → Yes on modal | Resolved/closed as NFF |
| FT-OR-005 | OR-006 | NFF → No on modal | Case open; NFF note visible |
| FT-OR-006 | OR-007 | Inconclusive | Case open; no replacement CTA |
| FT-OR-007 | OR-008/009/013 | Fault + type + channel + evidence | CTA Request immediate replacement visible |
| FT-OR-008 | OR-010 | Upload file with display name | Attachment listed by name |
| FT-OR-009 | OR-010 | Upload without name | Blocked with validation message |
| FT-OR-010 | OR-011 | Add FSE officer + guest observer | Officers list persisted after reload |
| FT-OR-011 | OR-014 | After fault | Investigation tree still usable |
| FT-OR-012 | OR-016 | After record | PD (and ME if any) receive occurrence_recorded |

---

## 3. Dual-track board & request (FT-DT)

| FT-ID | REQ | Steps | Expected |
|-------|-----|-------|----------|
| FT-DT-001 | DT-005 | After fault + create request | Dual-track board shows Track A started; Track B awaiting or idle |
| FT-DT-002 | RA-002 | Authorized user creates Replacement Request | Status replacement_requested; PD notified high |
| FT-DT-003 | RA-003 | HM assigns ME + reserves S/N | ME assigned; inventory reserved; case marked to ME |
| FT-DT-004 | DT-002 | Observe timing | Track A advances without requiring reception of faulty |

---

## 4. Track A Replacement / AIT (FT-RA)

| FT-ID | REQ | Steps | Expected |
|-------|-----|-------|----------|
| FT-RA-001 | RA-004 | PD rejects request | pd_rejected; IM cannot issue |
| FT-RA-002 | RA-004/005 | PD approves; ME requests issue | im_issue_pending |
| FT-RA-003 | RA-006 | Shortage fixture | Escalation shown; no issue; no Replaced badge |
| FT-RA-004 | RA-007/008/009 | IM issues available S/N | Hierarchy new S/N; Replaced badge; RED on Project/Order/Flight/SDLS; Track B awaiting |
| FT-RA-005 | RA-010/011 | ME custody + site + AIT upload | ait_in_progress; attachments visible to PD |
| FT-RA-006 | RA-012/014 | PD approves AIT | patch_delivered; Track A complete |
| FT-RA-007 | RA-013 | PD rejects AIT | New issue to same ME; failed unit quarantined; loop allowed |
| FT-RA-008 | RL-005 | View inventory/hierarchy | Replaced badge present on new S/N context |

---

## 5. Track B Inspection (FT-IE)

| FT-ID | REQ | Steps | Expected |
|-------|-----|-------|----------|
| FT-IE-001 | IE-002 | IM enters reception_date | PD notified faulty_received; status received |
| FT-IE-002 | IE-003/004 | PD assigns IE; IE handover; IM issues | inspection_under_process |
| FT-IE-003 | IE-005/009/010 | Repairable → repair → PD approve | restocked; Track B terminal |
| FT-IE-004 | IE-006 | Irreparable + warranty | OEM claim path; claim_closed eventually terminal |
| FT-IE-005 | IE-007/008 | Irreparable + no warranty; IE recommend; IM trash | Discarded badge; not reservable |
| FT-IE-006 | IE-007 | IE alone attempts trash | Denied; segregation enforced |
| FT-IE-007 | IE-010 | PD rejects repair tests | Remains repair_under_progress |

---

## 6. Close gate (FT-CG)

| FT-ID | REQ | Steps | Expected |
|-------|-----|-------|----------|
| FT-CG-001 | DT-003 | Attempt close with only Track A done | Blocked with clear message |
| FT-CG-002 | DT-003 | Attempt close with only Track B done | Blocked |
| FT-CG-003 | DT-003 | Both terminal | Close succeeds; case_closed notify |
| FT-CG-004 | DT-004 | Soft-fix case | Close/resolve without dual-track |
| FT-CG-005 | RA-016 | After patch_delivered | RED cleared (or on abort) |

---

## 7. Pass / Fail rules

- **Pass:** All steps Expected met; screenshots or API logs attached for Must cases on first full cycle.
- **Fail:** Any Expected mismatch → NCR; linked REQs set to NCR Open in Matrix.
- **Blocked:** Missing fixture/env → NCR type Environment; do not mark REQ Satisfied.

Update [06-conformance-matrix.md](./06-conformance-matrix.md) after each FT run.
