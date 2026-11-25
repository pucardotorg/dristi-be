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
| RPAD collection | Awaiting cover | `status=PENDING_STEPS` and `channel=RPAD&channel=POLICE_RPAD`; the cover still due needs a new filter **[gap 3]** |
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
    FE->>BE: GET /cases/{case_id}/process-recipients/ [gap 6]
    BE-->>FE: 200 [{id, type, name, addresses, mobiles, emails, defaults}]
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
    FE->>BE: GET /processes/counts/?court= [built, needs status x channel: gap 2]
    BE-->>FE: 200 {by_status, by_channel, my_moves}
    FE->>BE: GET /processes/?court=&status=PENDING_STEPS&channel=RPAD&channel=POLICE_RPAD<br/>&ordering=hearing_date [built, needs cover-due filter: gap 3]
    BE-->>FE: 200 {data: [{id, case, hearing, recipient, channel, destination,<br/>status, fee, allowed_actions}], meta}
    CO->>FE: Type a case number, press Enter (pile)
    FE->>BE: GET /processes/?court=&status=PENDING_STEPS&search={case_number} [built]
    BE-->>FE: 200 matching rows
    CO->>FE: Send N for signature
    loop each process in the pile [gap 1: no bulk endpoint]
        FE->>BE: POST /processes/{id}/envelope/ [built]
        BE-->>FE: 200 process (PENDING_SIGNATURE when the fee is paid)
    end
    alt refused
        BE-->>FE: 409 E12009 no envelope for this channel, or E12001 + allowed_actions
        BE-->>FE: 403 E12015 not allowed for this type and channel
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
        loop each selected process [gap 1]
            FE->>BE: POST /processes/{id}/send/ [built]
            BE-->>FE: 200 SENT
        end
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
    opt A supporting file
        FE->>BE: Upload the file [gap 7]
    end
    loop each cover [gap 1]
        FE->>BE: POST /processes/{id}/outcome/<br/>{status, reason, outcome_date, comment, file_id} [built]
        BE-->>FE: 200 DELIVERED / NOT_DELIVERED (Executed / Not executed for warrants)
        alt refused
            BE-->>FE: 400 E12014 reason required / E12018 outcome date
            BE-->>FE: 409 E12013 recorded by the system on this channel
        end
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
| 1 | Bulk acts on a selection: send for signature, sign, mark posted / sent, record returns with one date | One process per call (only recall is bulk) | Add bulk endpoints like recall's (`process_ids`, all or nothing on access), or the frontend loops. Bulk **signing** needs DSC or batch e-sign (spec open question 3). |
| 2 | Pill counts: To post, To hand over and To send are all `SIGNED`, split by channel | `counts` returns `by_status` and `by_channel` separately | Return counts per `(status, channel)` pair. |
| 3 | RPAD collection lists rows whose **fee is paid** and **cover is due**. The design assumes the fee always comes first. | `PENDING_STEPS` covers an unpaid fee, a missing cover, or both, in either order (`STP-03`) | Add `envelope_due` and `fee_paid` filters, and decide whether unpaid RPAD rows show on this tab. |
| 4 | Download the signed paper, and show it in the single-row overlay | No endpoint serves a process's document (`signing_file_id` / `signed_file_id`) | Add `GET /processes/{id}/document/`, covered by the same read permissions as the detail. |
| 5 | Proclamation by hand is recorded Sent and Executed **when its signed copy is downloaded** | `POST /processes/{id}/send/ {"published": true}` | Frontend calls send with `published` on download. No backend change. |
| 6 | The order dialog lists recipients with their addresses, pre-checked | `process_recipients` exists as a selector only. The §5.4 defaults are not built. | Add `GET /cases/{case_id}/process-recipients/` (or the orders module serves it) with the §5.4 defaults. |
| 7 | Attach a supporting file to a return | `outcome` takes a `file_id`, but there is no upload endpoint for it | Reuse the case document upload, or add an upload on the process. |
| 8 | Non-delivery reasons: Address not found, Door locked, Person not present, Delivery refused, Other | Kerala seed: Addressee not available, Refused, Address incomplete, Left without instructions, Unclaimed, Lost in transit, Other | Agree on one list for Kerala (state master, `DSP-09`). |
| 9 | Row status column shows each day: paid, sent for signature, signed, sent, returned | The list row has `status_at`, `fee.paid_at` and `outcome_date`. `envelope_received_at`, `sent_at` (detail only) and `signed_at` (nowhere) are missing. | Add those dates to the list serializer. |
| 10 | The Post officer sees only e-Post rows, and nothing before signing | The placeholder access ignores scope | Comes with 0029's scoped grants **[blocked: 0029]**. |
| 11 | e-Post, Email and Police (NSTEP) flows are drawn | Seeded unavailable in Kerala | Deployment choice. The flows work once a channel is made available. |
| 12 | Open in the design: India Post article number when posting | No field | Decide, then add to `send` for postal channels. |
