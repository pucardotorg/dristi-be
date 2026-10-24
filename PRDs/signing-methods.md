# Signing Methods — Developer & Agent Handover

**Status:** v2 — 2026-10-24; **digital signing and e-sign are different terms** (§1):
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
| Owner decisions, 2026-10-24 | Everything in this document, marked **[OWNER]** |
| [`../../signing/signatures-step-by-step.html`](../../signing/signatures-step-by-step.html) | Batch signing order: fingerprints first, each signatory's e-sign, then the signatures on each document |
| [`../../signing/batch-esign-proposal.md`](../../signing/batch-esign-proposal.md) | C-DAC request and response, the batch certificate, timestamps and key handling (Part 2). **Its order of signing (§1.3, §2.3) is superseded** — the system does not sign before the e-sign |
| Dristi app prototype, `apps/dristi-app/src/components/filing/sign-flow-dialog.tsx` | The signing choice as a signatory sees it |

This document owns **which methods exist, how each is switched on, and how many
documents each signs in one transaction**. It applies wherever the system signs. Who
signs, which documents are signed, and on which page of a document the signature sits
belong to the module doing the signing — for e-filing,
[`efiling-handover.md`](efiling-handover.md) §18.

Marks: `[DERIVED]` inferred, confirm before building · `[OWNER]` owner decision.

---

# 1. Digital signing and e-sign

**[OWNER]** **Digital signing** is the broad term: signing in the system by any of the
methods in §2. **E-sign** means **Aadhaar-based e-signing** only — one digital signing
method, not a synonym for digital signing. Batch signing is a way of doing an e-sign.

# 2. The methods — `SGM`

**[OWNER]** The number of documents one signing transaction can cover is the number of
places the signature can be placed. A method that signs every document in one
transaction places its signature on every document; a method that signs one document per
transaction places it once.

| ID | Method | How the signatory signs | Documents per transaction | Where the signature goes |
| --- | --- | --- | --- | --- |
| `SGM-01` | **Mobile OTP** | An OTP is sent to the signatory's mobile; once they confirm it, the system places their signature | Any number | On **every document** |
| `SGM-02` | **DSC** | The signatory's own Digital Signature Certificate (token and PIN) | Any number | On **every document** |
| `SGM-03` | **Aadhaar e-sign** | C-DAC Aadhaar OTP | **One** | **Once.** Where several documents are signed together they are combined into one PDF, and the one signature covers all of them |
| `SGM-04` | **Batch signing** — a way of doing an Aadhaar e-sign | One e-sign per signatory, on their own batch certificate (§4) | Any number | On **every document**: once a signatory's e-sign succeeds, the **system's own signature** goes on each document — one for that signatory, naming them and their batch certificate |

The enabled methods are offered together under digital signing, as in the prototype
("Aadhaar OTP" / "My DSC").

# 3. Switching methods on — `SGM-05`

**[OWNER]** Methods are switched on **per state**: `signingMethods`, the list of methods
enabled for the state. Only enabled methods are offered.

- Where more than one is enabled, each signatory chooses among them when they sign.
- `[DERIVED]` Each signatory's signature is placed according to the method **they** used.
  Where several people sign the same documents, one using DSC signs every document while
  one using Aadhaar e-sign signs once.

# 4. Batch signing — `SGM-04`

C-DAC's e-sign accepts one document per OTP. Batch signing lets a signatory authorise
any number of documents with **one** e-sign.

**[OWNER]** The receiving courts accept documents signed this way, and the rules permit
it: each document carries the **system's signature** — one for each signatory, naming
them — and each signatory's own Aadhaar signature is on their batch certificate.

## 4.1 What is in a batch

The documents being signed, each kept as its own PDF — from one case, or from several
cases the signatory selects together.

## 4.2 How it works

| Step | What happens |
| --- | --- |
| 1 | The system takes each document's **fingerprint**: its length in bytes and its SHA-256. **Nothing is signed yet** |
| 2 | Each signatory reviews the documents. **Each gets their own batch certificate**: one PDF with a **batch ID**, listing every document's **name, length and hash**. It can list documents across cases. All signatories' certificates list the same documents |
| 3 | Each signatory signs their own batch certificate with **one Aadhaar e-sign**. The order in which signatories sign does not matter |
| 4 | **Only once a signatory's e-sign succeeds**, the system signs every document for that signatory: a PAdES signature with the system's **organisational document signer certificate**, added as an incremental update. The visible box reads "Sealed by [court system name] on [date, time] IST / Signed by [name as per Aadhaar] / Batch certificate [ID]". With two signatories, every document ends up with two separate system signatures, each checked on its own |
| 5 | The documents go on (are filed, or delivered) only once **every** signatory has signed |

Each signature is added at the **end** of the file; the original bytes at the start are
untouched, so the file still matches the fingerprint in every batch certificate. Anyone
can check it with one command: `head -c <length> <file> | shasum -a 256`, using the length
the batch certificate lists, and see that the hash is on the certificate. The batch ID
in the document's signature box must match the batch certificate.

C-DAC request and response, batch certificate layout, timestamps and key handling:
[`batch-esign-proposal.md`](../../signing/batch-esign-proposal.md) Part 2 (not its
order of signing).

## 4.3 Rules

- `SGM-06` **The system places no signature on a document before that signatory's e-sign
  succeeds.** If a signatory's e-sign fails or is abandoned, nothing carries a signature
  for them.
- `SGM-07` **The original bytes never change after step 1** — no stamp, no annotation, no
  re-saving; signatures are only added at the end of the file. If a document changes or
  is withdrawn, fingerprints are taken again and every signatory signs again.
- `SGM-08` **The documents go on only once every signatory has signed** (step 5). Enforce
  server-side.

# 5. Open questions

| ID | Question | Blocking |
| --- | --- | --- |
| `SQ-1` | Which methods each state enables (`signingMethods`) | Per state, before that state goes live |
| `SQ-2` | Whether each batch certificate is filed with the documents it lists, or kept by the system and produced on request | Batch signing |
