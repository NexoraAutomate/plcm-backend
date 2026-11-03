# 02 — Implementation Phases (Step-by-Step)

Implement in order. **Do not skip phase exit criteria.** After each phase: run that phase’s UT/FT set, update [06-conformance-matrix.md](./06-conformance-matrix.md), enter verification loop for failed REQs.

---

## Phase P0 — Foundations (roles, schema, non-regression)

**Goal:** Additive schema + roles; zero behaviour change for existing onsite until P1 switches UI.

| Step | Work | REQ covered |
|------|------|-------------|
| P0.1 | Add/seed roles ME, FSE, IE; map permissions (additive) | ROLE-001..005 |
| P0.2 | DB: `occurrence_date`; attachment name; officers JSON/table; outcome `no_fault_found` | OR-002..004, OR-008..009 |
| P0.3 | DB: `ReplacementRequest` + status enum; link to case/entity | TA-002, TA-014 |
| P0.4 | Extend returned-unit: `awaiting_faulty_arrival`, `reception_date`, IE assignment fields | TB-001..004 |
| P0.5 | Discarded flag/badge field on inventory if missing | BDG-002 |
| P0.6 | Regression: existing soft_fix, warranty, delivery-close smoke | NR-001..006 |

**Exit:** Migrations apply; roles seed; existing UT/smoke green; matrix P0 REQs → `IMPL` or `PARTIAL`.

---

## Phase P1 — Occurrence Report

| Step | Work | REQ |
|------|------|-----|
| P1.1 | Rename UI + API payload accept new fields (keep backward compat for old clients) | OR-001 |
| P1.2 | Occurrence date vs recorded_at/by | OR-002, OR-003 |
| P1.3 | Outcome + Fault Type + soft-fix method rules | OR-004..007 |
| P1.4 | Named attachments upload UI/API | OR-008 |
| P1.5 | Officers dialog | OR-009 |
| P1.6 | NFF confirm modal + resolve/close | OR-010 |
| P1.7 | Soft fix / inconclusive / fault_identified postconditions | OR-011..013 |
| P1.8 | Optional confirmation channel | OR-014 |

**Exit:** FT-OR-* pass; soft_fix regression pass; matrix OR-* Must → path to `CONF-OK`.

---

## Phase P2 — Track A core (request → issue → badge → notify)

| Step | Work | REQ |
|------|------|-----|
| P2.1 | ME create Replacement Request from fault_identified CTA | TA-001, TA-002 |
| P2.2 | PD approve/reject + assign ME | TA-003 |
| P2.3 | ME → IM issue request; IM issue same-spec S/N | TA-004, TA-005 |
| P2.4 | Replaced badge + S/N display everywhere required | TA-005, BDG-001 |
| P2.5 | RED notification Project/Order/Flight/SDLS | TA-006, NTF-001, CL-002 |
| P2.6 | Auto enqueue Track B awaiting arrival | TA-007 |
| P2.7 | Dual-track board (A side) on case detail | UX-001 |

**Exit:** FT-TA-core + ST-01 (happy path to shipped) pass.

---

## Phase P3 — Track A AIT loop

| Step | Work | REQ |
|------|------|-----|
| P3.1 | ME custody + notify AIT in progress | TA-008 |
| P3.2 | Site actions with FSE (status/notes minimum) | TA-009 |
| P3.3 | AIT upload | TA-010 |
| P3.4 | PD approve → patch_delivered | TA-011, TA-013 |
| P3.5 | PD reject → IM re-issue same ME loop | TA-012 |
| P3.6 | Should: shortage, quarantine failed unit, abort, ME reassign | TA-015..018 |

**Exit:** ST-02 (AIT reject loop) + ST-03 (AIT approve) pass.

---

## Phase P4 — Track B inspection

| Step | Work | REQ |
|------|------|-----|
| P4.1 | IM reception date + PD notify | TB-001 |
| P4.2 | PD assign IE; IE request; IM issue to IE | TB-002..004 |
| P4.3 | Inspection under process + disposition | TB-004..007 |
| P4.4 | Warranty path (reuse OEM claim) | TB-005 |
| P4.5 | Discard path + Discarded badge + block reuse | TB-006, BDG-002, TB-009 |
| P4.6 | Repair under progress → PD verify → restock | TB-007, TB-008 |
| P4.7 | Dual-track board (B side) | UX-001 |
| P4.8 | Should: reusable, never-returned SLA | TB-010, TB-011 |

**Exit:** ST-04 (repair), ST-05 (discard), ST-06 (warranty) pass.

---

## Phase P5 — Close gate, notifications matrix, hardening

| Step | Work | REQ |
|------|------|-----|
| P5.1 | Enforce close gate dual-track vs Soft/NFF | CL-001 |
| P5.2 | Clear RED on patch_delivered/abort | CL-002 |
| P5.3 | Full notification matrix | NTF-001 |
| P5.4 | Evidence reuse of occurrence attachments (S) | UX-002 |
| P5.5 | Full ST suite + conformance report | All M |
| P5.6 | Sign-off per verification loop | — |

**Exit:** Conformance report `CONF-OK` for all Must; test reports attached; release gate.

---

## Dependency graph

```
P0 ──► P1 ──► P2 ──► P3 ──► P5
              │              ▲
              └──► P4 ───────┘
```

P3 and P4 may proceed in parallel after P2; P5 requires both.

---

## Definition of Done (per phase)

1. Code merged (or local complete) for phase steps.  
2. Unit tests for phase REQs executed; report filed under `reports/`.  
3. Functional tests for phase executed; report filed.  
4. Conformance matrix updated (no silent skips).  
5. Open defects linked to REQ IDs; blockers listed.  
6. Verification loop iteration logged in [07](./07-verification-loop-and-reports.md).
