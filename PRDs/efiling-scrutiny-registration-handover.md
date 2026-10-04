# E-Filing, Scrutiny and Registration — Developer & Agent Handover

**Status:** v25 — 2026-09-28; **§16.10 removed** — everything in it (`ACC-5` renamed,
the added fields, "print per `DOC-01`") was already stated in §8's field table, §16.2's
terminology note and the batch-8 log (§20); the section restated settled history rather
than specifying anything. **§16.9's sample PDF regenerated** against the merged §16.4
print order: same invented case, eight pages instead of nine, case title reads `+1
other`/`+3 others`, and Case details is one section per screen (§2.1–2.4). Link now
points at the repo copy (`efiling-reference/complaint-pdf-worked-example.pdf`); the
Coda-hosted copy is the stale pre-merge version and needs re-syncing.
v24 — 2026-09-28; two owner corrections to §16.5, the cover page: (1) the
**case title's multi-party suffix is `+N others`**, not `& Ors.` — `& Ors.` never
actually printed; (2) **title of proceeding is now a case-type variable, not a fixed
string** — each case type carries a short title (screens) and a long title (PDFs), so
the platform can hold more case types than §138 later without rewriting this line.
`CASE_TYPE.proceedingTitleShort`/`proceedingTitleLong` (`options.ts`) and
`court-document.tsx` updated to match.
v23 — 2026-09-28; **§16.4 print order now follows the wizard's own screen
order** (`DOC-01`, `DOC-06`, §16.1, §16.4, §16.8): Cheque & Return Memo, Legal Demand
Notice, Jurisdiction & Limitation, and ADR/Prayer/Other Details each print as one
section instead of splitting across several (print §2.1–2.4 replace the old §2.1–2.9);
within each, fields print in the screen's own collection order — `LDN-1` Nature of debt
now prints first, where it's collected, instead of last. Two exceptions stand: the
advocate card still prints Full Name before Bar Registration (reversed from collection
order, by owner decision), and Synopsis still prints first (it isn't collected on any
screen, so "collection order" doesn't apply to it). The Documents screen's split — list
at §3.2, files appended after §4 — is unchanged; it's a physical-attachment necessity,
not a reordering. **§16.9's sample PDF is now stale against this structure** and needs
regenerating; nothing in §16.1–§16.8 depends on it. Prototype code
(`court-document.tsx`) updated to match.
v22 — 2026-09-28; **§16.9 links the filled sample** — the heading now points
straight at `complaint-pdf-worked-example.pdf` instead of naming it in the heading text,
pulled down from an edit made directly on the Superhuman Docs page.
v21 — 2026-09-27; **ID card is court-only** (`DCM-9`, `DCM-10`, §14):
visible to the court, never to the accused side — new owner decision, partially
resolving the open "Aadhaar storage/masking" and "accused-side experience" questions
(§21). How it's enforced against a single generated complaint PDF is still open.
v20 — 2026-09-27; **doc hygiene**: the `Status` (New/Existing/Deleted)
column is dropped from every field table — it's development history, not a requirement,
and cluttered the read. Moved wholesale to a new `docs/kerala-migration-plan.md`,
grouped by section, to pick up later; nothing is lost. The Autofill note (§5) is
restated as a plain requirement instead of "X is removed, Y replaces it" — the removal
narrative added nothing and only confused. JUR-8's Logic cell ("ditto") is spelled out
in full — a repeated value written as a placeholder read as unprofessional.
v19 — 2026-09-27; **Police Station made mandatory** (`ACC-13`, `JUR-5`,
`JUR-6a`): all three were optional; per the owner, wherever a Police Station field
exists it is now required. §8, §11 updated.
v18 — 2026-09-27; **Oath repositioned, Affidavit gets its own section** (`OTH`, new
§14a; `PRY-4` screen-level facts, new §14b): both move to after Documents, in that
order, and both stay full, separate sections — an oath (administered at deposition) and
an affidavit (a document tendered as evidence) are distinct acts, per the P&H case files.
They only share one sidebar heading, "Affidavit", as a navigation grouping. Corrects v17,
which placed Oath between Witnesses and Documents as a standalone section, and corrects
an intermediate edit the same day that folded it under Affidavit as if subordinate to
it — neither was right. §5 updated.
v17 — 2026-09-26; **new mandatory section, Oath** (`OTH`, new §13a, `FIL-03`):
a per-complainant video of the complainant reciting the oath, its own screen between
Witnesses and Documents in the form order (§5) — blocks Preview like every other
mandatory section. Not a document on the `DCM` list and not appended to the complaint
PDF — a video cannot be embedded in a printed document; it is stored with the case file
and reviewed like any other upload. Wording is a placeholder pending legal confirmation
— see the note under §13a.
v16 — 2026-09-23; **registration point is now configurable** (`SCR-11/12`):
under `registrationPoint: scrutiny`, the scrutiny officer's second action is **Register**
(not Forward) — it assigns the case number and moves the case straight to Cognisance,
and the magistrate's separate Registration stage/task is skipped entirely. Default
remains `registrationPoint: magistrate` — today's behaviour, unchanged. §3, §4, §20.2,
§20.3 updated; new §20.3a; glossary gains **Registration**.
v15 — 2026-09-18; **the complaint-PDF specification is merged into §16**,
which now carries the whole thing as §16.1–§16.10 — generative rule, layout, value
formatting, print order, cover, signatures, appended documents, the form↔print divergence
map, and the filled sample. The separate `complaint-pdf-template.md` is deleted; there is
no second document to keep in step. New IDs `DOC-04` layout, `DOC-05` value formatting,
`DOC-06` print order, `DOC-07` appended documents; `DOC-01/02/03` unchanged.
v14 — 2026-09-18; owner decisions: `ACC-5` renamed **Institution Name** ·
no masking of the ID card at launch (not a deferred call) · optional personal fields
print · persons vicariously liable print in full, one block per person. v13 — 2026-09-18; `DOC-01` extended: the print rule is **literal** —
form-steering fields (`LIT-1`, `LIT-8`, `LIT-10`, `LIT-15`, `CHQ-4`, `ADV-1`) print like
any other and no exception list is to be maintained. The template spec now carries a
form↔print divergence map (its §8) and a filled worked-example PDF (its §10). v12 — 2026-09-18; §16 rewritten: the complaint PDF is generated from the
case's own field set rather than a hardcoded template (`DOC-01`), signature placeholders
are positioned per required signatory (`DOC-02`), cover derivations decided — no
hardcoded court name, full names in the title, whatever case number exists (`DOC-03`);
documents DCM-9/DCM-10 renamed "ID Card"; blank optional fields print `-`; reference-folder
paths corrected to `efiling-reference/`; owner decisions batch 8 logged. v11 — 2026-09-17; the hand-written
pending-task table in §20.2 replaced with live views of the master Pending Tasks tables
(court and citizen side); §20.5 now carries live views of the master Notifications and
Events tables
**Date:** 2026-09-18
**Audience:** developers and agents building the e-filing module (front end and backend)

## Sources and precedence

| Precedence | Source (reference files in `efiling-reference/` unless noted) | Provides |
| --- | --- | --- |
| 1 — **source of truth** | `E-Filing Fields.xlsx` (cell content only — **all threaded comments are void**, per owner) | Every field: type, validation, visibility, migration |
| 2 | `E-filing, Scrutiny and Registration.pdf` | Roles, workflow states, functional requirements |
| 2 | `Payment Logic.pdf` | Fee heads, amounts, slabs |
| 2 | `Templates (1).pdf` | Pre-populated textbox templates |
| 2 | `Templates.pdf` | Complaint PDF — an earlier filled sample |
| — illustration | `complaint-pdf-worked-example.pdf` | The generated complaint PDF as it comes out, produced from §16; invented data, **not normative** (§16.9) |
| 3 — interaction reference | Dristi app prototype: `Pucar-Dristi-2.0` @ `feature/e-filing-new`, `apps/dristi-app`, routes `/filings/**` | Screen behaviour: navigation, upload-first intake, OCR provenance, autosave, sign/pay |
| — | Owner decisions, 2026-08-25/26 | Recorded inline as **[OWNER]**; log in §20 |

Conflicts: xlsx wins over the PDFs, both win over the prototype; owner decisions win
over everything. Marks: `[DERIVED]` inferred, confirm before building · `[GAP]` not
specified, blocks the item · `[CURRENT]` today's behaviour, not automatically a
requirement · `[PROTO]` prototype-only, an interaction reference · `[OWNER]` owner
decision.

Requirement IDs (`ROLE/LIFE/FIL/VAL/SIG/PAY/SCR/DOC/REF-*`) and field IDs
(`<sheet>-<Sl. No.>`: `LIT ADV ACC CHQ LDN JUR PRY WIT DCM SYN`) — use in tickets,
commits, test names.

---

# 1. Scope

From first draft through registration: data entry (field-level), signing, payment,
scrutiny, correction cycles, registration; the generated complaint PDF; interaction
patterns. **[OWNER]** s.138 NI Act only — no other case types, no generalisation needed.

Out: post-registration stages; e-sign provider internals; payment-gateway integration
itself. Bulk/batch signing is the separate `../signing/` workstream.

---

# 2. Entry context

- `ASM-01` — the user is **already logged in** when the flow starts.
- `ASM-02` **[OWNER]** — a **profile switcher on the home screen** precedes the filing
  flow, so within the flow the user's role is predetermined: **advocate, clerk, or
  litigant**. A **PoA-holder** and a **party-in-person** can also file a case.

Role effects at entry:

| Role | Effect | Trace |
| --- | --- | --- |
| Advocate | PiP is **No and disabled for the 1st complainant** (an advocate-filed case needs a represented complainant) | `LIT-1` |
| Advocate | The filing advocate **and their associated junior advocates** are auto-added to the Advocate section (juniors removable), count set accordingly | `ADV-1` |
| Clerk | **[OWNER]** the advocate(s) the clerk works for are **auto-added the same way** | `ADV-1` |
| Clerk | Cannot e-sign (only rights difference; everything else allowed, incl. moving to signing and uploading a signed copy). **Enforce server-side** | `ROLE-08` |
| Litigant | **[OWNER]** the logged-in litigant **is Complainant 1** | §6 |

---

# 3. Roles and permissions

Filing roles: Advocate · Clerk/Junior Advocate · Litigant · PoA-Holder ·
Party-in-Person. Court roles: Scrutiny Officer · Magistrate.

**Scope predicates** — a user can view/edit a draft when (regardless of who created it,
`ROLE-06`):

| ID | Role | Condition |
| --- | --- | --- |
| `ROLE-01` | Advocate | added as an advocate on the case |
| `ROLE-02` | Clerk / Jr. Advocate | an advocate **they work for** is added on the case |
| `ROLE-03/05` | Litigant / PiP | added as a complainant on the case |
| `ROLE-04` | PoA-Holder | added as a complainant's PoA-holder on the case |

Permission matrix (`ROLE-07` — additionally gated by the predicates and case state):

| Action | Advocate | Clerk | Litigant | PoA | PiP | Scrutiny | Magistrate |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Create / view / edit drafts | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| Delete draft | ✓ ² | ✓ ² | ✓ ² | ✓ ² | ✓ ² | — | — |
| Add advocates to case | ✓ | ✓ | ✓ | ✓ | ✓ ¹ | — | — |
| Move to signing | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| Perform e-sign | ✓ | **✗** | ✓ | ✓ | ✓ | — | — |
| Upload signed document | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| Make payment / correct errors | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| Mark errors + send back / forward or register ³ | — | — | — | — | — | ✓ | — |
| Register / send back ³ | — | — | — | — | — | — | ✓ |

¹ A PiP may add advocates **for other complainants only**.
³ Which second scrutiny action, and whether the magistrate row applies at all, depends on
the `registrationPoint` config — see `SCR-11` (§20.3a).
² **Creator only (preferred)** — unlike other draft actions (which use the scope predicate), delete is ideally restricted to the user who created the draft. If that adds significant complexity, v1 may use the normal scope predicate instead and tighten later. See `LIFE-14`.

**[OWNER]** The clerk↔advocate mapping **exists elsewhere in the system** — consume it,
don't build it. **When someone is removed from a case, they lose access to it.**

---

# 4. Case lifecycle

| Initial stage | Action | New stage |
| --- | --- | --- |
| — | Create Draft | Draft |
| Draft | Save Draft | Draft |
| Draft | Delete Draft | *(deleted)* |
| Draft | Proceed to Sign | Pending Signature |
| Pending Signature | Delete Draft | *(deleted)* |
| Pending Signature | e-Sign | Pending Signature *(partial)* / Pending Payment *(last signature)* |
| Pending Signature | Upload Signed Document | Pending Payment |
| Pending Payment | Delete Draft | *(deleted)* |
| Pending Payment | Pay | Scrutiny |
| Scrutiny | Mark Defects and Send Back | Pending Correction |
| Scrutiny | Forward Case (`registrationPoint: magistrate`) | Registration |
| Scrutiny | Register (`registrationPoint: scrutiny`) | Cognisance |
| Registration | Register | Cognisance |
| Registration | Send Back | Pending Correction |
| Pending Correction | Save Draft | Pending Correction |
| Pending Correction | Proceed to Sign | Pending Signature |
| Pending Signature *(correction loop)* | e-Sign / Upload | Scrutiny — or Pending Payment per `LIFE-12` |

- The Registration row only occurs under `registrationPoint: magistrate` (the default);
  under `registrationPoint: scrutiny` the Scrutiny → Register → Cognisance row applies
  instead and the Registration stage never exists for that case. See `SCR-11` (§20.3a).
- `LIFE-11` — send-backs may repeat without limit.
- `LIFE-12` **[OWNER]** — on resubmission the amount is recalculated: **increased →
  payment step, extra amount collected before Scrutiny; not increased → payment step
  skipped**. No automatic refund when lower; the system later auto-generates a **refund
  note** the filer uses to claim the refund.
- `LIFE-13` — corrections require re-signing. **[OWNER]** any edit to the case
  **invalidates all signatures**.
- `LIFE-14` **[OWNER]** — **Delete Draft.** A draft can be deleted, subject to:
  - **Who:** only the user who **created** the draft — not every user with scope-predicate
    access. This is the one action where creator identity matters, not association.
    *However, this is a safety preference, not a hard requirement. If creator-only
    tracking adds significant complexity, v1 can allow deletion by anyone with edit
    access (the normal scope predicate) and restrict to creator-only in a later version.*
  - **When:** available in `Draft`, `Pending Signature` and `Pending Payment` — i.e.
    **up to the point that payment is made**. Once payment completes (case moves to
    `Scrutiny`), the draft cannot be deleted.
  - **Correction cycles:** a case in `Pending Correction` (sent back by scrutiny or
    magistrate) **cannot** be deleted — it has already been through payment and scrutiny.
  - Deletion is permanent. Confirm before executing.

---

# 5. Form structure

Sections in order — each a screen; repeatable sections carry "N" records:

1. Litigant (Complainant) Details — "Complainant N" (§6)
2. Advocate Details — "Advocate N" (§7)
3. Accused Details — "Accused N" (§8)
4. Cheque and Return Memo — "Cheque N" (§9)
5. Legal Demand Notice — "Demand Notice N" (§10)
6. Jurisdiction & Limitation (§11)
7. ADR, Prayer, Other Details (§12)
8. Witness Details — "Witness N" (§13)
9. Documents (§14)
10. **Oath — its own screen, mandatory** **[OWNER]** (§14a): a video per complainant,
    repeating the oath wording once per record
11. **Affidavit — its own screen** **[OWNER]** (§14b; content: `PRY-4`, §17 template 1;
    the PiP affidavit stays a field in Litigant, `LIT-27`)
12. Synopsis — auto-generated, shown after the case moves to signing (§15)

Oath (10) and Affidavit (11) are two separate sections — distinct acts in the case file,
not one nested in the other (see the P&H case files: the oath is administered at witness
deposition, the affidavit is a document tendered as evidence — different moments,
different records). **[OWNER]** They share one heading in the sidebar, "Affidavit", with
Oath listed first, because both are sworn statements filed back to back late in the
form — a navigation grouping only, not a content one.

**Gating** **[OWNER]**: **Advocate Details is hard-gated** — locked until Complainant
Details is complete (`FIL-01`, option A). `[DERIVED]` "complete" = every mandatory field
of every complainant record passes validation. `FIL-02` — Delay Condonation (in §11)
requires Legal Demand Notice completed first. **[OWNER]** — **Preview / the complaint
PDF is accessible only after all mandatory fields are filled and validations pass**
(§16).

**Terminology** **[OWNER]**: type is **Individual / Institution** ("Institution", not
"Entity").

**Address composite** **[OWNER]** — one definition, used everywhere an "Address"
appears. **Police Station is not part of the composite** — it is a separate field, only
where a sheet specifies it (accused §8, jurisdiction §11):

| Field | Type | Notes |
| --- | --- | --- |
| Line 1 | Text | |
| City/Town | Text | |
| Pincode | Number, 6-digit | |
| District | Dropdown | auto-filled from pincode |
| State | Dropdown | auto-filled from pincode |

**Address order** **[OWNER]** — wherever two addresses pair: **Permanent address first,
then "Is the current address the same as the permanent address?", then Current address**
(shown when No). Consistent across the whole form.

**Autofill** **[OWNER]** — only the logged-in user's own details are auto-filled, when
they are filing for themselves. No cross-user lookup anywhere.

---

# 6. Litigant (Complainant) Details — `LIT`

Repeats per complainant. Individual vs Institution branches the section.

| ID | Field | Type | Validation | Visible when / logic |
| --- | --- | --- | --- | --- |
| LIT-1 | Are you representing yourself as a Party-in-Person? | Radio Yes/No | — | **No + disabled for 1st complainant if an advocate is filing.** Tooltip: "If you have an advocate, select No. You can appoint an advocate at any time during the case." |
| LIT-2 | Complainant Type | Radio Individual/Institution | — | — |
| LIT-3 | Phone Number | Phone | Valid; **not same as any other complainant, accused, advocate or PoA**. Tooltip: if it is the advocate's number, error "Please do not enter the advocate's number here." | Individual |
| LIT-4 | Full Name | Text | Alphabetic | Individual; self-autofill only (§5) |
| LIT-5 | Age | Number | Integer, positive | Individual |
| LIT-5a | Gender | Dropdown: Male / Female / Other | — | Individual; **optional** |
| LIT-5b | Differently abled? | Radio Yes/No | — | Individual; **optional** |
| LIT-6 | Email ID | Email | Valid; optional | Individual |
| LIT-7 | Permanent Address | Address composite (§5) | — | Individual |
| LIT-8 | Is current address same as permanent? | Radio Yes/No | — | Individual |
| LIT-9 | Current Address | Address composite | — | Individual AND same = No |
| LIT-10 | Has this litigant transferred Power of Attorney to somebody else? | Radio Yes/No | — | Individual |
| LIT-11 | PoA Phone Number | Phone | Valid | PoA = Yes |
| LIT-12 | PoA Holder Full Name | Text | — | PoA = Yes |
| LIT-13 | PoA Holder Age | Number | Integer, positive | PoA = Yes |
| LIT-13a | PoA Holder Email | Email | Valid; optional | PoA = Yes |
| LIT-14 | PoA Permanent Address | Address composite | — | PoA = Yes |
| LIT-15 | PoA current same as permanent? | Radio Yes/No | — | PoA = Yes |
| LIT-16 | PoA Current Address | Address composite | — | PoA = Yes AND same = No |
| LIT-17 | Type of Institution | Dropdown | Values from MDMS | Institution |
| LIT-18 | Institution Name | Text | — | Institution |
| LIT-19 | Phone Number (Institution Contact) | Phone | Valid; optional | Institution |
| LIT-20 | Email ID (Institution Contact) | Email | Valid; optional | Institution |
| LIT-21 | Institution Address | Address composite | — | Institution |
| LIT-22 | Authorised Representative Phone | Phone | — | Institution |
| LIT-23 | Authorised Representative Full Name | Text | — | Institution |
| LIT-24 | Authorised Representative Age | Number *(sheet says Text)* | — | Institution |
| LIT-24a | Authorised Representative Gender | Dropdown: Male / Female / Other | — | Institution; **optional** |
| LIT-24b | Authorised Representative Differently abled? | Radio Yes/No | — | Institution; **optional** |
| LIT-25 | Authorised Representative Email | Email | Valid; optional | Institution |
| LIT-25a | Authorised Representative Designation | Text | — | Institution |
| LIT-26 | Authorised Representative Address | Address composite | — | Institution |
| LIT-27 | PiP Affidavit | Rich text, pre-populated (§17 template 2), editable | — | PiP = Yes |

---

# 7. Advocate Details — `ADV`

**Hard-gated behind Complainant Details (§5).** Hidden/zeroed when every complainant is
a PiP.

| ID | Field | Type | Validation | Logic |
| --- | --- | --- | --- | --- |
| ADV-1 | Number of advocates | Stepper | Integer ≥ 0 | Always visible; must equal advocates added; **0 + disabled if all litigants are PiP**. **Auto-add the filing advocate and all their associated junior advocates** (removable). **[OWNER]** a filing clerk's advocates are auto-added the same way |
| ADV-2 | Advocate for | Dropdown of all non-PiP complainants | — | Preselect all non-PiP complainants |
| ADV-3 | Advocate BAR Registration | Dropdown / search | — | Fetch from backend |
| ADV-4 | Advocate Full Name | Text, auto-filled | — | From BAR registration; **not editable** |

The advocate–complainant mapping feeds signing (§18) and payment (§19).

---

# 8. Accused Details — `ACC`

Repeats per accused. Individual vs Institution branches.

| ID | Field | Type | Validation | Visible when / logic |
| --- | --- | --- | --- | --- |
| ACC-1 | Accused Type | Radio Individual/Institution | — | — |
| ACC-2 | Full Name | Text | Alphabetic | Individual |
| ACC-3 | Age | Number | Integer ≥ 1; optional | Individual |
| ACC-4 | Type of Institution | Dropdown | Values from MDMS | Institution |
| ACC-5 | Institution Name | Text | — | Institution |
| ACC-6 | Mobile Number (contact) | Phone | Valid | both types; skippable per rule below |
| ACC-7 | Email ID (contact) | Email | Valid | both types; skippable per rule below |
| ACC-8…12 | Address | Address composite (§5) — **repeatable: multiple addresses per accused** (process fees are per address, §19) | — | — |
| ACC-13 | Police Station | Dropdown | **Mandatory** **[OWNER]** | per address |
| ACC-14 | Representative Full Name | Text | — | Institution; **repeatable** (below) |
| ACC-15 | Representative Designation | Text | Optional | Institution |
| ACC-16 | Representative Mobile | Phone | Valid | Institution `[DERIVED]` |
| ACC-17 | Representative Email | Email | Valid | Institution `[DERIVED]` |
| ACC-18…23 | Representative Address (+ Police Station) | Address composite | — | Institution |
| ACC-24 | Resides within jurisdiction — "jurisdiction" links to https://oncourts.kerala.gov.in/about | Radio Yes/No | — | **[OWNER]** no in-flow effect on No — information for the magistrate's judgment |

**Missing contacts** **[OWNER]** — when the filer has neither phone nor email for an
accused, they proceed by declaring they don't know them (§17 template 3). The
declaration is **recorded as data in the backend; nothing is added to the case file.**
`[PROTO]` dialog + checkbox before Continue.

**Persons responsible for the institution** **[OWNER]** — the representative block
(ACC-14…23) is **repeatable**: the filer may add multiple persons responsible for the
company (s.141), and **later in the flow each person appears as a separate accused**.

---

# 9. Cheque and Return Memo — `CHQ`

Repeats per cheque.

| ID | Field | Type | Validation | Logic |
| --- | --- | --- | --- | --- |
| CHQ-1 | Date on cheque | Date picker | — | Tooltip: as written on the cheque |
| CHQ-2 | Amount | Number | Positive | Tooltip: as written on the cheque |
| CHQ-3 | Cheque Number | Number | 6-digit | Tooltip: first set of six digits printed at the bottom |
| CHQ-4 | Bank details same as previous cheque? | Radio Yes/No | — | Default **No**; **not shown for 1st cheque** |
| CHQ-5 | IFSC Code | Text | — | **[OWNER]** lookup fires **automatically** on a valid IFSC (no fetch button); or carried from previous cheque |
| CHQ-6 | Bank Name | Text | — | Auto from IFSC / previous cheque |
| CHQ-7 | Bank Branch | Text | — | Auto from IFSC / previous cheque |
| CHQ-7a | Bank Account Number | Text | — | As on the cheque; feeds SYN-9 and complaint PDF §2.1 |
| CHQ-8 | Date of presentation/deposit | Date picker | **≥ CHQ-1** | Always visible |
| CHQ-9 | Date of return | Date picker | **≥ CHQ-8** | Always visible; tooltip: as on the return memo |
| CHQ-10 | Return reason | Dropdown, MDMS | **Warning if not "Insufficient Funds"** | Always visible |

---

# 10. Legal Demand Notice — `LDN`

Repeats per demand notice.

| ID | Field | Type | Validation | Logic |
| --- | --- | --- | --- | --- |
| LDN-1 | Nature of debt/liability | Dropdown, MDMS | — | Always visible. Tooltip: purpose/underlying transaction for the cheque |
| LDN-2 | Date of dispatch of demand notice | Date picker | **[OWNER]** at least one cheque's date of return (CHQ-9) must be **on or before** the dispatch date. **No 30-day warning** (removed by owner; the receipt-of-information date is not collected) | — |
| LDN-3 | Mode of service | Dropdown, MDMS | — | — |
| LDN-4 | Tracking number | Text | Optional | Tooltip: used to track delivery |
| LDN-5 | Whether delivered? | Radio Yes/No | — | — |
| LDN-6 | Date of delivery | Date picker | ≥ LDN-2 | Delivered = Yes |
| LDN-7 | Date of Return | Date picker | ≥ LDN-2 | Delivered = No; tooltip: returned to the delivery agency undelivered |
| LDN-8 | Reason for non-delivery | Dropdown, MDMS (values already in the MDMS sheet) | Mandatory when No | Delivered = No |
| LDN-9 | Has the accused replied to the demand notice? | Radio Yes/No | — | Always visible |
| LDN-10 | Has the Drawer made full or part payment due under the cheque? | Dropdown: Part Payment / No Payment Made | — | Always visible |
| LDN-11 | How much payment has already been made? | Number | — | Part payment only |

---

# 11. Jurisdiction & Limitation — `JUR`

| ID | Field | Type | Validation | Logic |
| --- | --- | --- | --- | --- |
| JUR-1 | Did the Payee (Complainant) deposit the cheque in their bank account? | Radio Yes/No | — | Drives the s.142(2) jurisdiction basis: deposited → payee's bank branch; else → drawer's |
| JUR-2 | IFSC Code (complainant's branch) | Text | — | Deposited = Yes; **[OWNER]** automatic lookup |
| JUR-3 | Bank Name | Text | — | Deposited = Yes; auto from IFSC |
| JUR-4 | Bank Branch | Text | — | Deposited = Yes; auto from IFSC |
| JUR-5 | Police Station of bank branch | Dropdown, MDMS | **Mandatory** **[OWNER]** | Deposited = Yes |
| JUR-6a | Police Station of Drawer (Accused) bank branch | Dropdown, MDMS | **Mandatory** **[OWNER]** | **[OWNER]** shown when Deposited = **No** |
| JUR-6b | Is there any other cheque dishonour complaint pending between the same parties? | Radio Yes/No | — | Always visible |
| JUR-7 | Court | Text | Optional | Other cases = Yes; repeatable per case |
| JUR-8 | Case Number | Text | Optional | Other cases = Yes; repeatable per case |
| JUR-9 | Date of cause of action | Date picker | — | **Auto: service of demand notice + 15 days; uneditable.** Service = date of delivery, or date of return when undelivered |
| JUR-10 | Date of complaint filing | Date picker | — | **Auto: current date; uneditable** |
| JUR-11 | Duration of delay | Number | — | Visible if filed **after 1 month from the date of cause of action**; auto; uneditable. Multiple notices: earliest cause-of-action date `[DERIVED]` |
| JUR-12 | Reason for praying condonation of delay | Textarea | — | Visible if delay exists |

Delay basis **[OWNER]**: one **calendar month** from the **date of cause of action**
(xlsx; the workflow PDF's "from service" wording is superseded). When the DCA attaches
it carries the INR 20 fee (§19) and the `REF-04` refiling rule.

**[OWNER]** The bank-details block (JUR-2…5 / JUR-6a) **repeats per cheque as needed**
when cheques were deposited in different accounts or branches. Whether a cheque was
deposited decides *which* branch grounds jurisdiction (that is JUR-1's job): deposited →
the payee's branch; not deposited → the drawer's.

---

# 12. ADR, Prayer, Other Details — `PRY`

| ID | Field | Type | Validation |
| --- | --- | --- | --- |
| PRY-5 | Would you like to settle the case outside the court through alternative methods of dispute resolution? | Radio Yes/No | — |
| PRY-1 | Additional details (Other Details) | Text | Optional |
| PRY-2 | Interim Relief | Rich text, pre-populated (§17 template 4), editable | — |
| PRY-3 | Final Relief | Rich text, pre-populated (§17 template 5), editable | — |
| PRY-4 | Affidavit | Rich text, pre-populated (§17 template 1), editable — **[OWNER]** rendered as its **own screen** (§5) | — |

---

# 13. Witness Details — `WIT`

Repeats per witness. Witnesses are optional; for an added witness, name-or-designation
and address are required.

| ID | Field | Type | Validation |
| --- | --- | --- | --- |
| WIT-1 | Full Name | Text | Optional if Designation entered |
| WIT-2 | Age | Number | Integer ≥ 1; optional |
| WIT-3 | What will the witness prove | Text | Optional |
| WIT-4 | Designation | Text | Optional if Name entered *(sheet wording corrected)* |
| WIT-5 | Mobile Number | Phone | Valid; optional |
| WIT-6 | Email ID | Email | Valid; optional |
| WIT-7 | Address | Address composite (§5) — **mandatory; repeatable (multiple addresses, same as accused)** | — |

---

# 14. Documents — `DCM`

| ID | Document | Mandatory | Instances / visibility |
| --- | --- | --- | --- |
| DCM-1 | Cheque | Yes | = number of cheques |
| DCM-2 | Cheque return memo | Yes | **[OWNER]** = number of **cheques** (sheet's "demand notices" was an error) |
| DCM-3 | Legal Demand Notice | Yes | = number of demand notices |
| DCM-4 | Proof of dispatch of demand notice | Yes | = number of demand notices |
| DCM-5 | Proof of delivery of demand notice (AD Card or Tracking Report) | No | = number of demand notices; tooltip: includes documents showing delivery was attempted but unsuccessful |
| DCM-6 | Reply to the demand notice | No | = number of demand notices; visible when a reply was received |
| DCM-7 | Proof of debt / liability | Yes | Always |
| DCM-8 | Proof of reasons for delay | No | Visible when there is delay |
| DCM-9 | ID Card — Complainant | Yes | = number of complainants |
| DCM-10 | ID Card — PoA holder | Yes | = number of PoAs |
| DCM-11 | Power of Attorney Authorisation | Yes | = number of PoAs |
| DCM-12 | Vakalatnama | No | Present if ≥ 1 advocate on the case |
| DCM-13 | Other documents | No | As many as the user adds |

"Natively digital" is a per-document attribute (a column in the complaint PDF's
evidence list), not a separate document. **[OWNER]** DCM-9/DCM-10 are named **"ID
Card"**, not "Aadhaar Card", wherever they are displayed or printed. **Aadhaar
handling** **[OWNER]** — **no masking at launch**: the ID card is stored and appended
exactly as uploaded (§16.7), because the court has to be able to check it. No field
collects an Aadhaar number, and nothing else may be built on the number (no extraction,
no search, no display outside the document). Storage design still uncovered `[GAP]`.

**ID Card visibility** **[OWNER]** — the ID card (`DCM-9`, `DCM-10`) is visible only to
the court (today's in-product court roles, §3: Scrutiny Officer, Magistrate), never to
the accused side. `[GAP]` how this is enforced is undecided: whether the accused-facing
copy of the complaint PDF omits the appended ID card pages while the court's copy keeps
them, or access is controlled at the file level regardless of which PDF it's bundled
into. This is one narrow carve-out inside the still-open "accused-side experience after
registration" question (§21) — it decides the ID card only, not the rest of what the
accused side can see.

`[PROTO]` Patterns worth keeping: the checklist is derived from the case data on every
commit; Documents-screen uploads write through to the same stored file as intake; this
is the flow's only hard block before preview — Continue refuses while a required
document is missing, with a visible count.

---

# 14a. Oath — `OTH`

**[OWNER]** Its own screen, mandatory: a video of each complainant reciting the oath.
A separate act from the affidavit (§14b) — see the P&H case files: an oath is
administered at witness deposition ("on S.A."), an affidavit is a document tendered as
evidence; different moments, different records. It sits after Documents, sharing the
"Affidavit" sidebar heading with §14b, listed first. Repeats per complainant record (same
complainants as §6, same order); for an Institution complainant the authorised
representative takes the oath in their place. `FIL-03` — like every other mandatory
section, this blocks Preview / the complaint PDF until every complainant record has one
(§5 Gating).

The screen shows the oath wording below the complainant's own card, for them to read
aloud on camera, so nothing has to be remembered before recording — repeated once per
complainant record so each one is prompted in turn, not shown a single shared block.

> I solemnly affirm that the contents of this complaint, and everything I have stated
> in support of it, are true to the best of my knowledge and belief, and that I have
> not concealed anything material to this case.

**[GAP]** this wording is a placeholder — a religion-neutral affirmation in the shape of
the Oaths Act, 1969 forms, not a verified, court-prescribed script. Confirm the exact
required wording (and whether an oath/affirmation choice is needed, per that Act) before
this ships.

**[OWNER]** Two ways to provide the video, offered side by side, not one replacing the
other: record it directly through the browser's own camera, or upload a video file
recorded elsewhere. Both produce the same stored record and the same validation
downstream — nothing else on this screen, or later in the flow, needs to know which one
the complainant used.

| ID | Field | Type | Validation |
| --- | --- | --- | --- |
| OTH-1 | Oath video | File upload, video (`.mp4`, `.mov`, `.webm`) | **Mandatory.** Duration ≤ 2 minutes, checked from the file's own metadata; if duration cannot be read, fall back to a 200 MB file-size cap |

Not part of the `DCM` document list and not appended to the complaint PDF (§16.7) — a
video cannot be embedded in a printed document. It is stored with the case file like any
other upload and appears in the scrutiny officer's document index (`SCR-01`) and the
case's Documents view, the same as every other section's uploads.

---

# 14b. Affidavit — `PRY-4`

**[OWNER]** Its own screen — a separate act from the oath (§14a): the affidavit is the
sworn written document tendered with the complaint (compare the P&H case files, where
"CW tendered into preliminary evidence his affidavit Ex.CA" is its own order-sheet entry,
distinct from any deposition). It sits directly after Oath, sharing the "Affidavit"
sidebar heading with it, listed second. `FIL-03` — like every other mandatory section,
this blocks Preview / the complaint PDF until it's complete (§5 Gating).

The field itself — pre-populated rich text, §17 template 1, editable — is owned by
`PRY-4` (§12); this section only records the screen-level facts: its title and copy, its
gating, and its position in the form order. The party-in-person affidavit is a different
thing, a field on the Litigant screen (`LIT-27`), not this screen.

Prints per §16.4; template text at §17.

---

# 15. Synopsis — `SYN`

Auto-generated; shown after the case moves to signing; cover page of the complaint PDF.

| ID | Section | Field | Logic |
| --- | --- | --- | --- |
| SYN-1/2 | Parties | Complainant Name · Accused Name | repeat per party |
| SYN-3 | — | Complainant's Advocate Name | all advocate names |
| SYN-4…9 | Cheque Details | Date on cheque · Amount · Cheque number · Bank Name · Bank Branch · Bank Account Number (`CHQ-7a`) | repeat per cheque |
| SYN-10…12 | Dishonour | Date of presentation · Date on return memo · Return reason | **[OWNER]** repeat per cheque |
| SYN-13 | Dishonour | Bank Branch (Complainant) | **[OWNER]** repeat per cheque as needed; exists only when that cheque was deposited |
| SYN-14…21 | Demand Notice | Dispatch date · Mode of service · Tracking number · Delivered? · Delivery date (Y) · Accused replied? (delivered) · Return date (N) · Non-delivery reason (N) | repeat per demand notice |
| SYN-22…25 | Cause of Action | Cause-of-action date · Jurisdiction under s.142(2) (deposited → complainant's branch, else accused's; bracket whose) · Other complaint pending? · Court and Case Number (if Yes, per case) | — |
| SYN-26 | — | Prayer / Relief sought | **[OWNER]** prints the **Final Relief** field (`PRY-3`) |

Every synopsis field now has a collecting field (SYN-9 ← `CHQ-7a`) and explicit
multi-count logic. PoA holders and persons-responsible do not appear in the parties
list; persons-responsible surface as separate accused (§8), so they appear via SYN-2.

---

# 16. Generated complaint PDF — `DOC`

This section is the whole specification for the generated complaint PDF: print order,
layout, value formatting, cover, signatures, and where the printed document departs from
the screens. It **owns none of the fields** — every field, its label, its type, its
validation and its visibility are in §6–§15 above, read from `E-Filing Fields.xlsx`.
Do not restate a field list here: add the field in its own section and it appears in the
PDF by `DOC-01`.

Two numbering schemes meet in this section, so they are kept apart throughout:
**§16.x** is a part of this specification; **print §2.4** is a numbered section of the
printed document itself, as it appears on the page.

**[OWNER]** decisions on the document as a whole:

- It is **always current**: whenever it is viewed it reflects the case data at that
  moment (regenerate on view / on data change — backend team's design).
- **Preview is reachable only after all mandatory fields are filled and validations
  pass** (§5).
- **No retention of superseded versions.**

A filled sample PDF exists — see §16.9. It illustrates one case and is not normative.

## 16.1 The generative rule — `DOC-01`

**[OWNER]** The complaint PDF is **generated from the case's own field set, not a
hardcoded template**. It is the case data, printed in a fixed section order, under a
fixed layout rule:

1. **Sections print in the order in §16.4.** That order is fixed and does not vary with
   the data.
2. **Within a section, every field assigned to it in §16.4 prints**, in the order those
   fields appear in this document's field tables. **[OWNER]** §16.4 follows the form's
   own screen order: one screen is one printed section (Case details print §2.1–2.4
   correspond one-to-one with the Cheque & Return Memo, Legal Demand Notice,
   Jurisdiction & Limitation, and ADR/Prayer/Other Details screens), and within a
   section fields print in the order the screen collects them. There are exactly two
   named exceptions, plus one structural one that isn't a reordering at all — the full
   list is §16.8.
3. **A field that does not apply to this case does not print at all** — no label, no
   blank space. "Does not apply" means the form's own visibility logic hid it: the wrong
   branch (Individual vs Institution), a conditional that is false (`Date of delivery`
   when the notice was not delivered), a repeat group with no records.
4. **A field that applied but was left empty prints its label with `-`** as the value, so
   the reader can see the question was asked and not answered. **[OWNER]** This is
   **every** optional field the form showed and the filer left blank — age, email,
   police station, tracking number, designation, additional details, all of them — not
   only the ones where the blank is legally material. Expect a case with few optional
   answers to print a good many dashes; that is accepted. Contrast rule 3: a field the
   form never showed prints nothing at all, not a dash.
5. **A repeat group prints once per record**, each labelled with its own number
   (`Cheque 1`, `Cheque 2`; `Accused 1`, `Accused 2`).
6. **A field added to the e-filing flow prints automatically**, in its section, at its
   position in the field order. Adding a field requires no change to this section. A
   field removed from the flow stops printing.

**There is no exception list, and none is to be added.** **[OWNER]** Rule 2 is literal:
a field that only steers the form still prints, as a row like any other — `LIT-1`
party-in-person, `LIT-8` and `LIT-15` whether the current address is the same as the
permanent one, `LIT-10` whether a Power of Attorney was given, `CHQ-4` whether the bank
details match the previous cheque, `ADV-1` the number of advocates. The same goes for the
optional personal fields — `LIT-5a`/`LIT-24a` gender, `LIT-5b`/`LIT-24b` differently
abled?, `ACC-24` resides within jurisdiction: they print too. There is no category of
field that is collected and then held back. **Do not suppress any of them** on the view
that they read as noise, or that they are personal; that is a decision already taken.

This also settles what happens when a second address is the same as the first: the
question prints with `Yes`, and the current-address field, which the form then hides,
prints nothing (rule 3). A reader can see why there is no second address — the question
above it says so.

Consequence to build for: the generator must walk the case's own field set, not a
hardcoded template. Two cases will have different rows, different row counts and
different page breaks. Nothing may assume a fixed row.

**Printed labels** are the field's own label from the field tables in §6–§15 — the PDF
never invents wording. This is what makes terminology decisions carry through: it is
**Institution**, never "Entity" (§5, `ACC-5`, `LIT-18`), and the identity document is an
**ID Card**, never "Aadhaar Card" (§14, `DCM-9`, `DCM-10`).

## 16.2 Layout — `DOC-04`

One page size, one type scale, no table borders anywhere. Three layout modes, chosen per
field by the rules below — not by hand, per field, in a template.

**Field flow — the default.** Fields flow **left to right across three equal columns,
then wrap** to the next row. Label above value: label in the smaller regular face, value
beneath it in the body face.

```
Type                     Full Name                Age
Individual               [name]                   [age]

Mobile Number            Email Address            Address
[phone]                  -                        [address line 1, city,
                                                  pincode]
                                                  Police Station
                                                  [police station]
```

- A value that wraps makes its row taller; the next row starts below the tallest cell.
- **An address prints as one field.** Its Police Station (a separate field, per address —
  §5) prints immediately beneath it in the same cell, not as a new column.
- A repeatable address prints as `Address 1`, `Address 2`, each with its own Police
  Station beneath it.

**Full width.** A field takes the **whole width**, label above value, when its label or
its value will not read in a third of the width: long-text fields (`Interim Relief`,
`Final Relief`, `Affidavit`, `Additional details`, `Reason for praying condonation of
delay`, `What will this witness prove?`) and long questions (the ADR question, the
other-pending-complaint question). A full-width field ends the current row of three and
starts a new one after it. Rich-text fields print **as the user left them** — their own
paragraphs, lists and lettered clauses preserved, no reformatting, no re-wrapping into
the grid.

**Columnar list.** Where a repeat group holds several records of the same two or three
short fields, the labels print **once as a header line** and each record prints as one
line beneath:

```
Court Name               Case Number
[court]                  [number]
[court]                  [number]
```

Unlike the field flow, the columns are **shared across rows**: every row uses the same
column positions, so a long value wraps inside its column rather than moving the layout.
A header line must never be the last line on a page — keep it with at least one of its
rows.

Used for, and only for: other cheque-dishonour complaints pending (Court Name · Case
Number) · the document list (print §3.2) · the advocate cards, where the advocates' names
stack in one column and their bar registration numbers in the next, row for row, so the
third line of one column is the same advocate as the third line of the other. Order is
load-bearing there: if the columns fall out of step the document attributes a bar number
to the wrong advocate.

**Headings and blocks.**

- Numbered section headings print as in §16.4 (`1.`, `1.1.`, `2.3.`), the number in a
  larger face than the words.
- Inside a section, a **block heading** in bold names the record or the group
  (`Complainant 1`, `POA for Complainant 1`, `Cheque 1`, `Payee (Complainant) Bank
  Details`, `Persons Vicariously liable for the Institution`).
- An empty section — every field inapplicable and no records — **does not print**, not
  even its heading. The numbering does **not** close the gap: print §3.1 is print §3.1
  whether or not print §2.4 printed.

## 16.3 Printing values — `DOC-05`

| Kind | Prints as |
| --- | --- |
| Date | `15 January 2025` — always day, month name, four-digit year. Never a bare `15 March` |
| Amount | `₹4,50,000` — Indian grouping, rupee symbol, no decimals when whole |
| Yes/No | `Yes` / `No` |
| Dropdown | the value's display label, in the case's language |
| Empty but applicable | `-` (`DOC-01` rule 4) |
| Multi-value field | each value on its own line in the same cell, in entry order |

**Never printed:** the missing-contacts declaration, which is recorded as backend data
only (§8). That is the only one. Every other field the form showed prints, per `DOC-01`.

**ID card handling** — no masking, appended exactly as uploaded, visible to the court
only and not to the accused side: see §14 for the full statement.

## 16.4 The document, in print order — `DOC-06`

| Print order | Printed heading | Fields | Repeats | Print notes |
| --- | --- | --- | --- | --- |
| — | *cover* | §16.5 | once | Centred, stacked, first page |
| — | **Synopsis** | §15, `SYN-1…26` | per its own logic | A curated subset, not "all fields" — the only section whose contents are listed field by field elsewhere. Blocks: Parties · Cheque details · Dishonour · Demand Notice · Cause of Action · Prayer/ Relief sought. A block that repeats carries the record in its heading (`Cheque details - Cheque 2`, `Dishonour - Cheque 2`, `Demand Notice 1`), or a reader cannot tell which dishonour belongs to which cheque. The prayer row prints the **Final Relief** field (`PRY-3`) in full, as the user left it: there is no summary field, no summarisation rule, and none is to be written — do not condense it |
| 1. | **Party details** | | | |
| 1.1. | Complainant | §6, `LIT-*` | per complainant | Individual and Institution branches print their own fields. A PoA holder prints as a block beneath its complainant (`POA for Complainant N`); an institution's authorised representative likewise (`Authorized Representative for Complainant N`). The party-in-person affidavit (`LIT-27`) prints here, at its position in the field order |
| 1.2. | Advocate (Complainant) | §7, `ADV-2…4` | per advocate card | Advocates representing the same complainants share one card. `ADV-2` "Advocate for" is **the card's heading**, not a row in it — `Advocate for Complainant 1, Complainant 2`. The card then prints `Full Name` (`ADV-4`) and `Bar Registration` (`ADV-3`) in that order — **the reverse of the field order**, the one place this table overrides `DOC-01` rule 2 within a section — with the names stacked in one column and the numbers in the next, row for row. Section omitted when every complainant is party-in-person |
| 1.3. | Accused | §8, `ACC-*` | per accused | Individual and Institution branches. Police Station (`ACC-13`) is per address and prints beneath its address. An institution's persons responsible (`ACC-14…23`) print under the heading `Persons Vicariously liable for the Institution`, one block per person (`Person 1`, `Person 2`) carrying **all** their fields — name, designation, mobile, email, address and police station — because rule 2 is literal. Each of them is **also** a separate accused in the flow (§8), so the same details print again in their own `Accused N` block. Both are true of them, and both print |
| 2. | **Case details** | | | |
| 2.1. | Cheque and return memo details | §9, `CHQ-1…10` | per cheque | One screen, one section: cheque fields (`CHQ-1…7a`) then that cheque's return memo fields (`CHQ-8…10`), in the screen's own field order. Heading carries the cheque's number |
| 2.2. | Demand notice details | §10, `LDN-1…11` | per demand notice | One screen, one section: `LDN-1` Nature of debt prints first, exactly where the screen collects it, followed by `LDN-2…11`. Delivered / not-delivered conditionals per `DOC-01` rule 3 |
| 2.3. | Jurisdiction and limitation | §11, `JUR-1…12` | bank block repeats per cheque as needed | One screen, one section, in the screen's own field order. The bank block prints `Payee (Complainant) Bank Details` when deposited, the drawer's-branch police station (`JUR-6a`) when not. A repeated block is headed with the cheque numbers it covers. Other pending complaints (`JUR-6b…8`) print as a columnar list, then the limitation fields (`JUR-9…12`); delay rows print only when the delay exists |
| 2.4. | ADR, prayer and other details | §12, `PRY-1…3`, `PRY-5` | once | One screen, one section, in the screen's own field order: `PRY-5` ADR, `PRY-1` Other details, then `PRY-2`/`PRY-3` Interim Relief and Final Relief, each full width, as the user left them |
| 3. | **Evidence** | | | |
| 3.1. | List of witnesses | §13, `WIT-*` | per witness | Whole section omitted when there are no witnesses |
| 3.2. | List of documents | §14, `DCM-*` | one line per uploaded document | Columnar: `S. No.` · `Document Name` · `Natively Digital`. **Generated, never a static list**: one line per document actually uploaded, in Documents-screen order; a repeated document carries its record's number (`Cheque 2`, `ID Card — Complainant 2`); an optional document not uploaded does not appear. `Natively Digital` is the per-document attribute, not a separate document |
| 4. | **Affidavit** | §12, `PRY-4` | once | Full width, as the user left it. Signature block follows (§16.6) |
| — | *appended documents* | §16.7 | | |

Print §4 is the last printed section of the complaint itself; the uploaded documents
follow it.

## 16.5 Cover page — `DOC-03`

**[OWNER]** Centred and stacked, in this order, on the first page above the Synopsis:

| Line | Value |
| --- | --- |
| Court name | The court the case is filed in, from the deployment's own court/jurisdiction configuration. **Never hardcoded** — no court name belongs in the generator |
| Case title | `[first complainant's full name] v/s [first accused's full name]` — **full names**, not first names. **[OWNER]** `+N others` after either side when there is more than one party on it, `N` being the count of parties on that side beyond the first named one (two complainants → `+1 other`; four accused → `+3 others`) — corrects the earlier `& Ors.` wording, which is not what prints |
| Case number | Whatever number the case has at the moment of printing: the system-generated **filing number** from draft creation onward, replaced by the case number assigned at registration (§20.1). Formats and generators per state are in the separate case-numbers document. A draft always has a filing number, so this line is never empty and needs no placeholder |
| Title of proceeding | **[OWNER]** `Complaint under [the case type's long title]` — the case type is a variable, not a hardcoded string, so the platform can carry more case types than §138 later. Each case type carries two titles: a **short title** for screens (`Complaint under S-138, NI Act`) and a **long title**, the full statutory form, for PDFs (`Complaint under Section 138 of the Negotiable Instruments Act, 1881`) — this line always prints the long title |

## 16.6 Signature block — `DOC-02`

**[OWNER]** Printed after the affidavit text, as **placeholders positioned from the
case** — the number of lines and their labels follow the case's signatories, and are not
fixed.

- One signature line **per required signatory**: for each complainant, whichever of the
  complainant, their PoA holder, or the institution's authorised representative is the
  signatory for that complainant; plus each signing advocate, at least one per
  represented complainant.
- Each line prints the rule, then the **signatory's name**, then their role and which
  complainant they sign for — `PoA holder for Complainant 2`, `Advocate for
  Complainant 1`.
- Lines lay out two to a row, left and right, and wrap to further rows as the count
  requires.
- A clerk is never a signatory (`ROLE-08`).
- Signing itself, and what invalidates signatures, is §18 (`SIG-*`) and `LIFE-13` — the
  PDF only has to leave the right number of correctly labelled places.

## 16.7 Appended documents — `DOC-07`

After the complaint, the page **`Documents uploaded by the Complainant.`**, then every
uploaded document appended in the print §3.2 order. A document appended here is the file
as uploaded; the PDF does not stamp, annotate or re-render it. Exception: the ID card
(`DCM-9`, `DCM-10`) — see §14 for its court-only visibility, still open how that's
reconciled with a single generated PDF.

## 16.8 Where the printed document differs from the flow

The PDF is not a print-out of the screens. A developer who assumes screen order and print
order are the same will get it wrong in the places below, and nowhere else.

**[OWNER]** As of this revision, every Case details screen prints as exactly **one**
section, in the screen's own field order (§9→2.1, §10→2.2, §11→2.3, §12→2.4). There is
no longer a case of one screen splitting across several print sections, or of a screen's
own field order being disturbed, anywhere in Case details. Two structural exceptions
remain, plus the Party details exception below — none of them a field reordering:

| Form screen | Print sections |
| --- | --- |
| §14 Documents | **print §3.2** the list, **and** the appended files after print §4 — one screen feeds two places in the document. This one can't be merged: the files are physical attachments that must sit at the end, not inline in the body |
| §15 Synopsis (auto-generated) | the **first page**, before print §1, drawing fields from most of the other screens. Synopsis isn't collected on any screen at all — it exists only as a generated summary — so "collection order" doesn't apply to it; it stays first by deliberate choice, as the reader's entry point |
| §6 Litigant | **print §1.1**, including the party-in-person affidavit (`LIT-27`). The case's main affidavit (`PRY-4`) is its own screen (§5, screen 9) and prints as **print §4** — so the document carries two affidavits, sections apart. These are two different fields, not one field split in two, so there is nothing to merge here |

**[OWNER]** Also unchanged: Oath (§5, screen 10) is a recorded video, not a document
field, and does not appear anywhere in the printed complaint.

**Fields that do not print as their own row.**

| Field | How it prints |
| --- | --- |
| `ACC-13` Police Station | Inside its address's cell, beneath the address — not as a separate cell (§16.2) |
| `JUR-2…5` payee bank details | Collected per cheque as needed, printed **once** with the cheque numbers in the block heading when several cheques share an account |
| `ADV-2` Advocate for | Becomes the **card's heading** (`Advocate for Complainant 1, Complainant 2`), not a row |
| `ADV-4` / `ADV-3` | The card prints `Full Name` before `Bar Registration` — **the reverse of the field order**, and the only place §16.4 overrides `DOC-01` rule 2 inside a section |
| `ACC-14…23` persons responsible | One block per person under a group heading, with every field — not a two-column name-and-designation list. The same person's contact details print a second time in their own `Accused N` block, which follows from each person responsible also being a separate accused (§8), not from anything in §16 |
| `LIT-9` / `LIT-16` current address | When the answer above is `Yes` the form hides it, so nothing prints. The question printing `Yes` is what tells the reader why |

**Printed, but not a form field at all.** The generator sources these from somewhere
other than the field tables, and a developer looking for them in `E-Filing Fields.xlsx`
will not find them:

| Printed | Source |
| --- | --- |
| Court name | deployment court/jurisdiction configuration (§16.5) |
| Case title | composed from the party names, with `+N others` (§16.5) |
| Case number | filing number, later the registration number (§16.5, §20.1) |
| `Complaint under Section 138 of the Negotiable Instruments Act, 1881` | the case type's long title (§16.5) — not a fixed string; varies with the case type once more than §138 is live |
| Synopsis jurisdiction line — "[branch] - complainant's bank branch" | composed: the branch, plus whose branch it is, derived from `JUR-1` |
| `Duration of delay` | computed from the cause-of-action and filing dates (`JUR-11`) |
| Repeat numbering — `Cheque 2`, `Accused 1`, `Address 2`, `S. No.` | the generator's own counters |
| `Natively Digital` | a per-document attribute captured at upload (§14), not a document and not a field |
| Signature names and roles | derived from the parties, their PoA holders and representatives, and their advocates (§16.6) |
| `Documents uploaded by the Complainant.` | fixed string on its own page (§16.7) |

**Collected, never printed.** Only the missing-contacts declaration, which is recorded as
backend data and never reaches the case file (§8).

## 16.9 The filled sample

[complaint-pdf-worked-example.pdf](https://codahosted.io/docs/KtL_rwN6Qw/blobs/bl-jLA4zutOUt/c183c9e3f40deaf3d41b9e55b3ce93d34e3845fdba82f0cf5062b290608a3b652b495a91ae9654e1736c3468b7fe50e527e81941ad245619424a5ad80c8bd6544e403da2b84c7efb6b7d82d90184dcf3be3bf981275ee7c03d1697b9fd18d37806806397)
— **[STALE]** this link is the pre-merge, nine-page version. **[OWNER]** regenerated
2026-09-28 against the merged §16.4 print order (v23/v24); the current file is
`efiling-reference/complaint-pdf-worked-example.pdf` in the repo — re-upload it here and
replace this link once done.

A filled sample PDF accompanies this handover: **the complaint as it actually comes
out** — eight pages, real typography, the three-column grid, the page breaks where they
fall. It was produced by applying §16.1–§16.8 to one invented case, so it shows the rules
rather than restating them.

**It is not the specification.** It is derived from §16.1–§16.8, not the other way round.
If it disagrees with them, they win and the sample is the thing to regenerate. It renders
one case, so **absence from it means nothing** — a field's behaviour comes from its row
in §6–§15, not from whether it appears in the sample.

**The data is invented.** Every name, address, phone number, amount, cheque number, IFSC
code and date in it is made up, and the case does not exist. It is not a filing, not a
template to file from, and nothing in it should be copied into a real document.

**The case it renders**, chosen to exercise the awkward parts:

| | |
| --- | --- |
| Complainants | two — an individual who has given a Power of Attorney, and a private limited company with an authorised representative |
| Advocates | three, all on one card, acting for both complainants |
| Accused | two — an individual with two addresses (one without a police station), and a partnership firm with two persons vicariously liable, who print both under the firm and again as accused in their own right |
| Cheques | two, drawn the same day on the same account, the second answering `Yes` to "bank details same as previous cheque?" |
| Demand notice | returned undelivered, and part payment made against the cheques |
| Other proceedings | one pending between the same parties |
| Limitation | filed 13 days beyond one calendar month, so delay condonation applies |
| Witness | known by designation, not by name — so `Full Name` prints `-` |
| Optional fields | several left blank, printing `-` per `DOC-01` rule 4 |

**What to look at in it:**

- **Page 1** — the case title reads `Anilkumar Sasidharan +1 other v/s Devadas Nair +3
  others`, and the cover's title of proceeding is the case type's long title (§16.5). The
  prayer row prints the whole Final Relief field, which is what §16.4 requires and is
  longer than a synopsis line would be.
- **Pages 2–4** — `Is current address same as permanent? / Yes` with no current address
  printed after it (`DOC-01` rules 2 and 3 together); `Number of advocates / 3` printing
  as an ordinary row; the authorised representative's long labels wrapping inside their
  column; police stations sitting under their addresses; Accused 3 and 4 repeating the
  two persons vicariously liable in their own right (§16.8).
- **Page 4** — `Bank details same as previous cheque? / Yes` on cheque 2, printed inside
  the merged §2.1 Cheque and return memo details block rather than a separate cheque
  section (`DOC-01` rule 2, as merged).
- **Page 5** — Nature of debt printing *first* in §2.2 Demand notice details, exactly
  where it's collected, not last; the not-delivered branch of the demand notice; the
  part-payment rows; §2.3 Jurisdiction and limitation as one merged section, headed with
  both cheque numbers, running straight into the delay rows.
- **Pages 6–7** — §2.4 ADR, prayer and other details as one merged section; four
  signature lines, because Complainant 1 signs through a PoA holder, Complainant 2
  through its authorised representative, and each needs an advocate.

If a rule in §16.1–§16.8 changes, the sample is the thing to regenerate — it is an
illustration, not a build artefact, and §16.1–§16.8 are complete enough to rebuild it
from, which is the point of them.

---

# 17. Prefilled text templates (verbatim, `Templates (1).pdf`)

**[OWNER]** All prefilled rich-text fields are **editable; the blanks (`___`) are for
the user to fill.**

**1. Affidavit** (→ `PRY-4`, the Affidavit screen):

> I am the complainant / authorised representative of the complainant in the above case
> and am fully acquainted with the facts and circumstances of the case. I am competent
> and authorised to swear to this affidavit. The accused issued the above cheque in
> discharge of a legally enforceable debt or liability. It has been dishonoured due to
> insufficiency of funds. A demand notice has been issued to the accused, but she/he has
> failed to make the payment due under the cheque. All other requirements under Section
> 138 of the Negotiable Instruments Act, 1881 have been complied with.
>
> I confirm that the demand notice was served on the last known correct address of the
> accused(s).
>
> In accordance with Section 225 of the Bharatiya Nagarik Suraksha Sanhita, 2023, I
> confirm that there is sufficient ground for proceeding against the accused.
>
> In accordance with Section 223 and other relevant provisions of the Bharatiya Nagarik
> Suraksha Sanhita, 2023, I confirm that the contents of this complaint are true and
> correct to the best of my knowledge, belief and information.
>
> The physical or electronic records of the documents etc. produced by me with this
> complaint are in my lawful and proper custody and possession. It is therefore humbly
> prayed that this Hon'ble Court may be pleased to take cognizance of the offence
> committed by the accused, and issue process to the accused.

Note: the text hard-codes "insufficiency of funds" and cites BNSS 2023. **[OWNER]** no
automatic variance — **the user edits the text** where the return reason or the
applicable code differs.

**2. Affidavit for appearing as party in person** (→ `LIT-27`):

> I request permission to appear and argue in person, as a party in person. By
> educational qualifications I am a _______. I have not engaged any advocate for this
> case. I give an undertaking that I will maintain decorum of the Court and will not use
> or express objectionable and unparliamentary language or behavior during the course of
> hearing in the Court premises or in any pleadings. Kindly grant me permission to
> appear in person and conduct the proceedings.

**3. Declaration for unavailability of accused's contact details** (→ §8; recorded as
backend data, not added to the case file **[OWNER]**):

> I confirm that I don't have any knowledge of the electronic contact details of the
> accused. I confirm that I am unable to locate these contact details with reasonable
> effort.

**4. Interim Relief** (→ `PRY-2`):

> It is, therefore, most respectfully prayed that this Hon'ble Court may be pleased to:
> Direct the Accused to pay interim compensation to the Complainant under Section 143A
> of the Negotiable Instruments Act, 1881, during the pendency of the trial, of a sum
> not exceeding 20% of the cheque amount i.e. Rs. ______________, within 60 days of the
> order or such further period not exceeding 30 days as this Hon'ble Court may allow for
> sufficient cause shown.

**5. Final Relief** (→ `PRY-3`):

> It is most respectfully prayed that this Hon'ble Court may be pleased to:
> (a) Take cognizance of the offence committed by the Accused under Section 138 of the
> Negotiable Instruments Act, 1881;
> (b) Issue process/summons against the Accused and direct him/her to appear before this
> Hon'ble Court;
> (c) Upon trial, convict and sentence the Accused under Section 138 of the Negotiable
> Instruments Act, 1881, to imprisonment for a term which may extend to two years, or
> with fine which may extend to twice the amount of the cheque, or with both;
> (d) Direct the Accused to pay compensation to the Complainant under Section 395 of the
> Bharatiya Nagarik Suraksha Sanhita, 2023, equivalent to the cheque amount along with
> interest ______% per annum from the date of dishonour;
> (e) Grant such other and further relief(s) as this Hon'ble Court may deem fit and
> proper in the facts and circumstances of the case.

---

# 18. Signing — `SIG`

- `SIG-01/02` — mode choice: **e-sign** or **upload a signed copy**; more modes later —
  don't hard-code a binary.
- `SIG-03` — required signatories: **every complainant** (or their PoA-holder) **and one
  advocate for each complainant**.
- `SIG-04` **[OWNER]** — all parties use the same mode. **Requirement**, not a
  limitation.
- `SIG-05` — upload mode: the uploader collects all wet signatures beforehand;
  **[OWNER]** additionally, **each required party confirms via a phone OTP** — the
  upload counts as fully signed only when the document is uploaded **and every party
  has confirmed**.
- `SIG-06` — e-sign is individual; the case advances when all have signed. **[OWNER]**
  **no mandated signing order.**
- **[OWNER]** — **parties cannot change mid-signing**: changing them requires going back
  to edit, and **any edit invalidates all signatures** (`LIFE-13`).
- **[OWNER]** — **account creation for new complainants happens at signing** (this is
  how auto-created accounts are retained): in **e-sign** mode each party must log in
  with the phone number entered for them in order to sign — creating their account; in
  **upload** mode the per-party OTP verification creates it.
- `ROLE-08` — clerks cannot e-sign; enforce server-side.

E-sign provider selection, failure modes, retry/timeout: left to engineering at
integration time (with §19's gateway equivalents).

---

# 19. Payment — `PAY`

Global: **Parties in Person are never counted as advocates.**

## 19.1 Case filing fees

| Head | Amount (INR) | Applies when |
| --- | --- | --- |
| Court Fee | 12.5 | ≥ 1 advocate in the case |
| Legal Benefit Fee | 12.5 | ≥ 1 advocate in the case |
| Advocate Welfare Fund | 100 per advocate, computed per complainant, **cap 300 per complainant** **[OWNER]** | ≥ 1 advocate |
| Stipend Stamp | 25 per advocate, computed per complainant, **cap 75 per complainant** **[OWNER]** | ≥ 1 advocate |
| Advocate Clerk Welfare Fund | 20 | ≥ 1 advocate in the case |
| Delay Condonation Application Fee | 20 | DCA attached |
| Complaint Fee | slab: ≤50k → 250 · 50k–2L → 500 · 2L–5L → 750 · 5L–10L → 1,000 · 10L–20L → 2,000 · 20L–50L → 5,000 · >50L → 10,000 | always; **[OWNER]** with multiple cheques the slab is applied to the **sum of all cheque amounts** |

Remittance accounts: Advocate Welfare Fund and Stipend Stamp go to TSB a/c
799010100175123 · head 8031-00-102-94-07-00-00-N-V · type 01 · head ID 56685; the
source leaves the other heads' account mapping blank `[GAP]`.

## 19.2 Join-a-case fees

Court Fee 12.5 + Legal Benefit Fee 12.5 — when a joining advocate is **not part of a
previous vakalatnama**; Advocate Welfare Fund / Stipend Stamp / Clerk Welfare Fund as
in §19.1.

## 19.3 Upfront process payments

Everything in this section is decided **per accused, independently**. What is chosen
for one accused says nothing about the others; a case with three accused makes the
choice three times, and the bill states each one separately.

### 19.3.1 Court fee per process

A small court fee of **INR 12.50** applies to every round of every process.

| Process | Rounds collectable upfront | Default | Charged |
| --- | --- | --- | --- |
| Summons | 1–4 | **1 — mandatory**, cannot be declined | 12.50 × rounds × **selected addresses** |
| Warrants | 0–4 | 1 | 12.50 × rounds |
| Notice | 0–1 | **1 when Delay Condonation applies**, else 0 | 12.50 × rounds |

`PAY-10` One round of summons is mandatory **for each accused**. An accused cannot be
left at zero summons rounds; a case with three accused therefore carries at least three.

`PAY-11` The notice default follows the Delay Condonation section: when the DCA applies
the round is opted in, when it does not it is not. Like `REF-04`, this is evaluated
**against the clock at the time the bill is drawn**, not cached from an earlier draft —
a filing that attracts the DCA during a correction cycle attracts the notice round with
it. The filer may still decline it.

### 19.3.2 Addresses

`PAY-12` The filer selects which of **that accused's** addresses summons is served at;
at least one. The summons court fee and the e-post fee are each charged once per
selected address, per round.

`PAY-13` The payment screen must state the multiplication on every line — rate ×
addresses × rounds — even where a factor is 1, so the filer can see what adding an
address or a round would cost before doing it.

### 19.3.3 E-post

`PAY-14` Delivery is by **e-post**; there is no channel to choose. **INR 100** per
address per round stands in until the real charge is supplied (`Q-1`). It is the post
office's charge, not the court's, and is billed apart from the court fees.

`PAY-15` E-post is opted in and out **separately from the summons court fee**, round by
round: an accused whose summons is prepaid for three rounds may prepay delivery for
one, two or three of them. The exception is the mandatory first round, whose e-post is
collected with it (batch 3). So delivery rounds run **1 … summons rounds prepaid**.

### 19.3.4 What prepayment buys

When the judge later triggers a pre-paid process, one is generated **per selected
address** and **no pending payment task is created**. Anything not prepaid is charged
later, if and when the court orders that process.

## 19.4 Resubmission

`LIFE-12` (§4): recalculate; **increased → extra amount collected; decreased → no
automatic refund**, but the system later **auto-generates a refund note** the filer
uses to claim the refund. Payment-affecting fields `[DERIVED]`: cheque amounts (slab),
advocate count, complainant count (caps), DCA attaching, added addresses (process
fees). Balance collection is already built in the current system — confirm reuse.
Payment failure, timeout, reconciliation: left to engineering at integration time.

---

# 20. Scrutiny, registration, refiling; decisions log

## 20.1 Case routing — courtroom, scrutiny officer, magistrate

A court establishment contains one or more courtrooms. Each courtroom has a magistrate,
a scrutiny officer, a bench clerk, and dedicated support staff (steno / typist / judgment
writer). Bench clerks and support staff are strictly 1:1 per courtroom. A single scrutiny
officer may in practice handle multiple courtrooms (Gujarat today: one officer across 5
courtrooms).

After a case is filed, signed, and paid, it is **automatically assigned to a courtroom**.
Since each courtroom has a designated scrutiny officer, the case becomes visible to that
officer.

**The allocation logic is configurable per court establishment.** The system carries all
possible allocation methods; which one applies is a deployment configuration.

| Method | Where used |
|---|---|
| Single courtroom — no allocation needed | Kerala, Punjab (Panchkula) |
| Institution-to-courtroom mapping + default fallback | Gujarat (Phase 1) |

Gujarat Phase 1: financial institutions are mapped to specific courtrooms (e.g. HDFC →
Courtroom A). Filers who don't match any mapping go to a default fallback courtroom. The
filer does not select a courtroom. The CJM retains authority to transfer cases between
magistrates to balance workload.

## 20.2 Scrutiny workflow

A case enters Scrutiny after signing and payment complete (§4: Pending Payment → pay →
Scrutiny). The courtroom's scrutiny officer reviews the submitted case for defects
before forwarding to the magistrate.

### How a case reaches the list — pending tasks

`SCR-09` There is **no separate scrutiny queue or registration queue**. Both lists are
the application-wide **pending tasks** mechanism, filtered to the logged-in user. A case
is in a scrutiny officer's or a magistrate's list exactly as long as its pending task is
open. The court-side tasks, as a live view of the master Pending Tasks list:

```superhuman-view
name: Pending tasks (Court Side) — E-Filing
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("efiling-scrutiny-registration-handover")
```

Both are assigned to the courtroom's scrutiny officer and magistrate respectively
(§20.1), due **+0 days**, visible to **Only Users** (the assignee). Neither carries a
Category — the Category values are citizen-side only. Task attributes and the status
lifecycle are in `pending-tasks-handover.md`.

`SCR-10` Creating and closing these tasks is a **side effect of the §4 lifecycle
transitions**, not a separate step, and it is the only mechanism for list membership —
do not build a second stage-query alongside it. The filer side works the same way:

```superhuman-view
name: Pending tasks (Citizen-Side) — E-Filing
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("efiling-scrutiny-registration-handover")
```

Both tables are the single source of truth and the place to edit these tasks. A
downloaded copy of this document is a snapshot.

**PRD language.** The functional spec says a case "appears in the list" for scrutiny and
for registration without saying how the system knows. That wording should be updated to
name the pending-task mechanism; the requirement is as stated here.

### Scrutiny interface (initial version)

`SCR-01` Three-panel layout:
- **Left**: case fields, grouped by section
- **Centre**: the selected document
- **Right**: document index (all uploaded documents)

`SCR-02` The scrutiny officer can **mark any individual field as an error** and type a
comment against it. They can also **mark an entire section** as an error with a comment.

`SCR-03` The scrutiny officer can **flag any document as an error**, which permits the
filer to re-upload it on send-back.

### Interlinked date auto-marking

`SCR-04` When the scrutiny officer marks any interlinked date field (any node in the
date chain, `VAL-01/02`), **all transitive downstream dates** in the chain are
**auto-marked** as well — the filer can then edit them without failing the ordering
validations. This implements `REF-03` at the scrutiny stage: the officer selects one
date, and the system marks the rest.

### Delay condonation alert

`SCR-05` If delay has become applicable since the case was filed — evaluated against the
clock at the time of scrutiny, the same rule as `REF-04` — the scrutiny interface must
**flag this to the scrutiny officer**. The Delay Condonation section may now be required
where it was not at filing.

### Actions

`SCR-06` Two actions. The second one depends on the `registrationPoint` config
(`SCR-11`, §20.3a):
- **Send back** — only the fields, sections, and documents marked as errors are flagged
  to the filer (`REF-01`). Send-backs repeat without limit (`LIFE-11`).
- **`registrationPoint: magistrate` (default) — Forward to magistrate** — moves the case
  to Registration (§20.3).
- **`registrationPoint: scrutiny` — Register** — assigns the case number itself and
  moves the case directly to Cognisance, skipping Registration entirely (`SCR-12`).

## 20.3 Registration

Applies only under `registrationPoint: magistrate` (the default). Under
`registrationPoint: scrutiny`, this stage and the *Register case* task below never
occur — the scrutiny officer registers directly (`SCR-06`); see §20.3a.

`SCR-07` Forwarding closes the *Scrutinise case* task and creates a ***Register case***
pending task for the courtroom's magistrate (§20.1) — that task is the magistrate's
list of cases to register (`SCR-09`).

`SCR-08` Two actions:
- **Register** — assigns a case number and moves the case to Cognisance.
  Case number format and generation are covered in a separate document.
- **Send back** — the magistrate types **one single overall comment** (no individual
  field marking, consistent with `REF-02`). This opens **everything** for editing.

**[OWNER]** There is **no outright rejection at this stage** — registration happens
first; dismissal is possible only after registration (out of this module's scope).

## 20.3a Registration point — config

`SCR-11` **`registrationPoint`**, set per court establishment alongside `allocationLogic`
(§20.1):
- **`magistrate`** (default — today's behaviour) — scrutiny's second action is Forward;
  the magistrate then Registers or Sends back (§20.3).
- **`scrutiny`** — scrutiny's second action is Register, done directly by the scrutiny
  officer. The Registration stage and the magistrate's *Register case* task (`SCR-07`)
  do not occur for that case. There is no separate magistrate send-back under this
  setting — only the scrutiny officer's Send back (`SCR-06`) is available before
  Cognisance.

`SCR-12` Under `registrationPoint: scrutiny`, the scrutiny officer's Register action does
exactly what the magistrate's Register does under the default (`SCR-08`): assigns the
case number and moves the case to Cognisance. Everything from Cognisance onward is
identical regardless of config — this module's scope already ends there.

## 20.4 Editability on send-back

**Date chain** (`VAL-01/02`) — implement as an explicit dependency graph (`REF-03`
walks it):

```
CHQ-1 date on cheque
  └─ CHQ-8 presentation (≥)
       └─ CHQ-9 return (≥)
            └─ LDN-2 dispatch (≥ return of at least one cheque)
                 ├─ LDN-6 delivery (≥)   [delivered = Yes]
                 └─ LDN-7 return (≥)     [delivered = No]
                      └─ JUR-9 cause of action = service + 15 days (auto)
                           └─ JUR-10 filing date (auto, today)
                                └─ JUR-11 delay = beyond 1 month of cause
```

**Editability rules** (`REF`) — override all defaults elsewhere:

| Trigger | Opens for editing |
| --- | --- |
| Scrutiny officer marks errors (`REF-01`/`SCR-02/03`) | Only the marked fields/sections/documents |
| …a marked field is an interlinked date (`REF-03`/`SCR-04`) | + all **transitive downstream** dates (auto-marked) |
| …DCA became applicable since filing (`REF-04/05/06`) | + the Delay Condonation section, now required |
| Magistrate sends back (`REF-02`) | Everything |

`REF-04` is evaluated **against the clock at refiling**, never cached — a correction
cycle sitting for weeks silently attracts the DCA (and its fee → `LIFE-12`).

## 20.5 Notifications and events

The notifications this module triggers, as a live view of the master Notifications
table. Do not invent notification copy — the master table is the source of truth and
the place to edit it.

```superhuman-view
name: Notifications — E-Filing
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-xnftvTkudd/tables/grid-3FTjQhdfYv
filter: PRDs.Contains("efiling-scrutiny-registration-handover")
```

The case-timeline events this module raises, from the master Events/Case Updates table:

```superhuman-view
name: Events — E-Filing
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-2x28DoUtbn/tables/grid-GPg4dKS-s9
filter: PRDs.Contains("efiling-scrutiny-registration-handover")
```

A downloaded copy of this document is a snapshot of both.

**Owner decisions log** — 2026-08-25/26 (batch 1): s.138 only · profile switcher
precedes the flow, role predetermined; PoA-holder and PiP can file · clerks' advocates
auto-added · logged-in litigant = Complainant 1 · single scrutiny officer · drafts
deletable · refile payment: balance if increased, else skipped · FIL-01 = hard gate ·
affidavit its own screen; PiP affidavit a Litigant field · OTP cross-user autofill
removed · "Institution" terminology · one address composite · permanent first, current
next · PoA email + representative designation added · missing accused contacts recorded
as backend data only · multiple persons responsible, each later a separate accused ·
bank account number added as cheque field · IFSC lookup automatic · LDN dispatch: ≥ 1
cheque returned on/before dispatch · JUR-6a when deposited = No · xlsx comments void.
(batch 2): police station out of the address composite · 30-day dispatch warnings
removed · ADR field added (PRY-5) · witness address added, mandatory, repeatable like
accused · DCM-2 = number of cheques · same-mode signing is a requirement · no signing
order; parties can't change mid-signing, edits invalidate all signatures · upload-mode
per-party phone-OTP confirmations in spec · welfare caps per complainant; complaint-fee
slab on the sum of cheques · complaint PDF always current, preview gated on
mandatory+validations, no version retention · templates editable, blanks user-filled ·
upfront model: notice ×1, summons ≤4 rounds per address, warrants ≤4 rounds, court fee
each, e-post channel fee later, defaults = 1 summons round (all addresses) + 1 warrant
round · payment/e-sign failure handling left to engineering · magistrate send-back = one
overall comment · no outright rejection before registration.
(batch 3): "one month" = one **calendar month** · account creation for new complainants
happens at signing (e-sign login / upload OTP) · ACC-24 = information only, magistrate
decides · synopsis dishonour rows repeat per cheque · jurisdiction bank details repeat
per cheque as needed · synopsis prayer prints the Final Relief field · scrutiny
mark-comments deferred to a separate defect-correction design · one summons round
mandatory, court **and** channel fee.
(batch 5) — 2026-09-03, upfront process payment: process court fee = **12.50** for each
of notice, summons and warrant · the whole upfront choice is **per accused,
independently**, and the mandatory summons round is **per accused** (three accused = at
least three rounds) · defaults per accused = 1 summons round (mandatory) + 1 warrant
round; notice defaults to 1 round **when Delay Condonation applies**, else 0 · filer
selects which of that accused's addresses summons goes to, and the bill states the
multiplication (rate × addresses × rounds) on every line · delivery is **e-post only**,
no channel choice, INR 100/address/round placeholder · e-post is opted in/out
**separately from the summons court fee**, round by round, floor at the mandatory first
round (batch 3 stands). Supersedes batch 2's "defaults = 1 summons round (all
addresses) + 1 warrant round" only in that the choice is now per accused and per
address. §19.3 rewritten.
(batch 4): magistrate case-visibility irrelevant to this design · clerk↔advocate mapping
assumed to exist elsewhere in the system · removal from a case removes access ·
affidavit variance handled by user editing, no automation · remaining references to be
supplied later; file closed.
(batch 7) — 2026-09-09: case number format and generation moved to a separate document
(Q-2 removed) · case routing added (§20.1): auto-assignment to courtroom, configurable
allocation logic per establishment, Gujarat Phase 1 = institution-to-courtroom mapping +
fallback · Q-3/Q-4 answered inline.
(batch 8) — 2026-09-18, complaint PDF: `ACC-5` renamed **Institution Name** (from the
sheet's "Company Name") so the accused and complainant sides name it alike · optional
personal fields (`LIT-5a/5b`,
`LIT-24a/24b`, `ACC-24`) **print** — there is no category of field that is collected and
then held back · persons vicariously liable print **one block per person with every
field**, the same details appearing again in that person's own accused block · the document is **generated from the case's own
field set**, not a hardcoded template — fixed section order, every applicable field of
each section printed in form order, three-column field flow, new fields appear without a
template change (`DOC-01`) · signature block is placeholders positioned per required
signatory (`DOC-02`) · court name never hardcoded, case title uses **full names**, cover
prints whatever case number exists — the system-generated filing number before
registration (`DOC-03`) · "Institution" terminology applies to the printed document too
· documents DCM-9/DCM-10 are named **"ID Card"**, not "Aadhaar Card" · Police Station
(`ACC-13`) prints beneath its address on the accused · the sample's condensed synopsis
prayer is not a requirement (batch 3 stands: it prints `PRY-3`) · an optional field the
form **showed** and the filer left blank prints its label with `-`, all 24 of them, not
only the blanks that are legally material; a field the form never showed prints nothing ·
**No masking of the ID card at launch** — it is appended as uploaded so the scrutiny
officer can check it · the print rule is
**literal**: form-steering fields (party-in-person, same-address, PoA given?, bank
details same as previous cheque?, number of advocates) print like any other field — not
worth an exception list, and nobody is to suppress them later.
(batch 6) — 2026-09-07, scrutiny interface: three-panel scrutiny layout (fields /
document / document index) · field-level and section-level error marking with per-error
comments · document flagging for re-upload · interlinked-date auto-marking (marking one
date auto-marks all transitive downstream dates) · delay-condonation alert to the
scrutiny officer when delay becomes applicable since filing · registration assigns a case
number (format in separate document) · supersedes batch 3's deferral of mark-comments to a
separate design.
(batch 9) — 2026-09-23: registration point made configurable (`SCR-11/12`) — under
`registrationPoint: scrutiny`, the scrutiny officer's second action is Register (assigns
case number, → Cognisance) instead of Forward, and the magistrate's Registration
stage/task is skipped entirely; default `registrationPoint: magistrate` is today's
behaviour, unchanged.

---

# 21. Open questions — `Q`

One item pending delivery:

| # | Item | Blocks |
| --- | --- | --- |
| Q-1 | Pending references (owner will supply later): **MDMS sheet**, notifications master file, Event List (Coda), "PUCAR Integrations", the e-post charge (§19.3 `PAY-14`; the process court fee is settled at 12.50) | MDMS dropdowns, §19, §20 |

**Resolved:**
- ~~Q-2~~ Case number format — moved to a separate document.
- ~~Q-3~~ Multiple scrutiny officers — answered in §20.1. Each courtroom formally has its
  own; one officer may handle multiple courtrooms in practice. Case goes to the
  courtroom's designated officer.
- ~~Q-4~~ Which magistrate — answered in §20.1. The courtroom's magistrate. Case is
  auto-assigned to a courtroom after filing; allocation logic is configurable per
  establishment.

**Left to engineering at integration time** (owner): payment failure/timeout/
reconciliation; e-sign provider, failure modes, retry; gateway and e-sign integration
specs; complaint-PDF regeneration mechanics.

**Not covered by any source**: data model; API contracts (incl. idempotency on
payment/signing); MDMS schemas/ownership; NFRs (upload limits, audit logging — likely
legally required, retention); test scenarios (especially §20 interactions); migration of
in-flight cases; Aadhaar storage/masking (viewer restriction now decided, §14 — the
enforcement mechanism is not); bulk filing; accused-side experience after registration
(narrowed by the same §14 decision, otherwise still open).

---

# 22. Interaction patterns from the prototype

All `[PROTO]` (`Pucar-Dristi-2.0` @ `feature/e-filing-new`); backend seams in
`apps/dristi-app/src/lib/filing/README.md`. The prototype predates several owner
decisions: it free-navigates (now hard-gated), never gates preview (now gated on
mandatory+validations), lets the cause-of-action date be typed (spec: uneditable), uses
an explicit IFSC fetch button (spec: automatic). Its fee dialog was rebuilt to §19.3
on 2026-09-03 and now matches it.

- **Upload-first intake**: documents requested up front (per-cheque and per-party
  cards); dropped files fill empty required slots in order; six types are machine-read
  with real progress. Outcome copy: low confidence is a signal, not the outcome — any
  fields filled reads as success ("Read · 7 fields filled in your form"); only zero
  fields + low confidence reads as failure with Re-upload. Intake never blocks; the
  Documents section is the hard gate.
- **Machine-read provenance (core pattern)**: a prefilled-unedited field carries a
  review marker (dashed border, "Machine filled, not yet verified"); clicking opens the
  **source panel** — the uploaded page with the read region spotlighted, an editable
  value box, document chips, Replace/Open-original. Any edit retires the marker
  permanently. Extraction writes only into empty machine-owned fields; removing a
  document takes back only untouched values. No design-system primitive exists yet
  (open DS request).
- **Autosave/resume**: clone → apply → recompute derived documents → debounced write
  (300 ms), flushed on tab-hide; indicator shows the real write state. `lastStep`
  follows the URL; "Continue draft" resumes in place.
- **Repeatable entities**: tabs for heavy records (status dot, meta, remove disabled at
  one record, confirm dialog naming what is lost); inline lists for light rows
  (contacts, addresses); advocates as stacked cards.
- **Validation posture**: advisory by default — warnings never block (non-funds return
  reason "Check that S-138 still applies", limitation state, blurry-scan detection,
  lookup failures that hand fields back for typing). PIN lookup auto-fills district/
  state only into blank or previously PIN-filled fields, silent on failure, politely
  announced. Directory comboboxes accept anything typed.
- **Preview**: synopsis cards with read-only per-section review sheets (entered values +
  source thumbnails) and the composed court document; print is the PDF path.
- **Sign & pay (sandbox)**: signatory rail derived from the case; mode-choice dialog
  stating consequences for other parties; upload mode with per-party phone
  confirmations (now spec, §18); fee dialog with per-line rate × addresses ×
  rounds, priced per accused (§19.3); simulated payment; success dialog with
  generated case number. Every sandbox surface says so in place.
- **Dashboard**: continue-draft cards ("X vs Y", last saved, "Up to <step>", % bar),
  discard-draft with confirm, start-a-new-case cards, recently-filed table whose status
  honestly reads "Submitted from this browser — registry status is not connected yet".

---

# 23. Glossary

| Term | Meaning |
| --- | --- |
| DCA | Delay Condonation Application — attaches when filed beyond limitation; INR 20 fee. |
| LDN | Legal Demand Notice — notice to the accused before filing. |
| MDMS | Master Data Management System — reference data behind dropdowns/config. |
| PoA-Holder | Power-of-Attorney holder; acts and signs on a complainant's behalf. |
| Party-in-Person (PiP) | A complainant representing themselves; never counted as an advocate. |
| Scrutiny | Court-staff defect review before registration. |
| Registration | Case-number assignment that moves the case to Cognisance. Done by the magistrate (default) or directly by the scrutiny officer, per `registrationPoint` (§20.3a). |
| Cognisance | Post-registration stage; end of this module. |
| Natively digital | Per-document attribute: born-digital vs scanned. |
| Vakalatnama | The document appointing an advocate. |
