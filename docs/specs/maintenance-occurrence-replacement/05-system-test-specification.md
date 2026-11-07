# 05 — System Test Specification (ST)

**Scope:** End-to-end workflows across roles, UI, APIs, inventory, hierarchy badges, and notifications.  
**Demo accounts:** `scripts/seed_maintenance_demo_users.py`  
**Entry:** P0–P5 Must features implemented; UT+FT for those phases green or Accepted Deviation recorded.

> Seed script references this file for target ST scenarios once P1+ lands.

---

## 1. Environment

| Item | Requirement |
|------|-------------|
| Backend | Deployed/local with migrated DB |
| Frontend | Occurrence Report + dual-track board + badges |
| Inventory | ≥2 same-P/N spares for AIT reject loop; 1 case for shortage |
| Hierarchy | Project / Order / Flight / SDLS entities visible for RED chip |
| Mail/notify | In-app notifications observable |

---

## 2. System scenarios

### ST-01 Soft fix early exit

| | |
|--|--|
| **REQ** | OR-005, DT-004, NR-001 |
| **Actors** | FSE/field user |
| **Flow** | Open case → Occurrence Report Soft fix → resolve soft_fixed |
| **Pass** | Case resolved soft_fixed; no Replacement Request; no RED; no Track B |

### ST-02 NFF confirm close

| | |
|--|--|
| **REQ** | OR-006 |
| **Flow** | Occurrence Report NFF → confirm Yes |
| **Pass** | Case closed/resolved NFF; dual-track not started |

### ST-03 NFF keep open

| | |
|--|--|
| **REQ** | OR-006 |
| **Flow** | NFF → confirm No |
| **Pass** | Case open with note; can later re-record / investigate |

### ST-04 Inconclusive

| | |
|--|--|
| **REQ** | OR-007 |
| **Pass** | Case open; no Track A CTA |

### ST-05 Dual-track happy path (replace + repair restock)

| | |
|--|--|
| **REQ** | DT-002, DT-003, RA-*, IE-005/009/010/011 |
| **Actors** | Opener → HM → PD → ME → IM → FSE → IE → PD → IM |
| **Flow** | Fault identified + evidence → Replacement Request → HM assign/reserve → PD approve → ME request issue → IM issue (RED + Replaced + awaiting faulty) → site AIT → PD approve AIT (patch_delivered) → customer returns faulty → IM reception → PD assign IE → inspect repairable → repair → PD approve → IM restock → close case |
| **Pass** | Both tracks terminal; RED cleared; case closed; notifications fired per matrix; investigation tree usable during process |

### ST-06 AIT reject loop then pass

| | |
|--|--|
| **REQ** | RA-013, RA-014 |
| **Flow** | As ST-05 through first AIT → PD Reject → IM issues second S/N to same ME → quarantine first → AIT Approve |
| **Pass** | Second S/N installed; Track A patch_delivered; failed unit quarantined |

### ST-07 Track B warranty

| | |
|--|--|
| **REQ** | IE-006, IE-011 |
| **Flow** | After ship/reception → IE irreparable + warranty → OEM claim → claim_closed |
| **Pass** | Track B terminal via claim; Track A independently completable; close gate respects both |

### ST-08 Track B discard

| | |
|--|--|
| **REQ** | IE-007, IE-008 |
| **Flow** | Irreparable + no warranty → IE recommend discard → IM trash |
| **Pass** | Discarded badge; unit not reservable/issuable; Track B terminal |

### ST-09 Close gate enforcement

| | |
|--|--|
| **REQ** | DT-003 |
| **Flow** | Complete only Track A; attempt close; then only Track B on another case; attempt close; then both |
| **Pass** | Partial close blocked; full close succeeds |

### ST-10 Stock shortage

| | |
|--|--|
| **REQ** | RA-006 |
| **Flow** | Approved request; no matching stock; ME requests issue |
| **Pass** | Escalation to PD/HM; no fake S/N; no RED Replaced from ghost issue |

### ST-11 PD reject pre-issue

| | |
|--|--|
| **REQ** | RA-004 |
| **Pass** | Request closed rejected; no inventory movement; no RED |

### ST-12 Segregation of duties discard

| | |
|--|--|
| **REQ** | IE-007 |
| **Pass** | IE cannot complete trash alone; IM confirmation required |

### ST-13 Non-regression soft fix + replace legacy

| | |
|--|--|
| **REQ** | DT-006, NR-001, NR-003 |
| **Flow** | Soft fix path; and (if still exposed) legacy replace→returned_unit without new board fields |
| **Pass** | No regressions on existing field-service paths |

### ST-14 Notification & badge sweep

| | |
|--|--|
| **REQ** | RL-004, RL-005, RA-008 |
| **Flow** | Walk ST-05; verify each FSD §7 event appears for intended audience; Replaced/Discarded/RED visibility |
| **Pass** | Matrix events observed; RED high on hierarchy while open |

### ST-15 Optional — Abort Track A after later NFF (Should)

| | |
|--|--|
| **REQ** | RA-017 |
| **Pass** | Request cancelled; RED cleared; audit retained — or Accepted Deviation if deferred |

### ST-16 Optional — Faulty never returned SLA (Should)

| | |
|--|--|
| **REQ** | IE-014 |
| **Pass** | Escalation fires per configured SLA — or Accepted Deviation |

---

## 3. System test execution order

1. ST-01 … ST-04 (early exits)  
2. ST-11, ST-10 (negative Track A)  
3. ST-05 (full happy path)  
4. ST-06 (reject loop)  
5. ST-07, ST-08, ST-12 (Track B branches)  
6. ST-09 (close gate)  
7. ST-13, ST-14 (regression + notify)  
8. ST-15, ST-16 if in scope  

---

## 4. Evidence to attach

- Case IDs / Replacement Request IDs / Rework IDs  
- Screenshots: Occurrence Report, dual-track board, RED chip, badges, AIT decision, discard  
- Notification list excerpts  
- Inventory status before/after  

Fill [08-test-report-template.md](./08-test-report-template.md) **System** section.  
Any Fail → NCR → user decision before Conformance Report approval.
