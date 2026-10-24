# Pending task drafts

**Status:** 2026-10-20 — all three tasks below written to the master **Pending tasks (Court Side)** table on Coda (PRDs label `order-generation`), and shown in §15 of [`order-generation.md`](order-generation.md). Coda is now the source of truth for them; this file is kept only as the record of the drafts. Nothing is waiting to be written.

Pending tasks drafted from other PRDs, held here until they are all written to the
pending tasks page on Coda together. **Not synced.** Each uses the attributes of §2 of
[`pending-tasks-handover.md`](pending-tasks-handover.md). *(proposed)* marks wording that
nobody has confirmed yet.

---

## 1. Draft order

Source: `DFT-05` of [`order-generation.md`](order-generation.md). This task is how a draft
order appears under *Drafting* in Pending orders (§11 of that document).

| # | Attribute | Value |
|---|---|---|
| 1 | Task Name | `Draft order — {orderTitle}` *(proposed)* |
| 2 | Due Date | None |
| 3 | Creation Trigger | A draft order is created, on the order screen, from a hearing or from the case. Also when an order that was sent for signing is **moved back to draft** (`SND-05`): a new task is created, because a closed task does not reopen (§3 of the pending tasks handover). |
| 4 | Closure Trigger | **Completed** when the order is sent for signing (`SND-01`). **Expired** when the draft is discarded (`DFT-06`). |
| 5 | Users | People holding the **order drafter** role ([`court-roles.md`](court-roles.md)) |
| 6 | Category | Not set: §2 lists citizen-side categories only |
| 7 | Link to Workflow | Opens the draft on the order screen |
| 8 | Status | Open · Completed · Expired · Archived, as §3 of the pending tasks handover |
| 9 | Case | The case the order belongs to |
| 10 | Visibility | All employees in the courtroom |
| 11 | Creation Date | When the task was created |
| 12 | Action Label | `Continue drafting` *(proposed)* |

**Open:**
- Court-side categories: §2 of the pending tasks handover defines only the citizen-side ones.
- Whether a draft order needs a due date. None is set.

---

## 2. Sign order

Source: `SND-07`, `SND-08` of [`order-generation.md`](order-generation.md). Created alongside
*Fill order data*; the two are worked in parallel.

| # | Attribute | Value |
|---|---|---|
| 1 | Task Name | `Sign order — {orderTitle}` *(proposed)* |
| 2 | Due Date | None |
| 3 | Creation Trigger | The order is **sent for signing** (`SND-01`), including each time it is sent for signing again after being moved back to draft. |
| 4 | Closure Trigger | **Completed** when the order is signed (`SGN-02`). **Expired** when the order is moved back to draft (`SND-05`). |
| 5 | Users | People holding the **order signer** role ([`court-roles.md`](court-roles.md)) |
| 6 | Category | Sign |
| 7 | Link to Workflow | Opens the order in Pending orders to sign it |
| 8 | Status | Open · Completed · Expired · Archived, as §3 of the pending tasks handover |
| 9 | Case | The case the order belongs to |
| 10 | Visibility | All employees in the courtroom |
| 11 | Creation Date | When the task was created |
| 12 | Action Label | `Sign` *(proposed)* |

Several signing tasks can be completed in one action with a DSC (`SGN-03`, `SGN-06`), as
the batch note in the pending tasks handover describes. With Aadhaar e-sign they are
completed one at a time.

---

## 3. Fill order data

Source: `SND-07`, `SND-08` of [`order-generation.md`](order-generation.md). Created alongside
*Sign order*; the two are worked in parallel.

| # | Attribute | Value |
|---|---|---|
| 1 | Task Name | `Fill order data — {orderTitle}` *(proposed)* |
| 2 | Due Date | None |
| 3 | Creation Trigger | The order is **sent for signing** (`SND-01`), including each time it is sent for signing again after being moved back to draft — even where the order data had been marked complete: sending it for signing again puts it back to not complete, keeping its values, so it is looked at again against text that may have changed (`SND-08`). |
| 4 | Closure Trigger | **Completed** when the order data is marked complete (`CMP-01`). **Expired** when the order is moved back to draft (`SND-05`). |
| 5 | Users | People holding the **order data filler** role ([`court-roles.md`](court-roles.md)) |
| 6 | Category | Not set: §2 lists citizen-side categories only |
| 7 | Link to Workflow | Opens the order in Pending orders to fill its order data |
| 8 | Status | Open · Completed · Expired · Archived, as §3 of the pending tasks handover |
| 9 | Case | The case the order belongs to |
| 10 | Visibility | All employees in the courtroom |
| 11 | Creation Date | When the task was created |
| 12 | Action Label | `Fill order data` *(proposed)* |
