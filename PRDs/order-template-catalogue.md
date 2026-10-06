# Order template catalogue

**Status:** 2026-10-06 (17) — accept, reject and acceptance of bail apply only once the
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
  each has its own template, variables and, optionally, a workflow
  (`ORD-01`–`ORD-03` of [`order-generation.md`](order-generation.md)).
- **Workflow** — what the system does once the order is signed, because an order item is
  in it. A workflow is a property of the order item, not an order item itself.

---

## Order items

| # | Order item | Availability | Category | Template | Workflow |
|---|---|---|---|---|---|
| 1 | Mandatory submissions and responses | Dropdown | Filings | It is directed that the [Party Type] files a [Document Type] for [Document Details] before the court by [Deadline for Submission]. | Creates submission task |
| 2 | Referral of case to ADR | Dropdown | Disposal | Both the Parties have voluntarily agreed to seek resolution through [Mode of ADR]. The parties are hereby referred to [Mode of ADR] to resolve their dispute by [Date of End of ADR]. | |
| 3 | Scheduling of hearing date | Dropdown | Case management | Next hearing is scheduled on [Hearing Date] for [Hearing Purpose]. | Schedules next hearing |
| 4 | Rescheduling of hearing date | Contextual | | Next hearing scheduled on [Original Hearing Date] for [Hearing Purpose] has been rescheduled to [New Hearing Date]. | Reschedules hearing |
| 5 | Accept application | Contextual | | Application [Application Number] for [Application Type] is accepted. | *(see note below)* |
| 6 | Reject application | Contextual | | Application [Application Number] for [Application Type] is rejected. | |
| 7 | Case transfer | Dropdown | Case management | The case is transferred to another court for further proceedings. | |
| 8 | Case settlement | Dropdown | Disposal | The settlement records have been accepted by the court. Case closed. | |
| 9 | Issue of summons | Dropdown | Process | Issue summons to the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps to issue summons. | Triggers the summons workflow |
| 10 | Issue of warrants | Dropdown | Process | Issue warrant to the [Party Type] [Party Name]. The [Party Type] is directed to take steps to issue warrant. | Triggers the warrant workflow |
| 11 | Withdrawal of case | Dropdown or contextual | Disposal | As per application [Application Number] complainant has sought to withdraw the complaint. Permission under Section 280 of the BNSS is granted and the Accused is acquitted. | |
| 12 | Issue of notice | Dropdown | Process | Issue [Notice Type] notice to the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps. | Triggers the notice workflow |
| 13 | Acceptance of bail | Contextual | | Application [Application Number] is accepted. | Optionally triggers bail bond submission workflow (magistrate specifies terms of bail) |
| 14 | Cognizance | Dropdown | Case management | Considering the materials produced before the Court, I am prima facie satisfied that the offence punishable under S. 138 of NI Act is made out. Accordingly cognizance of the offence is taken and the case is taken on file. | |
| 15 | Judgement | Dropdown | Disposal | *(dedicated judgement screen — template to be finalised)* | |
| 16 | Dismiss case | Dropdown | Case management | The case is dismissed. | |
| 17 | Bail | Dropdown | Filings | Accused is released on bail. Particulars of offences u/s.138 of NI Act were read over and explained to the Accused to which he pleaded [Plea] and claimed to be tried. | Triggers the bail workflow |
| 18 | Cost | Dropdown | Miscellaneous | The [Party Type] is directed to pay [Amount] to the [Party Type] as costs by [Date]. | Creates payment task |
| 19 | Witness batta | Dropdown | Miscellaneous | The [Party Type] is directed to pay [Amount] to the [Party Type] [Party Name] as witness batta by [Date]. | Creates a task for the paying party, closed by confirming they have paid — the payment is not made through the system |
| 20 | Issue of proclamation | Dropdown | Process | Issue proclamation to the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps. | Triggers the proclamation workflow |
| 21 | Issue of attachment | Dropdown | Process | Issue attachment against the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps. | Triggers the attachment workflow |
| 22 | Moving case to long pending register | Dropdown | Case management | As per sanction given by Honourable CJM the case is moved to the Long Pending Register and is marked as LP. | |
| 23 | Moving case out of long pending register | Dropdown | Case management | The case is moved out of the Long Pending Register and is to be considered and renumbered as a ST case. | |
| 24 | Abate case | Dropdown | Disposal | The case is abated following the death of the Accused party. | |
| 25 | Issue of miscellaneous process | Dropdown | Process | Issue [Process Type] to the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps. | Triggers the miscellaneous process workflow |
| 26 | Dismiss application | Contextual | | Application for [Application Type] filed by the [Party Type] [Party Name] on [Filing Date] is dismissed. | |

**Availability.** *Dropdown* order items can be picked by the judge on the order-issuance
screen. *Contextual* order items are not in the dropdown — they arrive from the thing that
produces them, such as an application being decided (`ITM-04` of
[`order-generation.md`](order-generation.md)). This split reflects the current order
screen; a different design of the order screen may set it aside.

**Onboarded applications only, except dismissal.** Accept application (#5), Reject
application (#6) and Acceptance of bail (#13) — the specific acceptance of a bail
application — apply only once the application has been onboarded. Before onboarding, the
only order item for an application is **Dismiss application** (#26). An application that
is not onboarded has no application number, so #26 names it by its type, the party that
filed it and its filing date. Onboarding and dismissal are owned by `ALC-04` and
`ALC-19` of [`application-lifecycle.md`](application-lifecycle.md) and `APL-04`–`APL-06` of
[`order-generation.md`](order-generation.md).

**Category.** Groups dropdown order items on the order-issuance screen. Contextual order
items have none.

**Application workflows belong to the application, not the order item.** When an
application is accepted, any workflow associated with that application type is triggered.
It is not listed in the Workflow column because it is a property of the application type,
not of the "accept application" order item.

**Case stage changes are not workflows.** A listener watches order events and updates the
case stage when it sees specific order items (case transfer, settlement, dismissal,
abatement, moving to/from LP register, etc.). The Workflow column lists only workflows the
order item itself triggers.

**Template text and order text.** The template seeds the order text; there is no second,
shorter wording. The order's own text is the record and goes into the A-Diary (`TXT-04`
of [`order-generation.md`](order-generation.md)).

---

## Variables by order item

**Locked** variables are needed by the workflow and cannot be removed. **Optional**
variables can be added or removed freely. A blank cell is not yet specified.

Listed are the variables that may be an input, and any other variable an order item's
template needs — that one is shown with input type *None*. Much else in the case may be
relevant and pulled into the text, but it is not listed here unless the template uses it.
**Default value** is what is preselected for the drafter to keep or change — not a value
filled in silently.

Where one table covers several order items, they are still separate order items; they
share a table only because their variables are the same.

Input types marked *(proposed)* are a first guess, not yet confirmed.

How variables are resolved on the screen is owned by `VAR-01`–`VAR-11` of
[`order-generation.md`](order-generation.md); the default values below are what those
rules give for each variable.

### 1. Mandatory submissions and responses

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Party Type]` | Party directed to file | Dropdown — Complainant, Accused | Locked | Yes | | |
| `[Document Type]` | Type of document to be filed | Dropdown — master data | Locked | Yes | | |
| `[Document Details]` | Details of the document to be filed | Text | Locked | Yes | | |
| `[Deadline for Submission]` | Date by which it must be filed | Date picker *(proposed)* | Locked | Yes | | |

### 2. Referral of case to ADR

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Mode of ADR]` | Mediation, arbitration, etc. | Dropdown — master data *(proposed)* | Optional | Yes | | |
| `[Date of End of ADR]` | Deadline for the ADR to conclude | Date picker *(proposed)* | Optional | Yes | | |

### 3. Scheduling of hearing date

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Hearing Date]` | Date of the next hearing | Date picker *(proposed)* | Locked | Yes | None | |
| `[Hearing Purpose]` | Purpose of the next hearing | Dropdown — MDMS hearing purposes | Locked | Yes | None — entered by the drafter | |

### 4. Rescheduling of hearing date

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Original Hearing Date]` | Date of the hearing being moved | None — from the hearing being moved | Locked | No | | |
| `[Hearing Purpose]` | Purpose of the rescheduled hearing | Dropdown — MDMS hearing purposes | Locked | Yes | The purpose the hearing already has | |
| `[New Hearing Date]` | Date it moves to | Date picker *(proposed)* | Locked | Yes | | |

### 5. Accept application · 6. Reject application

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Application Number]` | Application being decided | Read-only — from the application | Locked | Yes | From the application the order item was reached from | |
| `[Application Type]` | Its type | Read-only — from the application | Locked | Yes | From the application the order item was reached from | |

### 7. Case transfer · 8. Case settlement · 14. Cognizance · 15. Judgement · 16. Dismiss case · 22–23. Moving case to / out of long pending register · 24. Abate case

No variables.

### 9. Issue of summons · 10. Issue of warrants · 20. Issue of proclamation · 21. Issue of attachment

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Party Name]` | Person the process is addressed to | Dropdown — people in the case the process type may be addressed to; several may be chosen (`AUT-09`) | Locked | Yes | Every accused until the accused has joined the case; after that, the one witness not yet examined if there is exactly one, otherwise empty (`AUT-05`, `AUT-06`) | |
| `[Party Type]` | That person's party type | None — from the person chosen | Locked | No | | |
| `[Party Type]` | Party directed to take steps | Dropdown — Complainant, Accused *(proposed)* | Locked | Yes | Worked out from the person chosen: for the accused, the complainant; for the complainant, the accused; for a witness tagged to one side, that side; otherwise empty (`AUT-02`, `AUT-03`) | |
| Channels | Delivery channels, per person | Multi-select — the channels available in the deployment for this process type (`PRC-03`, `PRC-04`) | Locked | Yes — at least one | Pre-selected by process type (`AUT-08`) | |
| Addresses | Destination for each channel, per person | Multi-select — from the person's own record (`PRC-05`) | Locked | Yes | Every address on the person's record (`AUT-07`) | |
| Police station | For a police channel only | Dropdown — police-station master (`PRC-08`) | Locked | On a police channel | From the person's address (`AUT-04`) | |

Channels, addresses and police station are not in the template. They are inputs the
process workflow needs, asked for as part of the order item (`ITM-11` of
[`order-generation.md`](order-generation.md)); their rules are owned by
[`process-handover.md`](process-handover.md).

### 11. Withdrawal of case

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Application Number]` | The withdrawal application, where there is one | Read-only — from the application | Optional | Only when reached from an application | From the application the order item was reached from | |

Withdrawal may be ordered on an application or directly. When it is chosen from the
dropdown there is no application, and the clause "As per application [Application
Number]" is left out of the text. The configuration has to record that this clause is the
one `[Application Number]` governs.

### 12. Issue of notice

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Notice Type]` | Type of notice | Dropdown — master data *(proposed)* | Locked | Yes | | |
| `[Party Name]` | Person the process is addressed to | Dropdown — people in the case the process type may be addressed to; several may be chosen (`AUT-09`) | Locked | Yes | Every accused until the accused has joined the case; after that, the one witness not yet examined if there is exactly one, otherwise empty (`AUT-05`, `AUT-06`) | |
| `[Party Type]` | That person's party type | None — from the person chosen | Locked | No | | |
| `[Party Type]` | Party directed to take steps | Dropdown — Complainant, Accused *(proposed)* | Locked | Yes | Worked out from the person chosen: for the accused, the complainant; for the complainant, the accused; for a witness tagged to one side, that side; otherwise empty (`AUT-02`, `AUT-03`) | |
| Channels | Delivery channels, per person | Multi-select — the channels available in the deployment for this process type (`PRC-03`, `PRC-04`) | Locked | Yes — at least one | Pre-selected by process type (`AUT-08`) | |
| Addresses | Destination for each channel, per person | Multi-select — from the person's own record (`PRC-05`) | Locked | Yes | Every address on the person's record (`AUT-07`) | |

A notice takes no police channel, so there is no police station. Otherwise as for the
four above.

### 13. Acceptance of bail

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Application Number]` | The bail application | Read-only — from the application *(proposed)* | Locked | Yes | From the application the order item was reached from | |

### 17. Bail

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Plea]` | Guilty / not guilty | Dropdown — Guilty, Not guilty *(proposed)* | Optional | |  | |

### 18. Cost

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Party Type]` | Paying party | Dropdown — Complainant, Accused *(proposed)* | Locked | Yes | | |
| `[Amount]` | Amount, in ₹ | Number, ₹ *(proposed)* | Locked | Yes | | |
| `[Party Type]` | Receiving party | Dropdown — Complainant, Accused, Court | Locked | Yes | | |
| `[Date]` | Date by which it must be paid | Date picker *(proposed)* | Locked | Yes | | |

### 19. Witness batta

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Party Type]` | Paying party | Dropdown — Complainant, Accused *(proposed)* | Locked | Yes | | |
| `[Amount]` | Amount, in ₹ | Number, ₹ *(proposed)* | Locked | Yes | | |
| `[Party Type]` | Receiving party — always a witness | None — always Witness | Locked | No | | |
| `[Party Name]` | The witness receiving it | Dropdown — witnesses in the case | Locked | Yes | The witness, where the case has exactly one | |
| `[Date]` | Date by which it must be paid | Date picker *(proposed)* | Locked | Yes | | |

### 25. Issue of miscellaneous process

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Process Type]` | Type of process | Dropdown — master data *(proposed)* | Locked | Yes | | |
| `[Party Name]` | Person the process is addressed to | Dropdown — people in the case the process type may be addressed to; several may be chosen (`AUT-09`) | Locked | Yes | Every accused until the accused has joined the case; after that, the one witness not yet examined if there is exactly one, otherwise empty (`AUT-05`, `AUT-06`) | |
| `[Party Type]` | That person's party type | None — from the person chosen | Locked | No | | |
| `[Party Type]` | Party directed to take steps | Dropdown — Complainant, Accused *(proposed)* | Locked | Yes | Worked out from the person chosen: for the accused, the complainant; for the complainant, the accused; for a witness tagged to one side, that side; otherwise empty (`AUT-02`, `AUT-03`) | |
| Channels | Delivery channels, per person | Multi-select — the channels available in the deployment for this process type (`PRC-03`, `PRC-04`) | Locked | Yes — at least one | Pre-selected by process type (`AUT-08`) | |
| Addresses | Destination for each channel, per person | Multi-select — from the person's own record (`PRC-05`) | Locked | Yes | Every address on the person's record (`AUT-07`) | |
| Police station | For a police channel only | Dropdown — police-station master (`PRC-08`) | Locked | On a police channel | From the person's address (`AUT-04`) | |

As for the four above, with the type of process added.

### 26. Dismiss application

| Variable | Meaning | Input type | Locked / Optional | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|---|
| `[Application Type]` | Type of the application being dismissed | Read-only — from the application | Locked | Yes | From the application the order item was reached from | |
| `[Party Type]` | Party type of the person who filed it | Read-only — from the application | Locked | Yes | From the application the order item was reached from | |
| `[Party Name]` | Person who filed it | Read-only — from the application | Locked | Yes | From the application the order item was reached from | |
| `[Filing Date]` | Date the application was filed | Read-only — from the application | Locked | Yes | From the application the order item was reached from | |

There is no `[Application Number]`: the application is not onboarded, so it has none.

---

## Categories summary

| Category | Order items | Count |
|---|---|---|
| Filings | Mandatory submissions, Bail | 2 |
| Disposal | Referral to ADR, Case settlement, Withdrawal, Abate case, Judgement | 5 |
| Case management | Scheduling of hearing, Case transfer, Moving to/from LP register, Cognizance, Dismiss case | 6 |
| Process | Issue of summons, warrants, notice, proclamation, attachment, miscellaneous process | 6 |
| Miscellaneous | Cost, Witness batta | 2 |

Regrouped 2026-09-25, owner's own reorganisation, in two passes:

1. **Resolution → Disposal**; **Costs → Miscellaneous**; **Bail** folded into **Filings**
   (its only member, Bail, moved there); **Filings** is new — home for mandatory
   submissions and any future dropdown order tied to an application or a workflow it
   starts. **Case management** lost Mandatory submissions to Filings, dropping from 5 to
   4.
2. **Cognizance and Judgment folded in**, each having stood alone for a single row or
   two: **Judgement** moved into **Disposal** (it ends the case, like the rest of that
   category); **Cognizance** and **Dismiss case** moved into **Case management**, taking
   it from 4 to 6. Neither Cognizance nor Judgment survives as its own category.

Still to add: case stages where each order item is most likely issued.

---

## Combination restrictions

**Draft.** Carried over from the old system's Composite Order PRD and mapped onto the order
types above; where a type was renamed the mapping is noted below. To be finalised.

One order may carry several order items. These are the combinations that cannot stand in
the same order. The screen enforces them when an order item is added and shows the message
([`order-generation.md`](order-generation.md), §5).

| # | Rule | Order types it applies to | Message |
|---|---|---|---|
| 1 | Only **one case-closing order item** per order | Judgement · Dismiss case · Case settlement · Withdrawal of case · Case transfer · Referral of case to ADR · Abate case | You cannot add both *[order being added]* and *[order it clashes with]* |
| 2 | **Cognizance and Dismiss case** cannot stand in the same order, and neither may be repeated | Cognizance · Dismiss case | You cannot add both *[order being added]* and *[order it clashes with]* |
| 3 | Only **one hearing-date order item** per order | Scheduling of hearing date · Rescheduling of hearing date | You cannot add two *[order type]* items |
| 4 | Only **one decision per application or request** | Accept application · Reject application · Acceptance of bail · Dismiss application | You cannot add two responses to the same application |
| 5 | **No restriction** — may be repeated and combined freely | Issue of summons · warrants · notice · proclamation · attachment · miscellaneous process · Mandatory submissions and responses · Cost · Witness batta · Bail · Moving case to / out of long pending register | |

Mapping notes, for anyone checking this against the source:

- The old *Order to Admit Case* is **Cognizance** here — both are the order taking the case
  on file.
- The old *Response to Application for Case Withdrawal / Settlement / Case Transfer* are
  **Withdrawal of case**, **Case settlement** and **Case transfer**.
- The old *Order to Reschedule Case* row was struck out in the source and is not carried
  over.
- **Abate case** is not in the old closing set. It is added here because it ends the case.
  Confirm.
- **Referral of case to ADR** is in the old closing set, although a case can come back from
  ADR. Carried over as it stands. Confirm.

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

Order types removed from V1 scope. Retained here for future reference.

The Dristi app's `order-templates.ts` carried all three of these as live, selectable
order types until 2026-09-25 — a drift from this doc that had gone unnoticed. Removed
from the app (screen, hearing-purpose suggestions, and tests) on that date to match V1
scope.

| Order type | Was | Template | Locked variables | Workflow |
|---|---|---|---|---|
| Order under section 202 CrPC | Yes (Cognizance) | *(no template)* | *(none)* | *(none)* |
| Accept extension for submission deadline | No (application) | Application [Application Number] for extension of deadline of submission of [Document Type] for [Document Name] is accepted. The [Party Type] is required to submit the same by [New Submission Date]. | `[Application Number]` · `[Document Type]` · `[Document Name]` · `[Party Type]` · `[New Submission Date]` | Updates submission deadline |
| Reject extension for submission deadline | No (application) | Application [Application Number] for extension of deadline of submission of [Document Type] for [Document Name] is rejected. | `[Application Number]` · `[Document Type]` · `[Document Name]` | |

---

## Application types covered by generic accept/reject

The generic "Accept application" (#5) and "Reject application" (#6) rows above replace what were previously separate order types. These application types all use the same template and have no order-level workflow — any workflow triggered belongs to the application type itself.

| Application type | Notes |
|---|---|
| Voluntary submission | |
| Delay condonation (DCA) | |
| Bail (rejection only) | Bail acceptance is a separate order (#13) because it optionally triggers the bail bond submission workflow |
| Changes in litigant details | |
| Advocate replacement | Currently a task, not an application — has no application number |
| Change in power of attorney | "No such order" noted in source spreadsheet |

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
| 6 | Bail | Accused, Accused Advocate | Bail, Acceptance of bail, Issue of warrants |
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
- Section workflows (⚙) are surfaced as buttons alongside the order type dropdown. They open dedicated screens, not templates.
- #18 and #20 both cover application review — they exist as separate entries in the two codebases but are the same hearing purpose.

---

## How the template system works

### The concept

Every order is generated from a **template** — a piece of text with **variables** in square brackets. When the judge issues an order, the system fills in the variables and produces the final order text.

Some variables can be filled automatically from the case record (the general variables below). Others require the judge to make a choice — picking a party, entering a date, selecting a hearing purpose. The system pre-fills what it can and presents the rest as fields for the judge to complete.

### What the system fills automatically

**General variables** (Court Name, Case Name, Case Number, Current Date, Judge Name, Judge Designation, Complainant Name, Accused Name) are always resolved from case and court data. The judge never types these.

#### General variables

Available to every order template, filled automatically — the judge does not type them.

| Variable | Source | Meaning |
|---|---|---|
| `[Court Name]` | Court data | Name of the court |
| `[Case Name]` | Case data | e.g. "X vs Y" |
| `[Case Number]` | Case data | Case number |
| `[Current Date]` | System | Today's date |
| `[Judge Name]` | Court data | Presiding judge |
| `[Judge Designation]` | Court data | e.g. JMFC |
| `[Complainant Name]` | Case data | Name of the complainant |
| `[Accused Name]` | Case data | Name of the accused |
| `[Party Type]` | Case data | Complainant, Accused, or Witness |
| `[Party Name]` | Case data | Any person in the case — complainant, accused, witness, or PoA holder |
| `[Document Type]` | Master data | Type of document (e.g. complaint, affidavit, vakalat) |
| `[Hearing Purpose]` | Master data | Purpose of hearing (e.g. Appearance, Evidence, Arguments) |
| `[Current Hearing Date]` | Case data | Date of the current/most recent hearing |

**Application context.** When the judge is acting on an application (accept/reject), the Application Number and Application Type are already known — the judge arrived at this order from the application itself. These are filled automatically.

**Workflow context.** When an order is the output of a workflow (e.g. a rescheduling order follows from a rescheduling request), variables that the workflow already collected are pre-filled.

### What the judge must specify

The system cannot fill a variable when it requires a **choice among multiple options**. The judge must specify:

- **Which party**, when the case has more than one person of a given type. A §138 case typically has one complainant and one accused, but there can be multiple accused (e.g. the drawer and the company director). When the system encounters `[Party Name]` and there are multiple candidates, it presents a selector. If there is only one person of that type, it fills automatically.
- **Dates** that are set by the judge's discretion — a submission deadline, a new hearing date, the end date for ADR. The system cannot guess these.
- **Amounts** — cost and witness batta amounts are the judge's decision.
- **Selections from master data** — hearing purpose, document type, mode of ADR, notice type. These are dropdowns drawn from master data, not free text.

### Locked vs optional variables

**Locked variables** are required by the workflow that this order triggers. They cannot be removed from the template because the workflow depends on them to function. For example, the summons workflow needs to know which party is being summoned (`[Party Type]`, `[Party Name]`) and which party must take steps — without these, the system cannot create the correct task.

**Optional variables** can be added to or removed from a template by a system administrator. They enrich the order text but no workflow depends on them. For example, `[Plea]` in the bail order is optional — the bail workflow does not need it to release the accused, but the court record is better for having it.

**General variables** are always available to any template. A template author can reference any general variable in any template. They do not appear in the locked or optional columns because they are universally available, not specific to a particular order type.

### What the judge can customise

The judge works with the **generated text**, not the template. After the system fills in all the variables, the judge sees the complete order text and can:

- **Edit the text** freely — add sentences, remove paragraphs, correct wording. The template is a starting point, not a constraint.
- **Add additional comments** — a free-text area for anything the template does not cover.

The judge **cannot** change the template itself. Templates are system configuration managed by an administrator. What the judge produces is an order — a document — not a new template.

### How variables resolve at generation time

1. The judge selects an order type (from the dropdown, or by acting on an application).
2. The system loads the template for that order type.
3. **Auto-fill pass:** general variables and context variables (application number, workflow data) are filled in.
4. **Judge input pass:** the system presents any remaining unfilled variables as form fields — dropdowns for master data selections, date pickers for dates, party selectors for party references, text inputs for free values.
5. The judge fills the remaining fields and confirms.
6. The system generates the complete order text.
7. The judge reviews, optionally edits, and signs.

If an order type has **no template** (e.g. Order under section 202 CrPC), the judge writes the order text from scratch — or a dedicated screen handles it (e.g. Judgement).
