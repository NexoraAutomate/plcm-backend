# 03 — Unit Test Specification (UT)

**Scope:** Isolated backend services, domain rules, schema validation, and pure frontend helpers.  
**Harness:** pytest (`plcm-backend/tests/`), frontend unit tests as adopted by the repo.  
**Rule:** Every Must REQ in P0–P5 that is logic-local must have ≥1 UT; mark N/A only for pure UI E2E items (covered in FT/ST).

---

## 1. Conventions

| Field | Meaning |
|-------|---------|
| UT-ID | Unique test id |
| REQ | Trace to REQ-MHD-* |
| Pass criteria | Observable assertion |
| Location (target) | Suggested test module |

---

## 2. Roles & foundations (P0)

| UT-ID | REQ | Description | Pass criteria | Target |
|-------|-----|-------------|---------------|--------|
| UT-RL-001 | RL-001 | WorkflowRole includes ME, FSE, IE | Enum members present | `tests/unit/test_workflow_roles_permissions.py` |
| UT-RL-002 | RL-002 | maintenance.* permissions mapped to roles | ME/FSE/IE grants match catalog | same |
| UT-RL-003 | DT-001 | CaseStatus values unchanged | Exactly open…closed spine | `tests/unit/test_case_status_spine.py` (new) |
| UT-RL-004 | RL-003 | Legacy Maintenance still resolvable as notify target | Demo/notify helper includes Maintenance | seed / notification unit |

---

## 3. Occurrence Report (P1)

| UT-ID | REQ | Description | Pass criteria |
|-------|-----|-------------|---------------|
| UT-OR-001 | OR-002 | occurrence_date stored independently of recorded_at | recorded_at set by system; occurrence_date equals input |
| UT-OR-002 | OR-004 | Reject unknown outcome | 422 / validation error |
| UT-OR-003 | OR-005 | soft_fix + resolve_soft_fixed resolves case/entity | soft_fixed resolution applied |
| UT-OR-004 | OR-005 | soft_fix without method rejected | validation error |
| UT-OR-005 | OR-006 | NFF with confirm_close=True resolves as no_fault_found | status/resolution match |
| UT-OR-006 | OR-006 | NFF with confirm_close=False keeps case open | case remains open; note saved |
| UT-OR-007 | OR-007 | inconclusive does not resolve | case open |
| UT-OR-008 | OR-008 | fault_identified without fault_type rejected | validation error |
| UT-OR-009 | OR-009 | confirmation_channel required on fault | validation error if missing |
| UT-OR-010 | OR-010 | attachment without display name rejected | validation error |
| UT-OR-011 | OR-011 | officers payload persisted | officers count/roles match |
| UT-OR-012 | OR-015 | Legacy payload without new fields still accepted | backward compatible |

---

## 4. Dual-track / ReplacementRequest (P2–P3)

| UT-ID | REQ | Description | Pass criteria |
|-------|-----|-------------|---------------|
| UT-RA-001 | RA-001 | Create ReplacementRequest links case + entity | FKs set; status=replacement_requested |
| UT-RA-002 | RA-003 | Reserve inventory marks reserved | inventory not double-reserved |
| UT-RA-003 | RA-004 | PD reject sets pd_rejected + reason | cannot proceed to issue |
| UT-RA-004 | RA-006 | Issue blocked when no matching stock | shortage path; no S/N issued |
| UT-RA-005 | RA-007 | Successful issue sets Replaced badge flag / history | hierarchy S/N updated |
| UT-RA-006 | RA-009 | Issue creates awaiting_faulty_arrival on Track B | rework stage set |
| UT-RA-007 | RA-012 | AIT approve → patch_delivered | sub-status transition valid |
| UT-RA-008 | RA-013 | AIT reject → ait_rejected; allows re-issue loop | prior unit quarantine state |
| UT-RA-009 | RA-015 | Illegal sub-status jumps rejected | state machine guard |
| UT-RA-010 | DT-003 | Close gate fails if Track A incomplete | close/resolve API raises/returns 409 |

---

## 5. Inspection / Track B (P4)

| UT-ID | REQ | Description | Pass criteria |
|-------|-----|-------------|---------------|
| UT-IE-001 | IE-001 | reception_date sets received | status received |
| UT-IE-002 | IE-003 | PD assign IE | ie_assigned + assignee |
| UT-IE-003 | IE-004 | Issue to IE → inspection_under_process | status match |
| UT-IE-004 | IE-005 | Repairable → repair_under_progress | status match |
| UT-IE-005 | IE-006 | Irreparable + warranty → claim created/required | OEM claim linked |
| UT-IE-006 | IE-007 | Discard recommend without IM confirm does not trash | item not scrapped |
| UT-IE-007 | IE-007/008 | IM confirm discard → scrapped + Discarded flag | not selectable for reserve |
| UT-IE-008 | IE-009/010 | PD reject repair keeps repair_under_progress | no restock |
| UT-IE-009 | IE-010 | PD approve → restocked | available for future projects |
| UT-IE-010 | IE-011 | Terminal states only: restocked/discarded/claim_closed | helper is_track_b_terminal |

---

## 6. Notifications & badges (helpers)

| UT-ID | REQ | Description | Pass criteria |
|-------|-----|-------------|---------------|
| UT-NT-001 | RL-004 | Event builder emits replacement_requested high | priority=high |
| UT-NT-002 | RA-008 | RED event type replacement_case_open | typed event present |
| UT-NT-003 | RA-016 | Clear RED helper removes open flag | flag cleared |

---

## 7. Execution & reporting

```text
# Backend (from plcm-backend)
pytest tests/unit -k "workflow_roles or occurrence or replacement or inspection" -q
pytest tests/ -k "mhd or maintenance_occurrence" -q   # once suites land
```

Record results in [08-test-report-template.md](./08-test-report-template.md) section **Unit**.  
Failed UT → open NCR per [07](./07-non-conformance-and-verification-loop.md); block Verified status for linked REQs.
