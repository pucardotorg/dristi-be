# Office Management — Developer & Agent Handover

**Status:** v4 — 2026-10-21; open questions answered: the person is notified **by SMS and in-app** (`OFC-08`, drafted in §6); a clerk or advocate in an office sees **only the cases shared with them** (`OFC-03`); **All cases includes drafts** (`OFC-25`, `OFC-25a`). §7 has no open questions left. v3 — 2026-10-21; **access is one choice per person: All cases or Specific cases** (`OFC-24`, `OFC-25`, `OFC-25a`): All cases is every current and future case, with no per-case removal; Specific cases is only the cases picked, with no future cases. The separate future-cases switch is gone; §3.2, §4, §5 rewritten to match. v2 — 2026-10-21; **a person accepts joining an advocate's office once** (`OFC-07`, `OFC-07a`, `OFC-07b`): until they accept, the cases shared with them wait; after that, further shares from that advocate are immediate. v1 — 2026-10-21; first version: People tab, adding a person (specific cases, all current cases, future cases), removing access, and the two other entry points (end of joining a case, sharing from a case or the cases list)
**Date:** 2026-10-21
**Audience:** developers and agents building office management (front end and backend)

Owner decisions are marked **[OWNER]**. `[DERIVED]` — inferred, confirm before building.
Requirement IDs: `OFC-*` — use in tickets, commits, test names.

---

# 1. What office management is

An advocate can give other people access to their cases so those people can work on them.
The people an advocate has given access to are that advocate's **office**. Access given
this way is **office access**.

| ID | Requirement |
| --- | --- |
| `OFC-01` | Only an **advocate** can add people to their office. |
| `OFC-02` | **[OWNER]** The person added must be a **registered DRISTI user** whose account is an **advocate** or a **clerk**. Litigants, PoA holders and court staff cannot be added. A person who is not registered cannot be added or invited. |
| `OFC-03` | **[OWNER]** Office access is given **per case**. A person in the office — clerk or advocate — sees **only the cases shared with them**, and no other case of the advocate. Working for an advocate does not by itself give access to that advocate's cases. |
| `OFC-04` | An advocate can share only **their own cases**: cases where they are on the vakalatnama, and **drafts** where they are an advocate (e-filing `FIL-05`). A case the advocate holds through someone else's office access cannot be shared onward. |
| `OFC-05` | Office access does not put the person on the vakalatnama or on the case record. An advocate who must act on the record is added to the case through a vakalatnama ([Join a Case](join-a-case-handover.md)), not through office management. |
| `OFC-06` | A person with office access has the rights on the case set out in [`people-and-case-access.md`](../../docs/people-and-case-access.md) (rows 12–13): the same as the advocate, except they **cannot e-sign**. They cannot add or remove anyone's access to the case. |
| `OFC-07` | **[OWNER]** The first time an advocate adds a person to their office, the person must **accept** before they get access. They are shown the advocate's name and the cases shared, and can **Accept** or **Decline**. Until they accept, the shared cases do not appear in their Your cases list. |
| `OFC-07a` | **[OWNER]** Acceptance is **once per advocate**. After a person has accepted an advocate's office, every further case that advocate shares with them, including new cases under All cases (`OFC-25`), is given **immediately**, without asking again. |
| `OFC-07b` | If the person declines, they get no access and leave the advocate's People list. The advocate can add them again, which asks them again. |
| `OFC-08` | **[OWNER]** The person added is notified **by SMS and in-app**: on first adding, with the request to accept (`OFC-07`); afterwards, when they are given more cases. The advocate is told in-app when the person accepts or declines. Wording in §6. |
| `OFC-09` | A person can be in the office of several advocates. Each advocate sees and manages only the access they gave. |

---

# 2. People tab

The People tab is the advocate's office: everyone they have given office access to.

| ID | Requirement |
| --- | --- |
| `OFC-10` | **People** is a top-level item in the advocate's navigation. |
| `OFC-11` | The list shows **only people the advocate has given office access to**. Co-advocates on the same vakalatnama are not listed here; they appear on the case's Parties tab and in its access list (§5.2). |
| `OFC-12` | Each row shows: name, mobile number, designation (**Advocate** or **Clerk**, from their account), and the number of the advocate's cases they can access. A person on **All cases** (`OFC-24`) is marked as such. A person who has not yet accepted (`OFC-07`) is marked **Awaiting acceptance**; the advocate can manage their cases and remove them as for anyone else. |
| `OFC-13` | The list can be searched by name or mobile number, and sorted by name or by number of cases. |
| `OFC-14` | **Add person** opens the add flow (§3). |
| `OFC-15` | Opening a person shows their detail (§4) beside the list, without leaving the page. |
| `OFC-16` | With no one in the office, the page says so and offers **Add person**. |

---

# 3. Adding a person

## 3.1 Finding the person

| ID | Requirement |
| --- | --- |
| `OFC-20` | **[OWNER]** The advocate searches registered advocates and clerks by **name**, **mobile number** or **Bar ID**. Results show name, designation and, for an advocate, Bar ID. |
| `OFC-21` | Results are limited to registered accounts of type advocate or clerk (`OFC-02`). A search that matches no one says that only registered advocates and clerks can be added. |
| `OFC-22` | People already in the advocate's office appear first in results. |
| `OFC-23` | More than one person can be selected and given the same access in one step. |

## 3.2 Choosing access

| ID | Requirement |
| --- | --- |
| `OFC-24` | **[OWNER]** Each person in the office has exactly one kind of access, chosen when adding them: **All cases** or **Specific cases**. There is no mix of the two. |
| `OFC-25` | **[OWNER]** **All cases** — office access to every one of the advocate's cases (`OFC-04`), **drafts included**, now and in future. A new draft is given to the person when it is created with the advocate on it; a case the advocate joins, when they are added to it. |
| `OFC-25a` | **Specific cases** — office access only to the cases the advocate picks from their own cases (`OFC-04`), drafts included, searchable by case title or number. Later cases are not given automatically. |
| `OFC-26` | **Add** gives the access and closes the flow. It needs at least one person, and, for Specific cases, at least one case. |
| `OFC-27` | Adding a person who is already in the office on Specific cases adds the newly picked cases to theirs; choosing All cases for them moves them to All cases. A person already on All cases holds every case, so the add flow does not offer them again. |
| `OFC-28` | The confirmation names who was added and to how many cases, and says when a person must first accept (`OFC-07`). |

---

# 4. Person detail

| ID | Requirement |
| --- | --- |
| `OFC-30` | Shows the person's name, mobile number, designation and Bar ID (advocates). |
| `OFC-31` | Shows the person's access — **All cases** or **Specific cases** — and lets the advocate change it. Changing **Specific → All** gives every current case and future cases. Changing **All → Specific** keeps the cases they hold now as their specific cases and stops future cases; the advocate can then remove cases. |
| `OFC-32` | Lists every case of the advocate the person can access — case title, case number, and the date access was given — searchable by title or number. Each case can be opened. |
| `OFC-33` | For a person on Specific cases: **Give access to more cases** opens the case picker (`OFC-25a`) for this person. |
| `OFC-34` | For a person on Specific cases: each case has **Remove**, which removes their access to that case; several cases can be selected and removed together. A person on All cases has no per-case removal (`OFC-31`). |
| `OFC-35` | **Remove from office** removes the person's access to all of the advocate's cases, whichever kind of access they had. They leave the People list. |
| `OFC-36` | Every removal is confirmed first, stating what the person will lose. Removal takes effect immediately; the case leaves the person's Your cases list. |
| `OFC-37` | Removing a Specific-cases person's last case removes them from the office; the confirmation says so. |

---

# 5. Other entry points

The same access is given from two other places. Both write to the same office: a person
added there appears on the People tab with that case.

## 5.1 End of joining a case

| ID | Requirement |
| --- | --- |
| `OFC-40` | When an advocate finishes joining a case ([Join a Case](join-a-case-handover.md), success step, `JOIN-57`), they can give people office access to that case. |
| `OFC-41` | People in the office on **All cases** already have access to the case by this point (`OFC-25`). The step lists them as already added. |
| `OFC-42` | The advocate can add others from their office or search for anyone else (`OFC-20`, `OFC-21`). The person is given this case as a specific case: someone new joins the office on Specific cases with this case. |
| `OFC-43` | The step is optional; leaving it gives no one access. |

## 5.2 Sharing from a case

| ID | Requirement |
| --- | --- |
| `OFC-50` | On a case page, **Share access** opens a dialog for that case. |
| `OFC-51` | The dialog finds people as in `OFC-20`–`OFC-23` and gives them this case as a specific case (`OFC-25a`); someone new joins the office on Specific cases. People on All cases already hold it and are not offered. |
| `OFC-52` | The dialog lists **who has access** on the advocate's side of the case: the advocates on the vakalatnama and everyone with office access. The advocate can remove the office access of a person on Specific cases here (`OFC-34`, `OFC-36`); a person on All cases is marked as such and is narrowed from the People tab (`OFC-31`). Removing an advocate on the vakalatnama is a court application, not a removal of access ([`people-and-case-access.md`](../../docs/people-and-case-access.md)). |
| `OFC-53` | An advocate who holds the case through office access sees the access list, but cannot add or remove anyone (`OFC-04`). |
| `OFC-54` | **[OWNER]** On the Your cases list, the advocate can select several cases and **Share access** to all of them in one step. This gives access only; it shows no access list and removes nothing. Each person is given the cases as specific cases; cases they already hold are skipped and the confirmation says how many. |

---

# 6. Notifications

Drafted 2026-10-21; to be added to the master Notifications table. `{#…}` are variables.
Every message names the advocate, so the person knows whose office it is.

| ID | Trigger | Recipient | Channels | Message |
| --- | --- | --- | --- | --- |
| `OFC-N1` | An advocate adds a person to their office for the first time (`OFC-07`), on Specific cases | The person added | SMS | {#advocatename} has added you to their office and shared {#count} case(s) with you. Log in to accept or decline: {#link} - On Courts |
| | | | In-app | **{#advocatename} wants to add you to their office.** They have shared {#count} case(s) with you. Accept to see them in Your cases. Actions: **Accept** · **Decline** |
| `OFC-N2` | As `OFC-N1`, on All cases | The person added | SMS | {#advocatename} has added you to their office with access to all their cases. Log in to accept or decline: {#link} - On Courts |
| | | | In-app | **{#advocatename} wants to add you to their office.** You will have access to all their cases, now and in future. Actions: **Accept** · **Decline** |
| `OFC-N3` | An advocate shares more cases with a person who has already accepted (`OFC-07a`), on Specific cases | The person | SMS | {#advocatename} has shared {#casetitle} with you. View it: {#link} - On Courts (for several cases: "{#count} cases") |
| | | | In-app | **{#advocatename} shared {#casetitle} with you.** Action: **Open case** (for several cases: "{#count} cases", action **Open Your cases**) |
| `OFC-N4` | The person accepts | The advocate | In-app | **{#personname} accepted your office invitation.** They can now work on the cases you shared. |
| `OFC-N5` | The person declines (`OFC-07b`) | The advocate | In-app | **{#personname} declined your office invitation.** They have no access to your cases. |

A person on All cases is **not** notified of each new case (`OFC-25`): at Gujarat's
volumes that would be one message per filing.

The SMS link opens the same request as the in-app notification.

---

# 7. Open questions

None currently.
