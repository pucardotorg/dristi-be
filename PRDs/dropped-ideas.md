# Dropped ideas

**Status:** 2026-10-19 — created; locked and optional variables, dropped from the order template catalogue and the order generation PRD. Then order item templates and the template system, dropped from the catalogue. 2026-10-20 — application detail cut from the order generation PRD; the per-court setting for where attendance and the next hearing are entered; the one-press hearing control; the trigger summary before marking order data complete; personal shortcuts seeded from the catalogue. 2026-10-29 — shortcuts saved per courtroom. 2026-11-03 — the per-court setting for where the next hearing is entered (`nextHearingEntry`). 2026-11-04 — the cap on upfront channel-fee rounds (`PMT-12`). 2026-11-10 — no bulk acts on applications (`ALC-35`); the four application order items (#5, #6, #13, #26) of the order item catalogue. 2026-11-11 — the next hearing's status and View All Hearings on the case overview (`OVW-02`, `OVW-05`); one line of text per case update on the overview (`OVW-06`); the hearings list and hearing detail on the case (`HRG-01`–`HRG-12`); hiding Notice/Process Status when no process has issued (`SVC-16`); the Applications filters and search, and the Needs attention grouping, bulk signing and bulk payment (`APP-01`–`APP-04`, `APP-09`–`APP-11`); the application statuses and record restated in view-case (`APP-12`–`APP-20`); the Documents section's separate bail-bond list and its filters and search (`DOC-01`–`DOC-04`); a witness's linked party and added by, and how its number is composed (`PTY-13`–`PTY-16`); legal teams all authored or none (`PTY-21`); counts per group in Parties (`PTY-22`); the rest of the Parties section's structure — list and selection, per-population rules and fields (`PTY-01`–`PTY-14`, `PTY-17`–`PTY-20`, `PTY-23`, `PTY-27`, `PTY-29`, `PTY-31`, `PTY-32`); Case History's date range and the Bail lifecycle section of view-case (`TME-02`, `TME-03`, §13); view-case's Not yet covered section; the last order highlighted in Case History (`TME-06`).

Ideas taken out of the PRDs, kept here with their last wording so they can be restored. Each entry says where it came from and what replaced it. The full earlier documents are also in git history: commit `cb97c67` holds both files as they were before.

---

## Locked and optional variables

**Dropped 2026-10-19.** Order items no longer write the order text: they are pure data entry. Every order item just has variables; a variable is **mandatory to enter** or not. There is no locked/optional configuration, and no separate "input a workflow needs" beyond the variables.

**Now:** `VAR-05`, `VAR-06` and `CMP-02` of [`order-generation.md`](order-generation.md); the *Mandatory to enter* column of [`order-template-catalogue.md`](order-template-catalogue.md).

### From order-template-catalogue.md

Intro to *Variables by order item*:

> **Locked** variables are needed by the workflow and cannot be removed. **Optional**
> variables can be added or removed freely. A blank cell is not yet specified.

Section *Locked vs optional variables*:

> **Locked variables** are required by the workflow that this order triggers. They cannot be removed from the template because the workflow depends on them to function. For example, the summons workflow needs to know which party is being summoned (`[Party Type]`, `[Party Name]`) and which party must take steps — without these, the system cannot create the correct task.
>
> **Optional variables** can be added to or removed from a template by a system administrator. They enrich the order text but no workflow depends on them. For example, `[Plea]` in the bail order is optional — the bail workflow does not need it to release the accused, but the court record is better for having it.

The section's closing sentence on general variables also read: "They do not appear in the locked or optional columns because they are universally available, not specific to a particular order type."

The *Not in V1* table's *Variables* column was headed *Locked variables*.

The *Locked / Optional* column, by order item:

| Order item | Variable | Locked / Optional |
|---|---|---|
| 1. Mandatory submissions and responses | `[Party Type]` | Locked |
| 1. Mandatory submissions and responses | `[Document Type]` | Locked |
| 1. Mandatory submissions and responses | `[Document Details]` | Locked |
| 1. Mandatory submissions and responses | `[Deadline for Submission]` | Locked |
| 2. Referral of case to ADR | `[Mode of ADR]` | Optional |
| 2. Referral of case to ADR | `[Date of End of ADR]` | Optional |
| 3. Scheduling of hearing date | `[Hearing Date]` | Locked |
| 3. Scheduling of hearing date | `[Hearing Purpose]` | Locked |
| 4. Rescheduling of hearing date | `[Original Hearing Date]` | Locked |
| 4. Rescheduling of hearing date | `[Hearing Purpose]` | Locked |
| 4. Rescheduling of hearing date | `[New Hearing Date]` | Locked |
| 5. Accept application · 6. Reject application | `[Application Number]` | Locked |
| 5. Accept application · 6. Reject application | `[Application Type]` | Locked |
| 9. Issue of summons · 10. Issue of warrants · 20. Issue of proclamation · 21. Issue of attachment | `[Party Name]` | Locked |
| 9. Issue of summons · 10. Issue of warrants · 20. Issue of proclamation · 21. Issue of attachment | `[Party Type]` | Locked |
| 9. Issue of summons · 10. Issue of warrants · 20. Issue of proclamation · 21. Issue of attachment | `[Party Type]` | Locked |
| 9. Issue of summons · 10. Issue of warrants · 20. Issue of proclamation · 21. Issue of attachment | Channels | Locked |
| 9. Issue of summons · 10. Issue of warrants · 20. Issue of proclamation · 21. Issue of attachment | Addresses | Locked |
| 9. Issue of summons · 10. Issue of warrants · 20. Issue of proclamation · 21. Issue of attachment | Police station | Locked |
| 11. Withdrawal of case | `[Application Number]` | Optional |
| 12. Issue of notice | `[Notice Type]` | Locked |
| 12. Issue of notice | `[Party Name]` | Locked |
| 12. Issue of notice | `[Party Type]` | Locked |
| 12. Issue of notice | `[Party Type]` | Locked |
| 12. Issue of notice | Channels | Locked |
| 12. Issue of notice | Addresses | Locked |
| 13. Acceptance of bail | `[Application Number]` | Locked |
| 17. Bail | `[Plea]` | Optional |
| 18. Cost | `[Party Type]` | Locked |
| 18. Cost | `[Amount]` | Locked |
| 18. Cost | `[Party Type]` | Locked |
| 18. Cost | `[Date]` | Locked |
| 19. Witness batta | `[Party Type]` | Locked |
| 19. Witness batta | `[Amount]` | Locked |
| 19. Witness batta | `[Party Type]` | Locked |
| 19. Witness batta | `[Party Name]` | Locked |
| 19. Witness batta | `[Date]` | Locked |
| 25. Issue of miscellaneous process | `[Process Type]` | Locked |
| 25. Issue of miscellaneous process | `[Party Name]` | Locked |
| 25. Issue of miscellaneous process | `[Party Type]` | Locked |
| 25. Issue of miscellaneous process | `[Party Type]` | Locked |
| 25. Issue of miscellaneous process | Channels | Locked |
| 25. Issue of miscellaneous process | Addresses | Locked |
| 25. Issue of miscellaneous process | Police station | Locked |
| 26. Dismiss application | `[Application Type]` | Locked |
| 26. Dismiss application | `[Party Type]` | Locked |
| 26. Dismiss application | `[Party Name]` | Locked |
| 26. Dismiss application | `[Filing Date]` | Locked |

Under *9. Issue of summons · 10. Issue of warrants · 20. Issue of proclamation · 21. Issue of attachment*, the note on channels read: "Channels, addresses and police station are not in the template. They are inputs the process workflow needs, asked for as part of the order item (`ITM-11` of order-generation.md); their rules are owned by process.md."

### From order-generation.md

| ID | Requirement as it was |
|---|---|
| `ITM-11` | An order item may need input beyond its template variables, where the workflow it triggers needs it — the delivery channels per recipient for a process order (`PRC-03` of [`process.md`](process.md)). That input is asked for as part of the order item; its fields are owned by the workflow's own document. |
| `VAR-05` | **Locked variables are mandatory.** The order data cannot be marked complete while any order item has a locked variable or a required workflow input unanswered (`CMP-02`). |
| `VAR-06` | An optional or conditional variable may be left unanswered. |
| `CMP-02` | The order data cannot be marked complete while: an order item has a locked variable or required workflow input unanswered (`VAR-05`); the next hearing is not settled; or an accepted application that moves the hearing has no next hearing date (`APL-10`). The screen names what is missing and where to set it. |

---

## Order item templates

**Dropped 2026-10-19.** Order items no longer carry template text, and nothing generates order text from them: the order text is typed by the order drafter, and order items are pure data entry. The catalogue now holds only the order items, their variables, workflows, availability, combination restrictions and the hearing purposes they relate to.

**Now:** [`order-template-catalogue.md`](order-template-catalogue.md) (retitled *Order item catalogue*); the order text is owned by §5 of [`order-generation.md`](order-generation.md).

### Template text, by order item

| # | Order item | Template |
|---|---|---|
| 1 | Mandatory submissions and responses | It is directed that the [Party Type] files a [Document Type] for [Document Details] before the court by [Deadline for Submission]. |
| 2 | Referral of case to ADR | Both the Parties have voluntarily agreed to seek resolution through [Mode of ADR]. The parties are hereby referred to [Mode of ADR] to resolve their dispute by [Date of End of ADR]. |
| 3 | Scheduling of hearing date | Next hearing is scheduled on [Hearing Date] for [Hearing Purpose]. |
| 4 | Rescheduling of hearing date | Next hearing scheduled on [Original Hearing Date] for [Hearing Purpose] has been rescheduled to [New Hearing Date]. |
| 5 | Accept application | Application [Application Number] for [Application Type] is accepted. |
| 6 | Reject application | Application [Application Number] for [Application Type] is rejected. |
| 7 | Case transfer | The case is transferred to another court for further proceedings. |
| 8 | Case settlement | The settlement records have been accepted by the court. Case closed. |
| 9 | Issue of summons | Issue summons to the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps to issue summons. |
| 10 | Issue of warrants | Issue warrant to the [Party Type] [Party Name]. The [Party Type] is directed to take steps to issue warrant. |
| 11 | Withdrawal of case | As per application [Application Number] complainant has sought to withdraw the complaint. Permission under Section 280 of the BNSS is granted and the Accused is acquitted. |
| 12 | Issue of notice | Issue [Notice Type] notice to the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps. |
| 13 | Acceptance of bail | Application [Application Number] is accepted. |
| 14 | Cognizance | Considering the materials produced before the Court, I am prima facie satisfied that the offence punishable under S. 138 of NI Act is made out. Accordingly cognizance of the offence is taken and the case is taken on file. |
| 15 | Judgement | *(dedicated judgement screen — template to be finalised)* |
| 16 | Dismiss case | The case is dismissed. |
| 17 | Bail | Accused is released on bail. Particulars of offences u/s.138 of NI Act were read over and explained to the Accused to which he pleaded [Plea] and claimed to be tried. |
| 18 | Cost | The [Party Type] is directed to pay [Amount] to the [Party Type] as costs by [Date]. |
| 19 | Witness batta | The [Party Type] is directed to pay [Amount] to the [Party Type] [Party Name] as witness batta by [Date]. |
| 20 | Issue of proclamation | Issue proclamation to the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps. |
| 21 | Issue of attachment | Issue attachment against the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps. |
| 22 | Moving case to long pending register | As per sanction given by Honourable CJM the case is moved to the Long Pending Register and is marked as LP. |
| 23 | Moving case out of long pending register | The case is moved out of the Long Pending Register and is to be considered and renumbered as a ST case. |
| 24 | Abate case | The case is abated following the death of the Accused party. |
| 25 | Issue of miscellaneous process | Issue [Process Type] to the [Party Type] [Party Name]. The [Party Type] is directed to make the appropriate payments and take steps. |
| 26 | Dismiss application | Application for [Application Type] filed by the [Party Type] [Party Name] on [Filing Date] is dismissed. |

Not in V1:

| Order type | Template |
|---|---|
| Order under section 202 CrPC | *(no template)* |
| Accept extension for submission deadline | Application [Application Number] for extension of deadline of submission of [Document Type] for [Document Name] is accepted. The [Party Type] is required to submit the same by [New Submission Date]. |
| Reject extension for submission deadline | Application [Application Number] for extension of deadline of submission of [Document Type] for [Document Name] is rejected. |

### Wording removed from the catalogue

**Order items — note *Template text and order text*:**

> **Template text and order text.** The template seeds the order text; there is no second,
> shorter wording. The order's own text is the record and goes into the A-Diary (`TXT-04`
> of [`order-generation.md`](order-generation.md)).

**Variables by order item — intro:**

> Listed are the variables that may be an input, and any other variable an order item's
> template needs — that one is shown with input type *None*. Much else in the case may be
> relevant and pulled into the text, but it is not listed here unless the template uses it.

**9. Issue of summons · 10 · 20 · 21 — note under the table:**

> Channels, addresses and police station are not in the template. They are fields of the
> order item like any other; their rules are owned by
> [`process.md`](process.md).

**11. Withdrawal of case — note under the table:**

> Withdrawal may be ordered on an application or directly. When it is chosen from the
> dropdown there is no application, and the clause "As per application [Application
> Number]" is left out of the text. The configuration has to record that this clause is the
> one `[Application Number]` governs.

**Application types covered by generic accept/reject — intro:**

> They all use the same template and have no order-level workflow

**Hearing purposes — notes:**

> They open dedicated screens, not templates.

The Terminology entry for *Order item* read: "each has its own template, variables and, optionally, a workflow".

### How the template system works

The whole section, as it stood:

#### The concept

Every order is generated from a **template** — a piece of text with **variables** in square brackets. When the judge issues an order, the system fills in the variables and produces the final order text.

Some variables can be filled automatically from the case record (the general variables below). Others require the judge to make a choice — picking a party, entering a date, selecting a hearing purpose. The system pre-fills what it can and presents the rest as fields for the judge to complete.

#### What the system fills automatically

**General variables** (Court Name, Case Name, Case Number, Current Date, Judge Name, Judge Designation, Complainant Name, Accused Name) are always resolved from case and court data. The judge never types these.

##### General variables

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

#### What the judge must specify

The system cannot fill a variable when it requires a **choice among multiple options**. The judge must specify:

- **Which party**, when the case has more than one person of a given type. A §138 case typically has one complainant and one accused, but there can be multiple accused (e.g. the drawer and the company director). When the system encounters `[Party Name]` and there are multiple candidates, it presents a selector. If there is only one person of that type, it fills automatically.
- **Dates** that are set by the judge's discretion — a submission deadline, a new hearing date, the end date for ADR. The system cannot guess these.
- **Amounts** — cost and witness batta amounts are the judge's decision.
- **Selections from master data** — hearing purpose, document type, mode of ADR, notice type. These are dropdowns drawn from master data, not free text.

#### General variables

**General variables** are always available to any template. A template author can reference any general variable in any template. They are universally available, not specific to a particular order type.

#### What the judge can customise

The judge works with the **generated text**, not the template. After the system fills in all the variables, the judge sees the complete order text and can:

- **Edit the text** freely — add sentences, remove paragraphs, correct wording. The template is a starting point, not a constraint.
- **Add additional comments** — a free-text area for anything the template does not cover.

The judge **cannot** change the template itself. Templates are system configuration managed by an administrator. What the judge produces is an order — a document — not a new template.

#### How variables resolve at generation time

1. The judge selects an order type (from the dropdown, or by acting on an application).
2. The system loads the template for that order type.
3. **Auto-fill pass:** general variables and context variables (application number, workflow data) are filled in.
4. **Judge input pass:** the system presents any remaining unfilled variables as form fields — dropdowns for master data selections, date pickers for dates, party selectors for party references, text inputs for free values.
5. The judge fills the remaining fields and confirms.
6. The system generates the complete order text.
7. The judge reviews, optionally edits, and signs.

If an order type has **no template** (e.g. Order under section 202 CrPC), the judge writes the order text from scratch — or a dedicated screen handles it (e.g. Judgement).

---

## Application detail in the order generation PRD

**Cut 2026-10-20.** Not dropped as an idea: what can be done with an application belongs to the application workflow, which is to cover it. The order PRD now only says that pending applications are listed in the order data and that actions can be taken on them (`APL-01`, `APL-02` of [`order-generation.md`](order-generation.md)), and points to [`application-lifecycle.md`](application-lifecycle.md). Check this list against that document when it is next revised.

§6.3 *Applications standing on the matter*, as it stood:

| ID | Requirement |
|---|---|
| `APL-01` | The order data lists the applications on file standing on the matter, each with what it is, who raised it and when, and a way to open and read it without leaving the screen. They are listed last, under the order items. |
| `APL-02` | **Taking an application on file** is not done on this screen. It is a system action, not an order, owned by [`application-lifecycle.md`](application-lifecycle.md). |
| `APL-03` | The CMP number is assigned **only on being taken on file**, not at filing. Until then the application is referred to by its application number. Both number formats are owned by [`case-numbers.md`](case-numbers.md). |
| `APL-04` | **Dismissing an application at admission** — before it is taken on file — is an order. It is opened from the application, with the dismissal already in its order data as an order item added in advance (`ORD-10a`), and takes effect when the order is signed and its order data triggered. |
| `APL-05` | An order dismissing an application at admission **does not cite the application number**. That number is internal and is not something a court recognises as identifying an application. It identifies the application by **what kind of application it is, who raised it, and when it was filed**. |
| `APL-06` | **On the configuration:** an order item is needed for dismissal at admission, identifying the application by its kind, its filer and its filing date (`APL-05`). This is *Dismiss application*, #26 of the catalogue. |
| `APL-07` | **Once on file**, an application is allowed or rejected in the order data. The decision uses the configured accept / reject order item. A decision may be changed or cleared until the order data is marked complete. |
| `APL-08` | Any workflow that follows belongs to the **application type**, not to the accept/reject order item, and is triggered with the order's other workflows like any other order item's. |
| `APL-09` | Acceptance of bail is its own order item because it optionally triggers the bail bond workflow; it is not the generic accept. |
| `APL-10` | Accepting an application that moves the hearing — a request to postpone or advance it — needs the next hearing's date, because that date is where the hearing moves to. The order data cannot be marked complete without it (`CMP-02`). |
| `APL-11` | An order opened from an application has that application in its order data and the decision being made already loaded. |
| `APL-12` | An application left undecided does not block the order. |

---

## Attendance and the next hearing in order data (`detailsPlacement`)

**Dropped 2026-10-20.** Attendance and the next hearing are always entered and printed on the order (`PLC-02` of [`order-generation.md`](order-generation.md)). The only court setting left is whether the next hearing is entered in the order or on the cause list (`PLC-04`).

As they stood in §9 of order-generation.md:

| ID | Requirement |
|---|---|
| `PLC-01` | **`detailsPlacement`**, set per court: **on the order** (default) or **in order data**. |
| `PLC-03` | **In order data:** attendance and the next hearing are entered at the top of the Order data view. They are recorded and drive their workflows, but are **not printed** on the order. They can be changed until the order data is marked complete. |

§9's intro read: "Where these two are entered is a court setting, because courts divide this work differently." §6's intro read: "The Order data view carries, top to bottom: attendance and the next hearing where the court enters them here (§9), the order items, and the applications standing on the matter."

---

## The one-press hearing control

**Dropped 2026-10-20.** A hearing is now started, ended or passed over, each on its own (`HRG-01` of [`order-generation.md`](order-generation.md)). *Next case* is no longer a hearing control: it only takes a person to the next hearing that has started (`HRG-10`). Only the hearing controller sees the hearing controls (`HRG-00`).

§10 as it stood:

| ID | Requirement |
|---|---|
| `HRG-01` | The header carries **one hearing control**. For a person holding **hearing controller**, one press does three things: it marks this listing heard, calls the next unheard listing on the day's board in serial order, and opens its order screen. It reads *Next case*, or *End hearing* where there is no next listing; then it ends this hearing and returns to the day's board. |
| `HRG-02` | For a person without hearing controller, the same control only takes them to the hearing now under way; it ends nothing and starts nothing. It is **disabled until the next hearing has been started** by a hearing controller, and it **names the hearing it will take them to** — its item number on the day's board — once that hearing is under way. |
| `HRG-03` | `HRG-02` means the control changes without its user doing anything: another person's action enables it and gives it its number. The screen keeps it current while it is open, rather than waiting for a reload. |
| `HRG-04` | Ending a hearing does not require the order to be complete, sent or signed. The draft stays on the listing and can be returned to. |

---

## Summary of what triggering will do

**Dropped 2026-10-20.** Marking order data complete no longer has to show, first, what triggering will send out. The prototype's *Mark order data complete* dialog does list it (`triggerSummary` in `pending-order-screen.tsx`).

As it stood in §13 of [`order-generation.md`](order-generation.md):

| ID | Requirement |
|---|---|
| `CMP-03` | Before marking it complete, the order data filler sees **what triggering will do**, in words: each order item and what it sets moving, each decision, attendance and the next hearing. |

---

## Personal shortcuts seeded from the catalogue

**Dropped 2026-10-20.** Shortcuts are now saved per courtroom (`SHC-06` of [`order-generation.md`](order-generation.md)). The catalogue no longer carries template text, so it can't seed them. There are no personal shortcuts in this version (`SHC-07`).

As they stood in §5.1:

| ID | Requirement |
|---|---|
| `SHC-06` | The shortcuts a person starts with are the catalogue's order items that carry no variables, worded as the catalogue words them, and a set of longer model orders. |
| `SHC-07` | Shortcuts belong to the person and follow them across devices. A court-wide shared set is `Q-5`. |

---

## Shortcuts saved per courtroom

**Dropped 2026-10-29.** A shortcut now belongs to one person (`SHC-06` of [`order-generation.md`](order-generation.md)) and carries a scope listing the screens it applies to, so the same feature can be reused on other screens, advocates' included (`SHC-07`).

As they stood in §5.1:

| ID | Requirement |
|---|---|
| `SHC-06` | Shortcuts are saved **per courtroom**: everyone drafting orders in a courtroom works from that courtroom's saved set, on any device. |
| `SHC-07` | **Any order drafter** in the courtroom maintains the courtroom's set: lists, searches, adds, changes and removes its shortcuts (`SHC-05`). There are no personal shortcuts in this version. |

---

## Where the next hearing is entered (`nextHearingEntry`)

**Dropped 2026-11-03.** The next hearing setter role already decides who enters the next hearing, and each person already chooses whether the cause list shows the *Next hearing* column. A next hearing setter can now enter it in the order or on the cause list, and both edit the same value (`PLC-04`, `PLC-05` of [`order-generation.md`](order-generation.md)).

As it stood in §9 of order-generation.md:

| ID | Requirement |
|---|---|
| `PLC-04` | Each court chooses **where the next hearing is entered**, and with it **who enters it**. The setting is `nextHearingEntry`, with two values. **On the cause list** (default): the next hearing is entered on the day's cause list, in a *Next hearing* column beside each case, by the person working the cause list during the hearing. The order screen shows it read only. **In the order**: the next hearing is entered on the order screen, at the foot of the order (`PLC-02`), by the person working on the order. The cause list has no *Next hearing* column. Either way the person needs the **next hearing setter** role (`ROL-03`), and the next hearing is entered in one place only, never both. |

§9's intro read: "Attendance and the next hearing are always on the order. Whether the next hearing is entered in the order or on the cause list is a court setting, because courts divide this work differently." `SND-03` read: "…**whichever way the court enters it** (`PLC-04`). Where it is entered on the cause list, the order shows it read only, so it has to be entered there first."

---

## Cap on upfront channel-fee rounds (`PMT-12`)

**Dropped 2026-11-04.** It was not an owner decision: it was read into the e-filing decisions log (batch 5, "round by round"). The filer's channel-fee rounds now follow only the state's range ([`payment-logic.md`](payment-logic.md) `PMT-10`, `PMT-11`; [`efiling.md`](efiling.md) `PAY-15`).

As it stood in §2 of payment-logic.md:

| ID | Requirement |
|---|---|
| `PMT-12` | `[DERIVED]` For a process, the channel-fee rounds paid upfront cannot exceed the court-fee rounds paid upfront ([`efiling.md`](efiling.md) `PAY-15`). |

`PAY-15` of efiling.md also read: "The fee is charged per selected address, per round — no more rounds than those whose court fee they are paying upfront." Before 2026-11-04 it read: "So delivery rounds run **1 … summons rounds prepaid**."

## No bulk acts on applications (`ALC-35`)

**Dropped 2026-11-10.** Whether the court can act on several applications at once is a screen choice, not a requirement.

As it stood in "Users and actions" of [`application-lifecycle.md`](application-lifecycle.md):

| ID | Requirement |
|---|---|
| `ALC-35` | Every court act is on **one application at a time**. There are no bulk acts on a selection of applications. |

## Separate order items for accepting, rejecting and dismissing an application (#5, #6, #13, #26)

**Dropped 2026-11-10.** An order now acts on an application through one order item, **#27 Application action**, whose questions are in [`application-lifecycle.md`](application-lifecycle.md) `ALC-38`. Accepting a Bail application triggers the Bail type's workflow; setting bail terms may come back later as its own item or another way of raising a pending task.

As they stood in [`order-template-catalogue.md`](order-template-catalogue.md):

| # | Order item | Availability | Category | Workflow |
|---|---|---|---|---|
| 5 | Accept application | Contextual | | *(see note below)* |
| 6 | Reject application | Contextual | | |
| 13 | Acceptance of bail | Contextual | | Optionally triggers bail bond submission workflow (magistrate specifies terms of bail) |
| 26 | Dismiss application | Contextual | | |

**Onboarded applications only, except dismissal.** Accept application (#5), Reject
application (#6) and Acceptance of bail (#13) — the specific acceptance of a bail
application — apply only once the application has been onboarded. Before onboarding, the
only order item for an application is **Dismiss application** (#26). An application that
is not onboarded has no application number, so #26 names it by its type, the party that
filed it and its filing date. Onboarding and dismissal are owned by `ALC-04` and
`ALC-19` of [`application-lifecycle.md`](application-lifecycle.md).

### 5. Accept application · 6. Reject application

| Variable | Meaning | Input type | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|
| `[Application Number]` | Application being decided | Read-only — from the application | Yes | From the application the order item was reached from | |
| `[Application Type]` | Its type | Read-only — from the application | Yes | From the application the order item was reached from | |

### 13. Acceptance of bail

| Variable | Meaning | Input type | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|
| `[Application Number]` | The bail application | Read-only — from the application *(proposed)* | Yes | From the application the order item was reached from | |

### 26. Dismiss application

| Variable | Meaning | Input type | Mandatory to enter | Default value | Validation |
|---|---|---|---|---|---|
| `[Application Type]` | Type of the application being dismissed | Read-only — from the application | Yes | From the application the order item was reached from | |
| `[Party Type]` | Party type of the person who filed it | Read-only — from the application | Yes | From the application the order item was reached from | |
| `[Party Name]` | Person who filed it | Read-only — from the application | Yes | From the application the order item was reached from | |
| `[Filing Date]` | Date the application was filed | Read-only — from the application | Yes | From the application the order item was reached from | |

There is no `[Application Number]`: the application is not onboarded, so it has none.

---

## Categories summary

| Category | Order items | Count |
|---|---|---|
| Filings | Mandatory submissions, Bail | 2 |
| Disposal | Referral to ADR, Case settlement, Withdrawal, Abate case, Judgement | 5 |
| Case management | Scheduling of hearing, Rescheduling of hearing, Case transfer, Moving to/from LP register, Cognizance, Dismiss case | 7 |
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

Combination rule 4: Only **one decision per application or request** — Accept application · Reject application · Acceptance of bail · Dismiss application — "You cannot add two responses to the same application".

### Application types covered by generic accept/reject

The generic "Accept application" (#5) and "Reject application" (#6) rows above cover every application type below. They have no order-level workflow — any workflow triggered belongs to the application type itself.

| Application type | Notes |
|---|---|
| Voluntary submission | |
| Delay condonation (DCA) | |
| Bail (rejection only) | Bail acceptance is a separate order (#13) because it optionally triggers the bail bond submission workflow |
| Changes in litigant details | |
| Advocate replacement | Currently a task, not an application — has no application number |
| Change in power of attorney | "No such order" noted in source spreadsheet |

---

## Next hearing status and View All Hearings on the case overview

**Dropped 2026-11-11.** The overview's next hearing shows only the date and the purpose,
as on the court side.

**Now:** `OVW-01`, `OVW-03` and `OVW-04` of [`view-case.md`](view-case.md) §5.1. How the
list of all hearings is reached is open (`view-case.md` Q-11).

### From view-case.md §5.1

> | `OVW-02` | Status badge | Status of the next hearing |
> | `OVW-05` | View All Hearings | **[OWNER]** Link labelled "View All Hearings" (not "View Hearing Details"). Opens the hearings pop-up (§5.4). |

---

## One line of text per case update on the overview (`OVW-06`)

**Dropped 2026-11-11.** Not every event has a one-line text describing what happened. Only
an order shows text: its diary entry text.

**Now:** `OVW-17` of [`view-case.md`](view-case.md) §5.2.

### From view-case.md §5.2

> | `OVW-06` | Update text | A single line of text describing what happened |

---

## Hearings list and hearing detail on the case (`HRG-01`–`HRG-12`)

**Dropped 2026-11-11.** The case no longer has a list of all its hearings or a hearing
detail. The overview shows only the next hearing ([`view-case.md`](view-case.md) §5.1).

### From view-case.md §5.4

> ## 5.4 Hearings
>
> The list of all hearings on the case. How the user reaches it is open (Q-11).
>
> ### 5.4.1 List
>
> | ID | Element | Detail |
> | --- | --- | --- |
> | `HRG-01` | Contents | Each hearing shows its date, purpose and status, and can be opened to its detail (§5.4.2) |
> | `HRG-02` | Ordering | Newest first |
> | `HRG-03` | Values | Every value in the list is drawn from the hearing record (§5.4.2) |
>
> ### 5.4.2 Hearing detail
>
> A hearing carries these fields:
>
> | ID | Field | Notes |
> | --- | --- | --- |
> | `HRG-04` | Hearing purpose | What the matter was listed for |
> | `HRG-05` | Date | Date of the hearing |
> | `HRG-06` | Start time | When the hearing started |
> | `HRG-07` | End time | When the hearing ended |
> | `HRG-08` | Attendance | Who attended the hearing, as a line of text |
> | `HRG-09` | Next hearing purpose | What the matter is next listed for |
> | `HRG-10` | Next hearing date | The date it is next listed on |
> | `HRG-11` | Hearing summary | The order text entered in the order for that hearing. One text, held on the order and read from there. |
> | `HRG-12` | Order | The order passed in the hearing. Opens the order (§8). |

---

## Hiding Notice/Process Status when no process has issued (`SVC-16`)

**Dropped 2026-11-11.** Better to show the section empty than to hide it.

**Now:** `SVC-21` of [`view-case.md`](view-case.md) §7.1.

### From view-case.md §7.4

> | `SVC-16` | The section is not shown when no process has ever issued on the case (nothing to report). |

---

## Applications filters, search, and Needs attention grouping (`APP-01`–`APP-04`, `APP-09`–`APP-11`)

**Dropped 2026-11-11.** Filters and search are a UI matter, shown in the prototype. Needs
attention only shows the applications in draft, pending signature or pending payment.

**Now:** `APP-05` of [`view-case.md`](view-case.md) §9.2.

### From view-case.md §9.1 and §9.2

> ## 9.1 What is shown
>
> | ID | Element | Detail |
> | --- | --- | --- |
> | `APP-01` | Type filter | Filter by application type |
> | `APP-02` | Status filter | Filter by status (§9.3) |
> | `APP-03` | Filed by filter | Filter by the person on the case who filed it |
> | `APP-04` | Search | By application ID |
> | `APP-05` | Needs attention | Applications that still need a step from the viewer — drafts, pending signature, pending payment — are shown separately, ahead of the rest. |
> | `APP-06` | List | `[DERIVED]` Each application shows its type, application ID, status, who filed it, created on and submitted on, and can be opened |
> | `APP-07` | Open an application | Opens the application, the documents attached to it, and the linked order where there is one |
>
> `APP-08` `[DERIVED]` — the record carries both a created and a submitted date (§9.4), so the
> list shows both. Confirm which the list leads on.
>
> ## 9.2 "Needs attention" grouping
>
> `APP-09` — two or more applications waiting on the **same step from the same filer**
> collapse into one entry with one action.
>
> `APP-10` Signing — signatures can be added **one at a time or in bulk**. In v1, bulk
> signing is offered only to a filer who has set up their bulk signing tool; everyone else
> signs one application at a time.
>
> `APP-11` Payment — payments can be completed **one at a time or in bulk**.

---

## Application statuses and record restated in view-case (`APP-12`–`APP-20`)

**Dropped 2026-11-11.** They restated, and disagreed with,
[`application-lifecycle.md`](application-lifecycle.md), which owns an application's
statuses and attributes.

**Now:** [`view-case.md`](view-case.md) §9.3 links to "Application attributes" in
`application-lifecycle.md`.

### From view-case.md §9.3 and §9.4

> ## 9.3 Filing statuses
>
> | Value | Label | Needs attention? |
> | --- | --- | --- |
> | `draft` | Draft | Yes — continue the draft |
> | `pending-signature` | Pending signature | Yes — add the signature |
> | `pending-payment` | Pending payment | Yes — complete the payment |
> | `completed` | Completed | No |
> | `rejected` | Rejected | No |
> | `expired` | Expired | No |
>
> ## 9.4 Application record
>
> An application carries:
>
> | ID | Field | Notes |
> | --- | --- | --- |
> | `APP-12` | Type | One of the application types |
> | `APP-13` | Status | Filing workflow status (§9.3) |
> | `APP-14` | Created on | When the application was created |
> | `APP-15` | Submitted on | When it was submitted |
> | `APP-16` | Filed by | The person who submitted the application |
> | `APP-17` | Side | Whether it was filed by the complainant, the accused, or the court. Held separately from the person, not derived from them. |
> | `APP-18` | Application ID | The registry's identifier, once allotted |
> | `APP-19` | Linked order | The order the court passed on the application, where there is one |
> | `APP-20` | Documents | The files attached to the application |

---

## Documents section: separate bail-bond list, filters and search (`DOC-01`–`DOC-04`)

**Dropped 2026-11-11.** Every kind of document is returned, marked with its kind; how the
screen separates them, and which filters it offers, is a UI choice.

**Now:** `DOC-07` and `DOC-08` of [`view-case.md`](view-case.md) §10.2.

### From view-case.md §10

> | ID | Element | Detail |
> | --- | --- | --- |
> | `DOC-01` | Documents and bail bonds | Listed separately. Bail bonds are not a document type. |
> | `DOC-02` | Type filter | Filter by document type ([`document-submission.md`](document-submission.md) `DSB-11`) |
> | `DOC-03` | Submitted by filter | Filter by the person on the case who submitted it |
> | `DOC-04` | Search | By document title, provisional ID or evidence number |

---

## Witness linked party, added by, and number composition (`PTY-13`, `PTY-15`, `PTY-16`)

**Dropped 2026-11-11.** A witness's linked party and who added it both follow from its
side. How a witness number is formed belongs in another PRD, not the case view.

**Now:** `PTY-12` (side) and `PTY-13` (number, without how it is formed) of
[`view-case.md`](view-case.md) §11.

### From view-case.md §11, Witnesses

> | `PTY-13` | Number | Composed from prefix + index: PW-1, DW-2, CW-1. **Side is a field, never derived from the prefix** — they are two authored fields and must agree. |
> | `PTY-15` | Linked party | The party whose evidence this witness speaks to |
> | `PTY-16` | Added by | Complainant, accused, or court |

---

## Legal teams all authored or none (`PTY-21`)

**Dropped 2026-11-11.** A rule about how the prototype's sample data is put together, not
a requirement on the product.

**Now:** `PTY-20` of [`view-case.md`](view-case.md) §11.5.

### From view-case.md §11.3

> `PTY-21` — either all of a case's teams are authored or none are. A half-authored case
> throws — the mismatch cannot be resolved silently.

---

## Counts per group in Parties (`PTY-22`)

**Dropped 2026-11-11.** Not important enough to specify; the UI counts if it needs to.

### From view-case.md §11.1

> | `PTY-22` | The count shown for each group equals the number of people in it: every litigant on the case title, institutions included; every witness, the court's own included; every advocate on record; every office member with access to the case, each counted once. |

---

## Parties section structure (`PTY-01`–`PTY-14`, `PTY-17`–`PTY-20`, `PTY-23`, `PTY-27`, `PTY-29`, `PTY-31`, `PTY-32`)

**Dropped 2026-11-11.** The section is cut to the people on the case and the details shown
for each; how they are organised and shown is left to the UI. `PTY-24`–`PTY-26` and
`PTY-28` were kept.

**Now:** `PTY-33`–`PTY-42` of [`view-case.md`](view-case.md) §11.1.

### From view-case.md §11, as it stood before

> # 11. Parties
>
> This section shows everyone on the case and what is held about each of them: the
> litigants, their representatives and power of attorney holders, the witnesses, and the
> advocates with their juniors and clerks. It is the same for everyone who can see the case.
>
> The details themselves are collected elsewhere — at e-filing, by an application, or at
> registration — and the PRD that collects them sets their fields and rules. This section
> says which details are shown, and links there.
>
> ## 11.1 The list
>
> | ID | Requirement |
> | --- | --- |
> | `PTY-01` | A list of the people on the case, grouped as litigants, witnesses, and advocates with the members of their office; selecting one shows their details. |
> | `PTY-02` | It opens on the first litigant, unless a link names another person on the case. A link naming someone not on the case falls back to the first litigant. |
> | `PTY-23` | The viewer's own entry is marked "you". |
>
> ## 11.2 What is not shown
>
> | ID | Requirement |
> | --- | --- |
> | `PTY-24` | Contact details — phone, email and addresses — are shown to everyone who can see the case. Masking them is a later enhancement (§16). |
> | `PTY-25` | No documents are shown here. ID cards, vakalatnamas and power of attorney authorisations are in Documents (§10). |
> | `PTY-26` | An Aadhaar number is never shown. |
>
> ## 11.3 Litigants
>
> | ID | Requirement |
> | --- | --- |
> | `PTY-07` | An institution's entry names the person who acts for it. For an institution complainant, that is its authorised representative ([`efiling.md`](efiling.md)): they act for the institution but are not a party. For an institution accused, each person in charge is an accused in their own right (`PTY-08`). |
> | `PTY-08` | When an accused is a person in charge of an institution (§141), their entry names the institution and says whether they are its representative or another person in charge. |
> | `PTY-09` | When a litigant has a power of attorney holder, the holder is named on the litigant's entry. A litigant has at most one. The holder acts for the litigant but is not a party. |
> | `PTY-10` | A litigant conducting their own case is shown as party in person. This is shown differently from a litigant with no advocate on record: party in person is the litigant's own choice, while no advocate only means no vakalatnama has been filed for them. |
> | `PTY-11` | A litigant represented by advocates has each advocate on record named on their entry, with their bar registration ID (§11.5). A litigant cannot be party in person and have an advocate on record at the same time. |
>
> Each litigant shows:
>
> | ID | Field | Detail |
> | --- | --- | --- |
> | `PTY-03` | Side | Complainant or accused |
> | `PTY-04` | Kind | Individual or institution |
> | `PTY-05` | Institution type | e.g. "Partnership firm", "Private limited company" — institutions only |
> | `PTY-06` | Designation | How an individual stands inside an institution, e.g. "Managing partner" |
> | `PTY-27` | Details | The details collected at e-filing ([`efiling.md`](efiling.md) §6 for a complainant, §8 for an accused), as last changed by an Edit Litigant Details application ([`application-lifecycle.md`](application-lifecycle.md)). For an individual: name, age, gender, phone, email and addresses. For an institution: its name, CIN or PAN, contact phone and email, and address, and its representative's name, designation, phone, email and address. An accused's addresses each show their police station. |
> | `PTY-28` | Addresses | Every address on record for the litigant, including any added since filing, for example on an order issuing process ([`process.md`](process.md) `PRC-05`) |
> | `PTY-29` | Power of attorney holder's details | Name, age, phone, email and addresses ([`efiling.md`](efiling.md) `LIT-11`–`LIT-16`) |
>
> ## 11.4 Witnesses
>
> Each witness shows:
>
> | ID | Field | Detail |
> | --- | --- | --- |
> | `PTY-12` | Side | Complainant, accused, or neither (court witness) |
> | `PTY-13` | Number | The witness's number, e.g. PW-1. How it is formed is not set here. |
> | `PTY-14` | What the witness will prove | As entered when the witness was added ([`efiling.md`](efiling.md) `WIT-3`), where it was given |
> | `PTY-31` | Details | Name or designation, age, phone, email and addresses, as collected at e-filing ([`efiling.md`](efiling.md) §13) or by an Addition of Witness application ([`application-lifecycle.md`](application-lifecycle.md)), including any address added since (`PTY-28`) |
>
> ## 11.5 Advocates and their offices
>
> | ID | Requirement |
> | --- | --- |
> | `PTY-20` | Each advocate on record shows their name and bar registration ID ([`account-creation.md`](account-creation.md) `REG-13`), their side, the parties they appear for, whether they appear for more than one party on that side, and the members of their office who have access to this case — juniors and clerks ([`office-management.md`](office-management.md)). An advocate's address is not shown. |
> | `PTY-18` | Each office member is listed once, however many advocates they work for. A clerk in the offices of two advocates is one person with two advocates listed. |
>
> Each office member shows:
>
> | ID | Field | Detail |
> | --- | --- | --- |
> | `PTY-17` | Role | Junior or clerk |
> | `PTY-19` | Advocates | Every advocate on record whose office they are in |
> | `PTY-32` | Identifier | A junior's bar registration ID, or a clerk's clerk registration number ([`account-creation.md`](account-creation.md) `REG-13`, `REG-13a`) |

---

## Case History date range, and the Bail lifecycle section (`TME-02`, `TME-03`, view-case §13)

**Dropped 2026-11-11.** Case History was rewritten to match the overview's case updates;
the date range was a display detail, and `TME-03` (each event opens its record) is now part
of `TME-04`. The Bail lifecycle section does not belong in the case view.

**Now:** `TME-01`, `TME-04`–`TME-07` of [`view-case.md`](view-case.md) §12. Bail is owned by
[`bail-bond.md`](bail-bond.md).

### From view-case.md §12, as it stood before

> # 12. Case History
>
>
> | ID | Element | Detail |
> | --- | --- | --- |
> | `TME-01` | Order | Events grouped by date, newest first |
> | `TME-02` | Date range | The span of the history: first event to latest event |
> | `TME-03` | Events | Each event opens the record it came from |
>
> ## 12.1 Event types
>
> Case history draws from the same event catalogue as the overview case updates (§5.2).
> The full event catalogue is maintained in a [separate document](https://docs.superhuman.com/d/PUCAR-Dashboard-2027_dKtL_rwN6Qw/Events_suDoUtbn#Events-Case-Updates_tudKS-s9).
> The overview shows the updates down to the last order issued; case history shows all.

### From view-case.md §13

> # 13. Bail lifecycle
>
> Bail runs across the case: Make filings (`ACT-02`) and the overview's pending tasks (§5.3)
> always show the same bail state.
>
> ## 13.1 Phases
>
> | Phase | What happens |
> | --- | --- |
> | `none` | No bail activity |
> | `task` | The court has approved bail with terms; the task is to raise the bond |
> | `signing` | Bond generated, out for signatures |
> | `review` | Signatures complete; status review |
>
> ## 13.2 Entry points
>
> - Make filings → Raise bail application (`ACT-02`)
> - The bail bond task in the overview's pending tasks (§5.3)
>
> ## 13.3 Bail actions
>
> | Action | Purpose |
> | --- | --- |
> | Bail application | Raise a bail application |
> | Bail bond | Generate the bond document, or view it |
> | Bail bond status | Review status of an outstanding bond |

---

## view-case's Not yet covered section

**Dropped 2026-11-11.** No other PRD keeps a section like this.

### From view-case.md §14

> # 14. Not yet covered
>
> The following are known to be needed but are not specified in this document:
>
> | Area | Notes |
> | --- | --- |
> | Backend API contracts | Endpoints, payloads, pagination, real-time updates |
> | Data model (server) | Database schema, relationships, indices |
> | Search | Full-text search across cases, documents, orders |
> | Notifications | Push/in-app notifications for case events |
> | Audit trail | Who viewed/accessed what, when |
> | Offline / degraded | Behaviour when the backend is unreachable |
> | Performance | Pagination limits, caching strategy, lazy loading |
> | Permissions (server-side) | Enforcing access model server-side |
> | Join case / vakalatnama filing | How an advocate joins an existing case |
> | Share access | **[OWNER]** Not in v1. Will cover sharing office staff access to a case. |
> | Calendar | The calendar view mentioned in the prototype app shell |

---

## Last order highlighted in Case History (`TME-06`)

**Dropped 2026-11-11.** Not needed in the case's Case History section.

### From view-case.md §12

> | `TME-06` | The last order issued on the case is highlighted. |

---
