# 0038 — SBIePay Payment Gateway Addon (`addon.sbiepay_payment_gateway`)

## Status

Proposed

## References

- Issue #290 — *[Enhancement] Spec for Payments using SBIePay* ("Add as an addon")
- [0017 — Payments Module](0017-orders-management.md) — `apps.payments`, the consuming module; owns demands, payments, balances, the provider contract (#9), the callback endpoint, polling and every API error code
- [0022 — e-GRAS Payment Gateway Addon](0022-addon-egras-payment-gateway.md) — the first redirect-gateway addon; this spec follows its structure and decisions wherever SBIePay allows
- [0032 — Offline Payment Addon](0032-addon-offline-payment.md) — payer-selectable providers (`PAYMENT_SELECTABLE_PROVIDERS`), which lets SBIePay sit next to e-GRAS and the counter
- [0000 — API Coding Spec](0000-api-coding-spec.md) — error shape and codes (#9)
- *SBIePay Merchant Integration Guide*, v2.3.7 (Jul 2023), State Bank of India — shared as `Merchant Integration Doc.docx`; section names below ("Guide §…") refer to it

> **Scope note.** SBIePay is a *payment gateway*, not a payments module: the
> addon owns the SBIePay wire protocol and nothing else. Demands, payments,
> balances, idempotency, concurrency, permissions, the callback endpoints,
> polling, audit and every API error code stay in
> [`apps.payments`](0017-orders-management.md). The addon implements the
> provider contract of [0017](0017-orders-management.md) #9 and is selected
> only through the `PAYMENT_PROVIDERS` / `PAYMENT_DEFAULT_PROVIDER` /
> `PAYMENT_SELECTABLE_PROVIDERS` settings. A deployment can add, replace or
> remove it without changing any caller.

## Context

[0017](0017-orders-management.md) gives Dristi one payments module that
case filing, resubmission, process fees, applications, join-a-case and bulk
filing all use. [0022](0022-addon-egras-payment-gateway.md) added the first real
provider, e-GRAS, which pays into state treasury heads of account.
[0032](0032-addon-offline-payment.md) added counter collection and let a payer
choose between providers.

SBIePay is State Bank of India's payment aggregator. A deployment that collects
through an SBI merchant account (rather than, or as well as, a state treasury)
needs it. Its contract differs from e-GRAS in ways that matter to the design:

| Concern | e-GRAS (0022) | SBIePay |
| --- | --- | --- |
| Outbound request | Plain form fields | One AES-encrypted, pipe-separated packet (`EncryptTrans`) plus the plain merchant id |
| Who picks the bank | Dristi, before redirect (`bank` field) | The payer, on SBIePay's hosted page (net banking, cards, UPI, wallets, NEFT, branch cash) |
| Amounts | Whole rupees | Two decimals: paise are carried as-is |
| Split of the money | Government heads of account (`SCHEMENAME`) | Optional *Multiaccount* split by settlement-account identifier |
| Browser response | Plain or AES-GCM `payRes` | AES-encrypted `encData` posted to a success or fail URL |
| Server-to-server notification | None | **Push response**: an encrypted `pushRespData` posted to a whitelisted merchant URL |
| Authoritative status | SOAP lookup by application number | **Double Verification (DV)** web service, a plain HTTPS form POST queried by merchant order number |
| Final-outcome window | 8th day | `BOOKED` resolves after next-day reconciliation; still `BOOKED` on the 7th day becomes `EXPIRED` |
| Re-use of a reference | Never | The same merchant order number may be posted up to **3 times**. Only one attempt can succeed |
| Network allow-listing | None | SBI whitelists our business (source) URL, our push URL and public IP, and the IP our DV calls come from |

The guide also lists four other APIs as mandatory for SBI's integration
sign-off: Refund & Cancellation, Refund Enquiry, Payout and Transaction MIS
(Guide "Mandatory APIs for Successful Integration"). 0017 rules refunds and
settlement reconciliation out of scope (#10). #12 explains how this spec handles
that gap.

## Goals

- Ship `SBIePayPaymentProvider` in a standalone, removable module that
  implements the provider contract of 0017 #9 without changing it.
- Keep every SBIePay detail (packet layouts, encryption, merchant id and key,
  order numbers, DV calls, status vocabulary) inside
  `addon/sbiepay_payment_gateway/`.
- Enforce a one-way source dependency: the addon imports
  `apps.payments.providers.base`, and `apps.payments` never imports the addon.
- Never credit a payment on a browser or push response alone. Only DV confirms.
  Never report a final failure that SBIePay has not declared.
- Support single-demand payments and cross-demand batches (bulk filing,
  bulk applications) in one SBIePay transaction.
- Use the aggregator-hosted page, so card data never touches Dristi and Dristi
  stays out of PCI-DSS scope.
- Send SBIePay no personal data it does not need.
- Keep each concern (crypto, packet building, response parsing, verification,
  status mapping, account split) independently unit-testable.

## Non-goals

- Anything 0017 owns: demands, payments, balances, numbering, permissions,
  receipts, the callback endpoints, polling, cancellation, reconciliation flags
  and API error codes.
- Fee calculation, rounding, or SBIePay's own commission/GST policy. The addon
  records the fee SBIePay reports. It never adds the fee to a demand.
- The **merchant-hosted** integration type (Dristi capturing card, CVV or VPA
  data), and with it the Payment packet (Guide Table 2). It would put Dristi in
  PCI-DSS scope.
- The Billing and Shipping packets (integration models BP and BSP). The payer
  is not asked to re-enter data we would have to send, and we send none (#4.6).
- International operating mode (`INTL`) and non-INR currencies.
- Booking refunds or cancellations, refund enquiry, payout files and
  transaction MIS inside Dristi (#12).
- TPV (third-party validation) and mobile-app-specific integration beyond what
  #4.8 notes.
- Any models, migrations, URLs, views, admin or `errors.py` in the addon.
- A second provider registry, Dramatiq actor or retry policy in the addon.

---

## 1. Module placement and dependency direction

```text
src/
├── apps/
│   ├── payments/                    # 0017 — domain, APIs, provider contract, callback + push endpoints
│   └── ...
├── addon/
│   ├── cdac_sms_gateway/            # 0013
│   ├── cdac_esign/                  # 0015
│   ├── egras_payment_gateway/       # 0022
│   ├── offline_payment/             # 0032
│   └── sbiepay_payment_gateway/     # THIS SPEC — SBIePay wire protocol
└── config/settings/base.py          # the only wiring point
```

```text
addon.sbiepay_payment_gateway  -- imports -->        apps.payments.providers.base
apps.payments                  -- never imports -->  addon.*
config.settings.base           -- references -->     "addon.sbiepay_payment_gateway.provider.SBIePayPaymentProvider"
```

The addon imports the contract (`PaymentProvider`, its dataclasses and its
exception types from `apps.payments.providers.base`). For configuration and
system checks it also uses the same read-only helpers e-GRAS uses:
`apps.payments.conf` (is `"sbiepay"` registered?),
`apps.payments.checks.is_production_settings`, and the
`apps.payments.enums.ChargeType` values (for the unmapped-account warning,
#4.5). It never imports `apps.payments` models, services, selectors, tasks,
views, serializers, signals, the registry or the mock.
`tests/test_isolation.py` enforces exactly this list, and also checks that no
module under `apps.*` mentions `sbiepay`.

Django registration:

```python
# config/settings/base.py
INSTALLED_APPS = [
    ...
    "apps.payments",
    # Addons
    "addon.cdac_sms_gateway",
    "addon.egras_payment_gateway",
    "addon.offline_payment",
    "addon.sbiepay_payment_gateway",
]
```

The addon is an installed app only so it can register system checks. Its
`AppConfig` sets `name = "addon.sbiepay_payment_gateway"` and
`label = "sbiepay_payment_gateway"`. Deleting the package and its settings
leaves `apps.payments` working on the remaining providers.

### 1.1 Layout

```text
src/addon/sbiepay_payment_gateway/
├── __init__.py
├── apps.py                  # AppConfig(name="addon.sbiepay_payment_gateway")
├── provider.py              # SBIePayPaymentProvider(PaymentProvider)
├── config.py                # SBIePayConfig, resolve_config(), load_key() (cached, frozen)
├── constants.py             # packet field order, status vocabulary, failure codes, log events
├── crypto.py                # encrypt()/decrypt() for SBIePay packets (#7)
├── packets.py               # pipe/caret encoding, allowed characters, field lengths
├── accounts.py              # charge lines -> MultiAccountInstructionDtls (optional, #4.5)
├── request_builder.py       # InitiationRequest -> EncryptTrans (+ multi-account) form fields
├── response_parser.py       # decrypted browser/push string -> SBIePayResponse
├── callback_parser.py       # encData / pushRespData form -> ProviderCallback (untrusted)
├── verification_client.py   # Double Verification HTTPS call (TLS, timeout)
├── status_mapper.py         # DV record -> ProviderStatus
├── checks.py                # Django system checks
└── tests/
    ├── __init__.py
    ├── conftest.py          # test key, fixed vectors
    ├── test_config.py
    ├── test_crypto.py       # kit test vectors, round trip, random IV
    ├── test_packets.py
    ├── test_accounts.py
    ├── test_request_builder.py
    ├── test_response_parser.py
    ├── test_callback_parser.py
    ├── test_verification_client.py
    ├── test_status_mapper.py
    ├── test_checks.py
    ├── test_flow.py         # create → browser/push → DV → SUCCESS, mocked SBIePay
    ├── test_coexistence.py  # selectable with egras and offline
    └── test_isolation.py
```

---

## 2. End-to-end flow

```text
Dristi UI
   |  GET  /api/v1/payments/providers/options/                 -> lists "sbiepay" (no options) when selectable
   |  POST /api/v1/payments/demands/{id}/payments/
   |       {client_request_id, demand_item_ids, payer, provider: "sbiepay"}
   v
apps.payments                                                          [0017 #6.2, #9.4]
   +-- Payment(s) INITIATED, COMMIT
   +-- registry.get_for_new_payment("sbiepay") -> SBIePayPaymentProvider   [0032 #4.2]
   +-- provider.initiate(InitiationRequest)                             [addon, #4]
   |       order number, Other Details, EncryptTrans (AES), merchIdVal
   |       -> ProviderInitiation(REDIRECT_FORM)
   +-- mark_pending(provider="sbiepay", provider_payment_id=<order number>)
   v
201 {payment..., provider_action: {kind: REDIRECT_FORM, url, method, form_fields}}
   |
   v
browser auto-submits form ---> SBIePay hosted page ---> bank / card / UPI ---> SBIePay
                                                                              |   |
         (browser) POST /api/v1/payments/providers/sbiepay/_callback  <-------+   |
                   encData, merchIdVal, Bank_Code                    [0017 #9.6]  |
         (server)  POST /api/v1/payments/providers/sbiepay/_push   <--------------+
                   pushRespData, merchIdVal, Bank_Code               [#10, new]
                                                                 |
apps.payments                                                    v
   +-- provider.parse_callback(form) -> ProviderCallback(trusted=False)        [addon, #5]
   +-- provider.fetch_status(order number)  -> DV web service                  [addon, #6]
   +-- apply_provider_status(payments, status)                                 [0017 #9.5]
   v
browser: HTTP 302 -> PAYMENT_UI_REDIRECT_URL ; UI polls GET /api/v1/payments/payments/{id}/
server:  HTTP 200 "OK"
```

SBIePay sends the browser response and the push response for the same
transaction, usually seconds apart. Both go through the same parse → verify →
apply path. 0017 #9.5 makes the second one a no-op. If neither arrives (tab
closed, push blocked, SBIePay slow), the 0017 poller (#9.7) reaches the same
`apply_provider_status` through `fetch_status`. Both responses only speed things
up. Neither is required.

---

## 3. Responsibility boundary

| Concern | Owner |
| --- | --- |
| Demands, items, balances, statuses, numbering, idempotency, permissions | `apps.payments` (0017) |
| Provider choice for a new payment; routing by `Payment.provider` | `apps.payments` (0017 #9.3, 0032 #4.2) |
| Browser callback endpoint, CSRF, throttling, UI redirect | `apps.payments` (0017 #9.6) |
| Server push endpoint (#10) | `apps.payments` (amendment in this spec) |
| Applying an outcome; amount check; late success; mismatch; flags | `apps.payments` (0017 #9.5) |
| Polling; pending-horizon enforcement; cancel check | `apps.payments` (0017 #9.7, #9.8) |
| API error codes and the error response shape | `apps.payments` (0017 #12.5) |
| SBIePay configuration and key loading | addon `config.py` |
| AES encryption / decryption of packets | addon `crypto.py` |
| Packet encoding, allowed characters, lengths | addon `packets.py` |
| Merchant order number, Other Details, transaction packet | addon `request_builder.py` |
| Settlement-account split (Multiaccount) | addon `accounts.py` |
| Browser / push response parsing | addon `response_parser.py`, `callback_parser.py` |
| DV call, TLS, timeout | addon `verification_client.py` |
| SBIePay status vocabulary → `ProviderOutcome` | addon `status_mapper.py` |

Rule of thumb, as in 0013 and 0022: **if removing SBIePay tomorrow would delete
the code, it belongs in the addon. Otherwise it belongs in `apps.payments`.**
The push endpoint (#10) is the one exception that needs a change in
`apps.payments`. It is generic: it names no gateway, and any provider with a
server-to-server notification can use it.

Where SBIePay identifiers land, all in the generic fields of 0017 #2.3:

| SBIePay concept | Dristi field |
| --- | --- |
| Merchant Order Number (our correlation id) | `Payment.provider_payment_id` |
| ATRN / SBIePay Reference ID | `Payment.provider_reference`, the gateway transaction id printed on every receipt of a batch (BLK-15) |
| CIN, Bank Reference Number, Bank Code, Pay Mode, `Total Fee^GST`, status description | `Payment.metadata["provider"]` |
| failure reason | `Payment.failure_code`, e.g. `SBIEPAY_PAYMENT_FAILED` |

---

## 4. Initiation

### 4.1 Transport and integration type

```text
Browser form POST, application/x-www-form-urlencoded
action = SBIEPAY_PAYMENT_URL     (".../secure/AggregatorHostedListener", per environment)
```

- **Aggregator-hosted, model P (Only Payment).** Guide Table 1 requires only the
  Transaction packet. The payer picks the pay mode and bank on SBIePay's page.
- Dristi never posts this form from the server. The provider returns
  `ProviderAction(kind=REDIRECT_FORM, url=SBIEPAY_PAYMENT_URL, method="POST",
  form_fields=...)`, and the UI renders a hidden form and submits it, treating
  `form_fields` as opaque (0017 #12.2), the same way it does for e-GRAS and
  eSign ([0015](0015-cdac-esign.md) #6.1).
- `list_options()` returns `[]`. No choice is needed before the redirect, so
  the UI shows no bank picker for SBIePay.

### 4.2 Form fields

| Form field | Value | Notes |
| --- | --- | --- |
| `EncryptTrans` | `crypto.encrypt(transaction_packet)` (#4.3, #7) | parameter names are case-sensitive (Guide "Handling Case Sensitivity") |
| `merchIdVal` | `SBIEPAY_MERCHANT_ID` | plain text; required before every packet |
| `MultiAccountInstructionDtls` | `crypto.encrypt(account_packet)` (#4.5) | only when `SBIEPAY_MULTI_ACCOUNT_ENABLED` |

No other packet is sent.

### 4.3 Transaction packet

```text
EncryptTrans = MerchantID|OperatingMode|MerchantCountry|MerchantCurrency|PostingAmount|
               OtherDetails|SuccessURL|FailURL|AggregatorID|MerchantOrderNumber|
               MerchantCustomerID|Paymode|AccessMedium|TransactionSource
```

| # | Field | Value | Limit |
| --- | --- | --- | --- |
| 1 | Merchant ID | `SBIEPAY_MERCHANT_ID` | ≤ 20, no spaces |
| 2 | Operating Mode | `DOM` | — |
| 3 | Merchant Country | `IN` | — |
| 4 | Merchant Currency | `INR` (#4.7) | — |
| 5 | Posting Amount | `request.amount`, formatted `0.00` (#4.7) | Decimal(17,2) |
| 6 | Other Details | #4.4 | ≤ 1000, ≤ 30 caret fields |
| 7 | Success URL | `SBIEPAY_RETURN_URL` | ≤ 200, `https://` |
| 8 | Fail URL | `SBIEPAY_RETURN_URL` (the same endpoint) | ≤ 200, `https://` |
| 9 | Aggregator ID | `SBIEPAY` | — |
| 10 | Merchant Order Number | `provider_payment_id` (#4.4) | ≤ 100 |
| 11 | Merchant Customer ID | `NA` | the guide reserves it for future use |
| 12 | Paymode | `SBIEPAY_PAYMODE`, default `NB` | the guide's default for aggregator-hosted. The hosted page still offers every mode SBI enabled for the merchant |
| 13 | Access Medium | `ONLINE` | — |
| 14 | Transaction Source | `ONLINE` | — |

The success and fail URLs are the same 0017 callback endpoint. The outcome comes
from DV, not from which URL SBIePay chose, so splitting them gains nothing.

### 4.4 Merchant Order Number and Other Details

```text
MerchantOrderNumber = SBIEPAY_ORDER_PREFIX + upper(request.reference.hex)
e.g.  "DR" + "0F9D3A6C1B2E4F5A7B8C9D0E1F2A3B4C" -> "DR0F9D3A6C1B2E4F5A7B8C9D0E1F2A3B4C"   (34 characters)
```

- It is derived from `reference` (the batch id, or the payment id), so it is
  deterministic, unique per collection attempt, and traceable to Dristi by
  prefix. Unlike e-GRAS there is no 20-character limit, so the full UUID is
  used and no truncation collisions are possible.
- A retry in Dristi is a new `Payment` (0017 #4), so it gets a new order number.
- An idempotent replay of a `PENDING` payment returns the same form (#7.3). If
  the payer posts it again, SBIePay treats it as another attempt on the same
  order number. SBIePay allows three attempts and rejects a new attempt on an
  order that already succeeded ("PLEASE DO NOT RE-INITIATE", Guide Annexure B
  rows 21, 53). So one order number can never collect twice.
- The prefix (≤ 4 alphanumeric characters, default `DR`) keeps Dristi traffic
  apart in SBIePay support queries and settlement files.

**Other Details** is a free-text field that appears in SBIePay's settlement
report. It is used only to make settlements traceable:

```text
^DRISTI^<payment number or batch reference>^<demand number>^<demand number>^...^
```

- It has at most 30 caret-delimited fields and at most 1000 characters, with
  carets at both ends (Guide Table 4, field 6). When the demand numbers do not
  fit, they are cut to whole numbers and the last field becomes `AND N MORE`.
- Every value passes through `packets.clean()`. That keeps letters, digits and
  the guide's allowed characters (`_ . @ / space , - : '`), and removes `|`,
  `=`, `^` and anything else. Correlation never depends on this field.

### 4.5 Settlement accounts (Multiaccount, optional)

SBIePay can settle one transaction into several of the merchant's bank
accounts. Each account is identified by an *account identifier* configured in
the SBIePay merchant panel. This is SBIePay's counterpart of e-GRAS heads of
account. It is **off by default** in code, and when off every rupee settles
into the merchant's single account.

The PRD expects the money to be split. e-filing handover §19.1 sends the
Advocate Welfare Fund and Stipend Stamp to a separate remittance account
(a TSB account under head `8031-00-102-94-07-00-00-N-V`). It leaves the other
heads' accounts as `[GAP]`, and Q-5 makes every remittance account per-state
configuration. So for Kerala a single-account setup is a finance workaround,
not the target. Whether SBIePay can settle into a treasury TSB account at all
is open (Q-6). `SBIEPAY_ACCOUNT_MAP` is per-deployment configuration, which
matches the PRD's "per state, never hard-coded" rule.

When `SBIEPAY_MULTI_ACCOUNT_ENABLED` is on, `accounts.py` builds:

```text
for each ChargeLine:
    account = SBIEPAY_ACCOUNT_MAP[line.account_head]      if present
           or SBIEPAY_ACCOUNT_MAP[line.charge_type]        if present
           or ProviderPermanentError(SBIEPAY_ACCOUNT_UNMAPPED)

group lines by account, sum amounts per account
order accounts by identifier                              (determinism, 0017 #9.2 rule 2)
sum of account amounts == request.amount                  else SBIEPAY_AMOUNT_INCONSISTENT

MultiAccountInstructionDtls = amt1|INR|acct1||amt2|INR|acct2||...
```

- The rules match 0022 #4.3. `account_head` is looked up first. An
  `account_head` value is **never** used directly as an identifier, so whoever
  raises a demand cannot choose where the money settles. **There is no default
  account**, because money in the wrong account is worse than a refused payment.
- A batch across several demands produces one account split for the whole
  transaction. The per-demand breakup stays in `PaymentDemandItem`.

### 4.6 Payer data

Model P sends **no payer data**. `Payer` is used only for masked logging. The
SBIePay page collects what the chosen bank or card needs from the payer
directly.

- Dristi never holds card, CVV, VPA or bank login data, and never sends a
  litigant's address, phone or email to a third party it does not need to.
- If SBI requires payer contact details for its own SMS/e-mail notification
  (Guide "Transaction Notification via E-mail and SMS"), that needs the Billing
  packet. That is open question Q-4 and is not built here.

### 4.7 Currency and amounts

- `currency` must be `INR`, else `SBIEPAY_UNSUPPORTED_CURRENCY`.
- `request.amount` must be `> 0` and carry at most two decimal places, else
  `SBIEPAY_AMOUNT_INVALID`. 0017 stores paise, so this only catches a caller
  bug. **The addon never rounds.** Unlike e-GRAS, a `₹12.50` court fee is
  posted as `12.50`.
- The amount is formatted with exactly two decimals (`775.00`, `12.50`).
- The Posting Amount *excludes* SBIePay's commission and GST (Guide Table 4,
  field 5). If SBI is set up to charge the fee to the customer, the payer pays
  more than the demand on SBIePay's page. Dristi still credits exactly
  `request.amount`, and the reported `Total Fee^GST` is kept in metadata for
  the receipt (Q-3).

### 4.8 Browser and allow-listing requirements

These are not code, but initiation fails without them:

- **Business (source) URL.** SBIePay rejects a request that does not come
  from the whitelisted business URL ("Wrong Source URL"), and declines any
  request without `Origin` and `Referer` headers (Guide Annexure B, row 55).
  The page that auto-submits the form must be served from the URL registered
  with SBI, and it must not suppress the referrer (no
  `Referrer-Policy: no-referrer`). The browser default,
  `strict-origin-when-cross-origin`, sends only the *origin* cross-site. It is
  unconfirmed whether SBI matches on the domain or on the full URL (Q-9). If it
  matches the full URL, the UI must either use one fixed payment-hand-off route
  or relax its referrer policy for that route.
- **Mobile.** A mobile client that opens the form in a web view must set
  `Origin` and `Referer` headers (Guide "For Integration via Mobile"), and UPI
  requires UPI intent support in the app. Mobile clients are not in scope here.
  The requirement is recorded so the mobile team does not have to rediscover it.

---

## 5. Browser and push responses

### 5.1 What arrives

| Channel | Endpoint | Fields |
| --- | --- | --- |
| Browser | `POST …/providers/sbiepay/_callback` (0017 #9.6) | `encData`, `merchIdVal`, `Bank_Code` |
| Server push | `POST …/providers/sbiepay/_push` (#10) | `pushRespData`, `merchIdVal`, `Bank_Code` |

The decrypted value has the same layout on both channels (Guide "Message
Structure of 'Push Response'"):

```text
MerchantOrderNumber|ATRN|TransactionStatus|Amount|Currency|PayMode|OtherDetails|
Reason|BankCode|BankReferenceNumber|TransactionDate|Country|CIN|MerchantID|
TotalFee^GST|Ref1|…|Ref9
```

`TransactionStatus` is `SUCCESS`, `FAIL` or `PENDING`.

### 5.2 Parsing rules

`callback_parser.parse(payload) -> ProviderCallback`:

- It reads `encData`, or `pushRespData` if `encData` is absent. With neither,
  it raises `ProviderCallbackMalformed(SBIEPAY_CALLBACK_MALFORMED)`.
- If `merchIdVal` is present and differs from `SBIEPAY_MERCHANT_ID`, it raises
  `ProviderCallbackMalformed(SBIEPAY_MERCHANT_MISMATCH)`. A response meant for
  another merchant id (for example a UAT response reaching production) is never
  correlated.
- It decrypts with `crypto.decrypt` (#7). If decryption fails (wrong key,
  tampered or truncated value, bad padding) it raises
  `ProviderCallbackMalformed(SBIEPAY_RESPONSE_DECRYPT_FAILED)`. The order
  number is inside the ciphertext, so this callback cannot be correlated:
  `apps.payments` redirects `status=UNKNOWN` (or answers the push with `200`)
  and the poller resolves the payment by its stored order number.
- `response_parser` splits on `|` by position and accepts extra trailing fields.
  It requires at least the 15 fields up to `Total Fee^GST`. The Merchant ID
  field must equal `SBIEPAY_MERCHANT_ID`. The order number must match
  `SBIEPAY_ORDER_PREFIX` and the expected length. Any violation raises
  `ProviderCallbackMalformed`.
- `trusted` is **always `False`** (#5.3). The hinted status, ATRN, amount, pay
  mode and reason are parsed into `ProviderStatus`, which is used only to
  select the payment. They are recorded in the `SBIEPAY_CALLBACK_RECEIVED` log
  line and never applied.

### 5.3 Why responses are never trusted

The responses *are* encrypted with the merchant key, so a forger needs the key.
They are still not treated as proof:

1. **SBI requires DV.** The guide makes Double Verification "a mandatory part
   of the integration process … to avoid the data tampering in browser
   redirection" and the only way to resolve `BOOKED` transactions.
2. **The cipher is not authenticated.** The guide's kit uses AES-CBC. Unlike
   e-GRAS's AES-GCM `payRes`, CBC alone does not prove integrity, so it does
   not meet the bar of 0017 #9.2 rule 3 ("verified cryptographically").
3. **A browser `FAIL` can be wrong.** If an order that already succeeded is
   posted again, SBIePay answers `FAIL` ("Your earlier transaction was
   successful…"). Applying that hint would be wrong. DV returns the real
   outcome.
4. **One verification path is simpler to reason about.** Browser, push and
   poller all end in the same `fetch_status`.

---

## 6. Verification (Double Verification / Status Query)

### 6.1 Call

```text
HTTPS POST SBIEPAY_VERIFY_URL      (".../payagg/statusQuery/getStatusQuery", per environment; case-sensitive)
Content-Type: application/x-www-form-urlencoded
  queryRequest = |<MerchantID>|<MerchantOrderNumber>|
  aggregatorId = SBIEPAY
  merchantId   = <MerchantID>
timeout: SBIEPAY_TIMEOUT          TLS 1.2+, certificate verification on (SBIEPAY_VERIFY_SSL)
```

- The lookup is **always by our own order number**. The ATRN is left blank,
  even when a callback supplied one, so a forged callback cannot point DV at a
  different transaction. The guide marks ATRN optional (Guide Table 6).
- **Amount is left blank.** The guide's table calls Merchant Posted Amount
  mandatory, but its own samples show a request "Without Amount", and
  `fetch_status` receives only `provider_payment_id` (0017 #9.1). The amount is
  compared in `apps.payments` (0017 #9.5) instead. If SBI's UAT rejects a blank
  amount, Q-2 covers the fallback.
- The request is plain text. The response is a plain pipe-separated string
  (Guide "Sample 'Transaction Response' — for Double Verification/Query API").
  If the response turns out to be encrypted in an environment, the client
  decrypts it with the same key before parsing. That is decided by trying the
  plain parse first, never by a setting.
- `requests` is used with an explicit timeout. Transport errors, timeouts,
  non-2xx responses and unparsable bodies raise `ProviderTransientError`
  (`SBIEPAY_VERIFY_TIMEOUT`, `SBIEPAY_VERIFY_UNAVAILABLE`,
  `SBIEPAY_VERIFY_MALFORMED`). A body that is one of SBIePay's request-error
  messages ("Invalid Merchant Id", "No valid merchant packet", "Invalid
  ATRN", …) raises `ProviderTransientError(SBIEPAY_VERIFY_REJECTED)` and is
  logged at error. Usually it is a configuration or allow-list problem. The
  poller keeps retrying and the payment never fails on it.
- SBI must whitelist the public IP that DV calls come from. Both the `web`
  service (callbacks) and the `worker` service (poller) call DV, so both need
  the same static egress IP (#13).

### 6.2 Response

```text
MerchantID|ATRN|TransactionStatus|Country|Currency|OtherDetails|MerchantOrderNumber|
Amount|StatusDescription|BankCode|BankReferenceNumber|TransactionDate|PayMode|CIN|
MerchantID|TotalFee^GST|Ref1|…|Ref10

1000020|2011578958428|SUCCESS|IN|INR|^DRISTI^…^|DR0F9D…4C|775.00|Payment Success|sbiepay|
202116676766687|2026-10-15 19:44:00|UPI|10000202026101500074|1000020|4.50^0.81||||||||||
```

### 6.3 Status mapping (`status_mapper.py`)

| SBIePay `TransactionStatus` (case-insensitive, trimmed) | Extra conditions | `ProviderOutcome` | `failure_code` / `reconciliation_code` |
| --- | --- | --- | --- |
| `SUCCESS` (`Payment Success`, `Payment In Clearing`, `Transaction Settled`, `Transaction Paid Out`) | ATRN non-empty, Amount parses, order number and merchant id match | `SUCCESS` | — |
| `SUCCESS` | ATRN missing or Amount unparsable | `PENDING` | `SBIEPAY_SUCCESS_INCOMPLETE` |
| `FAIL` | — | `FAILED` | `SBIEPAY_PAYMENT_FAILED` |
| `EXPIRED` | still `BOOKED` on the 7th day with no money debited | `FAILED` | `SBIEPAY_EXPIRED` |
| `ABORT` | session expired before the payer finished | `NOT_FOUND` | `SBIEPAY_ABORTED` (see below) |
| `NO RECORDS FOUND` | — | `NOT_FOUND` | — |
| `PENDING` (maker/checker authorisation), `BOOKED` (no bank response yet), `INPROGRESS` | — | `PENDING` | — |
| `CANCELLED`, `REFUND` | money was collected and is being or has been returned | `FAILED` | `SBIEPAY_REVERSED` in both fields, so the payment is also flagged |
| `CLOSED` or anything else | — | `PENDING` | `SBIEPAY_UNKNOWN_STATUS`, logged at warning |

- **`ABORT` maps to `NOT_FOUND`, not `FAILED`.** An abandoned session moved no
  money, so it is the same as the payer never reaching the bank. But the same
  order number can still be posted again (#4.4). `NOT_FOUND` lets 0017's
  `not_found_grace` (#6.4) pass before the payment fails and its items become
  payable again. During that window a second attempt can still succeed and be
  credited normally rather than as a late success.

  *What the payer sees:* a litigant who abandons SBIePay's page and comes back
  can resume straight away. `GET /api/v1/payments/payments/{id}/action/`
  re-shows a pending payment's form (0032 #4.8), and posting it again is
  another attempt on the same order number. A replay of the original
  `client_request_id` does the same (0017 #7). SBI allows three attempts, so a fourth is refused by SBI, and the
  payment then fails once the grace passes. What they *cannot* do for up to
  `not_found_grace` is **cancel** it to pay another way, such as at the
  counter: 0017 #9.8 answers `409 E06012` while `NOT_FOUND` is within grace.
  e-GRAS has the same two-hour behaviour. The UI should offer "resume
  payment" rather than "cancel" for a recently abandoned SBIePay payment.
- **`CANCELLED` / `REFUND`** only happen when someone cancels or refunds
  through SBIePay, which Dristi never does (#12). They are operator actions, so
  the payment fails and is also flagged `needs_reconciliation`
  (`PAYMENT_PROVIDER_FLAGGED`, 0017 #9.5). A refund made after Dristi already
  credited the payment is *not* detected here, because the poller only polls
  `PENDING` payments. That belongs to the reconciliation work in #12.
- Unknown vocabulary maps to `PENDING`, never `FAILED` (0017 #9.2 rule 5).
- `ProviderStatus.amount` is `Decimal(Amount)` and `provider_reference` is the
  ATRN. `paid_at` is `TransactionDate` read as IST, or `None` if unparsable.
  `metadata` carries `cin`, `bank_code`, `bank_reference`, `pay_mode`,
  `status_description`, `fee` and `gst` (from `Total Fee^GST`), and
  `transaction_date`.
- The amount comparison against the Dristi payment happens in `apps.payments`
  (0017 #9.5), not here. The provider reports and the payments module decides.

### 6.4 Timing

| Provider attribute | SBIePay value | Why |
| --- | --- | --- |
| `pending_horizon` | `SBIEPAY_PENDING_HORIZON`, default 8 days | `BOOKED` turns `EXPIRED` on the 7th day (Guide Annexure B row 5). One day of margin |
| `not_found_grace` | `SBIEPAY_NOT_FOUND_GRACE`, default 2 hours | SBIePay creates a record (`INPROGRESS`) as soon as the form lands. `NO RECORDS FOUND` or `ABORT` after two hours means the payer never paid on that order |

---

## 7. Encryption (`crypto.py`)

### 7.1 Format

The format below follows the guide's Python integration kit ("Python Code is
provided below for reference"). The guide prints only part of that function.
It shows the checksum being appended (`message + "|" + result.hexdigest()`)
and the SHA-256 checksum type, but not what `result` hashes or what `pad()`
does. The checksum input and the padding below are therefore **assumptions**.
They, and every other parameter, must be checked against the kit's test vectors
during onboarding (Q-1). All of it is kept in this one module so that
confirming it changes nothing else.

```text
plaintext  = packet + "|" + hex(SHA-256(packet))                (assumed checksum input)
ciphertext = AES-CBC(key, iv, PKCS#7(plaintext.encode("utf-8")))   (PKCS#7 assumed)
iv         = 16 random bytes                                    (as the kit: os.urandom)
wire value = base64(iv[16] ‖ ciphertext)
```

- **Key.** This is the Merchant Encryption Key (MEK) SBI issues per merchant id
  and per environment (UAT and production keys differ). The kit uses the UTF-8
  bytes of the key string as issued. `SBIEPAY_KEY_FORMAT` (`text` default,
  `base64` if the kit turns out to decode it) selects the encoding. The key is
  read from the file at `SBIEPAY_KEY_PATH`, whitespace-trimmed, and cached by
  `config.load_key()`. Like e-GRAS's response key, it is never an env value,
  never logged, never in metadata, and never in an exception message. A key
  that does not decode to 16, 24 or 32 bytes is a startup error.
- **Decryption** reverses the steps. If the decrypted text ends in
  `|<64 hex chars>`, the checksum is checked and stripped, and a mismatch is
  `SBIEPAY_RESPONSE_DECRYPT_FAILED`. If there is no trailing checksum, the text
  is used as is (Q-1).
- The library is `cryptography`, already a dependency through e-GRAS. No new
  package is needed and the SBI Java jar or PHP kit is not vendored.

### 7.2 Determinism and the random IV

0017 #9.2 rule 2 asks that `initiate` be deterministic, so an idempotent replay
can rebuild the action without storing form bodies. The addon makes the
**packet** deterministic: the same `InitiationRequest` always gives the same
order number and the same plaintext Transaction (and Multiaccount) packet. Only
the IV, and therefore the ciphertext, differs on a replay.

**This deviates from the letter of 0017.** 0017 #7 says a replay "returns the
same `provider_action`", and with a random IV the `EncryptTrans` string differs
on every rebuild. The deviation is deliberate:

- The rule exists so a replay can be rebuilt without storing form bodies. That
  purpose is fully met.
- The code that enforces it, `PaymentService._rebuild_action`, compares only
  `provider_payment_id`.
- Both ciphertexts decrypt to the same packet for the same order number, so
  SBIePay treats them identically.
- No client compares form fields. 0017 #12.2 makes them opaque.

0017 #7 should be clarified to "the same `provider_payment_id` and an
equivalent action" when this spec lands.

A deterministic ("synthetic") IV derived with HMAC from the merchant key was
considered and rejected:

- It departs from the kit, which adds onboarding risk for no functional gain.
- It reuses the MEK for a second primitive.
- It invents cryptography where a bank-supplied scheme already exists.

### 7.3 Replay

On replay (`InitiationRequest.replay = True`) `initiate` returns the same
order number and an encryption of the same packet, and skips the `SBIEPAY_ENABLED`
kill switch (0017 #9.4, as 0022 does).

---

## 8. Provider surface

```python
# addon/sbiepay_payment_gateway/provider.py
from apps.payments.providers.base import PaymentProvider


class SBIePayPaymentProvider(PaymentProvider):
    """Collect payments through SBIePay's aggregator-hosted page."""

    name = "sbiepay"
    label = "Pay online (SBIePay)"  # pay modes depend on what SBI enables, so none are named
    pending_horizon = ...  # SBIEPAY_PENDING_HORIZON, #6.4
    not_found_grace = ...  # SBIEPAY_NOT_FOUND_GRACE, #6.4

    def list_options(self) -> list[PaymentOption]: ...  # always [], #4.1
    def initiate(self, request) -> ProviderInitiation: ...  # #4, no network call
    def fetch_status(self, *, provider_payment_id) -> ProviderStatus: ...  # #6
    def parse_callback(self, payload) -> ProviderCallback: ...  # #5, trusted=False
```

`initiate` makes **no network call**. It only encrypts and builds form fields,
so it can fail only permanently (configuration, amount, account mapping), never
transiently. `ProviderInitiation.metadata` carries `order_number`,
`multi_account` (bool) and, when it is on, the account split. It never carries
the packet or the ciphertext.

Activation is configuration only:

```python
PAYMENT_PROVIDERS = {
    "mock": "apps.payments.providers.mock.MockPaymentProvider",
    "egras": "addon.egras_payment_gateway.provider.EGRASPaymentProvider",
    "offline": "addon.offline_payment.provider.OfflinePaymentProvider",
    "sbiepay": "addon.sbiepay_payment_gateway.provider.SBIePayPaymentProvider",
}
PAYMENT_DEFAULT_PROVIDER = "sbiepay"          # SBIePay only, or …
PAYMENT_SELECTABLE_PROVIDERS = ["sbiepay", "offline"]   # … let the payer choose (0032 #4.2)
```

Recommended per-environment setup: `mock` in `config.settings.local` and
`config.settings.test`. `sbiepay` in staging, pointed at the SBI UAT URLs with
the UAT merchant id and key. `sbiepay` in production with the live merchant id
and key, which SBI issues only after UAT sign-off.

### 8.1 Coexistence

SBIePay, e-GRAS and the offline counter can all be selectable at once. Each
payment is routed by its own `Payment.provider` (0017 #9.3), so they share
nothing but `apps.payments`. Order numbers (`DR` + 32 hex characters) and e-GRAS
application numbers (`DR` + 18 hex characters) can never be confused, and the
two are always looked up together with `provider` in any case.

---

## 9. Replacing or removing SBIePay

The generic procedure is 0017 #9.8:

```text
1. Keep "sbiepay" registered (PAYMENT_REGISTERED_PROVIDERS=sbiepay in the env-driven settings).
2. Drop it from PAYMENT_DEFAULT_PROVIDER / PAYMENT_SELECTABLE_PROVIDERS.  -> no new SBIePay payments
3. Wait until `manage.py payments_provider_usage sbiepay` shows no PENDING payment
   (at most SBIEPAY_PENDING_HORIZON).
4. Remove "sbiepay" from PAYMENT_PROVIDERS / PAYMENT_REGISTERED_PROVIDERS, the
   INSTALLED_APPS entry and the SBIEPAY_* block, and delete src/addon/sbiepay_payment_gateway/.
```

Historic payments keep `provider="sbiepay"` and their ATRN in
`provider_reference`. They never need the addon again. `SBIEPAY_ENABLED=False`
is the emergency version of step 2: new SBIePay payments are refused while
browser, push and DV keep resolving the ones in flight.

---

## 10. Change to `apps.payments`: server push endpoint

0017 #9.6 has one callback endpoint, and it always answers with a `302` to the
UI because its caller is a browser. SBIePay's push response comes from SBIePay's
server, not a browser, and expects a plain success reply. The guide lists
`400`/`503`/`505` and TLS failures as push errors that need SBI support. A
redirect is the wrong answer to a server.

The change is generic and names no gateway:

```text
POST /api/v1/payments/providers/{provider}/_push
```

- It is the same handler as `_callback` (#9.6): `AllowAny`, `@csrf_exempt`,
  no authentication, body-size limit, unknown provider → `404`. It runs
  `parse_callback` → `fetch_status` (when `trusted=False`) →
  `apply_provider_status` under the same locks.
- **Response.** Always `200 text/plain "OK"` once the request is accepted for
  processing, including when nothing matched, the payload was malformed, or
  verification failed transiently. Retries from the gateway cannot help any of
  these cases, and the poller resolves them anyway. Only an unknown `provider`
  (`404`) and the body-size limit (`413`) differ. No redirect, no `meta`
  envelope.
- **Throttle.** It has its own throttle, `PAYMENT_PUSH_THROTTLE_RATE`
  (default `600/min`). Pushes come from a few gateway IPs, so the per-IP
  browser rate (`PAYMENT_CALLBACK_THROTTLE_RATE`) would throttle a busy
  morning.
- Swagger documents both responses. It lives in `apps.payments/views.py` and
  `urls.py`, next to `ProviderCallbackView`. It needs no contract change:
  `PaymentProvider` does not learn which channel called it.
- 0017 #9.6 gains one paragraph pointing here. The isolation test still holds,
  because the endpoint does not mention SBIePay.

The deployment registers
`https://<api-host>/api/v1/payments/providers/sbiepay/_push` with SBI as the
push URL (`SBIEPAY_PUSH_URL` is checked at startup but never sent in a packet,
because SBI configures it on its side).

---

## 11. Configuration

### 11.1 Namespace

Addon settings use the `SBIEPAY_` prefix and live in one block in
`config/settings/base.py`. Removing the integration means deleting that block
plus the `INSTALLED_APPS` and `PAYMENT_PROVIDERS` entries. One deployment uses
one SBIePay merchant id. A different merchant is a different `.env`, never a
different code path.

### 11.2 Settings

```python
# config/settings/base.py — SBIePay payment provider addon (addon.sbiepay_payment_gateway, spec 0038)
# Remove this block, the INSTALLED_APPS entry, and PAYMENT_PROVIDERS["sbiepay"]
# (plus "sbiepay" in PAYMENT_SELECTABLE_PROVIDERS) to remove the integration.
SBIEPAY_MERCHANT_ID = env("SBIEPAY_MERCHANT_ID", default="")
SBIEPAY_KEY_PATH = env("SBIEPAY_KEY_PATH", default="")
SBIEPAY_PAYMENT_URL = env("SBIEPAY_PAYMENT_URL", default="")
SBIEPAY_VERIFY_URL = env("SBIEPAY_VERIFY_URL", default="")
SBIEPAY_RETURN_URL = env("SBIEPAY_RETURN_URL", default="")
...
```

| Setting | Required | Default | Notes |
| --- | --- | --- | --- |
| `SBIEPAY_MERCHANT_ID` | yes | `""` | SBI-issued MID; UAT and production differ |
| `SBIEPAY_KEY_PATH` | yes | `""` | file holding the Merchant Encryption Key; mounted secret, never in `.env` |
| `SBIEPAY_KEY_FORMAT` | no | `text` | `text` (UTF-8 bytes of the issued string, as the kit does) or `base64` (Q-1) |
| `SBIEPAY_PAYMENT_URL` | yes | `""` | `…/secure/AggregatorHostedListener` (UAT: `https://test.epay.sbiuat.bank.in/secure/AggregatorHostedListener`) |
| `SBIEPAY_VERIFY_URL` | yes | `""` | `…/payagg/statusQuery/getStatusQuery` |
| `SBIEPAY_RETURN_URL` | yes | `""` | absolute `https://…/api/v1/payments/providers/sbiepay/_callback`, ≤ 200 characters; sent as Success and Fail URL |
| `SBIEPAY_PUSH_URL` | no | `""` | `https://…/api/v1/payments/providers/sbiepay/_push` as registered with SBI; validated only, never sent |
| `SBIEPAY_PAYMODE` | no | `NB` | Transaction packet field 12 |
| `SBIEPAY_ORDER_PREFIX` | no | `DR` | ≤ 4 alphanumeric characters |
| `SBIEPAY_MULTI_ACCOUNT_ENABLED` | no | `False` | sends `MultiAccountInstructionDtls` (#4.5) |
| `SBIEPAY_ACCOUNT_MAP` | when multi-account | `{}` | JSON: `account_head` or `charge_type` → SBIePay account identifier (≤ 100 characters) |
| `SBIEPAY_TIMEOUT` | no | `15` s | DV connect/read timeout |
| `SBIEPAY_VERIFY_SSL` | no | `True` | rejected as `False` in production |
| `SBIEPAY_PENDING_HORIZON` | no | `8` d | `pending_horizon`; must be ≥ 7 days |
| `SBIEPAY_NOT_FOUND_GRACE` | no | `2` h | `not_found_grace` |
| `SBIEPAY_ENABLED` | no | `True` | kill switch; `initiate` raises `SBIEPAY_DISABLED` (permanent) for new payments; replay, callbacks, push and DV keep working |

Added to `apps.payments` (#10): `PAYMENT_PUSH_THROTTLE_RATE`, default `600/min`.

`resolve_config()` loads the values into a frozen `SBIePayConfig` once and
caches it (cleared on `setting_changed` for tests), as `EGRASConfig` does.
`SBIePayConfig.__repr__` never includes key material. Every setting is
documented in `.env.example`, `.env.prod.example` and `README.md`, following
AGENTS.md.

### 11.3 Startup validation

System checks registered in `AppConfig.ready()`, error level, only when
`"sbiepay"` is a registered provider:

- every required `SBIEPAY_*` value is set, and the merchant id has no spaces;
- the key file exists, is readable, and decodes to 16, 24 or 32 bytes in
  `SBIEPAY_KEY_FORMAT`;
- `SBIEPAY_PAYMENT_URL`, `SBIEPAY_VERIFY_URL` and `SBIEPAY_RETURN_URL` (and
  `SBIEPAY_PUSH_URL` if set) are absolute `https://` URLs. The return URL is at
  most 200 characters and ends with the `_callback` path for `sbiepay`. The push
  URL ends with the `_push` path;
- `SBIEPAY_ORDER_PREFIX` is at most 4 alphanumeric characters;
- `SBIEPAY_PENDING_HORIZON` is at least 7 days;
- with multi-account on: `SBIEPAY_ACCOUNT_MAP` parses and is non-empty, every
  identifier is clean (#4.4 character set) and at most 100 characters, and a
  warning is raised for each `ChargeType` value without an entry;
- in production: `SBIEPAY_VERIFY_SSL` is on, and `SBIEPAY_PAYMENT_URL` /
  `SBIEPAY_VERIFY_URL` do not point at the SBI UAT host (`sbiuat`).

Checks stay silent when the addon is installed but `"sbiepay"` is not
registered, so local and CI runs need no SBI credentials.

---

## 12. SBI's other "mandatory" APIs

The guide lists five APIs for a "successful integration". This spec implements
only the first:

| API | What it does | In this spec |
| --- | --- | --- |
| Double Verification / Status Query | authoritative status of one order | **Yes** (#6) |
| Refund & Cancellation | books a full, partial or multiple refund (or cancellation while "in clearing") against an ATRN | No |
| Refund Enquiry | status of a booked refund (ARRN + ATRN) | No |
| Payout | daily settlement file (XML) for a date | No |
| Transaction MIS | transaction report by date, status, ATRN, order number or ARRN | No |

They are deferred because each needs a **domain concept 0017 explicitly leaves
out**. A refund changes what a `SUCCESS` payment means for a case (0017 #10:
"Refunds are out of scope here"). Payout and MIS only matter once there is a
reconciliation model to compare against. Calling the refund API from the addon
or a script would move money while Dristi still shows the payment as paid.

The PRD agrees that refunds are not a gateway operation:

- e-filing handover `LIFE-12`: when a recalculated filing fee is lower there
  is "no automatic refund". Instead the system auto-generates a *refund note*
  the filer uses to claim it.
- process handover `FEE-07`: "Nothing is refunded".

So no PRD flow needs Dristi to call SBIePay's refund API.

Until a follow-up spec adds a refund and reconciliation contract to 0017:

- refunds are booked by finance staff in SBIePay's Merchant Panel ("Initiate
  Refund", Guide "Refund Process"), and the case is corrected through the
  normal Dristi workflow;
- payout and MIS reports are downloaded from the Merchant Panel.

So the follow-up does not need to re-read the guide, the wire formats are
recorded in Appendix A. Whether SBI will sign off go-live with only DV is Q-5,
and this spec's rollout depends on the answer.

---

## 13. Onboarding and deployment checklist

These are not code, but go-live needs every item:

| Item | Who | Notes |
| --- | --- | --- |
| UAT merchant id and MEK; Integration Parameter Sheet filled in | SBI ↔ PUCAR | live MID and key are issued only after UAT sign-off |
| Business (source) URL whitelisted | SBI | the Dristi UI origin that auto-submits the form (#4.8) |
| Push URL + public IP + domain whitelisted | SBI | `…/providers/sbiepay/_push` (#10); HTTPS with a publicly valid certificate (SBI push fails on an invalid one) |
| DV source IP whitelisted | SBI | static egress IP shared by `web` and `worker`. SBI needs at least one working day |
| SBIePay's public IP/domain allowed out from our network | PUCAR infra | for DV calls |
| Pay modes enabled; "time interval"; DVP / non-DVP category | SBI ↔ PUCAR finance | guide "Technical Pre-Requisites" |
| Who bears the convenience fee and GST (customer or merchant) | PUCAR finance | affects what the payer sees and the receipt (Q-3) |
| Settlement account(s); Multiaccount identifiers if split | PUCAR finance | #4.5 |
| SMS/e-mail notification from SBIePay on or off | PUCAR | needs payer contact data if on (Q-4) |
| Merchant logo URL | PUCAR | shown on SBIePay's page |

---

## 14. Failure codes

SBIePay never defines API error codes. The addon contributes no `errors.py`, and
nothing it raises reaches a client unchanged. Its codes are **internal failure
codes** in `constants.py`, carried on `ProviderError.code` or
`ProviderStatus.failure_code`. `apps.payments` stores them on
`Payment.failure_code`, logs them, and maps the exception class to its own
registered API code (0017 #12.5). Swapping providers therefore never changes the
API's codes.

| Failure code | Raised as | Stored / returned by `apps.payments` |
| --- | --- | --- |
| `SBIEPAY_DISABLED` | `ProviderPermanentError` | `FAILED`; `422 E06014` |
| `SBIEPAY_INVALID_CONFIGURATION` | `ProviderPermanentError` | `FAILED`; `422 E06014` |
| `SBIEPAY_UNSUPPORTED_CURRENCY` | `ProviderPermanentError` | `FAILED`; `422 E06014` |
| `SBIEPAY_AMOUNT_INVALID` | `ProviderPermanentError` | `FAILED`; `422 E06014` |
| `SBIEPAY_AMOUNT_INCONSISTENT` | `ProviderPermanentError` | `FAILED`; `422 E06014` |
| `SBIEPAY_ACCOUNT_UNMAPPED` | `ProviderPermanentError` | `FAILED`; `422 E06014` |
| `SBIEPAY_CALLBACK_MALFORMED` | `ProviderCallbackMalformed` | nothing written; browser `status=UNKNOWN`, push `200` |
| `SBIEPAY_MERCHANT_MISMATCH` | `ProviderCallbackMalformed` | as above |
| `SBIEPAY_RESPONSE_DECRYPT_FAILED` | `ProviderCallbackMalformed` | as above |
| `SBIEPAY_VERIFY_TIMEOUT` | `ProviderTransientError` | unchanged; retried by the poller |
| `SBIEPAY_VERIFY_UNAVAILABLE` | `ProviderTransientError` | unchanged; retried by the poller |
| `SBIEPAY_VERIFY_MALFORMED` | `ProviderTransientError` | unchanged; retried by the poller |
| `SBIEPAY_VERIFY_REJECTED` | `ProviderTransientError` | unchanged; retried; logged at error (configuration or allow-list) |
| `SBIEPAY_PAYMENT_FAILED` | `ProviderStatus(FAILED)` | `FAILED` with this `failure_code` |
| `SBIEPAY_EXPIRED` | `ProviderStatus(FAILED)` | `FAILED` with this `failure_code` |
| `SBIEPAY_ABORTED` | `ProviderStatus(NOT_FOUND)` | `FAILED` (`PAYMENT_NOT_FOUND_AT_PROVIDER`) after `not_found_grace` |
| `SBIEPAY_REVERSED` | `ProviderStatus(FAILED, reconciliation_code=…)` | `FAILED`; `needs_reconciliation`, reason `PAYMENT_PROVIDER_FLAGGED` |
| `SBIEPAY_SUCCESS_INCOMPLETE` | `ProviderStatus(PENDING)` | unchanged; logged |
| `SBIEPAY_UNKNOWN_STATUS` | `ProviderStatus(PENDING)` | unchanged; logged at warning |

The raw SBIePay status description goes to the log line and to
`metadata["status_description"]`, never to `failure_message`. That stays a safe,
generic sentence.

---

## 15. Security

- **No card data.** The aggregator-hosted page means card numbers, CVV, VPA and
  bank credentials never reach Dristi (no PCI-DSS scope).
- **No unnecessary personal data.** Model P sends SBIePay no payer details.
  Logs mask the payer (name initial, last four phone digits).
- **The key is a secret.** It is read from a mounted file, cached in memory,
  and never logged, put in metadata, put in exception text or included in the
  config `repr`. UAT and production keys are separate files, and a production
  check rejects UAT URLs so a UAT key is never paired with production traffic.
- **Responses are hints.** Browser and push responses can only *select* a
  payment by order number. Its outcome, amount and ATRN are never applied.
  Authenticity comes only from DV by our own order number (#6.1), plus the
  amount check in 0017 #9.5.
- **No access gate** (case to Scrutiny, process to signing, advocate case
  access) opens on anything but a `SUCCESS` written by `confirm_payment`.
- **Transport.** DV uses TLS 1.2+ with certificate verification, and disabling
  it is rejected in production. The push endpoint is public by necessity. It is
  size-limited and throttled, and safe because it trusts nothing it receives.
- **No ciphertext at rest.** `initiate` rebuilds the encrypted form on replay
  (#7.2), so neither the packet nor its ciphertext is stored.

---

## 16. Logging

One structured line per stage under the `addon.sbiepay_payment_gateway` logger,
always carrying `provider_payment_id` (the order number) and, where known,
`payment_id` or `batch_id`. Lifecycle events (`PAYMENT_PENDING`,
`PAYMENT_CONFIRMED`, `PAYMENT_AMOUNT_MISMATCH`, …) are logged by
`apps.payments`.

| Event | Emitted by |
| --- | --- |
| `SBIEPAY_REQUEST_BUILT` (amount, paymode, multi-account, masked payer) | `request_builder.py` |
| `SBIEPAY_CALLBACK_RECEIVED` (channel `browser`/`push`, hinted status, ATRN) | `callback_parser.py` |
| `SBIEPAY_VERIFY_REQUEST` / `SBIEPAY_VERIFY_RESPONSE` (status, description, ATRN, amount, latency) | `verification_client.py` |

```text
event=SBIEPAY_VERIFY_RESPONSE payment_id=... provider_payment_id=DR0F9D…4C
sbiepay_status=SUCCESS description="Payment In Clearing" outcome=SUCCESS atrn=2011578958428 amount=775.00 latency_ms=380
```

Never logged: the key, the plaintext or encrypted packets, or the full form or
response bodies. Order number, ATRN, CIN, bank reference and amounts are
receipt data, not secrets, and are logged.

---

## 17. Testing

**Unit (no network)**
- crypto: the kit's published vectors (Q-1) decrypt and re-encrypt; round trip;
  a fresh random IV per call; trailing checksum checked when present; wrong key,
  truncated value, bad padding and bad base64 each raise; key formats `text`
  and `base64`; key never appears in `repr` or exception text.
- packets: allowed-character cleaning; `|`, `=`, `^` removed from data;
  length limits; amount formatting (`775.00`, `12.50`, refuses 3 decimals,
  never rounds).
- request builder: every Transaction packet field and its source; field order;
  same Success and Fail URL; order number prefix, length and determinism;
  Other Details caret layout, the 30-field and 1000-character limits with
  `AND N MORE`; `merchIdVal` plain; on replay the same order number and a ciphertext that decrypts to the identical packet; kill
  switch skipped on replay.
- accounts: map by `account_head`, by `charge_type`; precedence; an unmapped
  charge raises; grouping and summing; double-pipe layout; deterministic order;
  disabled → no field.
- response parser / callback parser: browser `encData` and push `pushRespData`;
  SUCCESS/PENDING/FAIL hints; extra trailing fields accepted; too few fields;
  merchant id mismatch (plain and in packet); wrong prefix; undecryptable;
  `trusted` always `False`.
- verification client: request body (blank ATRN, blank amount, plain text),
  URL, TLS settings, timeout, non-2xx, unparsable body, each SBIePay error
  message → `SBIEPAY_VERIFY_REJECTED`, encrypted-body fallback.
- status mapper: every row of #6.3, including the four SUCCESS descriptions,
  `ABORT` → `NOT_FOUND`, `CANCELLED`/`REFUND` → `FAILED` with
  `reconciliation_code`, `CLOSED`/unknown → `PENDING`.
- failure codes: every row of #14 raises the stated class with the stated code.
- config/checks: defaults, each check failure, silence when not registered,
  production guards (SSL, UAT host).

**Flow (DB + stub broker, mocked SBIePay endpoints, through 0017's APIs)**
- create payment with `provider: "sbiepay"` → `201` with a `REDIRECT_FORM`
  holding `EncryptTrans` and `merchIdVal`; idempotent replay returns the same
  order number and a packet that decrypts identically.
- forged plain `encData` (wrong key) → redirect `UNKNOWN`, payment still
  `PENDING`.
- correctly encrypted `SUCCESS` browser response with DV still `BOOKED` →
  payment `PENDING`; DV later `SUCCESS` via the poller → `SUCCESS`.
- browser response then push response for the same order → credited once;
  push answered `200 "OK"`, browser `302`.
- push only (browser tab closed) → `SUCCESS` with ATRN in `provider_reference`
  and CIN, pay mode and fee in metadata.
- batch of three demands → one order number, one DV call → three payments
  `SUCCESS`.
- `FAIL` → `FAILED` with `SBIEPAY_PAYMENT_FAILED`; items payable again.
- `ABORT` → stays `PENDING` within grace, `FAILED` after grace.
- `REFUND` while pending → `FAILED` and `needs_reconciliation`.
- DV amount differs → no credit, `needs_reconciliation` (0017 #9.5).
- browser `FAIL` "earlier transaction was successful" with DV `SUCCESS` →
  `SUCCESS`.
- `₹12.50` single line → posted as `12.50`, confirmed without rounding.
- unmapped charge with multi-account on → `422 E06014`, payment `FAILED` with
  `SBIEPAY_ACCOUNT_UNMAPPED`. Assertions on `code` and `field`, never message.

**Coexistence and isolation**
- `PAYMENT_SELECTABLE_PROVIDERS = ["egras", "offline", "sbiepay"]`: each payment
  routes to its own provider. An SBIePay push never matches an e-GRAS payment.
- No module under `apps.*` imports `addon.*` or mentions `sbiepay`. The addon
  imports only the surface in #1 and has no `errors.py`, `urls.py`,
  `models.py` or `admin.py`.
- Removing `"sbiepay"` from settings leaves `apps.payments` working.

**Manual / end-to-end** against SBI UAT (`test.epay.sbiuat.bank.in`) with the
UAT merchant id: net banking, card, UPI success; failure; abandonment
(`ABORT`); push with the browser closed; a batch. Each is confirmed by DV and
visible in Dristi with the right ATRN. This is also the evidence SBI asks for
at sign-off.

```bash
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest
cd src && ruff check . && ruff format .
cd src && python manage.py check
```

---

## 18. Out of scope

- Merchant-hosted integration, Payment packet, card/VPA capture.
- Billing and Shipping packets; SBIePay customer notifications that need them.
- International mode, foreign currencies, PayPal.
- Refund & Cancellation, Refund Enquiry, Payout and Transaction MIS in Dristi
  (#12, Appendix A).
- Detecting refunds made after a payment was credited.
- TPV (third-party validation of the payer's account).
- Mobile app integration (Origin/Referer headers, UPI intent).
- Per-court merchant ids within one deployment.
- Any admin UI for SBIePay configuration; DB-managed configuration.

## 19. Acceptance criteria

- [ ] SBIePay ships as `src/addon/sbiepay_payment_gateway/` with no models, migrations, URLs, admin or `errors.py`.
- [ ] SBIePay is selected only through `PAYMENT_PROVIDERS` / `PAYMENT_DEFAULT_PROVIDER` / `PAYMENT_SELECTABLE_PROVIDERS`; no caller changes.
- [ ] The addon imports only the contract and the read-only helpers listed in #1; no module under `apps.*` imports `addon.*` or mentions SBIePay.
- [ ] `initiate` makes no network call and returns the same order number and the same plaintext packet for the same request (#7.2).
- [ ] The Transaction packet matches #4.3; no payer data is sent; amounts carry paise and are never rounded.
- [ ] Order numbers are deterministic, prefixed, ≤ 100 characters and new per payment attempt.
- [ ] Multi-account, when on, follows #4.5 with no default account; off by default.
- [ ] `parse_callback` handles `encData` and `pushRespData`, always returns `trusted=False`, and rejects a foreign merchant id.
- [ ] DV is always by our own order number; statuses map per #6.3; unknown vocabulary is `PENDING`.
- [ ] `pending_horizon` ≥ 7 days; `not_found_grace` configurable.
- [ ] `apps.payments` exposes `POST /payments/providers/{provider}/_push` answering `200 "OK"`, with its own throttle (#10).
- [ ] Every failure is raised as the exception class in #14; SBIePay codes never appear in an API `errors` array.
- [ ] Batches produce one SBIePay transaction and one DV call for all their payments.
- [ ] SBIePay can stay registered for in-flight payments without being default or selectable.
- [ ] ATRN lands in `provider_reference`; CIN, bank reference, pay mode and fee/GST in `metadata["provider"]`.
- [ ] `manage.py check` fails on invalid SBIePay configuration and is silent when the addon is not registered.
- [ ] The key and the packets never appear in logs, metadata or exceptions; payer data is masked.
- [ ] Unit, flow, coexistence and isolation tests pass; Ruff clean.

---

## 20. Open questions

1. **Crypto parameters.** The Python kit sample uses AES-CBC with a random IV
   prepended, the UTF-8 bytes of the key string (a 24-character MEK gives
   AES-192), and a checksum appended before encryption. The guide elsewhere
   says "AES 128-bit" for Python and ships an `AES256Bit` jar, and its printed
   function omits what is hashed and how `pad()` pads. Confirm with SBI, using
   the kit's test vectors: cipher mode, key encoding (`text` or `base64`),
   padding, the checksum's input, and whether responses carry the checksum.
   `crypto.py` is the only module affected.
2. **DV amount.** Will SBI's DV accept a blank amount, as the guide's sample
   does? If not, the fallback is to pass the expected amount through the
   contract: a small 0017 amendment that adds the expected amount to
   `fetch_status`, which e-GRAS would ignore. The alternative, encoding the
   amount in the order number, is rejected.
3. **Convenience fee.** Does the court or the litigant bear SBIePay's commission
   and GST? If the litigant, should the Dristi receipt show the fee SBIePay
   reports (`Total Fee^GST`) next to the court fee?
4. **Customer notifications.** Does PUCAR want SBIePay's own SMS/e-mail to the
   payer? That needs the Billing packet (model BP) and sending the payer's
   mobile and e-mail to SBI. The recommendation is no. Dristi already sends
   its own "payment pending" and "case filed" SMS to the complainant side
   (e-filing handover v47, §20.1), so SBI's messages would duplicate them in
   different wording.
5. **Mandatory APIs.** Will SBI sign off go-live with DV only, refunds booked in
   the Merchant Panel, and payout/MIS downloaded from the panel (#12)? If not,
   the refund/reconciliation contract for 0017 has to come first.
6. **Settlement accounts. This blocks Kerala go-live.** e-filing handover
   §19.1 routes the Advocate Welfare Fund and Stipend Stamp to a treasury TSB
   account under a government head, and leaves the other heads' accounts as
   `[GAP]`. Three things to settle:
   - Can SBIePay Multiaccount settle into a treasury TSB account at all, or
     only into ordinary bank accounts?
   - If it cannot, are those heads collected through e-GRAS instead, which
     would split one bill across two providers (0017 has no such concept), or
     re-remitted manually by finance?
   - Finance must supply the identifiers for whichever accounts are used.
7. **Same order number, several attempts.** When an order has more than one
   attempt (for example `ABORT` then `SUCCESS`), does DV by order number return
   the successful attempt, the latest, or several records? The mapper assumes
   one record, with SBIePay guaranteeing at most one success per order. If DV
   can return several, the mapper needs the same "a success wins" rule as
   e-GRAS (0022 #6.3).
8. **Push acknowledgement.** Does SBIePay expect anything specific in the
   push reply body, or just HTTP 200? Does it retry on non-200, and how often?
9. **Business URL matching.** Does SBI match the whitelisted business URL on
   the domain or on the full URL (path included)? Browsers send only the origin
   cross-site by default (#4.8). This decides whether the UI needs a fixed
   payment-hand-off route.

## 21. Design decisions

| Decision | Rationale |
| --- | --- |
| SBIePay lives in `addon.sbiepay_payment_gateway`, not `apps.payments` | Mirrors 0013, 0015, 0022 and 0032, and issue #290 asks for it. The payment lifecycle outlives any gateway, and packet layouts, keys and DV calls are swappable detail. |
| Aggregator-hosted, model P only | Keeps card data and PCI-DSS out of Dristi, sends SBI no personal data, and needs no bank picker, so the UI stays provider-agnostic. |
| Browser and push responses never trusted; DV by our own order number is the only proof | SBI mandates DV. AES-CBC is not authenticated. A browser `FAIL` can contradict a real success. Looking up by our own order number stops a forged response from borrowing someone else's ATRN. |
| Same endpoint for Success and Fail URL | The outcome comes from DV, not from which URL SBIePay chose. |
| Generic `_push` endpoint in `apps.payments` | A server must get `200`, not a browser redirect. Addons cannot own URLs, and the endpoint names no gateway, so any future provider with a server-to-server notification reuses it. |
| Kit's random IV; determinism is of the order number and plaintext packet | 0017's replay check compares only `provider_payment_id`, and any ciphertext of the same packet is the same request to SBIePay. A home-made deterministic IV would diverge from the bank's kit and reuse the MEK, for no functional gain. |
| Key in a mounted file, not an env value | It is a credential: file-mounted like e-GRAS's response key, never in `.env`, logs or `repr`. |
| Paise carried, never rounded | SBIePay supports two decimals. Unlike e-GRAS (0022 Q-1), `₹12.50` court fees just work. |
| `ABORT` → `NOT_FOUND` | No money moved, but the same order number may still be retried. The grace window avoids turning a quick retry into a late success. Cost: no cancel within the grace, but resume works (#6.3). Mapping `ABORT` to `FAILED` was rejected because it would let a resumed attempt on the old order land as a late success needing an operator. |
| `CANCELLED`/`REFUND` → `FAILED` plus a reconciliation flag | Money moved and came back through a channel Dristi did not start. An operator must see it. |
| Unknown status → `PENDING` | 0017 #9.2 rule 5. Failing early risks money taken with no credit. |
| `pending_horizon` of 8 days | `BOOKED` turns `EXPIRED` on the 7th day. One day of margin. |
| Multi-account optional, no default account | It is the SBIePay counterpart of e-GRAS heads of account, with the same rule: money in the wrong account is worse than a refused payment. |
| Refund, payout and MIS deferred | Each needs a refund or reconciliation model 0017 excludes, and the PRD handles refunds by refund note, not through the gateway (`LIFE-12`, `FEE-07`). Booking a refund behind Dristi's back would leave a case showing paid money that was returned. |
| Internal failure codes, no API codes | API codes belong to `apps.payments` ([0000](0000-api-coding-spec.md) #9.2) and must not change when a provider is swapped. |
| `SBIEPAY_ENABLED` stops initiation only | Turning SBIePay off must not strand payments already at the bank. |

## 22. Implementation phases

Depends on 0017's provider contract and 0032's selectable providers, both
merged.

1. **Scaffolding.** `sbiepay_payment_gateway` app, `config.py`, `constants.py`,
   settings block, env/README docs, system checks, isolation test.
2. **Crypto and packets.** `crypto.py` against the SBI kit vectors (needs Q-1
   answered), `packets.py`, `request_builder.py`, `accounts.py` + unit tests.
3. **Responses and verification.** `response_parser.py`, `callback_parser.py`,
   `verification_client.py`, `status_mapper.py`, `provider.py`, flow tests
   through 0017's APIs.
4. **Push endpoint.** The `_push` view, URL, throttle and Swagger in
   `apps.payments` (#10), with its tests and a paragraph in 0017 #9.6.
5. **Rollout.** Complete the onboarding checklist (#13), run the end-to-end
   checks against SBI UAT, obtain sign-off (Q-5), then set the live merchant
   id, key and URLs and enable `sbiepay` per environment.

---

## Appendix A — Deferred SBIePay APIs (wire reference)

Recorded from the guide for the follow-up spec (#12). None of this is built
here. UAT hosts are shown. SBI supplies production URLs at go-live. All calls
are HTTPS form POSTs that also send plain `merchantId` and
`aggregatorId=SBIEPAY`.

| API | UAT URL | Request | Response |
| --- | --- | --- | --- |
| Refund & Cancellation | `/payagg/orderRefundCancellation/bookRefundCancellation` (the guide also shows `/payagg/bookRefundCancellation/AggStandardEncRefundQueryService`) | `refundRequest` = enc(`SBIEPAY\|MID\|RefundRequestID(≤20)\|ATRN\|RefundAmount\|INR\|OrderNo`) | enc(`MID\|ATRN\|ARRN\|SUCCESS/FAIL\|Message\|RefundRequestID\|OrderNo`) |
| Refund Enquiry | `/payagg/RefundMISReport/refundEnquiryAPI` | `queryRequest` = enc(`ACRN/ARRN\|ATRN\|MID`) | enc(`MID\|ARRN\|ATRN\|GatewayTrace\|OrderNo\|Status\|StatusDescription\|RefundAmount\|AvailableForRefund\|RefundDate\|ProcessedDate`) |
| Payout | `/payagg/transactionPayoutAPI/getTransactionPayoutAPI` | `queryRequest` = `DOM\|IN\|INR\|DDMMYYYY` | enc(XML: `ORDERDETAILS/ORDER`, `REFUNDDETAILS/REFUND`, `SUMMARYDETAILS`) |
| Transaction MIS | `/payagg/MISSettleReport/transactionMISAPI` | `queryRequest` = `SBIEPAY\|MID\|DOM\|IN\|INR\|DDMMYYYY\|Status^…\|ATRN^…\|OrderNo^…\|GatewayTrace^…\|ARRN^…` (≤ 50 values per list) | enc(XML: `ORDD/ORD` records) |

Rules the guide states for refunds: only a successful transaction "Payment
Sighted" / "Payment in Clearing" can be **cancelled**; only "Transaction Paid
Out" can be **refunded**. Full, partial and multiple partial refunds are
allowed. SBI processes refunds on T+1, and the bank credits the customer in
roughly 3–4 working days, provided the merchant has no negative liability.
