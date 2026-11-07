# Maintenance Occurrence Report + Dual-Track Replacement / Inspection

**Source diagram:** [`docs/diagrams/MHD.drawio`](../../diagrams/MHD.drawio) (pages 01–06)  
**Also mirrored as:** `docs/diagrams/PLCM_Maintenance_Occurrence_Replacement_Workflow.drawio`  
**Module:** PLCM Maintenance Augmentation (Occurrence Report + Track A Replacement / Track B Faulty Inspection)  
**Rule:** Augment only — do **not** replace soft-fix, tree investigation, IM rework queue, warranty claim, or delivery-close paths.

---

## Purpose of this pack

| Artifact | Use |
|----------|-----|
| Functional Specification | Step-by-step implementation of the MHD workflow |
| Requirements Catalog | Stable REQ-IDs for tracing |
| Unit / Functional / System tests | Verification at three levels |
| Conformance Matrix | Prove every requirement is implemented & tested |
| Non-conformance loop | Keep stakeholders in the loop until all REQs are Satisfied |
| Test & Conformance report templates | Formal sign-off evidence |

**Exit criteria for the feature:** Conformance Matrix = 100% Satisfied (or Accepted Deviation with signed waiver), Test Report = Pass, Conformance Report = Approved.

---

## Document index

| Seq | File | Description |
|-----|------|-------------|
| 00 | [README.md](./README.md) | This index + verification loop |
| 01 | [01-functional-specification.md](./01-functional-specification.md) | FSD + phased implementation steps |
| 02 | [02-requirements-catalog.md](./02-requirements-catalog.md) | REQ-MHD-xxx catalog |
| 03 | [03-unit-test-specification.md](./03-unit-test-specification.md) | Unit-level tests (UT) |
| 04 | [04-functional-test-specification.md](./04-functional-test-specification.md) | Functional / API & UI tests (FT) |
| 05 | [05-system-test-specification.md](./05-system-test-specification.md) | End-to-end system tests (ST) |
| 06 | [06-conformance-matrix.md](./06-conformance-matrix.md) | REQ ↔ Impl ↔ Test ↔ Status |
| 07 | [07-non-conformance-and-verification-loop.md](./07-non-conformance-and-verification-loop.md) | NCR process + user-in-loop |
| 08 | [08-test-report-template.md](./08-test-report-template.md) | Fill after each test cycle |
| 09 | [09-conformance-report-template.md](./09-conformance-report-template.md) | Formal conformance sign-off |

---

## Implementation phases (ship in order)

```
P0 Foundations     → roles ME/FSE/IE, permissions, CaseStatus preserved
P1 Occurrence      → Occurrence Report UI/API (page 02)
P2 Dual-track wire → Track A request + Track B awaiting arrival (page 03)
P3 Replacement/AIT → ME/PD/IM/FSE loop + badges/RED notify (page 04)
P4 Inspection/IE   → reception → IE disposition → repair/warranty/discard (page 05)
P5 Close & polish  → dual-track close gate, notifications matrix, gap fills (page 06)
P6 Verification    → UT → FT → ST → Conformance Matrix → Reports → Sign-off
```

Do **not** start P(n+1) until P(n) unit + functional tests for that phase are green, or an Accepted Deviation is recorded.

---

## Master logical flow

```
Case open (existing)
      ↓
Occurrence Report
      ↓
Outcome branch?
  ├─ Soft fix      → resolve soft_fixed (existing)
  ├─ NFF           → confirm close/resolve? Yes → NFF closed; No → note, stay open
  ├─ Inconclusive  → stay open
  └─ Fault identified
           ↓
     Dual track (parallel)
       Track A: Replacement Request → HM/PD assign ME + reserve → IM ISSUE
                → RED notify + Replaced badge → site AIT → PD Approve/Reject loop
                → patch_delivered
       Track B: awaiting_faulty_arrival → IM reception → PD assign IE
                → IE inspect → warranty | discard | repair → terminal
           ↓
     CASE CLOSE GATE
     Track A ait_approved/patch_delivered AND Track B terminal
     (or Soft/NFF early exit)
```

---

## Roles

| Code | Role | New? | Primary MHD duties |
|------|------|------|--------------------|
| FSE | Field Service Engineer | Wire | Occurrence Report officers; site replace with ME |
| ME | Maintenance Engineer | Wire | Replacement request advance, IM issue request, AIT upload, site integrate |
| PD | Project Director | Existing | Approve replacement, assign ME/IE, AIT & repair gates |
| HM | Hierarchy Manager | Existing | Assign ME; reserve replacement PN/S/N; mark case to ME |
| IM | Inventory Manager | Existing | Issue/receive/discard/restock; custody |
| IE | Inspection Engineer | Wire | Handover request, disposition, repair updates |
| Maintenance | Legacy | Existing | Notify target until ME seeded |

---

## Verification loop (keep user in the loop)

```
1. Implement phase Pn against REQ-MHD-* for that phase
2. Run UT → FT for Pn; update Conformance Matrix
3. If FAIL / Gap / Partial:
     a. Open NCR (see 07)
     b. Notify Product Owner / user with impact + options
     c. Decide: Fix | Defer (Accepted Deviation) | Descope
     d. Re-test affected REQ IDs
4. After P0–P5: run System Tests (05)
5. Fill Test Report (08) and Conformance Report (09)
6. Sign-off only when Matrix shows all Must REQs = Satisfied
   (or Accepted Deviation with user signature)
```

---

## Related code anchors (as-is baseline)

| Concept | Backend / Frontend anchor |
|---------|---------------------------|
| Onsite outcome API | `app/routers/maintenance_module.py` `onsite-outcome/` |
| Field service | `app/services/maintenance_field_service.py` |
| Enums | `app/models/base.py` (`CaseStatus`, `FaultType`, `OnsiteOutcome`, `ResolutionType`) |
| Returned unit | `create_returned_unit_rework` |
| Rework / discard / warranty | `app/services/item_rework_service.py`, OEM warranty routes |
| Roles / permissions | `app/domain/workflow_roles.py`, `workflow_permissions.py`, `auth.py` |
| UI onsite panel | `plcm-frontend/components/maintenance/field-service-panels.tsx` |
| Demo users | `scripts/seed_maintenance_demo_users.py` |

---

## Status legend (Conformance Matrix)

| Status | Meaning |
|--------|---------|
| **Not Started** | No implementation |
| **Partial** | Some code; REQ not fully met |
| **Implemented** | Code complete; tests pending or incomplete |
| **Verified** | UT+FT (and ST if required) Pass |
| **Satisfied** | Verified + Conformance Report accepted |
| **NCR Open** | Non-conformance raised; blocked for sign-off |
| **Accepted Deviation** | User-approved waiver; documented residual risk |
