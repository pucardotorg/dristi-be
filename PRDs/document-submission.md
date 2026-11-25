# Document Submission

**Status:** v19 — 2026-11-25; the four recorded-statement types (Evidence of the complainant, Witness deposition, Plea, Examination of the accused) are one type, **Recorded statement**, told apart by the title (§3). v18 — 2026-11-25; **open questions answered**: **Others** added to the document types (§3), and the recorded statements among them named; an optional **reason for filing** (`DSB-26`); the same file formats and size limit as other uploads (`DSB-27`); a Draft or Pending signature submission can be **deleted** as an application can, and otherwise stays until signed (`DSB-28`); documents can be submitted from **registration**, including after disposal (`DSB-29`); a document asked for by the Mandatory submissions and responses order item goes through its pending task (`DSB-30`). Marking a document as void is a later enhancement (§4). Who can submit and sign is already set by `DSB-04`, `DSB-18` and `DSB-25`; notifications, if any, are added in the master Notifications table (§5). `Q-1`, `Q-2`, `Q-4`–`Q-8` removed. v17 — 2026-11-25; this PRD now covers only how documents are submitted: who submits, the flow, signing and statuses. **§3 Documents tab and §4 Marking evidence removed**; how documents are shown is owned by [`view-case.md`](view-case.md) §10 and [`case-file.md`](case-file.md), and marking by [`evidence-marking.md`](evidence-marking.md). `DSB-23` moves to §1: the filer enters a title for the document. `DSB-09` (Needs attention) withdrawn to [`dropped-ideas.md`](dropped-ideas.md); view-case `DOC-09` now states it. MDMS, Enhancements, Linked records and Open questions are now §3–§6. v16 — 2026-11-25; **§3 cut down to what this PRD owns**: the Documents tab — what it lists, each document's attributes (title, source, type, document number, exhibit number, who submitted and created it) and filtering — is owned by [`view-case.md`](view-case.md) §10 and linked from here. §3 keeps the title of a submitted document (`DSB-23`, now for this PRD's documents only) and Needs attention (`DSB-09`). `DSB-05`, `DSB-07`, `DSB-08`, `DSB-10`, `DSB-11` and `DSB-22` withdrawn to [`dropped-ideas.md`](dropped-ideas.md), with the titles `DSB-23` gave other documents; a deposition's name moves to case-file §3.1. v15 — 2026-11-25; new §7 **Linked records**: live views of the four master tables, filtered on `document-submission`; the Events view shows the Documents Submitted event. Open questions move to §8. v14 — 2026-11-25; `DSB-04` covers the court side only; who submits on the citizen side is in `DSB-18` and `DSB-25`. `Q-4` reworded to match. v13 — 2026-11-25; on the court side, only holders of the new **Document submitter** role ([`court-roles.md`](court-roles.md)) submit documents (`DSB-04`). v12 — 2026-11-25; a submission names the advocate it is raised by, in **Raised by**, as an application does (`DSB-25`, new); there is no Litigant field. Only that advocate signs, and a clerk sends it for signing to them alone (`DSB-18`); the Sign documents task goes to that advocate (`DSB-24`). `Q-3` answered and removed. v11 — 2026-11-25; a submission carries **one document** (`DSB-02`); several documents in one submission is a later enhancement, in a new §6 **Enhancements**. Open questions move to §7. v10 — 2026-11-25; the document types (`DSB-01`) come from MDMS and are listed in a new §5 **MDMS**; the values are unchanged. Open questions move to §6. The Documents tab's type filter offers the document types in MDMS, plus Deposition, Filing and Application (`DSB-11`). v9 — 2026-11-25; §4 links to [`case-file.md`](case-file.md) §1.2 for which documents can be marked as evidence, in place of saying any document can be. v8 — 2026-11-17; the fourth recorded statement type is now named **Examination of the accused** (`DSB-01`, `DSB-11`). v7 — 2026-11-16; **four document types added** to the dropdown, for the recorded statements: Evidence of the complainant, Witness deposition, Plea, Accused's examination (`DSB-01`); the Documents tab's type filter offers them too (`DSB-11`). v6 — 2026-10-30; **marking evidence moved to its own PRD**, [`evidence-marking.md`](evidence-marking.md) (`DSB-12`–`DSB-15`, `DSB-20` keep their numbers); Marked as evidence is no longer a submission status, since any document can be marked. A clerk's send for signing raises a **Sign documents** pending task for the advocates (`DSB-24`). New open questions `Q-1`–`Q-8`. v5 — 2026-10-22; **draft, not complete**; added how a document's title is formed, by source (`DSB-23`). v4 — 2026-10-22; Filed by and Litigant removed from the flow, with `DSB-16`, `DSB-17` and `DSB-21` (numbers not reused); signing rewritten (`DSB-18`): an advocate or party-in-person signs their own submission, a clerk sends it to the advocates they work for and any one of them signs, a court member signs their own; each document shows its **source** (`DSB-22`). v3 — 2026-10-22; a party-in-person counts as an advocate for Filed by and signing; a court member's submission has no Filed by or Litigant (`DSB-21`); the court has no evidence series of its own (`DSB-13`). v2 — 2026-10-22; Filed by and Litigant dropdowns, signed by the advocate in Filed by (`DSB-16`–`DSB-18`); no payment (`DSB-19`); provisional ID format `DOC-n` (`DSB-15`); Application added as a document type in the filter (`DSB-11`); open questions closed; **any document in the case file** can be marked as evidence, not only submitted documents (`DSB-12`, `DSB-20`). v1 — 2026-10-22; first version: submitting documents (types, multiple documents, signing), statuses, the Documents tab, and marking evidence with prosecution and defence numbers.
**Audience:** developers and agents building document submission

Requirement IDs: `DSB-*` — use in tickets, commits, test names. Roles are owned by
[`court-roles.md`](court-roles.md); the case view, including the Documents tab, by
[`view-case.md`](view-case.md); the case file and document names by [`case-file.md`](case-file.md); marking a document as evidence by
[`evidence-marking.md`](evidence-marking.md).

---

# 1. Submitting documents

Opened from **Make filings → Submit documents** on a case.

| ID | Requirement |
| --- | --- |
| `DSB-29` | Documents can be submitted once the case is **registered**. Disposal of the case does not change this. |
| `DSB-01` | **Document type** is chosen from the document types held in MDMS (§3). |
| `DSB-02` | A submission carries **one document**. |
| `DSB-23` | The filer enters a **title** for the document. |
| `DSB-26` | The filer can enter a **reason for filing**, a short text. It is optional. |
| `DSB-27` | The file formats and size limit accepted are the same as for other uploads on the platform. |
| `DSB-03` | Before it is submitted, the submission goes through **signing**. Submitting happens only once it is signed. |
| `DSB-25` | A submission names the advocate it is raised by, in **Raised by**: anyone with advocate access on the case, chosen and preselected as Raised by is on an application ([`application-lifecycle.md`](application-lifecycle.md), Every application). A party-in-person counts as an advocate. A submission by a member of the court has no Raised by. |
| `DSB-18` | **Who signs.** A submission is signed only by the advocate in Raised by. A clerk cannot sign: they **send for signing** to that advocate. A member of the court signs their own submission. |
| `DSB-24` | Sending for signing raises a **Sign documents** pending task for the advocate in Raised by. It closes when they sign. |
| `DSB-28` | A submission in Draft or Pending signature can be **deleted** by anyone who could have created and edited it, as an application can ([`application-lifecycle.md`](application-lifecycle.md) `ALC-39`). It is then gone, and its Sign documents task closes with it. Until it is signed or deleted, a submission stays in Pending signature. |
| `DSB-19` | Submitting documents involves **no payment**. |
| `DSB-04` | On the court side, only holders of the **Document submitter** role ([`court-roles.md`](court-roles.md)) can submit documents. |
| `DSB-30` | A document asked for by the **Mandatory submissions and responses** order item is submitted through its pending task, not through Submit documents. |

# 2. Statuses

| Status | Meaning |
| --- | --- |
| Draft | Being prepared; not yet sent for signature |
| Pending signature | Waiting to be signed |
| Submitted | Signed and on the case record |

| ID | Requirement |
| --- | --- |
| `DSB-06` | A document is visible to **all parties on the case** as soon as it is Submitted. |

# 3. MDMS

Values held in MDMS. Until master data has a place of its own, they are listed here.

**Document types** (`DSB-01`)

| Document type |
| --- |
| Affidavit |
| Memo |
| Evidence |
| Recorded statement |
| Others |

A recorded statement is evidence of the complainant, a witness deposition, a plea or the examination of the accused ([`case-file.md`](case-file.md) §1). Its title tells which.

# 4. Enhancements

- In a later version, one submission can carry several documents.
- In a later version, a document can be marked as **void**, which removes it from the case file.

# 5. Linked records

Live views of the master tables, filtered to this document. Each master table is the
single source of truth and the place to edit its rows; anything tagged `document-submission` there
appears here automatically. A downloaded copy of this document is a snapshot.

## Pending tasks (Court Side)

```superhuman-view
name: Pending tasks (Court Side) — Document Submission
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("document-submission")
```

## Pending tasks (Citizen-Side)

```superhuman-view
name: Pending tasks (Citizen-Side) — Document Submission
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("document-submission")
```

## Notifications

```superhuman-view
name: Notifications — Document Submission
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-xnftvTkudd/tables/grid-3FTjQhdfYv
filter: PRDs.Contains("document-submission")
```

## Events

```superhuman-view
name: Events — Document Submission
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-2x28DoUtbn/tables/grid-GPg4dKS-s9
filter: PRDs.Contains("document-submission")
```

# 6. Open questions

None.
