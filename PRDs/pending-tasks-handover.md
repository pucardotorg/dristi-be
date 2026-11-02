# Pending Tasks — Developer Handover

Status: v1 — 2026-09-14
Audience: developers building the pending tasks module

---

## 1. What a pending task is

A pending task is a time-bound action a user must perform on a case. The system creates
it when a trigger fires (an order, a scrutiny return, a payment becoming due) and closes
it when the user acts or the window expires. Every task links to exactly one case and
routes to exactly one workflow.

---

## 2. Attributes of a pending task

| # | Attribute | Type | Description |
|---|---|---|---|
| 1 | Task Name | string | The title displayed on the screen. Supports template variables — e.g. `Pay ₹{amount} — {feeHead}`, `Correct {defectCount} defects in {caseName}`, `Sign {documentName}`. The name is the one thing every surface shows: the list, the card, the notification. |
| 2 | Due Date | date | The date by which the user must act. A task whose due date has passed is displayed as overdue — this is a visual treatment, not a status change. |
| 3 | Creation Trigger | documentation | Documents when the task is created. Used by the developer to translate into code — not a runtime value. |
| 4 | Closure Trigger | documentation | Documents all triggers that close the task, including explicit user action and auto-closure rules. Used by the developer to translate into code — not a runtime value. |
| 5 | Users | person[] | The users who can act on the task. |
| 6 | Category | enum | Groups tasks by action type. Citizen-side values: **Pay**, **Sign**, **File/Submit**, **Others**. |
| 7 | Link to Workflow | string | Where the task leads to. Either opens a new page or a pop-up where the user performs the required action. |
| 8 | Status | enum | **Open** · **Completed** · **Expired** · **Archived**. See §3. |
| 9 | Case | reference | The case the task is linked to. |
| 10 | Visibility | enum | Who sees the task: **Only Users** (who can act on it) · **All users on the same side of the case** (citizen-facing) · **All employees in the courtroom** (court-facing). |
| 11 | Creation Date | datetime | When the task was created. |
| 12 | Action Label | string | The text on the button the user clicks to act on the task — e.g. "Make Payment", "Sign Document", "File Response". |

---

## 3. Status lifecycle

Four statuses with one-way transitions:

```
Open ──→ Completed   (user acts, or the system observes completion)
Open ──→ Expired     (the window closed without action, or the task became irrelevant)
Open ──→ Archived    (user puts it away)
Archived ──→ Open    (user restores it)
```

**Overdue is not a status.** It is a derived visual state: any Open task whose due date
has passed is displayed as overdue. No process flips a status; no transition is needed
when a due date moves.

---

## 4. Open questions

None currently.

> **Note for developers — batch operations.** The UI will allow users to select multiple
> signing or payment tasks and complete them in one action (one OTP, one transaction).
> Each task remains an individual record; the batch is a UI convenience. The task record
> does not need to know it is part of a batch — it is closed when the batch succeeds. If
> a structured amount field is ever needed on the task (e.g. to sum totals in the batch
> UI), that is a separate decision.
