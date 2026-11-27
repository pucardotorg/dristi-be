# Order item catalogue

**Status:** 2026-11-27 (25) — **no more Dropdown and Contextual**: the Availability column and its note are removed; every order item is chosen the same way, and Application action (#27) asks which application it applies to when chosen, and is added in advance when the order is opened from the application's task. Rescheduling's condition is in its own note, as before. **#3 Scheduling of hearing date** is offered only when the case has no hearing scheduled, and not in a hearing's own order. The order items table gains a **States** column: Moving case to and out of the long pending register (#22, #23) are offered in Kerala only; the rest are not yet decided. The mapping notes under the combination restrictions are removed. 2026-11-26 (24) — **#12 Issue of notice**: the notice type is chosen from one value, *Delay condonation notice*, which is also the default; more notice types may be added later. The note on the missing police station is removed. **#11 Withdrawal of case** is not linked to an application: it is chosen from the dropdown only, and has no variables. **Every variables table has a new shape**: *Mandatory to enter*, *Default value* and *Validation* (empty in every row) are merged into one **Logic** column, which says when a variable is shown, whether it is mandatory and its default; variables the system fills in say where from and that they cannot be edited. The note that bond amount and number of sureties are asked only for a bailable warrant is now in their rows. The explanation above the tables is aligned. 2026-11-25 (23) — **#10 Issue of warrants has its own variables table**, no longer shared with summons, proclamation and attachment. It gains **Warrant type** (Bailable or Non-bailable, mandatory) and, for a bailable warrant only, **Bond amount** and **Number of sureties**, both mandatory. 2026-11-10 (22) — **one order item per application**: Accept application (#5), Reject application (#6), Acceptance of bail (#13) and Dismiss application (#26) are withdrawn and replaced by **#27 Application action**, the order item through which an order acts on an application, whose questions are owned by [`application-lifecycle.md`](application-lifecycle.md) `ALC-38`. Accepting a Bail application triggers the Bail type's workflow (`ALC-16`); there is no separate bail acceptance item. Combination rule 4 is now one Application action per application per order. "Application types covered by generic accept/reject" is replaced by a pointer to application-lifecycle.md. The withdrawn items are in [`dropped-ideas.md`](dropped-ideas.md). 2026-10-22 (21) — rescheduling of hearing date (#4) is now a dropdown order item under Case management, offered only when the case already has a hearing scheduled and the order is not a hearing's own; it asks only the new hearing date and the purpose, the purpose defaulting to the one the hearing already has. 2026-10-20 (20) — dismissal no longer points at `APL-04`–`APL-06` of order-generation.md. 2026-10-19 (19) — templates dropped: retitled *Order item catalogue*; the Template column, the template notes and *How the template system works* moved to [`dropped-ideas.md`](dropped-ideas.md). The catalogue now holds the order items, their variables, workflows, availability, combination restrictions and hearing purposes. 2026-10-19 (18) — contextual order items can now be chosen on the order screen, and ask what they apply to (`ITM-04`). Channels, addresses and police station are fields of the order item like any other (`ITM-11` of order-generation.md removed). Locked / Optional column and the *Locked vs optional variables* section removed: a variable is mandatory to enter or not; the old text is in [`dropped-ideas.md`](dropped-ideas.md). 2026-10-06 (17) — accept, reject and acceptance of bail apply only once the
application is onboarded; before that it can only be dismissed. New contextual order item
**26. Dismiss application**, which cites no application number and names the application
by its type, the party that filed it and its filing date. 2026-10-06 (16) — added a stop-reading marker before "Not in V1":
everything after it is not required for V1. 2026-10-06 (15) — combination restrictions: removed the extension
accept/reject and Order under section 202 CrPC (not in V1) and the redundant mention of
generic accept/reject. 2026-10-06 (14) — general variables moved out of the variable lists into
"How the template system works", where they belong. 2026-10-06 (13) — availability is now only Dropdown or Contextual (stage
and ST/LP conditions removed), noted as reflecting the current order screen; witness
batta task is closed by confirming payment, not paid in the system. 2026-10-06 (12) — cost can also be received by the court; witness batta
names the witness (chosen from the case's witnesses, preselected when there is one) and
its template now says who. 2026-10-06 (11) — cost and witness batta split: cost is received by the
complainant or the accused, witness batta always by a witness. 2026-10-06 (10) — summons, warrants, proclamation and attachment share one
variable table, for convenience only; notice and miscellaneous process keep their own, each
with its extra variable. Proclamation and attachment templates name the party taking steps
as a variable instead of "Complainant". 2026-10-06 (8) — withdrawal can be ordered directly or on an application;
application number optional, its clause left out when there is none. 2026-10-06 (7) — withdrawal application number read-only from the
application, worded as accept/reject; those input types confirmed. 2026-10-06 (6) — summons/warrants person default follows `AUT-05`/`AUT-06`
of the process handover.
2026-10-06 (5) — summons and warrants: party type of the person is no longer an
input (taken from the person chosen); defaults set for the person and the party taking
steps; channels, addresses and police station added. 2026-10-06 (4) — rescheduling: original hearing date listed again as a
variable (the template needs it) with input type None. 2026-10-06 (3) — rescheduling:
original hearing date is no longer an input;
hearing purpose editable, defaulting to the purpose the hearing already has; nothing
defaults from the rescheduling request. 2026-10-06 (2) — scheduling of hearing date: no default for the date or the
purpose. 2026-10-06 — proposed input types for every remaining variable, marked
*(proposed)* until confirmed. 2026-10-05 (2) — variable tables gain an **Input type** column; **Autofill**
renamed **Default value** (preselected, not filled silently). Mandatory submissions:
response deadline and response task dropped, `[Document Name]` replaced by a
`[Document Details]` text field, input types set. ADR variables mandatory to enter.
Scheduling hearing purpose from MDMS hearing purposes. 2026-10-05 — restructured around **order items**. The main table now carries
only availability, category, template and workflow; variables moved to a per-order-item
list below it, with columns for meaning, locked/optional, mandatory to enter, autofill and
validation. Everything else moved underneath, unchanged. Under review item by item.
2026-09-25 — regrouped the order-issuance-screen categories: **Resolution** renamed to
**Disposal**, **Costs** renamed to **Miscellaneous**, **Bail** folded into a new
**Filings** category. Also flagged that the Dristi app was missing "Issue of miscellaneous
process" and carrying three out-of-scope order types (§ Not in V1) — both fixed in the app
the same day. 2026-09-17 — added the combination restrictions and the workflow trigger
order, carried over from the old system's Composite Order PRD; added the note that a
conditional variable has to record what it governs. All three are draft. 2026-09-07 —
first version.

Source: `Untitled spreadsheet.xlsx` (Sheet2) · 2026-09-07. Combination restrictions and
workflow order: `Composite Order.pdf` (old system PRD).

How an order is drafted from this configuration is owned by
[`order-generation.md`](order-generation.md).

---

## Terminology

- **Order** — the document the judge signs. It is numbered, signed and published.
- **Order item** — one entry in this catalogue. An order carries one or more order items;
  each has its own variables and, optionally, a workflow
  (`ORD-01`–`ORD-03` of [`order-generation.md`](order-generation.md)).
- **Workflow** — what the system does once the order is signed, because an order item is
  in it. A workflow is a property of the order item, not an order item itself.

---

## Order items

| # | Order item | Category | Workflow | States |
|---|---|---|---|---|
| 1 | Mandatory submissions and responses | Filings | Creates submission task | |
| 2 | Referral of case to ADR | Disposal | | |
| 3 | Scheduling of hearing date | Case management | Schedules next hearing | |
| 4 | Rescheduling of hearing date | Case management | Reschedules hearing | |
| 7 | Case transfer | Case management | | |
| 8 | Case settlement | Disposal | | |
| 9 | Issue of summons | Process | Triggers the summons workflow | |
| 10 | Issue of warrants | Process | Triggers the warrant workflow | |
| 11 | Withdrawal of case | Disposal | | |
| 12 | Issue of notice | Process | Triggers the notice workflow | |
| 14 | Cognizance | Case management | | |
| 15 | Judgement | Disposal | | |
| 16 | Dismiss case | Case management | | |
| 17 | Bail | Filings | Triggers the bail workflow | |
| 18 | Cost | Miscellaneous | Creates payment task | |
| 19 | Witness batta | Miscellaneous | Creates a task for the paying party, closed by confirming they have paid — the payment is not made through the system | |
| 20 | Issue of proclamation | Process | Triggers the proclamation workflow | |
| 21 | Issue of attachment | Process | Triggers the attachment workflow | |
| 22 | Moving case to long pending register | Case management | | Kerala |
| 23 | Moving case out of long pending register | Case management | | Kerala |
| 24 | Abate case | Disposal | | |
| 25 | Issue of miscellaneous process | Process | Triggers the miscellaneous process workflow | |
| 27 | Application action | | *(see note below)* | |

**Application action (#27).** The order item through which an order acts on an application ([`application-lifecycle.md`](application-lifecycle.md) `ALC-32`), at most one per application in an order. When chosen, it asks which application it applies to. It is also added in advance when the order is opened from the application's task, and can be removed (`ALC-32`; [`order-generation.md`](order-generation.md) `ITM-04`). Its questions — whether to onboard the application, whether the order decides it, the outcome (Accepted or Rejected once onboarded; Dismissed before), the CIS outcome, a date, and whether the other party must respond — are owned by `ALC-38`. Numbers 5, 6, 13 and 26 are withdrawn and not reused.

**States.** The states whose deployment offers the order item. A blank cell is not yet
decided.

**Category.** Groups order items on the order-issuance screen. Application action (#27)
has none.

**Application workflows belong to the application, not the order item.** When an
application is accepted, any workflow associated with that application type is triggered.
It is not listed in the Workflow column because it is a property of the application type,
not of the Application action (#27).

**Case stage changes are not workflows.** A listener watches order events and updates the
case stage when it sees specific order items (case transfer, settlement, dismissal,
abatement, moving to/from LP register, etc.). The Workflow column lists only workflows the
order item itself triggers.

---

## Variables by order item

A blank cell is not yet specified.

**Logic** says when a variable is shown, whether it is mandatory, and its default. A
default is what is preselected for the drafter to keep or change — not a value filled in
silently. A system-filled variable is taken from the record and cannot be edited.

Where one table covers several order items, they are still separate order items; they
share a table only because their variables are the same.

Input types marked *(proposed)* are a first guess, not yet confirmed.

How variables are resolved on the screen is owned by `VAR-01`–`VAR-11` of
[`order-generation.md`](order-generation.md); the defaults below are what those rules
give for each variable.

### 1. Mandatory submissions and responses

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[Party Type]` | Party directed to file | Dropdown — Complainant, Accused | Mandatory. |
| `[Document Type]` | Type of document to be filed | Dropdown — master data | Mandatory. |
| `[Document Details]` | Details of the document to be filed | Text | Mandatory. |
| `[Deadline for Submission]` | Date by which it must be filed | Date picker *(proposed)* | Mandatory. |

### 2. Referral of case to ADR

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[Mode of ADR]` | Mediation, arbitration, etc. | Dropdown — master data *(proposed)* | Mandatory. |
| `[Date of End of ADR]` | Deadline for the ADR to conclude | Date picker *(proposed)* | Mandatory. |

### 3. Scheduling of hearing date

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[Hearing Date]` | Date of the next hearing | Date picker *(proposed)* | Mandatory. |
| `[Hearing Purpose]` | Purpose of the next hearing | Dropdown — MDMS hearing purposes | Mandatory. |

Offered only when the case has no hearing scheduled; otherwise the date is moved with
*Rescheduling of hearing date* (#4). Not offered in a hearing's own order, where the next
date is set under Next hearing ([`order-generation.md`](order-generation.md) `ORD-09`).

### 4. Rescheduling of hearing date

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[New Hearing Date]` | Date it moves to | Date picker *(proposed)* | Mandatory. |
| `[Hearing Purpose]` | Purpose of the rescheduled hearing | Dropdown — MDMS hearing purposes | Mandatory. Defaults to the purpose the hearing already has. |
| `[Original Hearing Date]` | Date of the hearing being moved | None — from the hearing being moved | System-filled with the date the case's hearing is currently scheduled for; not editable. |

Offered only when the case already has a hearing scheduled. Not offered in a hearing's own
order, where the next date is set under Next hearing. Only the new hearing date and the
purpose are asked.

### 7. Case transfer · 8. Case settlement · 11. Withdrawal of case · 14. Cognizance · 15. Judgement · 16. Dismiss case · 22–23. Moving case to / out of long pending register · 24. Abate case

No variables.

### 9. Issue of summons · 20. Issue of proclamation · 21. Issue of attachment

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[Party Name]` | Person the process is addressed to | Dropdown — people in the case the process type may be addressed to; several may be chosen (`AUT-09`) | Mandatory. Defaults to every accused until the accused has joined the case; after that, to the one witness not yet examined if there is exactly one, otherwise empty (`AUT-05`, `AUT-06`). |
| `[Party Type]` | That person's party type | None — from the person chosen | System-filled from the person chosen; not editable. |
| `[Party Type]` | Party directed to take steps | Dropdown — Complainant, Accused *(proposed)* | Mandatory. Defaults to a party worked out from the person chosen: for the accused, the complainant; for the complainant, the accused; for a witness tagged to one side, that side; otherwise empty (`AUT-02`, `AUT-03`). |
| Channels | Delivery channels, per person | Multi-select — the channels available in the deployment for this process type (`PRC-03`, `PRC-04`) | Mandatory — at least one. Pre-selected by process type (`AUT-08`). |
| Addresses | Destination for each channel, per person | Multi-select — from the person's own record (`PRC-05`) | Mandatory. Every address on the person's record is pre-selected (`AUT-07`). |
| Police station | For a police channel only | Dropdown — police-station master (`PRC-08`) | Shown only on a police channel, and then mandatory. Pre-filled from the person's address (`AUT-04`). |

The rules for channels, addresses and police station are owned by
[`process.md`](process.md).

### 10. Issue of warrants

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[Warrant Type]` | Whether the warrant is bailable | Dropdown — Bailable, Non-bailable | Mandatory. |
| `[Bond Amount]` | Amount of the bond, in ₹ | Number, ₹ | Shown only when the warrant type is Bailable, and then mandatory. |
| `[Number of Sureties]` | How many sureties the bond needs | Number | Shown only when the warrant type is Bailable, and then mandatory. |
| `[Party Name]` | Person the process is addressed to | Dropdown — people in the case the process type may be addressed to; several may be chosen (`AUT-09`) | Mandatory. Defaults to every accused until the accused has joined the case; after that, to the one witness not yet examined if there is exactly one, otherwise empty (`AUT-05`, `AUT-06`). |
| `[Party Type]` | That person's party type | None — from the person chosen | System-filled from the person chosen; not editable. |
| `[Party Type]` | Party directed to take steps | Dropdown — Complainant, Accused *(proposed)* | Mandatory. Defaults to a party worked out from the person chosen: for the accused, the complainant; for the complainant, the accused; for a witness tagged to one side, that side; otherwise empty (`AUT-02`, `AUT-03`). |
| Channels | Delivery channels, per person | Multi-select — the channels available in the deployment for this process type (`PRC-03`, `PRC-04`) | Mandatory — at least one. Pre-selected by process type (`AUT-08`). |
| Addresses | Destination for each channel, per person | Multi-select — from the person's own record (`PRC-05`) | Mandatory. Every address on the person's record is pre-selected (`AUT-07`). |
| Police station | For a police channel only | Dropdown — police-station master (`PRC-08`) | Shown only on a police channel, and then mandatory. Pre-filled from the person's address (`AUT-04`). |

The rules for channels, addresses and police station are owned by
[`process.md`](process.md).

### 12. Issue of notice

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[Notice Type]` | Type of notice | Dropdown — Delay condonation notice | Mandatory. Defaults to Delay condonation notice. |
| `[Party Name]` | Person the process is addressed to | Dropdown — people in the case the process type may be addressed to; several may be chosen (`AUT-09`) | Mandatory. Defaults to every accused until the accused has joined the case; after that, to the one witness not yet examined if there is exactly one, otherwise empty (`AUT-05`, `AUT-06`). |
| `[Party Type]` | That person's party type | None — from the person chosen | System-filled from the person chosen; not editable. |
| `[Party Type]` | Party directed to take steps | Dropdown — Complainant, Accused *(proposed)* | Mandatory. Defaults to a party worked out from the person chosen: for the accused, the complainant; for the complainant, the accused; for a witness tagged to one side, that side; otherwise empty (`AUT-02`, `AUT-03`). |
| Channels | Delivery channels, per person | Multi-select — the channels available in the deployment for this process type (`PRC-03`, `PRC-04`) | Mandatory — at least one. Pre-selected by process type (`AUT-08`). |
| Addresses | Destination for each channel, per person | Multi-select — from the person's own record (`PRC-05`) | Mandatory. Every address on the person's record is pre-selected (`AUT-07`). |

Delay condonation notice is the only notice type for now; more may be added later, each
with its own template where needed ([`process.md`](process.md) `TPL-01`).

### 17. Bail

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[Plea]` | Guilty / not guilty | Dropdown — Guilty, Not guilty *(proposed)* | |

### 18. Cost

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[Party Type]` | Paying party | Dropdown — Complainant, Accused *(proposed)* | Mandatory. |
| `[Amount]` | Amount, in ₹ | Number, ₹ *(proposed)* | Mandatory. |
| `[Party Type]` | Receiving party | Dropdown — Complainant, Accused, Court | Mandatory. |
| `[Date]` | Date by which it must be paid | Date picker *(proposed)* | Mandatory. |

### 19. Witness batta

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[Party Type]` | Paying party | Dropdown — Complainant, Accused *(proposed)* | Mandatory. |
| `[Amount]` | Amount, in ₹ | Number, ₹ *(proposed)* | Mandatory. |
| `[Party Type]` | Receiving party — always a witness | None — always Witness | System-filled as Witness; not editable. |
| `[Party Name]` | The witness receiving it | Dropdown — witnesses in the case | Mandatory. Defaults to the witness, where the case has exactly one. |
| `[Date]` | Date by which it must be paid | Date picker *(proposed)* | Mandatory. |

### 25. Issue of miscellaneous process

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[Process Type]` | Type of process | Dropdown — master data *(proposed)* | Mandatory. |
| `[Party Name]` | Person the process is addressed to | Dropdown — people in the case the process type may be addressed to; several may be chosen (`AUT-09`) | Mandatory. Defaults to every accused until the accused has joined the case; after that, to the one witness not yet examined if there is exactly one, otherwise empty (`AUT-05`, `AUT-06`). |
| `[Party Type]` | That person's party type | None — from the person chosen | System-filled from the person chosen; not editable. |
| `[Party Type]` | Party directed to take steps | Dropdown — Complainant, Accused *(proposed)* | Mandatory. Defaults to a party worked out from the person chosen: for the accused, the complainant; for the complainant, the accused; for a witness tagged to one side, that side; otherwise empty (`AUT-02`, `AUT-03`). |
| Channels | Delivery channels, per person | Multi-select — the channels available in the deployment for this process type (`PRC-03`, `PRC-04`) | Mandatory — at least one. Pre-selected by process type (`AUT-08`). |
| Addresses | Destination for each channel, per person | Multi-select — from the person's own record (`PRC-05`) | Mandatory. Every address on the person's record is pre-selected (`AUT-07`). |
| Police station | For a police channel only | Dropdown — police-station master (`PRC-08`) | Shown only on a police channel, and then mandatory. Pre-filled from the person's address (`AUT-04`). |

As for the four above, with the type of process added.

### 27. Application action

| Variable | Meaning | Input type | Logic |
|---|---|---|---|
| `[Application Number]` | The application acted on | Read-only — from the application | System-filled from the application the order item was reached from; not editable. |
| `[Application Type]` | Its type | Read-only — from the application | System-filled from the application the order item was reached from; not editable. |

Its questions are not variables: they are listed in [`application-lifecycle.md`](application-lifecycle.md) `ALC-38`.

---

## Combination restrictions

**Draft.** Carried over from the old system's Composite Order PRD and mapped onto the order
types above. To be finalised.

One order may carry several order items. These are the combinations that cannot stand in
the same order. The screen enforces them when an order item is added and shows the message
([`order-generation.md`](order-generation.md), §5).

| # | Rule | Order types it applies to | Message |
|---|---|---|---|
| 1 | Only **one case-closing order item** per order | Judgement · Dismiss case · Case settlement · Withdrawal of case · Case transfer · Referral of case to ADR · Abate case | You cannot add both *[order being added]* and *[order it clashes with]* |
| 2 | **Cognizance and Dismiss case** cannot stand in the same order, and neither may be repeated | Cognizance · Dismiss case | You cannot add both *[order being added]* and *[order it clashes with]* |
| 3 | Only **one hearing-date order item** per order | Scheduling of hearing date · Rescheduling of hearing date | You cannot add two *[order type]* items |
| 4 | Only **one Application action per application** | Application action | You cannot add two responses to the same application |
| 5 | **No restriction** — may be repeated and combined freely | Issue of summons · warrants · notice · proclamation · attachment · miscellaneous process · Mandatory submissions and responses · Cost · Witness batta · Bail · Moving case to / out of long pending register | |

---

## Workflow trigger order

**Draft**, same source. Workflows are triggered when the order is signed
([`order-generation.md`](order-generation.md), `PUB-03`). Where one order item's workflow
affects another's, the sequence matters:

| # | Triggered | Which order items |
|---|---|---|
| 1 | First | Scheduling of hearing date · Rescheduling of hearing date — so every other workflow in the same order acts on the new hearing date |
| 2 | Then | Every other order item, in the sequence the order lists them |
| 3 | Last | The case-closing order items of rule 1 above |

An order item's workflow is the same whether it stands alone in an order or alongside
others.

---

> **V1 readers can stop here.** Nothing from this point on is required for V1 — it is kept
> for reference and future work.

## Not in V1

Order types outside V1 scope. Kept here for future reference; they are not offered in V1.

| Order type | Was | Variables | Workflow |
|---|---|---|---|
| Order under section 202 CrPC | Yes (Cognizance) | *(none)* | *(none)* |
| Accept extension for submission deadline | No (application) | `[Application Number]` · `[Document Type]` · `[Document Name]` · `[Party Type]` · `[New Submission Date]` | Updates submission deadline |
| Reject extension for submission deadline | No (application) | `[Application Number]` · `[Document Type]` · `[Document Name]` | |

---

## Application types

Application action (#27) covers every application type. The types, and the workflow each triggers on acceptance, are in "Application types" of [`application-lifecycle.md`](application-lifecycle.md).

---

## Hearing purposes

Merged from both codebases and the attendance requirements table.

**Order types available at any hearing:** Scheduling of hearing date, Cost, Mandatory submissions, Withdrawal of case, Case transfer, Moving to/from LP register, Abate case. These are generic — they are always available and not repeated in every row below.

The table below has two kinds of actions: **order types** (from the order type catalogue above) and **section workflows** (marked with ⚙). Section workflows are not order types — they are dedicated screens for recording specific procedural steps during a hearing. Each opens its own form for the magistrate to enter structured details. They produce a record that becomes part of the case file.

### Section workflows

| ID | Section workflow | Description |
|---|---|---|
| ⚙ Recording of plea | Plea under S. 274 of the Sanhita | Records the accused's plea (guilty / not guilty) and the particulars of the offence as read and explained |
| ⚙ Examination of the accused | Examination under S. 351 BNSS | Records the statement of the accused when examined by the court |
| ⚙ Evidence of the complainant | Complainant evidence | Records the complainant's evidence — documents, testimony, affidavit evidence |
| ⚙ Examination of the witness | Witness examination | Records witness testimony — examination-in-chief, cross-examination, re-examination |

### Hearing purpose → actions

| # | Hearing purpose | People required | Likely order types and section workflows |
|---|---|---|---|
| 1 | Condonation of delay | Complainant Advocate, Accused Advocate | Dismiss case |
| 2 | Admission | Complainant Advocate, Accused Advocate | Cognizance, Dismiss case, Issue of summons |
| 3 | Delay condonation and admission | Complainant Advocate, Accused Advocate | Cognizance, Dismiss case, Issue of summons |
| 4 | Cognizance | Complainant Advocate, Accused Advocate | Cognizance, Dismiss case, Issue of summons |
| 5 | Appearance | Accused, Accused Advocate | Issue of summons, Issue of warrants, Bail, Issue of notice |
| 6 | Bail | Accused, Accused Advocate | Bail, Application action, Issue of warrants |
| 7 | Plea | Accused, Accused Advocate | Bail, Referral to ADR, Issue of notice · ⚙ Recording of plea |
| 8 | Evidence of the complainant | Complainant, Complainant Advocate, Accused Advocate | Witness batta, Issue of summons (for witnesses) · ⚙ Evidence of the complainant, ⚙ Examination of the witness |
| 9 | Examination of the accused under S. 351 BNSS | Accused, Accused Advocate | Issue of warrants · ⚙ Examination of the accused |
| 10 | Evidence of the accused | Complainant Advocate, Accused, Accused Advocate | Witness batta, Issue of summons (for witnesses) · ⚙ Examination of the witness |
| 11 | Arguments | Complainant Advocate, Accused Advocate | Referral to ADR, Case settlement |
| 12 | Judgement | Accused Advocate | Judgement |
| 13 | For reports (forensics, ADR, etc.) | | Referral to ADR |
| 14 | ADR | | Referral to ADR, Case settlement |
| 15 | Mediation | | Referral to ADR, Case settlement |
| 16 | Warrant | | Issue of warrants, Issue of proclamation, Issue of attachment, Bail |
| 17 | Execution | | Issue of attachment, Issue of warrants |
| 18 | Review application | | |
| 19 | To issue order | | *(any order — generic hearing for issuing pending orders)* |
| 20 | Review application | | |

**Notes:**
- "Delay condonation and admission" (#3) is a combined hearing that covers two purposes in one sitting.
- "People required" is blank where attendance rules are not yet defined.
- The "Likely order types" column lists order types *specific* to this hearing — the generic types listed above (scheduling, cost, submissions, etc.) are always available and not repeated.
- Section workflows (⚙) are surfaced as buttons alongside the order type dropdown. They open dedicated screens.
- #18 and #20 both cover application review — they exist as separate entries in the two codebases but are the same hearing purpose.

