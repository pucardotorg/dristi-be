# Cause List Generation

**Status:** v1.8 — 2026-11-20; `Q-2` (sequences of stages and case number types) and `Q-5` (who marks the active case number) removed; `Q-3` reworded. v1.7 — 2026-11-20; new `CLG-16`: the sequence numbers of stages and hearing purposes are configured per state deployment. `Q-1` now asks for the master list of hearing purposes and their sequence; `Q-2` no longer covers hearing purposes. v1.6 — 2026-11-20; the note on why the whole sort can run again on every addition now sits directly under `CLG-15`. v1.5 — 2026-11-20; §4: Punjab & Haryana sorts by hearing purpose, then date of registration; `Q-3` now asks only about Gujarat. v1.4 — 2026-11-20; `CLG-07`, `CLG-08`, `CLG-10`: dates are compared to the finest precision the recorded time has, not to a fixed unit. v1.3 — 2026-11-20; note directly under `CLG-03`: the cause list generator's interface will expand as more sophisticated sorts are built, for example grouping one advocate's cases or taking hearing duration into account. v1.2 — 2026-11-20; the step that orders the day's hearings is called the **cause list generator** throughout (§1, §2, `CLG-01`–`CLG-04`, `CLG-15`, `ENH-03`). v1.1 — 2026-11-20; `CLG-09`: a case number is read according to its type's format — within a type, earliest year first, then lowest sequence number — not compared as plain text (`Q-4` answered). v1 — 2026-11-19; **ordering the cause list** written (§1–§5): the day's hearings are ordered by a separate step that takes the hearings in and returns them in order (`CLG-01`–`CLG-04`); each court establishment builds its sort from up to three levels, chosen from four criteria — stage, hearing purpose, date of filing or date of registration, and case number (`CLG-05`–`CLG-13`); hearings can be added until midnight before the day, and every addition reorders the whole list (`CLG-14`, `CLG-15`). Kerala's sort is case number (§4). Which matters are listed, and publishing and revising the list, are not written yet. v0 — 2026-10-30; placeholder, not written yet.
**Audience:** developers and agents building the cause list

How a courtroom's cause list for a day is generated, ordered, published and revised. This
version covers **ordering** only. Which matters are listed on a day, and publishing and
revising the list, are not written yet.

The cause list screen, including how it groups hearings by status, is in
[`order-generation.md`](order-generation.md) §10.1.

## 1. How the order is worked out

1. Hearings are scheduled for a courtroom on a day.
2. All of that day's hearings for the courtroom are passed to the **cause list generator**.
3. The cause list generator sorts them using the sort configured for the court establishment (§3, §4).
4. It returns the same hearings in order. Each hearing's position is its **item number**
   for the day: hearing 1, hearing 2, and so on.
5. Each time a hearing is added to the day, steps 2–4 run again on the whole day (§5).

## 2. The cause list generator

| ID | Requirement |
|---|---|
| `CLG-01` | The **cause list generator** is a separate step with one job: it takes a courtroom's hearings for a day and returns the same hearings in order. Nothing else decides the item numbers. |
| `CLG-02` | The cause list generator takes, for each hearing, only the fields the criteria in §3 need: the case's stage, the hearing purpose, the case's date of filing, its date of registration, and its active case number (`CLG-11`). |
| `CLG-03` | The cause list generator is built so that **more inputs and more criteria can be added** in later versions without changing how the rest of the system uses it. |
| | *As more sophisticated sorts are built — for example, ones that place one advocate's cases together, or that take into account how long each hearing will take — the cause list generator's interface will expand.* |
| `CLG-04` | A hearing's item number is its position in the order the cause list generator returned. It does **not change** when the hearing's status changes. Grouping by status on the cause list screen is a display of the list, not a reordering ([`order-generation.md`](order-generation.md) `CLS-02`). |
## 3. Sort criteria

A sort has **levels**. Level 1 orders all the hearings. Level 2 orders hearings that are
equal at level 1, and level 3 orders hearings that are equal at levels 1 and 2. Each level
uses one criterion from the master list below. This is the complete list in this version.

| ID | Criterion | How hearings are ordered |
|---|---|---|
| `CLG-05` | **Stage of the case** | Each stage in the master list of stages ([`case-lifecycle.md`](case-lifecycle.md) §3) has a **sequence number**. Hearings whose case is at the stage with the lowest sequence number come first. |
| `CLG-06` | **Hearing purpose** | Each hearing purpose in the master list of hearing purposes has a **sequence number** — for example, admission first and evidence last. Hearings whose purpose has the lowest sequence number come first. |
| `CLG-07` | **Date of filing** | Earliest first, compared to the finest precision the recorded time has. |
| `CLG-08` | **Date of registration** | Earliest first, compared to the finest precision the recorded time has. |
| `CLG-09` | **Case number** | Each case number type in the state's master list has a **sequence number** (Kerala: CMP, then ST, then LP). Hearings are grouped by the type of their case's active case number, lowest sequence first. Within each type, the number is read according to that type's format, not compared as plain text: where the format includes a year, the earliest year comes first, and within a year the lowest sequence number comes first. For example: CMP/3/2025, CMP/58/2025, CMP/3/2026, then ST/1/2025. Case number types and their formats are in [`case-numbers.md`](case-numbers.md). |

| ID | Requirement |
|---|---|
| `CLG-10` | Two hearings with exactly the same date of filing or date of registration, at the finest precision recorded, may come out in **either order**. |
| `CLG-11` | Where a case has more than one case number, the case number used is the one **marked active** for the case. Usually this is the latest number the case was given, but another can be marked active. |
| `CLG-12` | If every level of the sort is equal for two hearings, they may come out in **either order**. A court establishment that wants no ties uses date of filing, date of registration or case number as its last level. |

*A sort that ends on case number never ties, and one that ends on a date almost never does.
A court that chooses a sort that can tie, for example hearing purpose alone, has chosen to
accept that order within the tie.*

## 4. Configuring the sort

| ID | Requirement |
|---|---|
| `CLG-13` | The sort is configured **per court establishment**: up to three levels, each one criterion from §3. A state deployment can set one sort for all its court establishments. Every courtroom in a court establishment uses its sort, on every day. |
| `CLG-16` | The sequence numbers of stages and of hearing purposes are configured per state deployment. |

| State | Level 1 | Level 2 | Level 3 |
|---|---|---|---|
| Kerala | Case number (CMP, then ST, then LP) | — | — |
| Gujarat | *(open, `Q-3`)* | | |
| Punjab & Haryana | Hearing purpose | Date of registration | — |

## 5. Adding hearings to a day

| ID | Requirement |
|---|---|
| `CLG-14` | Hearings can be added to a day's cause list **until midnight at the start of that day**. For example, at 9 pm a hearing can still be added for the next day. |
| `CLG-15` | **Every time a hearing is added**, the cause list generator runs again on all of the day's hearings, and the day gets fresh item numbers. |
| | *Running the whole sort again on every addition is acceptable because today's sort is cheap.* |

## 6. Enhancements

| ID | Enhancement |
|---|---|
| `ENH-01` | In a later version, each courtroom can configure its own sort, and a courtroom can use a different sort on different days. |
| `ENH-02` | In a later version, more criteria can be added to the master list — for example, placing one advocate's cases together. |
| `ENH-03` | In a later version, with a more expensive sort, the cause list generator may run less often — for example, once at the end of the day, or after a number of hearings have been added — instead of on every addition. |

## 7. Open questions

| ID | Question | Blocking |
|---|---|---|
| `Q-1` | What is the master list of hearing purposes, and what is their sequence? | Yes, for any court that sorts on hearing purpose, including Punjab & Haryana |
| `Q-3` | What is the sorting logic for Gujarat? | Yes, for Gujarat |

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
