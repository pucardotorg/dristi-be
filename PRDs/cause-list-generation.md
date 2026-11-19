# Cause List Generation

**Status:** v1 — 2026-11-19; **ordering the cause list** written (§1–§5): the day's hearings are ordered by a separate step that takes the hearings in and returns them in order (`CLG-01`–`CLG-04`); each court establishment builds its sort from up to three levels, chosen from four criteria — stage, hearing purpose, date of filing or date of registration, and case number (`CLG-05`–`CLG-13`); hearings can be added until midnight before the day, and every addition reorders the whole list (`CLG-14`, `CLG-15`). Kerala's sort is case number (§4). Which matters are listed, and publishing and revising the list, are not written yet. v0 — 2026-10-30; placeholder, not written yet.
**Audience:** developers and agents building the cause list

How a courtroom's cause list for a day is generated, ordered, published and revised. This
version covers **ordering** only. Which matters are listed on a day, and publishing and
revising the list, are not written yet.

The cause list screen, including how it groups hearings by status, is in
[`order-generation.md`](order-generation.md) §10.1.

## 1. How the order is worked out

1. Hearings are scheduled for a courtroom on a day.
2. All of that day's hearings for the courtroom are passed to the **ordering step**.
3. The ordering step sorts them using the sort configured for the court establishment (§3, §4).
4. It returns the same hearings in order. Each hearing's position is its **item number**
   for the day: hearing 1, hearing 2, and so on.
5. Each time a hearing is added to the day, steps 2–4 run again on the whole day (§5).

## 2. The ordering step

| ID | Requirement |
|---|---|
| `CLG-01` | Ordering is a **separate step** with one job: it takes a courtroom's hearings for a day and returns the same hearings in order. Nothing else decides the item numbers. |
| `CLG-02` | The ordering step takes, for each hearing, only the fields the criteria in §3 need: the case's stage, the hearing purpose, the case's date of filing, its date of registration, and its active case number (`CLG-11`). |
| `CLG-03` | The ordering step is built so that **more inputs and more criteria can be added** in later versions without changing how the rest of the system uses it. |
| `CLG-04` | A hearing's item number is its position in the order the ordering step returned. It does **not change** when the hearing's status changes. Grouping by status on the cause list screen is a display of the list, not a reordering ([`order-generation.md`](order-generation.md) `CLS-02`). |

## 3. Sort criteria

A sort has **levels**. Level 1 orders all the hearings. Level 2 orders hearings that are
equal at level 1, and level 3 orders hearings that are equal at levels 1 and 2. Each level
uses one criterion from the master list below. This is the complete list in this version.

| ID | Criterion | How hearings are ordered |
|---|---|---|
| `CLG-05` | **Stage of the case** | Each stage in the master list of stages ([`case-lifecycle.md`](case-lifecycle.md) §3) has a **sequence number**. Hearings whose case is at the stage with the lowest sequence number come first. |
| `CLG-06` | **Hearing purpose** | Each hearing purpose in the master list of hearing purposes has a **sequence number** — for example, admission first and evidence last. Hearings whose purpose has the lowest sequence number come first. |
| `CLG-07` | **Date of filing** | Earliest first, compared to the millisecond. |
| `CLG-08` | **Date of registration** | Earliest first, compared to the millisecond. |
| `CLG-09` | **Case number** | Each case number type in the state's master list has a **sequence number** (Kerala: CMP, then ST, then LP). Hearings are grouped by the type of their case's active case number, lowest sequence first, and within each type ordered by number, lowest first: CMP 1, CMP 2, CMP 3, then ST 1, ST 2, ST 3. Case number types are in [`case-numbers.md`](case-numbers.md). |

| ID | Requirement |
|---|---|
| `CLG-10` | Two hearings with exactly the same date of filing or date of registration, to the millisecond, may come out in **either order**. |
| `CLG-11` | Where a case has more than one case number, the case number used is the one **marked active** for the case. Usually this is the latest number the case was given, but another can be marked active. |
| `CLG-12` | If every level of the sort is equal for two hearings, they may come out in **either order**. A court establishment that wants no ties uses date of filing, date of registration or case number as its last level. |

*A sort that ends on case number never ties, and one that ends on a date almost never does.
A court that chooses a sort that can tie, for example hearing purpose alone, has chosen to
accept that order within the tie.*

## 4. Configuring the sort

| ID | Requirement |
|---|---|
| `CLG-13` | The sort is configured **per court establishment**: up to three levels, each one criterion from §3. A state deployment can set one sort for all its court establishments. Every courtroom in a court establishment uses its sort, on every day. |

| State | Level 1 | Level 2 | Level 3 |
|---|---|---|---|
| Kerala | Case number (CMP, then ST, then LP) | — | — |
| Gujarat | *(open, `Q-3`)* | | |
| Punjab & Haryana | *(open, `Q-3`)* | | |

## 5. Adding hearings to a day

| ID | Requirement |
|---|---|
| `CLG-14` | Hearings can be added to a day's cause list **until midnight at the start of that day**. For example, at 9 pm a hearing can still be added for the next day. |
| `CLG-15` | **Every time a hearing is added**, the ordering step runs again on all of the day's hearings, and the day gets fresh item numbers. |

*Running the whole sort again on every addition is acceptable because today's sort is
cheap.*

## 6. Enhancements

| ID | Enhancement |
|---|---|
| `ENH-01` | In a later version, each courtroom can configure its own sort, and a courtroom can use a different sort on different days. |
| `ENH-02` | In a later version, more criteria can be added to the master list — for example, placing one advocate's cases together. |
| `ENH-03` | In a later version, with a more expensive sort, the ordering step may run less often — for example, once at the end of the day, or after a number of hearings have been added — instead of on every addition. |

## 7. Open questions

| ID | Question | Blocking |
|---|---|---|
| `Q-1` | Where are the sequence numbers for stages and hearing purposes kept, and who maintains them? | No |
| `Q-2` | The sequence of hearing purposes, of stages, and of case number types in Gujarat and Punjab & Haryana, are not yet received. | Yes, for any court that sorts on them |
| `Q-3` | What sort do Gujarat and Punjab & Haryana use? | Yes, for those states |
| `Q-4` | Within one case number type, numbers from different years — for example CMP/58/2025 and CMP/3/2026: is the year compared first, then the number? | Yes |
| `Q-5` | The active case number (`CLG-11`) is not yet in [`case-numbers.md`](case-numbers.md). Who marks a number active, and when? | No |

## Linked records

Live views of the master tables, filtered to this document. Each master table is the
single source of truth and the place to edit its rows; anything tagged
`cause-list-generation` there appears here automatically. A downloaded copy of this
document is a snapshot.

### Pending tasks (Court Side)

```superhuman-view
name: Pending tasks (Court Side) — Cause List Generation
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("cause-list-generation")
```

### Pending tasks (Citizen-Side)

```superhuman-view
name: Pending tasks (Citizen-Side) — Cause List Generation
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("cause-list-generation")
```

### Notifications

```superhuman-view
name: Notifications — Cause List Generation
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-xnftvTkudd/tables/grid-3FTjQhdfYv
filter: PRDs.Contains("cause-list-generation")
```

### Events

```superhuman-view
name: Events — Cause List Generation
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-2x28DoUtbn/tables/grid-GPg4dKS-s9
filter: PRDs.Contains("cause-list-generation")
```
