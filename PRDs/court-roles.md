# Court roles

**Status:** v10.2 — 2026-10-25; new §4 *Open questions*, with `Q-1` (who signs proclamation and attachment), moved from the process handover. v10.1 — 2026-10-25; new role **Envelope receiver** — records receipt of the RPAD and Police (RPAD) envelope ([`process-handover.md`](process-handover.md) `STP-02`); held by the Bench clerk / Reader in all three states (§3). v10 — 2026-10-25; **process roles are held per process type and channel** (`RLE-09`). New role **Process reporter** records the outcome; **Process dispatcher** now only marks sent and records a recall; **Warrant signer** is removed — the Magistrate holds Process signer for warrants, and the Bench clerk / Reader holds it for every other process type (§3). Wherever a title held Process dispatcher, it now also holds Process reporter, for the same scope. On a system-send channel the dispatcher clicks Send rather than marking sent; the dispatcher recalls processes, sent or not, one or more at a time; where the status update is by the system, the system is the reporter. v9.4 — 2026-10-22; **Evidence marker** no longer marks as void, is owned by [`document-submission.md`](document-submission.md), and is held by every court-side staff title in all three states for now. v9.3 — 2026-10-20; **Account approver** is held by the Scrutiny officer in Gujarat and the Ahlmad in Punjab & Haryana (§3); Kerala still names no holder. **Process dispatcher** is held by the Reader in Gujarat and Punjab & Haryana. v9.2 — 2026-10-20; the **Magistrate** holds A-Diary editor and A-Diary signer in Kerala, Gujarat and Punjab & Haryana (§3). v9.1 — 2026-10-20; new role **A-Diary signer** ([`a-diary.md`](a-diary.md) `ADY-12`); not yet mapped to any staff title in §3. v9 — 2026-10-20; Hearing controller now starts, ends and passes over hearings (order-generation §10). Order data filler also sets the A-Diary text (order-generation `PUB-04`). New role **A-Diary editor** ([`a-diary.md`](a-diary.md)); not yet mapped to any staff title in §3. 2026-10-19; **a court establishment sits above the courtroom** (`RLE-02c`): the Account approver, Scrutiny officer and Case registerer roles are held per court establishment, not per courtroom, and the Scrutiny officer chooses the courtroom a case goes to; each state deployment has one establishment in this version. Replaces v6's whole-state Account approver. v8 — 2026-10-19; links point at the scrutiny and registration handover, after the e-filing, scrutiny and registration handover was split in two. v7 — 2026-10-19; new §3, **who holds which role, by state** — one table each for Kerala, Gujarat and Punjab & Haryana, listing each staff title and its roles: Magistrate, Scrutiny officer, Bench clerk / Reader, Typist, Steno, Ahlmad, Post officer. v6 — 2026-10-19; the Account approver role is held for the whole state deployment, replacing v5's court establishment (`RLE-02c`). v5 — 2026-10-19; the Account approver role is held per court establishment (`RLE-02c`). v4 — 2026-10-19; the Account approver role is the exception to per-courtroom roles — held above courtroom level (`RLE-02c`). v3 — 2026-10-18; a Scrutiny officer who also holds Case registerer is not offered Forward for registration. v2 — 2026-10-18; roles are held **per courtroom** — one account can hold
different roles in different courtrooms (`RLE-02a`, `RLE-02b`); the open question is
closed. v1 — 2026-10-18; first draft. Court-side permissions are held by **roles**,
not by user types: a staff account is given one or more roles, and every PRD names the
role an action needs.

Who holds which role is different in every court. In one court the typist types the
order and the bench clerk fills its data; in another the steno does both; in Punjab &
Haryana the same seats have different names (Steno, Reader, Ahlmad). So no PRD says
"the magistrate may" or "the typist may". It names a role, and each court decides which
of its staff hold it.

This document owns the list of court roles and what each one allows. The detail of each
action stays in the PRD that owns it, linked from the table.

---

## 1. How roles work

| ID | Requirement |
|---|---|
| `RLE-00` | Courts are arranged in two levels: a **court establishment** contains one or more **courtrooms**, and each courtroom belongs to one establishment. Each state deployment has **one** court establishment in this version; more than one, and how registrations and filed cases are placed at one, are not part of this version. |
| `RLE-01` | A **role** is a set of actions. Every court-side action that changes something — approving, scrutinising, registering, drafting, filling, signing, conducting a hearing — needs a role. |
| `RLE-02` | A staff account holds **one or more roles**. Any combination is allowed; there is no fixed bundle. |
| `RLE-02a` | Roles are held **per courtroom**, except those in `RLE-02c`. A staff account is mapped to a list of courtrooms ([`account-creation-handover.md`](account-creation-handover.md) `REG-35`), and each courtroom on the list carries its own set of roles. One person can hold different roles in different courtrooms — for example, order drafter in one and order drafter and order data filler in another. |
| `RLE-02b` | What a person can do follows the courtroom they are working in (`REG-36`). Switching courtroom (`REG-37`) switches the roles that apply. |
| `RLE-02c` | **Exception:** the **Account approver**, **Scrutiny officer** and **Case registerer** roles are held **per court establishment**, not per courtroom. A registration belongs to no courtroom ([`account-creation-handover.md`](account-creation-handover.md) `REG-23b`), and a case has no courtroom until the Scrutiny officer chooses one at the end of scrutiny ([`scrutiny-registration-handover.md`](scrutiny-registration-handover.md) §4). These roles apply whichever courtroom a person is working in. |
| `RLE-03` | Roles are assigned per courtroom — or per establishment, for those in `RLE-02c` — when the account is created, and changed afterwards through the same backend route ([`account-creation-handover.md`](account-creation-handover.md) §6, `REG-30`, `REG-31`). There is no self-service. |
| `RLE-04` | A role is enforced **server-side**. Hiding a control from someone who does not hold the role is not enough. |
| `RLE-05` | Several people may hold the same role in a court. Any of them can take the action. |
| `RLE-06` | Reading is not a role. Anyone with a staff account in the courtroom can see the courtroom's cases, orders and lists. A case that has no courtroom yet is seen by holders of the establishment's roles (`RLE-02c`). Roles govern what a person can **do**. |
| `RLE-07` | A screen may give different people a different **first action** depending on the roles they hold. That decides what is shown first, not what is allowed: anything a person's roles allow stays reachable. |
| `RLE-08` | No PRD names a staff title (magistrate, typist, bench clerk, CMO, reader, steno, ahlmad) as the holder of a permission. It names the role. Titles appear only where the law or a document needs one — for example, the designation printed under a signature. |
| `RLE-09` | The four process roles — **Envelope receiver**, **Process signer**, **Process dispatcher** and **Process reporter** — are held for a **scope**: some or all process types, on some or all channels ([`process-handover.md`](process-handover.md) §2, §6.2). A person can act on a process only where it falls within their scope. A role written without a scope covers every process type on every channel. Where a channel's send is done by the system, the Process dispatcher clicks Send, which triggers the system calls, instead of marking it sent. Where a channel's status update is done by the system, the system is the Process reporter: the receiving system's report is the recorded outcome. |

---

## 2. The roles

| Role | What it allows | Owning PRD |
|---|---|---|
| **Account approver** | Approve or reject an advocate's or clerk's registration, including a resubmission after rejection. | [`account-creation-handover.md`](account-creation-handover.md) §5.3 |
| **Scrutiny officer** | Scrutinise a filed case: mark fields and documents as errors, send the case back for correction, choose the courtroom the case goes to, and forward it for registration (not offered to someone who also holds Case registerer: they register it themselves). | [`scrutiny-registration-handover.md`](scrutiny-registration-handover.md) `SCR-01`–`SCR-07`, `SCR-16` |
| **Case registerer** | Register a case, which assigns its number and moves it to cognisance, or send it back for correction at registration. | [`scrutiny-registration-handover.md`](scrutiny-registration-handover.md) `SCR-08`, `SCR-11`, `SCR-12` |
| **Order drafter** | Write and edit an order's text, use shortcuts, send it for signing, move it back to draft before it is signed, and discard a draft. | [`order-generation.md`](order-generation.md) §5, §8 |
| **Order data filler** | Fill an order's data: its order items and their fields, the decision on each application, attendance, and the A-Diary text. Mark the order data complete, and reopen it before the order is signed. | [`order-generation.md`](order-generation.md) §6, §13 |
| **Next hearing setter** | Set the next hearing's date and purpose, or record that the matter is not listed again, wherever the court enters it. | [`order-generation.md`](order-generation.md) §9 |
| **Order signer** | Sign orders, one at a time or several at once. | [`order-generation.md`](order-generation.md) §12 |
| **Hearing controller** | Conduct the day's board: start, end and pass over hearings. | [`order-generation.md`](order-generation.md) §10 |
| **Application onboarder** | Take an application on file, and set or move the date it is to be decided. | [`application-lifecycle.md`](application-lifecycle.md) `ALC-04`, `ALC-09`, `ALC-15` |
| **Envelope receiver** | Record receipt of the envelope the party hands in for an RPAD or Police (RPAD) process, within the process types and channels held (`RLE-09`). | [`process-handover.md`](process-handover.md) `STP-02` |
| **Process signer** | Sign process, within the process types and channels held (`RLE-09`). | [`process-handover.md`](process-handover.md) `SGN-01` |
| **Process dispatcher** | Send process — mark it sent, or click Send where the system sends it — and recall a process, sent or not, within the process types and channels held (`RLE-09`). | [`process-handover.md`](process-handover.md) `DSP-03`, `PIA-01` |
| **Process reporter** | Record the outcome of process — served or executed, or not — within the process types and channels held (`RLE-09`). | [`process-handover.md`](process-handover.md) `DSP-03`, `DSP-08`, `DSP-09` |
| **Evidence marker** | Mark any document in the case file as evidence, as prosecution (P) or defence (D), which allots its evidence number. | [`document-submission.md`](document-submission.md) `DSB-12`–`DSB-14` |
| **A-Diary editor** | Change an A-Diary entry's text — which also changes the A-Diary text of the order it came from — until that day's A-Diary is signed. | [`a-diary.md`](a-diary.md) `ADY-07`, `ADY-09` |
| **A-Diary signer** | Sign the A-Diary. | [`a-diary.md`](a-diary.md) `ADY-12` |


---

## 3. Who holds which role, by state

The staff titles in each state, and the roles each one holds. This is reference for setting
up accounts (`RLE-03`); no PRD reads permissions from a title (`RLE-08`). **Not known**
means the title exists there but its roles have not been confirmed. Scrutiny officer and Case registerer are held at the court establishment, every other role in a courtroom (`RLE-02c`).

### 3.1 Kerala

| Staff title | Roles |
|---|---|
| **Magistrate** | Case registerer, Order drafter, Next hearing setter, Order signer, Hearing controller, Application onboarder, Process signer for warrants, Evidence marker, A-Diary editor, A-Diary signer |
| **Scrutiny officer** | Scrutiny officer, Evidence marker |
| **Bench clerk / Reader** | Order drafter, Order data filler, Next hearing setter, Hearing controller, Application onboarder, Envelope receiver, Process signer except for warrants, Evidence marker |
| **Typist** | Order drafter, Order data filler, Next hearing setter, Evidence marker |
| **Post officer** | Process dispatcher and Process reporter for e-Post, Evidence marker |

### 3.2 Gujarat

| Staff title | Roles |
|---|---|
| **Magistrate** | Case registerer, Order drafter, Next hearing setter, Order signer, Hearing controller, Application onboarder, Process signer for warrants, Evidence marker, A-Diary editor, A-Diary signer |
| **Scrutiny officer** | Scrutiny officer, Account approver, Evidence marker — one person across five courtrooms today |
| **Bench clerk / Reader** | Order drafter, Order data filler, Next hearing setter, Hearing controller, Application onboarder, Envelope receiver, Process signer except for warrants, Process dispatcher, Process reporter, Evidence marker |
| **Typist** | Order drafter, Order data filler, Evidence marker |
| **Post officer** | Evidence marker |

### 3.3 Punjab & Haryana

| Staff title | Roles |
|---|---|
| **Magistrate** | Case registerer, Order drafter, Next hearing setter, Order signer, Hearing controller, Application onboarder, Process signer for warrants, Evidence marker, A-Diary editor, A-Diary signer |
| **Scrutiny officer** | Scrutiny officer, Evidence marker |
| **Bench clerk / Reader** | Order drafter, Order data filler, Next hearing setter, Hearing controller, Application onboarder, Envelope receiver, Process signer except for warrants, Process dispatcher, Process reporter, Evidence marker |
| **Typist** | Order drafter, Next hearing setter, Evidence marker |
| **Steno** | Order drafter, Evidence marker |
| **Ahlmad** | Order data filler, Account approver, Evidence marker |
| **Post officer** | Evidence marker |

---

## 4. Open questions

| # | Question | Blocking? |
|---|---|---|
| `Q-1` | Who holds Process signer for proclamation and attachment — the same staff as for notice and summons, or the same as for warrants? §3 gives them to the Bench clerk / Reader for now. Moved from [`process-handover.md`](process-handover.md). | Yes |
