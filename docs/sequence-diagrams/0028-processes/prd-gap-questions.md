# Processes: design and backend gaps against the PRD

Each gap from [the API sequences](README.md), checked against the process PRD
(`PRDs/process-handover.md`), plus the further gaps that check found. Split into:

- **A. Questions for the design team**: where the design (`dristi-fe-design`) differs from the PRD
  or leaves something the PRD needs undrawn;
- **B. Backend gaps and questions**: where the backend (spec 0028 and
  `feature/summons_and_warrants`) falls short of the PRD, or needs a product decision;
- **C. Not a PRD question**: implementation choices the PRD leaves to us.

Design sources: `docs/design/features/sign-process-line.md`,
`docs/design/features/order-delivery-channels.md`, `src/lib/employee/sign-process.ts`.

## A. Questions for the design team

| # | Gap | PRD says | Question |
|---|---|---|---|
| A1 | **No recall.** The process line has no Recall act (`PROCESS_ACTS`: collect, sign, post, hand, send, resend, record). | `PIA-01`: a Process dispatcher recalls one or more processes with no outcome yet, sent or not. The screen may suggest every such process of that recipient in the round. | Where does Recall live (Issuance, Service, the single-row overlay, the case register)? Does it take a comment? Does it suggest the recipient's other processes in the round? |
| A2 | **No Expired or Recalled rows.** The pills cover awaiting cover → completed only. | §10.1: Expired and Recalled are terminal statuses. `EXP-02`: processes expire. | Where does a court officer see expired and recalled processes? A pill under Service, a filter, or only the case register? |
| A3 | **Electronic channels always go out on signing.** The design moves SMS, Email and iCOPS to In progress at Sign. | `DSP-02`, `SGN-04`: sign-and-send only for someone who holds **both** Process signer and Process dispatcher. Anyone else signs, and the process waits at Signed for a dispatcher to click Send. | What does a signer without dispatcher see after signing an SMS or iCOPS process? It needs a pill (e.g. "To send" for system channels; today "To send" is e-Post only) and a **Send** act that triggers the system send. |
| A4 | **RPAD collection assumes the fee is paid first** ("Every row has one — the fee comes first"). | §10.1 Pending steps: pay and hand in the envelope **in any order**. `STP-02`: the Envelope receiver records receipt. | Can a cover be received before the fee is paid? If so, where does that row show, and what does "Send for signature" do when the fee is still unpaid (it stays Pending steps)? Do unpaid processes show anywhere on the court side? |
| A5 | **The order dialog offers RPAD, SMS and Police** (owner-scoped). | §6.3 matrix, `AUT-08` preselection per type (SMS, Email, RPAD for notice/summons; Police (iCOPS) in Kerala for warrant and attachment; By hand for proclamation). Three police channels are distinct (`PRC-03`). | Can the dialog take its channels from `GET /process-types/` (type × deployment, with preselection), instead of a fixed three? Which of Police (RPAD) and Police (iCOPS) does "Police" mean? |
| A6 | **No police station in the order dialog.** | `PRC-03`, `PRC-08`, `AUT-04`: a police channel needs a police station from the master, pre-filled where one is held against the address. | Where is the station chosen, and how is a pre-filled one shown? |
| A7 | **Only summons and notice open the dialog.** | `PRC-01`: every Process-category item (notice, summons, warrant, proclamation, attachment, custom) starts processes. | Design the dialog for warrant, proclamation, attachment and custom process too (with their channel defaults and recipient rules). |
| A8 | **One accused only. No company persons in charge, witnesses or party taking steps.** | `PRC-02`: a company and each person in charge are separate recipients. `AUT-05`/`AUT-06`: recipient preselection rules. `AUT-03`: party taking steps is a choice when it can't be worked out. `AUT-09`: several recipients at once. | Design multi-recipient selection, persons in charge, witnesses, and the party-taking-steps choice. `AUT-08` also says a recipient with no destination for a channel is flagged beside them. How is that shown? |
| A9 | **No free-text comment in bulk Record returns** ("The legacy delivery dialog's Remarks field is not in bulk recording"). | `DSP-08`: every outcome carries a free-text comment and an optional supporting file. | Add a comment per cover (or one for the batch) to Record returns. Confirm the supporting file is per cover. |
| A10 | **Proclamation recorded Executed on download.** | `DSP-10` allows it, but sending is a Process dispatcher's act (`DSP-03`). | Is the download that records Sent and Executed limited to a Process dispatcher? Does a second download do nothing? Is it confirmed before recording? |
| A11 | **Non-delivery reasons** in the design: Address not found, Door locked, Person not present, Delivery refused, Other. | `DSP-09`: a state-configurable master, not fixed. | Confirm the design reads the list from the API (`GET /non-delivery-reasons/`) and doesn't hard-code it. The list itself is a product question (B6). |
| A12 | **Hearing date shown.** Rows show and sort by one hearing date. | `PRC-06`: screens may show the hearing's **current** date rather than the date at issue. A warrant prints no date but a QR code. | Which date does the line show and sort by, the date at issue or the current one? Is the warrant's QR scan screen designed? |
| A13 | **Channels drawn**: e-Post, Email and Police (NSTEP) next to iCOPS. | §13.1 Kerala: Email and e-Post post-launch, NSTEP never (iCOPS in its place). | Confirm the screens draw channels from the API per deployment, so Kerala never shows NSTEP. The e-Post channel fee (`FEE-02`) is post-launch. Is it out of these screens for now? |
| A14 | **"Send for signature" wording** on the RPAD collection act. | `STP-02`: the act is recording receipt of the envelope. The process moves to Pending signature by itself once the fee is also paid. | Fine to keep the wording, but the confirmation must not promise the process goes to signing when its fee is unpaid (A4). |
| A15 | **Bulk signing** of a selection. | `SGN-03`: several processes may be signed in one action, each signed separately underneath. | With Aadhaar e-sign each document needs its own authentication. Does the design walk through one e-sign per process, or does it wait for DSC / batch e-sign? |

## B. Backend gaps and questions

| # | Gap | PRD says | What's needed |
|---|---|---|---|
| B1 | **No document download.** No endpoint serves a process's rendered or signed PDF. | `DSP-10` (download records a proclamation Executed). The register shows the signed document (spec §11.3, view-case §7). | **Backend gap.** Add `GET /processes/{id}/document/` with the detail's read access. |
| B2 | **No recipients API for the order dialog**, and the §5.4 defaults aren't built. | §5.1 `AUT-01`–`AUT-09`, `PRC-02`, `PRC-05`. | **Backend gap.** Add an endpoint listing the case's recipients with destinations and defaults (`AUT-02`, `AUT-04`–`AUT-08`), or agree that the orders module serves it. |
| B3 | **No upload for an outcome's supporting file.** `outcome` takes a `file_id` from nowhere. | `DSP-08`: optional supporting file on every terminal outcome, manual or system. | **Backend gap.** Add an upload (on the process, or reuse the case document upload) and store files from system reports (`ChannelReport.file_bytes`). |
| B4 | **Signing, system send, resend, callbacks and notifications not built.** | §9, `DSP-02`, `DSP-11`, Notifications. | **Backend gap, planned** in the signing, channel backends and notifications issue. |
| B5 | **One fee demand per order item**, not per round. | `FEE-05`, `FEE-06`: the court fee is calculated for the round, with one payment task. | **Backend gap.** Group by round once orders hands over a round's items together **[blocked: orders]**. |
| B6 | **Non-delivery reasons for Kerala.** The seed is copied from the e-filing demand-notice reasons. The design has a different list. | `DSP-09`: state master. | **Product question:** what is Kerala's list for processes? |
| B7 | **Bulk signing method.** | `SGN-03` allows signing several in one action. | **Product question (spec open question 3):** DSC or batch e-sign, and when? Until then, signing is one e-sign per process. |
| B8 | **What moves SMS / Email to Delivered.** | §6.2: decided at implementation, or nothing. | **Product question (spec open question 4):** if nothing, SMS processes stay Sent for good and never leave the in-progress list. Agree on a rule. |
| B9 | **India Post article number** when marking posted (open in the design). | Not in the PRD. | **Product question:** is it recorded? If yes, it becomes an optional field on `send` for postal channels. |
| B10 | **Templates per channel.** The spec has per-channel templates with a fallback (`TPL-02`). | `TPL-01`: same template on every channel. Per-channel is "later". | **Backend question:** keep the per-channel option (harmless; one all-channel row per type) or drop it to match the PRD? The PDF format itself is `Q-16` (blocking). |
| B11 | **Recall after sending on a manual channel.** | `PIA-01`: the dispatcher recalls once the recall has been communicated. | Built as a plain recall. **Product question:** record how it was communicated (comment is enough?). |
| B12 | **Post officer sees e-Post only.** | court-roles §3. | **Backend gap [blocked: 0029]**: scoped grants by type and channel. |
| B13 | **Fee zero types.** | §13.2 Kerala: proclamation, attachment, custom ₹0. | Matches: no config row means ₹0. No action. |

## C. Not a PRD question (implementation choices)

The PRD leaves these to the implementer ("How the court staff's lists of processes are built
is for the implementer", `SGN-02`). These are backend tasks, not questions:

| # | Gap | Backend task |
|---|---|---|
| C1 | Bulk acts on a selection (receive envelope, send, record outcome) | Add bulk endpoints like recall's (`process_ids`, all or nothing on access), or the frontend loops. |
| C2 | Pill counts split `SIGNED` by channel | Return counts per `(status, channel)` pair from `GET /processes/counts/`. |
| C3 | RPAD collection needs "cover due" rows | Add `envelope_due` / `fee_paid` filters to `GET /processes/` (after A4 is answered). |
| C4 | Row status column shows each stage's day | Add `envelope_received_at`, `signed_at` and `sent_at` to the list serializer (`SGN-04`: each stage has its own timestamp). |
