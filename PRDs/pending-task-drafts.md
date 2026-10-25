# Pending task drafts

**Status:** 2026-10-25 — §8, three notifications from [`process-handover.md`](process-handover.md), drafted and **not yet written to Coda**. §4–§7, four court-side tasks from [`process-handover.md`](process-handover.md) `SGN-02`, drafted and **not yet written to Coda** (PRDs label `process-handover`). 2026-10-20 — the three order-generation tasks (§1–§3) written to the master **Pending tasks (Court Side)** table on Coda (PRDs label `order-generation`), and shown in §15 of [`order-generation.md`](order-generation.md). Coda is now the source of truth for them; this file is kept only as the record of the drafts. Nothing is waiting to be written.

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

---

## 4. Receive envelope

Source: `STP-02` of [`process-handover.md`](process-handover.md). One task per process.

| # | Attribute | Value |
|---|---|---|
| 1 | Task Name | `Receive envelope — {processType} to {recipientName}` *(proposed)* |
| 2 | Due Date | None |
| 3 | Creation Trigger | An RPAD or Police (RPAD) process is created (`STP-01`), alongside the citizen-side task to hand in the envelope. |
| 4 | Closure Trigger | **Completed** when receipt of the envelope is recorded (`STP-02`). **Expired** when the process expires (`EXP-02`) or is recalled (`PIA-01`). |
| 5 | Users | People holding the **Envelope receiver** role for the process's type and channel ([`court-roles.md`](court-roles.md) `RLE-09`) |
| 6 | Category | Not set: §2 lists citizen-side categories only |
| 7 | Link to Workflow | Opens the process to record receipt of its envelope |
| 8 | Status | Open · Completed · Expired · Archived, as §3 of the pending tasks handover |
| 9 | Case | The case the process belongs to |
| 10 | Visibility | All employees in the courtroom |
| 11 | Creation Date | When the task was created |
| 12 | Action Label | `Record receipt` *(proposed)* |

---

## 5. Sign process

Source: `SGN-02` of [`process-handover.md`](process-handover.md). One task per process.

| # | Attribute | Value |
|---|---|---|
| 1 | Task Name | `Sign {processType} — {recipientName}` *(proposed)* |
| 2 | Due Date | None |
| 3 | Creation Trigger | The process's fee (§7) and, for RPAD and Police (RPAD), envelope (§8) prerequisites are met. |
| 4 | Closure Trigger | **Completed** when the process is signed (`SGN-04`). **Expired** when the process expires (`EXP-02`) or is recalled (`PIA-01`). |
| 5 | Users | People holding the **Process signer** role for the process's type and channel ([`court-roles.md`](court-roles.md) `RLE-09`) |
| 6 | Category | Sign |
| 7 | Link to Workflow | Opens the process to sign it |
| 8 | Status | Open · Completed · Expired · Archived, as §3 of the pending tasks handover |
| 9 | Case | The case the process belongs to |
| 10 | Visibility | All employees in the courtroom |
| 11 | Creation Date | When the task was created |
| 12 | Action Label | `Sign` *(proposed)* |

Several processes can be selected and signed in one action, each still signed separately
(`SGN-03`), as the batch note in the pending tasks handover describes.

---

## 6. Send process

Source: `DSP-03` of [`process-handover.md`](process-handover.md). One task per process.

| # | Attribute | Value |
|---|---|---|
| 1 | Task Name | `Send {processType} — {recipientName} by {channel}` *(proposed)* |
| 2 | Due Date | None |
| 3 | Creation Trigger | The process is signed (`SGN-04`). Not created where it is signed and sent in one click (`DSP-02`). Created on every channel: on a manual channel the dispatcher marks it sent, on a system channel they click Send. |
| 4 | Closure Trigger | **Completed** when the process is marked sent or sent (`DSP-03`). **Expired** when the process expires (`EXP-02`) or is recalled (`PIA-01`). |
| 5 | Users | People holding the **Process dispatcher** role for the process's type and channel ([`court-roles.md`](court-roles.md) `RLE-09`) |
| 6 | Category | Not set: §2 lists citizen-side categories only |
| 7 | Link to Workflow | Opens the process to send it, or to mark it sent |
| 8 | Status | Open · Completed · Expired · Archived, as §3 of the pending tasks handover |
| 9 | Case | The case the process belongs to |
| 10 | Visibility | All employees in the courtroom |
| 11 | Creation Date | When the task was created |
| 12 | Action Label | `Send` on a system channel, `Mark as sent` on a manual one *(proposed)* |

---

## 7. Record outcome

Source: `DSP-03` of [`process-handover.md`](process-handover.md). One task per process.

| # | Attribute | Value |
|---|---|---|
| 1 | Task Name | `Record outcome — {processType} to {recipientName} by {channel}` *(proposed)* |
| 2 | Due Date | None |
| 3 | Creation Trigger | The process is sent, on a channel whose status update is Manual (§6.2). Not created where the status update is by the system. |
| 4 | Closure Trigger | **Completed** when a terminal outcome is recorded (`DSP-08`). **Expired** when the process expires (`EXP-02`) or is recalled (`PIA-01`). |
| 5 | Users | People holding the **Process reporter** role for the process's type and channel ([`court-roles.md`](court-roles.md) `RLE-09`) |
| 6 | Category | Not set: §2 lists citizen-side categories only |
| 7 | Link to Workflow | Opens the process to record its outcome |
| 8 | Status | Open · Completed · Expired · Archived, as §3 of the pending tasks handover |
| 9 | Case | The case the process belongs to |
| 10 | Visibility | All employees in the courtroom |
| 11 | Creation Date | When the task was created |
| 12 | Action Label | `Record outcome` *(proposed)* |

**Open, for §4–§7:**
- Court-side categories: §2 of the pending tasks handover defines only the citizen-side ones.
- Due dates: none is set. The process has its own expiry — by default midnight at the end of the day before the hearing (`process-handover.md` `EXP-01`).
- Volume: in Gujarat, at 1,000+ cases a day, these tasks could run to thousands open at once.

---

## 8. Notifications from the process handover

Not pending tasks: three notifications for the master **Notifications** table, PRDs label
`process-handover`, each with **Live** = No and **State** blank. Columns as in that table.
*(proposed)* marks wording nobody has confirmed. Errored and Expired send no notification.

| Trigger | Content | Recipients | Channels | Notes |
|---|---|---|---|---|
| Steps become due on a process — a court fee balance to pay or an RPAD envelope to hand in | `Take steps for the issue of {#processtype} to {#recipient} in case {#casenumber}. Log in at {#link}. - On Courts` | Users on the side of the party directed to take steps (`PRC-07`) *(proposed)* | SMS, In-App *(proposed)* | Goes with the citizen-side pay and envelope pending tasks (`FEE-06`, `STP-01`). |
| A process's outcome is recorded — Delivered, Not delivered, Executed or Not executed | `{#processtype} to {#recipient} in case {#casenumber} has been {#status}. - On Courts` *(proposed)* | All users on the case *(proposed)* | In-App *(proposed)* | `DSP-08`. Not sent for Errored. |
| A process is recalled | `{#processtype} to {#recipient} in case {#casenumber} has been recalled. - On Courts` *(proposed)* | All users on the case *(proposed)* | In-App *(proposed)* | `PIA-01`. |

**Open, for §8:**
- Whether *steps due* goes once per process or once per round, so that a round of several
  processes does not send several messages.

