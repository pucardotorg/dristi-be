# e-Post — post offices and routing

**Status:** v1 — 2026-11-05; first draft, not yet reviewed. Covers only what e-Post needs
beyond [`process.md`](process.md) when a deployment works with several post offices and
several Post officer accounts. Based on the Department of Posts' PIN-code list for
Haryana Circle and its rates letter of 3 November 2026 to the Punjab & Haryana High
Court, both received 4 November 2026. How a process is routed to a post office is not yet
decided (`Q-1` to `Q-4`).

---

## 1. Context

e-Post is one of the process channels. Everything about it that does not depend on which
post office handles a process is already in [`process.md`](process.md), and is not
repeated here:

- what e-Post is, and that it goes to the recipient's postal address (§A5, §6.2)
- which process types may use it (§6.3)
- that a Process dispatcher marks it sent and a Process reporter records the outcome,
  both done manually (§6.2, `DSP-03`)
- statuses, expiry and recall (§10, §11, §12)
- the channel fee, which comes from a fee service (§7, `FEE-02`, `FEE-03`)
- when each state offers e-Post (§13.1).

The Post officer holds Process dispatcher and Process reporter for e-Post in every state
([`court-roles.md`](court-roles.md) §3).

This document adds what is needed once there is more than one post office and more than
one Post officer account: which post office each e-Post process goes to, and which Post
officers can act on it.

### 1.1 What has been agreed with the Department of Posts

So far this applies to Punjab & Haryana only. On 3 November 2026 the Department of Posts,
Haryana Circle, wrote to the Registrar General of the Punjab & Haryana High Court, recording
what was decided at a meeting on 15 October 2026, for a pilot at District Court,
Panchkula:

- e-Post is not integrated with the Department of Posts' systems. Post office staff log
  in to the platform.
- Post office staff download and print the notices and summons, do the Business Post
  work (printing, enveloping), and book each item as Speed Post.
- The Department of Posts charges for printing, Business Post, the envelope and Speed
  Post. Speed Post is charged by weight and by distance band.

There will be several Post officer accounts, not one.

---

## 2. Where routing fits

```
An order starts an e-Post process (process.md §5)
        │
        ▼
Steps, fee and signing as for any process (process.md §7, §9)
        │
        ▼
The process is routed to one post office (§3) ── how: Q-1
        │
        ▼
A Post officer of that post office downloads and prints it, sends it as
Speed Post and marks it sent (process.md DSP-03)
        │
        ▼
A Post officer of that post office records the outcome (process.md DSP-03)
```

---

## 3. Requirements

| ID | Requirement |
|---|---|
| `EPR-01` | A **post-office master** is held per deployment, listing the post offices that handle e-Post, with the attributes in §4. `[DERIVED]` |
| `EPR-02` | Each e-Post process is routed to exactly one post office in the master. What decides which one is `Q-1`. `[DERIVED]` |
| `EPR-03` | Each Post officer account is linked to one or more post offices in the master. A Post officer can see, download, mark sent and record the outcome only for e-Post processes routed to a post office they are linked to. `[DERIVED]` |

---

## 4. The post-office master

The attributes below are those in the Department of Posts' list for Haryana Circle. Which
of them routing uses depends on `Q-1`.

| Attribute | What it holds |
|---|---|
| Office name | The post office's name, for example *Panchkula Sector 8 S.O* |
| PIN code | The post office's PIN code. One PIN code may have several post offices |
| District | The revenue district the post office is in |
| Division | The postal division the post office belongs to, for example *Ambala Division* |
| Office type | General Post Office, Head Post Office or Sub Post Office |

In the Haryana Circle list: 506 post offices (1 General Post Office, 14 Head Post
Offices, 491 Sub Post Offices) in 9 postal divisions, covering 319 PIN codes. 58 of those
PIN codes have more than one post office — 132001, for example, has 15.

### 4.1 What each state has sent

| State | Post-office list |
|---|---|
| Punjab & Haryana | Haryana Circle received 4 November 2026. Nothing for Punjab or Chandigarh yet |
| Gujarat | Not received |
| Kerala | Not received |

---

## Linked records

Live views of the master tables, filtered to this document. Each master table is the
single source of truth and the place to edit its rows; anything tagged `e-post` there
appears here automatically. A downloaded copy of this document is a snapshot.

### Pending tasks (Court Side)

```superhuman-view
name: Pending tasks (Court Side) — e-Post
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("e-post")
```

### Pending tasks (Citizen-Side)

```superhuman-view
name: Pending tasks (Citizen-Side) — e-Post
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("e-post")
```

### Notifications

```superhuman-view
name: Notifications — e-Post
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-xnftvTkudd/tables/grid-3FTjQhdfYv
filter: PRDs.Contains("e-post")
```

### Events

```superhuman-view
name: Events — e-Post
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-2x28DoUtbn/tables/grid-GPg4dKS-s9
filter: PRDs.Contains("e-post")
```

---

## 5. Open questions

| ID | Question | Blocking |
|---|---|---|
| `Q-1` | What decides which post office a process goes to? The Department of Posts' list maps PIN codes to post offices, which suggests the recipient's PIN code, but this has not been decided. If it is the post office that prints and books the item, it could instead be one office near the court (the letter names a pilot at District Court, Panchkula), with Speed Post carrying it on from there. | Yes |
| `Q-2` | Where a PIN code has several post offices (58 PIN codes in the Haryana list), which one gets the process? | Yes, if `Q-1` is by PIN code |
| `Q-3` | Where the recipient's address is outside the deployment's postal circle, or its PIN code is not in the master, where does the process go — and is e-Post offered for it at all? | Yes |
| `Q-4` | Can a process be moved to another post office after routing — for example, when a Post officer finds it is not theirs — and who may move it? | No |
| `Q-5` | Is a Post officer linked to post offices only, or also to courtrooms, as court staff roles are ([`court-roles.md`](court-roles.md) `RLE-02a`)? Does `EPR-03` need a change to `RLE-09` in court-roles? | Yes |
| `Q-6` | Who creates Post officer accounts and links them to post offices ([`account-creation.md`](account-creation.md))? | No |
| `Q-7` | Post-office lists are still to be received for Punjab, Chandigarh, Gujarat and Kerala (§4.1). | No |
| `Q-8` | The Haryana list needs cleaning before it is loaded: "Hisar Division" and "Hissar Division" both appear, and some district names differ only in capitals ("Rewari", "REWARI"). | No |
| `Q-9` | The rates in the 3 November 2026 letter (printing per page, Business Post per item, envelope, Speed Post by weight and distance) are what the e-Post channel fee will be worked out from. No document owns them yet: the fee service is a black box (process `FEE-03`), and [`payment-logic.md`](payment-logic.md) holds only how many rounds of channel fee are paid upfront. The Speed Post charge depends on the distance from the booking post office, so the fee depends on which post office books the item (`Q-1`). | No — no channel fee at launch |
