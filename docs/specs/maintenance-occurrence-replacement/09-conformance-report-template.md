# 09 — Conformance Report Template

**Copy this file** to `reports/CR-MHD-YYYYMMDD.md` when requesting feature / release sign-off.  
**Linked evidence:** Conformance Matrix (`06`) + latest Test Report (`08` / `TR-MHD-*`) + closed or waived NCRs (`07`).

---

## Document control

| Field | Value |
|-------|-------|
| Report ID | CR-MHD-________ |
| Feature | PLCM Maintenance — Occurrence Report + Dual-Track Replacement / Inspection |
| Source diagram | `docs/diagrams/MHD.drawio` |
| Spec pack | `docs/specs/maintenance-occurrence-replacement/` |
| Build / commit / tag | |
| Matrix snapshot date | |
| Test Report ID(s) | TR-MHD-________ |
| Prepared by | |
| Date | |

---

## 1. Conformance statement

The undersigned declare that the implementation of the MHD workflow:

1. Was developed against [01-functional-specification.md](./01-functional-specification.md).  
2. Was traced via [02-requirements-catalog.md](./02-requirements-catalog.md).  
3. Was verified with Unit, Functional, and System tests per docs 03–05.  
4. Has a completed [06-conformance-matrix.md](./06-conformance-matrix.md) for this build.  
5. Has all **Must** requirements in status **Satisfied** or **Accepted Deviation** (with user signature).  
6. Has no open **Blocker/Major** NCRs without user decision.

**Verdict:** ☐ CONFORMANT ☐ CONFORMANT WITH DEVIATIONS ☐ NOT CONFORMANT  

---

## 2. Requirements summary

| Priority | Total | Satisfied | Accepted Deviation | NCR Open | Not Satisfied |
|----------|-------|-----------|--------------------|----------|---------------|
| Must | | | | | |
| Should | | | | | |
| Could | | | | | |

Attach Matrix export or confirm Matrix file updated to this build.

---

## 3. Test evidence summary

| Level | Report | Result |
|-------|--------|--------|
| Unit | TR-… | Pass / Fail |
| Functional | TR-… | Pass / Fail |
| System | TR-… | Pass / Fail |

Outstanding Failures: ☐ None ☐ Listed below  

| Test-ID | REQ | NCR | Disposition |
|---------|-----|-----|-------------|
| | | | Fixed / Waived / Open |

---

## 4. Accepted deviations (must list all)

| Deviation ID | REQ | Description | Residual risk | User signed |
|--------------|-----|-------------|---------------|-------------|
| | | | | Yes / No |

If none: ☐ No accepted deviations  

---

## 5. Non-regression confirmation

| Path | OK? |
|------|-----|
| Soft fix / resolve_soft_fixed | ☐ |
| Investigation tree | ☐ |
| IM returned-unit rework | ☐ |
| OEM warranty claims | ☐ |
| Delivery-confirm close (when dual-track N/A) | ☐ |
| CaseStatus spine unchanged | ☐ |

---

## 6. Open backlog (non-blocking)

| GAP / Could REQ | Planned release | Notes |
|-----------------|-----------------|-------|
| | | |

---

## 7. Sign-off (user in the loop)

| Role | Name | Signature | Date | Decision |
|------|------|-----------|------|----------|
| Engineering Lead | | | | ☐ Ready |
| QA Lead | | | | ☐ Tests OK |
| Product Owner / User | | | | ☐ Approve ☐ Approve with deviations ☐ Reject |

**Reject reasons (if any):**  

**Conditions for Approve with deviations:**  

---

## 8. Post-approval

- [ ] Tag release / merge feature flag default-on (as agreed)  
- [ ] Archive TR + CR under `docs/specs/maintenance-occurrence-replacement/reports/`  
- [ ] Update `docs/diagrams/README.md` progress note if needed  
- [ ] Schedule Should/Could backlog items  

**Distribution:** Engineering, QA, Product Owner, Operations (IM/PD stakeholders as needed).
