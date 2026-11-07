# 07 — Non-Conformance & Verification Loop

**Purpose:** Keep the user / Product Owner in the loop whenever a requirement is not met, a test fails, or a gap must be accepted — until all Must REQs are Satisfied or waived.

---

## 1. Definitions

| Term | Meaning |
|------|---------|
| **NCR** | Non-Conformance Report — formal record of unmet REQ or failed test |
| **Fix** | Engineering change + re-test |
| **Defer** | Move to later phase; still open for release if Must → usually not allowed without waiver |
| **Accepted Deviation** | User-signed waiver; residual risk documented; Matrix status Accepted Deviation |
| **Descope** | REQ removed/changed; catalog updated with user approval |

---

## 2. When to open an NCR

Open an NCR if any of:

1. UT / FT / ST **Fail** against a REQ.  
2. Implementation **Partial** at phase exit with no plan in the same sprint.  
3. Spec ambiguity discovered (e.g. NFF enum vs modal).  
4. Gap fill (GAP-xx) conflicts with Must behavior.  
5. Non-regression failure (soft fix, warranty, delivery close).  
6. Conformance Matrix Must row cannot reach Verified by planned date.

---

## 3. NCR form (copy per incident)

```text
NCR-ID:       NCR-MHD-YYYYMMDD-##
Date raised:  
Raised by:    
REQ-ID(s):    
Test-ID(s):   UT-/FT-/ST- (if any)
Severity:     Blocker | Major | Minor | Observation
Phase:        P0…P6

Summary:
<one sentence>

Expected (per FSD/REQ):
Actual:
Evidence:     (logs, screenshots, case IDs)

Impact if unresolved:
Options for user:
  [ ] A — Fix now (target date: ____)
  [ ] B — Accepted Deviation (residual risk: ____)
  [ ] C — Descope / change REQ (new wording: ____)
  [ ] D — Defer to phase ____ (only if not Must for this release)

User decision:     A / B / C / D
User name / date:
Engineering action:
Re-test IDs:
Matrix update:     NCR Open → Verified / Accepted Deviation / Descope
Closed date:
```

Store NCRs under `docs/specs/maintenance-occurrence-replacement/ncr/` (create when first NCR opens) as `NCR-MHD-….md`.

---

## 4. Verification loop (mandatory)

```
                ┌──────────────────────────┐
                │ Implement phase Pn       │
                └────────────┬─────────────┘
                             ▼
                ┌──────────────────────────┐
                │ Run UT → FT (→ ST at P6) │
                └────────────┬─────────────┘
                             ▼
                     All Pass for Must?
                      │            │
                     Yes           No
                      │            │
                      ▼            ▼
              Update Matrix    Open NCR
              → Verified       Notify user (chat/email/review)
                      │            │
                      │            ▼
                      │      User chooses A/B/C/D
                      │            │
                      │     ┌──────┴──────┐
                      │   Fix          Waiver/Descope
                      │     │              │
                      │     ▼              ▼
                      │  Re-test     Matrix = Accepted Deviation
                      │     │        or REQ updated
                      │     └──────┐
                      ▼            ▼
              ┌──────────────────────────┐
              │ Phase exit / next phase  │
              └──────────────────────────┘
                             ▼
              After P5: full ST suite
                             ▼
              Test Report (08) + Conformance Report (09)
                             ▼
              User sign-off only if Must = Satisfied|Accepted Deviation
```

**Hard rule:** Do not mark Conformance Report **Approved** while any Must REQ is Not Started, Partial, Implemented-only, NCR Open, or Fail without user decision.

---

## 5. Communication to user (keep in the loop)

For every NCR Blocker/Major, notify the user with:

1. REQ-ID and plain-language impact.  
2. Options A–D with recommendation.  
3. Effect on dual-track close gate / inventory / badges if relevant.  
4. Ask for explicit decision before continuing dependent work.

Minor/Observation may batch in weekly review, but still logged.

---

## 6. Phase exit checklist (user-visible)

| Phase | Exit question to user |
|-------|----------------------|
| P0 | Roles/permissions OK to build on? |
| P1 | Occurrence Report fields & NFF behavior accepted? |
| P2 | Dual-track board & request model accepted? |
| P3 | AIT loop + RED/Replaced behavior accepted? |
| P4 | IE discard segregation + repair gate accepted? |
| P5 | Close gate + GAP decisions frozen? |
| P6 | Test + Conformance reports Approved? |

---

## 7. Initial NCRs / decisions (baseline 2026-11-07)

Raise with user as **scope decisions** (pre-implementation):

| Draft ID | Topic | Recommended |
|----------|-------|-------------|
| DEC-001 | NFF as OnsiteOutcome enum vs modal-only | Add enum value + modal (OR-004/006) |
| DEC-002 | Occurrence spelling | Use “Occurrence Report” |
| DEC-003 | GAP Must set for v1 | Must: GAP-01,03,09; Should: 02,04,05,06,08; Could: 07,10,11,12 |
| DEC-004 | Close without faulty return | Allowed with caveat flag only if PD confirms (IE-014) |

Until DEC-* answered, treat related Should items as **not blocking** P1 start; Must GAPs block P5 freeze.
