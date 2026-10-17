# Bulk Filing — Problem Statement

**Status:** v1.2 — 2026-09-23. §3.6 adds backend-lookup fields (Bar registration, IFSC,
pincode) alongside MDMS. §3.7 and Appendix B correct the Aadhaar note against the
handover's actual §14 decision — masking is settled (none at launch), only storage design
is open, and neither is bulk-specific. §4.3 now presents three signing methods (upload,
DSC, Aadhaar batch e-sign per the [batch e-sign proposal](../signing/batch-esign-proposal.md))
instead of DSC-only. Appendix D (fees) removed — out of scope here; owned by the e-filing
handover §19. Appendix A gets a note on where its "Cond." column flattens the handover's
`[DERIVED]` markers (`ACC-16`, `ACC-17`, `JUR-11`). Illustrative batch size in §2, §3.7,
§4.2, §5 and §7 brought down from 1,000 to **500** — owner does not yet know if 1,000 is
realistic; Gujarat's 1,000/day figure (§1, §8 Q4) is a separate, factual number and is
unchanged. **Pending:** the §2 "complex case" composition (institution + PoA pairing) and
a cheque-composition point are still open from the owner's last round of comments.
v1.1 — 2026-09-17; moved into `handovers/` and internal links repointed. Text
unchanged from v1 (2026-09-16, first issue). Problem definition only; no solution proposed.
**Date:** 2026-09-16
**Audience:** whoever designs and builds bulk filing — product, design, engineering, or an
external team taking this on
**Scope:** s.138 NI Act cheque dishonour complaints, filed through DRISTI

---

## 0. How to read this

This document states a problem. It does not answer it.

Section 1 to 8 describe what has to be solved and how big it is. **Appendix A to D carry
the complete specification** — every field, every condition, every document, every derived
value, every fee head. That detail is unreadable as an introduction, which is why it sits
at the back. Read the front for the shape of the problem; go to the back when you need to
know exactly what a case contains.

Where this document states a field, it carries the field ID from the
[e-filing handover](efiling-scrutiny-registration-handover.md) — `LIT-3`,
`CHQ-9`, `DCM-9` and so on. That handover owns the field-level truth. If the two disagree,
the handover wins and this document is wrong; tell us.

**What this is not.** It is not a design, a template, a file format, or an API contract.
An earlier internal sketch of one possible solution exists and is deliberately kept out of
this brief so it does not anchor the answer. It can be shared on request, after you have
formed your own view.

**What must not be invented.** Anything marked *(open)* here is genuinely undecided. Do not
resolve it by picking an answer and building on it quietly. Raise it.

---

## 1. The problem

Today a complaint is filed one at a time. A person opens the filing flow, works through
ten screens, uploads the documents, signs, pays, and submits. That is the only way in.

For most filers that is correct. For some it is unusable:

- A bank or NBFC advocate in **Gujarat** files **1,000+ cases a day**. Cheque dishonour is
  the bulk of the caseload, the complainant is the same institution every time, and the
  advocate is the same person every time. Only the borrower, the cheque and the notice
  change.
- The same advocate's cases are already sitting in the bank's own recovery system as
  structured data. They are re-typed into our form by hand, case by case.
- Even a small practice filing 5 to 20 cases in a week is doing the same work 20 times over
  for two complainants who never change.

The ask is a second way in: **submit many complaints in one operation**, and have each one
arrive in the court as a complete, lawful, individually-registrable case.

### The hard requirement

**A case filed in bulk must be indistinguishable from a case filed individually.**

Not similar. Identical. The same fields populated, the same documents attached, the same
generated complaint PDF, the same synopsis, the same affidavit, the same signature status,
the same payment record, the same case state. A scrutiny officer opening it must not be
able to tell how it arrived, and must not need to.

This single requirement is what makes the problem hard, and it rules out the easy answers.
There is no reduced dataset for bulk filers, no "we'll fill the rest in later", no relaxed
validation, no second definition of a complete case. Everything the form collects, a bulk
submission must also collect, and everything the form checks, a bulk submission must also
pass.

---

## 2. How big a case is

To size the problem: below is what one single complaint needs before it can be filed.

**Counting convention:** a "value" is something the filer must supply. Values the system
derives — district and state from a pincode, bank name and branch from an IFSC, the
advocate's name from their Bar registration, the cause-of-action date, the filing date,
the delay duration, the fee bill — are excluded. An address counts as 3 values (line,
city, pincode), not 5.

| | Simplest possible case | A complex but ordinary case |
|---|---|---|
| Complainants | 1 individual, no PoA | 1 institution + 1 individual with a PoA holder |
| Accused | 1 individual, 1 address | 2 individuals + 1 company with 2 persons responsible |
| Cheques | 1 | 4 |
| Demand notices | 1, delivered | 2, one undelivered |
| Witnesses | 0 | 2 |
| Delay condonation | No | Yes |
| **Mandatory values to supply** | **~40** | **~140** |
| **Documents to attach** | **6–8** | **20–25+** |

A 500-case batch is therefore on the order of **20,000 to 70,000 data values and 3,000
to 12,500 files**, submitted in one operation, each of which must be individually valid.

Three pre-populated rich-text blocks — the affidavit, the interim relief prayer and the
final relief prayer — also exist per case. They are editable, and some filers will want to
edit them.

Appendix A lists every field. Appendix B lists every document.

---

## 3. Why this is not "upload a spreadsheet"

The instinct is: export the data to a table, upload the table, done. The instinct is wrong,
or at least badly incomplete, for the reasons below. Each of these is a property of the
case, not of our current implementation — none of them can be removed by simplifying the
form.

### 3.1 A field's mandatoriness depends on other fields

Very few fields are always required. Most are required *given* something else:

- `LDN-8` **Reason for non-delivery** is mandatory — but only when the demand notice was
  not delivered (`LDN-5` = No). When it was delivered, supplying it is an error.
- `LDN-11` **Amount already paid** is mandatory when `LDN-10` = Part Payment, and
  meaningless otherwise.
- `JUR-12` **Reason for condonation of delay** is mandatory when the complaint is filed
  more than one calendar month after the cause of action — a date the filer does not
  compute and cannot see, because the system derives it (Appendix C).
- `JUR-2` **IFSC of the complainant's branch** is required only when the complainant
  deposited the cheque themselves (`JUR-1` = Yes). When they did not, a different field
  entirely — `JUR-6a`, the drawer's bank police station — is required instead.

So "is this row complete?" cannot be answered field by field. It can only be answered by
evaluating the whole record against the condition tree.

### 3.2 A field's *existence* depends on other fields

Stronger than the above: some fields are not merely optional, they are **not available**,
and supplying them is a contradiction rather than an excess.

- A complainant is **Individual or Institution** (`LIT-2`). Choose Individual and you get
  name, age, gender, personal addresses, and a Power of Attorney question. Choose
  Institution and all of those disappear, replaced by institution type, institution name,
  registered address, and a complete authorised-representative block with its own name,
  age, phone, designation and address. That is **17 fields on the Individual side including
  the PoA holder, 13 on the Institution side, and almost nothing in common between them.**
- The same branch exists for the accused (`ACC-1`), with a different field set again, and
  with an institution type list that includes a value the complainant's list does not.
- `CHQ-4` **Bank details same as previous cheque?** does not exist on the first cheque. It
  exists on the second onward, and when it is Yes, three further fields are carried
  forward rather than collected.
- Advocate details are **hard-gated** (`FIL-01`): the section is locked until every
  complainant record is complete and valid. And if every complainant is a party-in-person,
  the section does not apply at all and the advocate count is forced to zero.

A flat table has a column for every field on both sides of every branch. Most of them are
blank on any given row, and blank means two different things — "not applicable" and "not
filled" — which the validator must be able to tell apart.

### 3.3 Sections repeat, and repeats nest inside repeats

A case is not a record. It is a small tree:

```
Case
├── Complainant 1..n          (each Individual or Institution)
│   ├── PoA holder            (0 or 1, only for an Individual — 7+ more values)
│   └── Authorised rep        (exactly 1, only for an Institution — 9+ more values)
├── Advocate 1..n             (each mapped to one or more complainants)
├── Accused 1..n              (each Individual or Institution)
│   ├── Address 1..n          (process fees are charged per address)
│   └── Person responsible 1..n   (only for an Institution; each becomes a separate accused)
├── Cheque 1..n
├── Demand notice 1..n
├── Witness 0..n
│   └── Address 1..n
└── Other pending case 0..n
```

Every branch here is genuinely variable. There is no "usually one" that can be hard-coded.
Note in particular:

- **Multiple cheques in one complaint.** The complaint fee slab applies to the *sum* of all
  cheque amounts, so the number of cheques changes the money.
- **Multiple addresses per accused.** Summons is served at each selected address and
  charged per address per round, so the number of addresses changes the money.
- **Persons responsible for a company** (s.141) are entered inside the accused record, and
  then **each one becomes a separate accused later in the flow** — with their own summons,
  their own addresses, and their own share of the process fee.
- **Multiple demand notices**, each with its own delivery outcome, and the earliest
  resulting cause-of-action date is the one that governs limitation for the whole case.

Any bulk representation has to carry this tree, not flatten it.

### 3.4 Records point at each other

Within a case, records are cross-referenced and cross-validated:

- `ADV-2` maps each advocate to the specific complainants they represent. The mapping then
  drives who must sign (§4.3) and what is charged.
- `LIT-3` a complainant's phone number must not equal **any other** complainant's, accused's,
  advocate's or PoA holder's number in the same case — a check across four different record
  types.
- The date chain (Appendix C) runs across cheque records, notice records and derived
  values, and `LDN-2` must be on or after the return date of **at least one** cheque, not
  all of them.

These are not field formats. They are checks over the assembled case, and they can only run
once the whole case is present.

### 3.5 Some values must not be supplied at all

Several fields are computed and uneditable: the **cause-of-action date** (`JUR-9`), the
**filing date** (`JUR-10`), the **duration of delay** (`JUR-11`), the synopsis, and the fee
bill. A bulk submission that accepts these from the filer would let a filer state their own
limitation position. It must not. See Appendix C.

### 3.6 Controlled vocabularies

Around ten fields take their values from a court-maintained master list (MDMS): institution
types for complainants and for accused (two different lists), cheque return reasons, nature
of debt, mode of service, reason for non-delivery, and police stations — plus the district
and state lists behind every address. A bulk submission has to express these values in a way
that matches the master exactly, and stay correct when the master changes.

A separate set of fields isn't matched against a static list at all — it has to resolve
against a live backend record. `ADV-3` **Bar registration number** must match an actual
advocate in the Bar Council database; there is no value a filer can just type that passes
without that lookup succeeding, and the lookup is also what supplies `ADV-4`, the advocate's
name. The IFSC lookups (`CHQ-5`, `JUR-2`) and the pincode-to-district/state resolution behave
the same way. A bulk submission has to run these lookups too, not just validate against a
bundled MDMS snapshot.

### 3.7 It is not only data — the documents are half the problem

Each case carries **6 to 25+ files**, and the required set is not fixed. It is *derived from
the data*:

- one cheque image and one return memo **per cheque** (`DCM-1`, `DCM-2`)
- one notice copy and one dispatch proof **per demand notice** (`DCM-3`, `DCM-4`)
- one Aadhaar card **per complainant** (`DCM-9`)
- one Aadhaar card and one authorisation **per PoA holder** (`DCM-10`, `DCM-11`)
- proof of reasons for delay **only if there is delay** (`DCM-8`) — which the system
  computes, so the filer may not know they need it until after validation
- a reply to the notice **only if a reply was received** (`DCM-6`)

So the system cannot state what files it wants until the data is in and validated; and the
data cannot be confirmed complete until the files are in. That ordering problem is real and
the design has to resolve it.

At batch scale the volume is the second problem: a 500-case batch is thousands of files
and, depending on scan quality, **multiple gigabytes** in one submission. Any design in
which a single failure at 95% means starting again is not a design.

**Aside, not a third problem.** Many of these files are ID cards (`DCM-9`/`DCM-10`, usually
Aadhaar). Masking is already decided for the individual flow — none at launch, the card is
stored and shown exactly as uploaded because the scrutiny officer has to be able to read it,
and no field ever collects the number itself. The only open item is *storage design*
(`DCM`, marked `[GAP]`), and that gap is the same size whether a case arrived alone or in a
batch of 500. It is not a problem this document is asking bulk filing to solve.

---

## 4. What has to happen after the data is in

Getting the cases into the system as validated drafts is roughly half the problem. Each
draft then has to become a *filed* case, and three steps stand between those states. All
three are built around a single case and a person sitting in front of it.

For each, our current thinking is recorded below. **It is thinking, not a decision.** If the
design that comes back disagrees with it and is better, we would rather have the better one.

### 4.1 Verifying the complainants' mobile numbers

**How it works individually.** Every complainant (or their PoA holder) is a required
signatory (`SIG-03`). In e-sign mode each of them logs in with the phone number entered for
them, which proves the number and creates their account if they do not have one. In
upload-a-signed-copy mode each of them confirms by phone OTP instead. Either way **the
verified phone number is the identity check**, and it happens per complainant, per case.

**Why it does not survive contact with bulk.** A thousand cases filed by a bank have the
same complainant a thousand times. Verifying that institution's number a thousand times is
not a safeguard, it is a thousand SMS messages to one phone.

**Our current thinking:**

- If the complainant is the **logged-in user**, they are already authenticated. Nothing more
  should be needed.
- If the same complainant appears across the whole batch — the usual institutional case —
  **one verification for the batch** may be enough.
- If an **advocate** is filing and there is an **already established link** between that
  advocate and that complainant in the system, that link may itself be sufficient and no
  re-verification is needed.

**What the design has to settle:** what "an established link" is and where it comes from
(vakalatnama? a prior case? an explicit authorisation?); what happens when a batch contains
complainants the filer has no link to; whether a verification is scoped to the batch, to the
advocate–complainant pair, or to a time window; and what a complainant who is *not* the
filer sees, since in the individual flow this step is how they learn a case exists in their
name and get an account. *(open)*

### 4.2 Payment

**How it works individually.** One case, one bill, one gateway transaction. The bill has
several filing fee heads plus process fees charged per accused, per address, per round —
fee detail is out of scope here; it belongs to the
[e-filing handover](efiling-scrutiny-registration-handover.md) §19.

**Our current thinking.** This is the least troubling of the three. The system should be
able to **club the whole batch into a single amount and make one request to the payment
gateway**. One transaction reference comes back, that reference is recorded against every
case in the batch, and **a separate payment receipt is generated per case** — because each
case needs its own receipt as an individually filed case would have.

**What the design still has to settle:** what happens when the payment succeeds but some
cases in the batch have failed for another reason, and vice versa; whether a batch can be
part-paid; how a refund is handled when it is owed on one case out of 500; and how this
meets the resubmission rule (`LIFE-12`), where a corrected case is re-billed individually
and the balance collected — which is a per-case payment arriving after a batch payment.
*(open)*

### 4.3 Signing

**How it works individually.** Aadhaar e-sign through C-DAC, or uploading an already-signed
copy (§4.1). Aadhaar e-sign's binding constraint is that C-DAC's current endpoint
(**eSign v2.1**) accepts **exactly one document per OTP**. An advocate with 500 filings
would face 500 OTPs. That is not a scaling inconvenience; it is a wall.

**Three methods for bulk, none chosen yet:**

1. **Upload a signed document** — the same upload-a-signed-copy mode, for the whole batch.
2. **DSC-based signing.** Server-side, with **pyHanko** (open source), against the filer's
   **Digital Signature Certificate**, which has no per-document ceiling — one DSC session
   signs the batch. Not new ground: **DSC-based bulk signing already ships** for judicial
   output today — judges sign many orders in one PIN session through a desktop utility
   driving a USB token ([context](../docs/dristi-solutions-context.md), §8b). Solved for
   token holders; unsolved specifically for Aadhaar.
3. **Aadhaar-based batch e-sign.** One Aadhaar OTP signs a **batch certificate** listing
   every application's fingerprint, and the system fixes a signature derived from that
   certificate onto each individual application. This is Method 1 of the
   [batch e-sign proposal](../signing/batch-esign-proposal.md), which specifies the
   mechanics in full.

Method 3 is the one that still needs its own design: **what the flow is** (where the
Aadhaar step sits in the batch's lifecycle, who triggers it), and **how the complainant's
mobile number is verified** within it — the advocate's OTP authenticates the advocate, not
the complainant, and that's the same open question as §4.1, from the signing side.

**What the design has to settle, regardless of method:**

- `SIG-03` requires **every complainant (or their PoA holder) *and* one advocate for each
  complainant** to sign. An advocate's signature, by any method, does not discharge the
  complainant's. Whose signature covers what, and what happens to the complainant's
  required signature in a batch, is unresolved and is the most important question in this
  section. *(open, blocking)*
- `SIG-04` requires all parties on a case to use the **same** signing mode. Does a batch fix
  the mode for every case in it? *(open)*
- `LIFE-13`: **any edit to a case invalidates all its signatures.** In a batch, a correction
  to one case must not invalidate the other 999 — but the rule has only ever been written
  for a single case. *(open)*
- A clerk **cannot e-sign** (`ROLE-08`), and this is enforced server-side. A clerk preparing
  a batch for an advocate is the likely real-world pattern. *(open)*
- Whether the DSC lives on a USB token at the filer's desk (as with judges) or elsewhere,
  and what that means for a server-side signing step.

---

## 5. What happens to a batch afterwards

A batch is an entry method. It is **not** a thing the court knows about. After filing, there
is no batch — there are N independent cases, and everything downstream treats them
individually. This is the direct consequence of §1's hard requirement, and it has
consequences of its own.

- **Scrutiny is per case.** A scrutiny officer opens each one, marks defects on it, and
  sends it back on its own. 500 cases filed together can produce 500 separate correction
  tasks over the following weeks.
- **Correction is per case, and it reopens only part of the case.** When a scrutiny officer
  marks errors, only the marked fields unlock (`REF-01`). When a **magistrate** sends a case
  back, everything unlocks (`REF-02`). When a marked field is an interlinked date, every
  **transitive downstream** date unlocks with it (`REF-03`).
- **Correction re-triggers signing and possibly payment.** Editing invalidates signatures
  (`LIFE-13`), so the case is re-signed; if the recalculated fee is higher, the balance is
  collected before it returns to scrutiny (`LIFE-12`).
- **Delay condonation can attach while a case sits in correction.** `REF-04` is evaluated
  against the clock **at refiling**, never cached. A batch whose corrections sit for weeks
  can silently acquire a delay condonation requirement — a new mandatory field, a new
  document, a new fee head, and a notice round — case by case, at different times.

So: does a bulk filer get any bulk handling of the *return* path — correcting 40 sent-back
cases without opening 40 flows — or is that acceptably rare? We do not know. *(open)*

### The filing moment

Limitation under s.138 runs from the moment the complaint is **electronically received in
the Registry, in IST**. Portal failure is not a ground to extend it. For a single filing
that moment is unambiguous.

For a batch it is not. Is a case received when the data is uploaded, when it passes
validation, when it is signed, or when payment completes? A 2 GB upload that takes an hour,
or a validation cycle that takes a day, sits across that question — and for a case filed on
the last day of limitation, the answer decides whether it is in time. **This must be
answered explicitly and defensibly, not inherited by accident from whatever the
implementation happens to do.** *(open, blocking)*

---

## 6. Constraints

Things the answer must respect. These are not preferences.

| # | Constraint | Why |
|---|---|---|
| 1 | The resulting case is **identical** to an individually filed case — data, documents, generated PDF, signatures, payment record, state | §1 |
| 2 | **One set of validation rules**, shared with the individual flow, not a parallel implementation | Two implementations will diverge, and the divergence will be discovered by a court |
| 3 | Derived values (cause of action, filing date, delay, synopsis, fee bill) are **computed, never accepted** from the filer | Appendix C; a filer must not be able to assert their own limitation position |
| 4 | **Per-case independence.** One bad case must not block the other 999, and one correction must not disturb them | §5 |
| 5 | **Aadhaar Act s.29** — minimise, never display, never print the number | §3.7 |
| 6 | **DPDP** and the court's access rules apply to the whole batch, at rest and in transit | Thousands of people's identity documents in one upload |
| 7 | Role and scope rules are unchanged: access is by **association with the case**, and clerks cannot e-sign, enforced server-side | `ROLE-01`…`ROLE-08` |
| 8 | Court fee amounts come from the court's fee master, not from anything hard-coded | [E-filing handover](efiling-scrutiny-registration-handover.md) §19 |

---

## 7. What is deliberately left open

We are not specifying these. They are the design.

- **The submission mechanism.** An API for institutions whose systems already hold the data;
  a file-based upload for everyone else; both; something else. Most institutional filers can
  produce structured data programmatically, and most small practices cannot.
- **How the data is represented** — the tree in §3.3 has to be carried somehow. We have not
  decided how, and a spreadsheet is one candidate among several, not the answer.
- **How repetition is avoided.** The same complainant, advocate and jurisdiction basis in
  500 cases should not be typed 500 times. How that is expressed is open.
- **How files arrive and are matched to cases**, including whether a filer's existing file
  names can be used rather than imposed.
- **Supporting utilities.** Something that helps a filer name, organise and check files
  before submitting, and validate a batch locally before it is sent, would be valuable. What
  it is, and whether it runs on their machine or ours, is open.
- **Error reporting and the correction loop** — how a filer with 12 bad cases out of 859
  learns which 12, why, and what the cheapest path to fixing them is.
- **Batch size limits, resumability, and throughput.**
- **What the filer sees while a batch is processing**, and afterwards.

---

## 8. Questions we cannot answer for you — and need answered

| # | Question | Blocking |
|---|---|---|
| 1 | `SIG-03` requires every complainant *and* an advocate per complainant to sign. How is the complainant's signature discharged in a DSC-signed batch? | **Yes** |
| 2 | When is a bulk-filed complaint "electronically received in the Registry" for limitation purposes? (§5) | **Yes** |
| 3 | Who may bulk file? All filing roles, or advocates and institutional filers only? A clerk prepares but cannot sign (`ROLE-08`) — how does that split work across a batch? | **Yes** |
| 4 | Maximum batch size. Gujarat's 1,000/day — is that one batch or several? | **Yes** |
| 5 | How is mobile verification satisfied for complainants who are not the filer? (§4.1) | **Yes** |
| 6 | Does the return path (scrutiny send-backs) need bulk handling, or is case-by-case correction acceptable? (§5) | No |
| 7 | Upload size and infrastructure limits; is resumable upload available? | No |
| 8 | Aadhaar storage and masking at batch scale — the individual flow's `[GAP]` still stands | No |
| 9 | Is a mobile-OTP batch signing mode actually coming, and when? It changes what is worth building now | No |
| 10 | Can a batch mix complainants, or courts, or must it be homogeneous? | No |

---

---

# Appendix A — Complete field specification

Every field a case can contain. Field IDs are from the
[e-filing handover](efiling-scrutiny-registration-handover.md), which owns this
detail; go there for migration notes, tooltips and source traces.

**Reading the "Required" column:** *Yes* = always mandatory within the record it belongs to.
*Cond.* = mandatory only when the condition in the last column holds. *No* = optional.
*Auto* = supplied by the system, never by the filer.

**A gap in this restating, not in the field set.** Every ID below matches the handover's
field tables one for one — nothing is missing. But the handover marks a few conditions
`[DERIVED]` — inferred, not yet confirmed — and that marking doesn't survive into the
"Cond." column here: `ACC-16`/`ACC-17` (institution representative mobile/email) and the
"earliest cause-of-action date across multiple notices" rule under `JUR-11` read as settled
below when the handover itself still flags them as open. Treat this appendix's phrasing as
inherited, not independently confirmed, on those three.

### A.0 The address composite

One definition, used everywhere an address appears. **Police station is not part of it** —
it is a separate field, present only where a section specifies it.

| Sub-field | Type | Required | Notes |
|---|---|---|---|
| Line 1 | Text | Yes | |
| City / Town | Text | Yes | |
| Pincode | Number, 6 digits | Yes | |
| District | Dropdown | Auto | Derived from pincode |
| State | Dropdown | Auto | Derived from pincode |

**Address pairing order**, wherever two addresses appear together: permanent address, then
"is the current address the same as the permanent address?", then current address — shown
only when the answer is No.

### A.1 Complainant — `LIT` (repeats per complainant)

Branches on Individual vs Institution. Only one branch's fields exist for a given record.

| ID | Field | Type | Required | Condition / logic |
|---|---|---|---|---|
| LIT-1 | Representing yourself as a Party-in-Person? | Radio Y/N | Yes | Forced **No and disabled for complainant 1 when an advocate is filing** |
| LIT-2 | Complainant type | Radio Individual / Institution | Yes | Branches everything below |
| **Individual branch** ||||
| LIT-3 | Phone number | Phone | Yes | Must not equal any other complainant, accused, advocate or PoA phone in the case. Entering the advocate's number is an error |
| LIT-4 | Full name | Text, alphabetic | Yes | Auto-filled only when the filer is filing for themselves |
| LIT-5 | Age | Number, positive integer | Yes | |
| LIT-5a | Gender | Male / Female / Other | No | |
| LIT-5b | Differently abled? | Radio Y/N | No | |
| LIT-6 | Email | Email | No | |
| LIT-7 | Permanent address | Address (A.0) | Yes | |
| LIT-8 | Current address same as permanent? | Radio Y/N | Yes | |
| LIT-9 | Current address | Address (A.0) | Cond. | LIT-8 = No |
| LIT-10 | Has this litigant transferred Power of Attorney? | Radio Y/N | Yes | Individual only |
| **PoA holder sub-record** — exists only when LIT-10 = Yes ||||
| LIT-11 | PoA holder phone | Phone | Cond. | LIT-10 = Yes; same uniqueness rule as LIT-3 |
| LIT-12 | PoA holder full name | Text | Cond. | LIT-10 = Yes |
| LIT-13 | PoA holder age | Number, positive integer | Cond. | LIT-10 = Yes |
| LIT-13a | PoA holder email | Email | No | LIT-10 = Yes |
| LIT-14 | PoA holder permanent address | Address (A.0) | Cond. | LIT-10 = Yes |
| LIT-15 | PoA current same as permanent? | Radio Y/N | Cond. | LIT-10 = Yes |
| LIT-16 | PoA holder current address | Address (A.0) | Cond. | LIT-15 = No |
| **Institution branch** ||||
| LIT-17 | Type of institution | Dropdown (MDMS) | Cond. | LIT-2 = Institution |
| LIT-18 | Institution name | Text | Cond. | LIT-2 = Institution |
| LIT-19 | Institution contact phone | Phone | No | |
| LIT-20 | Institution contact email | Email | No | |
| LIT-21 | Institution address | Address (A.0) | Cond. | LIT-2 = Institution |
| LIT-22 | Authorised representative phone | Phone | Cond. | LIT-2 = Institution |
| LIT-23 | Authorised representative full name | Text | Cond. | LIT-2 = Institution |
| LIT-24 | Authorised representative age | Number | Cond. | LIT-2 = Institution |
| LIT-24a | Authorised representative gender | Male / Female / Other | No | |
| LIT-24b | Authorised representative differently abled? | Radio Y/N | No | |
| LIT-25 | Authorised representative email | Email | No | |
| LIT-25a | Authorised representative designation | Text | Cond. | LIT-2 = Institution |
| LIT-26 | Authorised representative address | Address (A.0) | Cond. | LIT-2 = Institution |
| **Both branches** ||||
| LIT-27 | Party-in-Person affidavit | Rich text, pre-populated, editable | Cond. | LIT-1 = Yes |

### A.2 Advocate — `ADV` (repeats per advocate)

**Hard-gated:** locked until every complainant record is complete and valid (`FIL-01`).
Absent entirely when every complainant is a Party-in-Person.

| ID | Field | Type | Required | Condition / logic |
|---|---|---|---|---|
| ADV-1 | Number of advocates | Stepper, integer ≥ 0 | Yes | Must equal advocates added. **Forced 0 and disabled when all complainants are PiP.** The filing advocate and their junior advocates are auto-added (juniors removable); for a filing clerk, the advocates they work for are auto-added the same way |
| ADV-2 | Advocate for | Multi-select of non-PiP complainants | Yes | Defaults to all non-PiP complainants. Drives signing (`SIG-03`) and fees |
| ADV-3 | Bar registration number | Search / dropdown | Yes | Looked up against the Bar Council database |
| ADV-4 | Advocate full name | Text | Auto | From ADV-3; **not editable** |

### A.3 Accused — `ACC` (repeats per accused)

| ID | Field | Type | Required | Condition / logic |
|---|---|---|---|---|
| ACC-1 | Accused type | Radio Individual / Institution | Yes | Branches below |
| ACC-2 | Full name | Text, alphabetic | Cond. | Individual |
| ACC-3 | Age | Number, integer ≥ 1 | No | Individual |
| ACC-4 | Type of institution | Dropdown (MDMS) | Cond. | Institution. **List includes values not offered to complainants** |
| ACC-5 | Company name | Text | Cond. | Institution |
| ACC-6 | Contact mobile number | Phone | Cond. | Both types; may be skipped only under the declaration below |
| ACC-7 | Contact email | Email | Cond. | Both types; may be skipped only under the declaration below |
| ACC-8…12 | Address | Address (A.0) — **repeatable, 1..n** | Yes | At least one. **Process fees are charged per address** |
| ACC-13 | Police station | Dropdown (MDMS) | No | Per address |
| ACC-24 | Resides within the court's jurisdiction? | Radio Y/N | Yes | Informational — no effect on the flow; the magistrate decides |
| **Person responsible for the institution (s.141)** — repeatable, only when ACC-1 = Institution. **Each person later appears as a separate accused.** ||||
| ACC-14 | Representative full name | Text | Cond. | Institution |
| ACC-15 | Representative designation | Text | No | Institution |
| ACC-16 | Representative mobile | Phone | Cond. | Institution |
| ACC-17 | Representative email | Email | Cond. | Institution |
| ACC-18…23 | Representative address (+ optional police station) | Address (A.0) | Cond. | Institution |

**Missing contacts.** When the filer has neither phone nor email for an accused, they may
proceed only by explicitly declaring they do not know them. The declaration is recorded as
data; **nothing is added to the case file.**

### A.4 Cheque — `CHQ` (repeats per cheque)

| ID | Field | Type | Required | Condition / logic |
|---|---|---|---|---|
| CHQ-1 | Date on cheque | Date | Yes | As written on the cheque |
| CHQ-2 | Amount | Number, positive | Yes | As written on the cheque. **The complaint fee slab applies to the sum across all cheques** |
| CHQ-3 | Cheque number | Number, 6 digits | Yes | First six digits printed at the bottom |
| CHQ-4 | Bank details same as previous cheque? | Radio Y/N, default No | Cond. | **Does not exist on cheque 1.** When Yes, CHQ-5/6/7 are carried forward |
| CHQ-5 | IFSC code | Text | Cond. | Required unless CHQ-4 = Yes. Lookup fires automatically on a valid IFSC |
| CHQ-6 | Bank name | Text | Auto | From CHQ-5, or carried from the previous cheque |
| CHQ-7 | Bank branch | Text | Auto | From CHQ-5, or carried from the previous cheque |
| CHQ-7a | Bank account number | Text | Yes | As on the cheque |
| CHQ-8 | Date of presentation / deposit | Date | Yes | **Must be ≥ CHQ-1** |
| CHQ-9 | Date of return | Date | Yes | **Must be ≥ CHQ-8.** As on the return memo |
| CHQ-10 | Return reason | Dropdown (MDMS) | Yes | **Warning** — not an error — when it is not "Insufficient Funds" |

### A.5 Legal demand notice — `LDN` (repeats per notice)

| ID | Field | Type | Required | Condition / logic |
|---|---|---|---|---|
| LDN-1 | Nature of debt or liability | Dropdown (MDMS) | Yes | |
| LDN-2 | Date of dispatch | Date | Yes | **At least one cheque's CHQ-9 must be on or before this date** |
| LDN-3 | Mode of service | Dropdown (MDMS) | Yes | |
| LDN-4 | Tracking number | Text | No | |
| LDN-5 | Whether delivered? | Radio Y/N | Yes | Branches below |
| LDN-6 | Date of delivery | Date | Cond. | LDN-5 = Yes; must be ≥ LDN-2 |
| LDN-7 | Date of return | Date | Cond. | LDN-5 = No; must be ≥ LDN-2 |
| LDN-8 | Reason for non-delivery | Dropdown (MDMS) | Cond. | LDN-5 = No |
| LDN-9 | Has the accused replied? | Radio Y/N | Yes | A Yes makes `DCM-6` available |
| LDN-10 | Has the drawer made full or part payment? | Part Payment / No Payment Made | Yes | |
| LDN-11 | How much has already been paid? | Number | Cond. | LDN-10 = Part Payment |

### A.6 Jurisdiction and limitation — `JUR`

| ID | Field | Type | Required | Condition / logic |
|---|---|---|---|---|
| JUR-1 | Did the complainant deposit the cheque in their own bank account? | Radio Y/N | Yes | Sets the s.142(2) jurisdiction basis: Yes → the payee's branch; No → the drawer's |
| JUR-2 | IFSC code (complainant's branch) | Text | Cond. | JUR-1 = Yes; automatic lookup. **This block repeats per cheque** when cheques were deposited at different branches |
| JUR-3 | Bank name | Text | Auto | From JUR-2 |
| JUR-4 | Bank branch | Text | Auto | From JUR-2 |
| JUR-5 | Police station of that branch | Dropdown (MDMS) | No | JUR-1 = Yes |
| JUR-6a | Police station of the drawer's bank branch | Dropdown (MDMS) | Cond. | **JUR-1 = No** |
| JUR-6b | Any other cheque dishonour complaint pending between the same parties? | Radio Y/N | Yes | Default No |
| JUR-7 | Court | Text | No | JUR-6b = Yes; **repeatable per pending case** |
| JUR-8 | Case number | Text | No | JUR-6b = Yes; repeatable |
| JUR-9 | Date of cause of action | Date | **Auto** | Service of the demand notice **+ 15 days**; uneditable. Service = delivery date, or return date when undelivered. Multiple notices → the **earliest** cause-of-action date |
| JUR-10 | Date of complaint filing | Date | **Auto** | Current date; uneditable |
| JUR-11 | Duration of delay | Number | **Auto** | Exists only when filed **more than one calendar month after JUR-9**; uneditable |
| JUR-12 | Reason for praying condonation of delay | Textarea | Cond. | Exists only when JUR-11 exists. Carries a ₹20 fee and a document requirement |

### A.7 ADR, prayer and other details — `PRY`

| ID | Field | Type | Required | Condition / logic |
|---|---|---|---|---|
| PRY-5 | Willing to settle through alternative dispute resolution? | Radio Y/N | Yes | Printed in the complaint PDF |
| PRY-1 | Additional details | Text | No | |
| PRY-2 | Interim relief | Rich text, pre-populated, editable | Yes | Standard s.143A template supplied; the filer may edit |
| PRY-3 | Final relief | Rich text, pre-populated, editable | Yes | Standard template supplied; printed as the prayer in the synopsis |
| PRY-4 | Affidavit | Rich text, pre-populated, editable | Yes | Its own screen in the individual flow |

### A.8 Witness — `WIT` (repeats per witness; the whole section is optional)

For a witness that **is** added, name-or-designation and address are required.

| ID | Field | Type | Required | Condition / logic |
|---|---|---|---|---|
| WIT-1 | Full name | Text | Cond. | Required unless WIT-4 is given |
| WIT-4 | Designation | Text | Cond. | Required unless WIT-1 is given |
| WIT-2 | Age | Number, integer ≥ 1 | No | |
| WIT-3 | What the witness will prove | Text | No | |
| WIT-5 | Mobile number | Phone | No | |
| WIT-6 | Email | Email | No | |
| WIT-7 | Address | Address (A.0) — **repeatable** | Yes | |

### A.9 Process configuration (collected at payment, per accused)

Decided **per accused, independently**. A case with three accused makes each choice three
times, and the bill states each separately.

| Setting | Range | Default | Notes |
|---|---|---|---|
| Summons rounds | 1–4 | 1 | **One round is mandatory per accused and cannot be declined** |
| Addresses summons is served at | ≥ 1 of that accused's addresses | — | Charged per selected address, per round |
| Warrant rounds | 0–4 | 1 | |
| Notice rounds | 0–1 | 1 when delay condonation applies, else 0 | Evaluated against the clock when the bill is drawn, not cached |
| E-post delivery rounds | 1 … summons rounds prepaid | — | Opted in and out separately from the summons court fee, round by round. The mandatory first round's e-post is collected with it |

---

# Appendix B — Documents

Every document a case can require. The required set is **derived from the case data** — the
"Instances" column is the formula.

| ID | Document | Mandatory | Instances |
|---|---|---|---|
| DCM-1 | Cheque | Yes | = number of cheques |
| DCM-2 | Cheque return memo | Yes | = number of **cheques** |
| DCM-3 | Legal demand notice | Yes | = number of demand notices |
| DCM-4 | Proof of dispatch of demand notice | Yes | = number of demand notices |
| DCM-5 | Proof of delivery (AD card or tracking report) | No | = number of demand notices. Includes documents showing delivery was attempted and failed |
| DCM-6 | Reply to the demand notice | No | = number of demand notices; available when `LDN-9` = Yes |
| DCM-7 | Proof of debt or liability | Yes | 1 per case |
| DCM-8 | Proof of reasons for delay | No | 1 per case; **exists only when the system computes a delay** |
| DCM-9 | ID card — complainant (usually Aadhaar; named "ID Card" deliberately, see below) | Yes | = number of complainants |
| DCM-10 | ID card — PoA holder | Yes | = number of PoA holders |
| DCM-11 | Power of Attorney authorisation | Yes | = number of PoA holders |
| DCM-12 | Vakalatnama | No | Present when the case has ≥ 1 advocate |
| DCM-13 | Other documents | No | As many as the filer adds |

**"Natively digital"** is a per-document attribute, not a separate document — it is a column
in the complaint PDF's evidence list. Whether a bulk filer states it or the system infers it
is *(open)*.

**ID card naming.** The handover deliberately calls `DCM-9`/`DCM-10` "ID Card," not "Aadhaar
Card" (§14), because of Aadhaar Act s.29. Masking is already decided — none at launch, shown
exactly as uploaded — so the only thing still open is *storage design*, and it is a gap in
the individual flow, not a bulk-specific one.

**Hard block.** In the individual flow, the document checklist is recomputed from the case
data on every change, and a missing mandatory document is the only hard block before
preview.

---

# Appendix C — What the system derives, and what it checks

## C.1 Derived values — never accepted from the filer

| Value | Derived from |
|---|---|
| District, State | Pincode, everywhere an address appears |
| Bank name, Bank branch | IFSC (`CHQ-5`, `JUR-2`) |
| Advocate full name | Bar registration number (`ADV-3`) |
| **Date of cause of action** (`JUR-9`) | Service of the demand notice + 15 days; service = delivery date, or return date when undelivered. Multiple notices → **earliest** |
| **Date of filing** (`JUR-10`) | The current date |
| **Duration of delay** (`JUR-11`) | Time beyond one calendar month from `JUR-9` |
| Whether delay condonation applies | `JUR-11` existing — which in turn creates `JUR-12`, `DCM-8`, a ₹20 fee head and a notice round |
| Synopsis | The whole case — parties, cheques, dishonour, notice, cause of action, jurisdiction, prayer |
| Complaint PDF | The whole case plus its documents |
| Fee bill | The court's fee master ([e-filing handover](efiling-scrutiny-registration-handover.md) §19) |
| Affidavit, interim relief, final relief | Pre-populated from templates, then editable |
| Party-in-Person affidavit | Pre-populated from a template when `LIT-1` = Yes |

## C.2 The date chain

Implemented as an explicit dependency graph. Marking any node during a correction cycle
unlocks everything transitively downstream of it (`REF-03`).

```
CHQ-1  date on cheque
  └─ CHQ-8  presentation            (≥ CHQ-1)
       └─ CHQ-9  return             (≥ CHQ-8)
            └─ LDN-2  dispatch      (≥ the return date of at least one cheque)
                 ├─ LDN-6  delivery (≥ LDN-2)   [delivered = Yes]
                 └─ LDN-7  return   (≥ LDN-2)   [delivered = No]
                      └─ JUR-9  cause of action = service + 15 days   (auto)
                           └─ JUR-10  filing date                     (auto)
                                └─ JUR-11  delay beyond 1 month       (auto)
```

## C.3 Checks that run across the whole case

- Every case has **≥ 1 complainant, ≥ 1 accused, ≥ 1 cheque, ≥ 1 demand notice**; every
  accused has **≥ 1 address**.
- **Phone uniqueness** — a complainant's number must not equal any other complainant's,
  accused's, advocate's or PoA holder's number in the same case.
- **Advocate mapping** — every non-PiP complainant has at least one advocate mapped to them
  (`ADV-2`), and the advocate section is complete only if the complainant section was.
- **Conditional presence** — every conditionally required field is present when its condition
  holds, and absent when it does not.
- **Controlled values** — every dropdown value exists in the current master list.
- **Documents** — every mandatory document, at its derived instance count, is attached.
- **Warnings, not errors** — a cheque return reason other than "Insufficient Funds" is
  flagged for the filer's attention but does not block filing.

---

## Related documents

| Document | What it owns |
|---|---|
| [E-filing, scrutiny and registration handover](efiling-scrutiny-registration-handover.md) | Field-level truth, lifecycle, signing, payment, scrutiny, refiling |
| [Account creation handover](account-creation-handover.md) | Registration paths, OTP as the default authentication, implicit account creation at signing |
| [dristi-solutions context](../docs/dristi-solutions-context.md) | The existing system — including the DSC bulk-signing that already ships (§8b) |
| [Batch e-sign proposal](../signing/batch-esign-proposal.md) | The Aadhaar one-document-per-OTP constraint and the methods researched around it |
| https://dristidomain.netlify.app/ | The legal domain model — source of truth for s.138 and limitation |
