# Document Submission

**Status:** v6 — 2026-10-30; **marking evidence moved to its own PRD**, [`evidence-marking.md`](evidence-marking.md) (`DSB-12`–`DSB-15`, `DSB-20` keep their numbers); Marked as evidence is no longer a submission status, since any document can be marked. A clerk's send for signing raises a **Sign documents** pending task for the advocates (`DSB-24`). New open questions `Q-1`–`Q-8`. v5 — 2026-10-22; **draft, not complete**; added how a document's title is formed, by source (`DSB-23`). v4 — 2026-10-22; Filed by and Litigant removed from the flow, with `DSB-16`, `DSB-17` and `DSB-21` (numbers not reused); signing rewritten (`DSB-18`): an advocate or party-in-person signs their own submission, a clerk sends it to the advocates they work for and any one of them signs, a court member signs their own; each document shows its **source** (`DSB-22`). v3 — 2026-10-22; a party-in-person counts as an advocate for Filed by and signing; a court member's submission has no Filed by or Litigant (`DSB-21`); the court has no evidence series of its own (`DSB-13`). v2 — 2026-10-22; Filed by and Litigant dropdowns, signed by the advocate in Filed by (`DSB-16`–`DSB-18`); no payment (`DSB-19`); provisional ID format `DOC-n` (`DSB-15`); Application added as a document type in the filter (`DSB-11`); open questions closed; **any document in the case file** can be marked as evidence, not only submitted documents (`DSB-12`, `DSB-20`). v1 — 2026-10-22; first version: submitting documents (types, multiple documents, signing), statuses, the Documents tab, and marking evidence with prosecution and defence numbers.
**Audience:** developers and agents building document submission and the case's Documents tab

Requirement IDs: `DSB-*` — use in tickets, commits, test names. Roles are owned by
[`court-roles.md`](court-roles.md); the rest of the case view by
[`view-case-handover.md`](view-case-handover.md); marking a document as evidence by
[`evidence-marking.md`](evidence-marking.md).

---

# 1. Submitting documents

Opened from **Make filings → Submit documents** on a case.

| ID | Requirement |
| --- | --- |
| `DSB-01` | **Document type** is a dropdown of three types: **Affidavit**, **Memo**, **Evidence**. |
| `DSB-02` | One submission carries **multiple documents**, added the same way as Supporting documents on an application ([`application-lifecycle.md`](application-lifecycle.md)): add as many as needed, one entry per document. |
| `DSB-03` | Before it is submitted, the submission goes through **signing**. Submitting happens only once it is signed. |
| `DSB-18` | **Who signs.** An advocate submitting documents signs them; a party-in-person counts as an advocate. A clerk cannot sign: they **send for signing**, and the submission goes to every advocate the clerk works for ([`office-management-handover.md`](office-management-handover.md)) who is on the case. Any one of them signs it. A member of the court signs their own submission. |
| `DSB-24` | Sending for signing raises a **Sign documents** pending task for those advocates. It closes when any one of them signs. |
| `DSB-19` | Submitting documents involves **no payment**. |
| `DSB-04` | Anyone with case access can submit documents, and so can **any member of the court**. |

# 2. Statuses

| Status | Meaning |
| --- | --- |
| Draft | Being prepared; not yet sent for signature |
| Pending signature | Waiting to be signed |
| Submitted | Signed and on the case record |

| ID | Requirement |
| --- | --- |
| `DSB-05` | The statuses above are held by the backend. The Documents tab does not show them as a column (§3). |
| `DSB-06` | A document is visible to **all parties on the case** as soon as it is Submitted. |

# 3. Documents tab

| ID | Requirement |
| --- | --- |
| `DSB-07` | Columns: Document (title and source), Document type, Submitted by, Submitted on, **Evidence number**, Actions. |
| `DSB-08` | The Document column shows the title and source (`DSB-22`) only — no identifier under it. |
| `DSB-22` | Every document carries a **source**, shown under its title: **Complaint**, **Application**, **Submitted directly** (through Submit documents) or **Deposition**. |
| `DSB-23` | **Title**, by source: |
| | **Complaint** — the name of the e-filing upload slot the file was uploaded to (Cheque, Demand notice, Proof of dispatch …). Where a slot holds more than one file, a number in upload order: Cheque 1, Cheque 2. |
| | **Application** — the application itself is named by its application type; a fixed attachment by its field name (Proof of solvency); a supporting document by the name the filer gave it. |
| | **Submitted directly** — the title the filer entered. |
| | **Deposition** — generated from the witness number: Deposition of PW-1. |
| `DSB-09` | Documents in Draft or Pending signature appear only under **Needs attention**. |
| `DSB-10` | **Evidence number** shows the provisional ID until the document is marked, then its evidence number (P1, D1 …). |
| `DSB-11` | The **Document type** filter offers: Affidavit, Memo, Evidence, **Deposition**, **Filing**, **Application**. Filing covers documents that came in with the complaint; Application covers documents submitted with an application. |

# 4. Marking evidence

Any document in the case file can be marked as evidence, a submitted document included.
Owned by [`evidence-marking.md`](evidence-marking.md).

# 5. Open questions

| ID | Question | Blocking |
| --- | --- | --- |
| `Q-1` | **Document types.** DRISTI 1.0 offers Affidavits, Memos, Objections and Others to filers, and Miscellaneous to the court only; it has no Evidence type. Are Objections, Others and a court-only Miscellaneous kept alongside Affidavit, Memo and Evidence (`DSB-01`)? | Yes |
| `Q-2` | **Fields per document.** Besides title, type and file, DRISTI 1.0 asks for a mandatory **reason for filing**. Is it kept? Which file formats and size limit apply? DRISTI 1.0: PDF, JPG, JPEG, PNG, 10 MB per file. | Yes |
| `Q-3` | **Who signs a clerk's submission.** `DSB-18` lets any advocate the clerk works for sign; an application is signed only by the advocate named in Raised by (`ALC-28`). Should the two match? | No |
| `Q-4` | **Litigants and PoA holders.** `DSB-04` lets anyone with case access submit. How does a represented litigant or a PoA holder sign their submission — or do they submit at all? | Yes |
| `Q-5` | **Drafts.** Can the filer delete a Draft or a Pending signature submission? What happens when the advocate declines to sign? | No |
| `Q-6` | **When it is offered.** Can documents be submitted before registration, or after the case is disposed of? DRISTI 1.0 offers it only between registration and disposal. | No |
| `Q-7` | **Mandatory submissions.** Does a document submitted here close a task raised by the Mandatory submissions and responses order item, or does that always go through a Production of Documents application? | No |
| `Q-8` | **Notifications.** Is the other side notified when a document is Submitted? Is a document filed in error withdrawn in any way, now that Mark as Void is removed (`view-case-handover.md` v1.9)? | No |
