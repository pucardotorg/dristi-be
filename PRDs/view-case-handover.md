# View Case — Developer & Agent Handover

**Status:** v1.7 — 2026-09-15; Complaint removed as a separate section (not attached); Notice/Process Status rewritten as a consolidated process register (recipients, rounds, channels); Hearings moved under Overview as a pop-up, with an order link; Orders cut to title/date/BoTD/PDF, opening an order shows the PDF, court-staff draft and pending-signature behaviour added; order types, mobile layout and pagination rows removed; attendance is a line of text; Applications reduced to one kind — record cut to type/status/dates/filer/side/ID/order/documents, bulk payment and bulk-or-individual signing added, type catalogues dropped
**Date:** 2026-09-11
**Audience:** developers and agents building the View Case module (front end and backend)

## Sources and precedence

| Precedence | Source | Provides |
| --- | --- | --- |
| 1 — **interaction reference** | Dristi app prototype: `Pucar-Dristi-2.0` @ `Feature/Your-Case`, `apps/dristi-app`, routes `/cases/**` | Screen behaviour: navigation, sections, registers, filters, actions |
| 1 — **event catalogue** | [PUCAR Dashboard 2027 — Events/Case Updates](https://docs.superhuman.com/d/PUCAR-Dashboard-2027_dKtL_rwN6Qw/Events_suDoUtbn#Events-Case-Updates_tudKS-s9) | Authoritative list of case update events |
| 2 — **domain** | https://dristidomain.netlify.app/ | §138 journey, actors, procedural stages |
| 3 | `docs/product/product-foundation.md` | Case stages, point-in-time law, Kerala operational spine |
| — | Owner decisions | Recorded inline as **[OWNER]** |

Marks: `[DERIVED]` inferred, confirm before building · `[GAP]` not specified, blocks
the item · `[CURRENT]` today's behaviour, not automatically a requirement · `[PROTO]`
prototype-only, an interaction reference · `[OWNER]` owner decision.

Requirement IDs: `DET/OVW/HRG/ORD/APP/DOC/PTY/SVC/TME/ACT/CF-*` — use in
tickets, commits, test names.

---

# 1. Scope

Viewing a single case from the point of registration through disposal: the case detail
page with all its sections and case actions available to advocates, litigants, clerks,
and other parties associated with a case.

**In:** case detail (overview, case file, notice/process status, orders &
notifications, applications, documents, parties, case history, hearings) · filing
actions from within a case.

**Out:** cases list (separate document) · e-filing flow (separate handover) · court-staff
/ employee screens · scrutiny and registration · post-disposal execution · share access
(not in v1) · backend API contracts (§15).

---

# 2. Entry context

- `ASM-01` — the user is **already logged in** and has navigated to this case from the
  cases list (separate document), a notification, or a direct link.
- `ASM-02` — the user is **associated with the case** and has access to it. This includes
  advocates, litigants, PoA holders, party-in-person, clerks, and any other person with
  case access. The access model is documented in the cases list handover.

---

# 3. Case detail — header

Route: `/cases/[caseId]`

The case header is persistent across all sections.

## 3.1 Identity

| ID | Field | Detail |
| --- | --- | --- |
| `DET-01` | Case number | The **latest** case number generated for this case is shown. Throughout a case's lifecycle, different numbers are generated at different points (e.g. filing number, registration number, appeal number). Only the most recent is displayed in the header. |
| `DET-02` | Case number history | A small icon next to the case number; clicking it shows the **older case numbers** with the point in the lifecycle at which each was generated. |
| `DET-03` | Cause title | `Complainant v. Accused` as `<h1>` |
| `DET-04` | Stage badge | Current stage or disposal outcome (stages and outcomes defined in a separate document) |
| `DET-05` | Secondary stages | An **array** of secondary stage labels shown alongside the primary stage. |
| `DET-06` | Complainant advocates | Names of advocates on record for the complainant side |
| `DET-07` | Accused advocates | Names of advocates on record for the accused side |

## 3.2 Header actions

| ID | Action | Type | Notes |
| --- | --- | --- | --- |
| `ACT-01` | Download case file | Icon button | **[OWNER]** Downloads the PDF that is visible in the Case File section (§6) |
| `ACT-02` | Make filings (dropdown) | Dropdown menu | Contains: Raise application, Submit documents, Raise bail application, Generate bail bond, Bond status. Available to **anyone with case access** — advocates, litigants, PoA holders, party-in-person, clerks. |

**[OWNER]** Share access is **not in v1**.

---

# 4. Section navigation

The case detail page uses a **tab strip** for section navigation. All navigation state
lives in URL search params (`?section=`), not in React state.

| # | Tab label |
| --- | --- |
| 1 | Overview |
| 2 | Case File |
| 3 | Notice/Process Status |
| 4 | Orders & Notifications |
| 5 | Applications |
| 6 | Documents |
| 7 | Parties |
| 8 | Case History |

`DET-08` — an invalid or absent `?section=` defaults to Overview.

---

# 5. Overview

Two-column layout.

## 5.1 Next hearing

| ID | Element | Detail |
| --- | --- | --- |
| `OVW-01` | Date tile | Calendar face: day numeral, weekday, month-year. Shows "Today" on the hearing day. |
| `OVW-02` | Status badge | Status of the next hearing |
| `OVW-03` | Purpose | What the matter is listed for (e.g. "Evidence of complainant") |
| `OVW-04` | No hearing state | **[OWNER]** When no hearing is scheduled (whether the case is active or disposed): shows "No hearing scheduled" |
| `OVW-05` | View All Hearings | **[OWNER]** Link labelled "View All Hearings" (not "View Hearing Details"). Opens the hearings pop-up (§5.4). |

## 5.2 Case updates

The last 3 events that occurred on the case, newest first. Each update is one row.

| ID | Element | Detail |
| --- | --- | --- |
| `OVW-06` | Update text | A single line of text describing what happened |
| `OVW-07` | Date | When the event occurred |
| `OVW-08` | Link | A link to the associated entity (order, hearing, application, document, etc.), when one exists |
| `OVW-09` | Category tag | A tag identifying the category of update (Filing, Orders, Submissions, Process, Hearing, Parties). Full event catalogue maintained in a [separate document](https://docs.superhuman.com/d/PUCAR-Dashboard-2027_dKtL_rwN6Qw/Events_suDoUtbn#Events-Case-Updates_tudKS-s9). |
| `OVW-10` | View all updates | Link to Case History section |

## 5.3 Pending tasks

| ID | Element | Detail |
| --- | --- | --- |
| `OVW-11` | Task list | List of pending tasks on the case |
| `OVW-12` | Task title | What needs to be done |
| `OVW-13` | Due date | When the task is due |
| `OVW-14` | Respond button | Enters the workflow to respond to the pending task |
| `OVW-15` | Archive button | Archives the task (removes it from the pending list without completing the workflow) |

## 5.4 Hearings

The hearings list opens as a **pop-up** over the case detail page, from the "View All
Hearings" link (`OVW-05`).

### 5.4.1 List

| ID | Element | Detail |
| --- | --- | --- |
| `HRG-01` | Columns | Date · Hearing purpose · Status · Action, which opens the hearing detail |
| `HRG-02` | Ordering | Newest first |
| `HRG-03` | Values | Every value in the list is drawn from the hearing record (§5.4.2) |

### 5.4.2 Hearing detail

A hearing carries these fields:

| ID | Field | Notes |
| --- | --- | --- |
| `HRG-04` | Hearing purpose | What the matter was listed for |
| `HRG-05` | Date | Date of the hearing |
| `HRG-06` | Start time | When the hearing started |
| `HRG-07` | End time | When the hearing ended |
| `HRG-08` | Attendance | Who attended the hearing, as a line of text |
| `HRG-09` | Next hearing purpose | What the matter is next listed for |
| `HRG-10` | Next hearing date | The date it is next listed on |
| `HRG-11` | Hearing summary | The order text entered in the order for that hearing. One text, held on the order and read from there. |
| `HRG-12` | Order | The order passed in the hearing. Opens the order (§8). |

---

# 6. Case File

The case file is the case bundle: a prescribed, ordered collection of every document and
artefact on the case — filings, affidavits, evidence, applications, orders, processes,
and notes.

## 6.1 Layout

`DET-09` — **split-pane layout**: a sidebar with a collapsible tree index, and a document
viewer on the right.

| ID | Element | Detail |
| --- | --- | --- |
| `DET-10` | Tree index | Nested collapsible folder tree. Selection via `?doc=` URL param. Each element is either a **heading** (collapsible, contains children) or a **root element** (leaf, corresponds to a file). |
| `DET-11` | Document viewer | Two view modes toggled by `?view=`: PDF (iframe) and Digital (structured `DigitalRecord` component). Both views co-exist in the DOM; inactive one is `invisible`, not unmounted. |
| `DET-13` | Default selection | Opens to the first root element in the tree |
| `DET-12` | Context menu | Right-click on a root element: **Mark as Evidence**, **Mark as Void**, **Download** (downloads the PDF). **Mark as Evidence and Mark as Void are available to court staff and magistrate only** — not to advocates, litigants, or other parties. Download is available to everyone with case access. |

## 6.2 Case file registry

Sources: `[CURRENT]` Case Bundle master table from the existing application,
cross-referenced against the e-filing handover (§14, DCM documents) and the prototype's
document type catalogue.

### Structure rules

The tree is **two levels deep**: sections (collapsible headings) and root elements
(leaves that open a file). No deeper nesting.

- **Row order in the table below = order in the tree.** No separate sequence column.
- When a document type has **multiple instances** on the case (e.g. two cheques), each
  instance appears as its own root element, consecutively, at that position.
- The **Case Cover Page** is a generated title page included in the PDF export only —
  it does not appear in the on-screen tree.

**Instances notation:**

| Value | Meaning |
| --- | --- |
| `1` | Exactly one; always present |
| `0–1` | At most one; may not be present |
| `1+` | One or more |
| `0+` | Zero or more |
| `1 per X` | One for each X on the case |
| `0–1 per X` | At most one per X; may not be present for a given X |

**Sort by** states the field that determines order when multiple instances exist.
`—` where the type is singular.

In the Display name column, `{field}` denotes a variable part drawn from the
document's data — the label the user actually sees in the tree for that instance.

### Registry

| Section | Display name | Instances | Docket page | Sort by | Notes |
| --- | --- | --- | --- | --- | --- |
| Complaint | Complaint | 1 | yes | — | |
| Initial Filings | Cheque | 1+ | yes | chronological | Usually one |
| | Cheque Deposit Slip | 0–1 per cheque | yes | chronological | |
| | Cheque Return Memo | 1 per cheque | yes | chronological | |
| | Demand Notice | 1+ | yes | chronological | |
| | Proof of dispatch of demand notice | 1 per demand notice | yes | chronological | |
| | Proof of service of demand notice | 0–1 per demand notice | yes | chronological | AD card or tracking report |
| | Reply Notice | 0–1 per demand notice | yes | chronological | |
| | Proof of debt or liability | 0+ | yes | chronological | |
| | Proof of reasons for delay | 0–1 | yes | — | Only when delay condonation applies |
| | Proof of authorization | 0–1 | yes | — | PoA authorization |
| | Other Documents | 0+ | yes | chronological | |
| Affidavits | Affidavit under Section 223 BNSS | 1 | yes | — | |
| | Affidavit under Section 225 BNSS | 0–1 | yes | — | Affidavit in lieu of examination in chief |
| | Affidavit under Section 145 NI Act | 1 | yes | — | |
| Vakalats | Vakalatnama — {advocate name} | 1 per advocate | yes | chronological | |
| Additional Filings | Additional Filing | 0+ | yes | chronological | Not marked as evidence, not void |
| Mandatory Submissions | Mandatory Submission | 0+ | yes | chronological | Court-directed |
| Evidence of Complainant | Deposition of {witness number} | 0+ | yes | date of examination | e.g. PW-1, PW-2 |
| | Exhibit {evidence number} | 0+ | yes | date of marking | e.g. P1, P2 |
| | Additional document | 0+ | yes | date of submission | Not marked as exhibit, not void |
| 313 Examination and Plea of Accused | 313 Examination and Plea — {accused name} | 0+ | yes | chronological | One per accused examined |
| Written Statement by Accused | Written Statement — {accused name} | 0+ | yes | chronological | One per accused |
| Evidence of Accused | Deposition of {witness number} | 0+ | yes | date of examination | e.g. DW-1, DW-2 |
| | Exhibit {evidence number} | 0+ | yes | date of marking | e.g. D1, D2 |
| | Additional document | 0+ | yes | date of submission | Not marked as exhibit, not void |
| Court Evidence | Deposition of {witness number} | 0+ | no | date of examination | e.g. CW-1 |
| | Exhibit {evidence number} | 0+ | no | date of marking | |
| | Additional document | 0+ | no | date of submission | |
| Notes | Court Note | 0+ | no | chronological | |
| | Complainant Note | 0+ | yes | chronological | |
| | Accused Note | 0+ | yes | chronological | |
| Pending Applications | {application type} | 0+ | yes | application number | CMP number appended when assigned; includes bail |
| Disposed Applications | {application type} | 0+ | yes | application number | CMP number appended when assigned; includes delay condonation |
| | {order type} | 0+ | no | date issued | The order disposing of the application |
| Bail Documents | Bail Application | 0+ | yes | chronological | |
| | Bail Document | 0+ | yes | chronological | Bond and related documents |
| Memos | Memo | 0+ | yes | chronological | |
| Processes | Notice | 0+ | no | chronological | |
| | Summons | 0+ | no | chronological | |
| | Warrant | 0+ | no | chronological | |
| Payment Receipts | Payment Receipt | 0+ | yes | payment date | |
| Orders | {order type} | 0+ | no | date issued | |

## 6.3 PDF export

`[CURRENT]` — the download case file action (§3.2, `ACT-01`) generates a compiled PDF:

| ID | Requirement | Detail |
| --- | --- | --- |
| `CF-01` | Contents | The same tree structure as the on-screen case file, in the same order |
| `CF-02` | Docket pages | A docket page is inserted before each document whose registry entry has docket page = yes |
| `CF-03` | Docket page path | Each docket page shows the path to the document in the tree (e.g. "5.1.1 Cheque 1 in 5.1 Cheques in 5 Initial Filings") so it can be referenced against the UI |
| `CF-04` | Freshness | Every time the PDF is requested, the last-modified flag is checked and the PDF is regenerated if there has been an update |

---

# 7. Notice/Process Status


This section consolidates **every process the court has issued on the case**, grouped by
the person it was issued to. Orders & Notifications (§8) holds the instrument as a record;
this section holds what happened to it — the channels it went out on, whether it reached
the person, and when.

## 7.1 Who processes are issued to

| ID | Element | Detail |
| --- | --- | --- |
| `SVC-01` | Recipients | A process may be issued to an **accused**, a **witness**, or — in exceptional cases — the **complainant**. All three appear in this section. |
| `SVC-02` | Per-person blocks | One block per person who has process history. Where the drawer is a company, every person in charge is also an accused and receives process separately. |
| `SVC-03` | Party info | Name and role on the case (e.g. "Accused 2", "PW-1", "Complainant") |

## 7.2 Rounds

| ID | Element | Detail |
| --- | --- | --- |
| `SVC-04` | Definition | A **round** is all the processes triggered by the same order, or issued together. A person may have had **multiple rounds**. |
| `SVC-05` | Process type | Each process in a round is a **notice**, **summons**, **proclamation**, **attachment**, or other **miscellaneous process**. |
| `SVC-06` | Ordering | Rounds are ordered oldest to newest; the newest round is shown first. |
| `SVC-07` | Linked hearing | The hearing the process was issued in relation to, and its date. |
| `SVC-08` | Triggering order | The order that triggered the round, and the date that order was issued. |
| `SVC-09` | Process fee | The date the process fee was paid for the round. |

## 7.3 Channels

| ID | Element | Detail |
| --- | --- | --- |
| `SVC-10` | Channel list | A round may carry more than one channel. Every channel selected in the round is listed, each with its own detail below. |
| `SVC-11` | Destination | The destination for that channel, by channel type: **postal address**, **mobile number**, or **email address**. |
| `SVC-12` | Status | The current status of that channel. |
| `SVC-13` | Status date | The date the status was last updated. |
| `SVC-14` | Remarks | Whatever was recorded against the channel — confirmation of delivery, any remark noted with it, or the reason recorded for non-delivery. |

`SVC-15` `[GAP]` — the list of channel types and the status vocabulary per channel are not
yet specified. Blocks `SVC-10`–`SVC-13`.

## 7.4 Visibility

| ID | Rule |
| --- | --- |
| `SVC-16` | Absent when no process has ever issued on the case (nothing to report). |

---

# 8. Orders & Notifications


## 8.1 Layout

| ID | Element | Detail |
| --- | --- | --- |
| `ORD-01` | Kind filter | Toggle: Orders / Notifications. Opens on Orders by default. |
| `ORD-02` | Table | Columns: Date, Title, BoTD (Business of the Day), Action |
| `ORD-03` | Open an order | Opens the order and shows the full PDF |

## 8.2 Order / notification split

Orders are passed by the court. Notifications are court communications about listings;
today the only notification is the bulk reschedule. Process that issues over court staff
signatures "by order of the Court" — summons and the rest — is an order.

## 8.3 Order statuses

| Value | Label | Variant |
| --- | --- | --- |
| `draft-in-progress` | Draft in progress | warning |
| `pending-signature` | Pending signature | info |
| `published` | Published | success |

`ORD-04` — a party to the case sees **published** orders. **Court staff also see orders in
draft and pending signature**, and opening one takes them into the work it is waiting for:

| ID | Status | Opening it |
| --- | --- | --- |
| `ORD-05` | Draft in progress | Opens the order drafting screen |
| `ORD-06` | Pending signature | Opens the PDF with the signing option |

## 8.4 Order record

An order carries:

| ID | Field | Notes |
| --- | --- | --- |
| `ORD-07` | Title | The order's title |
| `ORD-08` | Date | When the order was issued |
| `ORD-09` | BoTD | Business of the Day — the summary of what was passed. Absent until the order is passed. |
| `ORD-10` | PDF | The order document itself |

---

# 9. Applications


Everything in this section is an application — one kind, many types.

## 9.1 Layout

| ID | Element | Detail |
| --- | --- | --- |
| `APP-01` | Type filter | Combobox of application types |
| `APP-02` | Status filter | Select: draft, pending-signature, pending-payment, completed, rejected, expired |
| `APP-03` | Filed by filter | Combobox of people on the case |
| `APP-04` | Search | By application ID |
| `APP-05` | "Needs attention" well | Pinned above the table. Shows applications that still need a step from the viewer: drafts, pending-signature, pending-payment. |
| `APP-06` | Table | `[DERIVED]` Columns: Type, Application ID, Status, Filed by, Created on, Submitted on, Action |
| `APP-07` | Open an application | Opens the application, the documents attached to it, and the linked order where there is one |

`APP-08` `[DERIVED]` — the record carries both a created and a submitted date (§9.4), so the
table shows both. Confirm which the register leads on.

## 9.2 "Needs attention" grouping

`APP-09` — two or more applications waiting on the **same step from the same filer**
collapse into one entry with one action.

`APP-10` Signing — signatures can be added **one at a time or in bulk**. In v1, bulk
signing is offered only to a filer who has set up their bulk signing tool; everyone else
signs one application at a time.

`APP-11` Payment — payments can be completed **one at a time or in bulk**.

## 9.3 Filing statuses

| Value | Label | Variant | Needs attention? |
| --- | --- | --- | --- |
| `draft` | Draft | warning | Yes — "Continue draft" |
| `pending-signature` | Pending signature | warning | Yes — "Add signature" |
| `pending-payment` | Pending payment | warning | Yes — "Complete payment" |
| `completed` | Completed | success | No |
| `rejected` | Rejected | destructive | No |
| `expired` | Expired | secondary | No |

## 9.4 Application record

An application carries:

| ID | Field | Notes |
| --- | --- | --- |
| `APP-12` | Type | One of the application types |
| `APP-13` | Status | Filing workflow status (§9.3) |
| `APP-14` | Created on | When the application was created |
| `APP-15` | Submitted on | When it was submitted |
| `APP-16` | Filed by | The person who submitted the application |
| `APP-17` | Side | Whether it was filed by the complainant, the accused, or the court. Held separately from the person, not derived from them. |
| `APP-18` | Application ID | The registry's identifier, once allotted |
| `APP-19` | Linked order | The order the court passed on the application, where there is one |
| `APP-20` | Documents | The files attached to the application |

---

# 10. Documents


## 10.1 Layout

| ID | Element | Detail |
| --- | --- | --- |
| `DOC-01` | Sub-tabs | Documents and Bail bonds (two sibling populations, not a type filter) |
| `DOC-02` | Type filter | Grouped combobox of document types (see §10.3) |
| `DOC-03` | Submitted by filter | Combobox of people on the case |
| `DOC-04` | Search | By filing ID |
| `DOC-05` | Table | Columns: Document (title + source + filing ID), Document type, Submitted by, Submitted on, Submission status, Evidence (marked/objected badges with evidence numbers), Actions (download). |
| `DOC-06` | Record dialog | Detail view of a single document |

## 10.2 Document statuses

Same as filing statuses plus one additional state:

| Value | Label | Notes |
| --- | --- | --- |
| `pending-review` | Pending review | Between signature and the magistrate's decision. Not present in the Applications register. |

## 10.3 Document types

~18 types, organised into six groups:

| Group | Types |
| --- | --- |
| Complaint pack | Legal demand notice, Proof of dispatch, Dishonoured cheque, Cheque return memo, Vakalatnama, Party-in-person affidavit |
| Affidavits | Affidavit under section 223 BNSS, Affidavit under section 225 BNSS, Affidavit under section 145 NI Act |
| Exhibits | Account records, Proof of debt or liability, Proof of deposit of cheque, Exhibit index, Documentary |
| Witness records | Witness deposition |
| Court forms | Plea record, Questionnaire under section 351 BNSS, Mediation |
| Bail bonds | Bail bond |

## 10.4 Document sources

| Value | Label |
| --- | --- |
| `case-filing` | Case filing |
| `application` | Application |
| `hearing` | Hearing |
| `court` | Court |

## 10.5 Evidence tracking

| Field | Values | Notes |
| --- | --- | --- |
| Evidence number | String (e.g. "P1", "D2") or null | Assigned when evidence is marked |
| Evidence status | `marked` / `void` / null | Court treatment after submission workflow completes |

## 10.6 Document record

Each document carries:

| Field | Notes |
| --- | --- |
| Filing ID | The registry's own identifier |
| Title | Display title |
| Type | From the catalogue |
| Submission status | Filing workflow status (including `pending-review`) |
| Submitted on | Date |
| Submitted by | Person ID |
| Source | Where it came from: case filing, application, hearing, court |
| Linked application | Reference back to the application it was submitted through |
| Linked hearing | Reference to the hearing it was produced at |
| Evidence number | Assigned when marked as evidence |
| Evidence status | Marked or void |
| File | PDF with optional page reference |

---

# 11. Parties


## 11.1 Layout

| ID | Element | Detail |
| --- | --- | --- |
| `PTY-01` | Master-detail browser | Master list on the left, detail pane on the right. Selection via `?selected=` URL param. |
| `PTY-02` | Default selection | First litigant. A stale or invalid `?selected=` falls back to the first litigant. |

## 11.2 Three populations

### Litigants

| ID | Field | Notes |
| --- | --- | --- |
| `PTY-03` | Side | Complainant or accused |
| `PTY-04` | Kind | Individual or entity |
| `PTY-05` | Entity type | "Partnership firm", "Private limited company" — entities only |
| `PTY-06` | Designation | How an individual stands inside an entity, e.g. "Managing partner" |
| `PTY-07` | Entity representative | The human who answers for an entity in court. On the accused side, this person is separately liable (carries their own party record). On the complainant side, the representative is not a party. **Not "legal representative"** — §2(11) CPC gives that term to the estate of a deceased person, which is wrong here. |
| `PTY-08` | Represents | When an individual is a person in charge of an entity (§141). Links back to the entity. Distinguishes between entity representative and person in charge. |
| `PTY-09` | Power of attorney holder | At most one per litigant. Acts for the party but is not a party in their own right. |
| `PTY-10` | Party in person | The party is conducting their own case. **Not the same as an empty advocate list.** PiP is a decision the party made; an empty list is the registry not holding a vakalatnama. One says "this person is representing themselves"; the other says "we do not know who represents them". |
| `PTY-11` | Advocates | Resolved from legal teams. A party-in-person with an advocate on record is a contradiction and must error. |

### Witnesses

| ID | Field | Notes |
| --- | --- | --- |
| `PTY-12` | Side | Complainant, accused, or neither (court witness) |
| `PTY-13` | Number | Composed from prefix + index: PW-1, DW-2, CW-1. **Side is a field, never derived from the prefix** — they are two authored fields and must agree. |
| `PTY-14` | Description | Free text |
| `PTY-15` | Linked party | The party whose evidence this witness speaks to |
| `PTY-16` | Added by | Complainant, accused, or court |

### Support people

| ID | Field | Notes |
| --- | --- | --- |
| `PTY-17` | Role | Junior or Clerk |
| `PTY-18` | De-duplication | One row per person, not per advocate they work under. A clerk under two advocates is one person with two advocates listed. |
| `PTY-19` | Advocates | Every advocate on record this person works under |

## 11.3 Legal teams

`PTY-20` — one team per advocate on record. Each team carries:

- Advocate name (must be on `record.counsel[side]`)
- Side
- Client party IDs
- Whether the advocate is shared across multiple parties
- Juniors and clerks

`PTY-21` — either all of a case's teams are authored or none are. A half-authored case
throws — the mismatch cannot be resolved silently.

## 11.4 Counts

`PTY-22` — every tab count equals the length of the list behind it:

- Litigants: every party on the cause title, entities included
- Witnesses: every witness, court's own included
- Legal teams: one per advocate on record
- Support people: every junior and clerk, de-duplicated by person

## 11.5 Viewer awareness

`PTY-23` — the viewer's own row is rendered as "you" rather than a removal target. You
do not remove yourself from a case you are reading.

---

# 12. Case History


| ID | Element | Detail |
| --- | --- | --- |
| `TME-01` | Timeline layout | Vertical timeline grouped by date, newest first |
| `TME-02` | Date range | Shown in card header: first event to latest event |
| `TME-03` | Events | Each event links to its origin section |

## 12.1 Event types

Case history draws from the same event catalogue as the overview case updates (§5.2).
The full event catalogue is maintained in a [separate document](https://docs.superhuman.com/d/PUCAR-Dashboard-2027_dKtL_rwN6Qw/Events_suDoUtbn#Events-Case-Updates_tudKS-s9).
The overview shows only the last 3; case history shows all.

---

# 13. Bail lifecycle

A cross-cutting flow managed through React context (`CaseBailProvider`) spanning the case
detail page so the header dropdown and the overview card share state.

## 13.1 Phases

| Phase | What happens |
| --- | --- |
| `none` | No bail activity |
| `task` | Magistrate has approved bail with terms; the task is to raise the bond |
| `signing` | Bond generated, out for signatures |
| `review` | Signatures complete; status review |

## 13.2 Entry points

- "Make filings" dropdown in header → "Raise bail application"
- Bond task row in Overview's pending tasks

## 13.3 Dialogs

| Dialog | Purpose |
| --- | --- |
| Bail application | Raise a bail application |
| Bail bond | Generate the bond document (with mode: generate or view) |
| Bail bond status | Review status of an outstanding bond |

---

# 14. Open questions

| # | Question | Blocks | Owner |
| --- | --- | --- | --- |
| Q-1 | Case number formats — two coexist in the prototype (`DET-01`). Which formats, and is migration needed? | `DET-01` | Product |
| Q-2 | Download case file (`ACT-01`) — §6.3 documents the `[CURRENT]` PDF export behaviour. Confirm this is the intended format for the new system, or whether alternatives (ZIP, selective sections) are needed. | `ACT-01` | Product |
| Q-3 | Notice/Process Status — what is the list of channel types, and the status vocabulary for each? | `SVC-15` | Product |
| Q-4 | What filing actions should be available from within a case? The prototype offers: Raise application, Submit documents, Raise bail application, Generate bail bond, Bond status. | `ACT-02` | Product |
| Q-5 | Should disposed cases show any filing actions? | `ACT-02` | Product |
| Q-6 | Secondary stages (`DET-05`) — what values can this array hold, and how are they set/cleared? | `DET-05` | Product |
| Q-7 | Pending tasks — what is the full list of task types, and what workflow does each "Respond" button enter? | `OVW-14` | Product |

---

# 15. Not yet covered

The following are known to be needed but are not specified in this document:

| Area | Notes |
| --- | --- |
| Backend API contracts | Endpoints, payloads, pagination, real-time updates |
| Data model (server) | Database schema, relationships, indices |
| Search | Full-text search across cases, documents, orders |
| Notifications | Push/in-app notifications for case events |
| Audit trail | Who viewed/accessed what, when |
| Offline / degraded | Behaviour when the backend is unreachable |
| Performance | Pagination limits, caching strategy, lazy loading |
| Permissions (server-side) | Enforcing access model server-side |
| Join case / vakalatnama filing | How an advocate joins an existing case |
| Share access | **[OWNER]** Not in v1. Will cover sharing office staff access to a case. |
| Calendar | The calendar view mentioned in the prototype app shell |
