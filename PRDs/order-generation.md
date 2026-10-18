# Order generation

**Status:** v8 — 2026-10-18; rewritten to order screen E and the Pending orders flow. An
order is now **order text** and **order data**, worked separately: order items, decisions,
attendance and the next hearing are order data and never write into the text (§1, §5,
§6). Shortcuts (`/` + name + Tab) are back (§5.1). Drafting ends with **Send for
signing**; signing happens in **Pending orders** (§11, §12). Workflows are triggered only
when the order is signed **and** its order data is marked complete, in either order
(§13); the next hearing is announced then. Where attendance and the next hearing are
entered, and whether the next hearing is entered on the cause list, are court settings
(§9). Users are replaced by **roles** from [`court-roles.md`](court-roles.md) (§3).
Preview, *Sign now* and the signing list are gone: the page is the document.

v7 — 2026-09-17; an order dismissing an application at admission identifies it
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

Scope is the generation of a single order — typing it, filling its order data, signing
it, and triggering what it sets moving. Order types, templates, variables, categories and
hearing associations are not specified here; they are configuration owned by
[`order-template-catalogue.md`](order-template-catalogue.md). The workflows individual
orders trigger are each specified separately. Who may do what is stated in roles, owned
by [`court-roles.md`](court-roles.md).

Sources: order screen E ("Full-page editor") and the Pending orders flow in
`Pucar-Dristi-2.0` (`main`; `apps/dristi-app/src/components/employee/order-editor.tsx`,
`pending-order-screen.tsx`, `pending-orders-screen.tsx`,
`src/lib/employee/pending-orders.ts`), the order template catalogue, and the old system's
Composite Order PRD (`Composite Order.pdf`) for the combination restrictions and the
workflow trigger order.

---

## 1. Context

An order is the court's decision, recorded in writing and signed. It has two parts, and
they are worked separately:

- **The order text** — the words of the order, typed as a document. This is the record:
  what is signed, what the parties read, what goes into the A-Diary.
- **The order data** — what the order sets moving: its order items and their values, the
  decision on each application, attendance and the next hearing. This drives the
  workflows. Nothing in the order data is written into the order text.

The two are typed and filled by people holding different roles, at different times. An
order's workflows go out only once **both** the order is signed **and** its order data is
marked complete (§13).

Everything on this screen depends on configuration being in place: the order items the
court has, the fields each asks for, the category each sits in, the hearing purposes each
is associated with, the workflow each triggers, which of them cannot stand in the same
order, and the sequence their workflows run in. That configuration — system default or
set up by the court — is owned by
[`order-template-catalogue.md`](order-template-catalogue.md), and nothing in this document
restates it.

**The templates and variables are not final.** The catalogue is still being worked on, so
nothing here depends on what it happens to hold today. Where this screen needs something
the configuration does not yet carry, it is written below as a requirement **on the
configuration**.

What is out of scope, and where it belongs:

| Out of scope | Owner |
|---|---|
| The order items themselves — templates, variables, categories, hearing associations, combination restrictions, workflow trigger order | [`order-template-catalogue.md`](order-template-catalogue.md) |
| What each order's workflow does once triggered | A document per workflow; process orders are in [`process-handover.md`](process-handover.md) |
| Which roles exist and what each allows | [`court-roles.md`](court-roles.md) |
| Taking an application on file, and the application's own lifecycle | [`application-lifecycle.md`](application-lifecycle.md) |
| Conduct of the hearing itself — calling, passing over, the cause list | Hearing documents; scheduling rules in `scheduling/` |
| Case stages the order moves | [`case-lifecycle-handover.md`](case-lifecycle-handover.md) |
| Order and application number formats | [`case-numbers.md`](case-numbers.md) |
| Pending task attributes and visibility | [`pending-tasks-handover.md`](pending-tasks-handover.md) |
| The judgement, which has its own screen | Not yet written |

| ID | Requirement |
|---|---|
| `ORD-01` | The screen produces **one order**. An order carries order text and order data. Its order data carries zero or more **order items**, each taken from the configured catalogue. |
| `ORD-02` | Each order item may trigger its own workflow. Several order items in one order trigger several workflows. |
| `ORD-03` | An order item is the unit that carries fields and a workflow. The order is the unit that is numbered, signed and published. |
| `ORD-04` | An order may consist of text alone, with no order items. |

---

## 2. Where the screen is used

The same screen serves every order, whatever opened it.

| ID | Requirement |
|---|---|
| `ORD-05` | **In a hearing.** The screen is opened on a listing the court has called, from the day's cause list. The order it produces belongs to that hearing. |
| `ORD-06` | **Outside a hearing.** The screen is opened from the case (*New order*), or from the work that calls for an order — taking cognizance, deciding an application, dismissing an application at admission, a pending task. It opens with that context already in its order data: the application to be decided, the act being ordered. |
| `ORD-07` | An order raised outside a hearing belongs to the case and names no hearing. |
| `ORD-08` | Outside a hearing, **attendance** and the **hearing control** (§10) are absent. The next hearing is still asked for. |
| `ORD-09` | Which order items are available follows from the situation. *Scheduling of hearing date* is offered outside a hearing and not inside one, where the next date is set as the next hearing instead (`NXT-03`). |
| `ORD-10` | A case may carry any number of orders over its life. |
| `ORD-10a` | An order item loaded by the work that opened the screen — the decision on the application it was opened from, the cognizance act — **cannot be removed** from that order. |

---

## 3. Roles

This screen uses six roles from [`court-roles.md`](court-roles.md). A person may hold any
number of them, and sees the controls for every role they hold.

| ID | Role | What it does on this screen and in Pending orders |
|---|---|---|
| `ROL-01` | **Order drafter** | Types and edits the order text; manages their shortcuts; sends the order for signing; moves it back to draft before it is signed; discards a draft. |
| `ROL-02` | **Order data filler** | Adds, edits and removes order items and their fields; decides applications; marks attendance; marks the order data complete and reopens it before signing; adds order items to several orders at once. |
| `ROL-03` | **Next hearing setter** | Sets the next hearing's date and purpose, or records that the matter is not listed again, wherever the court enters it (§9). |
| `ROL-04` | **Order signer** | Signs orders, one at a time or several at once. |
| `ROL-05` | **Hearing controller** | Ends the hearing under way and calls the next listing (§10). |
| `ROL-06` | All of these are **enforced server-side**, not by hiding the control. A person without a role sees what that role would change, read only. |

---

## 4. The screen

```
┌────────────────────────────────────────────────────────────────────────────┐
│ Complainant v Accused                         [Side panel] [Next case ›]   │
│ Item 4 · Case ST/241/2026 · Stage Evidence · Purpose Evidence              │
├──────────────────────────────────────────┬─────────────────────────────────┤
│ [ Order | Order data ]   Type / for a     │ Case file · Overview ·          │
│                          shortcut  [Shortcuts]  History · Hearings        │
│ ┌──────────────────────────────────────┐ │                                 │
│ │ B I • 1.  ⊞                          │ │ [Search the case file]          │
│ │      Before the JMFC Court 1         │ │ Applications                    │
│ │  ST/241/2026 · A v B · 6 Oct 2026    │ │   Bail — by the accused   Link  │
│ │ ──────────────────────────────────── │ │ 1 Complaint                     │
│ │  ATTENDANCE  Complainant ◉P ○A …     │ │ 2 Vakalatnama                   │
│ │                                      │ │ …                               │
│ │  Heard. The accused is present and   │ │                                 │
│ │  is enlarged on bail on executing a  │ │                                 │
│ │  bond for ₹50,000 …                  │ │                                 │
│ │ ──────────────────────────────────── │ │                                 │
│ │  NEXT HEARING  Purpose [▾] Date [▾]  │ │                                 │
│ │                       Magistrate     │ │                                 │
│ │                       Not signed     │ │                                 │
│ └──────────────────────────────────────┘ │                                 │
├──────────────────────────────────────────┴─────────────────────────────────┤
│                                       Saved          [Send for signing]   │
└────────────────────────────────────────────────────────────────────────────┘
```

| ID | Requirement |
|---|---|
| `ORD-11` | The header states which matter this is: cause title, case number, case stage, and — in a hearing — the listing's item number on the day's board and what the matter was listed for. It carries the side panel's switch and, in a hearing, the hearing control (§10). |
| `ORD-12` | The screen has two views, switched above the page: **Order** and **Order data**. |
| `ORD-13` | **Order** shows the order as one page, as it will print: the court's heading at the top, the signature block at the foot, and the order text between them. The heading and signature block are rendered from the record and are never typed. The page is the same rendering the signed PDF uses; the two never disagree about what the document says. |
| `ORD-14` | An unsigned order's signature block says where it stands: *Not signed*, *Sent for signing*, or *Signed*. |
| `ORD-15` | Beside the page, in the Order view, a **side panel** carries the case: the case file's own index, searchable, with the applications standing on the matter first; the case overview; the case history; and the case's hearings with the order passed at each. The side panel can be put away to give the page the width. |
| `ORD-16` | A filed document opens in the side panel itself, readable beside the order, and returns to the list. |
| `ORD-17` | Any document in the case file can be **linked to the order**. An application decided in the order is linked by being decided, and cannot be unlinked while the decision stands. |
| `ORD-18` | **Order data** shows the page read only on one side and the order data on the other, wider side (§6). The side panel comes back with the Order view. |
| `ORD-19` | Once the order has been sent for signing, both views are read only, and the place where the shortcuts sat shows where the order stands: its **signature** and its **order data** (§11). |
| `ORD-20` | The draft saves itself as it is worked, and the footer says that it has. |

---

## 5. The order text

| ID | Requirement |
|---|---|
| `TXT-01` | The order text is **one body of rich text**, typed by the order drafter. It is editable from the moment the screen opens. |
| `TXT-02` | The editor supports paragraphs, numbered and lettered lists, emphasis and tables. Its toolbar stays in view as a long order scrolls. |
| `TXT-03` | An empty page shows, at the first line, where to click and type, and that `/` opens a shortcut. It disappears as soon as anything is typed or inserted. |
| `TXT-04` | **The order text is the record.** There is no second wording of the same order: what the text says is what goes into the A-Diary, what the parties see, and what is shown wherever the order appears (`PUB-04`). |
| `TXT-05` | **Nothing writes into the order text but the order drafter.** Adding an order item, deciding an application, marking attendance or setting the next hearing changes the order data, never the words. Where attendance and the next hearing are shown on the page, they are shown as their own parts of the page, outside the typed text (§9). |
| `TXT-06` | The order text and the order data may say different things. Nothing compares them; the system does not warn and does not block. The order data drives the workflows and the text is the record people read. Keeping them consistent is the responsibility of the people who type and fill them. |

### 5.1 Shortcuts

| ID | Requirement |
|---|---|
| `SHC-01` | A **shortcut** is a name and a piece of formatted text. Typing `/` and the shortcut's name, then Tab, replaces what was typed with its text. |
| `SHC-02` | A one-line shortcut with no formatting is inserted inline, in the sentence being typed. Anything longer is inserted as its own paragraphs, with its formatting. |
| `SHC-03` | A `[…]` in a shortcut's text is a blank. On insertion the first blank is selected, so the drafter types straight over it. |
| `SHC-04` | A shortcut has no workflow and no order data. It saves typing and nothing else. |
| `SHC-05` | The order drafter can list, search, add, change and remove shortcuts from a **Shortcuts** dialog on the screen. |
| `SHC-06` | The shortcuts a person starts with are the catalogue's order items that carry no variables, worded as the catalogue words them, and a set of longer model orders. |
| `SHC-07` | Shortcuts belong to the person and follow them across devices. A court-wide shared set is `Q-5`. |

### 5.2 The order's title

An order carrying several order items needs a name, because a register or a list cannot
show an order by its order item when it has three. This follows the old system.

| ID | Requirement |
|---|---|
| `TIT-01` | Every order carries a **title**. |
| `TIT-02` | An order with one order item takes that order item's name as its title, and the title is not editable. |
| `TIT-03` | When a second order item is added, the title becomes the first order item's name followed by *and other items*, and becomes **editable**. |
| `TIT-04` | From that point the system never changes the title again. Changing which order item is first, or removing one, leaves the title as it stands; it is edited if it is now wrong. |
| `TIT-05` | The title can be edited while the order is a draft. Once the order is signed it is fixed. |
| `TIT-06` | Wherever orders are listed, the list shows the **title**. |

---

## 6. The order data

The Order data view carries, top to bottom: attendance and the next hearing where the
court enters them here (§9), the order items, and the applications standing on the matter.

### 6.1 Order items

| ID | Requirement |
|---|---|
| `ITM-01` | Order items are chosen from the configured catalogue. Three ways in: what is likely at this hearing, a search across every order item, and the categories, browsable as lists. |
| `ITM-02` | **Likely at this hearing** lists the order items that configuration associates with what this hearing was listed for. It is a shortcut to part of the same catalogue; every other order item stays reachable through the search and the categories. |
| `ITM-03` | An order item the case cannot take is **listed with the reason**, not hidden and not offered. The reason is the configured availability rule — only before cognizance, only once the case is on file, only for a long-pending case, comes from an application — or the configured combination restriction it would break (`ITM-07`). |
| `ITM-04` | Contextual order items — the accept and reject ones — are never browsable. They arrive from the thing that produces them: an application being decided, or the work that opened the screen. |
| `ITM-05` | Adding an order item that asks for fields opens it in a dialog to fill them. One that asks for nothing is added at once. The dialog says that the order item is recorded in the order data and set moving once the order is signed and its order data is complete, and that nothing is written into the order text. |
| `ITM-06` | An order may carry several order items, including more than one of the same order item — two summonses to two witnesses are two order items. |
| `ITM-07` | Configuration holds which order items cannot stand in the same order, and which cannot be repeated in one — the *Combination restrictions* section of [`order-template-catalogue.md`](order-template-catalogue.md). The screen refuses the addition and shows the configured message. |
| `ITM-08` | Order items are listed in the sequence they were added, numbered. That sequence is what decides the order their workflows are triggered in (`PUB-03`). |
| `ITM-09` | An order item can be reopened, edited and removed until the order data is marked complete. Removing it takes it and its workflow out of the order. |
| `ITM-10` | Several orders can be given the same order items at once, from Pending orders: the order data filler selects hearing orders, chooses one or more order items, and each is added to every selected order as that order's own order data would add it, filled against that order's case and people. An order item that asks for fields is left to be filled on each order. |
| `ITM-11` | An order item may need input beyond its template variables, where the workflow it triggers needs it — the delivery channels per recipient for a process order (`PRC-03` of [`process-handover.md`](process-handover.md)). That input is asked for as part of the order item; its fields are owned by the workflow's own document. |

### 6.2 Fields

| ID | Requirement |
|---|---|
| `VAR-01` | **The system fills single-valued facts.** Court name, cause title, case number, current date, judge name and designation, complainant name, accused name, the date of this hearing. Nobody types these. |
| `VAR-02` | **The system fills values it has already collected.** The application number and type when the order item was reached from that application; the next hearing's date and purpose once they are set; values a workflow collected when the screen was opened from that workflow's task. |
| `VAR-03` | **The system never guesses a choice.** A party reference fills automatically only where the case holds exactly one candidate of that kind; with more than one, the order data filler chooses. An application number is filled only where the order item was reached from that application — never by taking the only application standing on the matter. |
| `VAR-04` | Everything left is asked for as a field typed to the variable: a party selector, a date picker, an amount in rupees, a dropdown from master data, or free text. |
| `VAR-05` | **Locked variables are mandatory.** The order data cannot be marked complete while any order item has a locked variable or a required workflow input unanswered (`CMP-02`). |
| `VAR-06` | An optional or conditional variable may be left unanswered. |
| `VAR-07` | A value is stored on the order item as data. **The stored value drives the workflow.** |

### 6.3 Applications standing on the matter

| ID | Requirement |
|---|---|
| `APL-01` | The order data lists the applications on file standing on the matter, each with what it is, who raised it and when, and a way to open and read it without leaving the screen. They are listed last, under the order items. |
| `APL-02` | **Taking an application on file** is not done on this screen. It is a system action, not an order, owned by [`application-lifecycle.md`](application-lifecycle.md). |
| `APL-03` | The CMP number is assigned **only on being taken on file**, not at filing. Until then the application is referred to by its application number. Both number formats are owned by [`case-numbers.md`](case-numbers.md). |
| `APL-04` | **Dismissing an application at admission** — before it is taken on file — is an order. It is opened from the application, with the dismissal already in its order data as an order item that cannot be removed (`ORD-10a`), and takes effect when the order is signed and its order data triggered. |
| `APL-05` | An order dismissing an application at admission **does not cite the application number**. That number is internal and is not something a court recognises as identifying an application. It identifies the application by **what kind of application it is, who raised it, and when it was filed**. |
| `APL-06` | **On the configuration:** an order item is needed for dismissal at admission, identifying the application by its kind, its filer and its filing date (`APL-05`). The existing *Reject application* cites a CMP number the application does not yet have, so it cannot serve. Part of the template work. |
| `APL-07` | **Once on file**, an application is allowed or rejected in the order data. The decision uses the configured accept / reject order item. A decision may be changed or cleared until the order data is marked complete. |
| `APL-08` | Any workflow that follows belongs to the **application type**, not to the accept/reject order item, and is triggered with the order's other workflows like any other order item's. |
| `APL-09` | Acceptance of bail is its own order item because it optionally triggers the bail bond workflow; it is not the generic accept. |
| `APL-10` | Accepting an application that moves the hearing — a request to postpone or advance it — needs the next hearing's date, because that date is where the hearing moves to. The order data cannot be marked complete without it (`CMP-02`). |
| `APL-11` | An order opened from an application has that application in its order data and the decision being made already loaded. |
| `APL-12` | An application left undecided does not block the order. |

---

## 7. The draft

| ID | Requirement |
|---|---|
| `DFT-01` | **One draft order per hearing**, shared by everyone working it. The person typing the order and the person filling its order data work the same draft, and each sees the other's changes. |
| `DFT-02` | Concurrent editing is not locked. The last write stands. |
| `DFT-03` | Outside a hearing, a draft belongs to the case. **Several draft orders may stand open on one case at the same time**, each its own draft. |
| `DFT-04` | A draft is saved and survives a reload, a sign-out and a change of device. It is not held in the browser. |
| `DFT-05` | Once an order has any text, it is listed in **Pending orders** at *Drafting* (§11). How a pending task relates to a draft order — whether the task closes when the draft is created or only when the order is signed, and whether it comes back if the draft is deleted — is owned by [`pending-tasks-handover.md`](pending-tasks-handover.md). |
| `DFT-06` | A draft may be discarded by the order drafter. Discarding removes it; it issues nothing and records nothing on the case. |
| `DFT-07` | **A draft is not an order.** Nothing is numbered, published, notified or triggered from a draft. |

---

## 8. Sending for signing

| ID | Requirement |
|---|---|
| `SND-01` | Drafting ends with **Send for signing**, the only primary action on the footer. It asks for confirmation, saying that the order goes to the order signer in Pending orders, that it can be moved back to draft until it is signed, and that its order data is triggered once it is signed and its order data is complete. |
| `SND-02` | An order cannot be sent for signing while its text is empty. |
| `SND-03` | Where the next hearing is entered **on the order** (§9), an order cannot be sent for signing until the next hearing is settled — a date and a purpose, or *Not listed again*. Attendance does not block sending. |
| `SND-04` | The order data does not have to be filled, or complete, for the order to be sent for signing. |
| `SND-05` | Once sent, the order text is **read only**. To change it, the order drafter **moves it back to draft**; this is possible until the order is signed, and takes it out of the signer's list until it is sent again. |
| `SND-06` | **Editing the text puts completed order data back to incomplete.** The order data was completed against words that are no longer the order's, so it has to be looked at again. |

---

## 9. Attendance and the next hearing

Where these two are entered is a court setting, because courts divide this work
differently.

| ID | Requirement |
|---|---|
| `PLC-01` | **`detailsPlacement`**, set per court: **on the order** (default) or **in order data**. |
| `PLC-02` | **On the order:** attendance is entered at the top of the page, under the court's heading, and the next hearing at the foot, above the signature block. Both are **printed on the order** as lines of their own — *Present: …*, *Absent: …*, *Next hearing: …* — and the next hearing has to be settled before the order is sent for signing (`SND-03`). |
| `PLC-03` | **In order data:** attendance and the next hearing are entered at the top of the Order data view. They are recorded and drive their workflows, but are **not printed** on the order. They can be changed until the order data is marked complete. |
| `PLC-04` | **`nextHearingEntry`**, set per court: **on the cause list** (default) or **in the order**. On the cause list, the next hearing setter enters the next hearing in a *Next hearing* column on the day's board, and the order shows it read only. In the order, it is entered on the order screen as `PLC-02` or `PLC-03` places it, and the cause list has no *Next hearing* column — one question has one place to answer it. |

### 9.1 Attendance — in a hearing only

| ID | Requirement |
|---|---|
| `ATT-01` | The roll is a **fixed list of four** in this version: the complainant, the complainant's advocate, the accused, and the accused's advocate. Nothing is checked or varied — not whether a side actually has an advocate, not a party appearing in person, not a PoA holder, not several complainants or several accused. Those cases are for a later version. |
| `ATT-02` | One mark per person — present or absent. A person may be left unmarked, and a mark may be cleared: no answer for a person is a real state. A single action marks everyone not yet marked as present. |
| `ATT-03` | Where attendance is printed (`PLC-02`), the page shows a **Present** line and an **Absent** line, naming each person and the office they appear in. A side with nobody marked prints no line. |
| `ATT-04` | An incomplete roll does not block the order or its order data. The order records what was answered. |

### 9.2 The next hearing

| ID | Requirement |
|---|---|
| `NXT-01` | The order carries where the matter is posted to: a date and a purpose, or an explicit decision not to list it again. |
| `NXT-02` | Both facts are needed. A date without a purpose, or a purpose without a date, is half an answer and is not printed or recorded as settled. |
| `NXT-03` | In a hearing this is the only place the next date is set; the *Scheduling of hearing date* order item is not offered (`ORD-09`). Outside a hearing that order item is how a date is set. |
| `NXT-04` | Whether the date offered is constrained — court calendar, holidays, the judge's availability, slot purpose — is owned by [`scheduling-product.md`](../scheduling/scheduling-product.md). |

### 9.3 Dates held before the order is triggered

The next date is **announced once the order's workflows are triggered** (`PUB-07`): until
then, nothing is listed and no party is told. But a court sets these dates one matter at a
time through the day, and the orders are often signed at the end of it. If the bench has
already set the same date for fifty matters, the fifty-first must not be picked in
ignorance of them.

| ID | Requirement |
|---|---|
| `NXT-10` | A next hearing date set on a draft order creates a **provisional listing** on that date from the moment it is set. Provisional, not scheduled: no cause list entry, no notification, nothing final. |
| `NXT-11` | Everything that reads a day's load counts provisional listings alongside confirmed ones — the date picker first of all, so the bench setting the fifty-first sees the fifty it has just set. |
| `NXT-12` | A provisional listing is distinguishable from a confirmed one wherever a day's load is shown, because it may still evaporate. |
| `NXT-13` | Changing the date moves the provisional listing. Discarding the draft, or removing the next date from it, releases it. |
| `NXT-14` | A provisional listing becomes the scheduled hearing when the order's workflows are triggered. |
| `NXT-15` | A provisional listing that is never triggered does not expire on its own; it lives and dies with the order that holds it. How long it may hold a date is `Q-1`. |

---

## 10. The hearing control — in a hearing only

| ID | Requirement |
|---|---|
| `HRG-01` | The header carries **one hearing control**. For a person holding **hearing controller**, one press does three things: it marks this listing heard, calls the next unheard listing on the day's board in serial order, and opens its order screen. It reads *Next case*, or *End hearing* where there is no next listing; then it ends this hearing and returns to the day's board. |
| `HRG-02` | For a person without hearing controller, the same control only takes them to the hearing now under way; it ends nothing and starts nothing. It is **disabled until the next hearing has been started** by a hearing controller, and it **names the hearing it will take them to** — its item number on the day's board — once that hearing is under way. |
| `HRG-03` | `HRG-02` means the control changes without its user doing anything: another person's action enables it and gives it its number. The screen keeps it current while it is open, rather than waiting for a reload. |
| `HRG-04` | Ending a hearing does not require the order to be complete, sent or signed. The draft stays on the listing and can be returned to. |

---

## 11. Pending orders

Every order that has not yet run its course is in **one list**, for everyone on the court
side. Each person sees the other people's steps.

```
Drafting ──▶ Awaiting signature ──▶ Order data to fill ──▶ Triggered
 (drafter)      (signer)              (filler; only a        (nothing
                                       signed order whose     changes)
                                       data is not complete)
```

| ID | Requirement |
|---|---|
| `PND-01` | Pending orders lists **every order** typed on the order screen — a hearing's or not — from its first text until its workflows are triggered. |
| `PND-02` | An order's **stage** is read from two facts — whether it is signed, and whether its order data is complete — and whether it has been sent: **Drafting** (not sent) → **Awaiting signature** (sent, not signed) → **Order data to fill** (signed, order data not complete) → **Triggered** (signed and order data complete). |
| `PND-03` | The list is tabbed by stage. Each row shows the order's title, case, where it comes from (a hearing and its purpose, cognizance, an application), and two columns that read the same for everyone: its **signature** and its **order data**. |
| `PND-04` | Each person opens the list on the stage that is their move: an order signer on *Awaiting signature*, an order data filler on *Order data to fill*. The count shown against Pending orders in the navigation is the number of orders at that stage. A person with no move here gets no count. |
| `PND-05` | Each row offers the one act that is the viewer's move at that stage: a draft opens back on the order screen; an order awaiting signature can be signed; an order whose data is to fill opens to fill it. |
| `PND-06` | An order signer can select several orders awaiting signature and sign them in one action (`SGN-03`). |
| `PND-07` | An order data filler can select several hearing orders and add the same order items to each (`ITM-10`). |
| `PND-08` | Opening a pending order shows its text read only on one side, its order data on the other, and where it stands — signature, then order data — above both. A line under it says where it stands and whose move it is. |

---

## 12. Signing

| ID | Requirement |
|---|---|
| `SGN-01` | Only a person holding **order signer** may sign. Enforced server-side. |
| `SGN-02` | An order is signed from Pending orders, once it is **sent for signing**. The confirmation says what signing will do: issue the order, and trigger its order data at once if it is complete, or once it is completed if not. |
| `SGN-03` | Several orders may be signed in one action. |
| `SGN-04` | Signing does not need the order data to be complete. |
| `SGN-05` | Court-side users may sign with **Aadhaar-based e-sign** or with a **DSC**. Both are offered; the signer chooses. |
| `SGN-06` | `SGN-03` and `SGN-05` interact. A DSC signs any number of documents in one action. Aadhaar e-sign through C-DAC accepts **one document per authentication**, so signing ten orders is ten OTPs unless the batch approach in [`batch-esign-proposal.md`](../signing/batch-esign-proposal.md) is used — which puts the court's seal, not the signer's Aadhaar signature, on each order. See `Q-2`. |

---

## 13. Completing the order data and triggering

| ID | Requirement |
|---|---|
| `CMP-01` | The order data filler **marks the order data complete** when it is filled. This can be done at any time once the order exists — before or after it is signed. |
| `CMP-02` | The order data cannot be marked complete while: an order item has a locked variable or required workflow input unanswered (`VAR-05`); the next hearing is not settled; or an accepted application that moves the hearing has no next hearing date (`APL-10`). The screen names what is missing and where to set it. |
| `CMP-03` | Before marking it complete, the order data filler sees **what triggering will send**, in words: each order item and what it sets moving, each decision, attendance and the next hearing. |
| `CMP-04` | **Triggering needs both**: the order signed, and its order data complete. When both are true, the workflows are triggered at once with no further step — by the signature, if the order data was already complete; by marking it complete, if the order was already signed. |
| `CMP-05` | Completed order data can be **reopened** by the order data filler until the order is signed. Once the order is signed and its order data complete, the workflows have gone out and nothing changes. |
| `CMP-06` | Order data can be filled while the order awaits signature, and after it is signed, until it is triggered. |

---

## 14. Once triggered — what the order becomes

| ID | Requirement |
|---|---|
| `PUB-01` | Signature is what makes it an order of the court. The order is numbered, dated and stored as a signed PDF. The number format is owned by [`case-numbers.md`](case-numbers.md). |
| `PUB-02` | The signed order joins the case record and becomes visible to the parties on the case. |
| `PUB-03` | **Each order item's workflow is triggered when the order is triggered (`CMP-04`), and never before.** An order carrying three order items triggers three workflows, each reading the values stored against its own order item (`VAR-07`). The sequence they are triggered in is configuration — the *Workflow trigger order* section of [`order-template-catalogue.md`](order-template-catalogue.md) — because a hearing-date change has to land before the workflows that use the new date, and a case-closing order after everything else. |
| `PUB-04` | The order's text becomes the case's **A-Diary entry** for the date of the hearing, unchanged and in full (`TXT-04`). The same text is what the parties see on the case and what any other screen showing this order shows. The A-Diary register itself, and its own signing, are not owned by this document — see `Q-3`. |
| `PUB-05` | Case stage changes are not workflows. A listener reads order events and moves the stage; stage rules are owned by [`case-lifecycle-handover.md`](case-lifecycle-handover.md). |
| `PUB-06` | A signed order cannot be edited or withdrawn. The court may pass a later order correcting it; the system records **no link** between the two, and neither order is marked as superseding or superseded. |
| `PUB-07` | The next hearing in the order data is **announced when the order is triggered** and becomes the scheduled hearing then. Before that it is held provisionally (§9.3). |

---

## 15. Open questions

| # | Question | Blocking? |
|---|---|---|
| `Q-1` | `NXT-15`: an untriggered order holds its date provisionally with nothing forcing it to be released. Does a draft expire, or is a stale-draft list enough? | No |
| `Q-2` | `SGN-06`: signing several orders at once with Aadhaar e-sign is one authentication per order. Do court users accept that, use a DSC for bulk signing, or is the batch-certificate approach wanted here too? | No |
| `Q-3` | `PUB-04`: the order's text becomes the A-Diary entry. Which document owns the A-Diary register and its own signing? | No |
| `Q-4` | `ATT-01`: the *People required* column of the hearing-purpose table in [`order-template-catalogue.md`](order-template-catalogue.md) names who should attend each purpose. Should the attendance roll use it — pre-select those people, or warn when one of them is unmarked or absent — or is the roll simply everyone on the case? | No |
| `Q-5` | `SHC-07`: shortcuts are personal. Does a court also need a shared set, and who maintains it? | No |
| `Q-6` | `TIT-02`–`TIT-05`: the title follows the order items, but order items can be added after the order is signed (`CMP-06`), when the title is fixed. Is the title taken from the order items at signing, or does it follow them until the order data is complete? | No |
