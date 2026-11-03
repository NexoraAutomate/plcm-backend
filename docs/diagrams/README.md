# PLCM Process Flow Diagrams

## Files

| File | Description |
|------|-------------|
| [Hierarchy_Inventory_Management_Workflow.drawio](./Hierarchy_Inventory_Management_Workflow.drawio) | Hierarchy & inventory management (multi-page) |
| [Maintenance_Faulty_Item_Return_Repair_Lifecycle.drawio](./Maintenance_Faulty_Item_Return_Repair_Lifecycle.drawio) | Generic faulty-item return, repair & acceptance lifecycle (multi-page) |
| [PLCM_Maintenance_Occurrence_Replacement_Workflow.drawio](./PLCM_Maintenance_Occurrence_Replacement_Workflow.drawio) | PLCM Occurrence Report + parallel ME replacement / IE inspection (augments existing maintenance) |

---

## Hierarchy & Inventory Management

### Pages

1. **01 Overview** — End-to-end phases, status spine, return paths, audit banner  
2. **02 Config & Project** — Hierarchy configuration (§1) + project approval & generate (§2)  
3. **03 Reservation & Shortage** — Availability decision, FCFS shortage loop, 30d+7d expiry  
4. **04 Issue & Install** — Issue to developer (§4) + install/test/verify (§5)  
5. **05 Defect Rework & Recall** — Defect loop (§6) + project cancel recall  
6. **06 Audit & Roles** — Audit fields (§7) + role responsibilities  

---

## Maintenance — Faulty Item Return, Repair & Acceptance

Generic product-agnostic maintenance lifecycle derived from `docs/VSAT_Faulty_Item_Return_Repair_LCS_Procedure.docx` (and accompanying process infographic). VSAT-specific examples are generalized to system / subsystem / LRU terminology.

### Pages

1. **01 Overview** — Summary chevron (Receive → Inspect → Diagnose → Repair/Replace → Test → Dispatch), master 12-step flow with decision gates, quality gates G1–G5, release outcomes  
2. **02 Field Return & Receipt** — RMA / field report, receipt & quarantine, incoming inspection, safety hold, G1  
3. **03 Triage & Diagnosis** — Fault reproduction, fault classification, root-cause analysis, OEM escalation, generic test points, G2  
4. **04 Repair vs Replace** — Decision matrix (feasibility / availability / economics / reliability / config), repair controls, G3  
5. **05 Verification & QA Release** — Post-repair verification, system acceptance, G4/G5, outgoing inspection & dispatch  
6. **06 Status, Records & LCS** — Work-order status codes, serviceability statuses, minimum records, equipment, fleet KPIs, roles, SLA metrics, implementation checklist  

### Source mapping

| Diagram concept | SOP reference |
|-----------------|---------------|
| 12-step master flow | §4 End-to-End Flow Diagram |
| Roles | §3 Roles and Responsibilities |
| Quality gates G1–G5 | §7 Quality Gates and Nonconformance Control |
| Repair vs replace matrix | §6.5 Repair-versus-Replace Decision |
| Status codes (REC…DISP, NFF, BER) | Appendix A |
| Records & forms | §8 Minimum Records and Forms |
| Life-cycle / fleet controls | §10 Life-Cycle Support and Fleet-Level Controls |
| SLA metrics | §11 Suggested Service-Level Targets |

---

## PLCM — Occurrence Report + Parallel Replacement / Inspection

Product-specific augmentation of the live PLCM maintenance module. **Does not replace** soft-fix, tree investigation, IM rework, warranty claims, or delivery-close. Adds Occurrence Report UX and a dual track after fault confirmation: immediate same-spec replacement (ME/PD/IM/FSE) in parallel with faulty return inspection (IM/PD/IE).

### Pages

1. **01 Overview & Principles** — Augment-only rules, role map (FSE/ME/PD/IM/IE), master chevron, existing vs new mapping  
2. **02 Occurrence Report** — Form fields (occurrence date ≠ recorded date, named attachments, FSE officers dialog), Outcome + Fault Type list, Soft/NFF/Inconclusive/Fault branches  
3. **03 Dual-Track Split** — Track A immediate replacement vs Track B faulty return; case close gate  
4. **04 Replacement & AIT (ME)** — Role swimlanes ME/PD/IM/FSE, AIT approve/reject loop, Track A sub-statuses, gap fills  
5. **05 Faulty Inspection (IE)** — Reception → IE assign → inspection → warranty / discard / repair → PD verify → restock  
6. **06 Statuses, Badges & Gaps** — CaseStatus spine preserved; sub-statuses; Replaced/Discarded/RED notify; notification matrix; missing-functionality backlog  

### Mapping to existing code

| Diagram concept | Existing PLCM anchor |
|-----------------|----------------------|
| Occurrence Report | UI “Onsite visit outcome” / `onsite-outcome/` API |
| Fault Type list | `FaultType` enum (already includes Electrical…Other) |
| Soft fix | `soft_fix` + `resolve_soft_fixed` |
| Immediate replace | Extends `resolution_type=replaced` + stock issue |
| Faulty return | Extends `create_returned_unit_rework` / IM inspect queue |
| Warranty | Existing OEM claim statuses |
| Discard | Existing discard/trash; **new** Discarded badge display |
| Roles PD/IM | Existing workflow roles; ME/FSE/IE to seed |

### Specification & conformance pack

Step-by-step FSD, unit/functional/system tests, conformance matrix, and verification loop:

[`docs/specs/maintenance-occurrence-replacement/`](../specs/maintenance-occurrence-replacement/README.md)

---

## Open & edit

### Option A — diagrams.net (free, recommended)

1. Open [https://app.diagrams.net](https://app.diagrams.net)  
2. **File → Open from → Device** → select the `.drawio` file  
3. Switch pages using the tabs at the bottom  

### Option B — VS Code / Cursor

Install the **Draw.io Integration** extension, then open the `.drawio` file.

### Export to Microsoft Visio (`.vsdx`)

1. Open the file in [diagrams.net](https://app.diagrams.net)  
2. **File → Export as → VSDX…**  
3. Save and open in Microsoft Visio  

> Native Visio is not required on the build machine; the maintainable source is the `.drawio` file.
