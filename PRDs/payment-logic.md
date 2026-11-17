# Payment Logic

**Status:** v2.7 — 2026-11-17; missing account details (account no., head of account, account type, head ID) and Kerala's application fee are highlighted as *Not known*. v2.6 — 2026-11-17; the upfront process payment tables that were empty or all zero are removed: the channel-fee tables for all three states (none at launch, `PMT-13`) and the court-fee tables for Gujarat and Punjab & Haryana, where it is off (`PMT-09`, `PMT-14`); Kerala's court-fee table stays. The Complaint Fee row (Nil) is removed from Gujarat's and Punjab & Haryana's case filing; the heads need not match from state to state. v2.5 — 2026-11-17; Punjab & Haryana application fee is ₹20 per application (§4); `Q-3` now asks only for Kerala's. v2.4 — 2026-11-17; every payment receipt has a **receipt number**, which is its title wherever it is shown (`PMT-15`, new, §1); who issues it and in what format is open (`Q-16`, new). v2.3 — 2026-11-16; **no process court fee in Gujarat or Punjab & Haryana**: Gujarat's court fee per process type is now ₹0 (§4, was ₹3), and upfront process payment is off in Gujarat (`PMT-14`, new) as it already was in Punjab & Haryana. Both states' upfront court-fee tables now show 0 rounds payable for every process type (§3.2, §3.3). `Q-2` (Gujarat upfront on or off) answered and removed. `PMT-09` now says Talwana is ₹50 whatever the number of accused, addresses and rounds, and covers every process for the life of the case; `Q-8` answered and removed. v2.2 — 2026-11-05; **Punjab & Haryana account heads added** (§3.3), from the Treasury Officer, Panchkula (No. 1493, 15-09-2026) and the District Bar Association, Panchkula (Ref. 1099/26, 22-10-2026), forwarded by the District & Sessions Judge, Panchkula (No. 15480, 30-10-2026): Court Fee and Process Fees (Talwana) go to receipt head 0030-01-101-99-51 (Pasting/Court Fees); Advocate Welfare Fund goes to the Panchkula Bar Association's account, at filing and join a case. `Q-12`–`Q-15` new: other districts' welfare fund accounts, collecting the fund through eGRAS, the 17-character head code, and the head for Vakalatnama Court Fee and Delay Condonation Application Fee. v2.1 — 2026-11-04; `PMT-12` (channel-fee rounds capped at court-fee rounds) dropped, to [`dropped-ideas.md`](dropped-ideas.md). v2 — 2026-11-04; **upfront channel fee added**, configured separately from the upfront court fee, per state and process type (`PMT-10`–`PMT-13`, new; `Q-11`, new): expected optional everywhere, never more rounds than the court fee, none at launch. Each state now has a court-fee table and a channel-fee table. v1.9 — 2026-11-04; Kerala upfront warrant and notice are charged × selected addresses, like summons, following e-filing `PAY-12`. v1.8 — 2026-11-04; `PMT-06` now says no minimum rounds apply, following the change to e-filing `PAY-10`. v1.7 — 2026-11-04; [`efiling.md`](efiling.md) §19 no longer repeats fee figures and links here; `Q-4` (Kerala ₹2 vs ₹12.50) removed — e-filing no longer states a figure. v1.6 — 2026-11-04; Gujarat Court Fee no longer says it is charged as stamps on the main complaint; `Q-5` removed with it. v1.5 — 2026-11-04; the fee tables' third column is now "Logic", not "Applies when"; conditions read "Applies if …"; join-a-case caps say "per complainant", as at filing. v1.4 — 2026-11-04; **which process types are offered upfront is a choice, not a consequence of a zero fee** (`PMT-08`, now `[OWNER]`): rounds payable upfront are set per process type; 0 means not offered. Kerala's table now lists proclamation, attachment and custom process at 0 rounds. v1.3 — 2026-11-04; every amount shown with ₹; "(INR)" dropped from column headings. v1.2 — 2026-11-04; `PMT-07`'s example is ePost, not eSeva. v1.1 — 2026-11-04; **a different fee per application type is a configuration change, not a new capability** (`PMT-03a`, new). v1 — 2026-11-04; first draft, from the *Payment Logic - New* Google Doc. Fee heads, amounts and conditions per state for case filing, join a case, a new application and a new process (§2–§4). **Upfront process payment is switched on or off per state; when off, the step is not shown at e-filing** (`PMT-05`–`PMT-09`). A state turns it off because its process court fee is zero, or because the court does not want it; the first may turn it on once a channel fee applies. Punjab & Haryana is off — its process fee is collected as one flat amount at filing. Blank cells are not known yet (§5). v0 — 2026-10-30; placeholder, not written yet.
**Audience:** developers and agents building fees and payments

Every fee the system collects, by state and by the moment it is collected: case filing,
join a case, a new application, a new process. What is charged, when it applies, and
which account it goes to. How the payment itself is taken — the upfront mechanism, the
payment screen, resubmission — is owned elsewhere and linked, not restated: filing in
[`efiling.md`](efiling.md) §19, processes in [`process.md`](process.md) §7, applications
in [`application-lifecycle.md`](application-lifecycle.md), joining in
[`join-a-case.md`](join-a-case.md).

A blank cell in this document means the value is not known yet. Do not fill it in. Amounts and account details still to be found are also highlighted: <mark>Not known</mark>.

---

## 1. Rules for every state

| ID | Requirement |
|---|---|
| `PMT-01` | Every head, amount, condition, cap, slab and account below is per-state configuration. No figure is hard-coded. |
| `PMT-02` | Parties in Person are never counted as advocates, for any rule that depends on an advocate being present or on the number of advocates. |
| `PMT-03` | One application fee applies to every application type, until we know whether types differ. |
| `PMT-03a` | **[OWNER]** A different application fee can be set for any application type, per state, by configuration alone — no code change. |
| `PMT-04` | Process court fee paid at filing or in earlier rounds is held as one pool on the case. A process draws from the pool and only the balance is charged; nothing is refunded. The pool rules are owned by [`process.md`](process.md) `FEE-04`–`FEE-07`. |
| `PMT-15` | Every payment receipt has a **receipt number**, which is its title wherever the receipt is shown, including the case file ([`case-file.md`](case-file.md) §3.1). |

## 2. Upfront process payment at filing

The upfront mechanism — rounds, defaults, addresses, the per-accused choice — is owned by
[`efiling.md`](efiling.md) §19.2. This section says when it is offered.

Upfront process payment has two parts, configured separately: the **court fee** for each
process, and the **channel fee** a delivery channel charges on top ([`process.md`](process.md)
`FEE-02`). §3 gives each state's settings.

| ID | Requirement |
|---|---|
| `PMT-05` | **[OWNER]** Upfront process payment is switched on or off per state. |
| `PMT-06` | **[OWNER]** When it is off, the upfront process payment step is not shown at e-filing. The filer makes no choice about rounds or addresses for payment, and no minimum rounds apply ([`efiling.md`](efiling.md) `PAY-10`). Every process is charged when the court issues it (§4). |
| `PMT-07` | **[OWNER]** A state turns it off for either reason: its process court fee is zero, so there is nothing to collect upfront; or the court does not want upfront payment. A state off for the first reason may turn it on once a channel fee applies — for example, when ePost is integrated. |
| `PMT-08` | **[OWNER]** When it is on, the rounds payable upfront are set per process type, per state. A process type whose rounds payable upfront is 0 is not offered for upfront payment, whatever its court fee. |
| `PMT-09` | **[OWNER]** Punjab & Haryana: off. Process fees are collected as one flat amount at filing (Process Fees (Talwana), §3.3), and every process type's court fee is zero. Talwana is ₹50 whatever the number of accused, addresses and rounds, and it covers every process for the life of the case. |
| `PMT-10` | **[OWNER]** The upfront channel fee is configured separately from the upfront court fee, per state and per process type: rounds payable upfront, default and what is charged. |
| `PMT-11` | **[OWNER]** The upfront channel fee is expected to be optional in every state — lowest rounds 0 — but each state sets its own range and default. |
| `PMT-13` | No channel fee is collected at launch. Only e-Post has one, and it comes after launch ([`process.md`](process.md) §13.1). |
| `PMT-14` | **[OWNER]** Gujarat: off. Every process type's court fee is zero (§4). |

## 3. Case filing and join a case

### 3.1 Kerala

**Case filing**

| Head | Amount | Logic | Type | Account no. | Head of account | Account type | Head ID |
|---|---|---|---|---|---|---|---|
| Court Fee | ₹12.5 | Applies if at least one advocate is in the case | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Legal Benefit Fee | ₹12.5 | Applies if at least one advocate is in the case | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Advocate Welfare Fund | ₹100 per advocate, calculated per complainant | Capped at ₹300 per complainant | TSB | 799010100175123 | 8031-00-102-94-07-00-00-N-V | 01 | 56685 |
| Stipend Stamp | ₹25 per advocate, calculated per complainant | Capped at ₹75 per complainant | TSB | 799010100175123 | 8031-00-102-94-07-00-00-N-V | 01 | 56685 |
| Advocate Clerk Welfare Fund | ₹20 | Applies if at least one advocate is in the case | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Delay Condonation Application Fee | ₹20 | Applies if a Delay Condonation Application is attached | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Complaint Fee | By cheque amount: up to 50k → ₹250 · 50k–2L → ₹500 · 2L–5L → ₹750 · 5L–10L → ₹1,000 · 10L–20L → ₹2,000 · 20L–50L → ₹5,000 · above 50L → ₹10,000 | With more than one cheque, the slab applies to the sum of all cheque amounts | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |

**Upfront process payment — court fee**

| Process | Rounds payable upfront | Default | Charged |
|---|---|---|---|
| Summons | 1–4 | 1, mandatory for each accused | ₹2 × rounds × selected addresses |
| Warrant | 0–4 | 1 | ₹2 × rounds × selected addresses |
| Notice | 0–1 | 1 when Delay Condonation applies, otherwise 0 | ₹2 × rounds × selected addresses |
| Proclamation | 0 | 0 | — |
| Attachment | 0 | 0 | — |
| Custom process | 0 | 0 | — |

Upfront process payment: on. Proclamation, attachment and custom process are not
offered (`PMT-08`).

**Upfront process payment — channel fee** — none at launch (`PMT-13`); figures not known yet (`Q-11`). The channel fee comes from the fee service ([`process.md`](process.md) `FEE-03`).

**Join a case**

| Head | Amount | Logic | Type | Account no. | Head of account | Account type | Head ID |
|---|---|---|---|---|---|---|---|
| Court Fee | ₹12.5 | Applies if the joining advocate says they are not part of a previous vakalatnama | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Legal Benefit Fee | ₹12.5 | Applies if the joining advocate says they are not part of a previous vakalatnama | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Advocate Welfare Fund | ₹100 per advocate, calculated per complainant | Capped at ₹300 per complainant | TSB | 799010100175123 | 8031-00-102-94-07-00-00-N-V | 01 | 56685 |
| Stipend Stamp | ₹25 per advocate, calculated per complainant | Capped at ₹75 per complainant | TSB | 799010100175123 | 8031-00-102-94-07-00-00-N-V | 01 | 56685 |
| Advocate Clerk Welfare Fund | ₹20 | Applies if at least one advocate is in the case | TSB | 701011400000051 | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |

### 3.2 Gujarat

**Case filing**

| Head | Amount | Logic | Type | Account no. | Head of account | Account type | Head ID |
|---|---|---|---|---|---|---|---|
| Court Fee | ₹3 | | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Advocate Welfare Fund | ₹20, whatever the number of advocates | | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Vakalatnama Court Fee | ₹2 per advocate | | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Delay Condonation Application Fee | ₹3 | Applies if a Delay Condonation Application is attached | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Affidavit Fee | ₹2 per affidavit | | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |

**Upfront process payment — court fee** — off (`PMT-14`). No process type is offered.

**Upfront process payment — channel fee** — none at launch (`PMT-13`); figures not known yet (`Q-11`). The channel fee comes from the fee service ([`process.md`](process.md) `FEE-03`).

**Join a case**

| Head | Amount | Logic | Type | Account no. | Head of account | Account type | Head ID |
|---|---|---|---|---|---|---|---|
| Vakalatnama Court Fee | ₹2 per advocate | | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Advocate Welfare Fund | ₹50, whatever the number of advocates | | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |

### 3.3 Punjab & Haryana

**Case filing**

| Head | Amount | Logic | Type | Account no. | Head of account | Account type | Head ID |
|---|---|---|---|---|---|---|---|
| Court Fee | ₹10 | Applies if at least one advocate is in the case | | <mark>Not known</mark> | 0030-01-101-99-51 (Pasting/Court Fees) | <mark>Not known</mark> | <mark>Not known</mark> |
| Advocate Welfare Fund | ₹50, whatever the number of advocates | | | Panchkula: 0988102100001192 (Punjab National Bank, IFSC PUNB0098810). Other districts not known yet (`Q-12`) | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Vakalatnama Court Fee | ₹2 per advocate | | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Delay Condonation Application Fee | ₹20 | Applies if a Delay Condonation Application is attached | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Process Fees (Talwana) | ₹50 | | | <mark>Not known</mark> | 0030-01-101-99-51 (Pasting/Court Fees) | <mark>Not known</mark> | <mark>Not known</mark> |

**Upfront process payment — court fee** — off (`PMT-09`). No process type is offered.
Process fees are collected in full through Process Fees (Talwana).

**Upfront process payment — channel fee** — none at launch (`PMT-13`). Punjab & Haryana may turn upfront payment on for channel fees alone (`PMT-07`); figures not known yet (`Q-11`). The channel fee comes from the fee service ([`process.md`](process.md) `FEE-03`).

**Join a case**

| Head | Amount | Logic | Type | Account no. | Head of account | Account type | Head ID |
|---|---|---|---|---|---|---|---|
| Vakalatnama Court Fee | ₹2 per advocate | | | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |
| Advocate Welfare Fund | ₹50, whatever the number of advocates | | | Panchkula: 0988102100001192 (Punjab National Bank, IFSC PUNB0098810). Other districts not known yet (`Q-12`) | <mark>Not known</mark> | <mark>Not known</mark> | <mark>Not known</mark> |

## 4. New application and new process

**Application fee** (`PMT-03`)

| State | Amount |
|---|---|
| Kerala | <mark>Not known</mark> |
| Gujarat | ₹3 per application |
| Punjab & Haryana | ₹20 per application |

**Court fee per process type**, charged when the court issues a process, less what the
pool holds (`PMT-04`). The process flow is owned by [`process.md`](process.md) §7.

| Process type | Kerala | Gujarat | Punjab & Haryana |
|---|---|---|---|
| Notice | ₹2 | ₹0 | ₹0 |
| Summons | ₹2 | ₹0 | ₹0 |
| Warrant | ₹2 | ₹0 | ₹0 |
| Proclamation | ₹0 | ₹0 | ₹0 |
| Attachment | ₹0 | ₹0 | ₹0 |
| Custom process | ₹0 | ₹0 | ₹0 |

## 5. Open questions

| ID | Question | Blocking |
|---|---|---|
| `Q-1` | Remittance accounts for every head with a blank account (all three states). Kerala's Advocate Clerk Welfare Fund has an account at join a case (701011400000051) but none at filing — is it the same account? | Yes, for remittance |
| `Q-3` | Application fee for Kerala. | Yes, for applications in Kerala |
| `Q-6` | Gujarat Affidavit Fee: which affidavits are counted? | Yes, for Gujarat filing |
| `Q-7` | Gujarat Advocate Welfare Fund is ₹20 at filing and ₹50 at join a case. Confirm both. | No |
| `Q-9` | Where upfront payment is off (`PMT-06`), are summons addresses chosen only when the court issues the process ([`process.md`](process.md) `PRC-05`)? | No |
| `Q-10` | Whether application fees differ by application type (`PMT-03`). | No |
| `Q-11` | Upfront channel fee per state: rounds payable upfront, defaults and which process types, once e-Post is available. | No — none at launch |
| `Q-12` | Punjab & Haryana Advocate Welfare Fund: the District Bar Association, Panchkula keeps its own welfare account (§3.3). Does each district have its own, and is the fund paid to the Bar Association of the district where the case is filed? If so, the account for every other district. | Yes, for Punjab & Haryana remittance |
| `Q-13` | Punjab & Haryana Advocate Welfare Fund goes to a Bar Association bank account, not a government receipt head. Can it be collected through eGRAS, or does it need another route? | Yes, for Punjab & Haryana filing |
| `Q-14` | Punjab & Haryana receipt head `0030-01-101-99-51` is 13 digits; eGRAS expects a 17-character head of account. What is the full code? | Yes, for eGRAS integration |
| `Q-15` | Punjab & Haryana Vakalatnama Court Fee and Delay Condonation Application Fee: do they also go to `0030-01-101-99-51`? The Treasury letter names only Court Fee and Process Fee. | Yes, for Punjab & Haryana remittance |
| `Q-16` | **Receipt number** (`PMT-15`). Who issues it (the system, the payment gateway or eGRAS), and in what format? | No |
