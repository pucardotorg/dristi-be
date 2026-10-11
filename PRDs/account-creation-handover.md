# Account Creation — Developer & Agent Handover

**Status:** v8 — 2026-09-27; `REG-34`'s unexplained "reasonable — confirm" dropped ·
§6.1 courtroom mapping generalised (no longer names Gujarat/a specific courtroom count,
states the 1:1-formally/differs-in-practice pattern for any employee role) · §7 accused
onboarding trimmed to the account-creation claim only, onboarding-journey detail now
points to `join-a-case-handover.md` §2c · **OTP rate limiting removed** (`REG-50`,
old §9) — not the owner's call to make here; later sections renumbered (old §10–13 →
§9–12).
v7 — 2026-09-27; §3 entry flow's step table and `REG-55/56/57` table merged
into one (they duplicated each other and step 3's wording conflicted with `REG-56`) —
the password option in step 3 is now stated as always offered, never conditional on
account existence.
v6 — 2026-09-26; **implicit account creation is not account completion**
(`REG-62/63`, §4): the first time that person logs in themselves, they still go through
the registration flow (set a password if they want, accept terms and conditions) —
their account is not complete until then.
v5 — 2026-09-17; §10 Linked records now carries live views of all four
master tables (pending tasks court and citizen side, notifications, events), so anything
tagged later appears automatically. v4 — §10 Notifications added; later sections renumbered. v3 — entry flow and password reminder
added
**Date:** 2026-09-17
**Audience:** developers and agents building the registration module

## Sources and precedence

| Precedence | Source | Provides |
| --- | --- | --- |
| 1 | `Account Creation.pdf` | User types, flows, requirements, context |
| 2 — interaction reference | Dristi app prototype: `Pucar-Dristi-2.0`, `apps/dristi-app`, routes `/join`, `/welcome` | Screen behaviour: sign-in, registration, accused onboarding |
| 3 — cross-reference | `efiling-scrutiny-registration-handover.md` §18 | Account creation at signing (implicit creation path) |
| — | Owner decisions, 2026-09-03 | Recorded inline as **[OWNER]**; log in §10 |
| — | Owner decisions, 2026-09-07 | Entry flow, password reminder; log in §10 |

Conflicts: the PDF wins over the prototype; owner decisions win over everything.
Marks: `[DERIVED]` inferred, confirm before building · `[GAP]` not specified, blocks
the item · `[CURRENT]` today's behaviour, not automatically a requirement · `[PROTO]`
prototype-only, an interaction reference.

Requirement IDs: `REG-nn` — use in tickets, commits, test names.

---

# 1. Scope

Account creation for all user types: litigants, PoA holders, advocates, clerks, court
employees (magistrate, bench clerk, CMO, typist), and accused persons arriving via
summons. Covers the entry flow (authenticate first, then route to login or
registration), the registration flow, the advocate/clerk approval workflow, credentials
setup and the password reminder lifecycle, accused onboarding, and password policy.

Out: ongoing session management; password reset via forgot-password flow and account
recovery (the Set Password / Reset Password options in account settings are covered by
`REG-61`); role-based access within the application (see e-filing handover §3); bulk
account creation tooling; Bar Council database synchronisation mechanics;
post-registration profile management; OTP rate limiting and other OTP delivery/security
parameters (not the owner's call — belongs with whoever owns SMS/OTP infrastructure).

---

# 2. User types and registration paths

| User type | Self-registers | Needs approval | Identity verified by |
| --- | --- | --- | --- |
| Litigant | Yes | No | Mobile OTP |
| PoA Holder | Yes | No | Mobile OTP |
| Advocate | Yes | Yes — scrutiny officer | Bar ID + photo of Bar ID |
| Clerk | Yes | Yes — scrutiny officer | Clerk registration number + photo of clerk ID card |
| Employee | No — created by admin | N/A | HRMS / backend |
| Accused (via summons) | Yes | No | Mobile OTP |

**[OWNER]** PoA Holder is presented as a **separate option** during role selection, but
the registration process and the resulting account are **identical to a litigant's**.
The distinction is presentational only — the system does not create a different kind of
account.

---

# 3. Entry flow — authenticate first, then route

**[OWNER]** The system authenticates before revealing whether an account exists.

| Step | ID | What happens |
| --- | --- | --- |
| 1 | | User enters their mobile number |
| 2 | `REG-55` | System sends an OTP — the **default** authentication method, not password |
| 3 | `REG-55`, `REG-56` | User verifies the OTP, or enters a password instead if they choose. The password option is **always offered**, regardless of whether this number has one set — choosing it never reveals account existence on its own; entering a password for a number with none set simply fails like any other wrong verification |
| 4a | `REG-57` | Verification succeeds, account exists → **logged in** directly |
| 4b | `REG-57` | Verification succeeds, no account → taken to the **registration flow** for their selected role |
| 4c | `REG-56` | Verification fails → generic error; no indication of whether an account exists |

This applies to all self-registering user types (litigant, PoA holder, advocate, clerk,
accused). Employee accounts are backend-created and follow a different login path (§6).

---

# 4. Litigant / PoA Holder registration

**[OWNER]** A simplified flow: verify the phone number, collect the name, done.
Address, ID proof, and other personal details are collected later in downstream flows
(case filing, bail applications) where they are needed and can be verified against
documents.

| ID | Step | Required | Notes |
| --- | --- | --- | --- |
| `REG-01` | Enter mobile number | Yes | Primary key for the account · **completed in the entry flow (§3)** |
| `REG-02` | Verify OTP | Yes | Proves access to the number · **completed in the entry flow (§3)** |
| `REG-03` | Name | Yes | **[OWNER]** collected during registration |
| `REG-04` | Add email | Optional | For case updates and as an alternative login method |
| `REG-05` | Create password | Optional | Can be **skipped** — see password reminder below |
| `REG-06` | Accept terms and conditions | Yes | **[OWNER]** required before account creation |

`REG-07` — the mobile number is the **primary key** for an account. No assumption is
made that the user has sole access to the number or that it is registered in their name.

`REG-08` — no approval or verification needed beyond OTP. Account is usable immediately.

`REG-09` `[DERIVED]` — the registration flow should **prompt** (not require) the user
to set a password and add an email, as fallbacks to SMS OTP. If the user skips password
setup, the reminder lifecycle below applies.

### Password setup — skip and reminder

**[OWNER]** Password setup during registration is offered but can be skipped entirely.

| ID | Requirement |
| --- | --- |
| `REG-58` | If the user skips password setup, the **next time they log in** a pop-up appears with three options: **Set a password** · **Remind me later** · **Don't remind me again**. |
| `REG-59` | **Remind me later** — the pop-up appears again on the next login. Repeats until the user sets a password or selects "Don't remind me again". |
| `REG-60` | **Don't remind me again** — no further pop-ups. |
| `REG-61` | Regardless of the user's reminder preference, **Set Password** and **Reset Password** are always available from **account settings**. |

This applies to all self-registering user types, not only litigants.

### Implicit account creation at signing

From the e-filing handover §18 (`[OWNER]`): account creation for **new complainants**
happens at signing — in e-sign mode, the party logs in with the phone number entered
for them (creating the account if it doesn't exist); in upload mode, per-party OTP
verification creates it. This is the path by which complainants who are not the filer
get accounts. **The registration module must support this implicit creation path** — a
verified phone number is sufficient.

| ID | Requirement |
| --- | --- |
| `REG-62` | **[OWNER]** — the first time the person behind an implicitly-created account logs in themselves (not the other party whose action created it), they are taken through the **registration flow**, not straight into the account — so they can set a password if they want, and accept the terms and conditions (`REG-05`, `REG-06`). |
| `REG-63` | **[OWNER]** — until that registration flow is completed, the account is **not complete**. |

This is the same registration flow as ordinary self-registration (§4) — an implicitly
created account is not a separate, lighter kind of account, only one that started from
a verified phone number instead of the person's own first login.

---

# 5. Advocate & Clerk registration

Two phases: the user submits their details, then a scrutiny officer approves.

## 5.1 Submission

| ID | Step / Field | Required | Advocate | Clerk | Notes |
| --- | --- | --- | --- | --- | --- |
| `REG-10` | Enter mobile number | Yes | ✓ | ✓ | Primary key · **completed in the entry flow (§3)** |
| `REG-11` | Verify OTP | Yes | ✓ | ✓ | **Completed in the entry flow (§3)** |
| `REG-12` | Full Name | Yes | ✓ | ✓ | |
| `REG-13` | Bar Registration ID | Yes | ✓ | — | Looked up against the Bar Council database |
| `REG-13a` | Clerk Registration Number | Yes | — | ✓ | **[OWNER]** clerks use their own identifier |
| `REG-14` | Photo of Bar ID card | Yes | ✓ | — | Uploaded; scrutiny officer uses it to verify |
| `REG-14a` | Photo of Clerk ID card | Yes | — | ✓ | **[OWNER]** |
| `REG-15` | Add email | Optional | ✓ | ✓ | |
| `REG-16` | Create password | Optional | ✓ | ✓ | Can be **skipped** — password reminder (§4) applies |
| `REG-16a` | Accept terms and conditions | Yes | ✓ | ✓ | **[OWNER]** |

**[OWNER]** Address and ID proof are **not collected** during registration.

## 5.2 Bar Council database — pre-fill and conflicts

`REG-17` `[CURRENT]` — advocate accounts are **auto-created from the backend** using
the Bar Council database. Accounts are only created when a mobile number exists in the
database.

`REG-18` **[OWNER]** — the **first time** an advocate logs in after their account was
auto-created from the backend, take them through the registration flow again with their
details **pre-filled**. If they edit anything, the updated request goes to the scrutiny
officer for verification (same approval flow as a fresh registration).

`REG-19` **[OWNER]** — when an advocate self-registers and the Bar ID is **already in
the system** with a different mobile number: show an error message telling them the Bar
ID is already registered and to **contact the help desk**. Display the help desk contact
details in the error message.

`REG-20` — the case where a Bar ID exists with **no mobile number** does not arise —
backend auto-creation only happens when a mobile number is present (`REG-17`).

## 5.3 Approval lifecycle

| State | Action | Next state |
| --- | --- | --- |
| — | Submit registration | Pending Approval |
| Pending Approval | Scrutiny officer approves | Approved — full access |
| Pending Approval | Scrutiny officer rejects | Rejected |
| Rejected | User edits details and resubmits | Pending Approval |

`REG-21` — rejections happen when details are incorrect (e.g. Bar ID doesn't match the
photo).

`REG-22` **[OWNER]** — the scrutiny officer provides a **free-text rejection reason**.

`REG-23` `[DERIVED]` — rejection–resubmission may repeat without limit.

`REG-24` **[OWNER]** — while **Pending Approval**, the user has **no access** from
their advocate/clerk account. If they also have a litigant account (same phone number),
they can switch to it and deal with any cases they have as a litigant.

---

# 6. Employee accounts

No self-registration. **[OWNER]** Backend-only is acceptable; no UI needed.

| ID | Requirement | Notes |
| --- | --- | --- |
| `REG-30` | Account created via HRMS or backend | No user-facing registration flow |
| `REG-31` | Role assigned during creation | Magistrate, Bench Clerk, CMO, Typist, Scrutiny Officer |
| `REG-32` | System generates an initial password | |
| `REG-33` | Credentials emailed to the user | User logs in with the emailed password |

`REG-34` `[CURRENT]` — employee login is **password-only**, no mobile number
requirement.

## 6.1 Courtroom mapping and login

Every court employee is **mapped to one or more courtrooms**. Formally, this is a 1:1
mapping for every employee role — magistrate, bench clerk, typist, scrutiny officer. In
practice this doesn't always hold — one person may need to cover more than one courtroom
— so the design accommodates it:

**Design:** rather than creating separate accounts for each courtroom a person works in,
every employee has **one account** with a list of assigned courtrooms. After login, they
select which courtroom they are working in. This means:

- A scrutiny officer handling 5 courtrooms has one account with 5 courtrooms in their
  list. They pick one after login and see that courtroom's cases. They can switch without
  logging out.
- A typist who is later asked to cover a second courtroom just gets that courtroom added
  to their list — no new account, no architecture change.
- A magistrate in a single courtroom has a list of one — the selector is still there but
  there is only one option.

| ID | Requirement | Notes |
| --- | --- | --- |
| `REG-35` | Each employee account carries a list of **assigned courtrooms** | Set during backend creation |
| `REG-36` | After login, the employee selects which courtroom to work in from their assigned list | If the employee is only mapped to one court room, this selection is not needed.  |
| `REG-37` | The employee can **switch courtrooms** without logging out | |
| `REG-38` | Adding or removing a courtroom from an employee's list is a backend/admin operation | No self-service |

---

# 7. Accused onboarding

**[OWNER]** Part of this module. The account creation process for an accused arriving
via a summons is the **same** as for a litigant (phone + OTP + name + terms, §4).

The onboarding journey itself — case papers, choices (settle vs contest), hearing date,
where to get help, joining the case — is specified separately in
`join-a-case-handover.md` §2c. It wraps around the same registration steps covered here.

---

# 8. Password policy

**[OWNER]**:

| ID | Rule |
| --- | --- |
| `REG-40` | Minimum **8 characters** |
| `REG-41` | Must not be the user's exact **mobile number** |
| `REG-42` | Must not be the user's exact **name** |
| `REG-43` | Must not be the user's exact **email address** |
| `REG-44` | Checked against a **blacklist of common passwords** |

No other complexity requirements (no mandatory uppercase/special characters).

---

# 9. Linked records

Live views of the master tables, filtered to this document. Each master table is the
single source of truth and the place to edit its rows; anything tagged
`account-creation-handover` there appears here automatically. A section showing nothing
means nothing is tagged for it yet. A downloaded copy of this document is a snapshot.

### Pending tasks (Court Side)

```superhuman-view
name: Pending tasks (Court Side) — Account Creation
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("account-creation-handover")
```

### Pending tasks (Citizen-Side)

```superhuman-view
name: Pending tasks (Citizen-Side) — Account Creation
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("account-creation-handover")
```

### Notifications

```superhuman-view
name: Notifications — Account Creation
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-xnftvTkudd/tables/grid-3FTjQhdfYv
filter: PRDs.Contains("account-creation-handover")
```

Notification copy itself is still pending the application-wide notifications master file
(e-filing handover `Q-1`).

### Events

```superhuman-view
name: Events — Account Creation
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-2x28DoUtbn/tables/grid-GPg4dKS-s9
filter: PRDs.Contains("account-creation-handover")
```

---

# 10. Owner decisions log

**2026-09-03** — Simplified litigant registration confirmed (phone + OTP + name only) ·
clerks use clerk registration number + clerk ID card photo · address and ID proof
dropped for advocate/clerk registration · Bar Council auto-created accounts: first login
takes the advocate through registration with pre-filled details; edits require
re-verification · Bar ID already registered with a different mobile → error + help desk
contact · free text rejection reason from scrutiny officer · no advocate/clerk access
while pending approval; can switch to litigant account · backend-only for employee
accounts · PoA Holder presented separately but same registration process and account
type as litigant · terms and conditions acceptance required · accused onboarding is part
of this module, same account creation process · password: min 8 chars, not exact
mobile/name/email, common password blacklist.

**2026-09-09** — Employee accounts mapped to courtrooms (`REG-35…38`) · one account per
person with a courtroom list, not separate accounts per courtroom; courtroom selector
after login; can switch without logging out · a scrutiny officer handling multiple
courtrooms has all of them in their list · scrutiny officer added to employee role list
(`REG-31`).

**2026-09-07** — OTP is the default authentication method, not password ·
authenticate first: the system verifies OTP or password before revealing whether an
account exists; no "account not found" message before successful authentication · after
successful verification, account exists → logged in, no account → registration flow ·
password setup during registration can be skipped; if skipped, next login shows a pop-up
with "Set a password" / "Remind me later" / "Don't remind me again" · "Remind me later"
re-shows the pop-up on next login · Set Password and Reset Password always available in
account settings regardless of reminder preference.

**2026-09-26** — An implicitly-created account (`REG-62/63`) is not complete on
creation: the first time that person logs in themselves, they go through the
registration flow to set a password if they want and accept terms and conditions.

---

# 11. Open questions — `Q`

| # | Question | Blocks |
| --- | --- | --- |
| Q-1 | **Help desk contact details** — what phone number / email / URL should the "contact help desk" error message display when a Bar ID conflict is found? | `REG-19`, §5.2 |

---

# 12. Not covered

Data model; API contracts; OTP rate limiting, expiry, max-attempts and lockout (not the
owner's call to make in this document); account deactivation/deletion; migration from
the current system's registration data; Bar Council database sync frequency and
ownership; notification copy (pending the application-wide notifications master file,
e-filing handover Q-1); common-password blacklist source; terms and conditions content;
password reset via forgot-password flow and account recovery (the Set Password / Reset
Password entry points in account settings are covered by `REG-61`).
