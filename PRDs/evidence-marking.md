# Evidence Marking

**Status:** v1.4 — 2026-11-25; the number allotted at marking is called the **exhibit number** throughout, as in the case file and view case (`DSB-14`, `DSB-15`, `EVM-01`). v1.3 — 2026-11-25; the provisional ID stays, with the evidence number shown beside it (`DSB-15`); the Documents tab shows the evidence number in view-case `DOC-18` (`EVM-01`); marking from the case file links to case-file `CFL-22` (`DSB-20`); the header names case-file.md and view-case.md §10 as owners. `Q-4` answered by case-file: a marked document appears in Exhibits and in its own category (`CFL-09`, §1); removed. v1.2 — 2026-11-25; `DSB-12`: the documents that can be marked as evidence are those in the categories listed in [`case-file.md`](case-file.md) §1.2, in place of any document in the case file. v1.1 — 2026-11-11; `Q-4` now links to [`case-file.md`](case-file.md), which owns the case file's contents and order. v1 — 2026-10-30; first version, moved out of [`document-submission.md`](document-submission.md) §4. Requirement IDs `DSB-12`–`DSB-15` and `DSB-20` keep their numbers. New: what a marked document shows (`EVM-01`) and that the A-Diary takes no entry for marking in this version (`EVM-02`). Open questions `Q-1`–`Q-4`.
**Audience:** developers and agents building evidence marking

Requirement IDs: `DSB-*` (carried over from document submission) and `EVM-*` — use in
tickets, commits, test names. Roles are owned by [`court-roles.md`](court-roles.md); the
case file by [`case-file.md`](case-file.md); the Documents tab by [`view-case.md`](view-case.md) §10.

---

# 1. Marking a document

| ID | Requirement |
| --- | --- |
| `DSB-12` | A document can be **marked as evidence** if it is in one of the categories listed in [`case-file.md`](case-file.md) §1.2. It is marked by a member of the court with the **Evidence marker** role. |
| `DSB-20` | Marking is available from the **case file** ([`case-file.md`](case-file.md) `CFL-22`) and from the Documents tab. |
| `DSB-13` | When marking, they choose **P** (prosecution) or **D** (defence). The court has no evidence series of its own: documents the court produces are marked P or D too. |

# 2. Numbers

| ID | Requirement |
| --- | --- |
| `DSB-15` | Every document on the case record is allotted a **provisional ID** when it enters the record: `DOC-` and a number in sequence within the case — DOC-1, DOC-2 …. It stays on the document after it is marked, and the exhibit number is shown beside it. |
| `DSB-14` | The exhibit number is allotted at marking, in sequence per side within the case: P1, P2 … and D1, D2 …. |
| `EVM-01` | A marked document shows its exhibit number wherever it is listed: in the Documents tab ([`view-case.md`](view-case.md) `DOC-18`) and in the case file ([`case-file.md`](case-file.md) `CFL-31`). |

# 3. Linked records

| ID | Requirement |
| --- | --- |
| `EVM-02` | Marking creates no A-Diary entry in this version ([`a-diary.md`](a-diary.md) `ADY-06`). |

# 4. Open questions

| ID | Question | Blocking |
| --- | --- | --- |
| `Q-1` | Is marking signed? DRISTI 1.0 stamps an evidence seal on the document (court, marked as, case number, marked through), which the magistrate signs; other staff send it to the magistrate's signing queue. | Yes |
| `Q-2` | Is **marked through** recorded — the witness or party through whom the document was marked (PW-1, DW-1 …)? DRISTI 1.0 requires it. Is the hearing it was marked in recorded? | No |
| `Q-3` | Can a marking be undone or corrected — wrong side, wrong document? | No |
