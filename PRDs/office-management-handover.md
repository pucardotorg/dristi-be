# Office Management — Developer & Agent Handover

**Status:** v1 — 2026-10-21; first version: People tab, adding a person (specific cases, all current cases, future cases), removing access, and the two other entry points (end of joining a case, sharing from a case or the cases list)
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
| `OFC-03` | Office access is given **per case**. A person in the office holds office access to each case shared with them, and to no other case of the advocate. |
| `OFC-04` | An advocate can share only cases where they are **on the vakalatnama**. A case the advocate holds through someone else's office access cannot be shared onward. |
| `OFC-05` | Office access does not put the person on the vakalatnama or on the case record. An advocate who must act on the record is added to the case through a vakalatnama ([Join a Case](join-a-case-handover.md)), not through office management. |
| `OFC-06` | A person with office access has the rights on the case set out in [`people-and-case-access.md`](../../docs/people-and-case-access.md) (rows 12–13): the same as the advocate, except they **cannot e-sign**. They cannot add or remove anyone's access to the case. |
| `OFC-07` | Access is given **immediately**. The person does not accept an invitation; the case appears in their Your cases list at once. |
| `OFC-08` | The person added is **notified** that they have been given access, naming the advocate and the cases. The channel is `Q-1`. |
| `OFC-09` | A person can be in the office of several advocates. Each advocate sees and manages only the access they gave. |

---

# 2. People tab

The People tab is the advocate's office: everyone they have given office access to.

| ID | Requirement |
| --- | --- |
| `OFC-10` | **People** is a top-level item in the advocate's navigation. |
| `OFC-11` | The list shows **only people the advocate has given office access to**. Co-advocates on the same vakalatnama are not listed here; they appear on the case's Parties tab and in its access list (§5.2). |
| `OFC-12` | Each row shows: name, mobile number, designation (**Advocate** or **Clerk**, from their account), and the number of the advocate's cases they can access. A person with **all future cases** on (`OFC-24`) is marked as such. |
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
| `OFC-24` | The advocate chooses which cases the person can access — one of: **All current cases** (every case where the advocate is on the vakalatnama, `OFC-04`) or **Specific cases** (picked from that same set, searchable by case title or number). |
| `OFC-25` | Separately, the advocate can turn on **All future cases**. When on, the person gets office access to every case the advocate is later added to on a vakalatnama, by filing or by joining, at the moment the advocate is added. It can be turned on together with either choice in `OFC-24`. |
| `OFC-26` | **Add** gives the access and closes the flow. It needs at least one person, and at least one case or All future cases. |
| `OFC-27` | Adding a person who is already in the office adds the newly chosen cases to their existing access; cases they already hold are left as they are. Turning on All future cases for them leaves their existing cases unchanged. |
| `OFC-28` | The confirmation names who was added and to how many cases. |

---

# 4. Person detail

| ID | Requirement |
| --- | --- |
| `OFC-30` | Shows the person's name, mobile number, designation and Bar ID (advocates). |
| `OFC-31` | Shows **All future cases** as an on/off control. Turning it off stops future cases being added; it does not remove access to any case they already hold. |
| `OFC-32` | Lists every case of the advocate the person can access — case title, case number, and the date access was given — searchable by title or number. Each case can be opened. |
| `OFC-33` | **Give access to more cases** opens the add flow (§3.2) for this person. |
| `OFC-34` | Each case has **Remove**, which removes the person's access to that case. Several cases can be selected and removed together. |
| `OFC-35` | **Remove from office** removes the person's access to all of the advocate's cases and turns off All future cases. They leave the People list. |
| `OFC-36` | Every removal is confirmed first, stating what the person will lose. Removal takes effect immediately; the case leaves the person's Your cases list. |
| `OFC-37` | Removing a person's access to every case one by one leaves them in the office only if All future cases is on; otherwise they leave the People list. |

---

# 5. Other entry points

The same access is given from two other places. Both write to the same office: a person
added there appears on the People tab with that case.

## 5.1 End of joining a case

| ID | Requirement |
| --- | --- |
| `OFC-40` | When an advocate finishes joining a case ([Join a Case](join-a-case-handover.md), success step, `JOIN-57`), they can give people office access to that case. |
| `OFC-41` | People in the office with **All future cases** on already have access to the case by this point (`OFC-25`). The step lists them as already added. |
| `OFC-42` | The advocate can add others from their office or search for anyone else (`OFC-20`, `OFC-21`). Someone new is added to the office with this case only. |
| `OFC-43` | The step is optional; leaving it gives no one access. |

## 5.2 Sharing from a case

| ID | Requirement |
| --- | --- |
| `OFC-50` | On a case page, **Share access** opens a dialog for that case. |
| `OFC-51` | The dialog finds people as in `OFC-20`–`OFC-23` and gives them office access to this case. |
| `OFC-52` | The dialog lists **who has access** on the advocate's side of the case: the advocates on the vakalatnama and everyone with office access. The advocate can remove office access here (`OFC-36`). Removing an advocate on the vakalatnama is a court application, not a removal of access ([`people-and-case-access.md`](../../docs/people-and-case-access.md)). |
| `OFC-53` | An advocate who holds the case through office access sees the access list, but cannot add or remove anyone (`OFC-04`). |
| `OFC-54` | **[OWNER]** On the Your cases list, the advocate can select several cases and **Share access** to all of them in one step. This gives access only; it shows no access list and removes nothing. Cases the person already holds are skipped and the confirmation says how many. |

---

# 6. Open questions

| ID | Question | Blocks |
| --- | --- | --- |
| `Q-1` | How is the person told they have been given access — SMS, in-app notification, or both? | `OFC-08` |
| `Q-2` | Is the office the same as the advocate↔clerk and advocate↔junior mapping that e-filing consumes to auto-add a filer's juniors and a clerk's advocates (`FIL-05`, `ADV-1`, `ROLE-02` in the [e-filing handover](efiling-handover.md))? If so, `ROLE-02` (a clerk sees every case of an advocate they work for) conflicts with per-case access (`OFC-03`). | `OFC-03`, `OFC-25` |
| `Q-3` | Do "all current cases" and future cases include the advocate's **drafts** not yet filed? | `OFC-24`, `OFC-25` |
