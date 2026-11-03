# 07 — Verification Loop & Report Templates

This document defines the **mandatory loop** until implementation, tests, and conformance are all OK.

---

## 1. Verification loop algorithm

```
INPUT:  Requirements baseline (00), FSD (01), phases (02), tests (03–05), matrix (06)
OUTPUT: Signed Conformance Report + Test Reports with RELEASE_OK = true

iteration = 0
WHILE true:
  iteration += 1
  SELECT next incomplete phase (P0…P5) OR defect fixes from prior CONF-GAP

  IMPLEMENT changes for selected REQs
  RUN Unit tests covering those REQs        → Unit Test Report (iteration)
  RUN Functional tests                      → Functional Test Report (iteration)
  IF phase ≥ P2 and dual-track touched:
    RUN applicable System tests             → System Test Report (iteration)

  UPDATE Conformance Matrix (06) cells
  GENERATE Conformance Report (iteration)

  IF RELEASE_OK:          # see matrix § Release gate
    BREAK  # success
  ELSE:
    OPEN / UPDATE defects for each Must CONF-GAP
    MAP each defect → REQ-ID + failed UT/FT/ST
    CONTINUE loop  # do not declare done
```

### Loop exit rules

| Condition | Action |
|-----------|--------|
| Must CONF-GAP > 0 | **Continue loop** — no release |
| Must tests Fail | **Continue loop** |
| Reports missing / incomplete | **Continue loop** |
| Only Should/Could gaps | May exit with **WAIVED** + signed waiver |
| All Must CONF-OK + reports PASS | **Exit** — RELEASE_OK |

### Anti-patterns (forbidden)

- Marking CONF-OK without attached test evidence IDs.  
- Skipping system tests for Track A/B Must REQs.  
- Closing the loop while roll-up Must N/S or CONF-GAP remain.  
- Changing REQ text in matrix without bumping baseline version in `00`.

---

## 2. Folder layout for evidence

```
docs/specs/maintenance-occurrence-replacement/
  reports/
    iteration-NN/
      unit-test-report.md
      functional-test-report.md
      system-test-report.md
      conformance-report.md
      defects.md
```

Create `reports/` on first iteration.

---

## 3. Unit Test Report template

```markdown
# Unit Test Report — Iteration NN

- Date:
- Build / commit:
- Phase under test:
- Executor:
- Environment:

## Summary
| Total | Pass | Fail | Skip |
|------:|-----:|-----:|-----:|
|       |      |      |      |

## Results by ID
| UT ID | Result | REQ | Notes / log |
|-------|--------|-----|-------------|
| UT-OR-001 | Pass/Fail | REQ-OR-002 | |

## Failed items → defects
| UT ID | Defect ID | REQ | Root cause | Fix owner |
|-------|-----------|-----|------------|-----------|

## Verdict
PASS | FAIL
```

---

## 4. Functional Test Report template

```markdown
# Functional Test Report — Iteration NN

- Date / commit / phase / executor / env:

## Summary
| Total | Pass | Fail | Blocked |
|------:|-----:|-----:|--------:|
|       |      |      |         |

## Results by ID
| FT ID | Result | REQ | Evidence (API log / screenshot path) |
|-------|--------|-----|--------------------------------------|

## Failed / blocked → defects
| FT ID | Defect ID | REQ | Notes |

## Verdict
PASS | FAIL
```

---

## 5. System Test Report template

```markdown
# System Test Report — Iteration NN

- Date / commit / phase / executor / env (staging URL):

## Scenario results
| ST ID | Result | Linked REQs | Evidence |
|-------|--------|-------------|----------|
| ST-01 | | | |
| ST-02 | | | |
| ST-03 | | | |
| ST-04 | | | |
| ST-05 | | | |
| ST-06 | | | |
| ST-07 | | | |
| ST-08 | | | |
| ST-09 | | | |

## Notifications / badges checklist (ST-07)
| Event / badge | Observed | OK? |
|---------------|----------|-----|
| RED on ship | | |
| RED cleared on approve | | |
| Replaced badge | | |
| Discarded badge | | |

## Verdict
PASS | FAIL
```

---

## 6. Conformance Report template

```markdown
# Conformance Report — Iteration NN

- Baseline version: 1.0
- Matrix version:
- Build / commit:
- Reports attached: Unit / Functional / System (paths)

## Roll-up
| Priority | Total | CONF-OK | CONF-GAP | WAIVED | N/S |
|----------|------:|--------:|---------:|-------:|----:|
| M | 52 | | | | |
| S | 12 | | | | |
| C | 4 | | | | |

## Must CONF-GAP list (must be empty for RELEASE_OK)
| REQ | Impl | Failed tests | Defect | Planned fix |
|-----|------|--------------|--------|-------------|

## Waivers (Should/Could only unless emergency)
| REQ | Reason | Approver | Date |

## RELEASE_OK
YES | NO

## Sign-off (only if RELEASE_OK = YES)
| Role | Name | Date | Signature |
|------|------|------|-----------|
| Dev lead | | | |
| QA | | | |
| Product / PD delegate | | | |
```

---

## 7. Defect log template (`defects.md`)

```markdown
# Defects — Iteration NN

| Defect ID | Severity | REQ | Failed test | Description | Status | Fixed in iteration |
|-----------|----------|-----|-------------|-------------|--------|--------------------|
| DEF-001 | High | REQ-TA-012 | FT-TA-010 | AIT reject did not keep same ME | Open | |
```

Severity: **High** = Must REQ blocked; **Medium** = Should; **Low** = Could/cosmetic.

---

## 8. Iteration checklist (copy per loop)

- [ ] Scope REQs selected for this iteration  
- [ ] Implementation complete for those REQs  
- [ ] Unit tests run → report filed  
- [ ] Functional tests run → report filed  
- [ ] System tests run if applicable → report filed  
- [ ] Matrix (06) updated  
- [ ] Conformance report generated  
- [ ] Defects filed for every Must CONF-GAP  
- [ ] `RELEASE_OK` evaluated  
- [ ] If NO → schedule next iteration; if YES → sign-off  

---

## 9. Relationship to implementation phases

| After phase | Minimum tests before next phase |
|-------------|----------------------------------|
| P0 | UT-NR-*, UT-ROLE-* smoke |
| P1 | All FT-OR-*, UT-OR-* |
| P2 | FT-TA-001..006, ST-01 |
| P3 | FT-TA-007..010, ST-02 |
| P4 | FT-TB-*, ST-04..06 |
| P5 | Full ST-01..09 + full matrix Must CONF-OK |

Skipping ahead without phase exit criteria is a **CONF-GAP** on process (treat as High defect DEF-PROC-*).
