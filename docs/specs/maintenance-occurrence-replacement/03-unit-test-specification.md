# 03 — Unit Test Specification

**Scope:** Backend services/validators/models and frontend pure helpers. No full browser E2E.  
**IDs:** `UT-<area>-NNN`  
**Pass rule:** Assert expected; no network to real external OEM unless mocked.

---

## 1. Occurrence Report — UT-OR-*

| ID | Target | Scenario | Assert | REQ |
|----|--------|----------|--------|-----|
| UT-OR-001 | Payload validator | Missing `occurrence_date` | 400 / validation error | OR-002 |
| UT-OR-002 | Persist service | Save sets `recorded_at`, `recorded_by_id`; user cannot override | Fields match SYS | OR-003 |
| UT-OR-003 | Validator | Soft fix without method | Reject | OR-006 |
| UT-OR-004 | Validator | Fault identified without fault_type | Reject | OR-005 |
| UT-OR-005 | Attachment model | File without display `name` | Reject | OR-008 |
| UT-OR-006 | Officers model | Empty onsite_role | Reject or default policy documented | OR-009 |
| UT-OR-007 | Outcome handler | Soft fix → soft_fixed resolve side effects | Entities/case as existing | OR-011, NR-002 |
| UT-OR-008 | Outcome handler | NFF + confirm=true → resolve NFF path | Status terminal | OR-010 |
| UT-OR-009 | Outcome handler | NFF + confirm=false → note only | Case still open | OR-010 |
| UT-OR-010 | Outcome handler | Inconclusive | Case open; no Track A auto-create | OR-012 |
| UT-OR-011 | Outcome handler | Fault identified | Flag/CTA data ready; no auto-ship | OR-013 |
| UT-OR-012 | FaultType enum | All 10 types accepted | Parse OK | OR-005 |

---

## 2. Roles / permissions — UT-ROLE-*

| ID | Scenario | Assert | REQ |
|----|----------|--------|-----|
| UT-ROLE-001 | ME can create replacement request | Allow | ROLE-001 |
| UT-ROLE-002 | Non-ME/non-privileged cannot create request | Deny | ROLE-001 |
| UT-ROLE-003 | PD only can approve replacement | Deny for ME/IM | ROLE-004 |
| UT-ROLE-004 | IE can request handover; cannot trash | Deny trash | ROLE-003, TB-009 |
| UT-ROLE-005 | IM can trash / issue | Allow | ROLE-005 |

---

## 3. Track A — UT-TA-*

| ID | Scenario | Assert | REQ |
|----|----------|--------|-----|
| UT-TA-001 | Create request without faulty reception | Allowed | TA-001 |
| UT-TA-002 | Status transition: requested → pd_approved | OK | TA-014 |
| UT-TA-003 | Illegal transition: requested → shipped | Reject | TA-014 |
| UT-TA-004 | PD reject stores reason; status pd_rejected | OK | TA-003 |
| UT-TA-005 | Issue same-spec: matching PN/specs | Issue OK; current_serial set | TA-004, TA-005 |
| UT-TA-006 | Issue mismatched specs | Reject | TA-004 |
| UT-TA-007 | On issue: Replaced badge flag / hierarchy update hook | Called once | TA-005, BDG-001 |
| UT-TA-008 | On issue: enqueue awaiting_faulty_arrival | Track B record created | TA-007 |
| UT-TA-009 | On issue: RED notify payload includes project/order/flight/sdls targets | Event shape | TA-006 |
| UT-TA-010 | AIT reject → status back to im_issue_pending; assigned_me unchanged | Same ME | TA-012 |
| UT-TA-011 | AIT approve → patch_delivered | OK | TA-013 |
| UT-TA-012 | Clear RED when patch_delivered | red_notification_active false | CL-002 |
| UT-TA-013 | Shortage path returns escalate code (S) | No issue | TA-015 |
| UT-TA-014 | Abort clears RED; audit retained (S) | OK | TA-017 |

---

## 4. Track B — UT-TB-*

| ID | Scenario | Assert | REQ |
|----|----------|--------|-----|
| UT-TB-001 | Reception sets reception_date; notifies PD | Event fired | TB-001 |
| UT-TB-002 | Assign IE → ie_assigned | OK | TB-002 |
| UT-TB-003 | Issue to IE → inspection_under_process | OK | TB-003, TB-004 |
| UT-TB-004 | Irreparable + warranty active → warranty_claim path | Status/claim link | TB-005 |
| UT-TB-005 | Irreparable + expired → discard_pending only | No auto-trash by IE | TB-006, TB-009 |
| UT-TB-006 | IM confirm trash → Discarded; allocatable=false | Badge/block | TB-006, BDG-002 |
| UT-TB-007 | Discarded S/N cannot be reserved/issued | Reject | BDG-002 |
| UT-TB-008 | Repairable → repair_under_progress | OK | TB-007 |
| UT-TB-009 | PD approve repair → restocked | Inventory available | TB-008 |
| UT-TB-010 | PD reject repair → still repair_under_progress | Loop | TB-008 |

---

## 5. Close gate — UT-CL-*

| ID | Scenario | Assert | REQ |
|----|----------|--------|-----|
| UT-CL-001 | Soft/NFF early close without Track A/B | Allowed | CL-001, OR-010 |
| UT-CL-002 | Close blocked if Track A open and Track B incomplete | Reject | CL-001 |
| UT-CL-003 | Close allowed when A patch_delivered and B discarded | Allow | CL-001 |
| UT-CL-004 | Close allowed when A patch_delivered and B restocked | Allow | CL-001 |

---

## 6. Non-regression — UT-NR-*

| ID | Scenario | Assert | REQ |
|----|----------|--------|-----|
| UT-NR-001 | CaseStatus enum values unchanged | Snapshot | NR-001 |
| UT-NR-002 | Soft fix service behaviour unchanged | Golden assertions | NR-002 |
| UT-NR-003 | OEM claim status transitions still valid | OK | NR-004 |

---

## Execution notes

- Prefer pytest (backend) / Vitest or project standard (frontend).  
- Name test functions after UT IDs for matrix grep.  
- Report template: [07 § Unit Test Report](./07-verification-loop-and-reports.md#unit-test-report-template).
