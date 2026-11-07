# 06 — Conformance Matrix

**Feature:** MHD Occurrence Report + Dual-Track  
**Baseline date:** 2026-11-07 (from code exploration vs `MHD.drawio`)  
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

| REQ | Pri | Impl (baseline) | UT | FT | ST | Conf | Notes |
|-----|-----|-----------------|----|----|----|------|-------|
| OR-001 | Must | Partial (UI still “Onsite visit outcome”) | Pending | FT-OR-001 | N/A | Not Started | Rename pending |
| OR-002 | Must | Not Started | UT-OR-001 | FT-OR-002 | N/A | Not Started | No occurrence_date |
| OR-003 | Must | Implemented | UT-OR-001 | FT-OR-002 | N/A | Partial | recorded_by exists |
| OR-004 | Must | Partial (no NFF in OnsiteOutcome) | UT-OR-002 | FT-OR-* | ST-02/03 | Partial | Add NFF |
| OR-005 | Must | Implemented | UT-OR-003/004 | FT-OR-003 | ST-01 | Partial | Needs Verified after formal UT |
| OR-006 | Must | Not Started (NFF on entity only) | UT-OR-005/006 | FT-OR-004/005 | ST-02/03 | Not Started | |
| OR-007 | Must | Implemented | UT-OR-007 | FT-OR-006 | ST-04 | Partial | |
| OR-008 | Must | Not Started on report | UT-OR-008 | FT-OR-007 | ST-05 | Not Started | FaultType enum exists |
| OR-009 | Must | Not Started | UT-OR-009 | FT-OR-007 | ST-05 | Not Started | |
| OR-010 | Must | Not Started | UT-OR-010 | FT-OR-008/009 | ST-05 | Not Started | |
| OR-011 | Must | Not Started | UT-OR-011 | FT-OR-010 | ST-05 | Not Started | |
| OR-012 | Should | Not Started | N/A | FT-OR-010 | N/A | Not Started | Warning only |
| OR-013 | Must | Partial (hint only) | Pending | FT-OR-007 | ST-05 | Partial | CTA missing |
| OR-014 | Must | Implemented | N/A | FT-OR-011 | ST-05 | Partial | Tree continues today |
| OR-015 | Must | Implemented (additive TBD) | UT-OR-012 | Pending | N/A | Partial | |
| OR-016 | Should | Not Started | UT-NT-* | FT-OR-012 | ST-14 | Not Started | |

---

## Matrix — Dual-track (DT)

| REQ | Pri | Impl (baseline) | UT | FT | ST | Conf | Notes |
|-----|-----|-----------------|----|----|----|------|-------|
| DT-001 | Must | Implemented | UT-RL-003 | N/A | ST-13 | Partial | Spine intact |
| DT-002 | Must | Not Started | UT-RA-006 | FT-DT-004 | ST-05 | Not Started | Replace today waits/ties rework differently |
| DT-003 | Must | Not Started | UT-RA-010 | FT-CG-001..003 | ST-09 | Not Started | |
| DT-004 | Must | Implemented | N/A | FT-CG-004 | ST-01 | Partial | |
| DT-005 | Must | Not Started | N/A | FT-DT-001 | ST-05 | Not Started | |
| DT-006 | Must | Partial | Pending | Pending | ST-13 | Partial | Continuous NR |

---

## Matrix — Replacement / AIT (RA)

| REQ | Pri | Impl (baseline) | UT | FT | ST | Conf | Notes |
|-----|-----|-----------------|----|----|----|------|-------|
| RA-001 | Must | Not Started | UT-RA-001 | FT-DT-002 | ST-05 | Not Started | No ReplacementRequest entity |
| RA-002 | Must | Not Started | UT-RA-001 | FT-DT-002 | ST-05 | Not Started | |
| RA-003 | Must | Not Started | UT-RA-002 | FT-DT-003 | ST-05 | Not Started | |
| RA-004 | Must | Not Started | UT-RA-003 | FT-RA-001/002 | ST-11 | Not Started | |
| RA-005 | Must | Not Started | Pending | FT-RA-002 | ST-05 | Not Started | |
| RA-006 | Must | Not Started | UT-RA-004 | FT-RA-003 | ST-10 | Not Started | Gap GAP-01 |
| RA-007 | Must | Partial (replace resolve exists) | UT-RA-005 | FT-RA-004 | ST-05 | Partial | Not ME-driven |
| RA-008 | Must | Not Started | UT-NT-002 | FT-RA-004 | ST-14 | Not Started | |
| RA-009 | Must | Partial (rework on replace) | UT-RA-006 | FT-RA-004 | ST-05 | Partial | Need awaiting_arrival |
| RA-010 | Must | Not Started | Pending | FT-RA-005 | ST-05 | Not Started | ait_upload perm stub only |
| RA-011 | Must | Not Started (process) | N/A | FT-RA-005 | ST-05 | Not Started | Field procedure |
| RA-012 | Must | Not Started | UT-RA-007/008 | FT-RA-006/007 | ST-05/06 | Not Started | |
| RA-013 | Must | Not Started | UT-RA-008 | FT-RA-007 | ST-06 | Not Started | |
| RA-014 | Must | Not Started | UT-RA-007 | FT-RA-006 | ST-05 | Not Started | |
| RA-015 | Must | Not Started | UT-RA-009 | FT-RA-* | ST-05 | Not Started | |
| RA-016 | Should | Not Started | UT-NT-003 | FT-CG-005 | ST-05 | Not Started | |
| RA-017 | Should | Not Started | Pending | Pending | ST-15 | Not Started | GAP-04 |
| RA-018 | Should | Not Started | Pending | Pending | N/A | Not Started | |
| RA-019 | Should | Not Started | Pending | Pending | N/A | Not Started | |
| RA-020 | Could | Not Started | N/A | N/A | N/A | Not Started | GAP-07 |

---

## Matrix — Inspection / IE (IE)

| REQ | Pri | Impl (baseline) | UT | FT | ST | Conf | Notes |
|-----|-----|-----------------|----|----|----|------|-------|
| IE-001 | Must | Partial (rework exists) | UT-IE-001 | FT-IE-001 | ST-05 | Partial | Add awaiting + reception_date |
| IE-002 | Must | Partial | UT-IE-001 | FT-IE-001 | ST-05 | Partial | |
| IE-003 | Must | Partial (PD assign exists for returned units) | UT-IE-002 | FT-IE-002 | ST-05 | Partial | Assign IE role specifically |
| IE-004 | Must | Partial (inspect queue) | UT-IE-003 | FT-IE-002 | ST-05 | Partial | |
| IE-005 | Must | Partial (repairable outcome) | UT-IE-004 | FT-IE-003 | ST-05 | Partial | Sub-status naming |
| IE-006 | Must | Implemented (OEM claim) | UT-IE-005 | FT-IE-004 | ST-07 | Partial | Needs IE-driven path Verified |
| IE-007 | Must | Partial (IM discard; no IE recommend gate) | UT-IE-006/007 | FT-IE-005/006 | ST-08/12 | Partial | Segregation gap |
| IE-008 | Must | Not Started (UI badge) | UT-IE-007 | FT-IE-005 | ST-08 | Not Started | Backend scrap exists |
| IE-009 | Must | Partial | UT-IE-008 | FT-IE-003/007 | ST-05 | Partial | PD verify gate |
| IE-010 | Must | Partial | UT-IE-008/009 | FT-IE-003/007 | ST-05 | Partial | |
| IE-011 | Must | Not Started (explicit terminal helper) | UT-IE-010 | FT-CG-* | ST-09 | Not Started | |
| IE-012 | Must | Not Started | Pending | FT-IE-* | ST-05 | Not Started | |
| IE-013 | Should | Implemented (reusable) | N/A | Pending | N/A | Partial | |
| IE-014 | Should | Not Started | N/A | N/A | ST-16 | Not Started | GAP-08 |
| IE-015 | Could | Not Started | N/A | N/A | N/A | Not Started | GAP-11 |

---

## Matrix — Roles / notifications / NR

| REQ | Pri | Impl (baseline) | UT | FT | ST | Conf | Notes |
|-----|-----|-----------------|----|----|----|------|-------|
| RL-001 | Must | Implemented (auth seed) | UT-RL-001 | N/A | N/A | Partial | Update role tests for 8 roles |
| RL-002 | Must | Partial (perms stubbed; endpoints missing) | UT-RL-002 | FT-* | ST-05 | Partial | |
| RL-003 | Must | Implemented | UT-RL-004 | N/A | N/A | Partial | |
| RL-004 | Must | Not Started (MHD event matrix) | UT-NT-001 | ST-14 | ST-14 | Not Started | |
| RL-005 | Must | Partial (history UI; no Discarded chip) | N/A | FT-RA-008 | ST-14 | Partial | |
| NR-001 | Must | Implemented | UT-OR-003 | FT-OR-003 | ST-01/13 | Partial | |
| NR-002 | Must | Implemented | N/A | FT-OR-007 | N/A | Partial | Surface on OR |
| NR-003 | Must | Implemented | Pending | Pending | ST-13 | Partial | |
| NR-004 | Must | Not Started | All | All | All | Not Started | No MHD pytest suite yet |
| NR-005 | Must | Not Started | — | — | — | Not Started | Sign-off gate |

---

## Summary dashboard (update each review)

| Priority | Total | Satisfied | Accepted Deviation | NCR Open | Remaining |
|----------|-------|-----------|--------------------|----------|-----------|
| Must | 57 | 0 | 0 | 0 | 57 |
| Should | 8 | 0 | 0 | 0 | 8 |
| Could | 2 | 0 | 0 | 0 | 2 |

**Baseline verdict (2026-11-07):** Spec pack created; implementation **not conformant** for release. Foundations (CaseStatus, soft fix, FaultType, roles stubs, rework/warranty) are Partial anchors only. User decision required on GAP-01…GAP-12 before P5 freeze (see § below).

---

## Open decisions for user (non-conformance / scope)

Confirm before treating Should/Could as Must:

1. **NFF:** Add `no_fault_found` to `OnsiteOutcome` **or** modal-only mapping to `ResolutionType.no_fault_found`?  
2. **Spelling:** “Occurrence” vs mandated “Occurance”?  
3. **GAP-01…GAP-12:** Which are Must for v1 vs Accepted Deviation / backlog?  
4. **Close caveat (IE-014):** Allow Track A close if faulty never returned?  
5. **Demo users:** Treat seed script accounts as official ST actors?

Record answers in NCR/ADR log ([07](./07-non-conformance-and-verification-loop.md)) and refresh this Matrix.
