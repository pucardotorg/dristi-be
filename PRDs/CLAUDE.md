# PRDs — how to work in this folder

Read this before changing any file here. It sets out how the PRDs are written and edited.
For the programme (what DRISTI is, the states, the §138 case), read the root
`PUCAR/CLAUDE.md`. For publishing, use the `sync-handovers` skill.

This file is not a PRD. Don't add it to `.superhuman-sync.json`, and don't sync it.

---

## 1. Who reads these

Developers and agents who build from them, and the owner, who reads each one end to end,
decision by decision. Every line a reader has to wade through costs real attention. Write
plainly: short sentences, no jargon-as-drama, and say what is not known.

## 2. Before you edit

- **Edit only a PRD the user named in this conversation.** A remark about a document is not
  a request to change it. If a message comments on a doc but asks for nothing, say in one
  line what it might mean, and ask. If the scope came from your own summary or list
  ("the thin ones"), list the files you mean to touch and confirm them first.
- Link fixes and new placeholder PRDs that a requested change makes necessary are fine,
  but say that you made them.
- **Never `git checkout`, `git restore` or `git stash` a PRD.** Other sessions often leave
  uncommitted work in this folder. To undo your own edit, reverse only that edit.
- Use `git -C <absolute path>` for every git command. Only the `sync-handovers` skill
  pushes `prds`.

## 3. Shape of a PRD

```
# <Title>

**Status:** vN — YYYY-MM-DD; <what changed>. v(N-1) — YYYY-MM-DD; <what changed>. …
**Audience:** <who builds from it>

<One short paragraph: what this PRD covers.>

## 1. …
| ID | Requirement |
|---|---|
| `XXX-01` | … |

## N. Open questions
| ID | Question | Blocking |
|---|---|---|
| `Q-1` | … | Yes |
```

- Titles don't end in "Handover" or "Developer & …", and file names don't end in
  `-handover`.
- A placeholder is the title, Status `v0 — <date>; placeholder, not written yet.`,
  Audience, one paragraph of scope, and "Not written yet."

### Status line

- **Update it on every edit.** It is the changelog, and Superhuman shows it as a callout.
  Readers who don't diff files see changes only through it.
- Put the new entry **first**, ahead of the earlier entries, which stay. Bump the version:
  a minor number (v8.6 → v8.7) for a correction or small addition, a whole number for a
  restructure or a new section.
- Say what changed, not why, and name the requirement IDs it touched.

## 4. Writing requirements

- **One requirement per ID row, and each one testable.** Reference IDs in backticks.
- **IDs never change.** When a requirement moves to another PRD, it keeps its ID; say so in
  both Status lines. Withdrawn ideas go to [`dropped-ideas.md`](dropped-ideas.md) with
  their IDs.
- **Settled is a plain requirement.** Once something is decided, write it as a
  requirement, marked `[OWNER]` where the owner decided it. Don't present it as a
  "resolved question" with its history.
- **Say what is shown, not where.** No placement words ("in the header", "beside the
  editor", "where the shortcuts sat"). The UI keeps moving. Don't sweep old PRDs for
  them unless asked.
- **No field descriptions.** A field gets a label, an error and "(optional)" where it
  applies. No hint or subtitle text.
- **Link, don't restate.** When another document owns a topic, say only what this PRD
  needs and link to the owner. If no document owns it, say so in chat rather than making
  this PRD the owner by default. Common owners:

  | Topic | Owner |
  |---|---|
  | Filing fields and validations | [`efiling.md`](efiling.md) |
  | Scrutiny, registration, refiling (`SCR`, `REF`) | [`scrutiny-registration.md`](scrutiny-registration.md) |
  | Who may do what (court side) | [`court-roles.md`](court-roles.md) — PRDs name a **role**, never a staff title |
  | Pending tasks | [`pending-tasks.md`](pending-tasks.md) and the Coda tables |
  | Order types and templates | [`order-types.md`](order-types.md), [`order-template-catalogue.md`](order-template-catalogue.md) |
  | Processes (summons, warrants, notices) | [`process.md`](process.md) |
  | Signing methods per state | [`signing-methods.md`](signing-methods.md) |
  | Legal detail | https://dristidomain.netlify.app/ |

- **Name the system SARAS** in new material, not "24x7 ON Courts". Don't rewrite older text
  that uses the old name. Mention it instead.
- Case history and event lists are always **newest first**.

### Marks

| Mark | Meaning |
|---|---|
| *(none)* | Requirement |
| `[OWNER]` | The owner decided it |
| `[DERIVED]` | Inferred; confirm before building |
| `[GAP]` | Not specified, and blocking |
| `[CURRENT]` | How today's system (DRISTI 1.0) behaves. **Not automatically a requirement** |

Comments threaded in `E-Filing Fields.xlsx` don't count: derive nothing from them.

## 5. Open questions

- Keep the list short. It holds **genuinely open questions and things yet to be done**
  (for example, "master data not received yet").
- When a question is answered, write the answer in as a requirement and **delete the row**.
  Don't strike it through, and don't leave a "Resolved" row. The Status line records the
  resolution.
- Mark each question Blocking Yes or No. Don't build a section that has a blocking
  question against it.

## 6. Pending tasks

When a PRD change implies a pending task, draft it in
[`pending-task-drafts.md`](pending-task-drafts.md) with the 12 attributes from
[`pending-tasks.md`](pending-tasks.md) §2. Don't write it to Coda as it comes up. The owner
has them written in one batch. In a PRD, show pending tasks through a `superhuman-view`
directive; a new PRD needs its file stem added to the Coda table's PRDs column first.

## 7. Requirement-ID prefixes

Prefixes each PRD defines. Before you choose a prefix for a new section, check it isn't
here.

| PRD | Prefixes |
|---|---|
| `a-diary.md` | `ADY` |
| `account-creation.md` | `REG` |
| `application-lifecycle.md` | `ALC` |
| `bulk-filing.md` | `BLK` |
| `court-roles.md` | `RLE` |
| `document-submission.md` | `DSB` |
| `efiling.md` | `ACC` `ADV` `CHQ` `DCM` `DOC` `FIL` `JUR` `LDN` `LIFE` `LIT` `OTH` `PAY` `PRY` `ROLE` `SIG` `WIT` |
| `evidence-marking.md` | `EVM` (also keeps `DSB-12`–`15`, `DSB-20`, moved from document-submission) |
| `join-a-case.md` | `JOIN` |
| `office-management.md` | `OFC` |
| `order-generation.md` | `APL` `ATT` `CLS` `CMP` `DFT` `ENH` `HRG` `ITM` `NXT` `ORD` `PLC` `PND` `PUB` `ROL` `SGN` `SHC` `SND` `TIT` `TXT` `VAR` |
| `order-types.md` | `DEN` `OTY` `RZN` `RZT` `SHW` |
| `process.md` | `AUT` `DSP` `EXP` `FEE` `PIA` `PRC` `SGN` `STP` `TPL` |
| `scrutiny-registration.md` | `SCR` `REF` |
| `signing-methods.md` | `SGM` |
| `view-case.md` | `ACT` `APP` `CF` `DET` `DOC` `HRG` `ORD` `OVW` `PTY` `SVC` `TME` |

**Known clashes.** The same ID means different things in two PRDs:
- `HRG` and `ORD`: order-generation.md and view-case.md;
- `SGN`: order-generation.md and process.md;
- `DOC`: efiling.md and view-case.md.

Until they are renumbered, a reference to one of these from another PRD names the file:
"order-generation `HRG-01`". Don't create new clashes.
