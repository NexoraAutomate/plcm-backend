# 06 — Conformance Matrix

**Baseline version:** 1.0 (matches [00-requirements-baseline.md](./00-requirements-baseline.md))  
**Matrix version:** 1.0  
**Last updated:** _(set on each verification loop iteration)_  
**Build / commit:** _(SHA)_  

## How to use

1. After each phase or loop iteration, update **Impl**, **UT**, **FT**, **ST**, **Status**.  
2. **Status = CONF-OK** only if: Impl = Yes **and** all listed Must-level tests for that REQ are PASS (or N/A with justification).  
3. Any Must REQ with Status ≠ CONF-OK ⇒ overall **CONF-GAP** ⇒ continue verification loop ([07](./07-verification-loop-and-reports.md)).  
4. Do not delete rows; mark waived Should/Could with `WAIVED` + reason in Notes.

**Legend:** Impl Y/N/P · Test: Pass / Fail / N/S / N/A · Status: CONF-OK / CONF-GAP / WAIVED / N/S

---

## A. Non-regression

| REQ | Pri | Phase | Impl | UT | FT | ST | Status | Notes |
|-----|-----|-------|------|----|----|-----|--------|-------|
| REQ-NR-001 | M | P0 | | UT-NR-001 | | ST-08 | N/S | |
| REQ-NR-002 | M | P0/P1 | | UT-NR-002, UT-OR-007 | FT-NR-001, FT-OR-003 | ST-03 | N/S | |
| REQ-NR-003 | M | P0 | | | | ST-08 | N/S | |
| REQ-NR-004 | M | P0/P4 | | UT-NR-003 | FT-NR-002 | ST-06 | N/S | |
| REQ-NR-005 | M | P0/P5 | | | FT-NR-003 | ST-08 | N/S | |
| REQ-NR-006 | M | P0 | | | | ST-08 | N/S | |

---

## B. Roles

| REQ | Pri | Phase | Impl | UT | FT | ST | Status | Notes |
|-----|-----|-------|------|----|----|-----|--------|-------|
| REQ-ROLE-001 | M | P0 | | UT-ROLE-001,002 | FT-TA-001 | ST-01 | N/S | |
| REQ-ROLE-002 | M | P0 | | | FT-OR-001,007 | ST-01 | N/S | |
| REQ-ROLE-003 | M | P0 | | UT-ROLE-004 | FT-TB-003 | ST-04 | N/S | |
| REQ-ROLE-004 | M | P0 | | UT-ROLE-003 | FT-TA-002 | ST-01 | N/S | |
| REQ-ROLE-005 | M | P0 | | UT-ROLE-005 | FT-TA-004, FT-TB-001 | ST-01 | N/S | |
| REQ-ROLE-006 | S | P0 | | | | | N/S | |

---

## C. Occurrence Report

| REQ | Pri | Phase | Impl | UT | FT | ST | Status | Notes |
|-----|-----|-------|------|----|----|-----|--------|-------|
| REQ-OR-001 | M | P1 | | | FT-OR-001 | ST-01 | N/S | |
| REQ-OR-002 | M | P1 | | UT-OR-001 | FT-OR-002 | ST-01 | N/S | |
| REQ-OR-003 | M | P1 | | UT-OR-002 | FT-OR-002 | ST-01 | N/S | |
| REQ-OR-004 | M | P1 | | UT-OR-008..011 | FT-OR-003..007 | ST-03 | N/S | |
| REQ-OR-005 | M | P1 | | UT-OR-004,012 | FT-OR-007,009 | ST-01 | N/S | |
| REQ-OR-006 | M | P1 | | UT-OR-003 | FT-OR-003 | ST-03 | N/S | |
| REQ-OR-007 | M | P1 | | | FT-OR-006 | | N/S | |
| REQ-OR-008 | M | P1 | | UT-OR-005 | FT-OR-007,008 | ST-01 | N/S | |
| REQ-OR-009 | M | P1 | | UT-OR-006 | FT-OR-007 | ST-01 | N/S | |
| REQ-OR-010 | M | P1 | | UT-OR-008,009 | FT-OR-004,005 | ST-03 | N/S | |
| REQ-OR-011 | M | P1 | | UT-OR-007 | FT-OR-003 | ST-03 | N/S | |
| REQ-OR-012 | M | P1 | | UT-OR-010 | FT-OR-006 | | N/S | |
| REQ-OR-013 | M | P1 | | UT-OR-011 | FT-OR-007 | ST-01 | N/S | |
| REQ-OR-014 | S | P1 | | | | | N/S | |
| REQ-OR-015 | C | P1+ | | | | | N/S | |

---

## D. Track A

| REQ | Pri | Phase | Impl | UT | FT | ST | Status | Notes |
|-----|-----|-------|------|----|----|-----|--------|-------|
| REQ-TA-001 | M | P2 | | UT-TA-001 | FT-TA-001 | ST-01, ST-09 | N/S | |
| REQ-TA-002 | M | P2 | | | FT-TA-001 | ST-01 | N/S | |
| REQ-TA-003 | M | P2 | | UT-TA-002,004 | FT-TA-002,003 | ST-01 | N/S | |
| REQ-TA-004 | M | P2 | | UT-TA-005,006 | FT-TA-004,005 | ST-01 | N/S | |
| REQ-TA-005 | M | P2 | | UT-TA-005,007 | FT-TA-004 | ST-01 | N/S | |
| REQ-TA-006 | M | P2 | | UT-TA-009 | FT-TA-004 | ST-01, ST-07 | N/S | |
| REQ-TA-007 | M | P2 | | UT-TA-008 | FT-TA-006 | ST-01 | N/S | |
| REQ-TA-008 | M | P3 | | | FT-TA-007 | ST-02 | N/S | |
| REQ-TA-009 | M | P3 | | | | ST-02 | N/S | |
| REQ-TA-010 | M | P3 | | | FT-TA-008 | ST-02 | N/S | |
| REQ-TA-011 | M | P3 | | | FT-TA-009,010 | ST-02 | N/S | |
| REQ-TA-012 | M | P3 | | UT-TA-010 | FT-TA-010 | ST-02 | N/S | |
| REQ-TA-013 | M | P3 | | UT-TA-011 | FT-TA-009 | ST-02 | N/S | |
| REQ-TA-014 | M | P2 | | UT-TA-002,003 | FT-TA-011 | | N/S | |
| REQ-TA-015 | S | P3 | | UT-TA-013 | FT-TA-012 | | N/S | |
| REQ-TA-016 | S | P3 | | | | ST-02 | N/S | |
| REQ-TA-017 | S | P3 | | UT-TA-014 | | | N/S | |
| REQ-TA-018 | S | P3 | | | | | N/S | |
| REQ-TA-019 | C | P3+ | | | | | N/S | |

---

## E. Track B

| REQ | Pri | Phase | Impl | UT | FT | ST | Status | Notes |
|-----|-----|-------|------|----|----|-----|--------|-------|
| REQ-TB-001 | M | P4 | | UT-TB-001 | FT-TB-001 | ST-04 | N/S | |
| REQ-TB-002 | M | P4 | | UT-TB-002 | FT-TB-002 | ST-04 | N/S | |
| REQ-TB-003 | M | P4 | | UT-TB-003 | FT-TB-003 | ST-04 | N/S | |
| REQ-TB-004 | M | P4 | | UT-TB-003 | FT-TB-003 | ST-04 | N/S | |
| REQ-TB-005 | M | P4 | | UT-TB-004 | FT-TB-004 | ST-06 | N/S | |
| REQ-TB-006 | M | P4 | | UT-TB-005,006 | FT-TB-005 | ST-05 | N/S | |
| REQ-TB-007 | M | P4 | | UT-TB-008 | FT-TB-007 | ST-04 | N/S | |
| REQ-TB-008 | M | P4 | | UT-TB-009,010 | FT-TB-007,008 | ST-04 | N/S | |
| REQ-TB-009 | M | P4 | | UT-TB-005, UT-ROLE-004 | FT-TB-005,006 | ST-05 | N/S | |
| REQ-TB-010 | S | P4 | | | | | N/S | |
| REQ-TB-011 | S | P4 | | | | | N/S | |
| REQ-TB-012 | C | P4+ | | | | | N/S | |

---

## F. Close / badges / notify / UX

| REQ | Pri | Phase | Impl | UT | FT | ST | Status | Notes |
|-----|-----|-------|------|----|----|-----|--------|-------|
| REQ-CL-001 | M | P5 | | UT-CL-001..004 | FT-CL-001..004 | ST-03,04,09 | N/S | |
| REQ-CL-002 | M | P2/P3/P5 | | UT-TA-012 | FT-TA-009 | ST-02,07 | N/S | |
| REQ-BDG-001 | M | P2 | | UT-TA-007 | FT-TA-004 | ST-01,07 | N/S | |
| REQ-BDG-002 | M | P4 | | UT-TB-006,007 | FT-TB-005 | ST-05,07 | N/S | |
| REQ-NTF-001 | M | P5 | | UT-TA-009 | | ST-07 | N/S | |
| REQ-UX-001 | M | P2/P4 | | | FT-TA-011, FT-TB-009 | ST-01 | N/S | |
| REQ-UX-002 | S | P5 | | | | | N/S | |

---

## Summary roll-up

| Priority | Total | CONF-OK | CONF-GAP | WAIVED | N/S |
|----------|------:|--------:|---------:|-------:|----:|
| M | 52 | 0 | 0 | 0 | 52 |
| S | 12 | 0 | 0 | 0 | 12 |
| C | 4 | 0 | 0 | 0 | 4 |
| **All** | **68** | **0** | **0** | **0** | **68** |

### Release gate

```
RELEASE_OK =
  (count Must CONF-OK == 52)
  AND (count Must CONF-GAP == 0)
  AND Unit Test Report = PASS
  AND Functional Test Report = PASS
  AND System Test Report = PASS
  AND Conformance Report = PASS
```

If `RELEASE_OK` is false → **loop** per [07-verification-loop-and-reports.md](./07-verification-loop-and-reports.md).
