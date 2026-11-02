# Scrutiny and Registration — Developer & Agent Handover

**Status:** v3.5 — 2026-10-25; **how the scrutiny and registration lists are built is for the implementer** (`SCR-09`); the pending tasks stay, and a case is on a list exactly while its task is open. No longer says the lists *are* the pending tasks mechanism or forbids a second stage-query (`SCR-10`). v3.4 — 2026-10-24; wording: `SCR-15` says "not signing digitally", not "not e-signing" — e-sign means Aadhaar-based e-signing only ([`efiling-handover.md`](efiling-handover.md) §18). v3.3 — 2026-10-19; **cases go to the court establishment first** (§4): the Scrutiny officer and Case registerer roles are held per court establishment, not per courtroom, and the Scrutiny officer **chooses the courtroom** when forwarding or registering (`SCR-16`, new). Automatic courtroom allocation is removed; a later version will suggest a courtroom. Two questions open (`Q-1`, `Q-2`, §4). v3.2 — 2026-10-19; **oath review** (`SCR-14`, new): each oath is listed with whose it is and when it was recorded, plays in the centre panel, is flagged on its own, and shows when it carried over from an earlier round; **paper upload reason** shown to the scrutiny officer (`SCR-15`, new). Oath now at [`efiling-handover.md`](efiling-handover.md) §18.2. v3.1 — 2026-10-19; **oath video** can be flagged under `SCR-03`; it is recorded again on correction only when flagged (`OTH-5`, [`efiling-handover.md`](efiling-handover.md) §14a). v3 — 2026-10-19; **registration type** (`SCR-13`, new, §6): where a state registers a case as one of several types, the type is chosen at Forward for registration, editable at Register and final there; with one type there is no choice. Kerala and Punjab & Haryana have one type, Gujarat three. Numbers each step issues are in [`case-numbers.md`](case-numbers.md). v2 — 2026-10-19; **`SCR-10` reworded** (§5): the action that changes a case creates and closes its tasks in the same transaction; tasks never move the case. v1 — 2026-10-19; **split out of the e-filing handover** (its §20.1–§20.4, the
court-side rows of its role matrix and lifecycle, and the scrutiny and registration
entries of its decisions log and glossary). Requirement IDs unchanged. Changes to these
sections before this date are in the Status line of
[`efiling-handover.md`](efiling-handover.md) (v11, v16, v30–v32, v37, v38).
**Date:** 2026-10-19
**Audience:** developers and agents building scrutiny, registration and the correction
cycle (front end and backend)

## Sources and precedence

| Precedence | Source | Provides |
| --- | --- | --- |
| 1 | [`efiling-handover.md`](efiling-handover.md) | Every field, its ID and its validation; the filing lifecycle; signing and payment |
| 2 | `efiling-reference/E-filing, Scrutiny and Registration.pdf` | Roles, workflow states, functional requirements |
| — | [`court-roles.md`](court-roles.md) | What the Scrutiny officer and Case registerer roles allow |
| — | Owner decisions | Recorded inline as **[OWNER]**; log in §9 |

Owner decisions win over everything. Marks are those of the e-filing handover:
`[DERIVED]` inferred, confirm before building · `[GAP]` not specified, blocks the item ·
`[OWNER]` owner decision.

Requirement IDs `SCR-*`, `REF-*` and `LIFE-11` are defined here. Field IDs (`CHQ-8`,
`LDN-2`, `JUR-9` …) and validation IDs (`VAL-01/02`) are defined in the e-filing
handover. Use both in tickets, commits, test names.

---

# 1. Scope

From the moment a filed, signed and paid case enters Scrutiny until it is registered and
reaches Cognisance: routing the case to a courtroom, scrutiny, registration, send-backs,
and what a send-back opens for editing.

The filer's side of a correction cycle — correcting, re-signing, paying any increase —
uses the e-filing steps unchanged: [`efiling-handover.md`](efiling-handover.md) §4
(`LIFE-12`, `LIFE-13`), §18 (`SIG-07`), §19.4.

Out: everything from Cognisance onward; case number formats and generation
([`case-numbers.md`](case-numbers.md)).

---

# 2. Roles and permissions

Court roles: **Scrutiny officer** · **Case registerer** — what each allows is owned by
[`court-roles.md`](court-roles.md); a staff account may hold both. Filer roles, scope
predicates and filer permissions are in [`efiling-handover.md`](efiling-handover.md) §3.

| Action | Scrutiny officer | Case registerer |
| --- | :---: | :---: |
| Mark errors + send back (Scrutiny) | ✓ | — |
| Forward for registration ¹ | ✓ | — |
| Register / send back (Registration) | — | ✓ |
| Register at Scrutiny ² | ✓ | ✓ |

¹ Only for someone who does **not** also hold the Case registerer role — see `SCR-11`.
² Needs **both** roles at the court establishment — see `SCR-11` (§7).

---

# 3. Case lifecycle

A case enters Scrutiny when payment completes. From Pending Correction the filer corrects,
re-signs and, if more is owed, pays, and the case returns to Scrutiny — those stages are
in [`efiling-handover.md`](efiling-handover.md) §4.

| Initial stage | Action | New stage |
| --- | --- | --- |
| Scrutiny | Mark Defects and Send Back | Pending Correction |
| Scrutiny | Forward for registration | Registration |
| Scrutiny | Register (`SCR-11`) | Cognisance |
| Registration | Register | Cognisance |
| Registration | Send Back | Pending Correction |

- Scrutiny → Register → Cognisance is available only to a person who holds both the
  Scrutiny officer and Case registerer roles at the court establishment, and replaces Forward for
  them; a case registered that way never reaches the Registration stage. See `SCR-11` (§7).
- `LIFE-11` — send-backs may repeat without limit.

---

# 4. Case routing — court establishment and courtroom

A court establishment contains one or more courtrooms ([`court-roles.md`](court-roles.md)
`RLE-00`). Each state deployment has one court establishment in this version; which
establishment a filed case goes to, when there is more than one, is not part of this
version.

The **Scrutiny officer** and **Case registerer** roles are held at the court
establishment, not in a courtroom ([`court-roles.md`](court-roles.md) `RLE-02c`). Who
holds them is not fixed by any seat: in Gujarat today one person scrutinises for five
courtrooms.

After a case is filed, signed and paid, it goes to the **court establishment**, with no
courtroom. Its scrutiny task goes to those who hold the Scrutiny officer role there.

`SCR-16` **The Scrutiny officer chooses the courtroom** the case goes to, from the
establishment's courtrooms, as part of **Forward for registration** or **Register at
Scrutiny** (§5, `SCR-06`). Where the establishment has **one** courtroom, no choice is
shown and the case goes to it. Send back does not choose a courtroom. From Cognisance
onward, the case's work goes to the holders of roles in that courtroom.

There is no automatic allocation in this version; nothing is pre-selected. A later
version will **suggest** a courtroom that the Scrutiny officer can change — for example
from Gujarat's mapping of financial institutions to courtrooms (HDFC → Courtroom A, with
a default for filers who match no mapping). The filer never selects a courtroom. Moving a
registered case to another courtroom is outside this module.

| # | Open question | Blocks |
| --- | --- | --- |
| `Q-1` | After a send-back, the case returns to Scrutiny. Is the courtroom chosen earlier kept or pre-selected, or does the Scrutiny officer choose afresh? | `SCR-16` on resubmission |
| `Q-2` | At Registration, can the Case registerer change the courtroom the Scrutiny officer chose? | `SCR-08`, `SCR-16` |

---

# 5. Scrutiny

A case enters Scrutiny after signing and payment complete (§3). A holder of the
establishment's **Scrutiny officer** role reviews the submitted case for defects before
forwarding it for registration.

## How a case reaches the list

`SCR-09` A case due for scrutiny or registration has an open **pending task** —
*Scrutinise case* or *Register case* — and is in the list of a Scrutiny officer or a Case
registerer exactly as long as that task is open. How the list itself is built is for the
implementer. The court-side tasks, as a live view of the master Pending Tasks list:

```superhuman-view
name: Pending tasks (Court Side) — Scrutiny and Registration
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("scrutiny-registration-handover")
```

Both are assigned to the holders of the court establishment's **Scrutiny officer** and
**Case registerer** roles respectively (§4), due **+0 days**, visible to **Only Users** (the
assignees; any one of them can act, [`court-roles.md`](court-roles.md) `RLE-05`). Neither carries a
Category — the Category values are citizen-side only. Task attributes and the status
lifecycle are in `pending-tasks-handover.md`.

`SCR-10` The action that changes a case — sending back, forwarding, registering,
resubmitting — also **creates and closes these tasks, in the same transaction**. Tasks
never move the case. The filer side works the same way:

```superhuman-view
name: Pending tasks (Citizen-Side) — Scrutiny and Registration
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("scrutiny-registration-handover")
```

Both tables are the single source of truth and the place to edit these tasks. A
downloaded copy of this document is a snapshot.

**PRD language.** The functional spec says a case "appears in the list" for scrutiny and
for registration without saying how the system knows. The requirement is as stated here (`SCR-09`).

## Scrutiny interface (initial version)

`SCR-01` Three-panel layout:
- **Left**: case fields, grouped by section
- **Centre**: the selected document
- **Right**: document index (all uploaded documents)

`SCR-02` A **Scrutiny officer** can **mark any individual field as an error** and type a
comment against it. They can also **mark an entire section** as an error with a comment.

`SCR-03` A **Scrutiny officer** can **flag any document as an error**, which permits the
filer to re-upload it on send-back.

`SCR-14` **Oath videos**, where the state requires an oath ([`efiling-handover.md`](efiling-handover.md)
§18.2):
- Each oath is listed on its own, labelled with the complainant it is for and the person
  who recorded it — the complainant, their PoA holder or an Institution's authorised
  representative — and when it was recorded.
- Selecting one plays the video in the centre panel.
- Each oath is flagged as an error on its own, with a comment. Only a flagged oath is
  recorded again on correction, and only by that complainant (`OTH-5`).
- After a correction cycle, an oath that was not recorded again says so, with the date it
  was recorded, so the officer can tell it carried over from an earlier round.

`SCR-15` **Paper upload reason.** Where the case was signed by uploading a physically
signed copy, the scrutiny officer sees the reason given for not signing digitally and when it was
given (`SIG-10`, [`efiling-handover.md`](efiling-handover.md) §18).

## Interlinked date auto-marking

`SCR-04` When a Scrutiny officer marks any interlinked date field (any node in the
date chain, `VAL-01/02`, §8), **all transitive downstream dates** in the chain are
**auto-marked** as well — the filer can then edit them without failing the ordering
validations. This implements `REF-03` at the scrutiny stage: the officer selects one
date, and the system marks the rest.

## Delay condonation alert

`SCR-05` If delay has become applicable since the case was filed — evaluated against the
clock at the time of scrutiny, the same rule as `REF-04` — the scrutiny interface must
**flag this to the Scrutiny officer**. The Delay Condonation section may now be required
where it was not at filing.

## Presentation outside validity

`SCR-05a` Where a cheque was presented after its validity (`CHQ-11`,
[`efiling-handover.md`](efiling-handover.md) §9), the scrutiny interface shows a
**warning line under that cheque's date of presentation** in the case fields —
*"Presented after validity — valid until [last valid day]"* — the same treatment as the
interface's other per-field warnings. It is information, not a flag: the Scrutiny officer
decides whether to mark the field as an error (`SCR-02`).

## Actions

`SCR-06` Actions, each needing the role named:
- **Send back** (Scrutiny officer) — only the fields, sections, and documents marked as
  errors are flagged to the filer (`REF-01`). Send-backs repeat without limit (`LIFE-11`).
- **Forward for registration** (Scrutiny officer, **not** also Case registerer) — moves the case to Registration (§6). The officer first chooses the courtroom (`SCR-16`) and, where the state has more than one registration type, the type (`SCR-13`).
- **Register** (Scrutiny officer **and** Case registerer) — chooses the courtroom
  (`SCR-16`), finalises the registration type (`SCR-13`), assigns the case number and moves the case directly to Cognisance,
  skipping Registration entirely (`SCR-11`, `SCR-12`).

---

# 6. Registration

Applies only to a case forwarded from Scrutiny. A case registered at Scrutiny (§7)
never reaches this stage or the *Register case* task below.

`SCR-07` Forwarding closes the *Scrutinise case* task and creates a ***Register case***
pending task for the holders of the court establishment's **Case registerer** role (§4) — that
task is their list of cases to register (`SCR-09`).

`SCR-08` Two actions, both needing the **Case registerer** role:
- **Register** — finalises the registration type (`SCR-13`), assigns a case number and
  moves the case to Cognisance. Case number format and generation are in
  [`case-numbers.md`](case-numbers.md).
- **Send back** — the Case registerer types **one single overall comment** (no individual
  field marking, consistent with `REF-02`). This opens **everything** for editing.

`SCR-08a` The *Register case* screen's case timeline states the statutory limit under
each step it governs. Under the cheque's presentation it reads *within 3 months of the
cheque date*, or — where the cheque was presented after its validity (`CHQ-11`) —
*beyond 3 months of the cheque date* in **warning ink**. Only a step outside its window
takes the warning ink. The warning does not stop either action. For a case registered at
Scrutiny there is no Registration stage, and `SCR-05a` is the only court-side warning.

**[OWNER]** There is **no outright rejection at this stage** — registration happens
first; dismissal is possible only after registration (out of this module's scope).

## Registration type — `SCR-13`

**[OWNER]** A state may register a case as one of several types. The types are
configured per state; each has its own number series ([`case-numbers.md`](case-numbers.md)).

| State | Registration types |
| --- | --- |
| Kerala | One: criminal complaint |
| Gujarat | Three: **eCC** Criminal Case · **eCR EN** Criminal Inquiry Case · **eCR MA** Criminal Miscellaneous Application |
| Punjab & Haryana | One: **NACT** |

Where the state has **more than one** type:

- **Forward for registration** — the Scrutiny officer chooses the type before forwarding.
  `[DERIVED]` No type is pre-selected: a wrong default would misclassify the case without
  anyone deciding it.
- **Register** (at Registration) — the type chosen at Forward is shown pre-selected. The
  Case registerer may change it. The type is **final at Register**.
- **Register at Scrutiny** (`SCR-11`) — there is no Forward, so the type is chosen once,
  at Register, and is final there.

Where the state has **one** type, no choice is shown at either step; the case is
registered as that type.

**[OWNER]** In Gujarat the scrutiny officer and the registrar are the same person, so in
practice the case is registered at Scrutiny and the type is chosen once.

---

# 7. Registering at Scrutiny

There is no setting for where a case is registered. It follows from the roles the person
at Scrutiny holds at the court establishment ([`court-roles.md`](court-roles.md) `RLE-02c`).

`SCR-11` A person who holds **both** the Scrutiny officer and the Case registerer roles at
the court establishment gets **Register** and Send back at Scrutiny. They do **not** get Forward
for registration: they would only be forwarding the case to themselves. A person who holds only the Scrutiny
officer role gets Forward for registration and Send back, not Register. A court that wants
every case checked by two people gives the two roles to different people.

`SCR-12` Register at Scrutiny does exactly what Register at Registration does (`SCR-08`):
finalises the registration type (`SCR-13`), assigns the case number and moves the case
to Cognisance. The case never reaches the
Registration stage or its *Register case* task (`SCR-07`), so there is no registration
send-back for it — only the Send back at Scrutiny (`SCR-06`). Everything from Cognisance
onward is identical either way; this module's scope ends there.

---

# 8. Editability on send-back

**Date chain** (`VAL-01/02`, field IDs as in [`efiling-handover.md`](efiling-handover.md)
§9–§11) — implement as an explicit dependency graph (`REF-03` walks it):

```
CHQ-1 date on cheque
  └─ CHQ-8 presentation (≥)
       └─ CHQ-9 return (≥)
            └─ LDN-2 dispatch (≥ return of at least one cheque; warn > 30 days after return)
                 ├─ LDN-6 delivery (≥)   [delivered = Yes]
                 └─ LDN-7 return (≥)     [delivered = No]
                      └─ JUR-9 cause of action = service + 15 days (auto)
                           └─ JUR-10 filing date (auto, today)
                                └─ JUR-11 delay = beyond 1 month of cause
```

**Editability rules** (`REF`) — override all defaults elsewhere:

| Trigger | Opens for editing |
| --- | --- |
| Send back at Scrutiny, with errors marked (`REF-01`/`SCR-02/03`) | Only the marked fields/sections/documents |
| …a marked field is an interlinked date (`REF-03`/`SCR-04`) | + all **transitive downstream** dates (auto-marked) |
| …DCA became applicable since filing (`REF-04/05/06`) | + the Delay Condonation section, now required |
| Send back at Registration (`REF-02`) | Everything — except the oath, which is recorded again only when flagged at Scrutiny (`OTH-5`) |

`REF-04` is evaluated **against the clock at refiling**, never cached — a correction
cycle sitting for weeks silently attracts the DCA (and its fee →
[`efiling-handover.md`](efiling-handover.md) `LIFE-12`, §19.4).

---

# 9. Notifications and events; decisions log

The notifications this module triggers, as a live view of the master Notifications
table. Do not invent notification copy — the master table is the source of truth and
the place to edit it.

```superhuman-view
name: Notifications — Scrutiny and Registration
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-xnftvTkudd/tables/grid-3FTjQhdfYv
filter: PRDs.Contains("scrutiny-registration-handover")
```

The case-timeline events this module raises, from the master Events/Case Updates table:

```superhuman-view
name: Events — Scrutiny and Registration
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-2x28DoUtbn/tables/grid-GPg4dKS-s9
filter: PRDs.Contains("scrutiny-registration-handover")
```

A downloaded copy of this document is a snapshot of both.

**Owner decisions log** — the scrutiny and registration entries, carried over from the
e-filing handover's log under the same batch numbers.
(batch 1) — 2026-08-25/26: single scrutiny officer.
(batch 2): magistrate send-back = one overall comment · no outright rejection before
registration.
(batch 3): scrutiny mark-comments deferred to a separate defect-correction design.
(batch 4): magistrate case-visibility irrelevant to this design.
(batch 6) — 2026-09-07, scrutiny interface: three-panel scrutiny layout (fields /
document / document index) · field-level and section-level error marking with per-error
comments · document flagging for re-upload · interlinked-date auto-marking (marking one
date auto-marks all transitive downstream dates) · delay-condonation alert to the
scrutiny officer when delay becomes applicable since filing · registration assigns a case
number (format in separate document) · supersedes batch 3's deferral of mark-comments to a
separate design.
(batch 7) — 2026-09-09: case number format and generation moved to a separate document ·
case routing added (§4): auto-assignment to courtroom, configurable allocation logic per
establishment, Gujarat Phase 1 = institution-to-courtroom mapping + fallback.
(batch 9) — 2026-09-23: registration point made configurable (`SCR-11/12`) — under
`registrationPoint: scrutiny`, the scrutiny officer's second action is Register (assigns
case number, → Cognisance) instead of Forward, and the magistrate's Registration
stage/task is skipped entirely; default `registrationPoint: magistrate` is today's
behaviour, unchanged.
(batch 10) — 2026-10-18: the `registrationPoint` config is removed; a person holding both
the Scrutiny officer and Case registerer roles in the courtroom can register at Scrutiny
(`SCR-11/12`). Supersedes batch 9.
(batch 13) — 2026-10-19: registration type per state (`SCR-13`) — Kerala one, Gujarat
three (eCC, eCR EN, eCR MA), Punjab & Haryana one (NACT); chosen at Forward, editable and
final at Register; in Gujarat the scrutiny officer and registrar are the same person.
(batch 14) — 2026-10-19: a court establishment sits above the courtroom; the Scrutiny
officer and Case registerer roles are held there. A filed case goes to the establishment,
and the Scrutiny officer chooses its courtroom at Forward or Register (`SCR-16`). One
establishment per state deployment for now. Automatic courtroom allocation comes later,
as a suggestion. Supersedes batch 7's auto-assignment to a courtroom.

---

# 10. Glossary

| Term | Meaning |
| --- | --- |
| DCA | Delay Condonation Application — attaches when filed beyond limitation. |
| Scrutiny | Court-staff defect review before registration. |
| Registration | Case-number assignment that moves the case to Cognisance. Needs the Case registerer role; done at its own stage, or at Scrutiny by someone who also holds the Scrutiny officer role (§7). |
| Cognisance | Post-registration stage; end of this module. |
| Registration type | The type a case is registered as, configured per state, each with its own number series (`SCR-13`). |
| Court establishment | The level above the courtroom; holds one or more courtrooms. Scrutiny and registration happen here (§4). |
