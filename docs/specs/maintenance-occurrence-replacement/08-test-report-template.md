# 08 — Test Report Template

**Copy this file** to `reports/TR-MHD-YYYYMMDD.md` (or attach in PR) for each formal test cycle.  
**Do not** mark Conformance Report Approved until this report’s Must failures are zero or waived.

---

## Document control

| Field | Value |
|-------|-------|
| Report ID | TR-MHD-________ |
| Feature | Occurrence Report + Dual-Track (MHD) |
| Build / commit | |
| Environment | |
| Spec pack version / date | |
| Test level(s) | ☐ Unit ☐ Functional ☐ System |
| Cycle | ☐ Phase exit ☐ Full regression ☐ Retest after NCR |
| Executed by | |
| Date | |
| Reviewed by | |

---

## 1. Summary

| Level | Planned | Executed | Pass | Fail | Blocked | Skip |
|-------|---------|----------|------|------|---------|------|
| Unit (UT) | | | | | | |
| Functional (FT) | | | | | | |
| System (ST) | | | | | | |
| **Total** | | | | | | |

**Overall result:** ☐ Pass ☐ Pass with deviations ☐ Fail  

**Must REQ coverage this cycle:** __ / __ Verified  

---

## 2. Unit results

| UT-ID | REQ | Result | Evidence / notes |
|-------|-----|--------|------------------|
| | | Pass / Fail / Blocked / Skip | |

Command log (optional):

```text
pytest …
```

---

## 3. Functional results

| FT-ID | REQ | Result | Evidence |
|-------|-----|--------|----------|
| | | Pass / Fail / Blocked / Skip | case id / screenshot |

---

## 4. System results

| ST-ID | REQ | Result | Evidence |
|-------|-----|--------|----------|
| ST-01 | | | |
| ST-02 | | | |
| ST-03 | | | |
| ST-04 | | | |
| ST-05 | | | |
| ST-06 | | | |
| ST-07 | | | |
| ST-08 | | | |
| ST-09 | | | |
| ST-10 | | | |
| ST-11 | | | |
| ST-12 | | | |
| ST-13 | | | |
| ST-14 | | | |
| ST-15 | | | |
| ST-16 | | | |

---

## 5. Defects / NCRs raised

| NCR-ID | Severity | REQ | Summary | User decision pending? |
|--------|----------|-----|---------|------------------------|
| | | | | Yes / No |

---

## 6. Non-regression notes

| Area | Result | Notes |
|------|--------|-------|
| Soft fix | | |
| Investigation tree | | |
| Returned unit rework | | |
| OEM warranty | | |
| Delivery close | | |

---

## 7. Recommendations

- ☐ Proceed to next phase  
- ☐ Retest after fixes (list NCR-IDs)  
- ☐ Escalate to user for Accepted Deviation  
- ☐ Ready for Conformance Report  

**QA signature:** _________________ Date: _______  
**Engineering acknowledgment:** _________________ Date: _______
