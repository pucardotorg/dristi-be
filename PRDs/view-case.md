# View Case

**Status:** v1.70 — 2026-11-11; `PTY-47`, `PTY-50`: who adds, removes or replaces a power of attorney holder, and the application behind it, are not yet decided (application-lifecycle `Q-16`). v1.69 — 2026-11-11; `DET-03`: removed the note that the title is not composed from the party names. v1.68 — 2026-11-11; `ACT-02`: Make filings offers Raise application, Submit documents and Generate bail bond, each shown to anyone its flow's PRD allows to use it; "both sides" replaced by "the court side and the citizen side" where that is what it meant (`ACT-01`, `ACT-04`, `DET-12`); `ACT-04` also shows the case's access code for sharing (join-a-case `JOIN-09`). v1.67 — 2026-11-11; `DOC-15`: every document has a number — its exhibit number once marked, until then a unique system identifier; Q-15 answered and removed. v1.66 — 2026-11-11; `TME-06` (last order highlighted in Case History) removed, to [`dropped-ideas.md`](dropped-ideas.md). v1.65 — 2026-11-11; open questions cleaned up — answered or owned by another PRD, and now linked from the requirement: case number formats to [`case-numbers.md`](case-numbers.md) (`DET-01`, Q-1); filing actions offered at every stage (`ACT-02`, Q-5); secondary stages to [`case-lifecycle.md`](case-lifecycle.md) §4 (`DET-05`, Q-6); pending tasks to [`pending-tasks.md`](pending-tasks.md) (`OVW-14`, Q-7); court and citizen differences now called out in each section (Q-8); share access to [`office-management.md`](office-management.md) (`ACT-04`, Q-9). Q-12–Q-15 stay open. v1.64 — 2026-11-11; §14 Not yet covered removed — no other PRD keeps one — and moved to [`dropped-ideas.md`](dropped-ideas.md); Enhancements is now §14; §1's Out list no longer points to it. v1.63 — 2026-11-11; Case History (§12) rewritten to match the overview: every update newest first, each showing what it shows in the overview (`TME-04`), updates on one application or process can be grouped (`TME-05`), the last order highlighted (`TME-06`), filterable, with every order kept when filtered to orders (`TME-07`); `TME-03` folded into `TME-04`; `TME-02` (date range) removed. §13 Bail lifecycle removed; later sections renumbered (§13 Open questions, §14 Not yet covered, §15 Enhancements). Both moved to [`dropped-ideas.md`](dropped-ideas.md). v1.62 — 2026-11-11; §11.2 heading now says "not at launch", replacing the At launch column. v1.61 — 2026-11-11; `PTY-46` leads to the vakalatnama generation flow, not yet defined; `PTY-49` — the person removing an advocate chooses between an application to the court and a request to the advocate to approve; `PTY-50` remove or replace a power of attorney holder confirmed — advocate-level access, by application, not at launch — and the prototype table and Q-18 removed. v1.60 — 2026-11-11; §11.2: no party action is at launch. `PTY-46` adds a new advocate to the vakalatnama, started by any litigant or advocate on record, through a vakalatnama generation flow not yet defined; Q-17 answered and removed. Remove an advocate (`PTY-49`) and Become party in person (`PTY-52`) confirmed and moved into the main table; Q-18 now covers only `PTY-50`. v1.59 — 2026-11-11; §11.2 launch scope set: only adding an advocate (`PTY-46`) is at launch; Q-16 answered and removed. `PTY-48`: editing a witness's details is for advocate-level access, through an Edit Witness Details application not yet defined. v1.58 — 2026-11-11; §11.2: most actions, not all, lead into a flow set elsewhere; `PTY-43` — who can edit is flexible, a court may restrict it to the complainant side; `PTY-44` — an address can be added for a witness too; `PTY-45` — the court side adds a witness directly, advocate-level access through the application; `PTY-48` worded like the other rows. v1.57 — 2026-11-11; new §11.2 Actions on people: the entry points from the Parties section — edit a litigant's details, add an address for an accused before they join, add a witness, add an advocate, add a power of attorney holder (`PTY-43`–`PTY-47`); editing witness details not offered (`PTY-48`); three actions from the prototype listed for confirmation (`PTY-49`, `PTY-50`, `PTY-52`); new Q-16–Q-18. v1.56 — 2026-11-11; `PTY-40`: a witness shows both name and designation when both are held. v1.55 — 2026-11-11; §11 intro: the latest details held for each person are shown, without naming how they change. v1.54 — 2026-11-11; Parties (§11) cut to one table of people and the details shown for each (new `PTY-33`–`PTY-42`); a complainant's authorised representative has an entry of their own (`PTY-35`); how people are organised and shown is left to the UI. Kept: `PTY-24`–`PTY-26`, `PTY-28`. Everything else in §11 (`PTY-01`–`PTY-14`, `PTY-17`–`PTY-20`, `PTY-23`, `PTY-27`, `PTY-29`, `PTY-31`, `PTY-32`) moved to [`dropped-ideas.md`](dropped-ideas.md). v1.53 — 2026-11-11; `PTY-07`–`PTY-09`: removed what v1.52 added beyond the earlier rows — that a representative or PoA holder is not listed as a litigant, and that an institution's entry names each person in charge. v1.52 — 2026-11-11; litigant rules (`PTY-07`–`PTY-11`) rewritten as full sentences saying what each litigant's entry shows; the advocates' bar registration ID now sits in `PTY-11`, so the separate Advocates field added in v1.49 is gone. v1.51 — 2026-11-11; `PTY-22` (counts per group) removed, left to the UI, and moved to [`dropped-ideas.md`](dropped-ideas.md). v1.50 — 2026-11-11; Parties (§11): "legal team" and "support people" replaced by the existing terms — an advocate on record and the members of their office with access to the case ([`office-management.md`](office-management.md)) (`PTY-01`, `PTY-11`, `PTY-18`–`PTY-20`, `PTY-22`). v1.49 — 2026-11-11; Parties (§11) rewritten: what each person shows, with links to the PRD that collects it — litigant details (new `PTY-27`), every address on record (new `PTY-28`), PoA holder's details (new `PTY-29`), witness details (new `PTY-31`), what the witness will prove in place of a free-text description (`PTY-14`), a junior's or clerk's identifier (new `PTY-32`); contact details shown to everyone at launch, masking a later enhancement (new `PTY-24`, §16); no documents (new `PTY-25`) and never an Aadhaar number (new `PTY-26`); legal teams described in plain terms (`PTY-20`); the rule that a case's teams are all authored or none (`PTY-21`) removed to [`dropped-ideas.md`](dropped-ideas.md); `PTY-23` no longer mentions removal. v1.48 — 2026-11-11; witnesses (§11): `PTY-13` no longer says how the number is formed; Linked party (`PTY-15`) and Added by (`PTY-16`) removed, since both follow from the side, and moved to [`dropped-ideas.md`](dropped-ideas.md). v1.47 — 2026-11-11; Parties (§11): "entity" is now "institution", the term the other PRDs use (`PTY-04`–`PTY-08`, `PTY-22`); `PTY-07` rewritten in plain terms — a complainant institution's authorised representative is not a party; for an accused institution each person in charge is an accused. v1.46 — 2026-11-11; Documents (§10): "kinds" renamed **sources**, matching document-submission `DSB-22` (§10.1, `DOC-07`, `DOC-08`); new §10.3 lists a document's attributes — title, source, type, submitted by, submitted on, number, file, status (`DOC-10`–`DOC-17`), which `DOC-05` now points to; new Q-12–Q-15 for what is not yet set. v1.45 — 2026-11-11; Documents (§10) is the place for every document that has no section of its own; vakalatnamas and payment receipts added as kinds (§10.1). v1.44 — 2026-11-11; Documents (§10) generalised like Orders & Notifications: new §10.1 lists the kinds shown — filing, application attachments, submitted directly, bail bonds, recorded statements — and what is not shown here; every kind is returned, marked with its kind, and how the screen separates them is a UI choice (new `DOC-07`, replacing `DOC-01`); the list can show any attribute (`DOC-05`) and be filtered and searched (new `DOC-08`, replacing `DOC-02`–`DOC-04`); drafts and pending signature shown as needing attention (new `DOC-09`). `DOC-01`–`DOC-04` moved to [`dropped-ideas.md`](dropped-ideas.md). v1.43 — 2026-11-11; `APP-07`: opening an application also shows when it was filed, the objection or where it stands, and the previous order (application-lifecycle `ALC-23`), to everyone who can see it. v1.42 — 2026-11-11; `APP-08`: by default the applications list is ordered by date created, newest first. v1.41 — 2026-11-11; Applications (§9) rounded out: an intro on what the section is; the list can show any of an application's attributes, the choice being the UI's (`APP-06`); the list can be filtered and searched by them (new `APP-22`); a line on why Needs attention exists (§9.2); `APP-08` now asks which date orders the list. v1.40 — 2026-11-11; Applications (§9) brought in line with [`application-lifecycle.md`](application-lifecycle.md), which now owns statuses and attributes: the status list (Draft … Completed, Rejected, Expired) and the application record (`APP-12`–`APP-20`) replaced by a link, and moved to [`dropped-ideas.md`](dropped-ideas.md) — they disagreed with the lifecycle (no Pending Review, Pending Decision, Accepted, Dismissed or Submitted; one linked order instead of every order; a court side; an ID allotted later instead of an application number from submission); new `APP-21` on who sees an application (`ALC-17`, `ALC-27`); `APP-06` uses the lifecycle's attribute names; `APP-07` opens the signed application, supporting documents, every order and any objection. v1.39 — 2026-11-11; Applications (§9): filters and search removed, left to the UI (`APP-01`–`APP-04`); Needs attention (§9.2) is only the applications in draft, pending signature or pending payment (`APP-05`), and its grouping and bulk signing and payment are removed (`APP-09`–`APP-11`); all moved to [`dropped-ideas.md`](dropped-ideas.md). v1.38 — 2026-11-11; order record (§8.4) carries the order's type where the state has more than one (new `ORD-11`). v1.37 — 2026-11-11; §8.2: removed the sentence saying a process issued "by order of the Court" is an order; processes are in §7 ([`process.md`](process.md)). v1.36 — 2026-11-11; Orders & Notifications (§8) generalised: everything the court issues on the case is returned — orders of every type, notifications, and diary entries that are documents of their own — each marked with its kind; how the screen separates them is a UI choice (`ORD-01`, §8.2). v1.35 — 2026-11-11; new §16 Enhancements: order data viewable with the order, in a later version. v1.34 — 2026-11-11; BoTD replaced by the order's diary text (`ORD-02`, `ORD-09`), as in the overview (`OVW-17`). v1.33 — 2026-11-11; each process shows its process document, the PDF that was sent (new `SVC-22`). v1.32 — 2026-11-11; §7.4 removed: the section is no longer hidden when no process has issued (`SVC-16`, to [`dropped-ideas.md`](dropped-ideas.md)); it is always available and shown empty instead (new `SVC-21`). v1.31 — 2026-11-11; `SVC-18` renamed Supporting file, the term in [`process.md`](process.md) `DSP-08`. v1.30 — 2026-11-11; each process shows its reason for non-delivery where it applies (new `SVC-20`); `SVC-14` Remarks is now the comment only. v1.29 — 2026-11-11; a round keeps the definition in [`process.md`](process.md) §3; where it holds more than one process type, its processes are shown in one group per type (new `SVC-19`, `SVC-05`). v1.28 — 2026-11-11; Notice/Process Status (§7) brought in line with [`process.md`](process.md): §7.3 lists processes, not channels — a process is one type, recipient, channel and destination, and carries its own status (`SVC-10`); a round is the processes from one order, without "or issued together" (`SVC-04`); rounds newest first (`SVC-06`); warrant added and custom process named (`SVC-05`); the company and each person in charge are separate recipients (`SVC-02`); police station added as a destination (`SVC-11`); channels and statuses now come from process.md, closing the gap (`SVC-15`) and Q-3; remarks follow `DSP-08`/`DSP-09` (`SVC-14`); new `SVC-17` (channel) and `SVC-18` (outcome file); tables split into rules and fields. v1.27 — 2026-11-11; `SVC-09`: the process fee is on each process, not the round; moved from §7.2 to §7.3. v1.26 — 2026-11-11; `DET-15` says exhibit number; `DET-20` and `ACT-01`: a court can choose not to offer the single-PDF download. v1.25 — 2026-11-11; Case File (§6) rewritten into index (§6.1), what each document shows (§6.2), viewing (§6.3), actions (§6.4) and downloading the whole case file (§6.5): headings up to two levels deep (`DET-10`); each document shows its name and number (new `DET-14`, `DET-15`); a document generated from form data can be viewed as data, with the reason (`DET-11`); download and Mark as Evidence only, on documents not headings, several at once (`DET-12`, new `DET-16`–`DET-18`); whole case file as a zip of individual files or a single PDF (new `DET-19`, `DET-20`), which `ACT-01` now points to; Q-10 answered and removed; marking now links to [`evidence-marking.md`](evidence-marking.md). v1.24 — 2026-11-11; §5.4 Hearings (`HRG-01`–`HRG-12`) removed, with Q-11, and moved to [`dropped-ideas.md`](dropped-ideas.md): the case has no list of hearings or hearing detail. v1.23 — 2026-11-11; `OVW-14` and Q-7: Respond renamed to Act. v1.22 — 2026-11-11; §5.1–§5.3 tables split by kind of row — rules, what each item shows, and what the user can do; IDs and meaning unchanged, wording adjusted only to read as a rule or a field. v1.21 — 2026-11-11; `OVW-11`: pending tasks are the tasks open for the viewing user, on either side; pending tasks taken out of Q-8. v1.20 — 2026-11-11; case updates (§5.2) spelled out: everything from the newest update down to, and including, the last order issued, with an example; new `OVW-16` (last order highlighted), `OVW-17` (an order shows its diary entry text) and `OVW-18` (updates on the same application or process can be grouped); `OVW-06` (one line of update text) removed, to [`dropped-ideas.md`](dropped-ideas.md). v1.19 — 2026-11-11; next hearing (§5.1) shows the date and purpose only: `OVW-02` (status) and `OVW-05` (View All Hearings) removed, as on the court side, and moved to [`dropped-ideas.md`](dropped-ideas.md); new Q-11 on how the hearings list (§5.4) is reached. v1.18 — 2026-11-11; UI detail taken out across §3–§13: routes, URL parameters, React and DOM detail, layout (tabs, panes, pop-ups, columns, dropdowns, badges, colour variants) and control types removed; each row now says what is shown or possible. No requirement added or removed; IDs unchanged. v1.17 — 2026-11-11; header actions (§3.2): Make filings is citizen side only (`ACT-02`); new `ACT-03` Generate order and Submit documents on the court side; new `ACT-04` Share access to this case, on both sides, replacing "not in v1"; Q-4 answered and removed; new Q-9 (share access) and Q-10 (download); §2.1 and Q-8 updated to match. v1.16 — 2026-11-11; `DET-03`: the case title is the one finalised at registration, shown as it is, not composed from the party names. v1.15 — 2026-11-11; `DET-02` no longer describes how the case number history is opened. v1.14 — 2026-11-11; scope runs from registration onwards, with no end stage (§1); each section calls out its own court/citizen differences and §2.1 summarises them; `ASM-01`: where the user came from is examples only; `ASM-02` is any user with access to the case, court side or citizen side; `ASM-03` removed. v1.13 — 2026-11-11; Overview (§5) is the same on both sides; case updates now run from the newest down to the last order issued, so their number varies (§5.2, §12.1); pending tasks are the viewing user's (`OVW-11`). v1.12 — 2026-11-11; the PRD now covers court-side and citizen-side users alike: scope (§1) and access (`ASM-02`, new `ASM-03`) cover both, and new §2.1 sets out what differs between them; new Q-8 for the differences not yet decided. v1.11 — 2026-11-11; §6.2 Case file registry and §6.3 PDF export (`CF-01`–`CF-04`) removed, with Q-2 on the PDF format; what the case file holds, its order and the downloaded PDF are now set by [`case-file.md`](case-file.md). v1.10 — 2026-11-03; title no longer ends in "Developer & Agent Handover"; file renamed to `view-case.md`. v1.9 — 2026-10-22; Mark as Void removed; Court Evidence has no exhibits — the court marks as P or D; any document in the case file can be marked as evidence (`DET-12`); Documents (§10) now points to [`document-submission.md`](document-submission.md) — evidence number column replaces submission status, types and statuses follow that PRD. v1.8 — 2026-10-18; `DET-12`: Mark as Evidence and Mark as Void need the **Evidence marker** role ([`court-roles.md`](court-roles.md)), not a staff title. v1.7 — 2026-09-15; Complaint removed as a separate section (not attached); Notice/Process Status rewritten as a consolidated process register (recipients, rounds, channels); Hearings moved under Overview as a pop-up, with an order link; Orders cut to title/date/BoTD/PDF, opening an order shows the PDF, court-staff draft and pending-signature behaviour added; order types, mobile layout and pagination rows removed; attendance is a line of text; Applications reduced to one kind — record cut to type/status/dates/filer/side/ID/order/documents, bulk payment and bulk-or-individual signing added, type catalogues dropped
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

Viewing a single case from registration onwards, at any stage: the case detail
page with all its sections and case actions. The page is the same for everyone who can
see the case, on the **court side** (court staff, by role) and the **citizen side**
(advocates, litigants, clerks and others associated with the case). Where what a person
sees or can do differs between the two, the section concerned says so, and §2.1
summarises the differences.

**In:** case detail (overview, case file, notice/process status, orders &
notifications, applications, documents, parties, case history, hearings) · filing
actions from within a case.

**Out:** cases list (separate document) · e-filing flow (separate handover) · scrutiny
and registration · post-disposal execution · share access (not in v1).

---

# 2. Entry context

- `ASM-01` — the user is **already logged in** and has opened this case from any of the
  places that lead to it — for example the cases list, a notification or a direct link.
- `ASM-02` — the user is **anyone with access to the case**, on the court side or the
  citizen side.

## 2.1 Court side and citizen side

A summary of the differences each section calls out. Anything not listed applies to both.

| Area | Court side | Citizen side |
| --- | --- | --- |
| Orders & Notifications (§8) | Also sees orders in draft and pending signature, and opening one takes them into the work it is waiting for (`ORD-04`–`ORD-06`) | Sees published orders only (`ORD-04`) |
| Header actions (§3.2) | Generate order and Submit documents (`ACT-03`) | Make filings (`ACT-02`) |
| Case file — Mark as Evidence (`DET-12`) | Available to holders of the Evidence marker role | Not available |


---

# 3. Case detail — header

The header is shown in every section of the case.

## 3.1 Identity

| ID | Field | Detail |
| --- | --- | --- |
| `DET-01` | Case number | The **latest** case number generated for this case is shown. Throughout a case's lifecycle, different numbers are generated at different points (e.g. filing number, registration number, appeal number). Only the most recent is displayed in the header. Case numbers and their formats are set by [`case-numbers.md`](case-numbers.md). |
| `DET-02` | Case number history | The user can see the **older case numbers**, each with the point in the lifecycle at which it was generated. |
| `DET-03` | Case title | The case title as finalised at registration, shown as it is. |
| `DET-04` | Stage | Current stage or disposal outcome (stages and outcomes defined in a separate document) |
| `DET-05` | Secondary stages | Any secondary stages the case is in, shown with the primary stage. There can be more than one. Secondary stages are set by [`case-lifecycle.md`](case-lifecycle.md) §4. |
| `DET-06` | Complainant advocates | Names of advocates on record for the complainant side |
| `DET-07` | Accused advocates | Names of advocates on record for the accused side |

## 3.2 Header actions

| ID | Action | Notes |
| --- | --- | --- |
| `ACT-01` | Download case file | Downloads the whole case file, as individual files or, where the court offers it, as a single PDF (§6.5). Available on the court side and the citizen side. |
| `ACT-02` | Make filings | Offers: Raise application ([`application-lifecycle.md`](application-lifecycle.md)), Submit documents ([`document-submission.md`](document-submission.md)), Generate bail bond ([`bail-bond.md`](bail-bond.md)). Each is shown to anyone that flow's PRD allows to use it. Not offered on the court side. Offered at every stage of the case. |
| `ACT-03` | Generate order, Submit documents | Court side only, in place of Make filings. Generate order follows [`order-generation.md`](order-generation.md); Submit documents follows [`document-submission.md`](document-submission.md). |
| `ACT-04` | Share access to this case | Always available, on the court side and the citizen side. What it does is set by [`office-management.md`](office-management.md). It also shows the case's access code, for sharing with people who need to join the case ([`join-a-case.md`](join-a-case.md) `JOIN-09`). |

---

# 4. Section navigation

The case is organised in these sections:

| # | Section |
| --- | --- |
| 1 | Overview |
| 2 | Case File |
| 3 | Notice/Process Status |
| 4 | Orders & Notifications |
| 5 | Applications |
| 6 | Documents |
| 7 | Parties |
| 8 | Case History |

`DET-08` — the case opens on Overview, unless a link names another section.

---

# 5. Overview

The overview is the same on the court side and the citizen side.

## 5.1 Next hearing

The next hearing shows:

| ID | Field | Detail |
| --- | --- | --- |
| `OVW-01` | Date | The date of the next hearing, with its weekday. Marked as today on the hearing day. |
| `OVW-03` | Purpose | What the matter is listed for (e.g. "Evidence of complainant") |

| ID | Requirement |
| --- | --- |
| `OVW-04` | **[OWNER]** When no hearing is scheduled (whether the case is active or disposed), it says "No hearing scheduled". |

## 5.2 Case updates

The overview shows the case's recent updates, newest first: every update from the newest
down to, and including, the **last order issued on the case**. Nothing older than that
order is shown here. So the number of updates varies: one, if nothing has happened since
the last order, or many, if a lot has.

For example, if the last order was issued on 3 October and since then an application was
filed and a summons was sent, the overview shows the summons, the application and the
3 October order, in that order.

| ID | Requirement |
| --- | --- |
| `OVW-16` | The last order issued on the case is highlighted. It is always the oldest update shown. |
| `OVW-18` | Several updates on the same application or process can be shown together as one group, under that application or process. Updates within a group are also newest first. |
| `OVW-10` | View all updates opens Case History (§12). |

Each update shows:

| ID | Field | Detail |
| --- | --- | --- |
| `OVW-07` | Date | When the event occurred |
| `OVW-09` | Category | The category of update (Filing, Orders, Submissions, Process, Hearing, Parties). Full event catalogue maintained in a [separate document](https://docs.superhuman.com/d/PUCAR-Dashboard-2027_dKtL_rwN6Qw/Events_suDoUtbn#Events-Case-Updates_tudKS-s9). |
| `OVW-17` | Order's diary text | Orders only: the order's diary entry text ([`order-generation.md`](order-generation.md) §14.1). Other updates have no descriptive text. |
| `OVW-08` | Link | Opens the related record (order, hearing, application, document, etc.), when one exists |

## 5.3 Pending tasks

| ID | Requirement |
| --- | --- |
| `OVW-11` | Every task on the case that is open for the viewing user is listed. Tasks open only for other people are not shown. |

Each task shows:

| ID | Field | Detail |
| --- | --- | --- |
| `OVW-12` | Task title | What needs to be done |
| `OVW-13` | Due date | When the task is due |

The user can:

| ID | Action | Detail |
| --- | --- | --- |
| `OVW-14` | Act | Takes the user into the workflow to act on the pending task. The tasks, and the workflow each leads into, are set in [`pending-tasks.md`](pending-tasks.md) and its master tables. |
| `OVW-15` | Archive | Archives the task (removes it from the pending list without completing the workflow) |

---

# 6. Case File

The case file holds **every document related to the case**: filings, orders,
applications, processes, payment receipts and anything else on the case. What it holds,
in what order, and how the single-PDF download is laid out are set by
[`case-file.md`](case-file.md). This section covers what the user can see and do with it.

## 6.1 Index

| ID | Requirement |
| --- | --- |
| `DET-09` | The case file has an index of its contents and shows the document selected in it. |
| `DET-10` | Each entry in the index is either a **heading**, which groups the entries under it, or a **document**. Headings go up to two levels deep: for example, heading 4, under it heading 4.2, and under that document 4.2.2. |
| `DET-13` | The case file opens on the first document in the index. |

## 6.2 Each document shows

| ID | Field | Detail |
| --- | --- | --- |
| `DET-14` | Name | The document's name |
| `DET-15` | Number | The document's exhibit number, if it has been marked as evidence; otherwise its system-generated identifier, such as the application number |

## 6.3 Viewing a document

| ID | Requirement |
| --- | --- |
| `DET-11` | Every document can be viewed as its PDF. A document generated from form data — the complaint filed in e-filing, an application — can also be viewed as **data**: what was entered in the form that produced the PDF. The user can switch between the two. |

**[OWNER]** Why the data view: the user entered data, and the system turned it into a PDF.
Showing the data directly is better than making the reader get it back out of the PDF. This
is the start of a move away from reading cases as PDFs.

## 6.4 Actions on documents

| ID | Requirement |
| --- | --- |
| `DET-12` | Two actions are offered on documents in the case file: **Download**, on the court side and the citizen side, and **Mark as Evidence**, on the court side to holders of the Evidence marker role ([`court-roles.md`](court-roles.md)). Any document can be marked; how marking works is set by [`evidence-marking.md`](evidence-marking.md). |
| `DET-16` | Both actions are on documents only, not on headings. |
| `DET-17` | The user can select several documents and download them, or mark them as evidence, together. |
| `DET-18` | No other action is offered in the case file. Anything else to be done with a document — responding to an application, for example — is done from the user's pending tasks (§5.3) or from the section the document belongs to, such as Applications (§9). |

## 6.5 Downloading the whole case file

| ID | Requirement |
| --- | --- |
| `DET-19` | The whole case file can be downloaded (`ACT-01`) **as individual files**, in one zip file. Each document is downloaded as it is held, so the digital signatures on it stay valid. |
| `DET-20` | It can also be downloaded **as a single PDF**. The system adds index pages, cover pages and other pages between the documents ([`case-file.md`](case-file.md)). The original digital signatures may no longer show as valid in this PDF. A court can choose not to offer this option; the case file is then downloaded only as individual files. |

---

# 7. Notice/Process Status


This section consolidates **every process the court has issued on the case**, grouped by
the person it was issued to. Orders & Notifications (§8) holds the instrument as a record;
this section holds what happened to it — the channels it went out on, whether it reached
the person, and when.

## 7.1 People

| ID | Requirement |
| --- | --- |
| `SVC-01` | Every person a process has been issued to is shown: usually an accused or a witness, and in exceptional cases the complainant. Who a process may be issued to is set by [`process.md`](process.md) §2. |
| `SVC-21` | The section is always available. When no process has been issued on the case, it is shown empty, saying so. |
| `SVC-02` | Processes are grouped by person, one group for each person who has process history. Where the drawer is a company, the company and every person in charge are each a separate recipient ([`process.md`](process.md) `PRC-02`), so each has their own group. |

Each person shows:

| ID | Field | Detail |
| --- | --- | --- |
| `SVC-03` | Name and role | Name and role on the case (e.g. "Accused 2", "PW-1", "Complainant") |

## 7.2 Rounds

| ID | Requirement |
| --- | --- |
| `SVC-04` | A **round** is all the processes triggered by the same order ([`process.md`](process.md) §3). A person may have had **several rounds**. |
| `SVC-19` | Where a round holds more than one process type, its processes are shown in one group per type, each named by the round and the type — for example, "Round 3 — Proclamation" and "Round 3 — Attachment". |
| `SVC-06` | A person's rounds are shown newest first. |

Each round — or, where it is split by type, each group — shows:

| ID | Field | Detail |
| --- | --- | --- |
| `SVC-05` | Process type | The process type of the group (`SVC-19`): **notice**, **summons**, **warrant**, **proclamation**, **attachment** or **custom process** ([`process.md`](process.md) §2) |
| `SVC-07` | Linked hearing | The hearing the processes were issued in relation to, and its date |
| `SVC-08` | Triggering order | The order that triggered the round, and the date it was issued |

## 7.3 Processes

| ID | Requirement |
| --- | --- |
| `SVC-10` | Every process in the round is listed. A process is one process type, to one recipient, on one channel, at one destination ([`process.md`](process.md) §3). For example, a summons sent by RPAD to two addresses and by SMS is three processes, each with its own status. |
| `SVC-15` | The channels are those in [`process.md`](process.md) §6.2, and the statuses those in §10.1. |

Each process shows:

| ID | Field | Detail |
| --- | --- | --- |
| `SVC-22` | Process document | The process itself, as sent: the final PDF ([`process.md`](process.md) `TPL-01`), which can be opened. Available once the process has been signed. |
| `SVC-17` | Channel | The channel it was sent on |
| `SVC-11` | Destination | Where it was sent: a **mobile number**, an **email address**, a **postal address**, or, on a police channel, the **police station** |
| `SVC-12` | Status | Its current status |
| `SVC-13` | Status date | The date the status was last updated |
| `SVC-09` | Process fee | The date the process fee for this process was paid; nothing while it is unpaid. The fee is paid on each process, not on the round ([`process.md`](process.md) §7). |
| `SVC-20` | Reason for non-delivery | Where the process was not delivered or not executed, the reason recorded ([`process.md`](process.md) `DSP-09`) |
| `SVC-14` | Remarks | The comment recorded with the outcome ([`process.md`](process.md) `DSP-08`) |
| `SVC-18` | Supporting file | The supporting file uploaded with the status, such as an acknowledgement card or an execution report, where there is one ([`process.md`](process.md) `DSP-08`) |

---

# 8. Orders & Notifications

This section lists what the court has issued on the case, of every kind (§8.2).

## 8.1 What is shown

| ID | Element | Detail |
| --- | --- | --- |
| `ORD-01` | Kinds | Every kind in §8.2 is returned, each marked with its kind: orders of every type, notifications, and diary entries that are documents of their own. How the screen separates the kinds — a switch, a filter or otherwise — is a UI choice. |
| `ORD-02` | List | Each item shows its date and title and, for an order, its diary text, and can be opened |
| `ORD-03` | Open an order | Opens the order and shows the full PDF |

## 8.2 Kinds

| Kind | What it is |
| --- | --- |
| Order | Passed by the court. Every order type is included ([`order-generation.md`](order-generation.md) `OTY-01`). |
| Notification | A court communication about listings. Today the only notification is the bulk reschedule. |
| Diary entry | Where a state keeps an order's diary entry as a document of its own, signed separately ([`order-generation.md`](order-generation.md) `DEN-06`). Today that is Gujarat's Roznama of a normal order. |

## 8.3 Order statuses

| Value | Label |
| --- | --- |
| `draft-in-progress` | Draft in progress |
| `pending-signature` | Pending signature |
| `published` | Published |

`ORD-04` — a party to the case sees **published** orders. **Court staff also see orders in
draft and pending signature**, and opening one takes them into the work it is waiting for:

| ID | Status | Opening it |
| --- | --- | --- |
| `ORD-05` | Draft in progress | Opens the order for drafting |
| `ORD-06` | Pending signature | Opens the order's PDF for signing |

## 8.4 Order record

An order carries:

| ID | Field | Notes |
| --- | --- | --- |
| `ORD-07` | Title | The order's title |
| `ORD-11` | Type | The order's type, in states that have more than one ([`order-generation.md`](order-generation.md) `OTY-01`) |
| `ORD-08` | Date | When the order was issued |
| `ORD-09` | Diary text | The order's diary entry text ([`order-generation.md`](order-generation.md) §14.1). Absent until the order is passed. |
| `ORD-10` | PDF | The order document itself |

---

# 9. Applications

This section lists the applications on the case that the viewer can see, and lets them
open any one of them. Everything here is an application — one kind, many types. An
application's life — its statuses, who can do what, and its attributes — is set by
[`application-lifecycle.md`](application-lifecycle.md); this section covers only how
applications are shown on the case.

## 9.1 The list

| ID | Requirement |
| --- | --- |
| `APP-21` | Who sees an application follows [`application-lifecycle.md`](application-lifecycle.md): a submitted application is seen by everyone on the case, on both sides, and by court staff (`ALC-17`); a draft only by the person who created it and their associated advocates, clerks and junior advocates (`ALC-27`). |
| `APP-06` | Each application in the list can show any of its attributes ([`application-lifecycle.md`](application-lifecycle.md), "Application attributes"); which ones is a UI choice. For example: its type, application number, status, who raised it, and when it was created and submitted. |
| `APP-22` | The list can be filtered and searched by the applications' attributes — for example, by type, status or who raised it, or by application number. |
| `APP-08` | By default the list is ordered by date created, newest first. |
| `APP-07` | Opening an application shows the signed application and its supporting documents, every order passed on it with the deciding order marked, and any objection raised against it — or, for an objection, the application it answers. It also shows when the application was filed, the objection or where it stands, and the previous order on it ([`application-lifecycle.md`](application-lifecycle.md) `ALC-23`). This is the same for everyone who can see the application. |

## 9.2 Needs attention

An application that has not yet been submitted is waiting on someone on the filer's side:
to finish the draft, to sign it, or to pay for it.

| ID | Requirement |
| --- | --- |
| `APP-05` | Applications in **draft**, **pending signature** or **pending payment** are shown separately, as needing attention. Nothing else is shown there. |

## 9.3 Statuses and attributes

An application's statuses and attributes are those in
[`application-lifecycle.md`](application-lifecycle.md), "Application attributes".

---

# 10. Documents

This section is the place for every document on the case that has no section of its own.
It lists them, from every source below, and lets the user open any one of them.

## 10.1 Sources

| Source | What it is |
| --- | --- |
| Filing | Documents that came in with the case filing ([`efiling.md`](efiling.md)) |
| Application attachments | Documents attached to an application. The applications themselves are in Applications (§9). |
| Submitted directly | Documents submitted through Submit documents ([`document-submission.md`](document-submission.md)) |
| Bail bonds | Bail bonds on the case ([`bail-bond.md`](bail-bond.md)) |
| Recorded statements | Every statement recorded in court, depositions included, and the documents generated from them |
| Vakalatnamas | Vakalatnamas filed on the case ([`join-a-case.md`](join-a-case.md)) |
| Payment receipts | Receipts for payments made on the case ([`payment-logic.md`](payment-logic.md)) |

Documents that have a section of their own are shown there instead: applications (§9),
orders, notifications and diary entries (§8), and processes (§7).

## 10.2 The list

| ID | Requirement |
| --- | --- |
| `DOC-07` | Documents from every source in §10.1 are returned, each marked with its source. How the screen separates them — tabs, a filter or otherwise — is a UI choice. |
| `DOC-05` | Each document in the list can show any of its attributes (§10.3); which ones is a UI choice. |
| `DOC-08` | The list can be filtered and searched by the documents' attributes — for example, by source, type or who submitted it, or by title or exhibit number. |
| `DOC-09` | Documents in draft or pending signature are shown separately, as needing attention ([`document-submission.md`](document-submission.md) `DSB-09`). |
| `DOC-06` | A document can be opened. |

## 10.3 Document attributes

| ID | Attribute | What it holds |
| --- | --- | --- |
| `DOC-10` | Title | The document's name. How it is formed is set by source in [`document-submission.md`](document-submission.md) `DSB-23` for filing, application attachments, documents submitted directly and depositions; for the other sources it is open (Q-12). |
| `DOC-11` | Source | One of the sources in §10.1 |
| `DOC-12` | Type | Affidavit, Memo or Evidence, for documents submitted directly ([`document-submission.md`](document-submission.md) `DSB-01`). Whether documents from other sources have a type is open (Q-13). |
| `DOC-13` | Submitted by | Who put the document on the case. Who it is for a document nobody submits — a generated recorded statement, a payment receipt — is open (Q-14). |
| `DOC-14` | Submitted on | When the document was put on the case |
| `DOC-15` | Number | Every document has a number. It is the exhibit number once the document has been marked as evidence; until then, a unique system identifier, such as a submitted document's provisional ID ([`document-submission.md`](document-submission.md) `DSB-10`). |
| `DOC-16` | File | The document itself |
| `DOC-17` | Status | Draft, Pending signature or Submitted, where the source has statuses ([`document-submission.md`](document-submission.md) §2) |

---

# 11. Parties

This section shows everyone on the case and the details held for each of them. It is the
same for everyone who can see the case. How the people are organised and shown is a UI
choice.

The details shown are always the latest held for each person. The PRDs linked below set
which fields each person has.

## 11.1 People and their details

| ID | Person | Details shown |
| --- | --- | --- |
| `PTY-33` | Complainant — individual | Name, age, gender, phone, email and addresses ([`efiling.md`](efiling.md) §6); their advocates on record, or that they are party in person |
| `PTY-34` | Complainant — institution | Institution type, name, CIN or PAN, contact phone and email, and address ([`efiling.md`](efiling.md) §6); its advocates on record |
| `PTY-35` | Authorised representative of an institution complainant | Name, designation, age, gender, phone, email and address ([`efiling.md`](efiling.md) `LIT-22`–`LIT-26`); the institution they act for. They are not a party. |
| `PTY-36` | Accused — individual | Name, age, phone, email, and addresses each with its police station ([`efiling.md`](efiling.md) §8); their advocates on record, or that they are party in person |
| `PTY-37` | Accused — institution | Institution type, name, phone, email, and addresses each with its police station ([`efiling.md`](efiling.md) §8); its advocates on record |
| `PTY-38` | Person in charge of an institution accused | Name, designation, phone, email, and addresses each with its police station ([`efiling.md`](efiling.md) `ACC-14`–`ACC-23`); the institution, and whether they are its representative. Each is an accused in their own right (§141). |
| `PTY-39` | Power of attorney holder | Name, age, phone, email and addresses ([`efiling.md`](efiling.md) `LIT-11`–`LIT-16`); the litigant they act for. A litigant has at most one. They are not a party. |
| `PTY-40` | Witness | Side (complainant, accused, or neither for a court witness); number, e.g. PW-1; what the witness will prove, where given; name and designation, whichever are held, age, phone, email and addresses ([`efiling.md`](efiling.md) §13, or an Addition of Witness application) |
| `PTY-41` | Advocate on record | Name, bar registration ID ([`account-creation.md`](account-creation.md) `REG-13`), side, and the parties they appear for. Not their address. |
| `PTY-42` | Member of an advocate's office with access to the case | Junior or clerk; a junior's bar registration ID or a clerk's registration number ([`account-creation.md`](account-creation.md) `REG-13`, `REG-13a`); the advocates whose office they are in ([`office-management.md`](office-management.md)) |

| ID | Requirement |
| --- | --- |
| `PTY-28` | Addresses include every address on record for the person, including any added since filing, for example on an order issuing process ([`process.md`](process.md) `PRC-05`). |
| `PTY-24` | Contact details — phone, email and addresses — are shown to everyone who can see the case. Masking them is a later enhancement (§14). |
| `PTY-25` | No documents are shown here. ID cards, vakalatnamas and power of attorney authorisations are in Documents (§10). |
| `PTY-26` | An Aadhaar number is never shown. |

## 11.2 Actions on people (not at launch)

The actions that can be started from this section. Most lead into a flow set elsewhere;
this section only says that the entry point exists, on whom, and for whom.
"Advocate-level access" means an advocate on record or a party in person.

| ID | Action | On whom | Who can start it | Leads to |
| --- | --- | --- | --- | --- |
| `PTY-43` | Edit details | Any litigant | Anyone with advocate-level access. This should be flexible: a court may ask to restrict it to the complainant side. | The Edit Litigant Details application ([`application-lifecycle.md`](application-lifecycle.md)), possibly with a screen for the editing first |
| `PTY-44` | Add an address | An accused, until they join the case; or a witness | The complainant side, with advocate-level access, and court staff | No application: the address is added directly |
| `PTY-45` | Add a witness | — | Anyone with advocate-level access, and the court side | From advocate-level access, the Addition of Witness application ([`application-lifecycle.md`](application-lifecycle.md)). From the court side, the witness is added directly. |
| `PTY-46` | Add an advocate | — | Any litigant, or any advocate on record | The vakalatnama generation flow (not yet defined) |
| `PTY-47` | Add a power of attorney holder | A litigant | Not yet decided ([`application-lifecycle.md`](application-lifecycle.md) `Q-16`) | The PoA Change application, whose details are not yet decided |
| `PTY-48` | Edit details | A witness | Anyone with advocate-level access | An Edit Witness Details application, not yet defined; it will be added when built |
| `PTY-49` | Remove an advocate | An advocate on record | Any other advocate on record | The person removing chooses one of two: an application, which goes to the court; or a request to the advocate being removed to approve it. |
| `PTY-50` | Remove or replace a power of attorney holder | A power of attorney holder | Not yet decided ([`application-lifecycle.md`](application-lifecycle.md) `Q-16`) | An application, not yet defined |
| `PTY-52` | Become party in person | A litigant | The litigant | Not yet known |

---

# 12. Case History

Every update on the case, from the newest back to the first. It is the full version of the
overview's case updates (§5.2), which stop at the last order issued. Updates come from the
[event catalogue](https://docs.superhuman.com/d/PUCAR-Dashboard-2027_dKtL_rwN6Qw/Events_suDoUtbn#Events-Case-Updates_tudKS-s9).

| ID | Requirement |
| --- | --- |
| `TME-01` | Every update on the case is shown, newest first. |
| `TME-04` | Each update shows what it shows in the overview: its date, category, a link to the record it came from, and, for an order, its diary text (`OVW-07`, `OVW-08`, `OVW-09`, `OVW-17`). |
| `TME-05` | Several updates on the same application or process can be shown together as one group, as in the overview (`OVW-18`). Updates within a group are also newest first. |
| `TME-07` | The history can be filtered, for example by category. Filtered to orders, it still lists every order of every type ([`order-generation.md`](order-generation.md) `DEN-08`). |

---

# 13. Open questions

| # | Question | Blocks | Owner |
| --- | --- | --- | --- |
| Q-12 | Document titles (`DOC-10`) — how is the title formed for bail bonds, vakalatnamas, payment receipts, and recorded statements other than depositions? | `DOC-10` | Product |
| Q-13 | Document type (`DOC-12`) — do documents from sources other than Submitted directly have a type, and which? | `DOC-12` | Product |
| Q-14 | Submitted by (`DOC-13`) — what is shown for a document nobody submits, such as a generated recorded statement or a payment receipt? | `DOC-13` | Product |

---

# 14. Enhancements

| Area | Enhancement |
| --- | --- |
| Orders & Notifications (§8) | In a later version, an order can also be viewed with its **order data**: what was filled in with the order ([`order-generation.md`](order-generation.md) §6), not only its PDF. |
| Parties (§11) | In a later version, contact details may be masked for some viewers (`PTY-24`). |

