# Application Lifecycle

**Status:** v31 — 2026-10-11; closed `Q-9`: an application in Pending Signature can be moved back to Draft and edited there, by anyone who could have created and edited the draft (`ALC-31`, new). Closed `Q-10`: the signer may use any signing mode enabled for the deployment. `ALC-28` tightened: only the person selected in Raised by signs, not any advocate or PiP on the case. v30 — 2026-10-11; **no setting a date before onboarding.** Review (step 2) now offers only Onboard or Dismiss; a date is set only after onboarding (3b). `ALC-05`, `ALC-06` and `ALC-20` are withdrawn, and the "set a date once, then dismiss promoted" rule goes with them, along with the note on deriving whether it had been used. v29 — 2026-10-11; rewrote the workflow as six linear steps — **Filing, Review, Onboarding, Objections, Decision, After the decision** — each with its own prose and its own requirements. "The workflow" now opens with the step list and a one-row-per-step table; "The decision points" is gone, its content moved into the steps; the full status table moves to the end as **Every status change**. Filing is written out in full: who drafts, signs and pays, how the status moves, and steps 1.1–1.8. New requirements `ALC-26`–`ALC-30` (types offered, resumable drafts, who signs, who pays, and expiry — only Advance / Prepone and Postpone expire, when their hearing passes; an unsubmitted application never does); every existing `ALC-` ID is kept. New open questions `Q-8`–`Q-12`. v28 — 2026-10-11; **Fields by application type**: every application can now carry optional, named supporting documents. Case Settlement gets a reason for settlement. Case Transfer's requested court and Case Withdrawal's reason for withdrawal are now text, not dropdowns. Advance / Postpone loses Prayer. PoA Change: Prayer is replaced by a reason for change; litigants appointing the applicant are a multi-select, and an existing PoA is a property of the litigant, not a field; the PoA instruments become one authorization document per litigant. Absent Application gets a reason for absence, Reopen Evidence a reason for reopening and Objection a reason for objection, all text. Bail's supporting documents are replaced by a proof of solvency, one per surety; other documents are optional, under Supporting documents. Edit Litigant Details: Complainant type / Accused type is now Litigant type; CIN or PAN is optional with no format validation; an accused institution's representatives are no longer edited with the institution, but as individual accused; an individual accused's name allows special characters, and the individual accused gains an optional Designation. v27 — 2026-10-09; rebuilt **Fields by application type** from the
application print templates — each type now lists its template, its fields,
who fills each (filer or system) and its field type. Updated **Application types**: renamed
"Bail — Bail Bond" to Bail (the bail bond workflow on acceptance stays); Certified Copy removed; Warrant by
Hand, Absent Application and Reopen Evidence have no workflow attached, and Warrant by Hand
and Absent Application are open to anyone. Added **Every application** (Raised by and
Litigant, with their preselection rules) and Bail's type of bail — cash or surety, a bail
amount for both, and for surety the number of sureties and each surety's details. Each
field table carries an Associated logic column. Bail's surety details are name,
father's / mother's name, phone (mandatory), email (optional), address and ID proof.
**Edit Litigant Details** now lists only the editable fields — the e-filing litigant
fields for complainant or accused, individual or institution, each prefilled with the
litigant's current details. Edit Litigant Details is one application for editing any
litigant's details, with a control on the workflow setting who can raise it and whose
details they can edit. Addition of Witness uses the e-filing witness fields. Warrant by
Hand has the accused and the delivery address, prefilled from the case file. Edit
Litigant Details can change a litigant between individual and institution. v26 — 2026-09-24; v25's image was the raw Mermaid SVG, which renders blank
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

Every application moves through the same steps, in the same order:

1. **Filing** — the filer side drafts, signs and pays for the application.
2. **Review** — the magistrate decides whether to take it onto the court's file.
3. **Onboarding** — it gets its number, and the magistrate decides when to deal with it.
4. **Objections** — if invited, the other party may file one objection.
5. **Decision** — the magistrate accepts or rejects it, by order.
6. **After the decision** — on acceptance, the application type's own workflow runs.

An application can leave the flow early in two ways only: at review, the magistrate can
**dismiss** it (step 2); and an Advance / Prepone or Postpone application **expires** if
its hearing passes before the application is dealt with ("Expiry", below). Step 4
happens only when the magistrate chooses to deal with the application on a date and
invites objections.

| Step | What happens | Who acts | Status when the step ends |
|---|---|---|---|
| 1. Filing | Choose the type, fill in the form, sign, pay. | Advocate/PiP; a clerk or junior advocate may draft; the litigant or PoA-holder may pay | Pending Review (Objection: Submitted) |
| 2. Review | Onboard or dismiss. | Magistrate | Pending Decision once onboarded, or Dismissed |
| 3. Onboarding | The application number is allotted, the other party can see it, and the magistrate chooses to deal with it now or on a date. | Magistrate | Pending Decision |
| 4. Objections | The other party may file one objection, due by midnight the day before the decision date. | The other party | Pending Decision (unchanged) |
| 5. Decision | An order accepting or rejecting the application is signed. | Magistrate signs; bench clerk or typist may draft | Accepted or Rejected |
| 6. After the decision | On acceptance, the type's workflow runs. On rejection, nothing does. | System, or the magistrate where the workflow needs a choice | Accepted or Rejected (unchanged) |

![Application lifecycle state diagram: Draft through Pending Signature, Pending Payment, Pending Review and Pending Decision to Accepted, Rejected, Dismissed, Submitted or Expired](https://codahosted.io/docs/KtL_rwN6Qw/blobs/bl-mU4WA9f9C5/bc11f1388ca64f3444395bbea36635929c423c3c9b0960a2e487ccfd0fd440e172372fbb2a53668bdb2328851d59631aff09804a71bba74d7545e184260413b6b3a723d97de7caddc5da9a43bb6ec6f993e4c3e6475d87df5072a6cdb22e922bc2015ce1)

Accepted, Rejected, Dismissed, Submitted and Expired have no arrow leaving them — that's what makes them
terminal. Moving the decision date (`ALC-15`) doesn't change status, so it is shown as a note rather than a loop. The
diagram still shows "set a date" before onboarding, withdrawn in v30; it needs re-rendering.

The steps are set out one at a time below. Every status change is listed in one table at
the end, under "Every status change".

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
  - Onboard an application (a system action, magistrate-only, `ALC-22`)
  - Set or move the decision date (`ALC-09`, `ALC-15`) — also a system action,
    magistrate-only
  - Draft or sign a dismissal, or an accept/reject order (only the magistrate signs,
    `ALC-22`)
  - Sees key metadata and any objection when opening an application (`ALC-23`)
- **Bench Clerk and Typist**
  - View all submitted applications, including before onboarding, same as the magistrate
  - Draft a dismissal or an accept/reject order — cannot sign it (`ALC-22`)
  - Cannot onboard, or set/move a decision date — those are system actions
    restricted to the magistrate (`ALC-22`)

The **objection-filing** action on Advocate/PiP is signed and paid for like any other
application type — confirmed, no longer open.

| ID | Requirement |
|---|---|
| `ALC-22` | **General rule on who may do what:** a **system action** — onboarding (`ALC-04`), setting or moving the decision date (`ALC-09`, `ALC-15`) — is restricted to the **magistrate**. An **order** — dismissing (`ALC-19`), accepting or rejecting (`ALC-08`) — may be **drafted** by the bench clerk or typist as well as the magistrate; only the **magistrate signs** it, per [`order-generation.md`](order-generation.md)'s standing rule. |
| `ALC-24` | **"The other party"**, throughout this file, means the opposing **side** — anyone on the complainant side, if the application was raised by anyone on the accused side, or vice versa — not a specific named individual. Only **one** objection may be raised against a given application, on behalf of that side. |

---

## Step 1 — Filing

Filing is everything the filer side does before the court sees the application. It ends
when the application is both **signed and paid for**; only then does it count as filed
(`ALC-01`). Until then it is the filer side's alone: the court does not see it. An
application that is never submitted stays where it is; it does not expire.

**Who can file.** Filing involves up to three roles, and they need not be the same person:

| Role | Who | Can do |
|---|---|---|
| Drafter | The advocate/PiP, or a clerk or junior advocate working for them | Create the draft, fill it in, send it for signature |
| Signer | The advocate/PiP selected in **Raised by** — anyone with advocate access on the case, or a party-in-person. For PoA Change, the incoming PoA holder. | Sign, in any signing mode enabled for the deployment. Only the signer can move the application past Pending Signature. |
| Payer | The advocate/PiP, a clerk or junior advocate for their associated advocate, the litigant it is raised for, or that litigant's PoA-holder | Pay |

The litigant and the PoA-holder do not draft or sign; they can only pay, and see the
application once it is submitted. Which **types** a filer may raise depends on each type's
"Available when" rule (1.1). Objection is the exception: only the other party files it, and
only from a File objection task (step 4).

**How the status moves during filing:**

| Status | Entered when | Left when |
|---|---|---|
| **Draft** | The drafter creates the application (1.3), or it is moved back from Pending Signature (1.4) | The drafter chooses **Proceed to sign** (1.4) |
| **Pending Signature** | **Proceed to sign** is chosen (1.4) | The signer signs (1.5), or it is moved back to Draft to be edited (1.4) |
| **Pending Payment** | The signer signs (1.5) | Someone allowed to pay pays (1.6) |
| **Pending Review** (Objection: **Submitted**) | Payment is made (1.6, 1.7) | Step 2 begins |

**1.1 Choose the type.** The filer picks one of the types in "Application types". Only the
types whose "Available when" rule is met are offered (`ALC-26`): Bail only to the accused,
Delay Condonation only to the complainant, Advance / Prepone and Postpone only when a
hearing is scheduled in the case, and Edit Litigant Details as its workflow control
allows. **Objection** is never chosen here — it is raised only from a File objection task
(step 4).

**1.2 Fill in the form.** Every application asks the same three things first (see "Every
application" under "Fields by application type"):

- **Raised by** — the advocate/PiP the application is raised by, preselected where the
  filer's role makes it obvious. This is the person who will sign it.
- **Litigant** — the litigant it is raised on behalf of, from those the advocate in
  Raised by represents.
- **Supporting documents** — optional; as many as needed, each named by the filer.

Then come the type's own fields, listed under its heading in "Fields by application type".

**1.3 Save as a draft.** Creating the application makes it a **Draft** and records Date
Created. Anyone who can draft — the advocate/PiP, or a clerk or junior advocate drafting on
their behalf — can save it, leave, and come back to it with everything still filled in
(`ALC-27`). A draft is visible to the person who created it and to their associated
advocates, clerks and junior advocates.

**1.4 Send for signature.** When the draft is ready, **Proceed to sign** moves it to
**Pending Signature**. A clerk or junior advocate can do this; it is how a draft they
prepared reaches the advocate for review and signature. An application in Pending
Signature cannot be edited as it stands. To change it, it is moved back to **Draft**,
edited there, and sent for signature again (`ALC-31`). Anyone who could have created and
edited the draft can move it back.

**1.5 Sign.** The application is signed by the person selected in **Raised by** (1.2), and
by no one else — not just any advocate or PiP on the case, and never a clerk or junior
advocate (`ALC-28`). For a PoA Change, it is the incoming PoA holder who signs. The signer
may use any of the signing modes enabled for the deployment. Signing moves the application
to **Pending Payment**.

**1.6 Pay.** The application is paid for by any one of: the advocate/PiP, a clerk or
junior advocate for their associated advocate's application, the litigant it was raised
for, or that litigant's PoA-holder (`ALC-29`). Payment can be left for later; the
application then waits in Pending Payment, and a pay task links back to it. `ALC-01`
requires payment only "where the type carries a fee"; what a type with no fee does at this
step is not yet decided (`Q-11`).

**1.7 Submission.** Once signed and paid, the application is **submitted**:

- Date Submitted is recorded.
- It gets a **temporary identifier**, shown to the filer from this point on (`ALC-02`).
- Its status becomes **Pending Review** — except an Objection, which becomes
  **Submitted** and goes no further (step 4).
- A **Review application** task is raised for the magistrate, due the next working day
  (`ALC-03`).
- The court can now see it. The other party cannot, until it is onboarded (`ALC-17`).

| ID | Requirement |
|---|---|
| `ALC-01` | Submitting an application requires the signature of a filer entitled to sign and, where the type carries a fee, payment. |
| `ALC-26` | The filer is offered only the application types whose "Available when" rule (see "Application types") is met for them and the case. Objection is not offered; it is raised only from a File objection task (`ALC-12`). |
| `ALC-27` | A draft saves with everything filled in, and reopens that way. Draft is a resumable status, not a discarded one. |
| `ALC-28` | An application is signed only by the person selected in **Raised by** (for PoA Change, the incoming PoA holder) — not by any other advocate or PiP on the case. A clerk or junior advocate may draft and send for signature, but cannot sign. The signer may use any signing mode enabled for the deployment. |
| `ALC-29` | The payer may be the advocate/PiP, a clerk or junior advocate for their associated advocate's application, the litigant on whose behalf it is raised, or that litigant's PoA-holder. When payment is left for later, a pay task is raised that links back to the application. |
| `ALC-31` | An application in Pending Signature can be moved back to Draft, and edited there, by anyone who could have created and edited that draft. It is edited only in Draft; once edited, it goes through Proceed to sign again. |
| `ALC-02` | On submission the application is allotted a **temporary identifier**. It can be shown to the user, but it is never cited in an order or any other document. The court-facing **application number** is allotted only on being onboarded (`ALC-04`). *(This reverses which of the two numbers `order-generation.md`'s `APL-02`/`APL-03` and `case-numbers.md`'s rows 6–7 currently name — see `Q-5`.)* |
| `ALC-03` | On submission the system raises a **Review application** task for the magistrate, due the next working day. Filing time is not a factor in this version; a later version may bring the due date forward to the same day when the application is filed during working hours on a working day. |

---

## Step 2 — Review: the first gate

The first gate is whether the magistrate takes the application onto the court's file at
all. The term for this throughout is **onboarding**. The **Review application** task
raised at submission gives the magistrate two choices. The status stays **Pending
Review** for as long as the task is open.

- **2a. Onboard** — the usual path. Goes straight on to step 3.
- **2b. Dismiss** — an order, effective on the magistrate's signature. The application ends
  as **Dismissed**, with no application number.

There is no setting a date at this step. A date is set only once the application has been
onboarded (3b).

| ID | Requirement |
|---|---|
| `ALC-05` | *Withdrawn in v30.* There is no "set a date" before onboarding. A date is set only after onboarding (`ALC-09`). |
| `ALC-06` | *Withdrawn in v30*, with `ALC-05`. |
| `ALC-19` | **Dismissing an application** is an order item, effective on the magistrate's signature, worded per [`order-generation.md`](order-generation.md) `APL-04`–`APL-06`. Any of the magistrate, the bench clerk or the typist may draft it; only the magistrate signs (an order, `ALC-22`). It's available on the **Review application** task the whole time it's open, alongside onboarding. |
| `ALC-20` | *Withdrawn in v30*, with `ALC-05`. |

---

## Step 3 — Onboarding

Onboarding is what officially takes the application onto the court's file. It is a system
action: no order, no signature, effective at once.

- The **application number** is allotted, and Date Onboarded recorded.
- The status becomes **Pending Decision**.
- The **other party can now see the application**, whether or not objections are invited
  (`ALC-17`).

In the same action, the magistrate chooses what happens next:

- **3a. Deal with it now** — the order screen opens with the application in context. Goes
  straight to step 5.
- **3b. Deal with it on a date** — the magistrate sets the decision date ("Suggesting a
  date", below) and answers whether to invite objections, checked by default. Checked
  leads to step 4; unchecked goes to step 5 on the date.
- **3c. Open the order generation screen directly** — for something unrelated, such as
  moving a hearing. This leaves the application exactly as it is.

Either 3a or 3b raises a **Decide application** task — due at once for 3a, on the decision
date for 3b. It closes only when an accept or reject order is signed, so the application
cannot be lost if a draft order is abandoned.

| ID | Requirement |
|---|---|
| `ALC-04` | **Onboarding** an application is a system action: it allots the application number, nothing is written into any order, no signature is involved, it takes effect at once, and only the **magistrate** may do it (a system action, `ALC-22`). Available for as long as the **Review application** task is open — the usual path (dismissing, `ALC-19`, is the alternative). The application's status is **Pending Review** the whole time this task is open; nothing here is a separate status. |
| `ALC-07` | Onboarding carries this question with it: **pass the order now, or deal with it on a date?** (or open the order generation screen directly, `ALC-18`) — answered alongside onboarding. Unlike onboarding itself, answering it doesn't require the order to be signed right away (`ALC-21`). |
| `ALC-08` | **Now** — the order screen opens with the application in context; any of the magistrate, the bench clerk or the typist may draft the accept/reject order there, but only the **magistrate** signs it (an order, `ALC-22`). |
| `ALC-09` | **On a date** — the magistrate (only) sets the date on which it will deal with the application (a system action, `ALC-22`), and the system raises a **Decide application** task due on that date. |
| `ALC-17` | The application is **invisible to the other party until it is onboarded** (`ALC-04`). From onboarding onward it is visible regardless of whether objections are invited (`ALC-12`). |
| `ALC-18` | The magistrate may open the **order generation screen** directly instead of answering "deal with it now" or "on a date" — e.g. to move a hearing at the same time. This has no connection to the application at all: it's the magistrate doing something unrelated on that screen, so it leaves the application's status and pending task untouched. |
| `ALC-21` | Choosing "deal with it now" (`ALC-08`) or "deal with it on a date" (`ALC-09`) both raise a **Decide application** task — due immediately for the former, due on the set date for the latter — closing only once an accept/reject order is signed. This covers the gap between the magistrate's choice and actually drafting the order. Once the application is onboarded, this task is visible to other users too — the bench clerk or typist, who may be the one drafting the order (`ALC-22`) — not just the magistrate. |
| `ALC-25` | Until application types carry their own configuration for this (see "Application types"), every type is treated the same: assumed to go through "deal with it on a date" (`ALC-09`) with the notify-for-objections checkbox (`ALC-11`) checked by default. The magistrate can still deselect the checkbox or choose "deal with it now" (`ALC-08`) by hand — this is a placeholder default, not a restriction on what the magistrate may do. |

---

## Step 4 — Objections

Step 4 happens only when the magistrate chose "deal with it on a date" and left "invite
objections" checked. Dealing with it now gives nobody the chance to object.

- The other party — the whole opposing side, not a named person (`ALC-24`) — is told
  plainly that it must file an objection, and by when. A **File objection** task is raised
  on it at once.
- The objection is due by **midnight the day before** the decision date: a decision on
  the 21st puts the deadline at the end of the 20th.
- The objection is itself an application of type **Objection**, filed through step 1 —
  drafted, signed and paid for. It ends at **Submitted**: it is never reviewed, onboarded,
  accepted or rejected on its own. It is linked to the application it answers.
- Only **one** objection may be filed against an application.
- If none is filed by the deadline, nothing happens: the magistrate goes ahead on the
  date, and nothing is recorded or delayed because of the silence.
- If objections are not invited, no task is raised, and the other party can still see the
  application.

| ID | Requirement |
|---|---|
| `ALC-11` | With the date, the magistrate answers one more question: **does the other party need to file objections?** — checked by default. Asked only on this branch; an application decided at once gives nobody an opportunity to object. Until application types carry their own configuration, this defaults to checked for every type (`ALC-25`). |
| `ALC-12` | **Checked** — the other party is told plainly that it must file an objection and by when, and a **File objection** task is raised on it at once. **Unchecked** — no task is raised, but the other party can still see the application regardless: visibility follows onboarding (`ALC-17`), not this choice. |
| `ALC-13` | The objection is due by **midnight the day before** the date the court has said it will deal with the application — e.g. a decision set for the 21st puts the objection deadline at the end of the 20th — and is raised at once, when the magistrate sets the date. If no objection is filed by then, it simply doesn't matter: the magistrate proceeds with the decision as scheduled, and nothing is recorded or delayed on account of the silence. |

---

## Step 5 — Decision: the second gate

The second gate is whether the magistrate accepts or rejects the application. It comes at
once after onboarding (3a), or on the decision date (3b). The magistrate decides from one
screen showing the application, its documents, when it was filed, whether an objection
was filed, and the objection itself if there is one.

- **Accept** — an order allowing the application. Once signed, the status is **Accepted**,
  and step 6 follows.
- **Reject** — an order rejecting it. Once signed, the status is **Rejected**. Nothing
  further runs.

**Moving the decision date.** Where the decision was set for a date (3b), the magistrate
can move it to another date before deciding. The Decide application task and any File
objection task move to the new date together, and the objection deadline moves with them.
The status stays Pending Decision.

The bench clerk or typist may draft the order; only the magistrate signs. Signing either
order closes the Decide application task.

**Dismissed and Rejected are different outcomes.** Dismissal happens at review, before
onboarding, with no application number. Rejection happens here, after onboarding.

| ID | Requirement |
|---|---|
| `ALC-14` | On the date, the court allows or rejects the application, reading the application, its documents and any objection filed against it from the same screen (`APL-07`, `APL-11`). |
| `ALC-15` | The court may instead **move the decision to another date**. The new date replaces the old one; both the court's task and the objection task (if raised) are re-dated to it, the objection task staying due before the new date (`ALC-13`). |
| `ALC-23` | **Whenever the magistrate opens the application**, key metadata is shown alongside it: when it was filed, and whether an objection has been filed. If one has been filed, the objection itself is shown too — not just the fact that one exists. |

---

## Step 6 — After the decision

Signing an order accepting the application starts the workflow that belongs to its type,
listed under "Workflow attached" in "Application types" — for example, for Postpone, the
magistrate selects a new hearing date and the hearing is rescheduled. Several types have no
workflow; for them, acceptance is the end. Rejection starts nothing.

| ID | Requirement |
|---|---|
| `ALC-16` | On signature of an order **allowing** the application, the workflow that belongs to that **application type** is triggered (`APL-08`). **Rejecting** it does not trigger that workflow. |

---

## Expiry (Advance / Prepone and Postpone only)

Only the two hearing-linked types expire. An Advance / Prepone or Postpone application is
about one particular hearing; if that hearing passes before the application has been dealt
with, there is nothing left to advance or postpone, and the system marks it **Expired**.
Expired is final. No other type expires, at any status.

| ID | Requirement |
|---|---|
| `ALC-30` | An **Advance / Prepone** or **Postpone** application that has not been accepted or rejected by the time its hearing passes is set to **Expired** by the system. No other application type expires. Which statuses this covers, and what happens to its open tasks, is in `Q-8`. |

---

## Suggesting a date

Used when setting the decision date at onboarding (3b), the only place a date is set.

| ID | Requirement |
|---|---|
| `ALC-10` | The system **suggests** a date by pre-filling the case's next hearing date, if it has one on record; if it doesn't, there is nothing to pre-fill and the magistrate sets the date manually. Later, when application work runs in dedicated asynchronous slots, the suggestion becomes the next such slot. |

---

## Every status change

| Initial status | Action | Actor | New status | Step | Ref |
|---|---|---|---|---|---|
| *(none)* | Create | Advocate/PiP (or a clerk/junior advocate drafting on their behalf) | Draft | 1 | `ALC-27` |
| Draft | Proceed to sign | Advocate/PiP, or a clerk/junior advocate | Pending Signature | 1 | |
| Pending Signature | Move back to draft, to edit | Anyone who could have created and edited the draft | Draft | 1 | `ALC-31` |
| Pending Signature | Sign | The person selected in Raised by (PoA Change: the incoming PoA holder) | Pending Payment | 1 | `ALC-28` |
| Pending Payment | Pay | Advocate/PiP, clerk/junior advocate, litigant, or PoA-holder | Pending Review | 1 | `ALC-02`, `ALC-29` |
| Pending Payment — **Objection only** | Pay | Advocate/PiP, clerk/junior advocate, litigant, or PoA-holder on the objecting side | **Submitted** — terminal; no `Pending Review` | 1, 4 | `ALC-24` |
| Not yet accepted or rejected (which statuses exactly: `Q-8`) — **Advance / Prepone and Postpone only** | Its hearing passes | System | Expired | Expiry | `ALC-30` |
| Pending Review | Onboard application | Magistrate | Pending Decision | 2, 3 | `ALC-04` |
| Pending Review | Dismiss application | Magistrate | Dismissed | 2 | `ALC-19` |
| Pending Decision | Accept, having dealt with it now or on a date | Magistrate | Accepted — the application type's workflow triggers | 5, 6 | `ALC-08`, `ALC-09`, `ALC-16` |
| Pending Decision | Reject, having dealt with it now or on a date | Magistrate | Rejected — no workflow | 5 | `ALC-16` |
| Pending Decision | Move the decision to another date | Magistrate | Pending Decision *(unchanged)* | 5 | `ALC-15` |

Left out on purpose: the **File objection** task the other party gets in step 4
(`ALC-12`) isn't a status of *this* application — it's a task on a different person
entirely, so it doesn't belong in this application's own status column.

---

## Application attributes

| Attribute | Description |
|---|---|
| Temporary Identifier | Assigned at filing (`ALC-02`). Can be shown to the user, but never cited in an order or any other document. |
| Application Number | Assigned at onboarding, not at filing (`ALC-04`). This is the number a court recognises the application by. |
| Application Type | The type of application. |
| Template | The print/PDF template this application renders into. Each type's template is named in "Fields by application type." |
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
| Bail | Only for the accused | On acceptance, the magistrate can request a bail bond — a draft is created from the application. | Request bail for an accused, with supporting details and documents. |
| Edit Litigant Details | Set by a control on the workflow: who can raise it, and whose details each of them can edit | On acceptance, the requested litigant details are updated. | Request corrections to any litigant's details in the case. |
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
| Warrant by Hand | Always | — The decision screen directs the magistrate to issue a warrant with the channel set to **By hand**; nothing runs automatically. | Request that a warrant be issued for delivery by hand. |
| Absent Application | Always | — | Notify the court of a party's absence and seek related directions. |
| Reopen Evidence | *?* | — | Request that evidence be reopened for further examination or submission. |
| **Objection** | Only against another application, raised via that application's **File objection** task (`ALC-12`) — not independently started by a filer | No accept/reject of its own: ends at `Submitted`, not `Pending Review` — read alongside the original application when the magistrate decides it (`ALC-14`, `ALC-23`), and becomes that application's `Objection (Linked Application)` (`ALC-24`) | State an objection to another party's application. |

Hearing-linked types (Advance / Prepone, Postpone) expire if their hearing passes before
the application is dealt with (`ALC-30`); whether a hearing that is moved counts as well is
open (`Q-8`). Until real per-type configuration of
"decide now vs. must offer objection" exists, `ALC-25` is the placeholder: every type
behaves the same.

Objection goes through the same Draft → Sign → Pay steps as every other type — confirmed
(`Q-6`, now closed). It only diverges after payment: `Submitted`, not `Pending Review`.

---

## Fields by application type

Each type's own fields, taken from its print template, with the field type from the
functional spec where the spec gives one.

Three fields are on every application, whatever its type, and are listed once under "Every
application" below. Everything else every application carries is left out, because it is
the same for every type and filled from the case, the filer's profile or those two fields:
court complex, case number, filing number, case name, date, the parties table (each
complainant and accused with their advocates), offence, application title, petitioner
name, party name and party type, advocate name, bar registration number, signature, the
"Dated this" line, and the closing additional comments box.

**Filled by:** *Filer* — typed or chosen by the person raising the application. *System* —
taken from the case record; shown, not editable.

### Every application

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Raised by | Filer | Dropdown, single select | Options: everyone with advocate access on the case. Preselected: the user's own name for an advocate with vakalatnama access or a party-in-person; for a clerk, or a junior advocate without vakalatnama access, the advocate they work for — left empty if they work for more than one. Saved as Application Raised By. |
| Litigant | Filer | Dropdown, single select | Options: the litigants represented by the person selected in Raised by; they refresh when Raised by changes. Preselected when there is only one. Saved as Application Raised On Behalf Of. |
| Supporting documents | Filer | Document name, file upload | Optional. Add as many; one entry per document. The filer names each document. |

### Bail

Template: `application-bail-bond`. The surety fields follow the bail bond form (Form No. 37).

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Type of bail | Filer | Dropdown, single select: Cash, Surety | Surety shows Number of sureties and the surety details. |
| Bail amount | Filer | Amount (Rs.) | Shown for both Cash and Surety. |
| Number of sureties | Filer | Number | Shown when Type of bail is Surety. Sets how many sets of surety details follow. |
| Surety name | Filer | Text | Shown when Type of bail is Surety; once per surety. |
| Father's / mother's name | Filer | Text | Shown when Type of bail is Surety; once per surety. |
| Surety phone number | Filer | Phone | Shown when Type of bail is Surety; once per surety. Mandatory. |
| Surety email ID | Filer | Email | Shown when Type of bail is Surety; once per surety. Optional. |
| Surety address | Filer | Address | Shown when Type of bail is Surety; once per surety. |
| Surety ID proof | Filer | File upload | Shown when Type of bail is Surety; once per surety. |
| Reason for bail | Filer | Text | |
| Proof of solvency | Filer | File upload | Shown when Type of bail is Surety; once per surety. Any other documents go in the optional Supporting documents on every application. |

### Edit Litigant Details

One application for editing any litigant's details — complainant or accused, individual or
institution. A control on the workflow decides who can raise it and whose details they can
edit. Template: `application-profile-edit`. Where the template prints a litigant's current
details, it takes them from the case record.

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Litigant to edit | Filer | Dropdown, single select | Options: the litigants whose details the person raising the application is allowed to edit, per the control. Prefills the fields below. |
| Reason for editing | Filer | Text | |
| Litigant type (`LIT-2` / `ACC-1`) | Filer | Radio: Individual, Institution | Prefilled with the litigant's current type; editable. Together with whether the litigant is a complainant or an accused, decides which of the tables below is shown. Changing it shows the other type's table; those fields start empty. |

The fields below are the litigant fields from e-filing ([e-filing handover](efiling-scrutiny-registration-handover.md)
§6 and §8; IDs in brackets), with the same field types and validations. Every field is
prefilled with the selected litigant's current details, and the filer edits only what has
changed. Addresses use the e-filing address composite (§5).

**Complainant — individual**

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Phone number (`LIT-3`) | Filer | Phone | Must not match any other complainant, accused, advocate or PoA holder in the case. |
| Full name (`LIT-4`) | Filer | Text | Alphabetic. |
| Age (`LIT-5`) | Filer | Number | Positive integer. |
| Gender (`LIT-5a`) | Filer | Dropdown, single select: Male, Female, Other | Optional. |
| Differently abled? (`LIT-5b`) | Filer | Radio: Yes, No | Optional. |
| Email ID (`LIT-6`) | Filer | Email | Optional. |
| Permanent address (`LIT-7`) | Filer | Address | |
| Is the current address the same as the permanent address? (`LIT-8`) | Filer | Radio: Yes, No | No shows Current address. |
| Current address (`LIT-9`) | Filer | Address | Shown when the answer above is No. |

**Complainant — institution**

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Type of institution (`LIT-17`) | Filer | Dropdown, single select | Options from MDMS. |
| Institution name (`LIT-18`) | Filer | Text | |
| CIN or PAN (`LIT-18a`) | Filer | Text, stored upper-case | Optional. No format validation. |
| Phone number (`LIT-19`) | Filer | Phone | Optional. |
| Email ID (`LIT-20`) | Filer | Email | Optional. |
| Institution address (`LIT-21`) | Filer | Address | |
| Authorised representative phone number (`LIT-22`) | Filer | Phone | |
| Authorised representative full name (`LIT-23`) | Filer | Text | |
| Authorised representative age (`LIT-24`) | Filer | Number | |
| Authorised representative gender (`LIT-24a`) | Filer | Dropdown, single select: Male, Female, Other | Optional. |
| Authorised representative differently abled? (`LIT-24b`) | Filer | Radio: Yes, No | Optional. |
| Authorised representative email ID (`LIT-25`) | Filer | Email | Optional. |
| Authorised representative designation (`LIT-25a`) | Filer | Text | |
| Authorised representative address (`LIT-26`) | Filer | Address | |

**Accused — individual**

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Full name (`ACC-2`) | Filer | Text | Alphabetic; special characters allowed. |
| Age (`ACC-3`) | Filer | Number | Integer, 1 or more. Optional. |
| Designation (`ACC-15`) | Filer | Text | Optional. Prefilled for a person responsible for an institution, from the designation entered at e-filing. |
| Mobile number (`ACC-6`) | Filer | Phone | |
| Email ID (`ACC-7`) | Filer | Email | |
| Addresses (`ACC-8…12`) | Filer | Address | Add as many. |
| Police station (`ACC-13`) | Filer | Dropdown, single select | One per address. Mandatory. |

**Accused — institution**

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Type of institution (`ACC-4`) | Filer | Dropdown, single select | Options from MDMS. |
| Institution name (`ACC-5`) | Filer | Text | |
| Mobile number (`ACC-6`) | Filer | Phone | |
| Email ID (`ACC-7`) | Filer | Email | |
| Addresses (`ACC-8…12`) | Filer | Address | Add as many. |
| Police station (`ACC-13`) | Filer | Dropdown, single select | One per address. Mandatory. |

The institution's persons responsible (`ACC-14…23`) are not edited here. Each became a separate individual accused at e-filing ([e-filing handover](efiling-scrutiny-registration-handover.md) §8), and is edited as one, under **Accused — individual**.

### Case Settlement

Template: `application-case-settlement`

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Reason for settlement | Filer | Text | |

### Case Transfer

Template: `application-case-transfer`

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Current court | System | — | The court the case is in. |
| Requested court | Filer | Text | |
| Reason for transfer | Filer | Text | |

### Case Withdrawal

Template: `application-case-withdrawal`

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Reason for withdrawal | Filer | Text | |

### Delay Condonation

Template: `application-delay-condonation`

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Reasons for delay | Filer | Text | |

### Generic

Template: `application-generic`

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Application title | Filer | Text | Used as the application's heading. |
| Details | Filer | Text | |

### Advance (Prepone) / Postpone

Three templates carry these: `application-reschedule-hearing` (advancement or rescheduling),
`application-reschedule-request` (rescheduling) and `application-for-checkout-request`
(checkout of the hearing date). The fields below cover all three.

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Initial hearing date | System | — | From the hearing scheduled in the case. |
| Purpose of hearing | System | — | From the hearing scheduled in the case. |
| Reason for rescheduling | Filer | Dropdown, single select | |
| Proposed hearing date | Filer | Date picker | The date from which the party is available. |

### PoA Change

Template: `application-poa-change`. Raised and signed by the incoming PoA holder,
not by an advocate.

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Litigants appointing the applicant | Filer | Multi-select | Options: the case's litigants. Whether a litigant already has a PoA holder is a property of that litigant on the case record, not a field here. |
| Authorization document | Filer | File upload | One per litigant selected above. |
| Reason for change | Filer | Text | |

### Production of Documents

Template: `application-production-of-documents`

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Reason for application | Filer | Text | |
| Documents | Filer | Document type, file upload | Add as many; one entry per document. PDF or JPEG, within the file size limit. |

### Addition of Witness

Template: `application-witness-deposition`. The witness fields from e-filing
([e-filing handover](efiling-scrutiny-registration-handover.md) §13; IDs in brackets), with
the same field types and validations. One set per witness; add as many.

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Full name (`WIT-1`) | Filer | Text | Optional if Designation is entered. |
| Age (`WIT-2`) | Filer | Number | Integer, 1 or more. Optional. |
| What will the witness prove (`WIT-3`) | Filer | Text | Optional. |
| Designation (`WIT-4`) | Filer | Text | Optional if Full name is entered. |
| Mobile number (`WIT-5`) | Filer | Phone | Optional. |
| Email ID (`WIT-6`) | Filer | Email | Optional. |
| Addresses (`WIT-7`) | Filer | Address | Mandatory. Add as many. Uses the e-filing address composite (§5). |

### Warrant by Hand

No template of its own.

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Accused | Filer | Dropdown, single select | Options: the case's accused. |
| Address for delivery | Filer | Address | Prefilled with the selected accused's address from the case file; editable. Where the accused has more than one address, the filer picks which one to prefill from. |

### Absent Application

No template.

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Reason for absence | Filer | Text | |

### Reopen Evidence

No template.

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Reason for reopening | Filer | Text | |

### Objection

No template yet.

| Field | Filled by | Field type | Associated logic |
|---|---|---|---|
| Reason for objection | Filer | Text | |


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
| `Q-8` | Expiry of Advance / Prepone and Postpone (`ALC-30`): (a) does it apply at every status before a decision — Draft, Pending Signature and Pending Payment as well as Pending Review and Pending Decision? (b) Does a hearing that is **moved**, not just one that passes, also expire the application? (c) On expiry, are its open tasks (Review application, Decide application, File objection) closed? | No |
| `Q-11` | `ALC-01` requires payment only "where the type carries a fee". Does a type with no fee skip Pending Payment and go straight from signing to Pending Review? | No |
| `Q-12` | The filer-side tasks for signing and paying (the pay task in `ALC-29`, and a sign task for the advocate/PiP) are not in the Pending tasks (Citizen-Side) table yet. Should they be added there? | No |
