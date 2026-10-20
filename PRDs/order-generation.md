# Order generation

**Status:** v8.1 — 2026-10-19; `ORD-08`: outside a hearing the next hearing is on the order as in a hearing, defaulting to the case's listed hearing; changing it adds a *Rescheduling of hearing date* order item (`NXT-03` aligned). `ORD-10a`: an order item added by the work that opened the screen is added in advance, not required, and can be removed (`APL-04` aligned). `ORD-14` (signature block status) removed. `ORD-15`: the side panel has three tabs — Case file, Case history (last order highlighted, filter to orders) and Data flags (not yet defined). `ORD-17`: no rule against unlinking a decided application. `ORD-18` reworded. `ITM-12`: the order data is built to take a later layer that reads the order text and lists or adds order items. `TIT-02`: the title comes from the order data's order items and is editable; how it follows them is left to the design (`TIT-03`, `TIT-04` removed). `ITM-04`: contextual order items can be chosen like any other, then ask what they apply to. `TIT-05`: the title is editable until the order is triggered, not just until signing (`Q-6` resolved). `ITM-11` removed: every order item just has variables, including what its workflow needs. `VAR-05`/`VAR-06`: no locked or optional variables; a field is mandatory to enter or not (old text in [`dropped-ideas.md`](dropped-ideas.md)). Template wording removed from the scope, out-of-scope table and `APL-06`: order items carry no template text. §6.3 cut to two rows: pending applications are listed, and the actions on them are owned by application-lifecycle.md (old rows in [`dropped-ideas.md`](dropped-ideas.md)). `DFT-02`: concurrent editing is ideally blocked, with the least effort that handles it, instead of last write wins. `DFT-05`: a draft is listed under *Drafting* in Pending orders through a pending task, cleared on sending for signing or discarding, and back when the order is moved back to draft. `SND-07`/`SND-08`: sending for signing creates a signing task and an order data task, worked in parallel; moving back to draft clears both, and sending for signing again recreates both. `ATT-02`–`ATT-04`: attendance is present, absent or not required, and must be complete before the order is sent for signing; the screen may default anyone unmarked to not required. `PND-02`: an order sent for signing sits in both *Awaiting signature* and *Order data to fill* until each is done. `Q-4`: People required will later mark people not required; not signed off. `SND-08`: sending for signing again after moving back to draft puts completed order data back to not complete, keeping its values. Bare "sent"/"sending" for orders replaced by "sent for signing" throughout. `PLC-01`/`PLC-03` removed: attendance and the next hearing are always on the order; only where the next hearing is entered (`PLC-04`) is a court setting. `PLC-04` reworded to say where and who. `ATT-01`: the roll lists every complainant, accused and PoA holder, with one advocate line per complainant and per accused; a party in person has none. §10 rewritten: Start hearing, End hearing and Pass over; Next case only takes people to the next started hearing. Which person sees which control is `Q-7`. §10 extended: statuses (Scheduled, Ongoing, Passed over, Heard, Abandoned), controls on the cause list only, several hearings Ongoing at once, ending in bulk, times recorded; pass over follows DRISTI 1.0. `ITM-10`/`PND-07`: order items added to several orders at once still have their fields filled, and each order marked complete, one order at a time. `SGN-06`: with Aadhaar e-sign orders are signed one at a time, bulk signing needs a DSC, and the batch-certificate approach does not apply to orders (`Q-2` resolved). `CMP-02` cut to mandatory fields only; `SND-03`: the next hearing must be settled before sending for signing, whether entered in the order or on the cause list. `CMP-03` (summary of what triggering will do) removed. `PUB-04`/`TXT-04`: the A-Diary entry is its own text, the same as the order text by default (an option, checked by default), and can be typed separately; shown cut at about one paragraph, with the order opened for the rest; set by the order data filler in the Order data view. Which text each screen shows is left to the screens (`PUB-04`, `TXT-04`). `NXT-15`: a draft does not expire (`Q-1` resolved). `SHC-06`/`SHC-07`: shortcuts are saved per courtroom; personal sets and who maintains the courtroom's set stay `Q-5`. `Q-4` moved to `ATT-02a` as a later-version note. `HRG-00`: hearing controls are shown only to the hearing controller, on the cause list (`Q-7` resolved). Out-of-scope table: conduct of the hearing is now §10, leaving only the cause list as a screen; the judgement has no screen of its own — it is drafted on this screen. `Q-3` resolved: the A-Diary register is owned by the new [`a-diary.md`](a-diary.md). `SHC-07`: any order drafter maintains the courtroom's shortcuts; no personal shortcuts in this version (`Q-5` resolved). New §10.1 *The cause list screen* (`CLS-01`–`CLS-06`): grouped by status, then the generated sequence; a superset of columns, configurable and sticky per person; Action and Next hearing offered by role. Generating the cause list stays out of scope. New §15 *Pending tasks*: Draft order, Sign order and Fill order data, as a live view of the master Pending Tasks (Court Side) list; open questions are now §16. §10.1 extended: filters (`CLS-07`), row actions (`CLS-08`), bulk selection and bulk actions (`CLS-09`, `CLS-10`), the case overview (`CLS-11`). `CLS-11`: the overview's case history is the order screen's *Case history* tab (`ORD-15`), replacing the separate last-hearing section. `HRG-02`/`CLS-10`: a hearing is always started before it is ended; ending a Scheduled listing in bulk starts and ends it with the same press. `CLS-07`: any column can be filtered where it makes sense, status included. `CLS-11`: the overview also shows the Data flags. New §1.1 *What an order carries* (its attributes) and §1.2 *How an order moves* (the state diagram), as a summary. `PUB-04`: the A-Diary entry is kept in full, never cut at a paragraph; shortening while showing is left to each screen. §1.1: *Opened from* is not an attribute of the order, and a decision on an application is an order item, not a separate attribute. Signature and order data completeness are folded into the order's *Status*. Pending tasks are not part of the order (§15). `PND-03`: a row no longer shows where the order comes from. `CLS-11`: the overview's foot carries Pass over too. `CLS-12`: an order drafter can add the same text to several orders from the cause list.

v8 — 2026-10-18; rewritten to order screen E and the Pending orders flow. An
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
it, and triggering what it sets moving. A judgement is drafted on this same screen, like
any other order. Order items, variables, categories and
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
  what is signed. By default it is also the A-Diary entry (`PUB-04`).
- **The order data** — what the order sets moving: its order items and their values, the
  decision on each application, attendance and the next hearing. This drives the
  workflows. Nothing in the order data is written into the order text.

The two are typed and filled by people holding different roles, at different times. An
order's workflows go out only once **both** the order is signed **and** its order data is
marked complete (§13).

### 1.1 What an order carries

| Attribute | What it holds | Owned by |
|---|---|---|
| Case | The case the order belongs to | `ORD-01` |
| Hearing | The listing it was drafted at, in a hearing; none outside one | `ORD-05`, `ORD-06` |
| Title | Taken from its order items; editable until the order is triggered | §5.2 |
| Order text | The words of the order, typed by the order drafter. The record: what is signed | §5 |
| Order items | Zero or more items from the catalogue, each with its fields and its workflow. A decision on a pending application is one of them — *Accept application*, *Reject application* and the like (§6.3) | §6.1–§6.3 |
| Attendance | Present, absent or not required, for each person on the roll — in a hearing only | §9.1 |
| Next hearing | A date and a purpose, or *Not listed again*; held provisionally until triggered | §9.2, §9.3 |
| A-Diary text | The same as the order text by default, or typed separately | `PUB-04` |
| Linked documents | Documents from the case file linked to the order | `ORD-17` |
| Status | Drafting, Awaiting signature, Order data to fill, Triggered — read from whether it is sent for signing, signed, and its order data complete | `PND-02` |
| Number and date | Given when the order is signed | `PUB-01` |
| Signed PDF | The signed order as stored | `PUB-01` |

Attendance, the next hearing and the A-Diary text are order data. Attendance and the next
hearing are also printed on the order (`PLC-02`).

### 1.2 How an order moves

```
                                  ┌─▶ Awaiting signature ── Sign ─────────────┐
Drafting ── Send for signing ─────┤     (order signer)                         ├─▶ Triggered
(order        (text, next         └─▶ Order data to fill ── Mark complete ─────┘   (workflows go out;
 drafter)      hearing and              (order data filler)                          next hearing
  │   ▲        attendance                                                             announced)
  │   │        settled)
  │   └──── Move back to draft — any time before signing. Sending for signing again
  │         recreates both tasks and puts completed order data back to not complete.
  │
  └──── Discard ──▶ removed; nothing is recorded on the case
```

- Once sent for signing, an order sits in **both** *Awaiting signature* and *Order data to
  fill* until each is done; the two are worked in parallel (`SND-07`, `PND-02`).
- Signing does not need the order data to be complete, and the order data can be completed
  before or after signing (`SGN-04`, `CMP-01`).
- An order is **triggered** the moment it is both signed and its order data complete
  (`CMP-04`). Nothing changes after that (`CMP-05`).

### 1.3 Configuration and scope

Everything on this screen depends on configuration being in place: the order items the
court has, the fields each asks for, the category each sits in, the hearing purposes each
is associated with, the workflow each triggers, which of them cannot stand in the same
order, and the sequence their workflows run in. That configuration — system default or
set up by the court — is owned by
[`order-template-catalogue.md`](order-template-catalogue.md), and nothing in this document
restates it.

**The order items and variables are not final.** The catalogue is still being worked on, so
nothing here depends on what it happens to hold today. Where this screen needs something
the configuration does not yet carry, it is written below as a requirement **on the
configuration**.

What is out of scope, and where it belongs:

| Out of scope | Owner |
|---|---|
| The order items themselves — variables, categories, hearing associations, combination restrictions, workflow trigger order | [`order-template-catalogue.md`](order-template-catalogue.md) |
| What each order's workflow does once triggered | A document per workflow; process orders are in [`process-handover.md`](process-handover.md) |
| Which roles exist and what each allows | [`court-roles.md`](court-roles.md) |
| Taking an application on file, and the application's own lifecycle | [`application-lifecycle.md`](application-lifecycle.md) |
| Generating the cause list — which matters are listed on a day, and in what sequence. The cause list screen and its hearing controls are in §10. | Not yet written; listing dates are in [`scheduling-product.md`](../scheduling/scheduling-product.md) |
| Case stages the order moves | [`case-lifecycle-handover.md`](case-lifecycle-handover.md) |
| Order and application number formats | [`case-numbers.md`](case-numbers.md) |
| Pending task attributes and visibility | [`pending-tasks-handover.md`](pending-tasks-handover.md) |
| The A-Diary register — its entries, editing and signing | [`a-diary.md`](a-diary.md) |

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
| `ORD-08` | Outside a hearing, **attendance** and **Next case** (§10) are absent. The **next hearing** is on the order as it is in a hearing (§9.2), set by default to the hearing the case is already listed for. It can be changed; changing it adds a *Rescheduling of hearing date* order item to the order, its original and new dates filled from that change. |
| `ORD-09` | Which order items are available follows from the situation. *Scheduling of hearing date* is offered outside a hearing and not inside one, where the next date is set as the next hearing instead (`NXT-03`). |
| `ORD-10` | A case may carry any number of orders over its life. |
| `ORD-10a` | An order item loaded by the work that opened the screen — the decision on the application it was opened from, the cognizance act — is **added in advance**, not required. It can be removed like any other order item. |

---

## 3. Roles

This screen uses six roles from [`court-roles.md`](court-roles.md). A person may hold any
number of them, and sees the controls for every role they hold.

| ID | Role | What it does on this screen and in Pending orders |
|---|---|---|
| `ROL-01` | **Order drafter** | Types and edits the order text; manages their shortcuts; sends the order for signing; moves it back to draft before it is signed; discards a draft. |
| `ROL-02` | **Order data filler** | Adds, edits and removes order items and their fields; decides applications; marks attendance; sets the A-Diary text (`PUB-04`); marks the order data complete and reopens it before signing; adds order items to several orders at once. |
| `ROL-03` | **Next hearing setter** | Sets the next hearing's date and purpose, or records that the matter is not listed again, wherever the court enters it (§9). |
| `ROL-04` | **Order signer** | Signs orders, one at a time or several at once. |
| `ROL-05` | **Hearing controller** | Starts, ends and passes over hearings (§10). |
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
| `ORD-11` | The header states which matter this is: cause title, case number, case stage, and — in a hearing — the listing's item number on the day's board and what the matter was listed for. It carries the side panel's switch and, in a hearing, the **Next case** button (§10). |
| `ORD-12` | The screen has two views, switched above the page: **Order** and **Order data**. |
| `ORD-13` | **Order** shows the order as one page, as it will print: the court's heading at the top, the signature block at the foot, and the order text between them. The heading and signature block are rendered from the record and are never typed. The page is the same rendering the signed PDF uses; the two never disagree about what the document says. |
| `ORD-15` | Beside the page, in the Order view, a **side panel** carries the case in three tabs. **Case file** — the same case file as the case's Case File section ([`view-case-handover.md`](view-case-handover.md) §6). **Case history** — the case history ([`view-case-handover.md`](view-case-handover.md) §12), with the case's last order highlighted and a filter to show only orders. **Data flags** — not yet defined; things like attendance history. The side panel can be put away to give the page the width. |
| `ORD-16` | A filed document opens in the side panel itself, readable beside the order, and returns to the list. |
| `ORD-17` | Any document in the case file can be **linked to the order**. |
| `ORD-18` | In the **Order data** view, the order text is shown read only beside the order data (§6), so whoever fills the data can see what the order says. The side panel is not shown in this view. |
| `ORD-19` | Once the order has been sent for signing, both views are read only, and the place where the shortcuts sat shows where the order stands: its **signature** and its **order data** (§11). |
| `ORD-20` | The draft saves itself as it is worked, and the footer says that it has. |

---

## 5. The order text

| ID | Requirement |
|---|---|
| `TXT-01` | The order text is **one body of rich text**, typed by the order drafter. It is editable from the moment the screen opens. |
| `TXT-02` | The editor supports paragraphs, numbered and lettered lists, emphasis and tables. Its toolbar stays in view as a long order scrolls. |
| `TXT-03` | An empty page shows, at the first line, where to click and type, and that `/` opens a shortcut. It disappears as soon as anything is typed or inserted. |
| `TXT-04` | **The order text is the record.** There is no second wording of the order itself. Which text each screen shows is left to that screen. The A-Diary entry is a separate text, which by default is the same (`PUB-04`). |
| `TXT-05` | **Nothing writes into the order text but the order drafter.** Adding an order item, deciding an application, marking attendance or setting the next hearing changes the order data, never the words. Where attendance and the next hearing are shown on the page, they are shown as their own parts of the page, outside the typed text (§9). |
| `TXT-06` | The order text and the order data may say different things. Nothing compares them; the system does not warn and does not block. The order data drives the workflows and the text is the record people read. Keeping them consistent is the responsibility of the people who type and fill them. This holds until the reading layer of `ITM-12` is built. |

### 5.1 Shortcuts

| ID | Requirement |
|---|---|
| `SHC-01` | A **shortcut** is a name and a piece of formatted text. Typing `/` and the shortcut's name, then Tab, replaces what was typed with its text. |
| `SHC-02` | A one-line shortcut with no formatting is inserted inline, in the sentence being typed. Anything longer is inserted as its own paragraphs, with its formatting. |
| `SHC-03` | A `[…]` in a shortcut's text is a blank. On insertion the first blank is selected, so the drafter types straight over it. |
| `SHC-04` | A shortcut has no workflow and no order data. It saves typing and nothing else. |
| `SHC-05` | The order drafter can list, search, add, change and remove shortcuts from a **Shortcuts** dialog on the screen. |
| `SHC-06` | Shortcuts are saved **per courtroom**: everyone drafting orders in a courtroom works from that courtroom's saved set, on any device. |
| `SHC-07` | **Any order drafter** in the courtroom maintains the courtroom's set: lists, searches, adds, changes and removes its shortcuts (`SHC-05`). There are no personal shortcuts in this version. |

### 5.2 The order's title

An order carrying several order items needs a name, because a register or a list cannot
show an order by its order item when it has three. This follows the old system.

| ID | Requirement |
|---|---|
| `TIT-01` | Every order carries a **title**. |
| `TIT-02` | The title is taken from the order items in the order data (§6.1), and is **editable** until the order is triggered (`TIT-05`). How the title follows the order items as they are added, reordered and removed is left to the design. |
| `TIT-05` | The title can be edited until the order is **triggered** — signed and its order data complete (`CMP-04`) — since order items can still be added after signing (`CMP-06`). Once triggered it is fixed. |
| `TIT-06` | Wherever orders are listed, the list shows the **title**. |

---

## 6. The order data

The Order data view carries, top to bottom: the order items, the pending applications and the A-Diary text (`PUB-04`).

### 6.1 Order items

| ID | Requirement |
|---|---|
| `ITM-01` | Order items are chosen from the configured catalogue. Three ways in: what is likely at this hearing, a search across every order item, and the categories, browsable as lists. |
| `ITM-02` | **Likely at this hearing** lists the order items that configuration associates with what this hearing was listed for. It is a shortcut to part of the same catalogue; every other order item stays reachable through the search and the categories. |
| `ITM-03` | An order item the case cannot take is **listed with the reason**, not hidden and not offered. The reason is the configured availability rule — only before cognizance, only once the case is on file, only for a long-pending case, comes from an application — or the configured combination restriction it would break (`ITM-07`). |
| `ITM-04` | Contextual order items — the accept and reject ones — can be found and chosen like any other order item. Once chosen, they ask what they apply to — which application — before they are added. They also arrive already applied, from the thing that produces them: an application being decided, or the work that opened the screen. How they are offered is left to the design. |
| `ITM-05` | Adding an order item that asks for fields opens it in a dialog to fill them. One that asks for nothing is added at once. The dialog says that the order item is recorded in the order data and set moving once the order is signed and its order data is complete, and that nothing is written into the order text. |
| `ITM-06` | An order may carry several order items, including more than one of the same order item — two summonses to two witnesses are two order items. |
| `ITM-07` | Configuration holds which order items cannot stand in the same order, and which cannot be repeated in one — the *Combination restrictions* section of [`order-template-catalogue.md`](order-template-catalogue.md). The screen refuses the addition and shows the configured message. |
| `ITM-08` | Order items are listed in the sequence they were added, numbered. That sequence is what decides the order their workflows are triggered in (`PUB-03`). |
| `ITM-09` | An order item can be reopened, edited and removed until the order data is marked complete. Removing it takes it and its workflow out of the order. |
| `ITM-10` | Several orders can be given the same order items at once, from Pending orders: the order data filler selects hearing orders, chooses one or more order items, and each is added to every selected order as that order's own order data would add it, filled against that order's case and people. An order item that asks for fields is left to be filled **on each order, one by one**, and each order's data is still marked complete on that order (`CMP-01`). |
| `ITM-12` | **Built to take a reading layer later.** A later version will read the order text for set language — anything from simple keywords to AI — match it to order items, and list them or add them to the order data. It is not built in this version, but the order data must not stand in its way: an order item can be listed or added by something other than a person choosing it on the screen, through the same rules that govern a person's addition (`ITM-03`, `ITM-07`). |

### 6.2 Fields

| ID | Requirement |
|---|---|
| `VAR-01` | **The system fills single-valued facts.** Court name, cause title, case number, current date, judge name and designation, complainant name, accused name, the date of this hearing. Nobody types these. |
| `VAR-02` | **The system fills values it has already collected.** The application number and type when the order item was reached from that application; the next hearing's date and purpose once they are set; values a workflow collected when the screen was opened from that workflow's task. |
| `VAR-03` | **The system never guesses a choice.** A party reference fills automatically only where the case holds exactly one candidate of that kind; with more than one, the order data filler chooses. An application number is filled only where the order item was reached from that application — never by taking the only application standing on the matter. |
| `VAR-04` | Everything left is asked for as a field typed to the variable: a party selector, a date picker, an amount in rupees, a dropdown from master data, or free text. |
| `VAR-05` | A field the catalogue marks **mandatory to enter** must be answered before the order data can be marked complete (`CMP-02`). |
| `VAR-06` | Any other field may be left unanswered. |
| `VAR-07` | A value is stored on the order item as data. **The stored value drives the workflow.** |

### 6.3 Pending applications

| ID | Requirement |
|---|---|
| `APL-01` | The order data lists the applications still pending on the matter, under the order items. |
| `APL-02` | Certain actions can be taken on each pending application from here. What they are, and what each does, is owned by [`application-lifecycle.md`](application-lifecycle.md). |

---

## 7. The draft

| ID | Requirement |
|---|---|
| `DFT-01` | **One draft order per hearing**, shared by everyone working it. The person typing the order and the person filling its order data work the same draft, and each sees the other's changes. |
| `DFT-02` | Ideally, **concurrent editing of a draft is blocked**. In practice several people are not expected to change the same draft at once, so this needs only the least effort that handles it; how is left to the build team. |
| `DFT-03` | Outside a hearing, a draft belongs to the case. **Several draft orders may stand open on one case at the same time**, each its own draft. |
| `DFT-04` | A draft is saved and survives a reload, a sign-out and a change of device. It is not held in the browser. |
| `DFT-05` | Once a draft order is created, it is listed in **Pending orders** under *Drafting* (§11). It is listed there through a **pending task**, which is cleared when the order is sent for signing or the draft is discarded. Moving an order back to draft (`SND-05`) brings the task back, and the order is listed under *Drafting* again. |
| `DFT-06` | A draft may be discarded by the order drafter. Discarding removes it; it issues nothing and records nothing on the case. |
| `DFT-07` | **A draft is not an order.** Nothing is numbered, published, notified or triggered from a draft. |

---

## 8. Sending for signing

| ID | Requirement |
|---|---|
| `SND-01` | Drafting ends with **Send for signing**, the only primary action on the footer. It asks for confirmation, saying that the order goes to the order signer in Pending orders, that it can be moved back to draft until it is signed, and that its order data is triggered once it is signed and its order data is complete. |
| `SND-02` | An order cannot be sent for signing while its text is empty. |
| `SND-03` | An order cannot be sent for signing until the next hearing is settled — a date and a purpose, or *Not listed again* — **whichever way the court enters it** (`PLC-04`). Where it is entered on the cause list, the order shows it read only, so it has to be entered there first. In a hearing, the order also cannot be sent for signing until attendance is complete (`ATT-04`). |
| `SND-04` | The order data does not have to be filled, or complete, for the order to be sent for signing. |
| `SND-05` | Once sent for signing, the order text is **read only**. To change it, the order drafter **moves it back to draft**; this is possible until the order is signed, and takes it out of the signer's list until it is sent for signing again. |
| `SND-06` | **Editing the text puts completed order data back to incomplete.** The order data was completed against words that are no longer the order's, so it has to be looked at again. |
| `SND-07` | Sending for signing creates **two pending tasks**: one to **sign the order**, for the order signer, and one to **fill the order data**, for the order data filler. They are worked in parallel; neither waits for the other. |
| `SND-08` | Each task is cleared when its work is done: the signing task when the order is signed, the order data task when the order data is marked complete. Moving the order back to draft (`SND-05`) clears both. Sending it for signing again creates both again. Order data that had been marked complete goes back to **not complete**: the values entered stay, but it has to be looked at again against text that may have changed, and marked complete again. |

---

## 9. Attendance and the next hearing

Attendance and the next hearing are always on the order. Whether the next hearing is
entered in the order or on the cause list is a court setting, because courts divide this
work differently.

| ID | Requirement |
|---|---|
| `PLC-02` | Attendance is entered at the top of the page, under the court's heading, and the next hearing at the foot, above the signature block. Both are **printed on the order** as lines of their own — *Present: …*, *Absent: …*, *Next hearing: …* — and the next hearing has to be settled before the order is sent for signing (`SND-03`). |
| `PLC-04` | Each court chooses **where the next hearing is entered**, and with it **who enters it**. The setting is `nextHearingEntry`, with two values. **On the cause list** (default): the next hearing is entered on the day's cause list, in a *Next hearing* column beside each case, by the person working the cause list during the hearing. The order screen shows it read only. **In the order**: the next hearing is entered on the order screen, at the foot of the order (`PLC-02`), by the person working on the order. The cause list has no *Next hearing* column. Either way the person needs the **next hearing setter** role (`ROL-03`), and the next hearing is entered in one place only, never both. |

### 9.1 Attendance — in a hearing only

| ID | Requirement |
|---|---|
| `ATT-01` | The roll lists **every complainant**, **every accused** and **every PoA holder** on the case. Under each complainant and each accused it lists **one advocate line**, even where that party has several advocates. A party with no advocate — appearing in person — has no advocate line. |
| `ATT-02` | Each person on the roll is marked **present**, **absent** or **not required**. The screen may leave *not required* out as a choice, and set a person to not required when neither present nor absent is marked. A single action marks everyone not yet marked as present. |
| `ATT-02a` | **Not in this version:** the *People required* column of the hearing-purpose table in [`order-template-catalogue.md`](order-template-catalogue.md) will later mark people **not required** automatically for each hearing purpose. Not signed off; until it is, nobody is marked not required automatically. |
| `ATT-03` | On the page (`PLC-02`), attendance shows as a **Present** line and an **Absent** line, naming each person and the office they appear in. People not required are not printed, and a line with nobody on it is not printed. |
| `ATT-04` | **Attendance must be complete before the order is sent for signing**: every person on the roll marked present, absent or not required (`SND-03`). |

### 9.2 The next hearing

| ID | Requirement |
|---|---|
| `NXT-01` | The order carries where the matter is posted to: a date and a purpose, or an explicit decision not to list it again. |
| `NXT-02` | Both facts are needed. A date without a purpose, or a purpose without a date, is half an answer and is not printed or recorded as settled. |
| `NXT-03` | In a hearing this is the only place the next date is set; the *Scheduling of hearing date* order item is not offered (`ORD-09`). Outside a hearing the next hearing starts at the hearing the case is already listed for, and changing it is a rescheduling (`ORD-08`). |
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
| `NXT-15` | A provisional listing that is never triggered does not expire; it lives and dies with the order that holds it. **A draft does not expire.** |

---

## 10. Hearings — in a hearing only

The hearing controls — **Start hearing**, **End hearing** and **Pass over** — are on the
cause list, the day's board, and nowhere else. The order screen carries none of them, only
the **Next case** button (`HRG-10`).

```
                  ┌──────────── Start hearing ─────────────┐
                  ▼                                        │
Scheduled ──▶ Ongoing ──── End hearing ──▶ Heard           │
    │            │                                         │
    └────────────┴──── Pass over ──▶ Passed over ──────────┘

Still Scheduled, Ongoing or Passed over at midnight ──▶ Abandoned
```

| ID | Requirement |
|---|---|
| `HRG-00` | The hearing controls are shown only to a person holding **hearing controller** (`ROL-05`), on the cause list. Inside the case, on the order screen, there is only the **Next case** button (`HRG-10`). |
| `HRG-01` | A listing on the day's board is **Scheduled**, **Ongoing**, **Passed over**, **Heard** or **Abandoned**. |
| `HRG-02` | **Start hearing** makes a Scheduled or Passed over listing Ongoing. **End hearing** makes an Ongoing listing Heard. A hearing is always started before it is ended. **Pass over** makes a Scheduled or Ongoing listing Passed over. |
| `HRG-03` | **Heard is final.** An ended hearing cannot be started again. |
| `HRG-04` | **Passed over** sets a listing aside unheard, to be returned to later the same day: it is started again with Start hearing. On the day's board it sits after the listings still to be heard. |
| `HRG-05` | **Abandoned** is the fallback for a listing not finished on its day. At midnight, every listing of that day still Scheduled, Ongoing or Passed over becomes Abandoned. |
| `HRG-06` | **Several hearings may be Ongoing at once.** The backend allows it. The screen may add a restriction later; it does not at first. |
| `HRG-07` | Several listings can be ended or passed over in **one action** from the cause list. |
| `HRG-08` | **Every change is timed.** Each start, pass over, end and abandonment is recorded with its time. The time a matter was heard is the sum of the periods it was Ongoing. |
| `HRG-09` | Once a hearing is started, the order drafter can open its order and start drafting. Ending or passing over the hearing does not require the order to be complete, sent for signing or signed; the draft stays on the listing and can be returned to. |
| `HRG-10` | The order screen's header carries a **Next case** button. It is not a hearing control: it opens the next Ongoing hearing on the day's board, and is **disabled while there is none**. Once there is one, it names it — its item number on the day's board. It changes without its user doing anything: someone starting a hearing enables it. The screen keeps it current while it is open, rather than waiting for a reload. |


### 10.1 The cause list screen

The cause list for a day is **generated elsewhere**, and this screen assumes it exists. How
it is generated — which matters are listed and in what sequence — is not specified here.

| ID | Requirement |
|---|---|
| `CLS-01` | The screen shows one courtroom's cause list for one day, chosen by date. It opens on today. |
| `CLS-02` | Listings are grouped **by status**, in this order: Ongoing, Scheduled, Passed over, Heard, Abandoned (`HRG-01`). **Within each group**, they keep the sequence the cause list was generated in. |
| `CLS-03` | The columns are chosen from this **superset**: **S. no.** — the item number on the day's board; **Case name**, which opens the case overview (`CLS-11`); **Case number**; **Advocates**; **Purpose** — what the matter is listed for; **Stage** — the case's stage; **Status** (`HRG-01`); **Orders** — opens the listing's order (`HRG-09`); **Action** — the hearing controls (`HRG-02`); **Next hearing** — where it is entered (`CLS-06`). Attendance is not a column: it is entered on the order (`PLC-02`). |
| `CLS-04` | **Columns are configurable per person.** Each person shows, hides and reorders the columns they are offered. S. no. and Case name are always shown, but can be moved. |
| `CLS-05` | **The choice is sticky per person**: it is saved for them and is what they see the next time they open the cause list. A person who has changed nothing sees a default set. |
| `CLS-06` | **What a person is offered follows their roles.** **Action**, and ending or passing over several listings at once (`HRG-07`), only to a hearing controller (`HRG-00`). Adding the same text to several orders (`CLS-12`) only to an order drafter. **Next hearing** only where the court enters the next hearing on the cause list (`PLC-04`), and only to a next hearing setter, who enters it there. Every other column is offered to everyone. |
| `CLS-07` | **Filters.** The list can be filtered on **any column where it makes sense**: **Status** (`HRG-01`) — also offered as quick choices above the list, *All* and each status with how many listings it has; **Advocate** (the advocates on the day's list); **Purpose**; **Stage**; **Orders** — no order, draft or recorded; and **Next hearing**, where it is a column (`CLS-06`) — set or not yet set. **Case name** and **Case number** are found by a **search**. S. no. and Action are not filtered. Each filter can take one or more values. Applied filters are shown as chips, each removable, with *Clear all*. A filter that matches nothing says so and offers to clear the filters; a day with nothing listed says so. |
| `CLS-08` | **Row actions.** In the **Action** column: *Start hearing* on a Scheduled or Passed over listing, *End hearing* on an Ongoing one, and a disabled *Hearing ended* on a Heard one (`HRG-02`, `HRG-03`). *Pass over* sits in a menu on the row, on Scheduled and Ongoing listings only. The **Orders** column shows whether the listing's order is a draft or recorded, and opens it once the hearing has started (`HRG-09`). |
| `CLS-09` | **Bulk selection.** A hearing controller or an order drafter can switch the list into **bulk mode**. Each row then has a checkbox, and one checkbox selects every listing the current filters show, across pages. Only selected listings the filters still show are acted on. A bar at the foot says how many are selected. |
| `CLS-10` | **Bulk actions.** One dialog applies to the selected listings: **Hearing** — *Leave as it is*, *End hearing* or *Pass over* — and, where the next hearing is entered on the cause list (`PLC-04`) and only for a next hearing setter, the **next hearing date** (with each day's load and *Not listed again*) and **purpose**, or *Leave each purpose as it is*. **Ending a Scheduled listing in bulk starts and ends it with the same press**: both are recorded, at the same time (`HRG-08`). A listing that cannot take the chosen hearing action — End needs Scheduled or Ongoing, Pass over needs Scheduled or Ongoing (`HRG-02`) — is named in the dialog and left as it is; the next hearing still applies to it. The action is applied with one press, *Apply to {n} hearings*, and what was done is reported. |
| `CLS-11` | **The case overview.** Clicking a listing opens a **case overview** over the list. Opening it changes nothing. It shows: the cause title, status, item number, case number and purpose; the **next hearing** date and purpose, to a next hearing setter where it is entered on the cause list (`PLC-04`); the **case history**, the same as the order screen's *Case history* tab (`ORD-15`): the full history, with the case's last order highlighted and a filter to show only orders; the **Data flags**, the same as the order screen's *Data flags* tab (`ORD-15`), not yet defined; and **case details** — stage, the parties with their advocates, the cheque amount and the filing date. Its foot has **View case**, which opens the case, and, for a hearing controller, the listing's hearing controls: *Start hearing* or *End hearing* as its status allows, and *Pass over* (`CLS-08`). It closes on its close button, Escape, or a click outside it. |
| `CLS-12` | **Bulk text for order drafters.** An order drafter can select listings in bulk mode and **add the same text to each one's order**, at the end of its order text. An order already sent for signing, or signed, is left out and named in the dialog. Nothing is sent for signing, and what was added is reported. |

---

## 11. Pending orders

Every order that has not yet run its course is in **one list**, for everyone on the court
side. Each person sees the other people's steps.

```
                                  ┌──▶ Awaiting signature ──┐
Drafting ──▶ sent for signing ────┤      (signer)           ├──▶ Triggered
 (drafter)                        └──▶ Order data to fill ──┘     (nothing changes)
                                         (filler)
```

| ID | Requirement |
|---|---|
| `PND-01` | Pending orders lists **every order** typed on the order screen — a hearing's or not — from its first text until its workflows are triggered. |
| `PND-02` | An order's **stage** is read from three facts: whether it has been sent for signing, whether it is signed, and whether its order data is complete. **Drafting**: not sent for signing. Once sent for signing, it sits in **Awaiting signature** until it is signed, and in **Order data to fill** until its order data is complete — in **both at once** while both are outstanding (`SND-07`). **Triggered**: signed and order data complete. |
| `PND-03` | The list is tabbed by stage. Each row shows the order's title, its case, and two columns that read the same for everyone: its **signature** and its **order data**. |
| `PND-04` | Each person opens the list on the stage that is their move: an order signer on *Awaiting signature*, an order data filler on *Order data to fill*. The count shown against Pending orders in the navigation is the number of orders at that stage. A person with no move here gets no count. |
| `PND-05` | Each row offers the one act that is the viewer's move at that stage: a draft opens back on the order screen; an order awaiting signature can be signed; an order whose data is to fill opens to fill it. |
| `PND-06` | An order signer with a DSC can select several orders awaiting signature and sign them in one action (`SGN-03`). |
| `PND-07` | An order data filler can select several hearing orders and add the same order items to each (`ITM-10`). Any further input those order items need is entered on each order one by one, and each order is opened to mark its order data complete. |
| `PND-08` | Opening a pending order shows its text read only on one side, its order data on the other, and where it stands — signature, then order data — above both. A line under it says where it stands and whose move it is. |

---

## 12. Signing

| ID | Requirement |
|---|---|
| `SGN-01` | Only a person holding **order signer** may sign. Enforced server-side. |
| `SGN-02` | An order is signed from Pending orders, once it is **sent for signing**. The confirmation says what signing will do: issue the order, and trigger its order data at once if it is complete, or once it is completed if not. |
| `SGN-03` | Several orders may be signed in one action, with a DSC (`SGN-06`). |
| `SGN-04` | Signing does not need the order data to be complete. |
| `SGN-05` | Court-side users may sign with **Aadhaar-based e-sign** or with a **DSC**. Both are offered; the signer chooses. |
| `SGN-06` | **With Aadhaar e-sign, orders are signed one at a time.** C-DAC accepts one document per authentication. Signing several orders in one action (`SGN-03`) needs a DSC. The batch-certificate approach of [`batch-esign-proposal.md`](../signing/batch-esign-proposal.md) does not apply to orders. |

---

## 13. Completing the order data and triggering

| ID | Requirement |
|---|---|
| `CMP-01` | The order data filler **marks the order data complete** when it is filled. This can be done at any time once the order exists — before or after it is signed. |
| `CMP-02` | The order data cannot be marked complete while an order item has a mandatory field unanswered (`VAR-05`). The screen names what is missing and where to set it. |
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
| `PUB-04` | The case's **A-Diary entry** for the date of the hearing is **its own text**, separate from the order text. An option, *The A-Diary text and order text are the same*, is **checked by default**: the A-Diary entry is then the order text in full, including its attendance and next hearing lines. Unchecking it lets the A-Diary text be typed separately. The option and the separate text are part of the **Order data** view, and are set by the **order data filler**. The A-Diary entry is **kept in full and never shortened** — it is the order text exactly, when the option is checked. Whether a screen shortens it while showing it is left to that screen. The A-Diary register, its editing and its signing are owned by [`a-diary.md`](a-diary.md). |
| `PUB-05` | Case stage changes are not workflows. A listener reads order events and moves the stage; stage rules are owned by [`case-lifecycle-handover.md`](case-lifecycle-handover.md). |
| `PUB-06` | A signed order cannot be edited or withdrawn. The court may pass a later order correcting it; the system records **no link** between the two, and neither order is marked as superseding or superseded. |
| `PUB-07` | The next hearing in the order data is **announced when the order is triggered** and becomes the scheduled hearing then. Before that it is held provisionally (§9.3). |

---

## 15. Pending tasks

This document creates three court-side pending tasks: **Draft order** (`DFT-05`), and **Sign
order** and **Fill order data**, created together when the order is sent for signing and
worked in parallel (`SND-07`, `SND-08`). They are a live view of the master Pending Tasks
list, which is the single source of truth and the place to edit them. Task attributes and
the status lifecycle are in [`pending-tasks-handover.md`](pending-tasks-handover.md).

```superhuman-view
name: Pending tasks (Court Side) — Order generation
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("order-generation")
```

A downloaded copy of this document is a snapshot.

---

## 16. Open questions

None currently.
