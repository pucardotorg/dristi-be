# Application Lifecycle

**Status:** v26 — 2026-09-24; v25's image was the raw Mermaid SVG, which renders blank
in Superhuman — Mermaid draws labels with `<foreignObject>` HTML, and a browser refuses
to paint `foreignObject` content when an SVG is shown as a plain `<img>`, so only the
boxes and lines survived. Re-rendered as a flat PNG (`html2canvas` against the live,
on-screen Mermaid DOM, where `foreignObject` renders fine) and swapped the image again;
updated the embedded URL to match. v25 — 2026-09-24; Superhuman doesn't render Mermaid —
it showed v24's diagram as plain code text. Rendered it once (headless Mermaid, Chrome)
and swapped the fenced diagram for the rendered image, hosted at Superhuman's own
permanent blob URL; pulling that back into this file so the local source matches the
synced page instead of drifting from it. v24 — 2026-09-24; the v23 diagram rendered as a crossing mess in Superhuman —
dropped the shared end-marker every terminal status pointed at (five long lines
converging on one dot) and turned the two self-loops (`ALC-05`, `ALC-15`) into notes on
their own state instead of arrows that double back, since neither changes the status
anyway. v23 — 2026-09-24; added a state diagram to **The workflow** — the same
statuses and transitions as the table below it, drawn out, so the shape of the flow reads
at a glance; the table stays the place for exact actor lists and `ALC-`/`Q-` references.
v22 — 2026-09-24; **the decision points** opened straight into the
magistrate's Review application task, with no step for how the application came to
exist — added a new **step 1, Raising the application** (Draft → Sign → Pay, pointing
back at "The workflow"), and renumbered the rest (steps 2–7, sub-letters 3a–c/4a–c)
accordingly. v21 — 2026-09-24; added an orienting paragraph to the top of **The decision
points** — the two gates (onboard-or-not, then accept-or-reject) an application passes
through, stated before the step-by-step detail — and glossed **onboarding** in plain
language at its first real use (now 3a). Both were missing context for a reader new to
the flow. v20 — 2026-09-23; added a **Linked records** section with live views of the
Pending Tasks master tables, filtered to this document — **Review application** and
**Decide application** (Court Side), **File objection** (Citizen-Side), tagged
`application-lifecycle` there. v19 — 2026-09-23; turned **Fields by application type** into one table per
type — field, field type, validations, notes — instead of a bullet list. Flagged two
things that look like spec errors while doing it: Case Transfer's "Select Requested Court"
is marked system-filled when it reads like filer input, and Production of Documents'
"Reason for submission of document" carries file-upload validations that look copied from
the field above it. v18 — 2026-09-23; added **Fields by application type**, pulled from the
functional specs, with fields common to every type (court name, case name, CNR/filing
number, statute/section, who raised it, comments) filtered out — those live once in
"Application attributes," not repeated per type. Added **Template** as an application
attribute — one per type, full spec to come in a separate, not-yet-written templates
document. v17 — 2026-09-23; moved **Users and actions** up, right after "The workflow"
— it's foundational context, not an appendix. Turned its table into a bulleted list per
user; the dot-separated single-line cells were hard to scan. Confirmed `Q-6`: Objection
goes through the same Draft → Sign → Pay steps as every other type — it only diverges
*after* payment, ending at `Submitted` instead of entering `Pending Review`. Closed `Q-6`.
v16 — 2026-09-23; moved the status table to the front and renamed it **"The workflow"** —
it's the fastest way to see the whole shape of the thing. Renamed what was "The workflow"
to **"The decision points"** and restructured it as a numbered sequence (1 → 6, with
sub-choices lettered under the step that offers them), since the old two-table layout read
as flat and parallel when it wasn't. Removed comparisons to the retired source documents
throughout — this file now stands on its own. Dropped a stale bullet from "What looks
missing" (no "Objection" application type) — resolved back in v13. v15 — 2026-09-23; added
a Users and actions section — court-side actions split along `ALC-22` (system action vs.
order); made explicit that `ALC-17`'s visibility gate is for the other party only, not
court staff, who can always see a submitted application. v14 — 2026-09-23; added a new
terminal status, **Submitted**, specific to Objection — it's never separately accepted or
rejected, so it ends there rather than entering `Pending Review` like every other type.
v13 — 2026-09-23; added the application types table, with **Objection** added as a new,
seventeenth type — raised only off another application's File objection task, never
freestanding. Answers half of `Q-6` (it's a type now); narrowed the rest to whether it
carries the usual Draft → Sign → Pay lifecycle. v12 — 2026-09-23; closed `Q-7` without
adding anything — whether "set a date" has been used once is derived by comparing the
Review application task's due date to its default (`ALC-03`), not stored. v11 —
2026-09-23; added an application attributes table — two new statuses (`Pending Decision`,
`Dismissed`), a second number (temporary identifier vs. application number), a widened
`Linked Order`, and `Objections Invited`. Surfaced a gap in doing so: no "Objection"
application type exists despite `Objection (Linked Application)` implying one (`Q-6`).
v10 — 2026-09-23; resolved five open questions: silence on an objection has no
consequence, and the deadline is exactly midnight the day before the decision date
(`ALC-13`, was `Q-1`/`Q-2`); "the other party" is the opposing side, one objection only
(`ALC-24`, was `Q-3`); per-type decide-now-vs-must-object configuration is deferred, with
every type defaulting to "on a date" + notify checked in the meantime (`ALC-25`, was
`Q-4`); system actions (onboard, set/re-date) are magistrate-only, but any order —
including dismissal — may be drafted by the bench clerk or typist, magistrate signs only
(`ALC-22`, was `Q-6`). Added: the magistrate sees filing date and objection status (plus
the objection itself, if any) whenever they open an application (`ALC-23`); the Decide
application task is visible to the bench clerk/typist too, once onboarded (`ALC-21`).
Reworded `Q-5` in plainer terms — the previous phrasing wasn't landing. v9 — 2026-09-23;
collapsed the "first time round" / "rescheduled" split back into a single
**Pending Review** status — offering "set a date" once and then promoting "dismiss" is a
UI/task-history rule, not a second application status (`ALC-05`, `ALC-19`, `ALC-20`).
v8 — 2026-09-23; added an end-to-end status table covering the whole flow, filer through
magistrate — surfaced one gap, what the escape hatch (`ALC-18`) resolves to (`Q-7`).
v7 — 2026-09-23; reverted a mis-sequencing from v6 — **onboarding is the usual,
first-time-round path**, not something gated behind a reschedule; the secondary path
("set a date") is for when the magistrate expects to dismiss but not immediately,
typically waiting for the hearing; a hidden "dismiss right there" sits alongside both from
the start (`ALC-04`, `ALC-05`, `ALC-19`). Once "set a date" has run its course, the
returning task's choices become **onboard or dismiss**, with dismiss now promoted out of
hiding, and no further deferral offered (`ALC-20`, resolves `Q-7`). Softened the "one
action" framing from v5: onboarding and deciding what happens next are still answered
together, but the order itself doesn't have to be signed in the same breath — a
**Decide application** pending task backs up both "deal with it now" and "deal with it on
a date," closing only once an order is actually signed, so an abandoned draft doesn't
quietly lose the application (`ALC-21`). Added a pointer to where application types and
their per-type behaviour live — not yet folded into this file (see "Application types,"
below). v6 — 2026-09-23; the Review application task's choices now change once it's been
rescheduled — first time round the expected path is **set a date**, with a hidden,
rarely-used **dismiss right there**; only after that reschedule does **onboard** appear,
paired with **dismiss** (`ALC-05`, `ALC-19`, `ALC-20`) — this resolves `Q-5` (dismissal was
missing from the flow). Rewrote the date-suggestion rule and the escape hatch in plain
terms, since both read unclearly in v5. v5 — 2026-09-23; onboarding and deciding what
happens next are **one action**, not two — an application is never left onboarded with
nothing decided (`ALC-04`, `ALC-07`); dropped "regardless of filing time" from the
Review-application due date, since nothing here establishes why time of filing would
matter — noted instead as a possible future tightening to same-day (`ALC-03`). v4 —
2026-09-23; the temporary identifier is shown to the user after all — only the "never
cited in an order" restriction stands (`ALC-02`); the workflow diagram is redrawn as two
stages instead of one nested tree, since the branching in v3's version wasn't readable.
v3 — 2026-09-23; the pre-onboarding second action re-dates the **Review application** task
instead of committing to a future dismissal, leaving the fate of an outright dismiss
action open (`ALC-05`, `Q-5`); onboarding and setting the later decision date are
magistrate-only (`ALC-04`, `ALC-09`, `Q-7`); the Review-application due date is always the
next working day, regardless of filing time (`ALC-03`); visibility resolved — invisible to
the other party pre-onboarding, visible after regardless of the objections choice
(`ALC-17`); the no-next-hearing-date case resolved — no default, set manually (`ALC-10`);
the objection window now closes **before** the decision date, not on it (`ALC-13`); the
two numbers swap names — **temporary identifier** at filing, **application number** at
onboarding — pending propagation to `order-generation.md` and `case-numbers.md` (`Q-6`).
v2 — 2026-09-18; compressed to the workflow only, with a note on the value of the
take-on-file step. v1 — 2026-09-18; first cut.

The life of an application from submission to disposal. Order drafting and signing are
owned by [`order-generation.md`](order-generation.md), pending task attributes by
[`pending-tasks-handover.md`](pending-tasks-handover.md), dates by
[`scheduling-product.md`](../scheduling/scheduling-product.md), and number formats by
[`case-numbers.md`](case-numbers.md).

---

## The workflow

Every status the application passes through, filer side through magistrate side, drawn
out first, then in one table.

![Application lifecycle state diagram: Draft through Pending Signature, Pending Payment, Pending Review and Pending Decision to Accepted, Rejected, Dismissed, Submitted or Expired](https://codahosted.io/docs/KtL_rwN6Qw/blobs/bl-mU4WA9f9C5/bc11f1388ca64f3444395bbea36635929c423c3c9b0960a2e487ccfd0fd440e172372fbb2a53668bdb2328851d59631aff09804a71bba74d7545e184260413b6b3a723d97de7caddc5da9a43bb6ec6f993e4c3e6475d87df5072a6cdb22e922bc2015ce1)

Accepted, Rejected, Dismissed, Submitted and Expired have no arrow leaving them — that's what makes them
terminal. The two magistrate actions that don't change status (`ALC-05`, `ALC-20`) are shown as notes rather
than loops, so they don't have to double back across the diagram.

| Initial status | Action | Actor | New status | Ref |
|---|---|---|---|---|
| *(none)* | Create | Advocate/PiP (or a clerk/junior advocate drafting on their behalf) | Draft | |
| Draft | Proceed to sign | Advocate/PiP | Pending Signature | |
| Pending Signature | Sign | Advocate/PiP | Pending Payment | |
| Pending Payment | Pay | Advocate/PiP, litigant, or PoA-holder | Pending Review | `ALC-02` |
| Pending Payment — **Objection only** | Pay | Advocate/PiP, litigant, or PoA-holder on the objecting side | **Submitted** — terminal; no `Pending Review` | `ALC-24` |
| Draft / Pending Signature / Pending Payment | Expire | System | Expired | |
| Pending Review | Onboard application | Magistrate | Pending Decision | `ALC-04` |
| Pending Review | Set a date *(usable once — `ALC-05`)* | Magistrate | Pending Review *(unchanged)* | `ALC-05` |
| Pending Review | Dismiss application | Magistrate | Dismissed | `ALC-19` |
| Pending Decision | Accept, having dealt with it now or on a date | Magistrate | Accepted — the application type's workflow triggers | `ALC-08`, `ALC-09`, `ALC-16` |
| Pending Decision | Reject, having dealt with it now or on a date | Magistrate | Rejected — no workflow | `ALC-16` |
| Pending Decision | Move the decision to another date | Magistrate | Pending Decision *(unchanged)* | `ALC-15` |

**Dismissed** and **Rejected** are two distinct terminal statuses, not one: dismissal
happens before onboarding — no application number yet, no accept/reject order (`ALC-19`)
— while rejection only happens after (`ALC-16`).

**Submitted** is a third, and it's specific to **Objection**: unlike every other type, an
objection is never separately accepted or rejected — it's read alongside the application
it's raised against (`ALC-14`, `ALC-23`) and just sits, `Submitted`, once it's in. It never
enters `Pending Review`, `Pending Decision`, or any of `Accepted`/`Rejected`/`Dismissed`.
It's raised the same way as every other type — draft, sign, pay — and just ends earlier.

Left out on purpose: the **File objection** task the other party gets under "deal with it
on a date" (`ALC-12`) isn't a status of *this* application — it's a task on a different
person entirely, so it doesn't belong in this application's own status column.

---

## Users and actions

- **Advocate/PiP**
  - Create a draft
  - Sign own drafts and drafts by associated clerks/junior advocates
  - Pay for own applications and those associated clerks/junior advocates created
  - View own and associated drafts
  - View all submitted applications on the case, subject to `ALC-17` if on the opposing side
  - File an objection, if invited (`ALC-12`)
- **Clerk and Junior Advocate**
  - Create drafts
  - View own drafts and drafts created by associated advocates
  - Pay for own applications and those associated advocates created
  - View all submitted applications, same visibility gate as their advocate (`ALC-17`)
- **Litigant**
  - Pay for all applications submitted on their behalf
  - View all submitted applications, subject to `ALC-17` if on the opposing side
- **PoA-Holder**
  - Pay for all applications submitted on their litigant's behalf
  - View all submitted applications, subject to `ALC-17`
- **Magistrate**
  - View all submitted applications, **including before onboarding** — `ALC-17`'s
    visibility gate is for the other party, not court staff
  - Onboard an application, or re-date the Review application task (system actions,
    magistrate-only, `ALC-22`)
  - Set or move the decision date (`ALC-09`, `ALC-15`) — also a system action,
    magistrate-only
  - Draft or sign a dismissal, or an accept/reject order (only the magistrate signs,
    `ALC-22`)
  - Sees key metadata and any objection when opening an application (`ALC-23`)
- **Bench Clerk and Typist**
  - View all submitted applications, including before onboarding, same as the magistrate
  - Draft a dismissal or an accept/reject order — cannot sign it (`ALC-22`)
  - Cannot onboard, re-date, or set/move a decision date — those are system actions
    restricted to the magistrate (`ALC-22`)

The **objection-filing** action on Advocate/PiP is signed and paid for like any other
application type — confirmed, no longer open.

---

## The decision points

Every application goes through the same two gates, in that order. **The first gate is
whether the magistrate takes it onto the court's file at all** — the term for this
throughout is **onboarding**. It happens straightaway (3a) in the usual case, or after
being deferred once (3b); dismissing the application (3c) is the way out of this gate
without ever onboarding it. **The second gate, reached only once onboarded, is whether
the magistrate accepts or rejects the application** (step 6) — dealt with right away or
on a later date, with the other party sometimes given a chance to object first. Steps
1–7 below walk through both gates in order, starting with how the application comes to
exist in the first place.

**1. Raising the application.** An advocate/PiP — or a clerk/junior advocate drafting on
their behalf — creates a draft, it's signed, and it's paid for: the Draft → Pending
Signature → Pending Payment progression already laid out in "The workflow," above. Only
once it's signed and paid does it count as filed, which is where step 2 picks up.

**2. Filing.** Submission is what step 1 ends with. The application gets a temporary
identifier (can be shown to the user, but never cited in an order), and a
**Review application** task is raised for the magistrate, due the next working day.
(Filing time isn't a factor in this version — a later version may tighten this to the
same day, for applications filed during working hours on a working day.)

**3. The Review application task offers the magistrate two things:**

- **3a. Onboard the application** — the usual path. This is what officially takes the
  application onto the court's file: a system action that allots the real application
  number, no order, no signature, takes effect at once. Continues straight to step 4, as
  part of the same action.
- **3b. Set a date** — the secondary path, used when the magistrate expects to dismiss the
  application but not immediately, typically waiting for the hearing. **Usable once**:
  re-dates this same task to a later date (step 7 covers how the date is suggested).
  Nothing about the application is decided yet, and it isn't dismissed. When that date
  comes round, the task is back at step 3 — except this time "set a date" isn't offered
  again, and dismissing (below) is shown up front rather than tucked away.

Sitting alongside both, the whole time, is one more option that stays out of the way
until "set a date" has been used once:

- **3c. Dismiss it right there** — an order, effective on the magistrate's signature. This
  ends the application: `Dismissed`.

**4. Reached only via 3a.** The other party can now see the application. As part of the
same action as onboarding, the magistrate also decides what happens to it:

- **4a. Deal with it now** — opens the order screen right away.
- **4b. Deal with it on a date** — sets a date (step 7) and decides whether to invite
  objections (checked by default). Checked → the other party gets a **File objection**
  task at once, due before the decision date (step 6 covers what "before" means exactly).
  Unchecked → no task, but the other party can still see the application either way.
- **4c. Open the order generation screen directly** — skips 4a and 4b entirely. The
  magistrate does something else there — e.g. reschedule a hearing — with no connection to
  this application at all.

**5. Whichever of 4a or 4b was picked, a Decide application task backs it up** — due
immediately for 4a, due on the chosen date for 4b. Onboarding is instant, but actually
drafting and signing an order isn't, so this task is what stops the application from being
lost if the magistrate opens the order screen and abandons the draft. It closes only once
an accept/reject order is signed.

**6. The decision itself**, whenever it happens (right away for 4a, on the date for 4b):
the magistrate allows or rejects the application, reading the application, its documents,
and any objection filed against it, all from the same screen.

- **Allow** → ends the application: `Accepted`, and the application type's own workflow
  now runs.
- **Reject** → ends the application: `Rejected`, no workflow.
- The magistrate may instead **move the decision to another date** — the Decide
  application task and any File objection task re-date together, and step 6 waits for the
  new date.
- An objection is due by **midnight the day before** whatever date is currently set — e.g.
  a decision on the 21st puts the deadline at the end of the 20th. If none is filed by
  then, it simply doesn't matter: the magistrate proceeds regardless.

**7. Suggesting a date** (used by 3b and 4b): the system pre-fills the case's next hearing
date, if the case has one on record. If it doesn't, there's nothing to pre-fill, and the
magistrate sets one manually.

| ID | Requirement |
|---|---|
| `ALC-01` | Submitting an application requires the signature of a filer entitled to sign and, where the type carries a fee, payment. |
| `ALC-02` | On submission the application is allotted a **temporary identifier**. It can be shown to the user, but it is never cited in an order or any other document. The court-facing **application number** is allotted only on being onboarded (`ALC-04`). *(This reverses which of the two numbers `order-generation.md`'s `APL-02`/`APL-03` and `case-numbers.md`'s rows 6–7 currently name — see `Q-5`.)* |
| `ALC-03` | On submission the system raises a **Review application** task for the magistrate, due the next working day. Filing time is not a factor in this version; a later version may bring the due date forward to the same day when the application is filed during working hours on a working day. |
| `ALC-04` | **Onboarding** an application is a system action: it allots the application number, nothing is written into any order, no signature is involved, it takes effect at once, and only the **magistrate** may do it (a system action, `ALC-22`). Available for as long as the **Review application** task is open — the usual path (`ALC-05` is the alternative). The application's status is **Pending Review** the whole time this task is open; nothing here is a separate status. |
| `ALC-05` | **Set a date** — the secondary path, used when the magistrate expects to dismiss the application but not immediately, typically waiting for the hearing — re-dates the **Review application** task itself; only the **magistrate** does this (a system action, `ALC-22`). Nothing about the application is decided and nothing is dismissed by choosing it. **Usable once per application**: this is a UI restriction, enforced off a flag/count kept on the task, not a second application status. |
| `ALC-06` | The date for `ALC-05` follows the rule in "Suggesting a date" (`ALC-10`). |
| `ALC-07` | Onboarding carries this question with it: **pass the order now, or deal with it on a date?** (or open the order generation screen directly, `ALC-18`) — answered alongside onboarding. Unlike onboarding itself, answering it doesn't require the order to be signed right away (`ALC-21`). |
| `ALC-08` | **Now** — the order screen opens with the application in context; any of the magistrate, the bench clerk or the typist may draft the accept/reject order there, but only the **magistrate** signs it (an order, `ALC-22`). |
| `ALC-09` | **On a date** — the magistrate (only) sets the date on which it will deal with the application (a system action, `ALC-22`), and the system raises a **Decide application** task due on that date. |
| `ALC-10` | The system **suggests** a date by pre-filling the case's next hearing date, if it has one on record; if it doesn't, there is nothing to pre-fill and the magistrate sets the date manually. Later, when application work runs in dedicated asynchronous slots, the suggestion becomes the next such slot. |
| `ALC-11` | With the date, the magistrate answers one more question: **does the other party need to file objections?** — checked by default. Asked only on this branch; an application decided at once gives nobody an opportunity to object. Until application types carry their own configuration, this defaults to checked for every type (`ALC-25`). |
| `ALC-12` | **Checked** — the other party is told plainly that it must file an objection and by when, and a **File objection** task is raised on it at once. **Unchecked** — no task is raised, but the other party can still see the application regardless: visibility follows onboarding (`ALC-17`), not this choice. |
| `ALC-13` | The objection is due by **midnight the day before** the date the court has said it will deal with the application — e.g. a decision set for the 21st puts the objection deadline at the end of the 20th — and is raised at once, when the magistrate sets the date. If no objection is filed by then, it simply doesn't matter: the magistrate proceeds with the decision as scheduled, and nothing is recorded or delayed on account of the silence. |
| `ALC-14` | On the date, the court allows or rejects the application, reading the application, its documents and any objection filed against it from the same screen (`APL-07`, `APL-11`). |
| `ALC-15` | The court may instead **move the decision to another date**. The new date replaces the old one; both the court's task and the objection task (if raised) are re-dated to it, the objection task staying due before the new date (`ALC-13`). |
| `ALC-16` | On signature of an order **allowing** the application, the workflow that belongs to that **application type** is triggered (`APL-08`). **Rejecting** it does not trigger that workflow. |
| `ALC-17` | The application is **invisible to the other party until it is onboarded** (`ALC-04`). From onboarding onward it is visible regardless of whether objections are invited (`ALC-12`). |
| `ALC-18` | The magistrate may open the **order generation screen** directly instead of answering "deal with it now" or "on a date" — e.g. to move a hearing at the same time. This has no connection to the application at all: it's the magistrate doing something unrelated on that screen, so it leaves the application's status and pending task untouched. |
| `ALC-19` | **Dismissing an application** is an order item, effective on the magistrate's signature, worded per [`order-generation.md`](order-generation.md) `APL-04`–`APL-06`. Any of the magistrate, the bench clerk or the typist may draft it; only the magistrate signs (an order, `ALC-22`). It's available on the **Review application** task the whole time it's open, not gated behind anything — the UI just tucks it away while "set a date" (`ALC-05`) is still available, and surfaces it plainly once that's been used, so it reads as the natural next step. |
| `ALC-20` | This whole restriction — "set a date" offered once, then dismiss promoted — is a **UI/task-history rule, not an application status**. The stored status is `Pending Review` throughout `ALC-04`–`ALC-19`; there is no separate "rescheduled" status behind it. |
| `ALC-21` | Choosing "deal with it now" (`ALC-08`) or "deal with it on a date" (`ALC-09`) both raise a **Decide application** task — due immediately for the former, due on the set date for the latter — closing only once an accept/reject order is signed. This covers the gap between the magistrate's choice and actually drafting the order. Once the application is onboarded, this task is visible to other users too — the bench clerk or typist, who may be the one drafting the order (`ALC-22`) — not just the magistrate. |
| `ALC-22` | **General rule on who may do what:** a **system action** — onboarding (`ALC-04`), setting or re-dating a date (`ALC-05`, `ALC-09`) — is restricted to the **magistrate**. An **order** — dismissing (`ALC-19`), accepting or rejecting (`ALC-08`) — may be **drafted** by the bench clerk or typist as well as the magistrate; only the **magistrate signs** it, per [`order-generation.md`](order-generation.md)'s standing rule. |
| `ALC-23` | **Whenever the magistrate opens the application**, key metadata is shown alongside it: when it was filed, and whether an objection has been filed. If one has been filed, the objection itself is shown too — not just the fact that one exists. |
| `ALC-24` | **"The other party"**, throughout this file, means the opposing **side** — anyone on the complainant side, if the application was raised by anyone on the accused side, or vice versa — not a specific named individual. Only **one** objection may be raised against a given application, on behalf of that side. |
| `ALC-25` | Until application types carry their own configuration for this (see "Application types"), every type is treated the same: assumed to go through "deal with it on a date" (`ALC-09`) with the notify-for-objections checkbox (`ALC-11`) checked by default. The magistrate can still deselect the checkbox or choose "deal with it now" (`ALC-08`) by hand — this is a placeholder default, not a restriction on what the magistrate may do. |

---

## Application attributes

| Attribute | Description |
|---|---|
| Temporary Identifier | Assigned at filing (`ALC-02`). Can be shown to the user, but never cited in an order or any other document. |
| Application Number | Assigned at onboarding, not at filing (`ALC-04`). This is the number a court recognises the application by. |
| Application Type | The type of application. |
| Template | The print/PDF template this application renders into. One per application type — full spec lives in a separate templates document, not yet written. |
| Date Created | The date the draft was originally created. |
| Date Submitted | The date the application was formally submitted (signed and paid). |
| Date Onboarded | The date the application number was allotted (`ALC-04`). |
| Application Raised By | The advocate/PiP who signed the application. |
| Application Raised On Behalf Of | The litigant on whose behalf the application was raised. |
| Status | **Draft · Pending Signature · Pending Payment · Pending Review · Pending Decision · Accepted · Rejected · Dismissed · Submitted · Expired.** `Pending Decision` sits between onboarding and the accept/reject order; `Dismissed` is a disposal distinct from `Rejected`; `Submitted` is Objection's own terminal status — never separately accepted or rejected — see "The workflow". |
| Objections Invited | Whether the notify-for-objections checkbox was checked when the decision date was set (`ALC-11`). Yes/no. |
| Linked Order | The order accepting, rejecting, or dismissing the application. |
| Objection (Linked Application) | The objection raised against this application, if any — at most **one** (`ALC-24`), not a list. |
| Objection To (Linked Application) | For an objection, the application it was raised against. |

**Left out on purpose:** whether "set a date" (`ALC-05`) has already been used once —
`ALC-20` needs nothing stored for this. It's derived by comparing the **Review
application** task's current due date to what it would be by default (the next working
day after Date Submitted, `ALC-03`): equal means unused, later means it's been rescheduled
already. (Edge case: a magistrate who deliberately reschedules to that exact default date
would read as unused — accepted as vanishingly unlikely rather than worth a stored flag.)

### What looks missing

- **Decision Date isn't in this table on purpose** — it's just the **Decide application**
  task's due date (`ALC-09`), not a separate stored field. Flagging in case you'd rather
  have it as its own attribute (e.g. for reporting without joining to the task).
- **Who onboarded / who dismissed / who decided** isn't listed separately — each is
  recoverable from `Linked Order`'s own signer, or from `Date Onboarded` plus whoever was
  logged in, so it didn't seem to need its own field. Worth a second look if audit needs
  more than that.

---

## Application types

Each type's own fields are in "Fields by application type," below.

| Type | Available when | Workflow attached | One-line description |
|---|---|---|---|
| Bail — Bail Bond | Only for the accused | On acceptance, the magistrate can request a bail bond — a draft is created from the application. | Request bail for an accused, with supporting details and documents. |
| Edit Litigant Details | Only for the complainant | On acceptance, the requested litigant details are updated. | Request corrections to a litigant's details in the case. |
| Case Settlement | Always | — | Request court recognition of a settlement between the parties. |
| Case Transfer | Always | — | Request transfer of the case to another court. |
| Case Withdrawal | Always | — | Request withdrawal of the case. |
| Delay Condonation | Only for the complainant | — | Request condonation of a delay in filing or complying. |
| Generic | Always | — | Submit a general application where no dedicated type applies. |
| Advance / Prepone | Only when a hearing is scheduled in the case | On acceptance, the magistrate selects a new hearing date and the hearing is rescheduled. | Request an earlier date for a scheduled hearing. |
| Postpone | Only when a hearing is scheduled in the case | On acceptance, the magistrate selects a new hearing date and the hearing is rescheduled. | Request a later date for a scheduled hearing. |
| PoA Change | Always | On acceptance, the PoA holder's rights transfer to the person named in the application. | Request an update to the appointed power-of-attorney holder. |
| Production of Documents | Always | On acceptance, the attached documents are added to the case file. | Submit documents for the court to consider in the case. |
| Addition of Witness | Always | On acceptance, the witness is added to the case. | Request the addition of a witness to the case. |
| Certified Copy | Anyone — even without logging in, or without being a party to the case | On acceptance, a certified true copy is generated. | Request a certified true copy of application or case materials. |
| Warrant by Hand — *new* | *?* | *?* | Request issuance or handling of a warrant by hand. |
| Absent Application — *new* | *?* | *?* | Notify the court of a party's absence and seek related directions. |
| Reopen Evidence — *new* | *?* | *?* | Request that evidence be reopened for further examination or submission. |
| **Objection** | Only against another application, raised via that application's **File objection** task (`ALC-12`) — not independently started by a filer | No accept/reject of its own: ends at `Submitted`, not `Pending Review` — read alongside the original application when the magistrate decides it (`ALC-14`, `ALC-23`), and becomes that application's `Objection (Linked Application)` (`ALC-24`) | State an objection to another party's application. |

One thing not yet reconciled: hearing-linked types (Advance/Prepone, Postpone) may need an
**auto-expiry** if their hearing passes or is moved before the magistrate acts on the
application — untouched by `ALC-04` onward so far. Until real per-type configuration of
"decide now vs. must offer objection" exists, `ALC-25` is the placeholder: every type
behaves the same.

Objection goes through the same Draft → Sign → Pay steps as every other type — confirmed
(`Q-6`, now closed). It only diverges after payment: `Submitted`, not `Pending Review`.

---

## Fields by application type

Each type's own fields, from the functional specs — with the fields every application
already carries regardless of type left out (application type, court name, case name,
CNR/filing number, statute/section, who raised it and on whose behalf, and a closing
comments box). Those are common to all of them, not specific to any one type, so they
don't belong here — see "Application attributes" for those.

"Not documented" and "nothing beyond the common fields" are different, and both appear
below: the first means no type-specific fields were ever written down for that type; the
second (Case Settlement) means they were, and every one of them turned out to be common.

### Bail — Bail Bond

| Field | Field type | Validations | Notes |
|---|---|---|---|
| Reason for Application | Textbox | — | Shown, editable |
| Prayer | Textbox | — | Shown, editable |
| List of supporting Documents (add as many) | Selection from document subtype; enter doc title (tax receipts, property tax record, others) | — | Shown, editable |

### Edit Litigant Details

Not documented.

### Case Settlement

Nothing beyond the common fields.

### Case Transfer

| Field | Field type | Validations | Notes |
|---|---|---|---|
| Select Requested Court | System filled | — | Shown *(reads like a spec error — a court the filer is requesting sounds like it should be filer-selected, not system-filled)* |
| Grounds for Seeking transfer | Input, alphanumeric text | — | Shown |

### Case Withdrawal

| Field | Field type | Validations | Notes |
|---|---|---|---|
| Reason for Withdrawal | Dropdown, single select | — | Shown |

### Delay Condonation

| Field | Field type | Validations | Notes |
|---|---|---|---|
| Reasons for Delay | Input, alphanumeric text | — | Shown |
| List of supporting Documents (add as many) | Selection from document type; enter doc title | — | Shown |

### Generic

| Field | Field type | Validations | Notes |
|---|---|---|---|
| Application Title | Input, alphanumeric text | — | Shown |
| Details | Input, alphanumeric text | — | Shown |
| List of supporting Documents (add as many) | Selection from document type; enter doc title | PDF/JPEG, file size limit | Shown |

### Advance (Prepone) / Postpone

Same fields for both — nothing in the spec currently distinguishes an earlier-date
request from a later-date one beyond whatever the filer writes into "Reason for
Rescheduling."

| Field | Field type | Validations | Notes |
|---|---|---|---|
| Initial Hearing Date | System filled | — | Shown, read-only |
| Reason for Rescheduling | Dropdown, single select | — | Shown |
| Date from which hearing can be scheduled | Date picker | — | Shown |

### PoA Change

Not documented.

### Production of Documents

| Field | Field type | Validations | Notes |
|---|---|---|---|
| List of documents | Input, add multiple documents | PDF/JPEG, file size limit | Shown |
| Reason for submission of document | Input, add multiple documents *(likely a copy-paste error in the spec — a "reason" field taking file uploads doesn't make sense)* | PDF/JPEG, file size limit | Shown |

### Addition of Witness

Not documented.

### Certified Copy

Not documented.

### Warrant by Hand / Absent Application / Reopen Evidence

New types — no fields specified yet.

### Objection

Not yet specified; it isn't in the original catalog this section is drawn from.

---

## A note on onboarding

**Onboarding an application carries no value of its own.** Nothing about the application
changes, nothing is decided, and nothing is written — it allots a number. As a step in its
own right it is one more touchpoint on the magistrate.

What the step is worth keeping for, for now, is the two answers attached to it: **whether
the other party has to respond**, and **when the court will deal with the application** —
which is what tells everyone involved where the application stands and when to expect an
answer.

In the future the step can go. The system assigns the date itself, on the same logic it
already uses to suggest one, and whether the other party must respond follows from the
application type. The magistrate is then left with the decision alone.

---

## Linked records

Live views of the master tables, filtered to this document. Each master table is the
single source of truth and the place to edit its rows; anything tagged
`application-lifecycle` there appears here automatically. A downloaded copy of this
document is a snapshot.

### Pending tasks (Court Side)

```superhuman-view
name: Pending tasks (Court Side) — Application Lifecycle
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("application-lifecycle")
```

### Pending tasks (Citizen-Side)

```superhuman-view
name: Pending tasks (Citizen-Side) — Application Lifecycle
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("application-lifecycle")
```

---

## Open questions

| # | Question | Blocking? |
|---|---|---|
| `Q-5` | This file calls the number assigned **at filing** the "temporary identifier," and the number assigned **at onboarding** the "application number." Two other files that also talk about these numbers use the **opposite** pairing: `order-generation.md` (`APL-02`, `APL-03`) calls the at-filing one the "application number," and `case-numbers.md` (rows 6–7) calls the at-onboarding one the "CMP number." Should those two files be updated to match the naming here, or does this file just stay different from them on purpose? | Yes |
