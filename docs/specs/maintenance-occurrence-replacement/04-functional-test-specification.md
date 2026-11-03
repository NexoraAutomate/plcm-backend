# 04 — Functional Test Specification

**Scope:** API + UI feature tests (authenticated roles). May use test DB; not full multi-system production.  
**IDs:** `FT-<area>-NNN`

---

## 1. Occurrence Report — FT-OR-*

| ID | Roles | Steps | Expected | REQ |
|----|-------|-------|----------|-----|
| FT-OR-001 | FSE/ME | Open case → Occurrence Report panel visible (not “Onsite visit outcome”) | Label/button renamed | OR-001 |
| FT-OR-002 | FSE | Set occurrence date yesterday; save; view detail | Occurrence ≠ recorded timestamps | OR-002, OR-003 |
| FT-OR-003 | FSE | Soft fix + method + notes | Case/entities soft_fixed | OR-006, OR-011 |
| FT-OR-004 | FSE | Select NFF → modal → Confirm Yes | Case resolved/closed as NFF | OR-010 |
| FT-OR-005 | FSE | Select NFF → Cancel/No | Report saved; case open | OR-010 |
| FT-OR-006 | FSE | Inconclusive + notes | Case open | OR-012 |
| FT-OR-007 | FSE | Fault identified + Fault Type Electrical + named attachment + 2 officers | Saved; CTA for replacement visible | OR-005, OR-008, OR-009, OR-013 |
| FT-OR-008 | FSE | Upload attachment without name | Blocked with validation | OR-008 |
| FT-OR-009 | FSE | Fault type each of 10 values (param) | All save | OR-005 |
| FT-OR-010 | Tech w/o perm | Attempt record | 403 / UI disabled | ROLE-* |

---

## 2. Track A — FT-TA-*

| ID | Roles | Steps | Expected | REQ |
|----|-------|-------|----------|-----|
| FT-TA-001 | ME | From fault_identified case, create Replacement Request **before** any faulty reception | Request status `replacement_requested` | TA-001, TA-002 |
| FT-TA-002 | PD | Approve + assign ME | `pd_approved`; ME notified | TA-003 |
| FT-TA-003 | PD | Reject with reason | `pd_rejected`; no IM issue | TA-003 |
| FT-TA-004 | ME→IM | Request issue; IM issues matching stock | New S/N; Replaced badge; RED on project hierarchy | TA-004..006, BDG-001 |
| FT-TA-005 | IM | Attempt issue wrong PN | Error; no badge | TA-004 |
| FT-TA-006 | SYS | After issue | Track B `awaiting_faulty_arrival` exists | TA-007 |
| FT-TA-007 | ME | Notify AIT in progress | PD sees status; notify | TA-008 |
| FT-TA-008 | ME | Upload AIT report | Attachments listed | TA-010 |
| FT-TA-009 | PD | Approve AIT | `patch_delivered`; RED cleared | TA-011, TA-013, CL-002 |
| FT-TA-010 | PD→IM→ME | Reject AIT; IM issues second S/N to same ME | Loop; prior S/N history retained | TA-012 |
| FT-TA-011 | Case UI | Dual-track board shows A statuses | UX board updates | UX-001 |
| FT-TA-012 | IM (S) | Zero stock | Escalation; no issue | TA-015 |

---

## 3. Track B — FT-TB-*

| ID | Roles | Steps | Expected | REQ |
|----|-------|-------|----------|-----|
| FT-TB-001 | IM | Receive faulty; set reception date | PD notified; status received | TB-001 |
| FT-TB-002 | PD | Assign IE | ie_assigned | TB-002 |
| FT-TB-003 | IE→IM | Request handover; IM issues | inspection_under_process | TB-003, TB-004 |
| FT-TB-004 | IE | Mark irreparable + warranty active | Warranty/claim path | TB-005 |
| FT-TB-005 | IE→IM | Irreparable + expired → recommend discard; IM trash | Discarded badge; cannot reserve | TB-006, TB-009, BDG-002 |
| FT-TB-006 | IE | Attempt trash directly | Denied | TB-009 |
| FT-TB-007 | IE→PD→IM | Repairable → repair → PD approve → restock | Available stock | TB-007, TB-008 |
| FT-TB-008 | PD | Reject repair verification | Stays repair_under_progress | TB-008 |
| FT-TB-009 | Case UI | Track B progress on dual board | Visible | UX-001 |

---

## 4. Close gate — FT-CL-*

| ID | Steps | Expected | REQ |
|----|-------|----------|-----|
| FT-CL-001 | Soft fix only → close | Allowed | CL-001 |
| FT-CL-002 | Track A shipped, Track B awaiting → attempt close | Blocked | CL-001 |
| FT-CL-003 | Track A patch_delivered + Track B discarded → close | Allowed | CL-001 |
| FT-CL-004 | Track A patch_delivered + Track B restocked → close | Allowed | CL-001 |

---

## 5. Non-regression — FT-NR-*

| ID | Steps | Expected | REQ |
|----|-------|----------|-----|
| FT-NR-001 | Legacy soft fix API payload (no occurrence_date if still supported via default) | Still works or clear migration message | NR-002 |
| FT-NR-002 | Open warranty claim on scrapped rework (existing UI) | Status transitions OK | NR-004 |
| FT-NR-003 | Delivery confirm on resolved case | Close still works | NR-005 |

---

## Evidence

For each FT: screenshot or API log excerpt + timestamp + build SHA in Functional Test Report ([07](./07-verification-loop-and-reports.md#functional-test-report-template)).
