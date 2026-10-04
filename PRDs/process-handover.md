# Process — Notice, Summons, Warrant, Proclamation, Attachment

**Status:** v10 — 2026-09-30; **police is now a channel, not a flag.** The channels are
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
attachment, or a custom process. The court issues it; the court does not deliver it.
Delivery is done by the post office, the police, or a messaging service, and what the
court holds afterward is a record of what it sent, where, and what came back.

## A2. What the judge enters

For every process, per recipient:

1. **The recipient** — always entered: the accused, the witness, whoever the process
   names.
2. **The channels** — one or more of SMS, Email, RPAD, e-Post, Police (RPAD), and
   Police (NSTEP) or Police (iCOPS). Which channels are available is configured per
   deployment.
3. **The police station** — entered for a police channel only.

Police is a channel of its own, not a setting on the others. On a police channel the
process goes to the police station, and the police serve or execute it on the recipient.
A warrant, proclamation or attachment is addressed to the police, so these take police
channels only.

**The document** is set by the process type and the recipient. It is the same on every
channel. Different templates per channel may come later; they are not in scope now.

## A3. The lifecycle, start to finish

```
Judge issues the order, entering per recipient the channels and, for a
police channel, the police station. Each recipient fans out into one process
per channel, per address (§3) — the rest of this line runs per process,
independently
        │
        ▼
System calculates the court fee, net of what is already in the case's pool,
and, for e-Post, the channel fee (§7)
        │
        ├── balance due ──▶ the party directed to take steps pays        ┐
        │                                                                 │ pending
        ├── RPAD or Police (RPAD) ──▶ that party hands in the envelope   │ tasks;
        │   at the court counter (Pending RPAD collection)                │ the
        ▼                                                                 ┘ process
CMO or Magistrate signs (by process type) — now Signed, awaiting send      expires
        │                                                                   if these
        ▼                                                                   aren't
Step 1 — Send. By the system (an API call), or by a person who marks it    done by
sent. Set per channel                                                       the
        │                                                                   expiry
        ▼                                                                   date
Step 2 — Update status. By the system (the receiving system reports back),
or by a person who records the outcome — status, reason if negative, a
comment, an optional file. Set per channel, separately from step 1
        │
        ▼
This one process reaches its own outcome and closes on it — or on the expiry
date, whichever comes first. Every other process fanned out from the same
recipient (§3) runs this same line independently, on its own channel
```

## A4. Who does the manual work

- **The CMO or the Magistrate** signs, depending on the process type — a warrant is
  signed by the Magistrate (§9).
- **The CMO** runs the manual steps for RPAD and
  Police (RPAD): collecting the envelope, marking it sent, recording the outcome.
- **The Post Officer** — a separate login from the CMO — does the same for e-Post, once
  it is signed: marks it sent and records the outcome. There is no envelope step for
  e-Post.
- The employee-side **Sign process** screen is where the CMO's queue of this work
  actually lives — Pending RPAD collection → Pending sign → Signed → Sent → Completed —
  already built for physical post; see
  [`sign-process.md`](../Pucar-Dristi-2.0/docs/design/proposals/sign-process.md). §9
  confirms the same Signed/Sent split holds for every channel, not physical post alone.

## A5. The channels, in plain terms

Every channel has two steps: **send**, and **update status**. Each is done either by the
system or by a person, and a channel can mix them — sent by hand, status by API, or the
reverse.

- **SMS / Email** — to the recipient's phone or email address. The system sends it and
  tracks it; nobody at the court acts unless the outcome needs recording.
- **RPAD** — physical post to the recipient. The party directed to take steps hands in an
  envelope at the counter; the CMO marks it posted and records the outcome from
  the acknowledgement card.
- **e-Post** — the electronic equivalent of RPAD, to the recipient. The Post Officer does
  what court staff do for RPAD: marks it sent and records the outcome.
- **Police (RPAD)** — RPAD to the entered police station. Same envelope and CMO steps as
  RPAD; the outcome is the station's service or execution report.
- **Police (NSTEP)** — to the entered police station through NSTEP. The document goes out
  via CIS in an end-of-day batch, and the system polls CIS for the result.
- **Police (iCOPS)** — Kerala's equivalent, in place of Police (NSTEP): the police system
  is called directly, and calls back with the result.

---

# Part B — Requirements

## 1. Context

A **process** is an instrument the court issues to a person to bring them before it, put
them on notice, or compel an act on them. This document specifies how a process is
created, paid for, signed, dispatched and tracked, for every process type in the Process
category of the order catalogue.

The court issues the instrument; it does not deliver it. Delivery is done by the post
office, the police, or a messaging service, and what the court holds is a record of what
it sent, where, and what came back. That record is the subject of this document.

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

A process type does not itself fix who it may be addressed to — that is a
configuration-level restriction, not a structural fact of the type, and it is set from
the UI rather than hardcoded here. Today's default restricts proclamation and
attachment to the accused; notice, summons and custom process are open to whichever
party the order names. A state may tighten or loosen these without a schema change.

Order templates, their locked variables and the dropdown behaviour are owned by
[`order-template-catalogue.md`](order-template-catalogue.md).

While a process is live, the case carries the matching **secondary stage** — Notice,
Summons, Warrant, Proclamation or Attachment. Stage rules are owned by
[`case-lifecycle-handover.md`](case-lifecycle-handover.md).

The **recipient** (addressee) never changes — it's who a summons is for, who a warrant is
against. On a police channel the process goes to the entered police station, but the
recipient is still the person it names.

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
Judge issues order, entering channels per recipient, and the police station
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
        │   envelope at the court counter (Pending RPAD      │  expires if these
        │   collection, §8)                                  │  are not done by
        ▼                                                    ┘  the expiry date
CMO or Magistrate signs, by process type (§9) — the process is now Signed,
awaiting send
        │
        ▼
Send — a distinct backend stage from signing, even where one screen or one
click carries out both (§9, §10). By the system, or by a person who marks
it sent — set per channel (§6.2)
        │
        ▼
Update status — a separate step from send. By the system, from what the
receiving system reports, or by a person who records the outcome —
status, reason (if negative), a comment and an optional file — when the
acknowledgement or report returns. Set per channel, independently of send
        │
        ▼
This process reaches its own outcome and closes on it, or on the expiry
date, whichever comes first — independently of every other process fanned
out from the same recipient
```

The spine is the same for every process type and every channel. Three things vary:
whether each of send and update status is done by the system or by a person, and which
person (§6.2, §10); and whether the process admits post-issue judicial action (§12).

---

## 5. Trigger and channel selection

| ID | Requirement |
|---|---|
| `PRC-01` | Issuing an order of a Process-category type triggers the process workflow. |
| `PRC-02` | One process is created per recipient, per selected channel, per address (§3). Where the drawer is a company, the company and every person in charge are each a separate recipient, shown as separate options in the recipient dropdown on the order screen (`PRC-03`), and each fanning out the same way. |
| `PRC-03` | The judge enters, per recipient, on the order screen: the recipient, and the delivery channels. For a police channel — Police (RPAD), Police (NSTEP) or Police (iCOPS) — the police station is also entered. At least one channel is required. Several channels may be selected for the same recipient, each becoming its own process, used simultaneously. |
| `PRC-04` | Which channels are available is configured per deployment (§13). The channels offered are those available in the deployment and permitted for the process type (§6.3). |
| `PRC-05` | Each process's destination is taken from the recipient's own record — a mobile number, an email address, or one postal address — or, on a police channel, from the entered police station. Where a recipient's record holds more than one address of the kind a selected channel uses, one process is created per address (`PRC-02`). A channel cannot be selected where the record holds no destination of that kind. |
| `PRC-06` | The process is associated with the hearing set in the same order. A warrant does not print that hearing's date: it carries a QR code and a line of text telling the reader to scan it for the latest hearing date. Screens may show the hearing's current date rather than the date at issue. |
| `PRC-07` | The party directed to take steps is worked out by the system wherever it can (`AUT-02`), and is named in the order. That party bears the fees (§7) and the envelope obligation (§8). |
| `PRC-08` | A police-station master is required for every state. It maps an address to the police station with jurisdiction over it, and is what the police station on a police channel is chosen from (`AUT-04`). |

Whether that master holds police stations or the jurisdictional
Superintendent/Commissioner's offices, per BNSS §80, is `SG-09` in
[`saras-2.0-gap-register.md`](../docs/saras-2.0-gap-register.md).

### 5.1 What the system fills in

The system fills in and pre-selects whatever it can on the order screen, so the judge or
court staff issuing the process only choose where the system cannot tell. This happens in
the pop-up that opens when a Process-category order item is selected.

| ID | Requirement |
|---|---|
| `AUT-01` | Wherever a value on the order screen can be worked out from the case, the system fills it in or pre-selects it. It is only shown as an open choice when the system cannot work it out. |
| `AUT-02` | The party directed to take steps is worked out from the recipient: for the accused, the complainant; for the complainant, the accused; for a witness associated with one side, that side. |
| `AUT-03` | Where the system cannot work out the party directed to take steps — for example, a witness added by the court — it is shown to the judge as a choice. |
| `AUT-04` | On a police channel, the police station is pre-selected from the recipient's address, using the police-station master (`PRC-08`). Where the address does not resolve to one police station, it is shown to the judge as a choice. |
| `AUT-05` | **Until the accused has joined the case**, the pop-up pre-selects the accused as the recipient. Where there is more than one accused, every accused is pre-selected. |
| `AUT-06` | **Once the accused has joined the case**, the pop-up pre-selects the witness where exactly one witness has not yet been examined. Otherwise no recipient is pre-selected and the choice is left open. |
| `AUT-07` | Every address on a selected recipient's record is pre-selected, before and after the accused has joined. |
| `AUT-08` | Channels are pre-selected by process type: SMS, Email and RPAD for notice and summons; Police (NSTEP) for warrant, proclamation and attachment — Police (iCOPS) in a deployment that runs it in place of Police (NSTEP) (`PRC-04`). Channels are chosen once for every recipient selected; a recipient whose record holds no destination of a channel's kind gets no process on it, and the pop-up says so beside them (`PRC-05`). |
| `AUT-09` | The pop-up may select several recipients for the same process at once. This is a convenience of the screen only: each recipient still resolves to one process per channel, per address (`PRC-02`, §3). |

Further fill-in and pre-selection rules are added to this section as they are defined.

---

## 6. Delivery channels

### 6.1 The document

| ID | Requirement |
|---|---|
| `TPL-01` | The process document's template is set by the process type and the recipient. The same template is used on every channel. |

Different templates per channel may be added later. That is not in scope for this
version.

### 6.2 The channels

Every channel has two separate steps — **send** and **update status** — and each is set
per channel as either **System** or **Manual**, independently of the other (`DSP-01`).

| Channel | Goes to | Send | Update status |
|---|---|---|---|
| SMS | The recipient's mobile number | System — messaging gateway | System — gateway delivery receipt |
| Email | The recipient's email address | System — email service | See `Q-9` |
| RPAD | The recipient's postal address | Manual — the CMO marks it sent once the envelope handed in (Pending RPAD collection, §8) is posted | Manual — the CMO records the outcome from the acknowledgement card |
| e-Post | The recipient's postal address | Manual — the Post Officer, a separate login from the CMO, marks it sent | Manual — the Post Officer records the outcome |
| Police (RPAD) | The entered police station's postal address | Manual — the CMO marks it sent once the envelope (§8) is posted | Manual — the CMO records the station's service or execution report |
| Police (NSTEP) | The entered police station, through NSTEP | System — via CIS in an end-of-day batch | System — polls CIS periodically |
| Police (iCOPS) | The entered police station, through Kerala's iCOPS | System — directly to iCOPS | System — iCOPS calls back (a push, not a poll) |

Today every channel is either System for both steps or Manual for both. Nothing ties the
two together: an e-Post integration that only reports status would make e-Post Manual
send, System update, with no change to how it is sent.

A new delivery mechanism is added as a new channel row. Gujarat's SARAS 2.0 concept note
proposes a **police return portal** — an OTP-gated link the executing officer submits a
report through (`SG-10`) — which would be one such row, with its status update entered by
the executing officer through the portal.

### 6.3 Which process type allows which channel

| Process type | SMS | Email | RPAD | e-Post | Police (RPAD) | Police (NSTEP) | Police (iCOPS) |
|---|---|---|---|---|---|---|---|
| Notice | ● | ● | ● | ● | | | |
| Summons | ● | ● | ● | ● | ● | ● | ● |
| Warrant | | | | | ● | ● | ● |
| Proclamation | | | | | ● | ● | ● |
| Attachment | | | | | ● | ● | ● |
| Custom process | ● | ● | ● | ● | ● | ● | ● |

Warrant, proclamation and attachment are addressed to the police, so they take police
channels only. Notice takes SMS, Email, RPAD and e-Post only — no police channel. This matrix is a default; a deployment only offers the channels
configured for it (`PRC-04`), and may narrow the matrix further. It is not yet
confirmed — see `Q-1`.

---

## 7. Fees and payment

There are two fees:

- **Court fee** — a flat fee for each process.
- **Channel fee** — the cost of delivery. Only e-Post has one, and not at launch.

| ID | Requirement |
|---|---|
| `FEE-01` | Every process carries a flat court fee, set per process type in the fee master. A process type may have no court fee (`Q-12`). |
| `FEE-02` | A channel fee applies to e-Post only. It is not in the launch scope. |
| `FEE-03` | The channel fee for an e-Post process is supplied by a fee service, treated as a black box: the system asks it for the fee and uses the amount returned. How it calculates the fee is outside this document. |
| `FEE-04` | Court fee paid on a case — at filing or in earlier rounds — is held as a single pool. A process draws from the pool, whatever channel or address the money was originally collected for. What is collected at filing is owned by [`efiling-scrutiny-registration-handover.md`](efiling-scrutiny-registration-handover.md). |
| `FEE-05` | On trigger, the system calculates the court fee for the round — every process in it (§3) — and deducts what is already in the pool. For each e-Post process, it gets the channel fee from the fee service (`FEE-03`). |
| `FEE-06` | Where a balance is due, the system creates a payment pending task on the party directed to take steps. Where nothing is due, the payment step is skipped. Whether the court fee and channel fee are one payment or two is `Q-13`. |
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
| `STP-02` | Court staff record receipt of the envelope. Recording receipt closes the task. The party cannot close it. |
| `STP-03` | An RPAD or Police (RPAD) process has exactly one envelope, since a process is one channel at one address (§3). It does not move to signing until that envelope has been received. Other processes in the round do not wait on it. |

---

## 9. Signing

| ID | Requirement |
|---|---|
| `SGN-01` | Who signs is set by the process type: the CMO or the Magistrate. A warrant is signed by the Magistrate. Notice, summons, proclamation, attachment and custom process are signed by the CMO (see `Q-11`). Every process for the same addressee, whatever its channel or address (§3), carries the same content — it doesn't vary by channel (`TPL-01`). |
| `SGN-02` | Once its fee (§7) and envelope (§8) prerequisites are met, a process is listed at Pending signature for the signer for that process type (`SGN-01`). Court-side work on a process — signing, marking sent, recording the outcome, recording that a recall was communicated — is not a pending task. It is a list of processes, segregated by status. |
| `SGN-03` | Each process is signed separately, with its own signature, timestamp and audit record, even where its content is identical to another process's. Several processes may be selected and signed in one action on screen; each is still signed separately underneath. |
| `SGN-04` | Signing does not dispatch the process. It moves the process to a distinct **Signed** status — signed, awaiting send — which is a separate backend stage from both Pending signature and Sent (§10), with its own timestamp. A screen may act on sign and send together in one click; the two stages are still recorded separately underneath. |

Citizen-side pending task attributes — name, users, visibility, triggers — are owned by
[`pending-tasks-handover.md`](pending-tasks-handover.md). The employee-side **Sign
process** screen already builds this staging for physical post — Pending RPAD
collection → Pending sign → Signed → Sent → Completed; see
[`sign-process.md`](../Pucar-Dristi-2.0/docs/design/proposals/sign-process.md). `SGN-04`
confirms the Signed/Sent split generalises to every channel, not physical post alone.

`SGN-01`'s warrant rule matches SARAS 2.0's concept note for Gujarat, which routes
warrant-signing to the Presiding Officer (`SG-04` in `saras-2.0-gap-register.md`).

---

## 10. Dispatch and status

| ID | Requirement |
|---|---|
| `DSP-01` | Send is a separate act from signing (`SGN-04`). Send and update status are themselves two separate steps. Each is done either by the system or by a person, set per channel (§6.2), independently of the other. |
| `DSP-02` | Where a channel's send is by the system, the system sends the process as soon as it is Signed; no court user acts to send it. Where a channel's status update is by the system, the system updates the process's status from what the receiving system reports — by polling or by callback. |
| `DSP-03` | Where a channel's send is manual, a person marks the process sent once the document has actually left in that form. Where a channel's status update is manual, a person records the outcome when the acknowledgement, tracking update or report comes back. Who that person is, per channel, is in §6.2 — the CMO for RPAD and Police (RPAD), the Post Officer for e-Post. |
| `DSP-04` | Every process carries its own status, status date and remark, independent of every other process — including another process for the same addressee (§3). There is no status that spans several processes. |
| `DSP-05` | A process's status moves through the vocabulary in §10.1 only. |
| `DSP-06` | A process is closed when it reaches a terminal status, or when the expiry date passes (§11). |
| `DSP-07` | A process's non-delivery does not create a new process. A fresh process requires a fresh order, which starts a new round. |
| `DSP-08` | Setting a process to a terminal outcome status carries the status itself (§10.1), a free-text comment, and an optional supporting file upload. This applies whether the status arrives through a person's manual entry or through an automatic webhook/poll report. |
| `DSP-09` | Where the status set is negative — Not delivered or Not executed — an additional **reason** field is required, chosen from a dropdown. The reason list is a state-configurable master, not a fixed enum in this document. |

`SG-10` in `saras-2.0-gap-register.md` proposes a manual police return portal for Gujarat
instead of a system-to-system police integration (§6.2). If confirmed, the portal is a
new channel whose status update comes from the executing officer through the portal —
a new row in §6.2, not a change to `DSP-02`.

### 10.1 Process status vocabulary

| Status | Terminal | Meaning |
|---|---|---|
| Pending | no | The process is signed but not yet dispatched — or a prerequisite (fee, envelope) is still outstanding. |
| Sent | no | Dispatched. |
| Delivered | yes | Reached its destination. Depending on the channel: a gateway delivery receipt; an acknowledgement card signed and returned; a Post Officer's recorded outcome for e-Post; a service/execution report from the station. |
| Not delivered | yes | The attempt reached the destination and failed — refused, addressee not found, returned undelivered. The reason is recorded as the remark. |
| Failed | yes | Could not be carried at all — invalid number, the receiving system rejected it. Distinct from Not delivered, where an attempt was made at the destination. |
| Expired | yes | The expiry date passed with no outcome recorded. |
| Recalled | yes | The process was recalled before an outcome was reached (§11). |

For warrant, proclamation and attachment, **Delivered** is labelled *Executed* and **Not
delivered** is labelled *Not executed*. The underlying status is the same.

---

## 11. Expiry

| ID | Requirement |
|---|---|
| `EXP-01` | Every process carries an expiry date. |
| `EXP-02` | When the expiry date passes, the system closes every pending task open on the process, and, if it has no outcome yet, marks it Expired and closes it. |
| `EXP-03` | A process that expires before it is signed, or that is Signed but expires before it is sent, is never dispatched. |

---

## 12. Post-issue actions

A signed, dispatched process may be overtaken by events. Two cases are handled.

| ID | Requirement |
|---|---|
| `PIA-01` | **It is no longer wanted.** The judge recalls the warrant or grants bail. The system marks every process for that addressee, in that round, Recalled — not just the one a court user happens to be looking at. Where the channel's send is by the system, the receiving system is told; where it is manual, the CMO or Post Officer records that the recall was communicated. |
| `PIA-02` | **The hearing date changes.** A warrant does not print its date (`PRC-06`), so nothing on it becomes wrong. No replacement is generated, signed or dispatched; the warrant stays live, and the QR code shows the new date. |
| ~~`PIA-03`~~ | ~~Replacement process rules.~~ Removed 2026-10-01 — there is no replacement process (`PIA-02`). |

`PIA-01` and `PIA-02` apply to warrants. Whether a summons, notice or custom process also
carries a QR code in place of a printed date is open — see `Q-4`.

---

## 13. What varies by state

| Aspect | Kerala | Gujarat and Punjab |
|---|---|---|
| Channels available (configured per deployment, `PRC-04`) | Police (iCOPS) in place of Police (NSTEP); the rest to be confirmed | To be confirmed |
| Where the court fee is collected | At filing, with the balance for the round collected at the process stage | To be confirmed — possibly entirely at filing |
| Envelope handed in at the counter | Yes, for RPAD and Police (RPAD) | To be confirmed |
| Send and update status | Both manual for RPAD, Police (RPAD) and e-Post; both by the system for SMS, Email and Police (iCOPS), where configured | Expected to be automatic end to end, but see `SG-10`'s manual-portal alternative |
| Who signs a warrant | The Magistrate (`SGN-01`) | The Magistrate (`SGN-01`); SARAS 2.0 names the Presiding Officer (`SG-04`) |

Where the court, the post office and the police run on a connected system, the envelope
step and the manual status steps fall away and the flow is the automatic path throughout.
Which of Gujarat and Punjab this is true for, and for which channels, is `Q-5`.

---

## Linked records

Live views of the master tables, filtered to this document. Each master table is the
single source of truth and the place to edit its rows; anything tagged
`process-handover` there appears here automatically. A downloaded copy of this
document is a snapshot.

### Pending tasks (Citizen-Side)

```superhuman-view
name: Pending tasks (Citizen-Side) — Process
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("process-handover")
```

---

## 14. Open questions

| # | Question | Blocking? |
|---|---|---|
| `Q-1` | Confirm the channel-by-process-type matrix in §6.3. | Yes |
| `Q-2` | A proclamation is published by affixation at the addressee's house and at the courthouse, and sometimes in a newspaper. None of these are in the channel list. How are they represented and tracked? | Yes |
| ~~`Q-3`~~ | ~~Do SMS and WhatsApp carry a fee, or are they free?~~ Resolved 2026-09-30 — only e-Post has a channel fee, and not at launch (`FEE-02`). | — |
| `Q-4` | Does a summons, notice or custom process carry a QR code in place of a printed hearing date, as a warrant does (`PRC-06`)? If not, what happens to a live one when the hearing date moves? | Yes |
| `Q-5` | For Gujarat and Punjab, which steps does the connected system remove — the envelope, the party payment, the manual status recording, or all three? | No |
| `Q-6` | What sets the expiry date on a process — the returnable hearing date, a fixed period from issue, or the judge? | Yes |
| `Q-7` | Where a process expires unpaid or unsigned, what happens to money already paid for that round? | No |
| `Q-8` | Which of Gujarat, Punjab and Sikkim have, or plan, NSTEP for police service, a manual return portal (`SG-10`), or neither? | No |
| `Q-9` | For Email, what counts as Delivered — the email service's delivery report, or something more? | No |
| `Q-11` | Confirm the signer for proclamation and attachment — CMO, as `SGN-01` has it, or the Magistrate like a warrant? | Yes |
| `Q-12` | Which process types, if any, carry no court fee? | No |
| `Q-13` | Are the court fee and the channel fee collected as one payment or as separate payments? | No |
| `Q-14` | What does the warrant's QR code open, and can a police officer see the hearing date there without logging in? | Yes |
