# Case File

**Status:** v9 — 2026-11-16; §1 Orders: possible overlap noted, as an order linked to documents is also shown under each of them. v8 — 2026-11-16; a bail bond shows the documents submitted with it, before the orders linked to it (§1, §1.1, §4.2). v7 — 2026-11-16; an order can now also be linked to the complaint, vakalatnamas, processes and payment receipts (§1, §1.1); linking to an application or a process also associates the order with what sits under it, which cannot be linked directly; the starting format shows orders under the complaint, each process and each payment receipt (§4.2), and Vakalatnamas will too (`Q-6`). v6 — 2026-11-16; new §1.1, the categories an order can be linked to, as a list (any document can be marked as evidence), replacing the note under §1; new `CFL-13`: an exhibit number never changes once allotted; new `Q-7`, to confirm with the courts that numbers never change. v5 — 2026-11-16; **how the case file is ordered** (new §2, `CFL-01`–`CFL-09`): sections in the order the state sets, documents numbered under them in the order filed, linked documents one level below, a copy in every place a document belongs, objections only under their application, sub-sections for Orders and Exhibits, Exhibits by exhibit number. **Downloading** (new §3, `CFL-10`–`CFL-12`): same format as on screen; sections and kinds of linked document can be left out for one download, with no renumbering; the pages generated on download are now §3.1. **Configuration by state** (new §4): two court settings and the starting format, without Vakalatnamas for now. `Q-1` and `Q-2` answered and removed; new `Q-6`. v4 — 2026-11-16; Index removed from the categories (§1), which are renumbered 1–15; it is a page generated on download (§2). v3 — 2026-11-16; new §2, the pages generated only when the case file is downloaded: the index, the cover page for the case file, and a cover page for each document or section; open questions move to §3. v2 — 2026-11-16; added `Q-5`: the cover pages of the case file and of each section or document are not yet covered. v1 — 2026-11-16; started afresh: the categories of documents that make up the case file, what each can be linked to (orders only to original filing documents, affidavits, applications, recorded statements, bail bonds, other documents and exhibits), and where a document can appear in more than one category (§1). The order of the categories and the format of the case file are not yet decided. v0 — 2026-11-04; placeholder, not written yet.
**Audience:** developers and agents building the case file

The case file: the documents that make up a case, how they are assembled, ordered and
shown to the court and the parties.

---

# 1. Categories

Every document in the case file falls under one of these categories. The table is not
the order of the case file; that is set for each state (§2, §4).

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
| 6 | Applications | Pending and disposed, including a delay condonation application filed with the complaint | The orders passed on it; the objections raised against it; the documents submitted with it | Exhibits (15): an attachment once marked |
| 7 | Orders | Published orders only: both normal orders and, in Punjab & Haryana, Zimni orders ([`order-generation.md`](order-generation.md) §5.3). The judgment and Roznama-type orders are not included: they go in Judgment (8) and Roznamas (9) | Any document whose row in this table lists orders | Orders linked to other documents: each is also shown under every document it is linked to (`CFL-04`) |
| 8 | Judgment | The judgment order, shown on its own when there is one | Same as orders (7) | — |
| 9 | Roznamas | In Gujarat, both Roznama-type orders and the Roznamas of normal orders | A Roznama-type order cannot be linked to documents ([`order-generation.md`](order-generation.md) `OTY-06`) | — |
| 10 | Recorded statements | Evidence of the complainant and other witness depositions, the plea, and the accused's examination | Orders | Exhibits (15): a deposition once marked |
| 11 | Processes | Notices, summons, warrants, proclamations, attachments and custom processes | Its execution reports; orders | — |
| 12 | Bail bonds | Bail bonds | The documents submitted with it; orders | — |
| 13 | Payment receipts | All payment receipts | Orders | — |
| 14 | Other documents | Directly submitted documents that don't belong in any other category, including memos and Evidence-type submissions | Orders | Exhibits (15), once marked |
| 15 | Exhibits | Any document from another category that has been marked as evidence, whether marked by hand or automatically by a state's rule when some other action happens | — | Every exhibit is also in its original category |

## 1.1 Linking and marking

An order can be linked only to documents in these categories. These links decide where the
order is shown in the case file (§2). Nothing else can be linked to an order, but the order's
text can still refer to any document on the case, such as the synopsis or the judgment.

An order linked to an application is associated through it with the application's objection
and the documents submitted with it; an order linked to a bail bond, with the documents
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

Any document in the case file can be marked as evidence, whatever its category
([`evidence-marking.md`](evidence-marking.md) `DSB-12`).

# 2. How the case file is ordered

The case file is shown on screen and downloaded in the same **format**: the sections in
order, the sub-sections of a section, and the kinds of linked document shown under each
document. Each state has its own format (§4).

| ID | Requirement |
| --- | --- |
| `CFL-01` | The case file is a list of **sections**, numbered 1, 2, 3 … in the order the state's format sets. Each section is one category from §1. A category that is not in the state's format is not shown. |
| `CFL-02` | The **documents in a section** are numbered under it: 4.1, 4.2, 4.3 … They are in the order they were filed, and a new document is always added at the end, so the number of a document already in the case file never changes. Exhibits are ordered differently (`CFL-09`). Synopsis, Complaint and Judgment each hold one document, which takes the section's own number. |
| `CFL-03` | **Linked documents.** Under each document come the documents linked to it, numbered one level below it: 4.1.1, 4.1.2 … The format sets which kinds of linked document a section shows, and in what order. For example, under each application: the objection raised against it, then the documents submitted with it, then the orders passed on it. Within one kind, linked documents are in the order filed. All the kinds are numbered in one run, so an application with an objection, one submitted document and two orders has them at 6.1.1 to 6.1.4. |
| `CFL-04` | **Copies.** A document is shown in every place it belongs. An order linked to two documents is shown under each of them, and again under Orders. A download can leave copies out (`CFL-11`). |
| `CFL-05` | **Objections.** An objection is shown only under the application it objects to. Although it is an application type ([`application-lifecycle.md`](application-lifecycle.md) `ALC-37`), it is not shown on its own under Applications. |
| `CFL-06` | **Orders** is split into two sub-sections: **Orders linked to other documents**, the orders with at least one linked document, and **Independent orders**, the orders with none. |
| `CFL-07` | **Exhibits** is split into three sub-sections, **Evidence of the complainant**, **Evidence of the accused** and **Other evidence**, where the state marks evidence separately by party (§4.1). Otherwise it is one section. |
| `CFL-08` | Sub-sections are numbered under their section (7.1, 7.2) in the order the format sets, and their documents one level below (7.1.1, 7.1.2 …). |
| `CFL-09` | **Exhibits** holds every document that has an exhibit number, in exhibit-number order, within each sub-section where it is split. Wherever else a marked document is shown, its exhibit number is shown beside it, for example *4.1 Cheque 1 (Exh. 5)*. A document marked later can sort before earlier ones (in Gujarat, Exh-5/1 comes straight after Exh-5), moving the exhibits after it down by one; an exhibit is referred to by its exhibit number, not its position in Exhibits. |
| `CFL-13` | **An exhibit number never changes** once it is allotted. Like a document's number in the case file (`CFL-02`), it stays the same for as long as the case file exists. |

# 3. Downloading

| ID | Requirement |
| --- | --- |
| `CFL-10` | The downloaded case file follows the same format and numbering as the case file on screen. |
| `CFL-11` | Before downloading, the person can leave out any section, any sub-section, or any kind of linked document: for example, Orders linked to other documents, or the orders under each original filing document. The choice applies to that download only and changes nothing for anyone else. |
| `CFL-12` | Leaving something out does not renumber the rest. Every document keeps the number it has on screen, and the numbers of what was left out are missing from the download. |

## 3.1 Pages generated on download

These pages are generated only when the case file is downloaded. They are not documents in the case file.

| # | Page | What it is |
| --- | --- | --- |
| 1 | Index | The index of the case file |
| 2 | Cover page for the case file | One cover page for the case file as a whole |
| 3 | Cover pages for documents or sections | A cover page for each document or section |

# 4. Configuration by state

## 4.1 Court settings

| Setting | What it changes | Gujarat | Punjab & Haryana | Kerala |
| --- | --- | --- | --- | --- |
| Roznama exists as a separate document | Roznamas is a section only where this is Yes | Yes | No | No |
| Evidence is marked separately by party | Exhibits is split into three sub-sections only where this is Yes (`CFL-07`) | No | No | Yes |

## 4.2 Starting format

The same format for every state for now. Vakalatnamas is not in it yet (`Q-6`). Where a
section is not shown, the sections after it take the next numbers.

| Section | Number in Gujarat | Number in Punjab & Haryana and Kerala | Sub-sections, in order | Linked to each document, in order |
| --- | --- | --- | --- | --- |
| Synopsis | 1 | 1 | — | — |
| Roznamas | 2 | Not shown | — | — |
| Complaint | 3 | 2 | — | Orders linked to it |
| Original filing documents | 4 | 3 | — | Orders linked to it |
| Affidavits | 5 | 4 | — | Orders linked to it |
| Applications | 6 | 5 | — | The objection raised against it; documents submitted with it; orders passed on it |
| Orders | 7 | 6 | Orders linked to other documents; Independent orders | — |
| Judgment | 8 | 7 | — | — |
| Recorded statements | 9 | 8 | — | Orders linked to it |
| Processes | 10 | 9 | — | Its execution reports; orders linked to it |
| Bail bonds | 11 | 10 | — | Documents submitted with it; orders linked to it |
| Exhibits | 12 | 11 | In Kerala only: Evidence of the complainant; Evidence of the accused; Other evidence | Orders linked to it |
| Other documents | 13 | 12 | — | Orders linked to it |
| Payment receipts | 14 | 13 | — | Orders linked to it |

# 5. Open questions

| ID | Question | Blocking |
| --- | --- | --- |
| `Q-3` | **Recorded statements.** Confirm what the category covers: evidence of the complainant and other witness depositions, the plea, and the accused's examination. | No |
| `Q-4` | **Automatic marking.** Which states mark a document as evidence automatically, on which actions, and with which number? No PRD defines such a rule yet; [`evidence-marking.md`](evidence-marking.md) covers marking by hand only. | No |
| `Q-5` | **Cover pages, not yet covered.** (1) The cover page for each section or document. (2) The cover page for the case file as a whole. | No |
| `Q-6` | **Vakalatnamas, to be added** to the format (§4.2) as a section of its own, after Original filing documents, with the orders linked to each vakalatnama. | No |
| `Q-7` | **Fixed numbers.** Confirm with the courts that a document's number in the case file (`CFL-02`) and its exhibit number (`CFL-13`) never change once given. Courts may want to correct or renumber them. | No |
