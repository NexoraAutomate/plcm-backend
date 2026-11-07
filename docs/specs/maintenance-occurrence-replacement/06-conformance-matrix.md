# 06 — Conformance Matrix

**Feature:** MHD Occurrence Report + Dual-Track  
**Baseline date:** 2026-11-07 (from code exploration vs `MHD.drawio`)  
**Last verification cycle:** 2026-11-07 — P6 full UT/FT/ST (`reports/TR-MHD-20261107-P6.md`)  
**Owner:** Product Owner + Engineering + QA  
**Rule:** Release / feature sign-off only when every **Must** row is **Satisfied** or **Accepted Deviation** (signed).

Update this file after each phase. Status values: see [README](./README.md).

---

## How to use

1. Implement → set **Impl** to Partial/Implemented.  
2. Pass linked UT/FT/ST → set **Verified**.  
3. PO accepts evidence → **Satisfied**.  
4. Fail → **NCR Open** + link NCR-ID; notify user (doc 07).  
5. User waives → **Accepted Deviation** + residual risk.

**Columns**

| Col | Meaning |
|-----|---------|
| Impl | Code status vs REQ |
| UT / FT / ST | Test refs (Pass/Fail/Pending/N/A) |
| Conf | Conformance status |
| Notes | Gap / NCR / waiver |

---

## Matrix — Occurrence Report (OR)

| REQ | Pri | Impl | UT | FT | ST | Conf | Notes |
|-----|-----|------|----|----|----|------|-------|
| OR-001 | Must | Implemented | N/A | FT-OR-001 Pass | N/A | Satisfied | UI labels Occurrence Report |
| OR-002 | Must | Implemented | UT-OR-001 Pass | FT-OR-002 Pass | N/A | Satisfied | occurrence_date independent |
| OR-003 | Must | Implemented | UT-OR-001 Pass | FT-OR-002 Pass | N/A | Satisfied | onsite_recorded_by_id |
| OR-004 | Must | Implemented | UT-OR-002 Pass | FT-OR-* Pass | ST-02/03/04 Pass | Satisfied | NFF in OnsiteOutcome |
| OR-005 | Must | Implemented | UT-OR-003/004 Pass | FT-OR-003 Pass | ST-01 Pass | Satisfied | soft_fixed path |
| OR-006 | Must | Implemented | UT-OR-005/006 Pass | FT-OR-004/005 Pass | ST-02/03 Pass | Satisfied | NFF confirm Yes/No |
| OR-007 | Must | Implemented | UT-OR-007 Pass | FT-OR-006 Pass | ST-04 Pass | Satisfied | |
| OR-008 | Must | Implemented | UT-OR-008 Pass | FT-OR-007 Pass | ST-05 Pass | Satisfied | Fault + RR path |
| OR-009 | Must | Implemented | UT-OR-009 Pass | FT-OR-007 Pass | ST-05 Pass | Satisfied | |
| OR-010 | Must | Implemented | UT-OR-010 Pass | FT-OR-008/009 Pass | N/A | Satisfied | Named attachments |
| OR-011 | Must | Implemented | UT-OR-011 Pass | FT-OR-010 Pass | N/A | Satisfied | Officers |
| OR-012 | Should | Implemented | N/A | FT-OR-010 Pass | N/A | Satisfied | Warning-only UX |
| OR-013 | Must | Implemented | N/A | FT-OR-007 Pass | ST-05 Pass | Satisfied | CTA + create RR |
| OR-014 | Must | Implemented | N/A | FT-OR-011 Pass | ST-05 Pass | Satisfied | Tree parallel |
| OR-015 | Must | Implemented | UT-OR-012 Pass | Pass | N/A | Satisfied | Additive fields |
| OR-016 | Should | Implemented | N/A | FT-OR-012 Pass | ST-14 Pass | Satisfied | occurrence_recorded notify |

---

## Matrix — Dual-track (DT)

| REQ | Pri | Impl | UT | FT | ST | Conf | Notes |
|-----|-----|------|----|----|----|------|-------|
| DT-001 | Must | Implemented | UT-RL-003 Pass | N/A | ST-13 Pass | Satisfied | Spine intact |
| DT-002 | Must | Implemented | UT-RA board Pass | FT-DT-004 Pass | ST-05 Pass | Satisfied | Track A without reception; ship on IM issue |
| DT-003 | Must | Implemented | UT-RA-010 Pass | FT-CG-001…003 Pass | ST-09 Pass | Satisfied | Close gate |
| DT-004 | Must | Implemented | UT DT-004 Pass | FT-CG-004 + delivery Pass | ST-01 Pass | Satisfied | Soft/NFF + dual-track N/A delivery close |
| DT-005 | Must | Implemented | UT board Pass | FT-DT-001 Pass | ST-05 Pass | Satisfied | Dual-track board API+UI |
| DT-006 | Must | Implemented | Pass | Pass | ST-13/14 Pass | Satisfied | Full ST non-regression at P6 |

---

## Matrix — Replacement / AIT (RA)

| REQ | Pri | Impl | UT | FT | ST | Conf | Notes |
|-----|-----|------|----|----|----|------|-------|
| RA-001 | Must | Implemented | UT-RA-001 Pass | FT-DT-002 Pass | ST-05 Pass | Satisfied | ReplacementRequest entity + APIs |
| RA-002 | Must | Implemented | UT-RA-001 Pass | FT-DT-002 Pass | ST-05/14 Pass | Satisfied | create + PD high notify |
| RA-003 | Must | Implemented | UT-RA-002 Pass | FT-DT-003 Pass | ST-05 Pass | Satisfied | HM assign ME; reserve |
| RA-004 | Must | Implemented | UT reject Pass | FT-RA-001 Pass | ST-11 Pass | Satisfied | Pre-issue PD gate |
| RA-005 | Must | Implemented | UT me_request Pass | FT-RA-002 Pass | ST-05 Pass | Satisfied | ME request-issue from pd_approved |
| RA-006 | Must | Implemented | UT-RA-004 Pass | Pass | ST-10 Pass | Satisfied | No fake issue without stock |
| RA-007 | Must | Implemented | UT-RA-005 Pass | Pass | ST-05 Pass | Satisfied | IM issue + hierarchy swap |
| RA-008 | Must | Implemented | UT red_notified | Board RED chip | ST-14 Pass | Satisfied | replacement_case_open notify + RED |
| RA-009 | Must | Implemented | UT-RA-006 Pass | FT-DT-004 Pass | ST-05 Pass | Satisfied | Track B awaiting on IM issue |
| RA-010 | Must | Implemented | UT upload Pass | FT AIT guards Pass | ST-05 Pass | Satisfied | AIT start + named attachments |
| RA-011 | Must | Implemented | Covered by AIT start | Board ME AIT CTA | ST-05 Pass | Satisfied | Custody/site via AIT in progress |
| RA-012 | Must | Implemented | UT-RA-007 Pass | FT AIT guards Pass | ST-05/06 Pass | Satisfied | PD AIT approve/reject |
| RA-013 | Must | Implemented | UT-RA-008 Pass | Pass | ST-06 Pass | Satisfied | Quarantine + re-issue |
| RA-014 | Must | Implemented | UT-RA-007 Pass | Pass | ST-05/06 Pass | Satisfied | → patch_delivered |
| RA-015 | Must | Implemented | UT-RA illegal jump Pass | FT-DT/RA Pass | ST-05 Pass | Satisfied | Full spine transitions wired |
| RA-016 | Should | Implemented | UT-NT-003 Pass | FT-CG-005 Pass | ST-05/15 Pass | Satisfied | Clear RED on patch_delivered / abort |
| RA-017 | Should | Implemented | UT abort Pass | FT-CG-005 Pass | ST-15 Pass | Satisfied | abort → track_a_closed + reason |
| RA-018 | Should | Implemented | assign_me reassign | Board Assign ME | N/A | Satisfied | HM/PD reassign pre-issue |
| RA-019 | Should | Implemented | UT upload link | API occurrence_attachment_id | N/A | Satisfied | Optional link on AIT attach |
| RA-020 | Could | Not Started | N/A | N/A | N/A | Accepted Deviation | GAP-07 backlog — P5 freeze |

---

## Matrix — Inspection / IE (IE)

| REQ | Pri | Impl | UT | FT | ST | Conf | Notes |
|-----|-----|------|----|----|----|------|-------|
| IE-001 | Must | Implemented | UT-IE-001 Pass | FT-IE-001 Pass | ST-05 Pass | Satisfied | reception_date → received |
| IE-002 | Must | Implemented | UT reception notify | FT-IE-001 Pass | ST-05 Pass | Satisfied | faulty_received notify PD |
| IE-003 | Must | Implemented | UT-IE-002 Pass | FT-IE-002 Pass | ST-05 Pass | Satisfied | PD assign IE |
| IE-004 | Must | Implemented | UT-IE-003 Pass | FT-IE-002 Pass | ST-05 Pass | Satisfied | handover + IM issue → inspection |
| IE-005 | Must | Implemented | UT-IE-004 Pass | FT-IE-003 Pass | ST-05 Pass | Satisfied | repairable → repair_under_progress |
| IE-006 | Must | Implemented | UT-IE-005 Pass | Pass | ST-07 Pass | Satisfied | Warranty + claim_closed |
| IE-007 | Must | Implemented | UT-IE-006/007 Pass | FT-IE-005 Pass | ST-08/12 Pass | Satisfied | discard_pending → IM confirm |
| IE-008 | Must | Implemented | UT discarded_flag | FT Discarded chip | ST-08 Pass | Satisfied | Discarded badge |
| IE-009 | Must | Implemented | UT repair submit | FT-IE-003 Pass | ST-05 Pass | Satisfied | IE repair evidence + PD gate |
| IE-010 | Must | Implemented | UT-IE-008/009 Pass | FT-IE-003/007 Pass | ST-05 Pass | Satisfied | approve restock / reject stays |
| IE-011 | Must | Implemented | UT-IE-010 Pass | FT-CG terminal | ST-07/09 Pass | Satisfied | Wired into close gate |
| IE-012 | Must | Implemented | UT illegal jump | FT-IE spine Pass | ST-05 Pass | Satisfied | MHD ReworkStage spine |
| IE-013 | Should | Implemented | disposition reusable | N/A | N/A | Satisfied | restock without full repair |
| IE-014 | Should | Not Started | N/A | N/A | ST-16 Skip | Accepted Deviation | GAP-08 never-returned SLA backlog |
| IE-015 | Could | Not Started | N/A | N/A | N/A | Accepted Deviation | GAP-11 QR custody backlog |

---

## Matrix — Roles / notifications / NR

| REQ | Pri | Impl | UT | FT | ST | Conf | Notes |
|-----|-----|------|----|----|----|------|-------|
| RL-001 | Must | Implemented | UT-RL-001 Pass | N/A | N/A | Satisfied | ME/FSE/IE + 8 roles |
| RL-002 | Must | Implemented | UT-RL-002 Pass | FT-* Pass | ST-05 Pass | Satisfied | inspection_disposition on Track B |
| RL-003 | Must | Implemented | UT-RL-004 Pass | N/A | N/A | Satisfied | Legacy Maintenance notify |
| RL-004 | Must | Implemented | UT-NT helpers | FT-CG-003/005 + Track B | ST-14 Pass | Satisfied | FSD §7 notify matrix |
| RL-005 | Must | Implemented | N/A | Board + inventory Discarded | ST-08/14 Pass | Satisfied | DiscardedBadge |
| NR-001 | Must | Implemented | UT-OR-003 Pass | FT-OR-003 Pass | ST-01/13 Pass | Satisfied | Soft fix |
| NR-002 | Must | Implemented | N/A | FT-OR-007 Pass | N/A | Satisfied | FaultType on OR |
| NR-003 | Must | Implemented | UT approve rework Pass | FT-DT-004 Pass | ST-13 Pass | Satisfied | create_returned_unit_rework retained |
| NR-004 | Must | Implemented | Full suite Pass | Full suite Pass | ST-01…15 Pass | Satisfied | P6 Must coverage complete |
| NR-005 | Must | Implemented | — | — | — | Satisfied | CR-MHD-20261107 Approved with deviations (2026-11-07) |

---

## Summary dashboard (update each review)

| Priority | Total | Satisfied | Verified | Accepted Deviation | NCR Open | Remaining (Not Started / Partial) |
|----------|-------|-----------|----------|--------------------|----------|-----------------------------------|
| Must | 57 | 57 | 0 | 0 | 0 | 0 |
| Should | 8 | 7 | 0 | 1 (IE-014) | 0 | 0 |
| Could | 2 | 0 | 0 | 2 (RA-020, IE-015) | 0 | 0 |

**P0–P2 verification verdict (2026-11-07):** UT 40 Pass; FT 15 Pass; ST 5 Pass / 3 Skip. See `reports/TR-MHD-20261107.md`.  
**P0–P4 verification verdict (2026-11-07):** MHD suite 88 passed, 3 skipped (ST dual-track E2E deferred).  
**P5 verification verdict (2026-11-07):** UT close-gate/RED/abort Pass; FT-CG-001…005 Pass.  
**P6 verification verdict (2026-11-07):** Full MHD suite **112 passed, 1 skipped** (ST-16 AD); ST-01…15 Pass. See `reports/TR-MHD-20261107-P6.md` + `reports/CR-MHD-20261107.md`.  
**Fix shipped in cycle:** UT AIT approve mock includes `case_id` + asserts `clear_replacement_red` (test-only).  
**PO decision (2026-11-07):** `CR-MHD-20261107` **Approved with deviations** (GAP-07 / GAP-08 / GAP-11). Feature sign-off complete.

---

## Open decisions for user (non-conformance / scope)

Confirm before treating Should/Could as Must:

1. **NFF:** Resolved — `no_fault_found` on `OnsiteOutcome` + confirm_close_nff.  
2. **Spelling:** “Occurrence” used in UI (not “Occurance”).  
3. **GAP-01…GAP-12:** Which are Must for v1 vs Accepted Deviation / backlog?  
4. **Close caveat (IE-014):** Allow Track A close if faulty never returned? — **Accepted Deviation** (backlog).  
5. **Demo users:** Treat seed script accounts as official ST actors? — ST used admin API E2E; seed optional.

Record answers in NCR/ADR log ([07](./07-non-conformance-and-verification-loop.md)) and refresh this Matrix.
