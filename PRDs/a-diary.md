# A-Diary

**Status:** v1.5 — 2026-10-20; `ADY-12a`: the day's PDF is generated only at the time of signing, from the entries as they stand, as for orders (`PUB-01` of [`order-generation.md`](order-generation.md)); no 23:59 or on-demand generation (`Q-4` resolved, §6 removed). v1.4 — 2026-10-20; `ADY-06`: only orders create entries in this version; evidence marking and bulk reschedule notices are left for later (`Q-2` removed). The **Magistrate** holds A-Diary editor and A-Diary signer in every state (`Q-3` resolved, [`court-roles.md`](court-roles.md) §3). v1.3 — 2026-10-20; §5: the A-Diary is signed as the **whole day in one PDF**, one signature per courtroom per day, as in DRISTI 1.0; the PDF is generated at 23:59 or on demand, and a day can be signed only once it is over (`ADY-12`, `ADY-12a`, `ADY-12b`; `Q-1` resolved). The comparison with the prototype is removed. New `Q-4`: an entry edited after the PDF is generated. v1.2 — 2026-10-20; `ADY-09`: the entry and its order's A-Diary text are one text, always in sync — editing the entry changes the order's A-Diary text (the order text is not changed). New role **A-Diary signer** signs the A-Diary (`ADY-12`); `Q-1` no longer asks who signs. v1.1 — 2026-10-20; `ADY-04`: the entry is kept in full, never cut at a paragraph; shortening while showing is left to each screen. v1 — 2026-10-20; first draft. Takes over `Q-3` of
[`order-generation.md`](order-generation.md): who owns the A-Diary register and its
signing. New role **A-Diary editor** ([`court-roles.md`](court-roles.md)).

Sources: `PUB-04` of [`order-generation.md`](order-generation.md); the Sign A-Diary
screen in `Pucar-Dristi-2.0` (`main`; `apps/dristi-app/src/components/employee/sign-a-diary-*.tsx`,
`src/lib/employee/sign-a-diary.ts`), which runs on demo data with no backend; and the
A-Diary in DRISTI 1.0 (`dristi-solutions`, service `backend/dristi-services/ab-diary`,
workflow `case-a-diary`, screen `BulkSignADiaryView.js`), the live system.

---

## 1. Context

The **A-Diary** is the court's daily register: one line of business for each matter dealt
with that day, signed by the court. In DRISTI 1.0 it is also called the *Business of the
Day*.

| Out of scope | Owner |
|---|---|
| What an order's A-Diary text says by default, and who sets it | [`order-generation.md`](order-generation.md) `PUB-04` |
| Which roles exist, and who holds them in each state | [`court-roles.md`](court-roles.md) |
| The B-Diary (DRISTI 1.0 keeps one per case) | Not covered |

---

## 2. The register

| ID | Requirement |
|---|---|
| `ADY-01` | There is **one A-Diary per courtroom per day**. |
| `ADY-02` | Each **entry** belongs to one case and one day, and carries: the case number, the day, the **A-Diary text** (the business of the day), the next hearing's date and purpose, and the order it came from. |
| `ADY-03` | The A-Diary is read **one day at a time**, chosen by date; it opens on today. It lists each entry's case number, its A-Diary text and its next hearing date. |
| `ADY-04` | An entry's A-Diary text is **kept in full and never shortened** (`PUB-04`). Whether a screen shortens it while showing it is left to that screen. |

---

## 3. Where entries come from

| ID | Requirement |
|---|---|
| `ADY-05` | **An order** creates an entry on the day of its hearing when the order is **triggered** — signed and its order data complete (`CMP-04` of [`order-generation.md`](order-generation.md)). The entry's text is the order's A-Diary text (`PUB-04`). |
| `ADY-06` | In this version **only orders** create entries. DRISTI 1.0 also creates entries when a document is marked or unmarked as evidence, and when hearings are moved by a bulk reschedule notice; these are left for a later version. |

---

## 4. Editing an entry

| ID | Requirement |
|---|---|
| `ADY-07` | A person holding **A-Diary editor** can change an entry's A-Diary text until that day's A-Diary is signed. Once it is signed, nothing in it changes. |
| `ADY-08` | An entry's text cannot be left blank. |
| `ADY-09` | An entry made from an order and that order's **A-Diary text** (`PUB-04`) are **one text, always in sync**: editing the entry changes the order's A-Diary text. The **order text** is not changed. If the option *The A-Diary text and order text are the same* was checked, an edit that makes the two differ unchecks it. |
| `ADY-10` | The editor sees the entry's source beside its text — for an order, the order itself — so the text can be checked against it. |
| `ADY-11` | The rule that a signed day cannot be edited is **enforced server-side**. (DRISTI 1.0 enforced it only in the screen.) |

---

## 5. Signing

| ID | Requirement |
|---|---|
| `ADY-12` | The A-Diary is signed as **the whole day in one PDF**: one signature per courtroom per day, by a person holding **A-Diary signer** ([`court-roles.md`](court-roles.md)). Entries are not signed one by one. |
| `ADY-12a` | Until it is signed, the A-Diary is entries on screen. The day's PDF is **generated only at the time of signing**, from the entries as they stand, and stored signed — as for orders (`PUB-01` of [`order-generation.md`](order-generation.md)). |
| `ADY-12b` | A day can be signed **only once it is over** — never on the same day. |
| `ADY-13` | Signing is with Aadhaar e-sign or a DSC, as for orders (`SGN-05` of [`order-generation.md`](order-generation.md)). |
| `ADY-14` | Signing **cannot be undone**. |
