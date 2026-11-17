# Case File

**Status:** v15 — 2026-11-17; §6.2 renamed **Format** and marked as not yet validated with users; each state has its own format, held as configuration, so a state can reorder its sections without a code change; the court settings are configuration too. **Vakalatnamas** added to it after Bail bonds, with the orders linked to each (12 in Gujarat, 11 in Punjab & Haryana and Kerala); the sections after it move down one; `Q-6` answered and removed. §2 intro says each state has its own format and court settings, both configuration. v14 — 2026-11-17; under each application, the documents submitted with it now come before the objection (`CFL-03`, §6.2, §1, §1.1). Recorded statements are four separate kinds: Evidence of the complainant, Witness deposition, Plea and Examination of the accused (§1); `Q-3` answered and removed. `Q-4` (automatic marking) removed: it belongs to evidence-marking.md. v13 — 2026-11-17; only documents in five categories can be marked as evidence: original filing documents, affidavits, documents submitted with an application, recorded statements and other documents, as the §1 table already showed (new §1.2, `CFL-22`, Exhibits in §1); the reason: marking may need an order, and orders cannot be linked to orders. §1.1 is now Linking to orders. `CFL-25` (no other action is offered in the case file) withdrawn to dropped-ideas.md. **Marking as evidence** is now a section of its own (new §4, `CFL-22`, `CFL-24`), and downloading a single document or several (new `CFL-26`) moves to Downloading, now §5, noting that some states may turn it off on the citizen side; `Q-5` now also covers the format of the index; `CFL-23` (both actions on documents only) withdrawn to dropped-ideas.md. Configuration by state is now §6, Open questions §7. v12 — 2026-11-17; **viewing the case file** moved here from view-case.md §6.1–§6.4 as new §3, unchanged in substance: the index (`DET-09`, `DET-10`, `DET-13` → `CFL-16`–`CFL-18`), what each document shows (`DET-14`, `DET-15` → `CFL-19`, `CFL-20`), viewing a document as PDF or data, with the owner's reason (`DET-11` → `CFL-21`), and the actions on documents (`DET-12`, `DET-16`–`DET-18` → `CFL-22`–`CFL-25`). Later sections renumbered: Downloading §4, Configuration by state §5, Open questions §6. `CFL-16` (an index that shows the selected document) and `CFL-17` (headings two levels deep) then withdrawn to dropped-ideas.md, as §2 sets the structure and `CFL-21` covers opening a document; `CFL-18` (the case file opens on the first document) withdrawn too, leaving where it opens to the UI, and the §3.1 Index heading removed; §3.2–§3.4 are now §3.1–§3.3. `CFL-23` now says sections or sub-sections, not headings. `CFL-19` (Name) links to the titles set by document-submission `DSB-23` and order-generation `TIT-07`, and adds the case file's own: "Order: " with the title and date, "Document attached: " for documents submitted with an application or bail bond, and the date on a payment receipt. `CFL-20` (a document's number: its exhibit number, otherwise a system identifier) withdrawn to dropped-ideas.md, as a document's number is its place in the case file (§2) with any exhibit number beside it (`CFL-09`). v11 — 2026-11-17; downloading the whole case file moved here from view-case.md (`DET-19`, `DET-20`): as individual files in a zip, or as a single PDF that a court can choose not to offer (new `CFL-14`, `CFL-15`); the pages in §3.1 are added only to the single PDF. v10 — 2026-11-16; `CFL-02` reworded: documents are in the order they came into the case unless the PRD says otherwise, and filing documents follow the filing's order; no longer framed as always adding at the end. `CFL-02` no longer states that a document's number never changes; `CFL-09` no longer describes later-marked exhibits sorting between earlier ones (no sub-numbers such as Exh-5/1), nor how exhibits are referred to. `CFL-13` (an exhibit number never changes) withdrawn to dropped-ideas.md, with `Q-7`: the court may want to edit exhibit numbers. `CFL-06` now gives its reason. `CFL-07` reworded to lead with the condition. v9 — 2026-11-16; §1 Orders: possible overlap noted, as an order linked to documents is also shown under each of them. v8 — 2026-11-16; a bail bond shows the documents submitted with it, before the orders linked to it (§1, §1.1, §4.2). v7 — 2026-11-16; an order can now also be linked to the complaint, vakalatnamas, processes and payment receipts (§1, §1.1); linking to an application or a process also associates the order with what sits under it, which cannot be linked directly; the starting format shows orders under the complaint, each process and each payment receipt (§4.2), and Vakalatnamas will too (`Q-6`). v6 — 2026-11-16; new §1.1, the categories an order can be linked to, as a list (any document can be marked as evidence), replacing the note under §1; new `CFL-13`: an exhibit number never changes once allotted; new `Q-7`, to confirm with the courts that numbers never change. v5 — 2026-11-16; **how the case file is ordered** (new §2, `CFL-01`–`CFL-09`): sections in the order the state sets, documents numbered under them in the order filed, linked documents one level below, a copy in every place a document belongs, objections only under their application, sub-sections for Orders and Exhibits, Exhibits by exhibit number. **Downloading** (new §3, `CFL-10`–`CFL-12`): same format as on screen; sections and kinds of linked document can be left out for one download, with no renumbering; the pages generated on download are now §3.1. **Configuration by state** (new §4): two court settings and the starting format, without Vakalatnamas for now. `Q-1` and `Q-2` answered and removed; new `Q-6`. v4 — 2026-11-16; Index removed from the categories (§1), which are renumbered 1–15; it is a page generated on download (§2). v3 — 2026-11-16; new §2, the pages generated only when the case file is downloaded: the index, the cover page for the case file, and a cover page for each document or section; open questions move to §3. v2 — 2026-11-16; added `Q-5`: the cover pages of the case file and of each section or document are not yet covered. v1 — 2026-11-16; started afresh: the categories of documents that make up the case file, what each can be linked to (orders only to original filing documents, affidavits, applications, recorded statements, bail bonds, other documents and exhibits), and where a document can appear in more than one category (§1). The order of the categories and the format of the case file are not yet decided. v0 — 2026-11-04; placeholder, not written yet.
**Audience:** developers and agents building the case file

The case file: the documents that make up a case, how they are assembled, ordered and
shown to the court and the parties.

---

# 1. Categories

Every document in the case file falls under one of these categories. The table is not
the order of the case file; that is set for each state (§2, §6).

**Can be linked to** lists only the links that may or may not exist on a given case, such as
between an application and the order that decides it, so that linked documents can be shown
together. Fixed associations, such as a complaint and its original filing documents, or an exhibit
and the document marked, are not listed.

| # | Category | What goes in it | Can be linked to | Possible overlaps |
| --- | --- | --- | --- | --- |
| 1 | Synopsis | The generated synopsis | — | — |
| 2 | Complaint | The original complaint | Orders | — |
| 3 | Original filing documents | All documents filed with the complaint, except the vakalatnama, affidavits and the delay condonation application, which go into their own categories (4, 5 and 6) | Orders | Exhibits (15): a filing document once marked |
| 4 | Vakalatnamas | All vakalatnamas, including one filed with the complaint | Orders | — |
| 5 | Affidavits | Affidavits filed with the complaint, and documents submitted directly with the type Affidavit | Orders | Exhibits (15), once marked |
| 6 | Applications | Pending and disposed, including a delay condonation application filed with the complaint | The documents submitted with it; the objections raised against it; the orders passed on it | Exhibits (15): an attachment once marked |
| 7 | Orders | Published orders only: both normal orders and, in Punjab & Haryana, Zimni orders ([`order-generation.md`](order-generation.md) §5.3). The judgment and Roznama-type orders are not included: they go in Judgment (8) and Roznamas (9) | Any document whose row in this table lists orders | Orders linked to other documents: each is also shown under every document it is linked to (`CFL-04`) |
| 8 | Judgment | The judgment order, shown on its own when there is one | Same as orders (7) | — |
| 9 | Roznamas | In Gujarat, both Roznama-type orders and the Roznamas of normal orders | A Roznama-type order cannot be linked to documents ([`order-generation.md`](order-generation.md) `OTY-06`) | — |
| 10 | Recorded statements | Four separate kinds of document: **Evidence of the complainant**, **Witness deposition**, **Plea** and **Examination of the accused** | Orders | Exhibits (15), once marked |
| 11 | Processes | Notices, summons, warrants, proclamations, attachments and custom processes | Its execution reports; orders | — |
| 12 | Bail bonds | Bail bonds | The documents submitted with it; orders | — |
| 13 | Payment receipts | All payment receipts | Orders | — |
| 14 | Other documents | Directly submitted documents that don't belong in any other category, including memos and Evidence-type submissions | Orders | Exhibits (15), once marked |
| 15 | Exhibits | Any document from a category in §1.2 that has been marked as evidence, whether marked by hand or automatically by a state's rule when some other action happens | — | Every exhibit is also in its original category |

## 1.1 Linking to orders

An order can be linked only to documents in these categories. These links decide where the
order is shown in the case file (§2). Nothing else can be linked to an order, but the order's
text can still refer to any document on the case, such as the synopsis or the judgment.

An order linked to an application is associated through it with the documents submitted
with the application and its objection; an order linked to a bail bond, with the documents
submitted with the bond; an order linked to a process, with the process's execution reports.
Those cannot be linked to an order directly.

| # | Category an order can be linked to |
| --- | --- |
| 2 | Complaint |
| 3 | Original filing documents |
| 4 | Vakalatnamas |
| 5 | Affidavits |
| 6 | Applications |
| 10 | Recorded statements |
| 11 | Processes |
| 12 | Bail bonds |
| 13 | Payment receipts |
| 14 | Other documents |
| 15 | Exhibits |

## 1.2 Marking as evidence

In this version, only documents in these categories can be marked as evidence
([`evidence-marking.md`](evidence-marking.md)). *Marking a document as evidence may itself
need an order; if orders could be marked, orders would have to be linked to orders.*

| # | Category whose documents can be marked as evidence |
| --- | --- |
| 3 | Original filing documents |
| 5 | Affidavits |
| 6 | Applications: the documents submitted with an application |
| 10 | Recorded statements |
| 14 | Other documents |

# 2. How the case file is ordered

The case file is shown on screen and downloaded in the same **format**: the sections in
order, the sub-sections of a section, and the kinds of linked document shown under each
document. Each state has its own format and court settings, both held as configuration (§6).

| ID | Requirement |
| --- | --- |
| `CFL-01` | The case file is a list of **sections**, numbered 1, 2, 3 … in the order the state's format sets. Each section is one category from §1. A category that is not in the state's format is not shown. |
| `CFL-02` | The **documents in a section** are numbered under it: 4.1, 4.2, 4.3 … Unless this PRD says otherwise, they are in the order they came into the case; documents filed with the complaint follow the order the filing gives them. Exhibits are ordered differently (`CFL-09`). Synopsis, Complaint and Judgment each hold one document, which takes the section's own number. |
| `CFL-03` | **Linked documents.** Under each document come the documents linked to it, numbered one level below it: 4.1.1, 4.1.2 … The format sets which kinds of linked document a section shows, and in what order. For example, under each application: the documents submitted with it, then the objection raised against it, then the orders passed on it. Within one kind, linked documents are in the order filed. All the kinds are numbered in one run, so an application with one submitted document, an objection and two orders has them at 6.1.1 to 6.1.4. |
| `CFL-04` | **Copies.** A document is shown in every place it belongs. An order linked to two documents is shown under each of them, and again under Orders. A download can leave copies out (`CFL-11`). |
| `CFL-05` | **Objections.** An objection is shown only under the application it objects to. Although it is an application type ([`application-lifecycle.md`](application-lifecycle.md) `ALC-37`), it is not shown on its own under Applications. |
| `CFL-06` | **Orders** is split into two sub-sections: **Orders linked to other documents**, the orders with at least one linked document, and **Independent orders**, the orders with none. *This keeps apart the orders that are also shown under the documents they are linked to (`CFL-04`), and gives the orders shown nowhere else a section of their own.* |
| `CFL-07` | Where the state marks evidence separately by party (§6.1), **Exhibits** is split into three sub-sections: **Evidence of the complainant**, **Evidence of the accused** and **Other evidence**. Otherwise it is one section. |
| `CFL-08` | Sub-sections are numbered under their section (7.1, 7.2) in the order the format sets, and their documents one level below (7.1.1, 7.1.2 …). |
| `CFL-09` | **Exhibits** holds every document that has an exhibit number, in exhibit-number order, within each sub-section where it is split. Wherever else a marked document is shown, its exhibit number is shown beside it, for example *4.1 Cheque 1 (Exh. 5)*. |

# 3. Viewing the case file

The case file is shown on the case ([`view-case.md`](view-case.md) §6).

## 3.1 Each document shows

| ID | Field | Detail |
| --- | --- | --- |
| `CFL-19` | Name | The document's title, as set by the PRD that owns it: [`document-submission.md`](document-submission.md) `DSB-23` for documents filed with the complaint, applications and what is submitted with them, documents submitted directly and depositions; [`order-generation.md`](order-generation.md) `TIT-07` for orders. In the case file, an order is named **"Order: "** followed by its title and its date, for example *Order: Rescheduling of hearing date, 18/02/2026*; a document submitted with an application or a bail bond is named **"Document attached: "** followed by its title; and a payment receipt shows its date. |

## 3.2 Viewing a document

| ID | Requirement |
| --- | --- |
| `CFL-21` | Every document can be viewed as its PDF. A document generated from form data — the complaint filed in e-filing, an application — can also be viewed as **data**: what was entered in the form that produced the PDF. The user can switch between the two. |

**[OWNER]** Why the data view: the user entered data, and the system turned it into a PDF.
Showing the data directly is better than making the reader get it back out of the PDF. This
is the start of a move away from reading cases as PDFs.

# 4. Marking as evidence

| ID | Requirement |
| --- | --- |
| `CFL-22` | **Mark as Evidence** is offered on documents in the case file, on the court side, to holders of the Evidence marker role ([`court-roles.md`](court-roles.md)). Only documents in the categories listed in §1.2 can be marked; how marking works is set by [`evidence-marking.md`](evidence-marking.md). |
| `CFL-24` | The user can select several documents and mark them as evidence together. |

# 5. Downloading

The case file is downloaded from the case ([`view-case.md`](view-case.md) `ACT-01`).

| ID | Requirement |
| --- | --- |
| `CFL-26` | Any single document in the case file can be downloaded, on the court side and the citizen side. The user can also select several documents and download them together. *Some states may turn off downloading on the citizen side.* |
| `CFL-14` | The whole case file can be downloaded **as individual files**, in one zip file. Each document is downloaded as it is held, so the digital signatures on it stay valid. |
| `CFL-15` | It can also be downloaded **as a single PDF**, with the pages in §5.1 added. The original digital signatures may no longer show as valid in this PDF. A court can choose not to offer this option; the case file is then downloaded only as individual files. |
| `CFL-10` | The downloaded case file follows the same format and numbering as the case file on screen. |
| `CFL-11` | Before downloading, the person can leave out any section, any sub-section, or any kind of linked document: for example, Orders linked to other documents, or the orders under each original filing document. The choice applies to that download only and changes nothing for anyone else. |
| `CFL-12` | Leaving something out does not renumber the rest. Every document keeps the number it has on screen, and the numbers of what was left out are missing from the download. |

## 5.1 Pages generated on download

These pages are generated only when the case file is downloaded as a single PDF (`CFL-15`). They are not documents in the case file.

| # | Page | What it is |
| --- | --- | --- |
| 1 | Index | The index of the case file |
| 2 | Cover page for the case file | One cover page for the case file as a whole |
| 3 | Cover pages for documents or sections | A cover page for each document or section |

# 6. Configuration by state

## 6.1 Court settings

| Setting | What it changes | Gujarat | Punjab & Haryana | Kerala |
| --- | --- | --- | --- | --- |
| Roznama exists as a separate document | Roznamas is a section only where this is Yes | Yes | No | No |
| Evidence is marked separately by party | Exhibits is split into three sub-sections only where this is Yes (`CFL-07`) | No | No | Yes |

## 6.2 Format

*Not yet validated with users; it will change.*

Each state has its own format, held as configuration. A state can change the order of its
sections, sub-sections and kinds of linked document, for example to put Orders last, without
a code change. The court settings (§6.1) are configuration too, set for each state.

| Section | Number in Gujarat | Number in Punjab & Haryana and Kerala | Sub-sections, in order | Linked to each document, in order |
| --- | --- | --- | --- | --- |
| Synopsis | 1 | 1 | — | — |
| Roznamas | 2 | Not shown | — | — |
| Complaint | 3 | 2 | — | Orders linked to it |
| Original filing documents | 4 | 3 | — | Orders linked to it |
| Affidavits | 5 | 4 | — | Orders linked to it |
| Applications | 6 | 5 | — | Documents submitted with it; the objection raised against it; orders passed on it |
| Orders | 7 | 6 | Orders linked to other documents; Independent orders | — |
| Judgment | 8 | 7 | — | — |
| Recorded statements | 9 | 8 | — | Orders linked to it |
| Processes | 10 | 9 | — | Its execution reports; orders linked to it |
| Bail bonds | 11 | 10 | — | Documents submitted with it; orders linked to it |
| Vakalatnamas | 12 | 11 | — | Orders linked to it |
| Exhibits | 13 | 12 | In Kerala only: Evidence of the complainant; Evidence of the accused; Other evidence | Orders linked to it |
| Other documents | 14 | 13 | — | Orders linked to it |
| Payment receipts | 15 | 14 | — | Orders linked to it |

# 7. Open questions

| ID | Question | Blocking |
| --- | --- | --- |
| `Q-5` | **Pages generated on download, not yet covered** (§5.1). (1) The cover page for each section or document. (2) The cover page for the case file as a whole. (3) The format of the index. | No |
