# Cognizance Cheat Sheet

**Status:** v6 — 2026-09-17; the §3 pending-task view now filters on the PRD label
rather than the task name, so newly tagged tasks appear; §7 Linked records added with
views of the remaining master tables. v5 — one positive action per tab, swappable per state on either
tab; both positive actions now schedule a hearing and ask for the date; cognizance
auto-adds the issue of summons. v4 — the 30-day demand-notice check runs from the date on
the return memo. v3 — actions restructured as positive/negative, View Case button added,
days of delay added as a column, pending task details replaced with a live view of the
Pending Tasks table, Date of Receipt of Information about Return removed. v2 — fresh
deployment, no data migration. v1 — converted from the `Cognizance Cheat Sheet` PRD.

**Product Owner:** Anshumanth Rao · Ayushi Singhal
**Contributors:** Ayushi Singhal · Anshumanth Rao
**Design:** Om Kumar

---

## 1. Context

The Cognizance Cheat Sheet gives a judge the case facts needed to decide whether to take
cognizance, in one screen, without opening the case file.

---

## 2. Where it lives

A new **Take Cognizance** option under the Actions area of the Magistrate's Home Screen.

It has two tabs:

| Tab | Contains | Columns |
|---|---|---|
| **Without Delay** | Cases where the complaint was filed within one calendar month of the date of accrual of cause of action | Case name · Case number · Advocates |
| **With Delay** | Cases where the complaint was filed more than one calendar month after the date of accrual of cause of action | Case name · Case number · Advocates · Days of delay |

---

## 3. What makes a case appear

Listing is driven by the **pending task**, not by the case stage. Every case with an open
`Take Cognizance` pending task appears, in the tab its delay status puts it in. A case
leaves the list when the task closes.

Stage is not the filter because a case can move to a later stage before cognizance is
taken or the case is dismissed.

The `Take Cognizance` task is defined in the **Pending Tasks** table, which is the single
source of truth for every pending task. Its row is embedded below as a live view of that
table and reflects any change made there.

```superhuman-view
name: Pending tasks (Court Side) — Cognizance
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("cognizance-cheat-sheet")
```

Delay status for the tab split is evaluated from the date of accrual of cause of action
and the date of complaint filing, on the same basis as the filing form: one **calendar
month** from the date of cause of action.

> **Note.** The Actions area also carries a Delay Condonation tab driven by its own
> pending task, which lists the same cases as the With Delay tab. We may want to remove
> that tab.

---

## 4. Fields

The fields visible on a case in the Cognizance tab. Every field is read from the filing;
the `Source` column gives the filing field ID from
`efiling-scrutiny-registration-handover.md`.

### Both tabs

| # | Field | Tooltip | Logic | Source |
|---|---|---|---|---|
| 1 | Date of Complaint Filing | | If the complaint was filed more than one calendar month after the date of accrual of cause of action, show the text: *The complaint is outside the limitation period* | `JUR-10` |
| 2 | Date on Cheque | | Repeats per cheque | `CHQ-1` |
| 3 | Date of Presentation/Deposit of cheque | | Repeats per cheque | `CHQ-8` |
| 4 | Date on Return Memo | | Repeats per cheque | `CHQ-9` |
| 5 | Reason for Return of Cheque | | Repeats per cheque | `CHQ-10` |
| 6 | Date of Dispatch of Demand Notice | | If the demand notice was not dispatched within 30 days of the date on the return memo, show the message: *Demand notice not issued within 30 days of the return of the cheque as unpaid.* | `LDN-2`, checked against `CHQ-9` |
| 7 | Date of Delivery of Demand Notice | | Show when the demand notice was delivered | `LDN-6`, shown on `LDN-5` = Yes |
| 8 | Date of Return of Demand Notice | Date on which the demand notice was returned to the post office as undelivered. | Show when the demand notice was not delivered | `LDN-7`, shown on `LDN-5` = No |
| 9 | Reason for Non-Delivery of Demand Notice | | Show when the demand notice was not delivered | `LDN-8`, shown on `LDN-5` = No |
| 10 | Bank Branch | | Show the complainant's bank branch if the complainant deposited the cheque in their own account; otherwise show the accused's bank branch | `JUR-4` or `CHQ-7`, switched on `JUR-1` |

### With Delay tab only

| # | Field | Tooltip | Logic | Source |
|---|---|---|---|---|
| 11 | Duration of Delay | | Shown in days | `JUR-11` |
| 12 | Reason for praying condonation of delay | | | `JUR-12` |

---

## 5. Files

Documents reachable from the Cognizance tab. All three are mandatory at filing.

| Document | Instances | Source |
|---|---|---|
| Cheque | One per cheque | `DCM-1` |
| Return memo | One per cheque | `DCM-2` |
| Demand notice | One per demand notice | `DCM-3` |

---

## 6. Actions

Each tab carries exactly two actions: one **positive** action that moves the case
forward, and one **negative** action that ends it. The negative action is always Dismiss
Case. There is never a second positive action on a tab.

| Tab | Positive action | Negative action |
|---|---|---|
| Without Delay | Take Cognizance | Dismiss Case |
| With Delay | Issue Notice | Dismiss Case |

**The positive action is configurable per state, on each tab independently.** A state can
replace Take Cognizance with Issue Notice, or Issue Notice with Take Cognizance, on
either tab. The values above are the defaults.

### Order items

Every action opens the order screen with its items pre-loaded as a composite order. The
judge can edit the order before issuing it.

| Action | Order items pre-loaded |
|---|---|
| Take Cognizance | Acceptance of the delay condonation application (`ACCEPTANCE_REJECTION_DCA`) — only when a delay exists · Cognizance (`TAKE_COGNIZANCE`) · Issue of summons (`SUMMONS`) · Scheduling of hearing (`SCHEDULE_OF_HEARING_DATE`) |
| Issue Notice | Issue of notice (`NOTICE`) · Scheduling of hearing (`SCHEDULE_OF_HEARING_DATE`) |
| Dismiss Case | Dismiss case (`DISMISS_CASE`) |

**Both positive actions carry a scheduling of hearing item.** It behaves like any other
item in the composite order, and its hearing date is a required field the judge fills in
on the order screen. Dismiss Case carries no scheduling item.

**Taking cognizance auto-adds the issue of summons.** The judge does not add it.

**Taking cognizance on a case with a delay auto-adds the acceptance of the delay
condonation application**, ahead of the cognizance item, so the delay application is
disposed of in the same order that takes cognizance. Acceptance uses the generic
*Accept application* order template.

Issuing a notice leaves the case on its tab — the Take Cognizance task stays open until
cognizance is taken or the case is dismissed.

### View Case

The screen also carries a **View Case** button, which opens the full case file. It is not
an order action and changes nothing on the case.

---

## 7. Linked records

Live views of the master tables, filtered to this document. Each master table is the
single source of truth and the place to edit its rows; anything tagged
`cognizance-cheat-sheet` there appears here automatically. A section showing nothing
means nothing is tagged for it yet. A downloaded copy of this document is a snapshot.

### Pending tasks (Citizen-Side)

The court-side task that drives this screen is in §3.

```superhuman-view
name: Pending tasks (Citizen-Side) — Cognizance
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("cognizance-cheat-sheet")
```

### Notifications

```superhuman-view
name: Notifications — Cognizance
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-xnftvTkudd/tables/grid-3FTjQhdfYv
filter: PRDs.Contains("cognizance-cheat-sheet")
```

### Events

```superhuman-view
name: Events — Cognizance
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-2x28DoUtbn/tables/grid-GPg4dKS-s9
filter: PRDs.Contains("cognizance-cheat-sheet")
```


---

## 8. Open questions

None currently.
