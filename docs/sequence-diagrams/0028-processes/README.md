# Summons, warrants and other processes: API sequences (spec 0028)

The API calls each process screen in the frontend design (`dristi-fe-design`) needs,
screen by screen. The screens are:

- the order screen's delivery-channel dialog (`order-variable-dialog.tsx`,
  `docs/design/features/order-delivery-channels.md`);
- the court's process line, `/employee/sign-process`, with its three tabs
  RPAD collection, Issuance and Service (`sign-process.ts`,
  `docs/design/features/sign-process-line.md`);
- the case's Notice/Process Status register (`case-process-status.tsx`);
- the party's steps (paying the process fee, handing in the cover).

Every call is marked:

- **[built]**: on `feature/summons_and_warrants` today;
- **[planned]**: in the signing, channel backends and notifications issue;
- **[blocked]**: waits on the orders module, 0029 or 0011;
- **[gap]**: needed by the design but in neither the code nor spec 0028 (see the last section).

All paths are under `/api/v1/`. List responses are `{data, meta}`, errors
`{errors: [{code, message, field}], meta}`.

## How the design's tabs and pills map to the backend

| Tab | Pill | Backend filter on `GET /processes/` |
|---|---|---|
| RPAD collection | Awaiting cover | `envelope_due=true` (add `fee_paid=true` if unpaid rows stay off this tab, design question A4) |
| Issuance | To sign | `status=PENDING_SIGNATURE` |
| Issuance | To post | `status=SIGNED&channel=RPAD&channel=POLICE_RPAD` |
| Issuance | To hand over | `status=SIGNED&channel=BY_HAND` |
| Issuance | To send (e-Post) | `status=SIGNED&channel=EPOST` |
| Issuance | Error | `status=ERRORED` |
| Service | In progress | `status=SENT` |
| Service | Completed | `status=DELIVERED&status=NOT_DELIVERED`, with `reason=` for the reason filter |

Sorts: *Soonest hearing first* is `ordering=hearing_date`, *Latest hearing first*
`ordering=-hearing_date`, and *Recently updated first* `ordering=-status_at`. The search box is
`search=` (case number, title or recipient name).

## 1. Ordering a process (order screen)

```mermaid
sequenceDiagram
    autonumber
    actor OD as Order drafter
    participant FE as Frontend
    participant BE as Backend
    participant ORD as Orders module

    OD->>FE: Choose "Issue of summons" (or warrant, notice...)
    FE->>BE: GET /process-types/ [built]
    BE-->>FE: 200 [{code, label, allowed_recipient_types,<br/>channels: [{code, label, destination_kind, preselected}]}]
    FE->>BE: GET /cases/{case_id}/process-recipients/ [built]
    BE-->>FE: 200 [{id, type, name, party_taking_steps, preselected,<br/>mobiles, emails, addresses}]
    opt A police channel is chosen
        FE->>BE: GET /locations/?location_type=police_station&search= [built]
        BE-->>FE: 200 [{code, name, ...}]
    end
    OD->>FE: Confirm recipients, channels, addresses, party taking steps
    FE->>ORD: Save the order item's values [blocked: orders]
    Note over ORD,BE: On trigger, after the hearing step, orders calls the processes handler in-process.<br/>No HTTP call. E12002-E12006 and E12017 come back through orders,<br/>with field = values.recipients[i]...
    ORD->>BE: start_from_order_item(...) [built, handler blocked: orders]
    BE-->>ORD: process ids
    BE-)BE: Notify the party taking steps: PROCESS_STEPS_DUE [planned]
```

## 2. The party's steps (pay the fee, hand in the cover)

```mermaid
sequenceDiagram
    autonumber
    actor P as Advocate or litigant
    participant FE as Frontend
    participant BE as Backend

    P->>FE: Open the case
    FE->>BE: GET /cases/{case_id}/processes/ [built]
    BE-->>FE: 200 [{recipient, groups: [{process_type, round, hearing, processes}]}]
    Note over FE,BE: The pay task itself comes from 0011 pending tasks [blocked: 0011]
    FE->>BE: GET /payments/demands/?case_id={case_id} [built]
    BE-->>FE: 200 demands with PROCESS_COURT_FEE items
    P->>FE: Pay
    FE->>BE: POST /payments/demands/{demand_id}/payments/ (one item, some, or all) [built]
    BE-->>FE: 201 payment, then the provider's flow
    BE-)BE: payment_completed: fee_paid set,<br/>PENDING_STEPS to PENDING_SIGNATURE once the cover is in [built]
    Note over P,BE: RPAD and Police (RPAD): the cover is handed in at the court counter. No party API.
```

## 3. RPAD collection tab (court: covers arriving)

```mermaid
sequenceDiagram
    autonumber
    actor CO as Court officer (process.receive_envelope)
    participant FE as Frontend
    participant BE as Backend

    CO->>FE: Open Process line, RPAD collection
    FE->>BE: GET /processes/counts/?court= [built]
    BE-->>FE: 200 {by_status, by_channel, by_status_channel, my_moves}
    FE->>BE: GET /processes/?court=&envelope_due=true&ordering=hearing_date [built]
    BE-->>FE: 200 {data: [{id, case, hearing, recipient, channel, destination,<br/>status, fee, envelope_received_at, signed_at, sent_at, allowed_actions}], meta}
    CO->>FE: Type a case number, press Enter (pile)
    FE->>BE: GET /processes/?court=&envelope_due=true&search={case_number} [built]
    BE-->>FE: 200 matching rows
    CO->>FE: Send N for signature
    FE->>BE: POST /processes/envelope/ {process_ids} [built]
    BE-->>FE: 200 {done, skipped} (PENDING_SIGNATURE where the fee is paid)
    alt refused
        BE-->>FE: 403 E12015 one process not allowed for its type and channel (nothing recorded)
        BE-->>FE: 400 E12016 too many in one request
    end
```

## 4. Issuance tab (court: sign, post, hand over, send, resend)

```mermaid
sequenceDiagram
    autonumber
    actor S as Process signer / dispatcher
    participant FE as Frontend
    participant BE as Backend
    participant ESP as e-Sign provider

    S->>FE: Open Issuance (To sign)
    FE->>BE: GET /processes/?court=&status=PENDING_SIGNATURE&ordering=hearing_date [built]
    BE-->>FE: 200 rows with allowed_actions (sign, recall)
    FE->>BE: GET /processes/{id}/ (single-row overlay) [built]
    BE-->>FE: 200 process + events
    FE->>BE: GET /processes/{id}/document/ (the paper beside the facts) [gap 4]

    S->>FE: Sign
    loop each selected process (Aadhaar e-sign: one at a time, SGM-03)
        FE->>BE: POST /processes/{id}/sign/ {method, send} [planned]
        BE-->>FE: 200 e-sign form fields
        alt refused
            BE-->>FE: 409 E12007 fee not paid / E12008 cover not received
            BE-->>FE: 400 E12010 method not enabled / 403 E12012 sign-and-send not allowed
        end
        FE->>ESP: Post the form, the signer authenticates
        ESP->>BE: POST /esign/_signed (callback) [built]
        BE-->>FE: redirect back with transaction_id
        FE->>BE: POST /processes/{id}/sign/confirm/ {transaction_id} [planned]
        BE-->>FE: 200 SIGNED, or SENT for SMS / Email / Police (iCOPS)
        Note over FE,BE: The design moves electronic channels on at signing,<br/>so the frontend sends send=true for them [planned]
    end
    BE-)BE: System send through the channel backend,<br/>ERRORED on a permanent failure [planned]

    alt To post / To hand over / To send (e-Post)
        FE->>BE: GET /processes/?court=&status=SIGNED&channel=... [built]
        FE->>BE: POST /processes/send/ {process_ids} [built]
        BE-->>FE: 200 {done: SENT, skipped}
    else Proclamation by hand, executed on download
        FE->>BE: GET /processes/{id}/document/ [gap 4]
        FE->>BE: POST /processes/{id}/send/ {published: true} [built]
        BE-->>FE: 200 DELIVERED (Executed), SENT and DELIVERED both recorded
    else Error pill
        FE->>BE: GET /processes/?court=&status=ERRORED [built]
        loop each selected process
            FE->>BE: POST /processes/{id}/resend/ [planned]
            BE-->>FE: 200 SENT, attempt + 1
        end
    end
```

## 5. Service tab (court: record returns)

```mermaid
sequenceDiagram
    autonumber
    actor R as Process reporter (process.record_outcome)
    participant FE as Frontend
    participant BE as Backend
    participant CH as Channel (SMS, Email, iCOPS)

    R->>FE: Open Service (In progress)
    FE->>BE: GET /processes/?court=&status=SENT&ordering=hearing_date [built]
    BE-->>FE: 200 rows, allowed_actions has record_outcome only on manual channels
    FE->>BE: GET /non-delivery-reasons/ [built]
    BE-->>FE: 200 [{code, label}] for the state
    R->>FE: Pile the returned covers, Record returns<br/>(one "Returned on" date, outcome per cover)
    opt A supporting file, per cover
        FE->>BE: POST /processes/{id}/outcome-file/ (multipart file) [built]
        BE-->>FE: 201 {file_id}
    end
    FE->>BE: POST /processes/outcome/ {outcome_date,<br/>outcomes: [{process_id, status, reason, comment, file_id}]} [built]
    BE-->>FE: 200 {done: DELIVERED / NOT_DELIVERED, skipped: system-reported channels}
    alt refused (nothing recorded)
        BE-->>FE: 400 E12014 / E12018 / E12019 with field outcomes[i].reason, .outcome_date, .file_id
        BE-->>FE: 403 E12015 one process not allowed
    end
    CH->>BE: POST /processes/channels/{channel}/_callback [planned]
    BE-)CH: poll_process_statuses every 15 minutes [planned]
    BE-)BE: Notify the case: PROCESS_OUTCOME_RECORDED [planned]

    R->>FE: Completed pill, filter by outcome or reason
    FE->>BE: GET /processes/?court=&status=NOT_DELIVERED&reason=REFUSED [built]
```

## 6. Recall (from Issuance or Service)

```mermaid
sequenceDiagram
    autonumber
    actor D as Court officer (process.recall)
    participant FE as Frontend
    participant BE as Backend

    D->>FE: Select processes, Recall, comment
    FE->>BE: POST /processes/recall/ {process_ids, comment} [built]
    BE-->>FE: 200 {recalled: [...], skipped: [...]}
    alt refused
        BE-->>FE: 403 E12015 one process outside the caller's access (nothing recalled)
        BE-->>FE: 400 E12016 too many in one request
    end
    BE-)BE: Unpaid fee item cancelled [built], backend told after a system send [planned],<br/>notify the case: PROCESS_RECALLED [planned]
```

## 7. The case's Notice/Process Status register

```mermaid
sequenceDiagram
    autonumber
    actor U as Court staff or a party
    participant FE as Frontend
    participant BE as Backend

    U->>FE: Open the case, Notice/Process Status
    FE->>BE: GET /cases/{case_id}/processes/ [built]
    BE-->>FE: 200 [{recipient, groups: [{process_type, round, hearing,<br/>processes: [{channel, destination, status_label, status_at, fee, reason, remark}]}]}]
    opt Download the signed document
        FE->>BE: GET /processes/{id}/document/ [gap 4]
    end
```

## Gaps between the design and the backend

| # | What the design does | What the backend has | Proposal |
|---|---|---|---|
| 1 | Signing a selection in one action | Signing is not built yet; with Aadhaar e-sign each document needs its own authentication (`SGM-03`) | Bulk signing needs DSC or batch e-sign (spec open question 3). Every other act on a selection has a bulk endpoint. |
| 4 | Download the signed paper, and show it in the single-row overlay | No endpoint serves a process's document (`signing_file_id` / `signed_file_id`) | Add `GET /processes/{id}/document/`, covered by the same read permissions as the detail. |
| 5 | Proclamation by hand is recorded Sent and Executed **when its signed copy is downloaded** | `POST /processes/{id}/send/ {"published": true}` | Frontend calls send with `published` on download. No backend change. |
| 6 | The order dialog pre-fills the police station, and after the accused joins pre-selects the unexamined witness | The recipients endpoint does neither | `AUT-04` needs spec open question 2; `AUT-06` needs examination to be recorded. |
| 8 | Non-delivery reasons: Address not found, Door locked, Person not present, Delivery refused, Other | Kerala seed: Addressee not available, Refused, Address incomplete, Left without instructions, Unclaimed, Lost in transit, Other | Agree on one list for Kerala (state master, `DSP-09`). |
| 10 | The Post officer sees only e-Post rows, and nothing before signing | The placeholder access ignores scope | Comes with 0029's scoped grants **[blocked: 0029]**. |
| 11 | e-Post, Email and Police (NSTEP) flows are drawn | Seeded unavailable in Kerala | Deployment choice. The flows work once a channel is made available. |
| 12 | Open in the design: India Post article number when posting | No field | Decide, then add to `send` for postal channels. |
