# Bulk Filing — Developer & Agent Handover

**Status:** v8 — 2026-10-24; **uploading again** (`BLK-40`): signed and filed cases are not touched, and rows are not matched to existing cases; BQ-1 answered, so the open questions section is removed. v7 — 2026-10-24; §4.3 lists each column's header and field ID only; type, format and when it is required come from the e-filing handover. v6 — 2026-10-24; **a vakalatnama for each complainant** of the batch (`BLK-05`), as in the e-filing flow, instead of one for the batch. v5 — 2026-10-24; `BLK-05` says plainly that the only documents entered for the batch are those that go with the complainant and advocate details; every other document is uploaded per case. v4 — 2026-10-24; **clubbing batches removed** (was `BLK-09`). v3 — 2026-10-24; **complainants and advocates are the same across a batch only when it is created** (`BLK-04`, `BLK-06`): once the drafts exist, each case's complainants and advocates can be changed in that case. v2 — 2026-10-24; **source and batch number** (`BLK-01a`, `BLK-04a`): every case records whether it came from Individual, Excel or API filing, and a bulk case carries its batch number (`BLK-<year>-<nnnn>`), for tracking and for placing it on screen; neither is printed. v1 — 2026-10-24; first version. Bulk filing of S-138 cases and the Excel
format for it: one sheet, one row per case, fixed numbered column groups (79 columns in the
template). Replaces `bulk-filing-problem-statement.md` and the multi-sheet format in
`docs/bulk-upload-spec.md`, both withdrawn. The API is specified separately.
**Date:** 2026-10-24
**Audience:** developers and agents building bulk filing (front end and backend)

## Sources and precedence

| Source | Provides |
| --- | --- |
| Owner decisions, 2026-10-24 | Everything in this document, marked **[OWNER]** where it is a decision |
| [`efiling-handover.md`](efiling-handover.md) | Every field, validation, document, fee and signing rule a case carries. Field IDs (`ACC-13`, `CHQ-9`, `DCM-12`) are that handover's |
| [`signing-methods.md`](signing-methods.md) | The signing methods and batch signing |
| Bulk filing prototype, `Pucar-Dristi-2.0` branch `bulk-filing`, `apps/dristi-app/src/app/filings/bulk/` | The batch screens |

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
| `BLK-04a` | Each batch has a **batch number**, `BLK-<year>-<nnnn>`, numbered in the order batches are created within the year — for example `BLK-2026-0007`. The filer refers to the batch by it, and a case filed in bulk carries it (`BLK-01a`). |
| `BLK-05` | **[OWNER]** **Batch details are entered once, on the upload screen, and apply to every case:** the complainants, with every field of the e-filing Complainant section (§6) including power of attorney; the advocates (§7), with whom each appears for (`ADV-2`); the ADR preference (`PRY-5`); and **only the documents that go with the complainant and advocate details**: complainant ID cards (`DCM-9`), PoA holder ID cards (`DCM-10`), PoA authorisations (`DCM-11`) and **a vakalatnama for each complainant** (`DCM-12`), as in the e-filing flow. Every other document is uploaded for each case on Documents (`BLK-11`). The filing advocate and their juniors are pre-added as in `FIL-05`. |
| `BLK-06` | **[OWNER]** Once the drafts are created, each case's complainants and advocates can be changed in that case like any other field, as in the e-filing flow. A change to one case does not change the others. |
| `BLK-07` | **[OWNER]** **Case reference** — the filer's own reference for a case (for example a loan account number), unique within the batch. It is stored with the case for the filer to find it by. It is never printed in the complaint, synopsis or any document, and never shown to the court. |
| `BLK-08` | Each case moves on its own. A case that needs fixing waits; the rest of the batch goes ahead. |

# 3. From upload to filing

A batch moves through six steps, in order.

| ID | Step | What happens |
| --- | --- | --- |
| `BLK-10` | **Upload** | The filer enters the batch details (`BLK-05`) and chooses the Excel file. A file that follows the template goes straight to Review; any other layout is matched first (§4.6). Review shows the cases read and the rows discarded (§4.5). **Create batch** creates one draft per case. |
| `BLK-11` | **Documents** | One row per case, each with a slot for every document the case needs, derived from its data as in the e-filing handover §14 (`DCM-1`…`DCM-8`, `DCM-13`). The complainant and advocate documents entered with the batch (`BLK-05`) are already attached to every case. The filer clicks a slot or drags a file onto it; a filled slot can be viewed and replaced. Cases missing a document are listed first. A case's documents lock once it is signed. |
| `BLK-12` | **Case details** | Every open case, with what it still needs. A case opens in the e-filing screens at the first section with something to fix. **Needs fixing**: a required value is missing or invalid; the case waits until it is fixed. **To check**: an e-filing warning (for example `CHQ-10`, `CHQ-11`); the filer can skip it and the case goes ahead. Changes save as the filer types. |
| `BLK-13` | **Review** | Each case as the court will read it: its synopsis and complaint, one at a time. |
| `BLK-14` | **Sign** | The filer chooses the cases to sign, and each signatory signs them together with a method switched on for the state ([`signing-methods.md`](signing-methods.md)). **[OWNER]** The oath is recorded once and applies to every case signed with it (e-filing handover §18.2). |
| `BLK-15` | **Pay** | **[OWNER]** One payment for the chosen cases: one payment gateway transaction. The system generates **a receipt for each case**, each carrying the shared gateway transaction ID. **[OWNER]** Upfront process payments take the defaults of e-filing handover §19.2 for every accused. Each case gets its own case number and is filed when the payment completes. |

# 4. The Excel format

## 4.1 The file

| ID | Requirement |
| --- | --- |
| `BLK-20` | The filer downloads the template from the bulk filing screen. It is generated for the filer's state: its dropdowns carry that state's MDMS values. |
| `BLK-21` | The template has three sheets: **Cases**, where the cases go; **Lists**, holding each dropdown's values; and **Instructions**, describing each column and how repeated sections are numbered (§4.2). |
| `BLK-22` | **Cases**: row 1 holds the column headers (§4.3). Row 2 describes what each column takes — type, format, and when it is required. Row 3 is an example case whose case reference starts with `EXAMPLE`. From row 4, **one row per case**. |
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
| `BLK-27` | A file may carry more instances than the template, numbered the same way (`Cheque 2 amount`); they are read like any other. Anything a case has beyond the file's columns is added on Case details. |
| `BLK-28` | **[OWNER]** **A group is present in a case when any of its cells is filled.** Its required columns then apply. A group with every cell blank is absent. |

## 4.3 Columns

`N` is the instance number (§4.2). Each column takes its field's type, format, list values
and conditions from the [e-filing handover](efiling-handover.md); the template's row 2
states them for the filer. A group's required columns apply only when the group is present
(`BLK-28`).

**Case**

| Header | Field |
| --- | --- |
| Case reference | `BLK-07` |

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
| Accused N person responsible 1 address line | `ACC-18…23` |
| Accused N person responsible 1 address city | `ACC-18…23` |
| Accused N person responsible 1 address pincode | `ACC-18…23` |
| Accused N person responsible 1 police station | `ACC-18…23` |

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

**[OWNER]** Interim relief, final relief and the affidavit each hold the **full, finished
text** for that case, including what fills the blanks of the e-filing handover's §17
templates. These and Additional details are plain text in the sheet; each line break
starts a new paragraph.

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

**In the template:** 1 + 2 × 19 + 11 + 11 + 5 + 4 + 9 = **79 columns**. Each further
instance adds: accused 19, cheque 11, witness 9, person responsible 8, demand notice 11,
accused address 4, witness address 3, other pending case 2.

The system derives the rest, so they have no column: district and state from a pincode;
bank name and branch from an IFSC; the advocate's name from their Bar registration; the
cause of action, filing date and delay (`JUR-9`…`JUR-11`); the fees; the synopsis.

## 4.4 Reading values

| ID | Requirement |
| --- | --- |
| `BLK-30` | Headers are matched ignoring case, spacing and punctuation. Columns can be in any order. Columns that match no field are ignored. |
| `BLK-31` | **Dates** are read from an Excel date, or text as `DD-MM-YYYY` (with `-`, `/` or `.`) or `YYYY-MM-DD`. Text in any other form is invalid. |
| `BLK-32` | **Identifiers** — mobile, pincode, cheque number, account number, IFSC — are read as text, so leading zeros and long account numbers are kept. **Amounts** are numbers; commas are ignored. |
| `BLK-33` | **List values** are matched to the state's values ignoring case, spacing and punctuation. Values that match none go to **Match your values** (§4.6). |
| `BLK-34` | **[OWNER]** **An invalid value is ignored**: the field is left empty. If the field is required, the case is marked **Needs fixing** on Case details. A value in a column that does not apply to the case — a delivery date when the notice was not delivered, an institution type for an individual — is ignored the same way. |
| `BLK-35` | **[OWNER]** **A row with missing or ignored values is still imported**, as a draft with what it has. What it lacks is fixed on Case details. |

## 4.5 Rows

| ID | Requirement |
| --- | --- |
| `BLK-36` | Row 2 (column descriptions) and any row whose case reference starts with `EXAMPLE` are discarded. Blank rows are skipped. Review shows how many rows were discarded. |
| `BLK-37` | `[DERIVED]` A row repeating a case reference already used higher in the file is not imported; Review lists it. |

## 4.6 Files in another layout

A file whose headers do not follow the template — for example a lender's own report — is
matched before Review.

| ID | Requirement |
| --- | --- |
| `BLK-38` | **Match your columns**: each field shows the column matched to it, matched by header name where possible. The filer picks a column for any field, or leaves it to be filled on Case details. A list field can instead take one value for every row. Repeated sections are detected from numbered columns, and the filer can correct how many instances the file holds. |
| `BLK-39` | **Match your values**: each value in a list column that matches none of the state's values is shown, and the filer maps it to one. An unmapped value is invalid (`BLK-34`). |

## 4.7 Uploading again

| ID | Requirement |
| --- | --- |
| `BLK-40` | **[OWNER]** **Uploading an Excel file again replaces the batch's drafts.** Its draft cases, their documents and every change made on Case details are discarded, and a draft is created for every row of the new file. Cases already signed or filed are not touched. Rows are not matched to existing cases. |
