# Dropped ideas

**Status:** 2026-10-19 — created; locked and optional variables, dropped from the order template catalogue and the order generation PRD. Then order item templates and the template system, dropped from the catalogue. 2026-10-20 — application detail cut from the order generation PRD; the per-court setting for where attendance and the next hearing are entered; the one-press hearing control; the trigger summary before marking order data complete; personal shortcuts seeded from the catalogue. 2026-10-29 — shortcuts saved per courtroom.

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

Under *9. Issue of summons · 10. Issue of warrants · 20. Issue of proclamation · 21. Issue of attachment*, the note on channels read: "Channels, addresses and police station are not in the template. They are inputs the process workflow needs, asked for as part of the order item (`ITM-11` of order-generation.md); their rules are owned by process-handover.md."

### From order-generation.md

| ID | Requirement as it was |
|---|---|
| `ITM-11` | An order item may need input beyond its template variables, where the workflow it triggers needs it — the delivery channels per recipient for a process order (`PRC-03` of [`process-handover.md`](process-handover.md)). That input is asked for as part of the order item; its fields are owned by the workflow's own document. |
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
> [`process-handover.md`](process-handover.md).

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
