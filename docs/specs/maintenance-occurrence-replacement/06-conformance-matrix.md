# 06 — Conformance Matrix

**Feature:** MHD Occurrence Report + Dual-Track  
**Baseline date:** 2026-11-07 (from code exploration vs `MHD.drawio`)  
**Last verification cycle:** 2026-11-07 — P0–P2 UT/FT/ST (`reports/TR-MHD-20261107.md`)  
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
| OR-001 | Must | Implemented | N/A | FT-OR-001 Pass | N/A | Verified | UI labels Occurrence Report |
| OR-002 | Must | Implemented | UT-OR-001 Pass | FT-OR-002 Pass | N/A | Verified | occurrence_date independent |
| OR-003 | Must | Implemented | UT-OR-001 Pass | FT-OR-002 Pass | N/A | Verified | onsite_recorded_by_id |
| OR-004 | Must | Implemented | UT-OR-002 Pass | FT-OR-* Pass | ST-02/03/04 Pass | Verified | NFF in OnsiteOutcome |
| OR-005 | Must | Implemented | UT-OR-003/004 Pass | FT-OR-003 Pass | ST-01 Pass | Verified | soft_fixed path |
| OR-006 | Must | Implemented | UT-OR-005/006 Pass | FT-OR-004/005 Pass | ST-02/03 Pass | Verified | NFF confirm Yes/No |
| OR-007 | Must | Implemented | UT-OR-007 Pass | FT-OR-006 Pass | ST-04 Pass | Verified | |
| OR-008 | Must | Implemented | UT-OR-008 Pass | FT-OR-007 Pass | ST-05 Skip | Verified (P1) | ST-05 deferred P3+ |
| OR-009 | Must | Implemented | UT-OR-009 Pass | FT-OR-007 Pass | ST-05 Skip | Verified (P1) | |
| OR-010 | Must | Implemented | UT-OR-010 Pass | FT-OR-008/009 Pass | N/A | Verified | Named attachments |
| OR-011 | Must | Implemented | UT-OR-011 Pass | FT-OR-010 Pass | N/A | Verified | Officers |
| OR-012 | Should | Implemented | N/A | FT-OR-010 Pass | N/A | Verified | Warning-only UX |
| OR-013 | Must | Implemented | N/A | FT-OR-007 Pass | ST-05 Skip | Verified (P1/P2) | CTA + create RR |
| OR-014 | Must | Implemented | N/A | FT-OR-011 Pass | ST-05 Skip | Verified (P1) | Tree parallel |
| OR-015 | Must | Implemented | UT-OR-012 Pass | Pass | N/A | Verified | Additive fields |
| OR-016 | Should | Implemented | N/A | FT-OR-012 Pass | ST-14 Skip | Verified (P1) | occurrence_recorded notify |

---

## Matrix — Dual-track (DT)

| REQ | Pri | Impl | UT | FT | ST | Conf | Notes |
|-----|-----|------|----|----|----|------|-------|
| DT-001 | Must | Implemented | UT-RL-003 Pass | N/A | ST-13 Pass | Verified | Spine intact |
| DT-002 | Must | Implemented (P2) | UT-RA board Pass | FT-DT-004 Pass | ST-05 Skip | Verified (P2) | Track A without reception; ship path P3 |
| DT-003 | Must | Not Started | Pending | Pending | ST-09 Skip | Not Started | P5 close gate |
| DT-004 | Must | Implemented | N/A | FT-OR-003 Pass | ST-01 Pass | Verified | Soft/NFF early exit |
| DT-005 | Must | Implemented | UT board Pass | FT-DT-001 Pass | ST-05 Skip | Verified (P2) | Dual-track board API+UI |
| DT-006 | Must | Partial | Pass (P0–P2 slice) | Pass | ST-13 Pass | Verified (P0–P2) | Continuous NR through P5 |

---

## Matrix — Replacement / AIT (RA)

| REQ | Pri | Impl | UT | FT | ST | Conf | Notes |
|-----|-----|------|----|----|----|------|-------|
| RA-001 | Must | Implemented (P2) | UT-RA-001 Pass | FT-DT-002 Pass | ST-05 Skip | Verified (P2) | ReplacementRequest entity + APIs |
| RA-002 | Must | Implemented (P2) | UT-RA-001 Pass | FT-DT-002 Pass | ST-05 Skip | Verified (P2) | create + PD high notify |
| RA-003 | Must | Implemented (P2) | UT-RA-002 Pass | FT-DT-003 Pass | ST-05 Skip | Verified (P2) | HM assign ME; reserve via UT |
| RA-004 | Must | Implemented (P3) | UT reject Pass | FT-RA-001 Pass | ST-11 Skip | Verified (P3 slice) | Pre-issue PD gate; ST deferred |
| RA-005 | Must | Implemented (P3) | UT me_request Pass | FT-RA-002 Pass | ST-05 Skip | Verified (P3 slice) | ME request-issue from pd_approved |
| RA-006 | Must | Implemented (P3) | UT-RA-004 Pass | FT-RA shortage via UT | ST-10 Skip | Verified (P3 slice) | shortage_held; no fake issue |
| RA-007 | Must | Implemented (P3) | UT-RA-005 Pass | Pending E2E stock | ST-05 Skip | Verified (P3 UT) | IM issue + hierarchy swap |
| RA-008 | Must | Implemented (P3) | UT red_notified | Board RED chip | ST-14 Skip | Verified (P3 slice) | replacement_case_open notify + board RED |
| RA-009 | Must | Implemented (P3) | UT-RA-006 Pass | FT-DT-004 updated | ST-05 Skip | Verified (P3 slice) | Track B awaiting on IM issue (ship) |
| RA-010 | Must | Implemented (P3) | UT upload Pass | FT AIT guards Pass | ST-05 Skip | Verified (P3 slice) | AIT start + named attachments |
| RA-011 | Must | Implemented (P3) | Covered by AIT start | Board ME AIT CTA | ST-05 Skip | Verified (P3 slice) | Custody/site via AIT in progress |
| RA-012 | Must | Implemented (P3) | UT-RA-007 Pass | FT AIT guards Pass | ST-05 Skip | Verified (P3 slice) | PD AIT approve/reject |
| RA-013 | Must | Implemented (P3) | UT-RA-008 Pass | Pending E2E loop | ST-06 Skip | Verified (P3 UT) | Quarantine INSPECTION + re-issue |
| RA-014 | Must | Implemented (P3) | UT-RA-007 Pass | Pending E2E | ST-05 Skip | Verified (P3 UT) | → patch_delivered |
| RA-015 | Must | Implemented (P3) | UT-RA illegal jump Pass | FT-DT/RA Pass | ST-05 Skip | Verified (P3 slice) | Full spine transitions wired |
| RA-016 | Should | Not Started | Pending | Pending | ST-05 Skip | Not Started | P5 |
| RA-017 | Should | Not Started | Pending | Pending | ST-15 Skip | Not Started | GAP-04 |
| RA-018 | Should | Not Started | Pending | Pending | N/A | Not Started | |
| RA-019 | Should | Implemented (P3) | UT upload link | API occurrence_attachment_id | N/A | Verified (P3 slice) | Optional link on AIT attach |
| RA-020 | Could | Not Started | N/A | N/A | N/A | Not Started | GAP-07 |

---

## Matrix — Inspection / IE (IE)

| REQ | Pri | Impl | UT | FT | ST | Conf | Notes |
|-----|-----|------|----|----|----|------|-------|
| IE-001 | Must | Partial (columns + awaiting) | Pending | Pending | ST-05 Skip | Partial | Reception flow P4 |
| IE-002 | Must | Partial | Pending | Pending | ST-05 Skip | Partial | P4 |
| IE-003 | Must | Partial | Pending | Pending | ST-05 Skip | Partial | P4 |
| IE-004 | Must | Partial | Pending | Pending | ST-05 Skip | Partial | P4 |
| IE-005 | Must | Partial | Pending | Pending | ST-05 Skip | Partial | P4 |
| IE-006 | Must | Implemented (OEM claim legacy) | Pending | Pending | ST-07 Skip | Partial | IE-driven path P4 |
| IE-007 | Must | Partial | Pending | Pending | ST-08/12 Skip | Partial | P4 |
| IE-008 | Must | Not Started (UI badge) | Pending | Pending | ST-08 Skip | Not Started | P4 |
| IE-009 | Must | Partial | Pending | Pending | ST-05 Skip | Partial | P4 |
| IE-010 | Must | Partial | Pending | Pending | ST-05 Skip | Partial | P4 |
| IE-011 | Must | Not Started | Pending | Pending | ST-09 Skip | Not Started | P4/P5 |
| IE-012 | Must | Not Started | Pending | Pending | ST-05 Skip | Not Started | P4 |
| IE-013 | Should | Implemented (reusable) | N/A | Pending | N/A | Partial | |
| IE-014 | Should | Not Started | N/A | N/A | ST-16 Skip | Not Started | GAP-08 |
| IE-015 | Could | Not Started | N/A | N/A | N/A | Not Started | GAP-11 |

---

## Matrix — Roles / notifications / NR

| REQ | Pri | Impl | UT | FT | ST | Conf | Notes |
|-----|-----|------|----|----|----|------|-------|
| RL-001 | Must | Implemented | UT-RL-001 Pass | N/A | N/A | Verified | ME/FSE/IE + 8 roles |
| RL-002 | Must | Partial (P0–P2 perms) | UT-RL-002 Pass | FT-* Pass | ST-05 Skip | Verified (P0–P2) | Full matrix through P4 |
| RL-003 | Must | Implemented | UT-RL-004 Pass | N/A | N/A | Verified | Legacy Maintenance notify |
| RL-004 | Must | Not Started (full matrix) | Pending | Pending | ST-14 Skip | Not Started | P5 |
| RL-005 | Must | Partial | N/A | Pending | ST-14 Skip | Partial | P3–P4 badges |
| NR-001 | Must | Implemented | UT-OR-003 Pass | FT-OR-003 Pass | ST-01/13 Pass | Verified | Soft fix |
| NR-002 | Must | Implemented | N/A | FT-OR-007 Pass | N/A | Verified | FaultType on OR |
| NR-003 | Must | Implemented | UT approve rework Pass | FT-DT-004 Pass | ST-13 Pass | Verified (P2) | create_returned_unit_rework retained |
| NR-004 | Must | Partial | P0–P2 suite Pass | P0–P2 Pass | P0–P2 Pass | Partial | Full Must coverage at P6 |
| NR-005 | Must | Not Started | — | — | — | Not Started | Sign-off after P5/P6 |

---

## Summary dashboard (update each review)

| Priority | Total | Satisfied | Verified | Accepted Deviation | NCR Open | Remaining (Not Started / Partial) |
|----------|-------|-----------|----------|--------------------|----------|-----------------------------------|
| Must | 57 | 0 | ~28 (P0–P2 slice) | 0 | 0 | ~29 (P3–P6) |
| Should | 8 | 0 | 2 | 0 | 0 | 6 |
| Could | 2 | 0 | 0 | 0 | 0 | 2 |

**P0–P2 verification verdict (2026-11-07):** UT 40 Pass; FT 15 Pass; ST 5 Pass / 3 Skip (P3–P5). See `reports/TR-MHD-20261107.md`.  
**Fix shipped in cycle:** `FaultyEntity.resolution_type` values_callable + lowercase `resolutiontype` PG labels (`o6a7b8c9d0`).  
**PO action:** Mark Verified P0–P2 Must rows as **Satisfied** when accepted; proceed to P3.

---

## Open decisions for user (non-conformance / scope)

Confirm before treating Should/Could as Must:

1. **NFF:** Resolved — `no_fault_found` on `OnsiteOutcome` + confirm_close_nff.  
2. **Spelling:** “Occurrence” used in UI (not “Occurance”).  
3. **GAP-01…GAP-12:** Which are Must for v1 vs Accepted Deviation / backlog?  
4. **Close caveat (IE-014):** Allow Track A close if faulty never returned?  
5. **Demo users:** Treat seed script accounts as official ST actors?

Record answers in NCR/ADR log ([07](./07-non-conformance-and-verification-loop.md)) and refresh this Matrix.
