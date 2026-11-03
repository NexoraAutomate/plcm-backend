# Maintenance Occurrence Report & Dual-Track Workflow — Specification Pack

**Product:** PLCM  
**Scope:** Augment existing maintenance (Occurrence Report, ME replacement Track A, IE inspection Track B)  
**Source diagram:** [`docs/diagrams/PLCM_Maintenance_Occurrence_Replacement_Workflow.drawio`](../../diagrams/PLCM_Maintenance_Occurrence_Replacement_Workflow.drawio)  
**Principle:** Do **not** regress soft-fix, tree investigation, IM rework, OEM warranty, or delivery-close.

---

## Document set

| # | Document | Purpose |
|---|----------|---------|
| 00 | [Requirements Baseline](./00-requirements-baseline.md) | Numbered REQ-* catalogue (single source of truth) |
| 01 | [Functional Specification](./01-functional-specification.md) | Behaviour, actors, data, API/UI contracts |
| 02 | [Implementation Phases](./02-implementation-phases.md) | Step-by-step build order (P0→P5) |
| 03 | [Unit Test Specification](./03-unit-test-specification.md) | UT-* cases |
| 04 | [Functional Test Specification](./04-functional-test-specification.md) | FT-* cases |
| 05 | [System Test Specification](./05-system-test-specification.md) | ST-* end-to-end scenarios |
| 06 | [Conformance Matrix](./06-conformance-matrix.md) | REQ ↔ impl ↔ tests; pass/fail tracking |
| 07 | [Verification Loop & Reports](./07-verification-loop-and-reports.md) | Iterate until all REQ + reports OK |

---

## Verification loop (summary)

```
Implement phase → Unit tests → Functional tests → System tests
       ↓
Update Conformance Matrix
       ↓
All REQ Satisfied AND UT/FT/ST reports PASS AND Conformance report PASS?
       ├─ YES → Release gate OK (sign-off)
       └─ NO  → Open defects / gaps → re-implement → re-test (loop)
```

Details and report templates: [07-verification-loop-and-reports.md](./07-verification-loop-and-reports.md).

---

## Status legend (used in matrix & reports)

| Code | Meaning |
|------|---------|
| `N/S` | Not started |
| `PARTIAL` | Partially implemented / covered |
| `IMPL` | Implemented (code present) |
| `UT-PASS` / `UT-FAIL` | Unit evidence |
| `FT-PASS` / `FT-FAIL` | Functional evidence |
| `ST-PASS` / `ST-FAIL` | System evidence |
| `CONF-OK` | Requirement fully conformant (impl + required tests pass) |
| `CONF-GAP` | Gap: missing impl, missing test, or failing test |

**Release rule:** Zero `CONF-GAP` for Must (M) requirements; Should (S) tracked with waiver if needed.
