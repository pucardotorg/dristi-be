# Process — Notice, Summons, Warrant, Proclamation, Attachment

**Status:** v14 — 2026-10-25; **three process roles, each held per process type and channel** ([`court-roles.md`](court-roles.md)): a **Process signer** signs, a **Process dispatcher** marks sent and records a recall, a **Process reporter** records the outcome (§A4, `SGN-01`, `DSP-03`, `PIA-01`, §6.2). Warrant signer is gone — a warrant is signed by whoever holds Process signer for warrants. The Post Officer no longer appears here; e-Post is dispatched and reported by those roles. The dispatcher either marks a process sent (manual send) or clicks Send, which triggers the system calls (system send); where the status update is by the system, the system is the reporter (§A4, `DSP-03`). Sign-and-send in one click needs both Process signer and Process dispatcher (`DSP-02`). Removed the references to the Sign process screen design (§A4, §9). Status **Failed** renamed **Errored** (§10.1). **A process expires, by default, at midnight at the end of the day before its hearing** (`EXP-01`); `Q-6` resolved. `PIA-02` (warrant on a hearing-date change) removed: what happens to any live process when its hearing moves is `Q-4`. **A hearing-date change moves an unsigned process's expiry; a signed process's expiry stays** (`EXP-01a`). **Recall is process by process** — a Process dispatcher recalls one or more processes with no outcome yet, sent or not — before sending it is in effect a cancellation; a screen may suggest all of the recipient's, but the dispatcher chooses (`PIA-01`); it is no longer a pending task. **§13 cut to the channels available**; fees and roles are configuration owned by the fee master, the e-filing handover and court-roles; §13.1 is a table of available channels per state — Kerala, Gujarat, Punjab & Haryana — each At launch, Post-launch or Never; filled 2026-10-25: SMS, RPAD, Police (RPAD) and By hand at launch everywhere; Email and e-Post post-launch; Police (iCOPS) Kerala only, at launch; Police (NSTEP) Gujarat and Punjab & Haryana, at launch (`Q-5` resolved). New **§13.2 Court fee per process type**, per state: Kerala ₹2 for notice, summons and warrant, ₹0 for proclamation, attachment and custom process; Gujarat and Punjab & Haryana to be confirmed (`Q-12`). Open questions: `Q-1`, `Q-2`, `Q-7`, `Q-8`, `Q-14` resolved; `Q-4` narrowed; `Q-11` moved to [`court-roles.md`](court-roles.md); `Q-13` removed — it returns with the channel-fee requirement. Newspaper publication of a proclamation is recorded Executed, not tracked (`DSP-10`). Resolved open questions removed; open questions now also carry items yet to be done — new `Q-16` (the PDF template per process type); `Q-15` now records that the police-station master data is yet to be received. Part A (A2–A5) rewritten to the latest requirements. `Q-4` closed: nothing else is done to a signed process when the hearing moves (`EXP-01a`). Linked records gains **Notifications** and **Events** views; three notifications drafted in `pending-task-drafts.md` §8 — steps due, outcome recorded, recalled; none for Errored or Expired. Court-side tasks and notifications written to the master tables 2026-10-25; events: Reissued removed, envelope event renamed *Envelope for {Process Type} received*, Issued details include custom process. Custom templates a court creates itself are out of scope for launch (§6.1). Who a process type may name as recipient is backend configuration, not set from the UI (§2). §4 adds who signs to what varies between processes. **By hand has a destination** — the recipient's postal address, like every other postal channel — and fans out per address; it differs only in how it is sent and its outcome recorded (§6.2, `PRC-05`, §A5). **The police-station master covers every state**, since a police channel can send to a station in any state (`PRC-08`); whether we will have that data is `Q-15`. The note on SP/Commissioner offices (`SG-09`) is removed. With more than one accused, none is pre-selected (`AUT-05`). The police station is pre-filled only from one already held against the address, from e-filing or an earlier round, otherwise blank — the system does not work it out from the address (`AUT-04`, `PRC-08`). For SMS and Email, what counts as Delivered is left to implementation (§6.2); `Q-9` closed. The police return portal (`SG-10`) is a way for the executing officer to update status as Process reporter, not a new channel (§6.2). Custom process may also go By hand (§6.3). `FEE-01` reworded: the court fee is flat per process type and may be zero for some. The court fee and channel fee may go through different payment gateways, making them two payments (`FEE-06`, `Q-13`). New role **Envelope receiver** records receipt of the RPAD and Police (RPAD) envelope, in place of "court staff" (`STP-02`, §A4). §6.2 defines System (the step happens digitally, such as an API call) and Manual (a person records something that happened offline). **Each manual step of a process has a court-side pending task** for the holders of that step's role; how staff lists are built is for the implementer (`SGN-02`); a Court Side view is under Linked records and the tasks are drafted in `pending-task-drafts.md`. v13 — 2026-10-25; **the process workflow is separate from the order's** — the order triggers it, loosely coupled, and starts each process with one process type, recipient, channel and address, plus the police station on a police channel (§A2, `PRC-01`); A1 and §1 no longer say the court does not deliver. v12 — 2026-10-19; order items' variables are no longer locked or optional, and order items carry no template text (see [`dropped-ideas.md`](dropped-ideas.md)); links point at the e-filing handover, after the e-filing, scrutiny and registration handover was split in two. v11 — 2026-10-18; **court-side work is named by role** ([`court-roles.md`](court-roles.md)): a warrant is signed by a **Warrant signer**, every other process by a **Process signer** (`SGN-01`); marking sent, recording the outcome and recording a recall are done by a **Process dispatcher** (§6.2, `DSP-03`, `PIA-01`); the channels and police station are order data. The CMO and Magistrate no longer hold permissions here. v10 — 2026-09-30; 2026-10-15: **new By hand channel** (§6.2) — no envelope, no destination; the CMO marks it sent and records the outcome. Warrant may take it; **a proclamation takes By hand only**, and a screen may record it Sent and Executed once the signed copy is downloaded (`DSP-10`); `Q-2` resolved for affixation. **System send is still its own step** — whether a screen sends on signing is a UI choice (`DSP-02`). 2026-10-12: **recipient vs addressee clarified** (§2) — the recipient is the person the process names and never changes; a warrant, proclamation or attachment is *addressed* to the police; "addressee" no longer used for the person named (`SGN-01`, `DSP-04`, `PIA-01`, `Q-2`). **police is now a channel, not a flag.** The channels are
SMS, Email, RPAD, e-Post, Police (RPAD), Police (NSTEP) and Police (iCOPS) (§6.2); which
are available is configured per deployment (`PRC-04`) — Kerala runs Police (iCOPS) in
place of Police (NSTEP). **Send and update status are two separate steps**, each set per
channel as System or Manual (`DSP-01`, §6.2). A company accused and each of its persons in
charge are separate recipient options (`PRC-02`). New §5.1: the system fills in and
pre-selects what it can, including the party directed to take steps
and the police station from the recipient's address (`AUT-01`–`AUT-04`); a police-station
master is required for every state (`PRC-08`). **Fees split into court fee and channel
fee** (§7): the court fee is flat per process and held as one pool on the case; the
channel fee is e-Post only, from a fee service, not at launch; whether the two are
paid separately is open (`Q-13`). Notice takes SMS, Email, RPAD and e-Post only (§6.3). 2026-10-01: **§5.1 pre-selection rules added** (`AUT-05`–`AUT-09`) —
recipient, addresses and channels pre-selected in the issue-process pop-up, switching from
the accused to the one unexamined witness once the accused has joined. **A warrant no longer
prints its returnable date** — it carries a QR code that opens the latest hearing date, so a
hearing-date change needs no replacement warrant (`PRC-06`, `PIA-02`; `PIA-03` removed). New
**Linked records** section: the module's two citizen-side pending tasks, held in the Pending
Tasks master table and tagged `process-handover` there. **Court-side work is not a pending
task** — it is a list of processes, segregated by status (`SGN-02`). `STP-03`
now gates each process on its own single envelope, not the round's. Each process is signed
separately, even where content is identical (`SGN-03`). **The signer is set by process type** — CMO
or Magistrate; a warrant is signed by the Magistrate (`SGN-01`). The "via police" flag
(`VIA-01`–`VIA-04`) is removed. For a police channel the police station is entered,
alongside the recipient (`PRC-03`). A warrant, proclamation or attachment is addressed to
the police, so these three take police channels only (§6.3). The template is set by
process type + recipient and is the same on every channel (`TPL-01`). WhatsApp and police
via e-Post are no longer in the channel list. Miscellaneous
process is renamed **custom process**. Supersedes v9 — 2026-09-30 (plain-language
rewrite of the via-police explanation) and v8 — 2026-09-27 (warrant always via police;
SMS/WhatsApp-to-police gap as a data fact). Earlier: v7 (process as the atomic unit —
one per addressee, per channel, per address, §3 — carried forward unchanged); v6 (via
police as one flag per process); v5 (recipient chosen per channel); v4–v2 (e-Post
manual/Post Officer; status-update fields; `Q-3` resolved); v1 — 2026-09-16 (first
draft). Still defines the channel list and the per-process status vocabulary, which
`SVC-15` of `view-case-handover.md` records as a gap.

**Referenced by ID, from outside this document — do not renumber these sections:**
`PRC-03` (`order-generation.md`), `SGN-01` at §9, `DSP-02` at §10, `EXP-01`/`EXP-02` at
§11, and the channel list at §6 (all four from `saras-2.0-gap-register.md`).

---

# Part A — Overview

*For presenting the workflow — to the program team, or to the court. Nothing here is a
separate design from Part B; it is the same requirements in plain language.*

## A1. What a process is

A **process** is an instrument the court issues to bring a person before it, put them on
notice, or compel an act on them — a notice, a summons, a warrant, a proclamation, an
attachment, or a custom process. Once issued, it goes out over one or more channels, and
the court keeps a record of what was sent, where, and what came back.

## A2. How a process starts

The process has its own workflow, separate from the order's workflow. An order is what
triggers it, but the coupling is loose: the order supplies the inputs and starts the
process workflow, and the process then runs on its own.

A process is one process type, to one recipient, on one channel, at one address (§3).
Each process workflow is started with exactly one of each:

1. **The process type** — notice, summons, warrant, proclamation, attachment or custom
   process.
2. **The recipient** — the accused, the witness, whoever the process names.
3. **The channel** — one of SMS, Email, RPAD, e-Post, Police (RPAD), Police (NSTEP),
   Police (iCOPS) or By hand. Which channels are available is configured per deployment
   (§13.1).
4. **The address** — the destination on that channel, from the recipient's record.
5. **The police station** — for a police channel only.

It also carries the hearing (`PRC-06`) and the party directed to take steps (`PRC-07`).

The order is where these are entered, today on the order screen. One order may pick
several recipients, several channels per recipient, and a recipient may have several
addresses; the order starts one process for each combination (`PRC-02`).

Police is a channel of its own, not a setting on the others. On a police channel the
process goes to the police station, and the police serve or execute it on the recipient.
A warrant or attachment is addressed to the police, so these take police channels — and a
warrant may also go By hand. A proclamation is published, not sent: it is printed and
affixed, so it goes By hand only. Which process type takes which channel is in §6.3.

**The document** — the final PDF of the process that users see — is set by the process
type and the recipient, and is the same on every channel (`TPL-01`).

## A3. The lifecycle, start to finish

```
The order is issued. For each recipient it picks the channels and, on a police
channel, the police station. One process is created per recipient, per channel,
per address (§3); everything below runs per process, independently
        │
        ▼
The system works out the court fee, net of what is already in the case's
pool (§7)
        │
        ├── balance due ──▶ the party directed to take steps pays
        │
        ├── RPAD or Police (RPAD) ──▶ the party hands in the envelope at the
        │   counter, and an Envelope receiver records it (§8)
        ▼
A Process signer signs — the process is now Signed, awaiting send (§9)
        │
        ▼
Send — a Process dispatcher marks it sent (manual channel), or clicks Send
and the system sends it (system channel) (§10)
        │
        ▼
Update status — a Process reporter records the outcome (manual channel), or
the receiving system reports it (system channel) (§10)
        │
        ▼
The process closes on its outcome. Before that, it may be Recalled by a
Process dispatcher, sent or not (§12), or it expires — by default at midnight
at the end of the day before the hearing (§11)
```

## A4. Who does the manual work

Four roles do the manual work ([`court-roles.md`](court-roles.md)). Each is held for
particular process types and channels, so the steps of one process may be done by
different people, or all by one.

- An **Envelope receiver** records receipt of the envelope — RPAD and Police (RPAD) only
  (§8).
- A **Process signer** signs it (§9). Signing is always done by a person.
- A **Process dispatcher** sends it: on a manual channel by marking it sent once it has
  physically gone out, on a system channel by clicking Send, which triggers the system
  calls. The dispatcher also recalls a process that is no longer wanted, sent or not
  (§12).
- A **Process reporter** records the outcome — served or executed, or not — on a manual
  channel. On a system channel, the receiving system is the reporter (§10).

Who holds which role in each state is in [`court-roles.md`](court-roles.md) §3. Each step
reaches the holders of its role as a court-side pending task (`SGN-02`).

## A5. The channels, in plain terms

Every channel has two steps: **send** and **update status**. Each is either **System** —
it happens digitally, through an API call or a report coming back — or **Manual** — a
person records something that happened offline (§6.2). Which channels each state offers,
and when, is in §13.1.

- **SMS / Email** — to the recipient's phone or email address. The dispatcher clicks Send;
  the system sends and tracks it. What counts as delivered is decided at implementation
  (§6.2).
- **RPAD** — physical post to the recipient. The party directed to take steps hands in an
  envelope at the counter; a Process dispatcher marks it posted, and a Process reporter
  records the outcome from the acknowledgement card.
- **e-Post** — the electronic equivalent of RPAD, to the recipient, with no envelope. A
  Process dispatcher marks it sent and a Process reporter records the outcome — usually
  post office staff, who hold those roles for e-Post.
- **Police (RPAD)** — RPAD to the entered police station. The same envelope, dispatcher and
  reporter steps as RPAD; the outcome is the station's service or execution report.
- **Police (NSTEP)** — to the entered police station through NSTEP. The document goes out
  via CIS in an end-of-day batch, and the system polls CIS for the result.
- **Police (iCOPS)** — Kerala's equivalent, in place of Police (NSTEP): the police system
  is called directly, and calls back with the result.
- **By hand** — to the recipient's postal address, like RPAD but without the envelope: the
  document is taken there in person. A Process dispatcher marks it sent and a Process
  reporter records the outcome. For a proclamation, which is printed and affixed, the
  screen may record it sent and executed once the signed copy is downloaded.

---

# Part B — Requirements

## 1. Context

A **process** is an instrument the court issues to a person to bring them before it, put
them on notice, or compel an act on them. This document specifies how a process is
created, paid for, signed, dispatched and tracked, for every process type in the Process
category of the order catalogue.

Once issued, it goes out over one or more channels, and the court keeps a record of what
was sent, where, and what came back. That record is the subject of this document.

---

## 2. Process types

| Type | Triggering order |
|---|---|
| Notice | Issue of notice |
| Summons | Issue of summons |
| Warrant | Issue of warrants |
| Proclamation | Issue of proclamation |
| Attachment | Issue of attachment |
| Custom process | Issue of miscellaneous process |

A process type does not itself fix who its recipient may be. That is a restriction held
in backend configuration, not built into the type, and it is not editable from the UI. Today's default restricts proclamation and
attachment to the accused; notice, summons and custom process are open to whichever
party the order names. A state may tighten or loosen these without a schema change.

Order items, their variables and the dropdown behaviour are owned by
[`order-template-catalogue.md`](order-template-catalogue.md).

While a process is live, the case carries the matching **secondary stage** — Notice,
Summons, Warrant, Proclamation or Attachment. Stage rules are owned by
[`case-lifecycle-handover.md`](case-lifecycle-handover.md).

The **recipient** never changes — it's the person the process names: who a summons is
for, who a warrant is against. The recipient is not always the addressee. A summons or
notice is addressed to the recipient; a warrant or attachment is addressed to the police,
who execute it on the recipient; a proclamation is published rather than addressed (§A2). On a police channel the process goes
to the entered police station, but the recipient is still the person it names.

---

## 3. The record

```
Order (Process category)
└── Round ─ everything the order issues together
    └── Process ─ one per recipient, per channel, per address: the atomic
        unit tracking, steps and status updates all happen against
```

A **process** is not one per recipient — it is one per (recipient, channel, address).
There is no separate "channel delivery" layer beneath it; the process itself carries the
status, is the thing signed, and is the thing a pending task points at, precisely so that
tracking, the manual steps and every status update happen at one level, not two.

If an order issues a summons to two people, and one of those two is served at two
addresses, that is **three processes**: one for the first person, and two for the
second — one per address. If the second person is also served by SMS as well as post,
that is a fourth process, since channel differs too. Several processes may carry the
same content (`TPL-01`), but each is signed separately (`SGN-03`).

A **round** is all the processes triggered by the same order. A person may have several
rounds over the life of a case, and several processes within one round. How the register
is displayed on the case is owned by [`view-case-handover.md`](view-case-handover.md) §7.

---

## 4. The flow

```
Order issued, entering channels per recipient, and the police station
for a police channel
        │
        ▼
Order triggers the workflow — one process per recipient, per selected
channel, per address (§3). Everything below runs per process, independently
        │
        ▼
System calculates the court fee against what is already in the case's pool,
and, for e-Post, the channel fee (§7)
        │
        ├── balance due ──▶ party pays                       ┐
        │                                                    │  pending tasks;
        ├── on RPAD or Police (RPAD) ──▶ party hands in the  │  the process
        │   envelope at the counter; an Envelope receiver    │  expires if these
        │   records it (§8)                                  │  are not done by
        ▼                                                    ┘  the expiry date
A Process signer for that process type and channel signs (§9) — now Signed,
awaiting send
        │
        ▼
Send — a distinct backend stage from signing, even where one screen or one
click carries out both (§9, §10). By the system, or by a Process dispatcher
who marks it sent — set per channel (§6.2)
        │
        ▼
Update status — a separate step from send. By the system, from what the
receiving system reports, or by a Process reporter who records the outcome —
status, reason (if negative), a comment and an optional file — when the
acknowledgement or report returns. Set per channel, independently of send
        │
        ▼
This process reaches its own outcome and closes on it, or on the expiry
date, whichever comes first — independently of every other process fanned
out from the same recipient
```

The spine is the same for every process type and every channel. What varies: who signs —
always a person (§9); whether each of send and update status is done by the system or by
a person, and which person (§6.2, §10); and whether the process admits post-issue judicial
action (§12).

---

## 5. Trigger and channel selection

| ID | Requirement |
|---|---|
| `PRC-01` | Issuing an order of a Process-category type triggers the process workflow. The process workflow is separate from the order's workflow: the order is only its trigger. Each process is started with one process type, one recipient, one channel and one address, plus the police station on a police channel, the hearing and the party directed to take steps (§A2); the order starts one per combination it selects (`PRC-02`). |
| `PRC-02` | One process is created per recipient, per selected channel, per address (§3). Where the drawer is a company, the company and every person in charge are each a separate recipient, shown as separate options in the recipient dropdown on the order screen (`PRC-03`), and each fanning out the same way. |
| `PRC-03` | An **Order data filler** enters, per recipient, on the order screen ([`court-roles.md`](court-roles.md)): the recipient, and the delivery channels. For a police channel — Police (RPAD), Police (NSTEP) or Police (iCOPS) — the police station is also entered. At least one channel is required. Several channels may be selected for the same recipient, each becoming its own process, used simultaneously. |
| `PRC-04` | Which channels are available is configured per deployment (§13). The channels offered are those available in the deployment and permitted for the process type (§6.3). |
| `PRC-05` | Each process's destination is taken from the recipient's own record — a mobile number, an email address, or one postal address — or, on a police channel, from the entered police station. Where a recipient's record holds more than one address of the kind a selected channel uses, one process is created per address (`PRC-02`). A channel cannot be selected where the record holds no destination of that kind. |
| `PRC-06` | The process is associated with the hearing set in the same order. A warrant does not print that hearing's date: it carries a QR code and a line of text telling the reader to scan it for the latest hearing date; the QR code opens a screen built to show it. Screens may show the hearing's current date rather than the date at issue. |
| `PRC-07` | The party directed to take steps is worked out by the system wherever it can (`AUT-02`), and is named in the order. That party bears the fees (§7) and the envelope obligation (§8). |
| `PRC-08` | A police-station master is required. It is the list the police station on a police channel is chosen from (`AUT-04`); it does not work out a station from an address. It covers every state, not only the deployment's own: a recipient may live anywhere, and a police channel can send to a police station in any state, provided that station is in the master (see `Q-15`). |

### 5.1 What the system fills in

The system fills in and pre-selects whatever it can on the order screen, so whoever fills the
order data only chooses where the system cannot tell. This happens in
the pop-up that opens when a Process-category order item is selected.

| ID | Requirement |
|---|---|
| `AUT-01` | Wherever a value on the order screen can be worked out from the case, the system fills it in or pre-selects it. It is only shown as an open choice when the system cannot work it out. |
| `AUT-02` | The party directed to take steps is worked out from the recipient: for the accused, the complainant; for the complainant, the accused; for a witness associated with one side, that side. |
| `AUT-03` | Where the system cannot work out the party directed to take steps — for example, a witness added by the court — it is shown as a choice on the order screen. |
| `AUT-04` | On a police channel, the police station is pre-filled where one is already held against the recipient's address — entered at e-filing or in an earlier round. Where none is held, it is left blank and chosen from the police-station master (`PRC-08`). The system does not work out a station from the address. |
| `AUT-05` | **Until the accused has joined the case**, the pop-up pre-selects the accused as the recipient where there is exactly one. Where there is more than one accused, none is pre-selected; the recipient is chosen manually, since a screen may allow only one accused per order item. |
| `AUT-06` | **Once the accused has joined the case**, the pop-up pre-selects the witness where exactly one witness has not yet been examined. Otherwise no recipient is pre-selected and the choice is left open. |
| `AUT-07` | Every address on a selected recipient's record is pre-selected, before and after the accused has joined. |
| `AUT-08` | Channels are pre-selected by process type: SMS, Email and RPAD for notice and summons; Police (NSTEP) for warrant and attachment — Police (iCOPS) in a deployment that runs it in place of Police (NSTEP) (`PRC-04`); By hand for proclamation. Channels are chosen once for every recipient selected; a recipient whose record holds no destination of a channel's kind gets no process on it, and the pop-up says so beside them (`PRC-05`). |
| `AUT-09` | The pop-up may select several recipients for the same process at once. This is a convenience of the screen only: each recipient still resolves to one process per channel, per address (`PRC-02`, §3). |

Further fill-in and pre-selection rules are added to this section as they are defined.

---

## 6. Delivery channels

### 6.1 The document

| ID | Requirement |
|---|---|
| `TPL-01` | The process document — the final PDF users see — has its template set by the process type and the recipient. The same template is used on every channel. |

Different templates per channel may be added later. That is not in scope for this
version. Nor are **custom templates** — templates a court creates itself, beyond the fixed
PDF templates, deciding who each goes to: they are out of scope for launch.

### 6.2 The channels

Every channel has two separate steps — **send** and **update status** — and each is set
per channel as either **System** or **Manual**, independently of the other (`DSP-01`).
**System** means the step happens digitally — an API call to a gateway, the post office or
the police, or a report coming back from one. **Manual** means a person records in the
system something that happened offline — that the envelope was posted, or what the
acknowledgement card says.

| Channel | Goes to | Send | Update status |
|---|---|---|---|
| SMS | The recipient's mobile number | System — messaging gateway | System — what counts as Delivered is decided at implementation (below) |
| Email | The recipient's email address | System — email service | System — what counts as Delivered is decided at implementation (below) |
| RPAD | The recipient's postal address | Manual — a Process dispatcher marks it sent once the envelope received by an Envelope receiver (§8) is posted | Manual — a Process reporter records the outcome from the acknowledgement card |
| e-Post | The recipient's postal address | Manual — a Process dispatcher marks it sent | Manual — a Process reporter records the outcome |
| Police (RPAD) | The entered police station's postal address | Manual — a Process dispatcher marks it sent once the envelope (§8) is posted | Manual — a Process reporter records the station's service or execution report |
| Police (NSTEP) | The entered police station, through NSTEP | System — via CIS in an end-of-day batch | System — polls CIS periodically |
| Police (iCOPS) | The entered police station, through Kerala's iCOPS | System — directly to iCOPS | System — iCOPS calls back (a push, not a poll) |
| By hand | The recipient's postal address — the signed document is taken there in person | Manual — a Process dispatcher marks it sent. There is no envelope (§8) | Manual — a Process reporter records the outcome |

For SMS and Email, what moves a process from Sent to Delivered is decided at
implementation. It may be the gateway's or email service's confirmation that the message
was sent, the recipient opening a link in it, or nothing — leaving the process at Sent.

Where a step is Manual, the person who does it holds the Process dispatcher (send) or
Process reporter (update status) role for that process type and channel
([`court-roles.md`](court-roles.md)). The two may be different people. The executing
officer may hold Process reporter on a police channel and record the outcome through an
interface of their own — Gujarat's SARAS 2.0 proposes an OTP-gated police return portal
(`SG-10`). It is a way of updating status, not a new channel; not in this version.

Today every channel is either System for both steps or Manual for both. Nothing ties the
two together: an e-Post integration that only reports status would make e-Post Manual
send, System update, with no change to how it is sent.

A new delivery mechanism is added as a new channel row.

### 6.3 Which process type allows which channel

| Process type | SMS | Email | RPAD | e-Post | Police (RPAD) | Police (NSTEP) | Police (iCOPS) | By hand |
|---|---|---|---|---|---|---|---|---|
| Notice | ● | ● | ● | ● | | | | |
| Summons | ● | ● | ● | ● | ● | ● | ● | |
| Warrant | | | | | ● | ● | ● | ● |
| Proclamation | | | | | | | | ● |
| Attachment | | | | | ● | ● | ● | |
| Custom process | ● | ● | ● | ● | ● | ● | ● | ● |

Warrant and attachment are addressed to the police, so they take police channels; a
warrant may also go By hand. A proclamation is printed and affixed, so it takes By hand
only. By hand is available for warrant, proclamation and custom process only. Notice takes SMS, Email, RPAD and e-Post only — no police channel. This matrix is a default; a deployment only offers the channels
configured for it (`PRC-04`), and may narrow the matrix further.

---

## 7. Fees and payment

There are two fees:

- **Court fee** — a flat fee for each process.
- **Channel fee** — the cost of delivery. Only e-Post has one, and not at launch.

| ID | Requirement |
|---|---|
| `FEE-01` | The court fee is a flat amount per process type, set in the fee master. For some process types it may be zero (`Q-12`). |
| `FEE-02` | A channel fee applies to e-Post only. It is not in the launch scope. |
| `FEE-03` | The channel fee for an e-Post process is supplied by a fee service, treated as a black box: the system asks it for the fee and uses the amount returned. How it calculates the fee is outside this document. |
| `FEE-04` | Court fee paid on a case — at filing or in earlier rounds — is held as a single pool. A process draws from the pool, whatever channel or address the money was originally collected for. What is collected at filing is owned by [`efiling-handover.md`](efiling-handover.md). |
| `FEE-05` | On trigger, the system calculates the court fee for the round — every process in it (§3) — and deducts what is already in the pool. For each e-Post process, it gets the channel fee from the fee service (`FEE-03`). |
| `FEE-06` | Where a balance is due, the system creates a payment pending task on the party directed to take steps. Where nothing is due, the payment step is skipped. |
| `FEE-07` | Where the pool holds more than the round's court fee, the remainder stays in the pool for later rounds. Nothing is refunded. |
| `FEE-08` | A process does not move to signing until its court fee and, where it has one, its channel fee are paid. |

---

## 8. Steps — the envelope

Every RPAD and Police (RPAD) process (§3) needs its own envelope, handed in at the court
counter by the party directed to take steps — addressed to the recipient for RPAD, or to
the entered police station for Police (RPAD). Where the same recipient has two such
processes (two addresses, or RPAD plus Police (RPAD)), that is two envelopes. This happens outside
the system.

| ID | Requirement |
|---|---|
| `STP-01` | Each RPAD and Police (RPAD) process creates its own pending task on the party directed to take steps, to hand in that process's envelope. |
| `STP-02` | An **Envelope receiver** records receipt of the envelope, holding that role for the process's type and channel ([`court-roles.md`](court-roles.md)). Recording receipt closes the task. The party cannot close it. |
| `STP-03` | An RPAD or Police (RPAD) process has exactly one envelope, since a process is one channel at one address (§3). It does not move to signing until that envelope has been received. Other processes in the round do not wait on it. |

---

## 9. Signing

| ID | Requirement |
|---|---|
| `SGN-01` | A process is signed by a **Process signer** who holds that role for its process type and channel ([`court-roles.md`](court-roles.md)). Which staff sign which process types is set there, per state — a warrant may be signed by different people from a summons. Every process for the same recipient, whatever its channel or address (§3), carries the same content — it doesn't vary by channel (`TPL-01`). |
| `SGN-02` | Each manual step of a process — receive the envelope (`STP-02`), sign, send (`DSP-03`), record the outcome (`DSP-03`) — has a court-side **pending task** ([`pending-tasks-handover.md`](pending-tasks-handover.md)) for the holders of that step's role for the process's type and channel ([`court-roles.md`](court-roles.md)), open from when the step is due until it is done. Where the system does a step, no task is created. Doing a step closes its task and creates the next, in the same transaction; expiry closes any open task (`EXP-02`). A process's sign task is created once its fee (§7) and envelope (§8) prerequisites are met. How the court staff's lists of processes are built is for the implementer. |
| `SGN-03` | Each process is signed separately, with its own signature, timestamp and audit record, even where its content is identical to another process's. Several processes may be selected and signed in one action on screen; each is still signed separately underneath. |
| `SGN-04` | Signing does not dispatch the process. It moves the process to a distinct **Signed** status — signed, awaiting send — which is a separate backend stage from both Pending signature and Sent (§10), with its own timestamp. A screen may act on sign and send together in one click; the two stages are still recorded separately underneath. |

Pending task attributes — name, users, visibility, triggers — are owned by
[`pending-tasks-handover.md`](pending-tasks-handover.md).

SARAS 2.0's concept note for Gujarat routes warrant-signing to the Presiding Officer
(`SG-04` in `saras-2.0-gap-register.md`); under `SGN-01`, that is whoever holds Process
signer for warrants there.

---

## 10. Dispatch and status

| ID | Requirement |
|---|---|
| `DSP-01` | Send is a separate act from signing (`SGN-04`). Send and update status are themselves two separate steps. Each is done either by the system or by a person, set per channel (§6.2), independently of the other. |
| `DSP-02` | Where a channel's send is by the system, the system carries out the send — but it is still its own action, separate from signing (`SGN-04`). Whether a screen sends straight after signing or waits for a separate send action is a UI decision. Sign-and-send in one click is offered only to someone who holds both Process signer and Process dispatcher for that process (`SGN-01`, `DSP-03`); anyone else signs, and the process waits at Signed for a dispatcher. Where a channel's status update is by the system, the system updates the process's status from what the receiving system reports — by polling or by callback. |
| `DSP-03` | A **Process dispatcher** sends a process. Where the channel's send is manual, they mark it sent once the document has actually left in that form. Where the send is by the system, they click Send, and the system carries out the send (`DSP-02`). Where a channel's status update is manual, a **Process reporter** records the outcome when the acknowledgement, tracking update or report comes back; where it is by the system, the system is the reporter. Each person must hold that role for the process's type and channel ([`court-roles.md`](court-roles.md)); the dispatcher and reporter may be different people. |
| `DSP-04` | Every process carries its own status, status date and remark, independent of every other process — including another process for the same recipient (§3). There is no status that spans several processes. |
| `DSP-05` | A process's status moves through the vocabulary in §10.1 only. |
| `DSP-06` | A process is closed when it reaches a terminal status, or when the expiry date passes (§11). |
| `DSP-07` | A process's non-delivery does not create a new process. A fresh process requires a fresh order, which starts a new round. |
| `DSP-08` | Setting a process to a terminal outcome status carries the status itself (§10.1), a free-text comment, and an optional supporting file upload. This applies whether the status arrives through a person's manual entry or through an automatic webhook/poll report. |
| `DSP-09` | Where the status set is negative — Not delivered or Not executed — an additional **reason** field is required, chosen from a dropdown. The reason list is a state-configurable master, not a fixed enum in this document. |
| `DSP-10` | A proclamation By hand is signed, then sent, then Executed — three stages, each recorded separately. Since all that happens physically is that the signed copy is printed and affixed, a screen may record Sent and Executed together once the signed copy is downloaded. However a proclamation is published — affixed, or in a newspaper — it is recorded Executed; publication in a newspaper is not tracked separately. |

### 10.1 Process status vocabulary

| Status | Terminal | Meaning |
|---|---|---|
| Pending | no | The process is signed but not yet dispatched — or a prerequisite (fee, envelope) is still outstanding. |
| Sent | no | Dispatched. |
| Delivered | yes | Reached its destination. Depending on the channel: for SMS and Email, whatever is decided at implementation (§6.2); an acknowledgement card signed and returned; a Process reporter's recorded outcome for e-Post; a service/execution report from the station; a Process reporter's recorded outcome for By hand. |
| Not delivered | yes | The attempt reached the destination and failed — refused, addressee not found, returned undelivered. The reason is recorded as the remark. |
| Errored | yes | Could not be carried at all — invalid number, the receiving system rejected it. Distinct from Not delivered, where an attempt was made at the destination. |
| Expired | yes | The expiry date passed with no outcome recorded. |
| Recalled | yes | The process was recalled by a Process dispatcher before an outcome was reached (`PIA-01`). |

For warrant, proclamation and attachment, **Delivered** is labelled *Executed* and **Not
delivered** is labelled *Not executed*. The underlying status is the same.

---

## 11. Expiry

| ID | Requirement |
|---|---|
| `EXP-01` | Every process carries an expiry date. By default it is midnight at the end of the day before its hearing (`PRC-06`) — that is, 00:00 IST on the hearing date. |
| `EXP-01a` | If the hearing date changes before a process is signed, its expiry date moves with it (`EXP-01`). Once a process is signed, its expiry date does not change, and nothing else is done to it. |
| `EXP-02` | When the expiry date passes, the system closes every pending task open on the process, and, if it has no outcome yet, marks it Expired and closes it. |
| `EXP-03` | A process that expires before it is signed, or that is Signed but expires before it is sent, is never dispatched. |

---

## 12. Post-issue actions

A signed, dispatched process may be overtaken by events.

| ID | Requirement |
|---|---|
| `PIA-01` | **It is no longer wanted** — for example, the court recalls a warrant or grants bail. A **Process dispatcher** recalls it, process by process: they choose one or more processes that have no outcome yet, sent or not, and each chosen process is marked Recalled. A process recalled before it is sent is never dispatched — in effect, a cancellation — and any task open on it closes. A screen may suggest selecting every such process for that recipient in that round, but the choice is the dispatcher's. For a sent process: where the channel's send is by the system, recalling tells the receiving system; where it is manual, the dispatcher recalls it once the recall has been communicated. |

When the hearing date moves, an unsigned process's expiry moves with it and a signed
process's stays, and nothing else is done to a signed process (`EXP-01a`).

---

## 13. What varies by state

### 13.1 Available channels

Which channels each state offers (`PRC-04`): **At launch**, **Post-launch** or **Never**.
Each channel's send and status update are set as System or Manual in §6.2.

| Channel | Kerala | Gujarat | Punjab & Haryana |
|---|---|---|---|
| SMS | At launch | At launch | At launch |
| Email | Post-launch | Post-launch | Post-launch |
| RPAD | At launch | At launch | At launch |
| e-Post | Post-launch | Post-launch | Post-launch |
| Police (RPAD) | At launch | At launch | At launch |
| Police (NSTEP) | Never — Police (iCOPS) in its place | At launch | At launch |
| Police (iCOPS) | At launch | Never — iCOPS is Kerala's | Never — iCOPS is Kerala's |
| By hand | At launch | At launch | At launch |

### 13.2 Court fee per process type

The flat court fee per process type (`FEE-01`), per state, as entered in the fee master. A
fee may be zero — a state that collects nothing more at the process stage sets it to zero.

| Process type | Kerala | Gujarat | Punjab & Haryana |
|---|---|---|---|
| Notice | ₹2 | To be confirmed | To be confirmed |
| Summons | ₹2 | To be confirmed | To be confirmed |
| Warrant | ₹2 | To be confirmed | To be confirmed |
| Proclamation | ₹0 | To be confirmed | To be confirmed |
| Attachment | ₹0 | To be confirmed | To be confirmed |
| Custom process | ₹0 | To be confirmed | To be confirmed |

What is collected at filing is owned by [`efiling-handover.md`](efiling-handover.md). Who
holds which role is in [`court-roles.md`](court-roles.md) §3.

---

## Linked records

Live views of the master tables, filtered to this document. Each master table is the
single source of truth and the place to edit its rows; anything tagged
`process-handover` there appears here automatically. A downloaded copy of this
document is a snapshot.

### Pending tasks (Court Side)

```superhuman-view
name: Pending tasks (Court Side) — Process
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("process-handover")
```

The four court-side tasks (`SGN-02`): Receive envelope, Sign, Send and Record outcome.

### Pending tasks (Citizen-Side)

```superhuman-view
name: Pending tasks (Citizen-Side) — Process
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("process-handover")
```

### Notifications

```superhuman-view
name: Notifications — Process
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-xnftvTkudd/tables/grid-3FTjQhdfYv
filter: PRDs.Contains("process-handover")
```

Three process notifications — steps due, outcome recorded, recalled. Errored and Expired
send no notification.

### Events

```superhuman-view
name: Events — Process
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-2x28DoUtbn/tables/grid-GPg4dKS-s9
filter: PRDs.Contains("process-handover")
```

---

## 14. Open questions

| # | Question | Blocking? |
|---|---|---|
| `Q-12` | What is the court fee for each process type in Gujarat and in Punjab & Haryana (§13.2)? Kerala's is set. | No |
| `Q-15` | The police-station master data for all the states (`PRC-08`) is yet to be received. | No |
| `Q-16` | What is the format of each process type — the PDF template for notice, summons, warrant, proclamation, attachment and custom process (`TPL-01`)? | Yes |
