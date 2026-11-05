# Document Submission

**Status:** v5 — 2026-10-22; **draft, not complete**; added how a document's title is formed, by source (`DSB-23`). v4 — 2026-10-22; Filed by and Litigant removed from the flow, with `DSB-16`, `DSB-17` and `DSB-21` (numbers not reused); signing rewritten (`DSB-18`): an advocate or party-in-person signs their own submission, a clerk sends it to the advocates they work for and any one of them signs, a court member signs their own; each document shows its **source** (`DSB-22`). v3 — 2026-10-22; a party-in-person counts as an advocate for Filed by and signing; a court member's submission has no Filed by or Litigant (`DSB-21`); the court has no evidence series of its own (`DSB-13`). v2 — 2026-10-22; Filed by and Litigant dropdowns, signed by the advocate in Filed by (`DSB-16`–`DSB-18`); no payment (`DSB-19`); provisional ID format `DOC-n` (`DSB-15`); Application added as a document type in the filter (`DSB-11`); open questions closed; **any document in the case file** can be marked as evidence, not only submitted documents (`DSB-12`, `DSB-20`). v1 — 2026-10-22; first version: submitting documents (types, multiple documents, signing), statuses, the Documents tab, and marking evidence with prosecution and defence numbers.
**Audience:** developers and agents building document submission and the case's Documents tab

Requirement IDs: `DSB-*` — use in tickets, commits, test names. Roles are owned by
[`court-roles.md`](court-roles.md); the rest of the case view by
[`view-case-handover.md`](view-case-handover.md).

---

# 1. Submitting documents

Opened from **Make filings → Submit documents** on a case.

| ID | Requirement |
| --- | --- |
| `DSB-01` | **Document type** is a dropdown of three types: **Affidavit**, **Memo**, **Evidence**. |
| `DSB-02` | One submission carries **multiple documents**, added the same way as Supporting documents on an application ([`application-lifecycle.md`](application-lifecycle.md)): add as many as needed, one entry per document. |
| `DSB-03` | Before it is submitted, the submission goes through **signing**. Submitting happens only once it is signed. |
| `DSB-18` | **Who signs.** An advocate submitting documents signs them; a party-in-person counts as an advocate. A clerk cannot sign: they **send for signing**, and the submission goes to every advocate the clerk works for ([`office-management-handover.md`](office-management-handover.md)) who is on the case. Any one of them signs it. A member of the court signs their own submission. |
| `DSB-19` | Submitting documents involves **no payment**. |
| `DSB-04` | Anyone with case access can submit documents, and so can **any member of the court**. |

# 2. Statuses

| Status | Meaning |
| --- | --- |
| Draft | Being prepared; not yet sent for signature |
| Pending signature | Waiting to be signed |
| Submitted | Signed and on the case record |
| Marked as evidence | Marked by the court, with an evidence number (§4) |

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

| ID | Requirement |
| --- | --- |
| `DSB-12` | **Any document in the case file** can be **marked as evidence** — whatever its type or source (filing, application, submitted document, deposition) — by a member of the court with the **Evidence marker** role. |
| `DSB-20` | Marking is available from the **case file** ([`view-case-handover.md`](view-case-handover.md) `DET-12`) and from the Documents tab. |
| `DSB-13` | When marking, they choose **P** (prosecution) or **D** (defence). The court has no evidence series of its own: documents the court produces are marked P or D too. |
| `DSB-14` | The evidence number is allotted at marking, in sequence per side within the case: P1, P2 … and D1, D2 …. |
| `DSB-15` | Every document on the case record is allotted a **provisional ID** when it enters the record: `DOC-` and a number in sequence within the case — DOC-1, DOC-2 …. It stays on the document after it is marked; the evidence number is shown in its place. |
