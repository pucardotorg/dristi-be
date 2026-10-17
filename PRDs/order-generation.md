# Order generation

**Status:** v7 — 2026-09-17; an order dismissing an application at admission identifies it
by kind, filer and filing date, never by the application number; changing a decision on an
application does not rewrite text already written; the attendance roll is a fixed four
rows in this version; the typist's hearing control is disabled until the next hearing has
started and then names it, so it updates live; the order carries a title (§7.1); typing
shortcuts dropped. v6 — 2026-09-17; *Likely at this hearing* is only the configured
hearing association, with no ranking behind it; an order item with no template writes
nothing into the order text; there is no free item — extra text is simply typed; removing
an order item leaves the text it wrote, and deleting that text does not remove the order
item; re-answering an order item's variables does not rewrite the text already in the
order; "order item" used throughout; recital language removed. The combination
restrictions and the workflow trigger order from the old system's Composite Order PRD are
now in [`order-template-catalogue.md`](order-template-catalogue.md), as draft
configuration. v5 — 2026-09-17; the two configuration gaps — what a conditional variable
governs, and an order item for dismissal at admission — are stated as requirements on the
template work rather than as open questions; templates and variables are not treated as
final anywhere in this document.

v4 — 2026-09-17; the hearing control is one button — end this hearing, start the next and
go to it for the magistrate and the bench clerk, go to the next for the typist — and the
difference between users is which action they are given first, not what they are allowed
to do. Only signing is restricted.

v3 — 2026-09-17; no user restriction on the admission stage of an application — any of the
three may take one on file or dismiss it, and a dismissal has to come with an order.

v2 — 2026-09-17; no Business of the Day line — the order's own text is the record and
becomes the A-Diary entry; an edit that changes an operative value in the text stands
against the drafter; a next date held provisionally from the moment it is set and announced
on signature; dismissal at admission designed as an order; the application's CMP number
assigned only on being taken on file; a signed order corrected only by a fresh order with
no link recorded; several draft orders allowed on a case; court users sign with Aadhaar
e-sign or DSC.

v1 — 2026-09-17; first draft.

Scope is the generation of a single order — drafting it, signing it, publishing it. Order
types, templates, variables, categories and hearing associations are not specified here;
they are configuration owned by
[`order-template-catalogue.md`](order-template-catalogue.md). The workflows individual
orders trigger are each specified separately.

Sources: the order composer prototype in `Pucar-Dristi-2.0` (branch
`feature-courtside-dashboard`, route `/employee/hearings/[hearingId]/order`, built in
`apps/dristi-app/src/components/employee/order-screen.tsx`), the order template catalogue,
and the old system's Composite Order PRD (`Composite Order.pdf`) for the combination
restrictions and the workflow trigger order.

---

## 1. Context

An order is the court's decision, recorded in writing and signed by the magistrate. This
document specifies the one screen on which an order is drafted, previewed, signed and
published.

Everything on this screen depends on configuration being in place: the order items the
court has, the template text and variables held against each, the category each sits in,
the hearing purposes each is associated with, the workflow each triggers, which of them
cannot stand in the same order, and the sequence their workflows run in. That
configuration — system default or set up by the court — is owned by
[`order-template-catalogue.md`](order-template-catalogue.md), and nothing in this document
restates it.

**The templates and variables are not final.** The catalogue is still being worked on, so
nothing here depends on what it happens to hold today. Where this screen needs something
the configuration does not yet carry, it is written below as a requirement **on the
configuration** — something the template work has to supply — and not as an open question
about the screen.

What is out of scope, and where it belongs:

| Out of scope | Owner |
|---|---|
| The order items themselves — templates, variables, categories, hearing associations, combination restrictions, workflow trigger order | [`order-template-catalogue.md`](order-template-catalogue.md) |
| What each order's workflow does once triggered | A document per workflow; process orders are in [`process-handover.md`](process-handover.md) |
| Conduct of the hearing itself — calling, passing over, the cause list | Hearing documents; scheduling rules in `scheduling/` |
| Case stages the order moves | [`case-lifecycle-handover.md`](case-lifecycle-handover.md) |
| Order and application number formats | [`case-numbers.md`](case-numbers.md) |
| Pending task attributes and visibility | [`pending-tasks-handover.md`](pending-tasks-handover.md) |
| The judgement, which has its own screen | Not yet written |

| ID | Requirement |
|---|---|
| `ORD-01` | The screen produces **one order**. An order carries one or more **order items**, each one taken from the configured catalogue. |
| `ORD-02` | Each order item may trigger its own workflow. Several order items in one order trigger several workflows. |
| `ORD-03` | An order item is the unit that carries template text, variables and a workflow. The order is the unit that is numbered, signed and published. |
| `ORD-04` | An order may also carry text the drafter writes that belongs to no order item — anything extra is simply typed into the order text. An order may consist only of such text. |

---

## 2. Where the screen is used

The same screen serves two situations.

| ID | Requirement |
|---|---|
| `ORD-05` | **In a hearing.** The screen is opened on a listing the court has called, from the day's cause list. The order it produces belongs to that hearing. |
| `ORD-06` | **Outside a hearing.** The screen is opened from the case (*New order*), or from a pending task, which opens it with its context already filled — the application to be decided, the rescheduling request, the process to be renewed. |
| `ORD-07` | An order raised outside a hearing belongs to the case and names no hearing. |
| `ORD-08` | The two situations use the same screen. Outside a hearing, the **Attendance** and **Next hearing** regions are absent, and with them the hearing controls of §10. |
| `ORD-09` | Which order items are available follows from the situation. *Scheduling of hearing date* is offered outside a hearing and not inside one, where the next date is set in the Next hearing region instead (`NXT-03`). |
| `ORD-10` | A case may carry any number of orders over its life. |

The prototype implements the in-hearing case only. The outside-a-hearing variant is
specified here and has not been built.

---

## 3. Users

Three users work this screen: the **magistrate**, the **typist** and the **bench clerk**.

| ID | Requirement |
|---|---|
| `ROL-01` | All three may draft: add and remove order items, answer variables, write and edit the order text, mark attendance, set the next hearing, and add the order to the signing list. |
| `ROL-02` | **Only the magistrate signs.** Enforced server-side, not by hiding the control. |
| `ROL-03` | Deciding an application — allow or reject — is an order item and may be **drafted** by any of the three. It takes effect on the magistrate's signature. |
| `ROL-04` | Taking an application on file, and dismissing one that is not yet on file, may be done by **any of the three**. Taking on file is a system action and takes effect at once; a dismissal has to come with an order, so it takes effect on the magistrate's signature like any other order (§8). |
| `ROL-05` | The hearing control is **one button**, and what it does differs by user. For the magistrate and the bench clerk it ends this hearing, starts the next listing and takes them to it. For the typist it takes them to the next listing and neither ends nor starts anything (`NXT-05`). |
| `ROL-06` | That difference is one of **primary action, not permission**. Apart from signing (`ROL-02`), nothing on this screen is hard-restricted by user: each may reach what another is offered. What differs is which action each is given first. |

What each user may do:

| | Magistrate | Typist | Bench clerk |
|---|---|---|---|
| Draft the order — order items, variables, text | ● | ● | ● |
| Mark attendance, set the next hearing | ● | ● | ● |
| Draft allow / reject of an application | ● | ● | ● |
| Take an application on file, or dismiss it at that stage | ● | ● | ● |
| Preview | ● | ● | ● |
| Add to signing list | ● | ● | ● |
| Move an order back to draft from the signing list | ● | ● | ● |
| Sign | ● | | |

The hearing control is the one place the screen differs by user, and it differs in what the
button does rather than in what anyone is allowed to do:

| | Magistrate | Typist | Bench clerk |
|---|---|---|---|
| The hearing control | End this hearing and start the next | Go to the hearing now under way — disabled until one is | End this hearing and start the next |

---

## 4. The screen

```
┌────────────────────────────────────────────────────────────────────────┐
│ Order: Complainant v Accused             [End and start next hearing] │
│ Listing: 4 · Case: ST/241/2026 · Stage: Evidence · Purpose: Evidence   │
├───────────────────────────┬────────────────────────────────────────────┤
│ Applications        2 ▾   │  ORDER                                     │
│   Yet to be taken on file │  ┌──────────────┐ ┌───────────────────┐    │
│     CMP application       │  │ ATTENDANCE   │ │ NEXT HEARING      │    │
│     [Take on file] [Dis…] │  │ Complainant  │ │ ☑ List it again   │    │
│   On file, to be decided  │  │  ◉Present ○Ab│ │ Purpose  [▾]      │    │
│     CMP/312/2026 — Bail   │  │ Accused      │ │ Date     [▾]      │    │
│     [Allow] [Reject] View │  │  ○Present ◉Ab│ │                   │    │
│                           │  └──────────────┘ └───────────────────┘    │
│ Order items         3 ▾   │  ──────────────────────────────────────    │
│   [Search the catalogue]  │                                            │
│   Likely at this hearing  │  Present: …  Absent: …                     │
│     Witness batta         │                                            │
│     Issue of summons      │  The application of the accused for bail   │
│   Categories              │  (CMP/312/2026) is allowed.                │
│     Process orders     6  │                                            │
│     Case management    5  │  Issue summons to the witness Ramesh K…    │
│     …                     │                                            │
│   In this order            │  Next hearing: 6 October 2026             │
│     1. Bail — allowed  🗑  │  Purpose: Evidence of the complainant     │
│     2. Issue of summons 🗑 │                                            │
├───────────────────────────┴────────────────────────────────────────────┤
│                        [Preview]  [Sign now]  [Add to signing list]    │
└────────────────────────────────────────────────────────────────────────┘
```

Left: the work of the hearing — the applications standing on the matter, and the catalogue
the order items are chosen from. Right: the order itself, as the document it will be. The header
names the matter; the footer carries the actions.

| ID | Requirement |
|---|---|
| `ORD-11` | The header states which matter this is: cause title, case number, case stage, and — in a hearing — the listing's serial number on the day's board and what the matter was listed for. |
| `ORD-12` | The order is shown as the document it will print, not as a form that describes one. The court's own furniture — court name, cause title, case number, date, signature block — is rendered from the record and is never typed. |
| `ORD-13` | Attendance and the next hearing are answered as controls on the document, and what is answered there is written into the order text (§9, §10). |
| `ORD-14` | Every region stays visible and correctable for as long as the order is a draft. |

---

## 5. Order items

| ID | Requirement |
|---|---|
| `ITM-01` | Order items are chosen from the configured catalogue. Three ways in: what is likely at this hearing, a search across every order item, and the categories, browsable as lists. |
| `ITM-02` | **Likely at this hearing** lists the order items that configuration associates with what this hearing was listed for. That is all it is — a shortcut to part of the same catalogue. Every other order item stays reachable through the search and the categories. |
| `ITM-03` | An order item the case cannot take is **listed with the reason**, not hidden and not offered. The reason is the configured availability rule: only before cognizance, only once the case is on file, only for a long-pending case, comes from an application. |
| `ITM-04` | Contextual order items — the accept and reject ones — are never browsable. They arrive from the thing that produces them: an application being decided, or a pending task that opened the screen. |
| `ITM-05` | An order item with no template configured **writes nothing into the order text**. Whatever fields it carries are still asked for, and the drafter writes the text themselves. |
| `ITM-06` | An order may carry several order items, including more than one of the same order item — two summonses to two witnesses are two order items. |
| `ITM-07` | Configuration holds which order items cannot stand in the same order, and which cannot be repeated in one — the *Combination restrictions* section of [`order-template-catalogue.md`](order-template-catalogue.md). The screen refuses the addition and shows the configured message. |
| `ITM-08` | Order items are listed in the sequence they were added, numbered. That sequence is what decides the order their workflows are triggered in (`PUB-03`). |
| `ITM-09` | An order item may be removed until the order is signed. Removing it takes the order item and its workflow out of the order. **The text it wrote stays in the order text**: the drafter has usually edited that text by then, and the system cannot say with certainty which words are still the order item's. The screen says so on removal, and the drafter deletes the text themselves. |
| `ITM-10` | The reverse also holds. Deleting the words an order item wrote does **not** remove the order item, and nothing about the order is inferred from the text having been edited. |
| `ITM-11` | An order item may need input beyond its template variables, where the workflow it triggers needs it — the delivery channels per addressee for a process order (`PRC-03` of [`process-handover.md`](process-handover.md)). That input is asked for on this screen as part of the order item; its fields are owned by the workflow's own document. |

---

## 6. Variables

Configuration holds each type's template text and the variables in it, marked locked or
optional. This section specifies how those variables are resolved when an order item is added.

| ID | Requirement |
|---|---|
| `VAR-01` | Resolution runs in this order: load the template for the chosen type → fill what the system knows → collect what is left as fields → compose the sentence → insert it into the order. |
| `VAR-02` | **The system fills single-valued facts.** Court name, cause title, case number, current date, judge name and designation, complainant name, accused name, the date of this hearing. The drafter never types these. |
| `VAR-03` | **The system fills values it has already collected.** The application number and type when the order item was reached from that application; the next hearing's date and purpose when they have been set on this screen; values a workflow collected when the screen was opened from that workflow's task. |
| `VAR-04` | **The system never guesses a choice.** A party reference fills automatically only where the case holds exactly one candidate of that kind; with more than one, the drafter chooses. An application number is filled only where the order item was reached from that application — never by taking the only application standing on the matter. |
| `VAR-05` | Everything left is collected as a field **before** the sentence is inserted, typed to the variable: a party selector, a date picker, an amount in rupees, a dropdown from master data, or free text. |
| `VAR-06` | **Locked variables are mandatory.** An order item cannot be inserted with a locked variable unanswered, because the workflow behind it cannot run without one. |
| `VAR-07` | An optional variable may be left unanswered. Where configuration marks a variable **conditional**, the sentence or clause that depends on it is not inserted at all when it is unanswered — see §6.1. |
| `VAR-08` | A collected value is stored on the order item as data, not only as words in the text. The **stored value drives the workflow**; the text is the record read by people. |
| `VAR-09` | Where the drafter edits the text so that it no longer matches the stored value, the divergence stands: the workflow acts on the stored value and the order reads as written. The system does not warn and does not block. That is the drafter's responsibility. |
| `VAR-10` | An order item's variables can be reopened and re-answered until the order is signed. **The text already in the order is not rewritten.** The screen says so when the variables are reopened: it writes the corrected sentence into the order, and the drafter deletes the old one. Where a later version can tell with certainty which words the order item wrote and that they are unedited, it may remove them itself. |
| `VAR-11` | No bracketed token ever reaches a signed order. Because variables are asked for as fields, the text an order item writes is complete; anything the drafter types by hand is their own text. |

### 6.1 Conditional variables

Some templates carry a clause that only applies sometimes. *Mandatory submissions and
responses* is the example in the catalogue today:

> It is directed that the [Party Type] files a [Document Type] for [Document Name] before
> the court by [Deadline for Submission]. **Additionally, the [Party Type] must submit a
> response by [Deadline for Response].**

`[Deadline for Response]` is marked *conditional*: the court often directs a submission
with no response at all. So the second sentence is not always wanted, and the drafter
cannot be made to answer a deadline for a response nobody has to file.

| ID | Requirement |
|---|---|
| `VAR-12` | A conditional variable is offered as a field the drafter may skip. |
| `VAR-13` | Skipping it drops the sentence or clause that depends on it. The order does not print a sentence with a gap in it, and the drafter is not left correcting the wording by hand. |
| `VAR-14` | **On the configuration:** each conditional variable has to carry which sentence or clause depends on it, so that `VAR-13` has something to drop. Today's catalogue marks a variable conditional without saying what the condition governs. That belongs to the template work. |

---

## 7. The order text

| ID | Requirement |
|---|---|
| `TXT-01` | The order is **one body of text**, not a box per order item. An order item's sentence is added to the end of that body and from then on is text the drafter shapes — joined, split, renumbered, reworded. |
| `TXT-02` | The body is editable from the moment the screen opens, whether or not any order item has been added. |
| `TXT-03` | The editor supports paragraphs, numbered and lettered lists, and emphasis. An order often carries numbered directions, so the editor has to be able to write them. |
| `TXT-04` | **The body of the order is the record.** There is no separate short line and no second wording of the same order: what the body says is what goes into the A-Diary, what the parties see, and what is shown wherever the order appears (`PUB-04`). An order item's template sentence is a starting point for that text, not a parallel record of it. |
| `TXT-05` | What is answered in the **Attendance** and **Next hearing** controls is written into the order text as lines of the order: who was present and who was absent, the next date and what it is for. Changing an answer rewrites that line where the line still reads as the system wrote it. Where the drafter has reworded it, the same limit as `VAR-10` applies — the system writes the corrected line and the drafter removes the old one. |


### 7.1 The order's title

An order carrying several order items needs a name, because a register or a list cannot
show an order by its order item when it has three. This follows the old system.

| ID | Requirement |
|---|---|
| `TIT-01` | Every order carries a **title**. |
| `TIT-02` | An order with one order item takes that order item's name as its title, and the title is not editable. |
| `TIT-03` | When a second order item is added, the title becomes the first order item's name followed by *and other items*, and becomes **editable**. |
| `TIT-04` | From that point the system never changes the title again. Changing which order item is first, or removing one, leaves the title as it stands; the drafter edits it if it is now wrong. |
| `TIT-05` | The title can be edited while the order is a draft. Once the order is signed it is fixed. |
| `TIT-06` | Wherever orders are listed, the list shows the **title**. It does not show the order item alongside it: for an order with one order item the two are the same, and for an order with several the title is the more useful of the two. |

---

## 8. Applications standing on the matter

An application reaches the court, and it is disposed of in two stages, usually at two
different hearings. Both stages are worked from this screen, and only the second is an
order.

```
Application filed ──▶ carries an application number, no CMP number yet
      │
      ▼
Yet to be taken on file ──── any of the three may act
      │
      ├── taken on file ──▶ CMP number assigned. A system action,
      │         │            not an order, writes nothing
      │         │
      │         ▼  (typically a later hearing)
      │   Allowed / rejected ──── an order item; drafted by any user,
      │                           signed by the magistrate
      │
      └── dismissed at admission ──── an order item; drafted by any user,
                                      signed by the magistrate
```

| ID | Requirement |
|---|---|
| `APL-01` | The screen lists the applications standing on the matter, grouped by which stage each is at, with the action each stage offers. |
| `APL-02` | **Taking on file** assigns the application its own CMP number, independent of the case number. It is a system action, not an order: nothing is written into the order text, no signature is involved, and it takes effect at once. Any of the three may do it. |
| `APL-03` | The CMP number is assigned **only on being taken on file**, not at filing. Until then the application is referred to by its application number. Both number formats are owned by [`case-numbers.md`](case-numbers.md), whose row 7 records the current system assigning the CMP number at filing; this decision supersedes that behaviour. |
| `APL-04` | **Dismissing an application at admission** — before it is taken on file — is an **order item**. It disposes of the application, so it must come with an order: it is written into the order text and takes effect on the magistrate's signature. Any of the three may draft it. |
| `APL-05` | An order dismissing an application at admission **does not cite the application number**. That number is internal and is not something a court recognises as identifying an application. It identifies the application by **what kind of application it is, who raised it, and when it was filed**. |
| `APL-06` | **On the configuration:** an order item is needed for dismissal at admission, worded to identify the application by its kind, its filer and its filing date (`APL-05`). The existing *Reject application* cites a CMP number the application does not yet have, so it cannot serve. Part of the template work. |
| `APL-07` | **Once on file**, an application is allowed or rejected. This is an order item, uses the configured accept / reject order item, and is written into the order text. Any of the three may draft it. |
| `APL-08` | Any workflow that follows belongs to the **application type**, not to the accept/reject order, and is triggered on signature like any other order item's workflow. |
| `APL-09` | Acceptance of bail is its own order item because it optionally triggers the bail bond workflow; it is not the generic accept. |
| `APL-10` | A decision may be changed until the order is signed. As with `VAR-10` and `ITM-09`, **the text already in the order is not rewritten**: the sentence for the new decision is written in, the screen says so, and the drafter removes the sentence the earlier decision wrote. |
| `APL-11` | The drafter can open and read the application itself — the paper, its filer, its date, what it asks for — without leaving the screen. |
| `APL-12` | An application left undecided does not block the order, and the order says nothing about it. The screen states what is still standing. |

---

## 9. Attendance — in a hearing only

| ID | Requirement |
|---|---|
| `ATT-01` | The roll is a **fixed list of four** in this version: the complainant, the complainant's advocate, the accused, and the accused's advocate. Nothing is checked or varied — not whether a side actually has an advocate, not a party appearing in person, not a PoA holder, not several complainants or several accused. Those cases are for a later version. |
| `ATT-02` | One mark per person — present or absent. A person may be left unmarked, and a mark may be cleared: no answer for a person is a real state, and an uncorrectable one is not. |
| `ATT-03` | What is marked is written into the order text as a **Present** line and an **Absent** line, naming each person and the office they appear in. A side with nobody marked prints no line. |
| `ATT-04` | A roll that is only part-marked writes in whoever has been marked so far, and takes on the rest as they are answered. |
| `ATT-05` | An incomplete roll does not block the order. The order records what was answered. |

---

## 10. Next hearing and hearing control — in a hearing only

| ID | Requirement |
|---|---|
| `NXT-01` | The order carries where the matter is posted to: a date and a purpose, or an explicit decision not to list it again. |
| `NXT-02` | Both facts are needed. A date without a purpose, or a purpose without a date, is half an answer and is not written into the order. |
| `NXT-03` | In a hearing this is the only place the next date is set; the *Scheduling of hearing date* order item is not offered (`ORD-09`). Outside a hearing that order item is how a date is set. |
| `NXT-04` | The screen carries **one hearing control**. For the magistrate and the bench clerk one press does three things: it marks this listing heard, calls the next unheard listing on the day's board in serial order, and opens its order screen. |
| `NXT-05` | For the typist the same control only takes them to the hearing that is now under way; it ends nothing and starts nothing. It is **disabled until the next hearing has actually been started** by the magistrate or the bench clerk, and it **names the hearing it will take them to** — its number on the day's board — once that hearing is under way. |
| `NXT-06` | `NXT-05` means the control changes without the typist doing anything: it is another user's action that enables it and gives it its number. The screen keeps it current while it is open, rather than waiting for a reload. |
| `NXT-07` | Ending a hearing does not require the order to be complete or signed. The draft stays on the listing and can be returned to. |
| `NXT-08` | Where there is no next listing, the control ends this hearing and returns to the day's board — and for the typist, returns to the board only. |
| `NXT-09` | Whether the date offered is constrained — court calendar, holidays, the judge's availability, slot purpose — is owned by [`scheduling-product.md`](../scheduling/scheduling-product.md). |

### 10.1 Dates held before the order is signed

The next date is **announced on signature** (`PUB-07`): until the magistrate signs, nothing
is listed and no party is told. But a court sets these dates one matter at a time through the
day, and the orders are often signed at the end of it. If the bench has already set the
same date for fifty matters, the fifty-first must not be picked in ignorance of them.

| ID | Requirement |
|---|---|
| `NXT-10` | A date set in a draft order creates a **provisional listing** on that date from the moment it is set. Provisional, not scheduled: no cause list entry, no notification, nothing final. |
| `NXT-11` | Everything that reads a day's load counts provisional listings alongside confirmed ones — the date picker on this screen first of all, so the bench setting the fifty-first sees the fifty it has just set. |
| `NXT-12` | A provisional listing is distinguishable from a confirmed one wherever a day's load is shown, because it may still evaporate. |
| `NXT-13` | Changing the date in the draft moves the provisional listing. Discarding the draft, or removing the next date from it, releases it. |
| `NXT-14` | A provisional listing becomes the scheduled hearing on signature. |
| `NXT-15` | A provisional listing that is never signed does not expire on its own; it lives and dies with the draft that holds it. How long an unsigned draft may hold a date is `Q-1`. |

---

## 11. The draft

| ID | Requirement |
|---|---|
| `DFT-01` | **One draft order per hearing**, shared by all three users. The magistrate opening the screen sees what the typist has typed, and the typist sees what the magistrate changed. |
| `DFT-02` | Concurrent editing is not locked. The last write stands. |
| `DFT-03` | Outside a hearing, a draft belongs to the case. **Several draft orders may stand open on one case at the same time**, each its own draft. |
| `DFT-04` | A draft is saved and survives a reload, a sign-out and a change of device. It is not held in the browser. |
| `DFT-05` | Drafts in progress are listed where the court picks up work — on the case, and in the court-side list of orders drawn up but not signed. How a pending task relates to a draft order — whether the task closes when the draft is created or only when the order is signed, and whether it comes back if the draft is deleted — is owned by [`pending-tasks-handover.md`](pending-tasks-handover.md), where the old system's PRD leaves two options open. |
| `DFT-06` | A draft may be discarded by any of the three. Discarding removes it; it issues nothing and records nothing on the case. |
| `DFT-07` | **A draft is not an order.** Nothing is numbered, published, notified or triggered from a draft, and no workflow starts. |

---

## 12. Preview

| ID | Requirement |
|---|---|
| `PRV-01` | Every user can preview the order as it will print, as a PDF, from the composer and from the signing list. |
| `PRV-02` | The preview is the same rendering the signed PDF uses. The composer and the preview must not disagree about what the document says. |
| `PRV-03` | An unsigned order previews as unsigned, and says so where the signature will be. |
| `PRV-04` | The magistrate's **Sign now** is offered in the preview as well as on the composer. |

---

## 13. Signing

| ID | Requirement |
|---|---|
| `SGN-01` | The primary action, for all three including the magistrate, is **Add to signing list**. |
| `SGN-02` | The magistrate has a secondary **Sign now**, on the composer footer and in the preview. It signs that order there and then. |
| `SGN-03` | Only the magistrate may sign, from either route. Enforced server-side. |
| `SGN-04` | An order cannot be added to the signing list while it carries no text, or while any order item has a locked variable or a required workflow input unanswered. |
| `SGN-05` | An order on the signing list is **not editable**. Any of the three may move it back to draft, edit it, and add it back. |
| `SGN-06` | Several orders may be signed in one action from the signing list. |
| `SGN-07` | Court-side users may sign with **Aadhaar-based e-sign** or with a **DSC**. Both are offered; the user chooses. |
| `SGN-08` | `SGN-06` and `SGN-07` interact. A DSC signs any number of documents in one action. Aadhaar e-sign through C-DAC accepts **one document per authentication**, so signing ten orders is ten OTPs unless the batch approach in [`batch-esign-proposal.md`](../signing/batch-esign-proposal.md) is used — which puts the court's seal, not the magistrate's Aadhaar signature, on each order. See `Q-2`. |

---

## 14. On signature — what the order becomes

| ID | Requirement |
|---|---|
| `PUB-01` | Signature is what makes it an order of the court. The order is numbered, dated and stored as a signed PDF. The number format is owned by [`case-numbers.md`](case-numbers.md). |
| `PUB-02` | The signed order joins the case record and becomes visible to the parties on the case. |
| `PUB-03` | **Each order item's workflow is triggered on signature, and never before.** An order carrying three order items triggers three workflows, each reading the values stored against its own order item (`VAR-08`). The sequence they are triggered in is configuration — the *Workflow trigger order* section of [`order-template-catalogue.md`](order-template-catalogue.md) — because a hearing-date change has to land before the workflows that use the new date, and a case-closing order after everything else. |
| `PUB-04` | The order's text becomes the case's **A-Diary entry** for the date of the hearing, unchanged and in full (`TXT-04`). The same text is what the parties see on the case and what any other screen showing this order shows. The A-Diary register itself, and its own signing, are not owned by this document — see `Q-3`. |
| `PUB-05` | Case stage changes are not workflows. A listener reads order events and moves the stage; stage rules are owned by [`case-lifecycle-handover.md`](case-lifecycle-handover.md). |
| `PUB-06` | A signed order cannot be edited or withdrawn. The court may pass a later order correcting it; the system records **no link** between the two, and neither order is marked as superseding or superseded. |
| `PUB-07` | The next hearing set in the order is **announced on signature** and becomes the scheduled hearing then. Before signature it is held provisionally (§10.1). |

---

## 15. Open questions

| # | Question | Blocking? |
|---|---|---|
| `Q-1` | `NXT-15`: an unsigned draft holds its date provisionally with nothing forcing it to be released. Does a draft expire, or is a stale-draft list enough? | No |
| `Q-2` | `SGN-08`: signing several orders at once with Aadhaar e-sign is one authentication per order. Do court users accept that, use a DSC for bulk signing, or is the batch-certificate approach wanted here too? | No |
| `Q-3` | `PUB-04`: the order's text becomes the A-Diary entry. Which document owns the A-Diary register and its own signing? The prototype has a *Sign A-Diary* screen; no handover specifies it. | No |
| `Q-4` | `ATT-01`: the *People required* column of the hearing-purpose table in [`order-template-catalogue.md`](order-template-catalogue.md) names who should attend each purpose. Should the attendance roll use it — pre-select those people, or warn when one of them is unmarked or absent — or is the roll simply everyone on the case? | No |
