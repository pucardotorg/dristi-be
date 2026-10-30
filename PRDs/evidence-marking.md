# Evidence Marking

**Status:** v1 — 2026-10-30; first version, moved out of [`document-submission.md`](document-submission.md) §4. Requirement IDs `DSB-12`–`DSB-15` and `DSB-20` keep their numbers. New: what a marked document shows (`EVM-01`) and that the A-Diary takes no entry for marking in this version (`EVM-02`). Open questions `Q-1`–`Q-4`.
**Audience:** developers and agents building evidence marking

Requirement IDs: `DSB-*` (carried over from document submission) and `EVM-*` — use in
tickets, commits, test names. Roles are owned by [`court-roles.md`](court-roles.md); the
case file and Documents tab by [`view-case-handover.md`](view-case-handover.md) and
[`document-submission.md`](document-submission.md).

---

# 1. Marking a document

| ID | Requirement |
| --- | --- |
| `DSB-12` | **Any document in the case file** can be **marked as evidence** — whatever its type or source (filing, application, submitted document, deposition) — by a member of the court with the **Evidence marker** role. |
| `DSB-20` | Marking is available from the **case file** ([`view-case-handover.md`](view-case-handover.md) `DET-12`) and from the Documents tab. |
| `DSB-13` | When marking, they choose **P** (prosecution) or **D** (defence). The court has no evidence series of its own: documents the court produces are marked P or D too. |

# 2. Numbers

| ID | Requirement |
| --- | --- |
| `DSB-15` | Every document on the case record is allotted a **provisional ID** when it enters the record: `DOC-` and a number in sequence within the case — DOC-1, DOC-2 …. It stays on the document after it is marked; the evidence number is shown in its place. |
| `DSB-14` | The evidence number is allotted at marking, in sequence per side within the case: P1, P2 … and D1, D2 …. |
| `EVM-01` | A marked document shows its evidence number wherever it is listed — in the Documents tab's Evidence number column ([`document-submission.md`](document-submission.md) `DSB-10`) and in the case file. |

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
| `Q-4` | Where does a marked document sit in the case file: does it move under the evidence headings ([`view-case-handover.md`](view-case-handover.md) §6.2), or stay where it was filed? | No |
