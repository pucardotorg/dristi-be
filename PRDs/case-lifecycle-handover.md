# Case Lifecycle

Status: Converted from PUCAR functional spec (PDF, undated). V1-specific event names removed; end triggers removed from primary stages; Post-Judgement, Post-Disposal, and Long Pending Register made sticky.

Source: `Case Lifeycle.pdf`

---

## 1. Context

A case on DRISTI progresses through a series of stages that together form the case lifecycle. These stages help users understand where a case currently stands in the judicial process and enable stage-wise tracking and analysis.

---

## 2. Triggers

There are multiple events that could occur within a case. The triggers described below refer to those events that are relevant for causing changes in the stages of a case.

---

## 3. Primary Stages

A case lifecycle is represented as a progression of **mutually exclusive** stages (for example: Filing → Scrutiny → Registration → Evidence → Judgement). At any given point in time, **a case can only be in one primary stage**.

### Transition rule

Whenever the start trigger tagged to a primary stage occurs, that stage becomes the primary stage of the case, **replacing any previous primary stage** the case was in.

### List of primary stages

| # | Primary Stage | Start Trigger | Notes |
|---|---|---|---|
| 1 | Filing | A draft case file is created | |
| 2 | Scrutiny | Case is submitted for scrutiny | |
| 3 | Defect Correction | Case is sent back by the scrutiny officer or magistrate for defect correction | |
| 4 | Registration | Scrutiny officer forwards the case to the judge | |
| 5 | Cognizance | Case is registered | |
| 6 | Appearance | Cognizance is taken | |
| 7 | Bail & Recording of Plea | The primary stage is Appearance AND a user belonging to the Accused side joins the case | In the case of multiple accused, even a single advocate/litigant from the Accused side joining the case moves the case from Appearance to this stage. |
| 8 | Complainant Evidence | Hearing is scheduled with purpose = Complainant Evidence AND the case is not in Post-Judgement, Post-Disposal, or Long Pending Register | |
| 9 | Examination of Accused | Hearing is scheduled with purpose = Examination of Accused AND the case is not in Post-Judgement, Post-Disposal, or Long Pending Register | |
| 10 | Defence Evidence | Hearing is scheduled with purpose = Defence Evidence AND the case is not in Post-Judgement, Post-Disposal, or Long Pending Register | |
| 11 | Arguments | Hearing is scheduled with purpose = Arguments AND the case is not in Post-Judgement, Post-Disposal, or Long Pending Register | |
| 12 | Mediation | Order for Mediation is issued | |
| 13 | Judgement | Hearing is scheduled with purpose = Judgement AND the case is not in Post-Judgement, Post-Disposal, or Long Pending Register | |
| 14 | Post-Judgement | Judgement order is passed | |
| 15 | Post-Disposal | Order for dismissal is passed, OR case is withdrawn, OR case is settled, OR case is transferred | |
| 16 | Long Pending Register | Workflow for moving case to long pending register is triggered | The case leaves LPR when the exit workflow is triggered. What the primary stage should be on exit is open — see OQ-1. |

---

## 4. Secondary Stages

During the lifecycle of a case, there are additional procedural processes that may occur **without changing the primary stage** of the case. These processes are captured using secondary stages. Examples include notices, summons, warrants, or defect correction.

These processes can:
- Occur at different points across the lifecycle.
- Be triggered **independently of the primary stage transitions**.
- Exist simultaneously with other such processes — **multiple secondary stages can be active at the same time**.

### Start trigger

Whenever the start trigger tagged to a secondary stage occurs, that secondary stage becomes active. This **does not affect any of the other active secondary stages**.

### End trigger

The end trigger for a secondary stage ends that secondary stage.

### List of secondary stages

| # | Secondary Stage | Start Trigger | End Trigger | Remarks |
|---|---|---|---|---|
| 1 | Delay Condonation | Case is registered AND the condition for delay condonation being required is met | Delay condonation application is accepted OR rejected | If the delay condonation application is filed as a miscellaneous application, or never filed (it is not technically mandatory), or never accepted/rejected, the case stays in this stage indefinitely. This is unlikely to occur, and no special handling is planned for it. |
| 2 | Notice | Notice workflow is triggered | Every active notice has reached a terminal state (delivered, expired, or status updated) | |
| 3 | Summons | Summons workflow is triggered | Every active summons has reached a terminal state (served, expired, or status updated) | |
| 4 | Warrant | Warrant workflow is triggered | Every active warrant has reached a terminal state (executed, expired, or status updated) | |
| 5 | Proclamation | Proclamation workflow is triggered | Every active proclamation has reached a terminal state (completed, expired, or status updated) | |
| 6 | Attachment | Attachment workflow is triggered | Every active attachment has reached a terminal state (completed, expired, or status updated) | |
| 7 | *(none)* | The end trigger for one of the other secondary stages occurs, following which the list of secondary stages becomes empty (no secondary stage is active) | The start trigger for any of the other secondary stages occurs | This represents the empty state between secondary stages. |

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

The following data events and analysis must be enabled:

- For a specific case, a list of all primary and secondary stages that were triggered, with the date each stage started and the date it was replaced.
- A stage-wise analysis of how long the case remains in each primary and secondary stage.

---

## 7. Open Questions

| # | Question | Blocking? |
|---|---|---|
| OQ-1 | When a case is moved out of Long Pending Register, what should the primary stage be? | Yes |
| OQ-2 | The full list of case outcomes needs to be confirmed. The source names Dismissed, Withdrawn, Convicted, Settled, and Transferred — what else? | Yes |

---

## References

- Whimsical board (case stage names): https://whimsical.com/case-stage-names-GaWnc9Rvzgx62HcpvvMyFA
