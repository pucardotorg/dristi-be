# Bulk Filing

**Status:** v8.19 — 2026-11-13; **Documents takes only what the case's sections allow** (`BLK-11e`, new): the same documents as individual filing's Documents step; a document for a section the case does not have, such as a second cheque, needs that section added on Case details first. **A case changed after reaching Documents goes back to Case details** until fixed (`BLK-11f`, new); its documents are kept (`Q-6` removed). A case waiting for signatures has no time limit (`BLK-14b`, new; `Q-9` removed). `Q-10`, `Q-11` and `Q-12` (failed signing, failed payment, filing failing after payment) are removed: the e-filing handover leaves signing and payment failures to engineering (§21). `Q-8` (a batch document going out of date) is removed: batch details cannot be changed once the batch exists (`BLK-05c`), so such a document is replaced in each case (`BLK-11c`). **Status:** v8.18 — 2026-11-13; **open questions answered**: batch details stay unchangeable once the batch is created (`BLK-05c`; `Q-1` removed); a file that cannot be read shows an error, and the filer can close it and try again (`BLK-10j`, new; `Q-2` removed); if no row can be created, no batch is created (`BLK-10k`, new; `Q-3` removed); if creating the batch stops partway, the filer uploads the file again to it (`BLK-10l`, new; `Q-4` removed); what the filer entered before leaving is kept as an unfinished batch in the filer's list of batches (`BLK-10m`, new; `Q-5` removed). **Status:** v8.17 — 2026-11-13; **a batch with every case removed no longer exists** (`BLK-08b`, new; answers `Q-16`). `Q-15`, two people changing the same case, is removed: it is for engineering, as for a case filed individually. v8.16 — 2026-11-13; **repeated sections reworded** (§4.2): `BLK-27` is split, with a case that has more than the file carries now in `BLK-27a` (new); `BLK-28` says more plainly when a case has a group. The note on interim relief, final relief and the affidavit (§4.3) is reworded. No requirement changes. `BLK-35` is split: the rule for rows stays in `BLK-35`, now pointing to `BLK-37`, and a file with no column for an essential field moves to `BLK-35a` (new), with a note that the essential fields will be refined over time. v8.15 — 2026-11-13; **Additional details templates** (§3.5): the filer chooses a saved template or writes a new one, whose fields each stand for an e-filing field (`BLK-10a`, reworded); any e-filing field can be used, identified by its e-filing section and its name within it, replacing a small set of fields (`BLK-10c`; `Q-17` removed); only text in the template's field format is a field, and engineering settles the format (`BLK-10i`, new); fields are filled for every case as the template is edited, which can be scaled back if too costly (`BLK-10e`); a field with no value, or more than one value, in a case is left unfilled and the case needs fixing (`BLK-10h`, new). v8.14 — 2026-11-13; **Match columns matches the filer's columns to the template's columns** (§4.3), not to every field of a case (`BLK-38`, `BLK-38a`, `BLK-38b`, `BLK-30`); `BLK-38b` says plainly that one value from a column's list can be used for every row instead of a column of the file. §3.4 explains with an example when Match values comes. List values are matched to the column's fixed list ignoring case only, no longer spacing and punctuation (`BLK-33`, `BLK-39`, §3). v8.13 — 2026-11-13; **uploading again leaves only filed cases untouched** (`BLK-40`): signed cases not yet filed are replaced too. This answers `Q-13` (a partly signed case), which is removed. v8.12 — 2026-11-13; **the first four steps apply to Excel filing only** (§3): Batch details, Excel file, Match columns and Match values do not apply to API filing. v8.11 — 2026-11-13; **restructured: each step of §3 has its own subsection** (§3.1–§3.11), with an overview table of the steps; requirements that held several rules are split into one row each, keeping their wording and their IDs, with new letters for the added rows (`BLK-05a…c`, `BLK-10g`, `BLK-11a…d`, `BLK-12a…d`, `BLK-14a`, `BLK-15a…c`, `BLK-38a…c`, `BLK-39a`). Batch details (`BLK-05`, `BLK-06`, the table) move from §2 to §3.1; uploading again (`BLK-40`) moves from §4.7 to §3.2; Match columns and Match values move from §4.6 to §3.3 and §3.4; §4.6 and §4.7 are removed. **Additional details templates** (§3.5): the fields are a small set of values every case always has (`BLK-10c`, new; list to do, `Q-17`); each filer has a default template (text to do, `Q-18`) and can write their own, which belong to them only (`BLK-10d`, new). New §5 Enhancements: sharing templates, and templates in individual filing. Open questions are now §6. v8.10 — 2026-11-13; **§3 lists every step before the batch is created**: Excel file (`BLK-10`), Match columns (`BLK-38`, moved from §4.6), Match values (`BLK-39`, moved from §4.6; it applies whenever list values match none of the state's values, not only to other layouts), Additional details (`BLK-10a`, explained as e-filing's `PRY-1` written once for the batch as a template; §3.1 removed) and Create batch (`BLK-10b`, new; the second half of the old `BLK-10`). §4.6 now points to these steps. No requirement changes. v8.9 — 2026-11-13; **edge cases and failures specific to bulk filing** added as open questions `Q-2`…`Q-16` (§5): an unreadable file, partial creation, leaving before creating, a case edited after reaching Documents, skipped warnings, out-of-date batch documents, unfinished or failed signing, failed or unconfirmed payment, filing failing after payment, uploading again with a partly signed case, reused draft numbers, two people on one batch, an empty batch. v8.8 — 2026-11-13; **§3 reorganised for reading**: rows are full sentences; the seven steps are listed first, with batch details (§2) as step 1; Upload is now **Excel file** (`BLK-10`); Additional details for the batch moves to its own §3.1 (`BLK-10a`); `BLK-11` says what a case needs and what the filer can do, no longer how the screen looks. No requirement changes. v8.7 — 2026-11-13; **case reference dropped** (`BLK-07` withdrawn, see [`dropped-ideas.md`](dropped-ideas.md)): its exact need is not known yet, and alongside the draft number (`BLK-04b`), which matches each Excel row to its case, a second reference would confuse filers; it may come back later. The template loses its Case reference column (78 columns, §4.3). In a file in the template's layout, rows 2 and 3 are discarded, no longer rows whose reference starts with `EXAMPLE` (`BLK-22`, `BLK-36`). A row is no longer left out for lacking or repeating a reference (`BLK-37`). v8.6 — 2026-11-13; **the batch places no restriction on its cases** (`BLK-08`, rewritten): until a case is filed, it can be removed from the batch and can move ahead without the rest. `BLK-08a` (removal until signed) is folded into it and withdrawn. v8.5 — 2026-11-13; **batch details are listed in their own table** (§2), with `BLK-05` as the rule; the meaning is unchanged. v8.4 — 2026-11-13; **batch number is `B` and the filer's own count** (`BLK-04a`): `B1`, `B2`…, replacing `BLK-<year>-<nnnn>`. **Draft number** for each case from an Excel file (`BLK-04b`, new): batch number, then `R` and the Excel row, for example `B7-R12`, so each row matches one case; shown to the filer, not printed. v8.3 — 2026-11-13; brought in line with the bulk filing prototype of 2026-11-12. **Case details comes before Documents** (§3; `BLK-11` and `BLK-12` swap places, IDs unchanged): a case joins Documents once nothing is left to fix in its details. **Batch details are entered before the file and cannot be changed for the batch once it is created** (`BLK-05`). **Additional details can be written once for the batch** (`BLK-10a`, new). **A case can be removed from a batch** until it is signed (`BLK-08a`, new). Before the batch is created, the filer sees how many cases will be created and how many need fixing or have warnings (`BLK-10`). **A file with no column for the accused's name, the cheque number or the cheque amount creates no cases** (`BLK-35`). **Rows that cannot be created** now also include a row with neither a case reference nor an accused name, and a row repeating a cheque number and amount (`BLK-37`, no longer `[DERIVED]`). New §5 Open questions, `Q-1`. v8.2 — 2026-11-10; the person-responsible columns follow e-filing's IDs: address `ACC-18…22`, police station `ACC-23`. v8.1 — 2026-11-03; title no longer ends in "Developer & Agent Handover". v8 — 2026-10-24; **uploading again** (`BLK-40`): signed and filed cases are not touched, and rows are not matched to existing cases; BQ-1 answered, so the open questions section is removed. v7 — 2026-10-24; §4.3 lists each column's header and field ID only; type, format and when it is required come from the e-filing handover. v6 — 2026-10-24; **a vakalatnama for each complainant** of the batch (`BLK-05`), as in the e-filing flow, instead of one for the batch. v5 — 2026-10-24; `BLK-05` says plainly that the only documents entered for the batch are those that go with the complainant and advocate details; every other document is uploaded per case. v4 — 2026-10-24; **clubbing batches removed** (was `BLK-09`). v3 — 2026-10-24; **complainants and advocates are the same across a batch only when it is created** (`BLK-04`, `BLK-06`): once the drafts exist, each case's complainants and advocates can be changed in that case. v2 — 2026-10-24; **source and batch number** (`BLK-01a`, `BLK-04a`): every case records whether it came from Individual, Excel or API filing, and a bulk case carries its batch number (`BLK-<year>-<nnnn>`), for tracking and for placing it on screen; neither is printed. v1 — 2026-10-24; first version. Bulk filing of S-138 cases and the Excel
format for it: one sheet, one row per case, fixed numbered column groups (78 columns in the
template). Replaces `bulk-filing-problem-statement.md` and the multi-sheet format in
`docs/bulk-upload-spec.md`, both withdrawn. The API is specified separately.
**Date:** 2026-10-24
**Audience:** developers and agents building bulk filing (front end and backend)

## Sources and precedence

| Source | Provides |
| --- | --- |
| Owner decisions, 2026-10-24 | Everything in this document, marked **[OWNER]** where it is a decision |
| [`efiling.md`](efiling.md) | Every field, validation, document, fee and signing rule a case carries. Field IDs (`ACC-13`, `CHQ-9`, `DCM-12`) are that handover's |
| [`signing-methods.md`](signing-methods.md) | The signing methods and batch signing |
| Bulk filing prototype, `Pucar-Dristi-2.0` `main`, `apps/dristi-app/src/app/filings/bulk/` | The batch screens |

This document owns **the batch and the Excel format**. Everything a case is, and
everything that happens to it once it exists, belongs to the e-filing handover. Where the
two disagree on a field, the e-filing handover wins.

Marks: `[DERIVED]` inferred, confirm before building · `[OWNER]` owner decision.

---

# 1. What bulk filing is

Bulk filing creates many S-138 cases at once from one Excel file, or from the API. Each
case it creates is an ordinary draft of the e-filing flow.

| ID | Requirement |
| --- | --- |
| `BLK-01` | **[OWNER]** **A case filed in bulk is indistinguishable from one filed individually**: the same fields, documents, complaint PDF, synopsis, affidavit, signatures, payment record and case state. Every validation, warning, derived value and rule of the e-filing handover applies to it unchanged — limitation and delay condonation, fees, refiling, editability. The only additions are the case's **source** and **batch number** (`BLK-01a`). |
| `BLK-01a` | **[OWNER]** **Every case records its source** — **Individual**, **Excel** or **API** — and a case filed in bulk records its **batch number**. They are used to track cases and to show each one in the right place on screen, since screens may list bulk and individual cases separately. They are not printed in any document. |
| `BLK-02` | **[OWNER]** Anyone who can draft an individual case can file in bulk (e-filing handover §3). |
| `BLK-03` | **[OWNER]** There is no product limit on cases per batch. Any limit is set by engineering. |

# 2. The batch

| ID | Requirement |
| --- | --- |
| `BLK-04` | **[OWNER]** **When a batch is created, every case in it has the same set of complainants and the same set of advocates.** A set may hold more than one complainant or advocate. Cases for a different set go in a different batch. |
| `BLK-04a` | **[OWNER]** Each batch has a **batch number**: `B` followed by a count of the filer's own batches, in the order the filer creates them — `B1`, `B2`, `B3`. Each filer's count is their own, so two filers can each have a `B1`. The filer refers to the batch by it, and a case filed in bulk carries it (`BLK-01a`). |
| `BLK-04b` | **[OWNER]** Each case created from an Excel file has a **draft number**: its batch number, then `R` and the number of the Excel row it came from — for example `B7-R12` for row 12 of batch `B7`'s file. The filer can match each row of the file to its case by it. It is shown to the filer and can be searched by. Like the batch number, it is not printed in any document; the case still has its ordinary filing number (e-filing handover §16). |
| `BLK-08` | **[OWNER]** The batch places no restriction on its cases. Until a case is filed, it can be removed from the batch, and it can move ahead without the rest of the batch. Which of these the screens offer is a design choice. |
| `BLK-08b` | **[OWNER]** A batch from which every case has been removed no longer exists. |

# 3. From upload to filing

A batch goes through these steps, in this order. Once the batch is created, each case
goes through the remaining steps on its own, without waiting for the rest of its batch
(`BLK-08`).

| Step | Section | When it applies |
| --- | --- | --- |
| Batch details | §3.1 | Excel filing only |
| Excel file | §3.2 | Excel filing only |
| Match columns | §3.3 | Excel filing only, for a file that is not in the template's layout |
| Match values | §3.4 | Excel filing only, when the file has values that are not on a column's fixed list |
| Additional details | §3.5 | Optional |
| Create batch | §3.6 | Always |
| Case details | §3.7 | For each case, until nothing is left to fix |
| Documents | §3.8 | For each case |
| Review | §3.9 | For each case |
| Sign | §3.10 | For each case |
| Pay | §3.11 | For each case |

## 3.1 Batch details

| ID | Requirement |
| --- | --- |
| `BLK-05` | **[OWNER]** **Batch details** are the details every case in the batch shares, listed in the table below. |
| `BLK-05a` | **[OWNER]** The filer enters the batch details once, before choosing the Excel file, and every case the batch creates gets them. |
| `BLK-05b` | **[OWNER]** The only documents among the batch details are those that go with the complainants and advocates. Every other document is added for each case on Documents (§3.8). |
| `BLK-05c` | **[OWNER]** Once the batch is created, its batch details can be viewed but not changed for the batch. |
| `BLK-06` | **[OWNER]** Once the drafts are created, each case's complainants and advocates can be changed in that case like any other field, as in the e-filing flow. A change to one case does not change the others. |

| Detail | What the filer enters | E-filing reference |
| --- | --- | --- |
| Complainants | Every field of the Complainant section, including power of attorney | §6 |
| Advocates | Every field of the Advocate section, including whom each advocate appears for. An advocate filing is already added, with their junior advocates; a clerk filing has the advocates they work for already added. Any of them can be removed. | §7, `ADV-2`, `FIL-05` |
| ADR preference | Whether the complainant is open to ADR | `PRY-5` |
| Complainant ID cards | One for each complainant | `DCM-9` |
| PoA holder ID cards | One for each PoA holder | `DCM-10` |
| PoA authorisations | One for each power of attorney | `DCM-11` |
| Vakalatnamas | One for each complainant | `DCM-12` |

## 3.2 Excel file

| ID | Requirement |
| --- | --- |
| `BLK-10` | The filer chooses the Excel file; §4 sets out its format. A file in the template's layout goes on to the next step that applies. A file in any other layout, for example a lender's own report, goes to Match columns first (§3.3). |
| `BLK-10j` | **[OWNER]** If the file cannot be read, for example because it is damaged, protected by a password or of the wrong type, the filer is shown an error message, and can close it and try again with a file. |
| `BLK-40` | **[OWNER]** **Uploading an Excel file again replaces the batch's drafts.** Its draft cases, their documents and every change made on Case details are discarded, and a draft is created for every row of the new file. Only cases already filed are not touched. Rows are not matched to existing cases. |

## 3.3 Match columns

This step comes only for a file that is not in the template's layout.

| ID | Requirement |
| --- | --- |
| `BLK-38` | For each column of the template (§4.3), the filer sees which column of their file is matched to it. Columns are matched by their header names where possible. |
| `BLK-38a` | The filer can pick a different column of their file for any template column, or leave it to be filled in on Case details. |
| `BLK-38b` | For a template column whose values come from a list, the filer can choose one value from that list instead of a column of their file; that value is used for every row. |
| `BLK-38c` | Repeated sections, such as a second cheque, are found from numbered columns (§4.2), and the filer can correct how many of each the file holds. |

## 3.4 Match values

Some template columns take a value from a fixed list, for example
Accused type (Individual or Institution) or the reason a cheque was returned. A filer's own
file often uses its own words for these, such as `COMPANY` for Institution or `A/C CLOSED`
for Account closed. A value that is not on the list comes to this step for the filer to
match (`BLK-33`). If every value in the file is on its list, this step does not come.

| ID | Requirement |
| --- | --- |
| `BLK-39` | Each value that is not on its column's list is shown, and the filer maps it to a value from that list. |
| `BLK-39a` | A value left unmapped is invalid, and is treated as `BLK-34` says. |

## 3.5 Additional details

This step is optional.

| ID | Requirement |
| --- | --- |
| `BLK-10a` | **[OWNER]** E-filing has an Additional details field for each case (`PRY-1`). Here the filer chooses a saved template or writes a new one, and it is used for every case in the batch. A template is text with fields in it, such as the accused's name or the cheque amount, and each field stands for a field of the e-filing flow. In each case, every field is filled with that case's own value. |
| `BLK-10c` | **[OWNER]** Any field of the e-filing flow can be used in a template. A field is identified by two things: the name of its section in [`efiling.md`](efiling.md), and its own name within that section — for example the Accused Details section and Full Name (`ACC-2`). The screens use these two parts to organise the fields for the filer, for example grouping them by section and showing only each field's name, or showing the section and field name together. |
| `BLK-10i` | **[OWNER]** A field is written in a template in one specific format. All other text in the template is treated as plain text. The format, for example the field's name in square brackets or in curly brackets, is settled by engineering when it is built. |
| `BLK-10h` | **[OWNER]** Where a case has no value for a field, or more than one value, such as two accused or two cheques, that field is left unfilled in the case's text, and the case is marked **Needs fixing** on Case details (`BLK-12b`) until the filer resolves it. |
| `BLK-10d` | **[OWNER]** Each filer has a default template to start from (`Q-18`). The filer can also write their own templates, which belong to that filer only. |
| `BLK-10e` | **[OWNER]** The filer can see how the text reads in any case of the batch.<br>*This means the fields are filled for every case of the batch each time the template changes. If the engineering effort for this proves too high, it can be scaled back.* |
| `BLK-10f` | **[OWNER]** If some rows of the file already have their own Additional details, the filer chooses whether those rows keep their own text or take the batch's. Rows with no text of their own take the batch's. |

## 3.6 Create batch

| ID | Requirement |
| --- | --- |
| `BLK-10b` | Before creating the batch, the filer sees how many cases will be created, and how many of those will need fixing or have warnings on Case details (§3.7). The filer also sees how many rows were discarded (`BLK-36`) and which rows cannot be created (`BLK-37`). |
| `BLK-10g` | Creating the batch creates one draft case per row. A file that cannot create any case is described in `BLK-35a`. |
| `BLK-10k` | **[OWNER]** If no row of the file can be created, no batch is created. |
| `BLK-10l` | **[OWNER]** If creating the batch stops partway, the drafts already made stay in the batch, and the filer uploads the file again to it. As with any upload again (`BLK-40`), those drafts are discarded and every row of the file is read again. |
| `BLK-10m` | **[OWNER]** If the filer leaves before creating the batch, what they have entered is kept as an unfinished batch in the list of the filer's batches. The filer can come back to it or delete it. |

## 3.7 Case details

| ID | Requirement |
| --- | --- |
| `BLK-12` | The filer sees every open case and what it still needs. |
| `BLK-12a` | Opening a case shows it in the e-filing screens, at the first section with something to fix. |
| `BLK-12b` | A case is marked **Needs fixing** when a required value is missing or invalid. It cannot go ahead until that is fixed. |
| `BLK-12c` | A case is marked **To check** when it has an e-filing warning (for example `CHQ-10`, `CHQ-11`). The filer can skip the warning, and the case goes ahead. |
| `BLK-12d` | Changes are saved as the filer types. |

## 3.8 Documents

| ID | Requirement |
| --- | --- |
| `BLK-11` | Each case needs the documents that follow from its data, as in the e-filing handover §14 (`DCM-1`…`DCM-8`, `DCM-13`). |
| `BLK-11a` | The batch's own documents (§3.1) are already attached to every case. |
| `BLK-11b` | **[OWNER]** A case comes to Documents only once nothing is left to fix in its details (§3.7), because fixing them can change which documents it needs. |
| `BLK-11c` | The filer adds each document, and can view and replace it until the case is signed. |
| `BLK-11d` | Cases missing a document are listed first. |
| `BLK-11e` | **[OWNER]** The documents a case can take here are the same as on the Documents step of individual filing (e-filing handover §14). The filer can add documents only for the sections the case already has: if it has one cheque, a document for a second cheque cannot be added here. To add one, the filer first adds the section to the case on Case details, and can then add its documents. This keeps a single way of changing a case's sections, so there are fewer paths that can go wrong. |
| `BLK-11f` | **[OWNER]** If a case that has reached Documents is changed so that something needs fixing, for example a second cheque is added, it goes back to Case details until that is fixed (`BLK-11b`). The documents already added are kept. |

## 3.9 Review

| ID | Requirement |
| --- | --- |
| `BLK-13` | The filer reads each case as the court will read it: its synopsis and complaint, one case at a time. |

## 3.10 Sign

| ID | Requirement |
| --- | --- |
| `BLK-14` | The filer chooses the cases to sign, and each signatory signs them together with a method switched on for the state ([`signing-methods.md`](signing-methods.md)). |
| `BLK-14a` | **[OWNER]** The oath is recorded once and applies to every case signed with it (e-filing handover §18.2). |
| `BLK-14b` | **[OWNER]** A case waiting for signatures has no time limit. Editing it invalidates every signature already given (e-filing handover `LIFE-13`), and so does a change in its limitation (e-filing handover `SIG-12`). |

## 3.11 Pay

| ID | Requirement |
| --- | --- |
| `BLK-15` | **[OWNER]** The filer pays for the chosen cases together, in one payment gateway transaction. |
| `BLK-15a` | **[OWNER]** The system generates **a receipt for each case**, each carrying the shared gateway transaction ID. |
| `BLK-15b` | **[OWNER]** Upfront process payments take the defaults of e-filing handover §19.2 for every accused. |
| `BLK-15c` | Each case gets its own case number and is filed when the payment completes. |

# 4. The Excel format

## 4.1 The file

| ID | Requirement |
| --- | --- |
| `BLK-20` | The filer downloads the template from the bulk filing screen. It is generated for the filer's state: its dropdowns carry that state's MDMS values. |
| `BLK-21` | The template has three sheets: **Cases**, where the cases go; **Lists**, holding each dropdown's values; and **Instructions**, describing each column and how repeated sections are numbered (§4.2). |
| `BLK-22` | **Cases**: row 1 holds the column headers (§4.3). Row 2 describes what each column takes — type, format, and when it is required. Row 3 is an example case. From row 4, **one row per case**. |
| `BLK-23` | Upload accepts `.xlsx` and `.csv`. In an `.xlsx`, the sheet named **Cases** is read; failing that, the first sheet with rows. |

## 4.2 Repeated sections

| ID | Requirement |
| --- | --- |
| `BLK-24` | **[OWNER]** A section that repeats in a case is a group of columns, and every instance of a group carries **every field of that section**. The template includes: |

| Group | Instances in the template |
| --- | --- |
| Accused | 2 |
| Address, per accused | 1 |
| Person responsible, per accused | 1 |
| Cheque | 1 |
| Demand notice | 1 |
| Witness | 1 |
| Other pending case | 1 |

| ID | Requirement |
| --- | --- |
| `BLK-25` | **[OWNER]** These counts keep the sheet a workable width. They are configuration, changed when filers' cases show a different need (for example 3 cheques instead of 1). The API accepts any number. |
| `BLK-26` | **Every repeated thing carries its number in the header**, next to the thing it counts, including the first: `Accused 1 name`, `Accused 2 name`, `Accused 1 address 1 pincode`, `Accused 1 person responsible 1 name`, `Cheque 1 amount`, `Demand notice 1 dispatch date`, `Witness 1 name`. |
| `BLK-27` | A file may have more instances of a group than the template, numbered the same way (for example `Cheque 2 amount` when the template has one cheque). They are read like any other column. |
| `BLK-27a` | If a case has more of something than the file carries, for example a second cheque in a file with columns for only one, the filer adds it on Case details. |
| `BLK-28` | **[OWNER]** A case has a group, for example a second accused, when at least one of that group's cells in its row is filled. That group's required columns must then be filled for the case. If every cell of a group is blank, the case does not have that group, and its required columns do not apply. |

## 4.3 Columns

`N` is the instance number (§4.2). Each column takes its field's type, format, list values
and conditions from the [e-filing handover](efiling.md); the template's row 2
states them for the filer. A group's required columns apply only when the group is present
(`BLK-28`).

**Accused N** — 19 columns per accused: 11 for the accused, 8 for their person responsible

| Header | Field |
| --- | --- |
| Accused N type | `ACC-1` |
| Accused N name | `ACC-2`; `ACC-5` for an institution |
| Accused N age | `ACC-3` |
| Accused N institution type | `ACC-4` |
| Accused N mobile | `ACC-6` |
| Accused N email | `ACC-7` |
| Accused N address 1 line | `ACC-8…12` |
| Accused N address 1 city | `ACC-8…12` |
| Accused N address 1 pincode | `ACC-8…12` |
| Accused N address 1 police station | `ACC-13` |
| Accused N resides within jurisdiction | `ACC-24` |
| Accused N person responsible 1 name | `ACC-14` |
| Accused N person responsible 1 designation | `ACC-15` |
| Accused N person responsible 1 mobile | `ACC-16` |
| Accused N person responsible 1 email | `ACC-17` |
| Accused N person responsible 1 address line | `ACC-18…22` |
| Accused N person responsible 1 address city | `ACC-18…22` |
| Accused N person responsible 1 address pincode | `ACC-18…22` |
| Accused N person responsible 1 police station | `ACC-23` |

Each person responsible also becomes a separate accused in the case, as in the e-filing
handover §8. `[DERIVED]` That accused is created from the person-responsible columns; the
person is not entered again as Accused 2.

**Cheque N** — 11 columns per cheque

| Header | Field |
| --- | --- |
| Cheque N number | `CHQ-3` |
| Cheque N date | `CHQ-1` |
| Cheque N amount | `CHQ-2` |
| Cheque N drawer bank IFSC | `CHQ-5` |
| Cheque N drawer account number | `CHQ-7a` |
| Cheque N presentation date | `CHQ-8` |
| Cheque N return date | `CHQ-9` |
| Cheque N return reason | `CHQ-10` |
| Cheque N complainant branch IFSC | `JUR-2` |
| Cheque N complainant branch police station | `JUR-5` |
| Cheque N drawer branch police station | `JUR-6a` |

**Demand notice N** — 11 columns per notice

| Header | Field |
| --- | --- |
| Demand notice N nature of debt | `LDN-1` |
| Demand notice N dispatch date | `LDN-2` |
| Demand notice N mode of service | `LDN-3` |
| Demand notice N tracking number | `LDN-4` |
| Demand notice N delivered | `LDN-5` |
| Demand notice N delivery date | `LDN-6` |
| Demand notice N return date | `LDN-7` |
| Demand notice N reason for non-delivery | `LDN-8` |
| Demand notice N accused replied | `LDN-9` |
| Demand notice N payment after notice | `LDN-10` |
| Demand notice N amount paid | `LDN-11` |

**Jurisdiction and limitation** — 5 columns

| Header | Field |
| --- | --- |
| Deposited in complainant's account | `JUR-1` |
| Other complaint pending between the same parties | `JUR-6b` |
| Other pending case 1 court | `JUR-7` |
| Other pending case 1 case number | `JUR-8` |
| Reason for condonation of delay | `JUR-12` |

**ADR, prayer and other details** — 4 columns

| Header | Field |
| --- | --- |
| Additional details | `PRY-1` |
| Interim relief | `PRY-2` |
| Final relief | `PRY-3` |
| Affidavit | `PRY-4` |

**[OWNER]** In e-filing, interim relief, final relief and the affidavit start with standard
text that has blanks for the filer to fill (e-filing handover §17). For these three columns,
the system takes the text in the sheet as the complete text for that case. These three
columns and Additional details are plain text: each line break in a cell starts a new
paragraph.

**Witness N** — 9 columns per witness

| Header | Field |
| --- | --- |
| Witness N name | `WIT-1` |
| Witness N designation | `WIT-4` |
| Witness N age | `WIT-2` |
| Witness N what they will prove | `WIT-3` |
| Witness N mobile | `WIT-5` |
| Witness N email | `WIT-6` |
| Witness N address 1 line | `WIT-7` |
| Witness N address 1 city | `WIT-7` |
| Witness N address 1 pincode | `WIT-7` |

**In the template:** 2 × 19 + 11 + 11 + 5 + 4 + 9 = **78 columns**. Each further
instance adds: accused 19, cheque 11, witness 9, person responsible 8, demand notice 11,
accused address 4, witness address 3, other pending case 2.

The system derives the rest, so they have no column: district and state from a pincode;
bank name and branch from an IFSC; the advocate's name from their Bar registration; the
cause of action, filing date and delay (`JUR-9`…`JUR-11`); the fees; the synopsis.

## 4.4 Reading values

| ID | Requirement |
| --- | --- |
| `BLK-30` | Headers are matched ignoring case, spacing and punctuation. Columns can be in any order. Columns that match no template column are ignored. |
| `BLK-31` | **Dates** are read from an Excel date, or text as `DD-MM-YYYY` (with `-`, `/` or `.`) or `YYYY-MM-DD`. Text in any other form is invalid. |
| `BLK-32` | **Identifiers** — mobile, pincode, cheque number, account number, IFSC — are read as text, so leading zeros and long account numbers are kept. **Amounts** are numbers; commas are ignored. |
| `BLK-33` | **List values** are matched to the column's list ignoring case. Values that match none go to the **Match values** step (`BLK-39`, §3). |
| `BLK-34` | **[OWNER]** **An invalid value is ignored**: the field is left empty. If the field is required, the case is marked **Needs fixing** on Case details. A value in a column that does not apply to the case — a delivery date when the notice was not delivered, an institution type for an individual — is ignored the same way. |
| `BLK-35` | **[OWNER]** **A row with missing or ignored values is still imported**, as a draft with what it has. What it lacks is fixed on Case details. The only rows not imported are those in `BLK-37`. |
| `BLK-35a` | **[OWNER]** A file with no column for the accused's name, the cheque number or the cheque amount creates no cases, and the filer is told which columns are missing.<br>*Which fields are essential, so that no draft is created without them, will be refined over time.* |

## 4.5 Rows

| ID | Requirement |
| --- | --- |
| `BLK-36` | In a file in the template's layout, row 2 (column descriptions) and row 3 (the example case) are discarded. Blank rows are skipped. Before the batch is created, the filer sees how many rows were discarded. |
| `BLK-37` | **[OWNER]** These rows cannot be created and are not imported: a row with no accused name; a row repeating the cheque number and amount of a row higher in the file. Before the batch is created, the filer sees each such row, with its row number in the file and the reason, and can download them to correct. |

# 5. Enhancements

- **Sharing Additional details templates.** Today a filer's own templates belong to that
  filer only (`BLK-10d`). In a later version they can be shared with others; who they
  can be shared with is to be defined.
- **Additional details templates in individual filing.** In a later version, the
  templates of §3.5 are also offered when a case is filed individually.

# 6. Open questions

| ID | Question | Blocking |
| --- | --- | --- |
| `Q-7` | If the filer skips a warning (To check) and then changes the data it was about, does the warning come back? | No |
| `Q-14` | After uploading again (`BLK-40`), a draft number (`BLK-04b`) can point to a different case than before, since it follows the row of the new file. Is that acceptable, or must a draft number never be reused within a batch? | No |
| `Q-18` | To do: write the default Additional details template every filer starts from (`BLK-10d`). | No |
