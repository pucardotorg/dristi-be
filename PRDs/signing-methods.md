# Signing Methods

**Status:** v3.11 — 2026-11-20; **a document type disallowing signing options moves to a later version** (`SGM-09`, new §8 Enhancements); `SQ-5`, which asked which options each document type disallows, is removed. Open questions is now §9. v3.10 — 2026-11-20; §3 renamed "Individual signing options". v3.9 — 2026-11-20; **bulk signing is its own section** (new §4, `SGM-15`, new): signing several main files at once, such as several cases or several applications, can be done only with DSC, batch signing or mobile OTP. §3 now covers signing one main file and its documents; the bulk-signing remarks in the `SGM-01`, `SGM-04` and `SGM-13` rows and in §7 move to §4. Later sections renumbered: per state is §5, batch signing §6, Aadhaar e-sign with system-generated signatures §7, open questions §8. v3.8 — 2026-11-20; **§3 is now "Signing options", for any main file submitted with documents** — e-filing (the complaint with documents such as the cheque and vakalatnama), a bail bond with the files given with it, or an application with its attached files; the rows in §3 now say "main file" in place of "complaint" (`SGM-01`, `SGM-02`, `SGM-03`, `SGM-04`, `SGM-13`), and the sentence extending `SGM-03`'s implications to applications and bail bonds is removed, since §3 now covers them. §6 refers to §3 for the main file. v3.7 — 2026-11-20; §4 Gujarat, batch signing: the open point is whether the rules can be changed to support it, matching §3; `SGM-14` confirmed (now `[OWNER]`); the batch signing order in Sources now links the Signatures, Step by Step prototype. v3.6 — 2026-11-20; **Aadhaar e-sign with system-generated signatures is offered in e-filing and in similar situations**, such as documents attached to an application (§6, `SGM-13`); §6, `SGM-14` and `SQ-7` now speak of the **main file** — the complaint in e-filing, or the application when documents are attached to one — and one main file is signed at a time. v3.5 — 2026-11-20; the `[DERIVED]` rule that each signatory's signatures follow the option they used is removed (§4); "Batch signing is switched on per state" removed from §5, since §4 covers it; the batch e-sign proposal is replaced, in Sources and §5.2, by the Signing approach: legal and cryptographic validation note (Google Docs). v3.4 — 2026-11-20; **§4 per-state table filled in** (`SGM-05`): every undecided cell is now "?" with what is known. Gujarat — Aadhaar e-sign alone does not meet the requirements expressed by the Gujarat High Court; the Gujarat High Court has expressed acceptance of Aadhaar e-sign with system-generated signatures and of batch signing, with the rules the open point; it has expressed willingness for mobile OTP, whose rule change is not passed yet. Punjab & Haryana — unclear for every option except DSC. Kerala — "?" for every option except DSC and Aadhaar e-sign alone. v3.3 — 2026-11-20; implications added in §3: **Aadhaar e-sign alone** (`SGM-03`) — the same applies wherever documents are attached to another file and signed with it, such as an application or a bail bond; **batch signing** (`SGM-04`) — it allows bulk signing of every kind of document, including applications. v3.2 — 2026-11-20; **§4 is now one row per signing option, with a column each for Kerala, Gujarat and Punjab & Haryana** (`SGM-05`); a blank cell is not decided yet (`SQ-4`). DSC is on in all three; Aadhaar e-sign alone is on in Kerala. Aadhaar e-sign alone is no longer stated as on in every state. The "Who can use it" column is removed; the mobile OTP roles are kept as a rule under the table. `SQ-4` no longer asks who can use Aadhaar e-sign with system-generated signatures. v3.1 — 2026-11-20; **batch signing and mobile OTP: the open point is whether the rules can be changed** (§3, `SQ-6`): the current rules do not cover batch signing, and whether they can be changed to support it is open; for mobile OTP, whether the rule change can be passed is open, especially in Punjab & Haryana. v3 — 2026-11-20; **restructured around three signature types and the signing options built from them.** New §2 lays out the three signature types — Aadhaar e-sign, DSC and the **system-generated signature** (new term: a signature made with the system's own private key after a confirmation from the person) — with how many signatures each can place in one transaction (`SGM-10`, `SGM-11`, `SGM-12`, new). New §3 lays out the signing options that can be offered in e-filing, with what goes on which document, the implications and the acceptability of each; **mobile OTP is now described as a confirmation that triggers a system-generated signature, not a signature type** (`SGM-01`); **a new option, Aadhaar e-sign with system-generated signatures on the documents** (`SGM-13`, new; e-filing only, one case at a time). Who can use which option is now §4, with the new option added; batch signing is now §5. The statement that the receiving courts and the rules accept batch signing is removed: its legal acceptability is open (`SQ-6`, new). The order of signing for the new option is `SGM-14` (new, `[DERIVED]`); whether the complaint lists the documents' hashes is `SQ-7` (new); who can use the new option is part of `SQ-4`. The line about how the prototype offers the methods is removed. v2.2 — 2026-11-06; **who can use which method** (§3, `SGM-05`): Aadhaar e-sign and DSC are available in every state; mobile OTP and batch signing are switched on per state. Aadhaar e-sign: every signatory. DSC: every user, after a setup whose mechanics are open (`SQ-3`, new). Mobile OTP, where on: complainants and advocates always, the accused once marked present in a hearing. Batch signing, where on: every signatory. A document type can disallow methods (`SGM-09`, new; which ones is `SQ-5`, new). Which states switch on mobile OTP and batch signing is `SQ-4` (new). `signingMethods` and `SQ-1` removed. v2.1 — 2026-11-03; title no longer ends in "Developer & Agent Handover". v2 — 2026-10-24; **digital signing and e-sign are different terms** (§1):
digital signing covers mobile OTP, DSC and Aadhaar e-sign; e-sign means Aadhaar-based
e-signing only, and batch signing is a way of doing it. **Not specific to e-filing**:
each method is described by how many documents one signing transaction covers, which is
how many places its signature can be placed; which documents and which page belong to
the module that signs. Batch signing order corrected (§4.2): fingerprints first, nothing signed;
each signatory signs their own batch certificate with one e-sign; **only after a
signatory's e-sign succeeds** does the system place its own signature for them on every
document, added at the end of the file. The system's signature uses its organisational
certificate and names the signatory; the batch certificate lists each document's name,
length and hash with a batch ID. The batch e-sign proposal's earlier order is
superseded. v1 — 2026-10-24; first version. Signing methods — mobile OTP,
DSC, Aadhaar e-sign and batch signing — each switched on per state; where each places
the signature; how batch signing works.
**Date:** 2026-10-24
**Audience:** developers and agents building signing (front end and backend)

## Sources and precedence

| Source | Provides |
| --- | --- |
| Owner decisions, 2026-10-24, 2026-11-06 and 2026-11-20 | Everything in this document, marked **[OWNER]** |
| [Signatures, Step by Step](https://claude.ai/artifact/KxwHoYNLLgigA79obCin6u) (prototype) | Batch signing order: fingerprints first, each signatory's e-sign, then the signatures on each document |
| [Signing approach: legal and cryptographic validation note](https://docs.google.com/document/d/1522L2gDVwD8cwnDxYudHxB8eP_dl3_fXzoX7S_wMhJQ/edit) | How batch signing works and how a signed document is checked, the cryptographic claims to be tested, where the approach is weakest, and the questions for legal review |

This document owns **which signature types and signing options exist, how each is
switched on, and how many documents each signs in one transaction**. It applies wherever
the system signs. Who signs, which documents are signed, and on which page of a document
the signature sits belong to the module doing the signing — for e-filing,
[`efiling.md`](efiling.md) §18.

Marks: `[DERIVED]` inferred, confirm before building · `[OWNER]` owner decision.

---

# 1. Terms

**[OWNER]** **Digital signing** is the broad term: signing in the system by any of the
signing options in §3. **E-sign** means **Aadhaar-based e-signing** only — one signature
type, not a synonym for digital signing.

**[OWNER]** A **system-generated signature** is a signature made with the system's own
private key. It is not the person's own signature: the system places it only after a
confirmation from the person, such as a mobile OTP they confirm or their Aadhaar e-sign
succeeding.

# 2. Signature types

**[OWNER]** There are three signature types. Every signing option in §3 uses one of them,
or two of them together. The number of signatures one transaction can place is the
number of documents it can sign separately.

| ID | Signature type | Whose key signs | What has to happen first | Signatures in one transaction |
| --- | --- | --- | --- | --- |
| `SGM-10` | **Aadhaar e-sign** | C-DAC, for the person | The person confirms an Aadhaar OTP | **One** |
| `SGM-11` | **DSC** | The person's own Digital Signature Certificate | The person uses their DSC token and PIN | **Many** |
| `SGM-12` | **System-generated signature** | The system's own private key | A confirmation from the person: a mobile OTP they confirm, or their Aadhaar e-sign succeeding | **Many** |

# 3. Individual signing options

**[OWNER]** The signing options are for when several files have to be submitted together:
a **main file** and the **documents** that go with it. For example:

- **E-filing:** the main file is the complaint, which the system generates from the
  details the filer has entered and which includes the affidavit. The documents are every
  additional file filed with it, such as the cheque and the vakalatnama.
- **Bail bond:** the main file is the bail bond; the documents are the other files given
  with it.
- **Application:** the main file is the application; the documents are the files attached
  to it.

**[OWNER]** The options below can be offered for signing one main file and its documents.
Signing several main files at once is §4. Each state chooses which options it accepts
(§5).

| ID | Signing option | Signature types used | What goes on which file | Implications | Acceptability |
| --- | --- | --- | --- | --- | --- |
| `SGM-02` | **DSC** | DSC | A DSC signature on the main file and on each document | Every file carries the person's own signature and can be viewed on its own. Only for people who have a DSC, have set it up in the system (`SQ-3`) and can install and configure the DSC signing software on their computer. The signing software is not guaranteed to work on every operating system. A person can sign only from a computer on which they have set this up | Legally acceptable, but will not always be possible |
| `SGM-03` | **Aadhaar e-sign alone** | Aadhaar e-sign | The main file and all its documents are combined into one PDF, which carries one Aadhaar signature | The signature holds only for the whole combined file. A document shown on its own has no visible signature. The main file viewed without its documents shows the signature as invalid | Accepted in Kerala. Does not meet Gujarat's requirement of a visible signature on every file |
| `SGM-13` | **Aadhaar e-sign with system-generated signatures on the documents** | Aadhaar e-sign and system-generated signature | An Aadhaar signature on the main file; a system-generated signature on each document (§7) | Every file carries a signature and can be viewed on its own. The documents are covered by a system-generated signature, not by an Aadhaar signature. | Meets the functional requirements of every state. Whether the rules accept it is open (`SQ-6`) |
| `SGM-04` | **Batch signing** | Aadhaar e-sign and system-generated signature | An Aadhaar signature on a separate batch certificate that lists every file; a system-generated signature on the main file and on each document (§6) | Every file carries a signature and can be checked against the batch certificate. No filed file carries the Aadhaar signature itself: it is on the batch certificate, an extra document (`SQ-2`). | Cryptographically sound and highly secure. The current rules do not cover it; whether they can be changed to support it is open (`SQ-6`) |
| `SGM-01` | **Mobile OTP** | System-generated signature | A system-generated signature on the main file and on each document, once the person confirms an OTP sent to their mobile | No Aadhaar or DSC signature is behind any file | Gujarat has expressed interest in it; it would meet all of Gujarat's functional requirements. It needs a change in the rules. Whether that change can be passed is open, especially in Punjab & Haryana (`SQ-6`) |

# 4. Bulk signing

**[OWNER]** **Bulk signing** is signing several main files at once, each with its
documents: for example, several cases or several applications.

- `SGM-15` **[OWNER]** Bulk signing can be done only with DSC (`SGM-02`), batch signing
  (`SGM-04`) or mobile OTP (`SGM-01`), where the state has that option on (§5). Aadhaar
  e-sign alone (`SGM-03`) and Aadhaar e-sign with system-generated signatures (`SGM-13`)
  sign one main file at a time.
- With batch signing, one e-sign covers the files of every main file being signed: one
  batch certificate lists them all (§6).

# 5. Signing options per state — `SGM-05`

**[OWNER]** Each state switches each signing option in §3 on or off. A question mark is
not decided yet (`SQ-4`).

| Signing option | Kerala | Gujarat | Punjab & Haryana |
| --- | --- | --- | --- |
| DSC (`SGM-02`) | On | On | On |
| Aadhaar e-sign alone (`SGM-03`) | On | ?<br>Does not meet the requirements expressed by the Gujarat High Court | ?<br>Unclear what their expectation is |
| Aadhaar e-sign with system-generated signatures (`SGM-13`) | ? | ?<br>The Gujarat High Court has expressed acceptance; whether the rules allow it is the question | ?<br>Unclear |
| Batch signing (`SGM-04`) | ? | ?<br>The Gujarat High Court has expressed acceptance; whether the rules can be changed to support it is not known | ?<br>Unclear |
| Mobile OTP (`SGM-01`) | ? | ?<br>The Gujarat High Court has expressed willingness to get this done; the rule change is not passed yet | ?<br>Unclear |

- **[OWNER]** Where mobile OTP is on, complainants and advocates can always use it; the
  accused can use it once they have been marked present in a hearing of the case.

- Where more than one option is available to a signatory, they choose among them when
  they sign.

# 6. Batch signing — `SGM-04`

C-DAC's e-sign accepts one document per OTP. Batch signing lets a signatory authorise
any number of documents with **one** e-sign: each document carries a **system-generated
signature** — one for each signatory, naming them — and each signatory's own Aadhaar
signature is on their batch certificate.

## 6.1 What is in a batch

The documents being signed, each kept as its own PDF — from one case, or from several
cases the signatory selects together.

## 6.2 How it works

| Step | What happens |
| --- | --- |
| 1 | The system takes each document's **fingerprint**: its length in bytes and its SHA-256. **Nothing is signed yet** |
| 2 | Each signatory reviews the documents. **Each gets their own batch certificate**: one PDF with a **batch ID**, listing every document's **name, length and hash**. It can list documents across cases. All signatories' certificates list the same documents |
| 3 | Each signatory signs their own batch certificate with **one Aadhaar e-sign**. The order in which signatories sign does not matter |
| 4 | **Only once a signatory's e-sign succeeds**, the system places a system-generated signature on every document for that signatory: a PAdES signature with the system's **organisational document signer certificate**, added as an incremental update. The visible box reads "Sealed by [court system name] on [date, time] IST / Signed by [name as per Aadhaar] / Batch certificate [ID]". With two signatories, every document ends up with two separate system-generated signatures, each checked on its own |
| 5 | The documents go on (are filed, or delivered) only once **every** signatory has signed |

Each signature is added at the **end** of the file; the original bytes at the start are
untouched, so the file still matches the fingerprint in every batch certificate. Anyone
can check it with one command: `head -c <length> <file> | shasum -a 256`, using the length
the batch certificate lists, and see that the hash is on the certificate. The batch ID
in the document's signature box must match the batch certificate.

How a signed document is checked, the cryptographic claims to be tested, timestamps and
key handling: [Signing approach: legal and cryptographic validation note](https://docs.google.com/document/d/1522L2gDVwD8cwnDxYudHxB8eP_dl3_fXzoX7S_wMhJQ/edit).

## 6.3 Rules

- `SGM-06` **The system places no signature on a document before that signatory's e-sign
  succeeds.** If a signatory's e-sign fails or is abandoned, nothing carries a signature
  for them.
- `SGM-07` **The original bytes never change after step 1** — no stamp, no annotation, no
  re-saving; signatures are only added at the end of the file. If a document changes or
  is withdrawn, fingerprints are taken again and every signatory signs again.
- `SGM-08` **The documents go on only once every signatory has signed** (step 5). Enforce
  server-side.

# 7. Aadhaar e-sign with system-generated signatures — `SGM-13`

**[OWNER]** Offered where the state switches it on (§5). The signatory signs the main
file (§3) with one Aadhaar e-sign, and the system places a system-generated signature on
each of its documents.

- `SGM-14` **[OWNER]** The system places no system-generated signature on a document
  before that signatory's Aadhaar e-sign on the main file succeeds. If the e-sign fails
  or is abandoned, no document carries a signature for them.

Whether the main file lists each document's name and hash, so that the signatory's
Aadhaar signature refers to the documents it authorises, is open (`SQ-7`).

# 8. Enhancements

- `SGM-09` In a later version, a document type can disallow some signing options. A
  disallowed option is not offered for that document, even where the state has it on and
  the signatory could otherwise use it.

# 9. Open questions

| ID | Question | Blocking |
| --- | --- | --- |
| `SQ-2` | Whether each batch certificate is filed with the documents it lists, or kept by the system and produced on request | Batch signing |
| `SQ-3` | How a user sets up their DSC before signing with it, and what signing with it then involves | DSC |
| `SQ-4` | Which signing options each state switches on: the cells marked "?" in §5 | Per state, before that state goes live |
| `SQ-6` | Whether each state's rules accept Aadhaar e-sign with system-generated signatures; and whether each state's rules can be changed to support batch signing and mobile OTP | Each of those options, per state |
| `SQ-7` | Whether the main file signed with Aadhaar (§7) lists each document's name and hash when the documents carry system-generated signatures | Aadhaar e-sign with system-generated signatures |
