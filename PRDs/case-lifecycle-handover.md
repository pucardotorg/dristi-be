# Case Lifecycle

**Status:** v2 — 2026-10-30; **brought in line with the newer PRDs** and given requirement IDs (`CLC-*`). Filing covers Draft, Pending Signature and Pending Payment; a case enters Scrutiny when payment completes; Defect Correction starts on a send-back at Scrutiny or Registration; Registration starts when the Scrutiny officer forwards the case, and a case registered at Scrutiny skips it (`CLC-05`); hearing-purpose triggers use the catalogue's purpose names; Mediation starts on the **Referral of case to ADR** order item; **Abate case** joins the Post-Disposal triggers; stages change on signed order items, not workflows (`CLC-03`). Secondary stages end on the process statuses of [`process-handover.md`](process-handover.md) §10.1, so **Recalled** ends one and **Errored** does not. Delay Condonation ends on the acceptance item in the Take Cognizance order. Outcomes gain no new values; `OQ-2` now asks about the partial findings. New open questions `OQ-3`–`OQ-8`. v1 — converted from the PUCAR functional spec (PDF, undated); V1-specific event names removed; end triggers removed from primary stages; Post-Judgement, Post-Disposal and Long Pending Register made sticky.
**Audience:** developers and agents building case stages, stage display and stage-wise analysis

Source: `Case Lifeycle.pdf`. Requirement IDs: `CLC-*` — use in tickets, commits, test names.

---

## 1. Context

A case on DRISTI progresses through a series of stages that together form the case lifecycle. These stages help users understand where a case currently stands in the judicial process and enable stage-wise tracking and analysis.

The stage is not the case's workflow status. The statuses of filing, scrutiny and registration are owned by [`efiling-handover.md`](efiling-handover.md) §4 and [`scrutiny-registration-handover.md`](scrutiny-registration-handover.md) §3; the stage is a separate field derived from events.

---

## 2. Triggers

There are multiple events that could occur within a case. The triggers described below refer to those events that are relevant for causing changes in the stages of a case.

| ID | Requirement |
|---|---|
| `CLC-01` | Stages change only on the triggers in §3 and §4. |
| `CLC-02` | Where a trigger is an order item, the stage changes when the order carrying it is signed. |
| `CLC-03` | Stage changes are not workflows. A listener watches events — signed order items, scheduled hearings, filing and scrutiny actions, process statuses — and updates the stage ([`order-template-catalogue.md`](order-template-catalogue.md), *Case stage changes are not workflows*). |

---

## 3. Primary Stages

A case lifecycle is represented as a progression of **mutually exclusive** stages (for example: Filing → Scrutiny → Registration → Evidence → Judgement). At any given point in time, **a case can only be in one primary stage**.

### Transition rule

| ID | Requirement |
|---|---|
| `CLC-04` | Whenever the start trigger tagged to a primary stage occurs, that stage becomes the primary stage of the case, **replacing any previous primary stage** the case was in. A case stays in a stage until another stage's start trigger occurs — so a case sent back for correction stays in Defect Correction while it is signed and paid again, until it is resubmitted to Scrutiny. |
| `CLC-05` | A stage whose start trigger never occurs is skipped. A case registered at Scrutiny by someone holding both the Scrutiny officer and Case registerer roles (`SCR-11`) goes from Scrutiny to Cognizance and never enters Registration. |
| `CLC-06` | **Post-Judgement, Post-Disposal and Long Pending Register are sticky**: a scheduled hearing does not move a case out of them. The hearing-purpose triggers below apply only when the case is in none of the three. |

### List of primary stages

| # | Primary Stage | Start Trigger | Notes |
|---|---|---|---|
| 1 | Filing | A draft case file is created | Covers Draft, Pending Signature and Pending Payment ([`efiling-handover.md`](efiling-handover.md) §4). A deleted draft (`LIFE-14`) has no stage. |
| 2 | Scrutiny | Payment completes, or the filer resubmits after correction | [`scrutiny-registration-handover.md`](scrutiny-registration-handover.md) §3 |
| 3 | Defect Correction | The case is sent back at Scrutiny (Scrutiny officer) or at Registration (Case registerer) | The status during this stage is Pending Correction. |
| 4 | Registration | The Scrutiny officer forwards the case for registration (`SCR-16`) | Skipped when the case is registered at Scrutiny (`CLC-05`). |
| 5 | Cognizance | The case is registered — at Registration or at Scrutiny | |
| 6 | Appearance | Cognizance is taken | |
| 7 | Bail & Recording of Plea | The primary stage is Appearance AND a user belonging to the Accused side joins the case | In the case of multiple accused, even a single advocate/litigant from the Accused side joining the case moves the case from Appearance to this stage. See `OQ-7`. |
| 8 | Complainant Evidence | A hearing is scheduled with purpose = Evidence of the complainant (`CLC-06`) | |
| 9 | Examination of Accused | A hearing is scheduled with purpose = Examination of the accused under S. 351 BNSS (`CLC-06`) | |
| 10 | Defence Evidence | A hearing is scheduled with purpose = Evidence of the accused (`CLC-06`) | |
| 11 | Arguments | A hearing is scheduled with purpose = Arguments (`CLC-06`) | |
| 12 | Mediation | An order with the **Referral of case to ADR** item is signed | Whatever the mode of ADR. See `OQ-3`. |
| 13 | Judgement | A hearing is scheduled with purpose = Judgement (`CLC-06`) | |
| 14 | Post-Judgement | An order with the **Judgement** item is signed | See `OQ-4`. |
| 15 | Post-Disposal | An order is signed with any of: **Dismiss case**, **Withdrawal of case**, **Case settlement**, **Case transfer**, **Abate case** | Dismiss case is also offered at cognizance ([`cognizance-cheat-sheet.md`](cognizance-cheat-sheet.md) §6). |
| 16 | Long Pending Register | An order with the **Moving case to long pending register** item is signed | The case leaves LPR when an order with **Moving case out of long pending register** is signed. What the primary stage should be on exit is open — see `OQ-1`. |

---

## 4. Secondary Stages

During the lifecycle of a case, there are additional procedural processes that may occur **without changing the primary stage** of the case. These processes are captured using secondary stages. Examples include notices, summons and warrants.

These processes can:
- Occur at different points across the lifecycle — a notice can be issued before cognizance is taken ([`cognizance-cheat-sheet.md`](cognizance-cheat-sheet.md) §6).
- Be triggered **independently of the primary stage transitions**.
- Exist simultaneously with other such processes — **multiple secondary stages can be active at the same time**.

### Start and end triggers

| ID | Requirement |
|---|---|
| `CLC-07` | Whenever the start trigger tagged to a secondary stage occurs, that secondary stage becomes active. This **does not affect any of the other active secondary stages**. |
| `CLC-08` | The end trigger for a secondary stage ends that secondary stage. |
| `CLC-09` | A process secondary stage ends when every process of that type on the case is closed: it has reached a terminal status — Delivered / Executed, Not delivered / Not executed, Expired or Recalled — as defined in [`process-handover.md`](process-handover.md) §10.1. **Errored is not terminal** (`DSP-11`), so an errored process keeps the stage active. |

### List of secondary stages

| # | Secondary Stage | Start Trigger | End Trigger | Remarks |
|---|---|---|---|---|
| 1 | Delay Condonation | The case is registered AND delay condonation is required | The delay condonation application is accepted or rejected | The application comes in with the complaint ([`efiling-handover.md`](efiling-handover.md) §11) and is decided by the acceptance item added to the Take Cognizance order ([`cognizance-cheat-sheet.md`](cognizance-cheat-sheet.md) §6). See `OQ-5`. |
| 2 | Notice | A notice is issued | `CLC-09` | |
| 3 | Summons | A summons is issued | `CLC-09` | |
| 4 | Warrant | A warrant is issued | `CLC-09` | |
| 5 | Proclamation | A proclamation is issued | `CLC-09` | |
| 6 | Attachment | An attachment is issued | `CLC-09` | |
| 7 | *(none)* | The end trigger for one of the other secondary stages occurs, following which the list of secondary stages becomes empty (no secondary stage is active) | The start trigger for any of the other secondary stages occurs | This represents the empty state between secondary stages. |

Custom process (`process-handover.md` §2) has no secondary stage — see `OQ-6`.

---

## 5. Case Outcome

A case carries a case outcome field, maintained separately from the stage model. The outcomes named in the source are:

- Dismissed
- Withdrawn
- Convicted
- Settled
- Transferred
- Abated
- Acquitted

---

## 6. Tracking and Analysis

| ID | Requirement |
|---|---|
| `CLC-10` | For a specific case, a list of all primary and secondary stages that were triggered, with the date each stage started and the date it was replaced. |
| `CLC-11` | A stage-wise analysis of how long the case remains in each primary and secondary stage. |

---

## 7. Open Questions

| # | Question | Blocking? |
|---|---|---|
| OQ-1 | When a case is moved out of Long Pending Register, what should the primary stage be? DRISTI 1.0 restores the stage the case had when it entered the register, unless the exit order schedules a hearing, whose purpose then sets the stage. | Yes |
| OQ-2 | Are partial findings outcomes in their own right? DRISTI 1.0 also records Partially convicted, Partially acquitted, Allowed and Partially allowed, and a nature of disposal (Contested / Uncontested). | Yes |
| OQ-3 | A case can come back from ADR (catalogue, *Combination restrictions*). What returns it, and to which primary stage? Is Mediation the right name when the mode is arbitration or another mode? | No |
| OQ-4 | Is a judged case in Post-Judgement for good, or does it move to Post-Disposal — and on what? | No |
| OQ-5 | How does Delay Condonation end on a case dismissed at cognizance, where no acceptance item is passed? | No |
| OQ-6 | Does Custom process get a secondary stage of its own? | No |
| OQ-7 | Does Bail & Recording of Plea still start when an accused-side user joins, now that hearings can have the purposes Appearance, Bail and Plea? | No |
| OQ-8 | Which further events change the stage: restoration of a dismissed case, transfer into this court, an appeal or revision, compounding under §147? | No |

---

## References

- Whimsical board (case stage names): https://whimsical.com/case-stage-names-GaWnc9Rvzgx62HcpvvMyFA
