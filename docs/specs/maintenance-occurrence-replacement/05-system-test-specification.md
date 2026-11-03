# 05 — System Test Specification

**Scope:** End-to-end multi-role workflows across frontend + backend + notifications + inventory/hierarchy side effects.  
**IDs:** `ST-NNN`  
**Environment:** Staging (or local full stack) with seeded roles ME, FSE, IE, PD, IM.

---

## ST-01 — Immediate replacement happy path to ship (parallel Track B queued)

**Covers:** OR-013, TA-001..007, BDG-001, NTF-001 (ship), UX-001  

| Step | Actor | Action |
|------|-------|--------|
| 1 | Any | Open maintenance case on project with installed S/N |
| 2 | FSE | Record Occurrence Report: fault_identified, Fault Type Hardware, named email attachment, 2 FSE officers, occurrence date |
| 3 | ME | Create Replacement Request (faulty **not** yet received) |
| 4 | PD | Approve; assign ME |
| 5 | ME | Request IM issue |
| 6 | IM | Issue same-spec replacement S/N; ship |

**Pass criteria:**

- Project/Order/Flight/SDLS show **RED** replacement-open notification.
- Entity displays **new S/N** + **Replaced** badge.
- Track B record `awaiting_faulty_arrival` exists.
- Dual-track board shows A=`shipped_*`, B=`awaiting_*`.
- Soft-fix cases elsewhere unaffected (spot check).

---

## ST-02 — AIT reject loop then approve

**Covers:** TA-008..013, CL-002  

| Step | Actor | Action |
|------|-------|--------|
| 1 | — | Continue from ST-01 post-ship (or seed equivalent) |
| 2 | ME | Custody + notify AIT in progress |
| 3 | ME+FSE | Site replace/integrate; upload failing AIT results |
| 4 | PD | **Reject** AIT |
| 5 | IM | Issue **second** replacement to **same** ME |
| 6 | ME | Re-install; upload passing AIT |
| 7 | PD | **Approve** |

**Pass criteria:**

- `assigned_me_id` unchanged across loop.
- `issued_serials` history length ≥ 2.
- Final status `patch_delivered`; RED cleared.
- Failed unit handled per quarantine policy if implemented (S).

---

## ST-03 — Soft fix & NFF early exits (no dual track)

**Covers:** OR-010, OR-011, CL-001, NR-002  

| Scenario | Steps | Pass |
|----------|-------|------|
| Soft fix | Occurrence soft_fix + method → auto resolve | Case closed/resolved soft_fixed; no Replacement Request |
| NFF Yes | NFF + confirm close | Case NFF closed; no Track A |
| NFF No | NFF + decline close | Case open with report |

---

## ST-04 — Full dual track: replace + repair restock + close

**Covers:** CL-001, TB-001..008, TA-* complete  

| Step | Actor | Action |
|------|-------|--------|
| 1 | — | Complete Track A to `patch_delivered` (ST-02) |
| 2 | Customer/IM | Faulty arrives; IM sets reception date |
| 3 | PD | Assign IE |
| 4 | IE→IM | Handover → inspection_under_process |
| 5 | IE | Repairable; repair_under_progress; document root cause |
| 6 | IE | Complete repair + test reports |
| 7 | PD | Verify Approve |
| 8 | IM | Restock repaired unit |
| 9 | PD/ME | Close maintenance case |

**Pass criteria:** Close succeeds; restocked S/N allocatable; dual board both terminal; notifications for receive/restock/close fired.

---

## ST-05 — Discarded path

**Covers:** TB-006, TB-009, BDG-002  

| Step | Actor | Action |
|------|-------|--------|
| 1 | — | Track B at inspection_under_process |
| 2 | IE | Irreparable; warranty expired; recommend discard + comments |
| 3 | IE | Attempt trash | **Must fail** |
| 4 | IM | Confirm trash |

**Pass criteria:** Discarded badge on inventory row; reserve/issue of that S/N fails; case close allowed if Track A done.

---

## ST-06 — Warranty claim path

**Covers:** TB-005, NR-004  

| Step | Actor | Action |
|------|-------|--------|
| 1 | IE | Irreparable + under warranty |
| 2 | IM/system | Open/submit OEM claim (existing statuses) |

**Pass criteria:** Claim linked to rework/case; Track B `warranty_claim` / claim lifecycle progresses; no Discarded badge until claim rejected and discard chosen.

---

## ST-07 — Notification & badge system sweep

**Covers:** NTF-001, BDG-001, BDG-002, CL-002  

Run ST-01→ST-05 (or scripted events) and verify each row of FSD §7 notification matrix appears for correct audience/priority. Verify RED appears on ship and clears on approve/abort.

---

## ST-08 — Non-regression system smoke

**Covers:** NR-001..006  

| Check | Pass |
|-------|------|
| Create case with production-support override | Still works |
| Tree suspect → confirm → resolve repaired (no Track A) | Still works |
| Delivery confirm close on legacy resolved case | Still works |
| Hierarchy reservation/issue unrelated project | Unaffected |

---

## ST-09 — Concurrent tracks timing

**Covers:** TA-001, TB-001, CL-001  

| Step | Action |
|------|--------|
| 1 | Complete Track A to patch_delivered **before** faulty ships |
| 2 | Attempt case close | **Blocked** |
| 3 | Receive faulty; complete discard or restock |
| 4 | Close | **Allowed** |

---

## System pass rule

All ST-01..ST-09 Must scenarios **PASS** for release. Should/Could failures → waiver or CONF-GAP on linked S/C REQs only.
