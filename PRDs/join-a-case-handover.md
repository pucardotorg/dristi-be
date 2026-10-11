# Join a Case — Developer & Agent Handover

**Status:** v6 — 2026-10-06; added a placeholder for the vakalatnama payment logic. v5 — 2026-10-06; a mobile number entered for a party is confirmed by that party at their first sign-in before the case links to their account (JOIN-64). v4 — 2026-10-06; PoA holders can join for the complainant side and for several parties at once (one authorization document and one mobile number per party); flow outcome is Success. v3 — 2026-09-17; §12 Linked records now carries live views of all four
master tables (pending tasks court and citizen side, notifications, events), so anything
tagged later appears automatically. v2 — §12 Events added; later sections renumbered. v1 — all open questions resolved;
no approval flows in V1 (replacement deferred, all joins immediate)
**Date:** 2026-10-06
**Audience:** developers and agents building the Join a Case module (front end and backend)

## Sources and precedence

| Precedence | Source | Provides |
| --- | --- | --- |
| 1 — **source of truth** | Owner decisions, 2026-09-10 (recorded inline as **[OWNER]**) | Flow structure, role rules, V1 scope, access rules |
| 2 | `Case Access and Management.docx` | Broad scenarios: join, replacement, PoA, office management |
| 2 | `../docs/people-and-case-access.md` | Party-change scenario table (additions, removals, replacements) |
| 3 — interaction reference | Dristi app prototype: `Pucar-Dristi-2.0` @ `Feature/Your-Case`, `apps/dristi-app`, routes `/join/**`, `/join-case`, `/home` | Screen behaviour: onboarding modal, join dialogs (litigant + advocate), case details |

Conflicts: owner decisions win over everything; the docx wins over the prototype.
Marks: `[DERIVED]` inferred, confirm before building · `[GAP]` not specified, blocks
the item · `[CURRENT]` today's behaviour, not automatically a requirement · `[PROTO]`
prototype-only, an interaction reference · `[OWNER]` owner decision · `[V1]` deliberate
V1 shortcut, noted for later correction.

Requirement IDs: `JOIN-*` — use in tickets, commits, test names.

---

# 1. Scope

The Join a Case flow: from first contact (summons or manual lookup) through gaining
access to a case. Covers the accused side (litigant, party in person), and both sides
for PoA holders and advocates.

**Out of scope (separate documents):**
- Ongoing case access management (advocate replacement, PoA changes, office management)
  — covered in `../docs/people-and-case-access.md`
- Account creation — mentioned as a prerequisite (§3) but specified elsewhere
  (`../handovers/account-creation-handover.md`)
- E-filing — `../handovers/efiling-scrutiny-registration-handover.md`
- Post-join actions (filing, bail applications, case viewing)

**Who uses Join a Case:**
- The **accused** — the person named in the complaint
- An **advocate** — representing either the complainant or the accused
- A **PoA holder** — acting under a power of attorney for one or more parties, on the
  complainant side or the accused side

The **complainant** never uses this flow. Their details are entered during e-filing and
the case is linked to their account automatically (`JOIN-01`). A complainant's PoA holder
does use it (§9b).

---

# 2. Entry points

`JOIN-02` — Two entry points into the flow. The steps after entry are the same; the
difference is what the system already knows.

### 2a. Summons entry (QR code or link)

The accused learns about the case through a process document (summons, warrant,
proclamation) or other communication (SMS, email, WhatsApp). All communications must
provide clear next steps and an entry path into the system (`JOIN-03`).

The summons contains a unique URL (QR code + printed link). This URL embeds the case
identity and the access code, so the user does not need to look up the case or enter
the code manually.

**Before sign-in:** an onboarding journey explains the summons, the case, and the
person's options (see §2c below). The summons document itself is viewable within the
onboarding flow (`JOIN-04`).

`JOIN-05` — **[OWNER]** Multiple process documents (several summons, a warrant) may
have been issued to the same person. The system shows the **latest summons** that has
been issued for them. The screen stays the same regardless of which document brought
them in. The system tracks which process document was used in the background; this does
not change anything in the user-facing flow.

`JOIN-06` — After the onboarding journey, the user signs in or creates an account.
If they do not already have an account, they are taken through the account creation
process first (see `../handovers/account-creation-handover.md`).

After sign-in, the join flow opens with the case details already loaded and the access
code already verified (both embedded in the summons URL).

### 2b. Manual entry (logged in)



The user is already signed in. They navigate to Join a Case from the home screen or
the app navigation. The flow starts at the case lookup step.

### 2c. Summons onboarding journey

The onboarding journey is a full-screen walkthrough shown **before sign-in** when the
user arrives from a summons URL. It opens automatically after landing. Someone who
reaches the site directly (e.g. through search) goes straight to sign-in; a "Seek
help" button on the sign-in screen can open the onboarding manually.

The journey must be available in **English and Malayalam** (language toggle at the top).

**Step 1 — Your papers.** What the summons is. Explains the complainant's claim (a
cheque returned unpaid) and that being named as the accused does not mean the court has
found the person guilty. Shows a case summary card (case number, complainant, cheque
amount, cheque number) from the summons data, with fallbacks ("On your summons") when
the case is not yet in the system. Link to view the original summons document
(`JOIN-04`). An expandable "This is not about me" section directs the person to call
the court if the summons reached the wrong person.

**Step 2 — Your choices.** Three ways forward, explained plainly:
1. **Pay the cheque amount** — fastest resolution. Includes a warning about fake
   payment links (anti-fraud).
2. **Settle** — pay less or over time, or through Lok Adalat / mediation (both free).
   Names the complainant's advocate from the summons for contact.
3. **Contest the case** — with a lawyer or by representing yourself. Warning about the
   20% deposit requirement if pleading not guilty.

**Step 3 — Your date.** When and where the person must appear. Hearing date, court
name, and court address (from the summons data). Key facts: come in person, send a
lawyer, or join by video; if you cannot make it, ask the court for a new date
beforehand — do not stay away.

**Step 4 — Get help.** Free legal aid eligibility: women, children (any income),
anyone earning under ₹3 lakh/year. A signed statement of income is enough — no
certificate required. Contact card for the District Legal Services Authority.

**Step 5 — Join.** Directs the person to sign in or register. Notes that the access
code is on the summons and should be shared only with their lawyer. CTA closes the
modal and returns to the sign-in screen.

Each step has a companion area for a video and a help panel (common questions,
step-specific). `[DERIVED]` Video content is not specified — placeholder slots exist in
the prototype.

---

# 3. Prerequisites

| ID | Prerequisite | Notes |
| --- | --- | --- |
| `JOIN-07` | The user has an account and is signed in | If not, account creation happens first |
| `JOIN-08` | The case exists in the system | If the case is not yet in the system, the lookup returns no result and the user is told to check their papers |
| `JOIN-09` | The user has the six-digit access code | Printed on the summons; parties who have already joined the case can also share it |

---

# 4. Flow overview

The join flow is a single linear sequence. Every user goes through the same steps; what
changes at each step depends on their role and circumstances.

| Step | What happens | Summons entry | Manual entry |
| --- | --- | --- | --- |
| 1. Case lookup | Enter case number or filing number | *Skipped* — case known from URL | User enters it |
| 2. Access code | Enter the six-digit code | *Skipped* — code embedded in URL | User enters it |
| 3. Case details | Review the case before joining | Shown | Shown |
| 4. Role selection | "How are you joining this case?" | Asked | Asked |
| 5. Role-specific steps | Identity, party selection, documents | Varies by role | Varies by role |
| 6. Outcome | Success | Shown | Shown |

---

# 5. Step 1 — Case lookup

**Applies to:** manual entry only (summons entry skips this step).

`JOIN-10` — The user enters a case number or filing number. The system looks up the
case and returns basic identifying information.

**Before the access code is verified, the system shows only:**
- Case title (e.g. "South Indian Bank Ltd. vs Rajan Krishnan Nair and 1 other")
- Case number (e.g. "CC 847 / 2026")
- Court name

`JOIN-11` — **[OWNER]** The amount claimed is **not** shown before the access code is
verified. Before the code, the card shows: title, case number, court. This is
sufficient.

`JOIN-12` — If no case matches, the user is told: the case may not be in the system
yet, check the summons.

---

# 6. Step 2 — Access code

**Applies to:** manual entry only (summons entry skips this step — the code is embedded
in the URL).

`JOIN-13` — **[OWNER]** The access code is required from **everyone** joining the case
— litigants, advocates, and PoA holders alike. It is a six-digit numeric code.

The access code is printed on the summons. Parties who have already joined the case can
also share it with the joining user.

The screen shows the basic case information from step 1 (title, case number, court —
no amount) so the user can confirm they are joining the right case before entering the
code.

`JOIN-14` — After successful verification, the full case details are revealed (step 3).

---

# 7. Step 3 — Case details

`JOIN-15` — After the access code is verified (or immediately for summons entry), the
full case details are shown:

| Field | Shown |
| --- | --- |
| Case type badge | e.g. "Cheque bounce · NIA S138" |
| Case title | With explorable "and N other" for multiple accused |
| Next hearing date | Prominent — date, day, time |
| Case number | |
| Filing date | |
| Court | |
| Complainant | |
| Complainant's advocate | With contact option (phone) for settlement discussions |
| Accused parties | All names |
| Accused's advocate | If one is on record |

**[PROTO]** The prototype also shows CNR, filing number, and both sides' advocates in
an "extended" view for advocates. Whether to differentiate the details view by role is
an implementation choice; the data is the same.

`JOIN-16` — The user can view/download the case file from this screen.

`JOIN-17` — **[PROTO]** For summons entry, an info note says: "By joining this case you
confirm that the summons has reached you."

---

# 8. Step 4 — Role selection

`JOIN-18` — **[OWNER]** After reviewing the case details, the user is asked: **"How are
you joining this case?"**

The options depend on the user's account type:

| Account type | Options shown |
| --- | --- |
| Advocate account | Advocate · Litigant · PoA holder |
| Litigant account | Litigant · PoA holder |

`JOIN-19` — **[OWNER]** The **Advocate** option is only available for users who are
registered as an advocate in the system. It does not appear for litigant accounts.

`JOIN-20` — **[OWNER]** If a user with an advocate account selects **Litigant** or
**PoA holder**, they switch to their litigant profile before continuing. The rest of
the flow proceeds as a litigant.

`JOIN-21` — **[OWNER]** The PoA holder option is available in all entry modes —
including when the user initiates the flow from within the app (not only from a
summons).

---

# 9. Step 5 — Role-specific steps

## 9a. Joining as a litigant (accused)

The litigant flow collects: which party you are, and how you will appear in court.

### Which party are you?

`JOIN-22` — The user selects which accused party they are from a list of accused
parties in the case.

`JOIN-23` — **[OWNER]** If there is only one accused party, the system auto-selects
them. The user still sees who they are joining as, but does not need to choose.

`JOIN-24` — If the selected party has already joined the case, the system shows a
warning: the party has already joined, sign in with the account used earlier or
contact the court. The user cannot proceed.

`JOIN-25` — After selecting a party, a note confirms the mapping: "You are joining as
{name}. Your account will be linked to that name in the case record." This is
necessary because the user's registered name may differ from the name in the case
record.

### How will you appear in court?

`JOIN-26` — The user is asked how they will appear in court. Three options:

| Option | Label | What happens next |
| --- | --- | --- |
| Hire an advocate | "I want to hire an advocate" | Joins immediately. Can add an advocate later. |
| Already have one | "I already have an advocate" | Joins immediately. Advocate joins the case separately. |
| Party in person | "I will represent myself (Party in Person)" | See `JOIN-27`. |

`JOIN-27` — **[OWNER]** Party in Person rules:

- The PiP option is only available when **no advocates are currently on record for the
  accused side** of this case. This is because when an advocate joins, they enter the
  accused's details and the case is linked to the accused's account — the accused
  never needs Join a Case in that scenario.
- **[V1]** The accused joining as PiP must upload an **affidavit**. After uploading,
  they receive **immediate access** to the case. No court verification is required in
  V1. `[DERIVED]` In a later version, court verification before granting full case
  access may be added.

### Outcome

`JOIN-28` — An accused joining as a litigant receives **immediate access** to the case
after completing the flow — including a Party in Person in V1 (see `JOIN-27` for the
affidavit requirement). Post-V1, a PiP will require court verification before access
is granted; a non-PiP accused will continue to receive immediate access.

---

## 9b. Joining as a PoA holder

The PoA holder flow collects: which side, which party or parties you hold power of
attorney for, an authorization document for each party, and each party's mobile number
where the system does not have it.

### Which side?

`JOIN-63` — **[OWNER]** The user is asked: "Are you a PoA holder for a complainant or an
accused?" If the user is entering from a summons, the accused side is pre-selected; the
user can still change it.

### Which parties?

`JOIN-29` — **[OWNER]** The user selects the party or parties on that side they hold power
of attorney for. This is a **multi-select** — one person can hold power of attorney for
several parties. `[DERIVED]` All selected parties are on the same side.

`JOIN-30` — **[OWNER]** If there is only one party on the selected side, the system
auto-selects them.

`JOIN-31` — If another PoA holder is already managing the case for a selected party, the
user is blocked for that party: only one PoA holder can act for a party at a time. The
user is directed to contact the court.

Note: the party having joined in person does **not** block a PoA join — the party and
their PoA holder both legitimately hold access.

### Authorization documents

`JOIN-32` — **[OWNER]** The user uploads a **separate authorization document for each
selected party** (an affidavit signed by that party authorizing them). One upload per
party; each is required. Accepts JPG, JPEG, PNG, or PDF.

`JOIN-33` — **[PROTO]** A sample authorization document is available for download.

### Parties' contact

`JOIN-34` — **[OWNER]** For **each** selected party who does not yet have an account in
the system, the PoA holder must provide that party's mobile number. This is
**mandatory** — the system needs it to link the case to the party's account. One field
per party needing a number. Parties who have already joined the case are skipped (the
number is already on record); if every selected party has joined, this step is skipped.
The number is confirmed by the party themselves, not at entry (`JOIN-64`).

`JOIN-64` — **[OWNER]** A mobile number entered for a party — by a PoA holder (`JOIN-34`)
or an advocate (`JOIN-47`) — is **not verified by OTP at entry**, and the joining user's
own access is not held up by it. The number is confirmed by its owner:

1. When the number is entered, an SMS goes to it saying the case is waiting for them.
2. The case is **not linked automatically**. The next time someone signs in with that
   number — an existing account, or a new one registered with it — they are asked:
   "Are you {party name} in case {case number}?" Signing in already requires their own
   OTP.
3. **Yes** → the case is linked to their account and they have access.
4. **No** → the case is not linked and nothing else happens in the system. The party
   stays unlinked until they join the case themselves and provide their own number. A
   notification goes to the users on that party's side of the case, telling them the
   number was not confirmed.

### Outcome

`JOIN-35` — **[V1] [OWNER]** In V1, the PoA holder receives **immediate access** to
the case after completing the flow.

This is a deliberate V1 shortcut. Properly, the magistrate must approve a PoA holder
before they can begin representing the litigant (the docx states: "The Join a Case
flow must therefore not end with direct access to the case, but rather with the
raising of an application"). This is deferred because it requires building a
magistrate approval screen. **Log this clearly in the backlog — it must be built
before V1 exits pilot.**

---

## 9c. Joining as an advocate

The advocate flow collects: which side, which parties, whether they are replacing an
existing advocate, litigant contact details (if needed), and the vakalatnama.

### Which side?

`JOIN-36` — The user is asked: "Are you representing a complainant or an accused?"

`JOIN-37` — **[OWNER]** If the user is entering from a summons, the accused side is
pre-selected (since summons are served to the accused). The user can still change
this.

`JOIN-38` — **[PROTO]** If the advocate selects the accused side, an info note says:
"By joining for the accused, you confirm that the summons has reached them."

### Which parties?

`JOIN-39` — The user selects which litigant(s) they represent. This is a
**multi-select** — one vakalatnama routinely covers co-accused (or co-complainants).

`JOIN-40` — **[OWNER]** If there is only one party on the selected side, the system
auto-selects them.

### Replacing an existing advocate?

`JOIN-41` — **[V1] [OWNER]** Advocate replacement is **not available in V1**. The
advocate always joins in addition to any existing advocates. The replacement flow
(selecting who to replace, choosing an approver, providing a reason and supporting
document) will be built in a later version.

`[DERIVED]` In V1 there are **no approval flows** in Join a Case. Every join is
immediate.

### Litigant contact capture

`JOIN-47` — **[OWNER]** If any of the selected litigants do not yet have an account in
the system (and therefore no phone number on record), the advocate must provide their
mobile number. This is **mandatory** — the system needs it to link the case to the
litigant's account. One field per litigant needing a number.

`JOIN-48` — Litigants who have already joined the case are skipped — the system already
has their number.

`JOIN-49` — `[DERIVED]` This step is skipped entirely if all selected litigants already
have numbers on record.

Each number entered here is confirmed by the litigant, not at entry (`JOIN-64`).

### Vakalatnama

`JOIN-50` — **[OWNER]** In V1, the advocate must always **upload** a vakalatnama.
Generated vakalatnamas will be available in a later version.

`JOIN-51` — **[OWNER]** The advocate **always uploads** the vakalatnama document,
regardless of whether another advocate has already done so.

If another advocate is already on the case, the user is asked: **"Has another advocate
already uploaded and paid for this vakalatnama?"**

- **Yes** → This advocate uploads the document but **does not pay**.
- **No** → This advocate uploads the document **and pays**.

`JOIN-52` — This question is only asked when another advocate is already on the case.
If this is the first advocate joining, they always upload and pay.

`JOIN-53` — If the advocate is uploading (not joining an existing vakalatnama), they
are asked:
- How many advocates are part of this vakalatnama? (numeric)
- Which advocates? (selected from the bar directory, capped at the stated count)

`JOIN-54` — **[OWNER]** Payment for the vakalatnama happens **within the join flow**.
After uploading the vakalatnama, the advocate is taken to the payment step. The
advocate **does not get access to the case until payment is complete**.

If the advocate closes the dialog or the session ends before payment, the payment
becomes a **pending task**. The advocate can complete it later, but does not have
access to the case until they do.

### Vakalatnama payment logic

`[GAP]` To be specified — how the vakalatnama fee is calculated and collected.

### Outcome

`JOIN-55` — **[OWNER]** An advocate joining the case receives access **after payment**
of the vakalatnama fee (see `JOIN-54`) — regardless of whether they are on the
complainant side or the accused side. In V1 there is no replacement flow, so no
advocate join requires approval. Payment is the only gate.

`JOIN-57` — **[PROTO]** On the success screen (immediate access), the advocate is
offered the option to invite team members (clerks, junior advocates) to the case by
entering their mobile numbers.

---

# 10. Auto-fill rules

`JOIN-58` — **[OWNER]** Wherever possible, the system auto-fills information for the
user. Specific rules:

| Condition | What is auto-filled |
| --- | --- |
| Summons entry | The case is pre-loaded; the access code is pre-verified; the accused side is pre-selected (for advocates) |
| Only one accused party (litigant flow) | The "which party" dropdown is auto-selected |
| Only one party on the selected side (advocate and PoA flows) | The party multi-select is auto-selected |
| Summons entry (PoA flow) | The accused side is pre-selected |

`JOIN-59` — Auto-fill never skips a step. The auto-filled value is shown to the user so
they can confirm or change it. The step is still displayed; only the selection is
pre-made.

---

# 11. Blocking and duplicate guards

| ID | Scenario | Behaviour |
| --- | --- | --- |
| `JOIN-60` | The accused has already joined | Blocked — sign in with the earlier account or contact the court |
| `JOIN-61` | A PoA holder is already acting for a selected party | Blocked for that party — only one PoA holder per party at a time |
| `JOIN-62` | The case is not in the system | Lookup returns no result; user told to check their papers |

---

# 12. Linked records

Live views of the master tables, filtered to this document. Each master table is the
single source of truth and the place to edit its rows; anything tagged
`join-a-case-handover` there appears here automatically. A section showing nothing
means nothing is tagged for it yet. A downloaded copy of this document is a snapshot.

### Pending tasks (Court Side)

```superhuman-view
name: Pending tasks (Court Side) — Join a Case
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("join-a-case-handover")
```

### Pending tasks (Citizen-Side)

```superhuman-view
name: Pending tasks (Citizen-Side) — Join a Case
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("join-a-case-handover")
```

### Notifications

```superhuman-view
name: Notifications — Join a Case
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-xnftvTkudd/tables/grid-3FTjQhdfYv
filter: PRDs.Contains("join-a-case-handover")
```

### Events

```superhuman-view
name: Events — Join a Case
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-2x28DoUtbn/tables/grid-GPg4dKS-s9
filter: PRDs.Contains("join-a-case-handover")
```

---

# 13. V1 decisions log

### Governing principle

**[OWNER]** In V1, **no action in Join a Case requires approval**. Every join is
immediate. Advocate replacement is deferred to a later version.

This is deliberate: it empowers litigants to manage access in their own case without
waiting for court process, and it means there are no approval screens to build for
this module in V1. More stringent controls (magistrate approval for PoA holders,
court verification for PiP, advocate replacement with an approver) can be layered on
in later versions.

**Cross-reference:** this principle also governs case access management actions outside
the join flow — a party in person dismissing all their advocates (row 4 in
`../docs/people-and-case-access.md`) takes effect immediately in V1 without magistrate
approval, following the same rule. That document should be updated to reflect this.

### Specific V1 shortcuts

These are deliberate shortcuts. Each must be revisited before V1 exits pilot.

| ID | Decision | Proper behaviour | Why deferred |
| --- | --- | --- | --- |
| `JOIN-41` | Advocate replacement not available | Advocate can replace an existing advocate, with approval from the judge or outgoing advocates | No approval flows in V1 |
| `JOIN-35` | PoA holder gets immediate access | Magistrate must approve before access is granted | No approval flows in V1 |
| `JOIN-27` | PiP gets immediate access after uploading affidavit | Court verifies once before the accused can act in the case | No approval flows in V1 |
| `JOIN-50` | Vakalatnama is upload-only | System can generate vakalatnamas | Generated vakalatnama feature comes later |

---

# 14. Open questions

No blocking open questions remain. All questions from v1 have been resolved inline.
