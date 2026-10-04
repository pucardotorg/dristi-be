# Order template catalogue

**Status:** 2026-09-25 — regrouped the order-issuance-screen categories: **Resolution**
renamed to **Disposal**, **Costs** renamed to **Miscellaneous**, **Bail** folded into a
new **Filings** category (home for mandatory submissions and future application/workflow
orders). Also flagged that the Dristi app was missing "Issue of miscellaneous process"
and carrying three out-of-scope order types (§ Not in V1) — both fixed in the app the same
day. 2026-09-17 — added the combination restrictions and the workflow trigger order,
carried over from the old system's Composite Order PRD and mapped onto the order types
here; added the note that a conditional variable has to record what it governs. All three
are draft. 2026-09-07 — first version.

Source: `Untitled spreadsheet.xlsx` (Sheet2) · 2026-09-07. Combination restrictions and
workflow order: `Composite Order.pdf` (old system PRD).

Still to add: case stages where each order is most likely issued.

How an order is drafted from this configuration is owned by
[`order-generation.md`](order-generation.md).

---

## Notes

**Case stage changes are not workflows.** A listener monitors all order events. When it sees specific order types (case transfer, settlement, dismissal, abatement, moving to/from LP register, etc.), it updates the case stage accordingly. The Workflow column below only lists workflows that the order itself triggers.

**Application workflows belong to the application, not the order.** When an application is accepted, any workflow associated with that application type is triggered. We do not list these in the Workflow column because the workflow is a property of the application type, not of the "accept application" order.

**"In dropdown" vs application orders.** Orders marked "Yes" in the dropdown column can be manually selected by the judge from the order generation screen. Orders marked "No" are not in the dropdown — they appear only in context (e.g. when the judge is acting on an application).

**Category.** Groups the order type on the order-issuance screen. Only populated for orders that appear in the dropdown; contextual orders (In dropdown = No) are surfaced by the action that triggers them, not by category.

**Template text and order text.** The template text below seeds the order text. There is no second, shorter wording of the same order: the order's own text is the record and is what goes into the A-Diary (`TXT-04` of [`order-generation.md`](order-generation.md)). Earlier versions of this document described the template text as a separate Business of the Day line; that idea has been dropped.

**A conditional variable has to record what it governs.** `[Deadline for Response]` in order type 1 is marked conditional because a submission is often directed with no response at all. For the sentence depending on it to be left out when it is unanswered, the configuration has to hold *which* sentence or clause the variable governs, not only that it is conditional. Same for any conditional variable added later.

---

## General variables

Available to every order template. These are auto-populated — the judge does not type them.

| Variable | Source | Description |
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

---

## Order types

**Locked variables** are needed by the workflow and cannot be removed. **Optional variables** can be added or removed freely.

| # | Order type | In dropdown | Category | Template | Locked variables | Optional variables | Workflow |
|---|---|---|---|---|---|---|---|
| 1 | Mandatory submissions and responses | Yes | Filings | It is directed that the [Party Type] files a [Document Type] for [Document Name] before the court by [Deadline for Submission]. Additionally, the [Party Type] must submit a response by [Deadline for Response]. | `[Party Type]` · `[Document Type]` · `[Document Name]` · `[Deadline for Submission]` · `[Deadline for Response]` (conditional) | | Creates submission task; creates response task if response required |
| 2 | Referral of case to ADR | Yes | Disposal | Both the Parties have voluntarily agreed to seek resolution through [Mode of ADR]. The parties are hereby referred to [Mode of ADR] to resolve their dispute by [Date of End of ADR]. | | `[Mode of ADR]` — mediation/arbitration/etc. · `[Date of End of ADR]` — deadline | |
| 3 | Scheduling of hearing date | Yes (when hearing not ongoing) | Case management | Next hearing is scheduled on [Hearing Date] for [Hearing Purpose]. | `[Hearing Date]` · `[Hearing Purpose]` | | Schedules next hearing |
| 4 | Rescheduling of hearing date | No | | Next hearing scheduled on [Original Hearing Date] for [Hearing Purpose] has been rescheduled to [New Hearing Date]. | `[Original Hearing Date]` · `[Hearing Purpose]` · `[New Hearing Date]` | | Reschedules hearing |
| 5 | Accept application | No | | Application [Application Number] for [Application Type] is accepted. | `[Application Number]` · `[Application Type]` | | *(See note above — application workflows are triggered by the application type, not this order)* |
| 6 | Reject application | No | | Application [Application Number] for [Application Type] is rejected. | `[Application Number]` · `[Application Type]` | | |
| 7 | Case transfer | Yes | Case management | The case is transferred to another court for further proceedings. | | | |
| 8 | Case settlement | Yes | Disposal | The settlement records have been accepted by the court. Case closed. | | | |
| 9 | Issue of summons | Yes (ST/LP) | Process | Issue summons to the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps to issue summons. | `[Party Type]` — person summoned · `[Party Name]` · `[Party Type]` — party taking steps | | Triggers the summons workflow |
| 10 | Issue of warrants | Yes (ST/LP) | Process | Issue warrant to the [Party Type] [Party Name]. The [Party Type] is directed to take steps to issue warrant. | `[Party Type]` · `[Party Name]` · `[Party Type]` — party taking steps | | Triggers the warrant workflow |
| 11 | Withdrawal of case | Yes | Disposal | As per application [Application Number] complainant has sought to withdraw the complaint. Permission under Section 280 of the BNSS is granted and the Accused is acquitted. | `[Application Number]` | | |
| 12 | Issue of notice | Yes | Process | Issue [Notice Type] notice to the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps. | `[Notice Type]` — type of notice · `[Party Type]` · `[Party Name]` · `[Party Type]` — party taking steps | | Triggers the notice workflow |
| 13 | Acceptance of bail | No | | Application [Application Number] is accepted. | `[Application Number]` | | Optionally triggers bail bond submission workflow (magistrate specifies terms of bail) |
| 14 | Cognizance | Yes (when cognizance is due) | Case management | Considering the materials produced before the Court, I am prima facie satisfied that the offence punishable under S. 138 of NI Act is made out. Accordingly cognizance of the offence is taken and the case is taken on file. | | | |
| 15 | Judgement | Yes | Disposal | *(dedicated judgement screen — template to be finalised)* | | | |
| 16 | Dismiss case | Yes (when cognizance is due) | Case management | The case is dismissed. | | | |
| 17 | Bail | Yes (ST/LP) | Filings | Accused is released on bail. Particulars of offences u/s.138 of NI Act were read over and explained to the Accused to which he pleaded [Plea] and claimed to be tried. | | `[Plea]` — guilty/not guilty | Triggers the bail workflow |
| 18 | Cost | Yes | Miscellaneous | The [Party Type] is directed to pay [Amount] to the [Party Type] as costs by [Date]. | `[Party Type]` — paying party · `[Amount]` — ₹ · `[Party Type]` — receiving party · `[Date]` — deadline | | Creates payment task |
| 19 | Witness batta | Yes | Miscellaneous | The [Party Type] is directed to pay [Amount] to the [Party Type] as witness batta by [Date]. | `[Party Type]` — paying party · `[Amount]` — ₹ · `[Party Type]` — receiving party · `[Date]` — deadline | | Creates payment task |
| 20 | Issue of proclamation | Yes (ST/LP) | Process | Issue proclamation to the [Party Type] [Party Name]. Complainant is directed to make the appropriate payments and take steps. | `[Party Type]` · `[Party Name]` | | Triggers the proclamation workflow |
| 21 | Issue of attachment | Yes (ST/LP) | Process | Issue attachment against the [Party Type] [Party Name]. Complainant is directed to make the appropriate payments and take steps. | `[Party Type]` · `[Party Name]` | | Triggers the attachment workflow |
| 22 | Moving case to long pending register | Yes (when case is ST) | Case management | As per sanction given by Honourable CJM the case is moved to the Long Pending Register and is marked as LP. | | | |
| 23 | Moving case out of long pending register | Yes (when case is LP) | Case management | The case is moved out of the Long Pending Register and is to be considered and renumbered as a ST case. | | | |
| 24 | Abate case | Yes | Disposal | The case is abated following the death of the Accused party. | | | |
| 25 | Issue of miscellaneous process | Yes (ST/LP) | Process | Issue [Process Type] to the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps. | `[Process Type]` · `[Party Type]` · `[Party Name]` · `[Party Type]` — party taking steps | | Triggers the miscellaneous process workflow |

### Categories summary

| Category | Order types | Count |
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
| 4 | Only **one decision per application or request** | Accept application · Reject application · Acceptance of bail · Accept extension for submission deadline · Reject extension for submission deadline, and the generic accept/reject for advocate replacement and changes in litigant details | You cannot add two responses to the same application |
| 5 | **No restriction** — may be repeated and combined freely | Issue of summons · warrants · notice · proclamation · attachment · miscellaneous process · Mandatory submissions and responses · Cost · Witness batta · Bail · Moving case to / out of long pending register · Order under section 202 CrPC | |

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

Some variables can be filled automatically from the case record (the general variables above). Others require the judge to make a choice — picking a party, entering a date, selecting a hearing purpose. The system pre-fills what it can and presents the rest as fields for the judge to complete.

### What the system fills automatically

**General variables** (Court Name, Case Name, Case Number, Current Date, Judge Name, Judge Designation, Complainant Name, Accused Name) are always resolved from case and court data. The judge never types these.

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
