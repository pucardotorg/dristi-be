# 0022 — e-GRAS Payment Gateway Addon (`addon.egras_payment_gateway`)

## Status

Proposed

## References

- [0017 — Payments Module](0017-orders-management.md) — `apps.payments`, the consuming module; owns demands, payments, balances, the provider contract (#9), the callback endpoint and the API error codes
- [0000 — API Coding Spec](0000-api-coding-spec.md) — error shape and codes (#9)

> **Scope note.** e-GRAS is a *payment gateway*, not a payments module: it owns
> the e-GRAS wire protocol and nothing else. Demands, payments, balances,
> idempotency, concurrency, permissions, the callback endpoint, polling, audit
> and every API error code remain owned by
> [`apps.payments`](0017-orders-management.md). The addon implements the
> provider contract of [0017](0017-orders-management.md) #9 and is selected
> purely by the `PAYMENT_PROVIDERS` setting, so a deployment can replace it with
> another provider at any point.

## Context

[0017](0017-orders-management.md) gives Dristi one payments module that every
paying flow uses:

| Flow | What it needs from a provider |
| --- | --- |
| Case filing | One bill, one gateway transaction; the case leaves Pending Payment only when the money is in |
| Resubmission after correction | A second, smaller transaction for the balance only |
| Process issue | One transaction per process or per round; the process moves to signing only once paid |
| Applications | One at a time **or in bulk** — several demands, one transaction |
| Join a case | The advocate gets case access only after payment completes |
| Bulk filing | The whole batch clubbed into one gateway request; one transaction reference recorded against every case |

0017 defines the provider contract — frozen dataclasses in and out, normalised
outcomes, untrusted callbacks verified before credit, a provider-declared
pending horizon — and routes every payment back to the provider that started
it. It ships only a mock.

What is missing is a real provider. e-GRAS (Government Receipt Accounting
System), run by the state treasury with NIC, is how state government
departments collect receipts into government heads of account. Its contract is
specific enough to justify an isolated module:

- **Browser redirect.** The department's page auto-submits a hidden form to
  e-GRAS; the user pays at the bank, and e-GRAS auto-submits a form back to a
  department return URL.
- **No signature, no credential.** Neither the outbound form nor the inbound
  callback is signed. The callback is plain form fields — a hint, never proof
  of payment.
- **Server-to-server verification.** A SOAP status service, queried by the
  department's own application number, is the only authoritative outcome.
- **Heads of account, not line items.** The request carries a handful of
  `SCHEMENAME`/`FEEAMOUNT` pairs — 17-character government scheme codes — and an
  integer total that must equal their sum.
- **Whole rupees.** Every amount is an integer.
- **Long pending window.** A transaction may stay pending for days; e-GRAS only
  declares failure on the 8th day when the bank never reports.
- **Strict field formats.** Lengths and character sets are restricted for every
  payer and remarks field.

## Goals

- Ship `EGRASPaymentProvider` in a standalone, removable module that satisfies
  the provider contract of 0017 #9.
- Keep every e-GRAS detail — form fields, office codes, scheme codes, bank
  codes, field sanitisation, SOAP verification, status vocabulary — inside
  `addon/egras_payment_gateway/`.
- Enforce a one-way source dependency: the addon imports
  `apps.payments.providers.base`; `apps.payments` never imports the addon.
- Never let an e-GRAS callback credit a payment on its own; never report a
  final failure e-GRAS has not declared.
- Support single-demand payments and cross-demand batches in one e-GRAS
  transaction.
- Keep each concern (scheme mapping, sanitisation, request building, callback
  parsing, verification, status mapping) independently unit-testable.

## Non-goals

- Anything 0017 owns: demands, payments, balances, numbering, permissions,
  receipts, the callback endpoint, polling, cancellation, reconciliation flags
  and API error codes.
- Fee calculation, rounding of fees, or netting against fees already paid.
- Manual (over-the-counter bank) challans, POS terminals, CSC wallet payments,
  and service-charge splits to non-government accounts.
- Refunds, reversals and settlement/reconciliation against treasury statements.
- Any models, migrations, URLs, views, admin or `errors.py` in the addon.
- A second provider registry, Dramatiq actor or retry policy in the addon.

---

## 1. Module placement and dependency direction

```text
src/
├── apps/
│   ├── payments/                  # 0017 — domain, APIs, provider contract, callback
│   └── ...
├── addon/
│   ├── cdac_sms_gateway/          # 0013
│   ├── cdac_esign/                # 0015
│   └── egras_payment_gateway/     # THIS SPEC — e-GRAS wire protocol
└── config/settings/base.py        # the only wiring point
```

```text
addon.egras_payment_gateway  -- imports -->        apps.payments.providers.base
apps.payments                -- never imports -->  addon.*
config.settings.base         -- references -->     "addon.egras_payment_gateway.provider.EGRASPaymentProvider"
```

The addon imports only the contract: `PaymentProvider`, its dataclasses and
its exception types. It never imports `apps.payments` models, services,
selectors, tasks or errors, and never receives a model instance, so it cannot
write a balance even by accident.

Django registration:

```python
# config/settings/base.py
INSTALLED_APPS = [
    ...
    "apps.payments",
    # Addons
    "addon.cdac_sms_gateway",
    "addon.egras_payment_gateway",
]
```

The addon is an installed app only so it can register system checks. Its
`AppConfig` sets `name = "addon.egras_payment_gateway"` and an explicit
`label = "egras_payment_gateway"`. Deleting `src/addon/egras_payment_gateway/`
plus its settings entries leaves `apps.payments` working on the mock provider.

### 1.1 Layout

```text
src/addon/egras_payment_gateway/
├── __init__.py
├── apps.py                  # AppConfig(name="addon.egras_payment_gateway")
├── provider.py              # EGRASPaymentProvider(PaymentProvider)
├── config.py                # EGRASConfig, resolve_config() (cached, frozen)
├── constants.py             # field names, status vocabulary, failure codes, log events
├── schemes.py               # charge lines -> SCHEMENAME/FEEAMOUNT pairs
├── sanitise.py              # field character sets, lengths, fallbacks
├── request_builder.py       # InitiationRequest -> e-Challan form fields
├── callback_parser.py       # return-URL form -> ProviderCallback (untrusted)
├── verification_client.py   # SOAP call to the GRN status service (TLS, timeout)
├── status_mapper.py         # GrnDetails -> ProviderStatus
├── checks.py                # Django system checks
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_schemes.py
    ├── test_sanitise.py
    ├── test_request_builder.py
    ├── test_callback_parser.py
    ├── test_verification_client.py
    ├── test_status_mapper.py
    ├── test_checks.py
    ├── test_flow.py         # create → callback → verify → SUCCESS, mocked e-GRAS
    └── test_isolation.py
```

---

## 2. End-to-end flow

```text
Dristi UI
   |  GET  /api/v1/payments/providers/options/      -> e-GRAS bank list (opaque)
   |  POST /api/v1/payments/demands/{id}/payments/
   |       {client_request_id, demand_item_ids, payer, provider_options: {bank}}
   v
apps.payments                                                     [0017 #6.2, #9.4]
   +-- Payment(s) INITIATED, COMMIT
   +-- registry.get_default() -> EGRASPaymentProvider
   +-- provider.initiate(InitiationRequest)                       [addon, #4]
   |       schemes, whole-rupee check, sanitised payer, Applicationnumber, UURL
   |       -> ProviderInitiation(REDIRECT_FORM)
   +-- mark_pending(provider="egras", provider_payment_id=Applicationnumber)
   v
201 {payment..., provider_action: {kind: REDIRECT_FORM, url, method, form_fields}}
   |
   v
browser auto-submits form ---> e-GRAS ---> bank / UPI ---> e-GRAS
                                                             |
                    POST /api/v1/payments/providers/egras/_callback   [0017 #9.6]
                                                             |
apps.payments                                                v
   +-- provider.parse_callback(form) -> ProviderCallback(trusted=False)   [addon, #5]
   +-- provider.fetch_status(Applicationnumber)                           [addon, #6]
   |       SOAP lookup by identity -> ProviderStatus
   +-- apply_provider_status(payments, status)                            [0017 #9.5]
   v
HTTP 302 -> PAYMENT_UI_REDIRECT_URL ; UI polls GET /api/v1/payments/payments/{id}/
```

When the callback never arrives (tab closed, bank slow, e-GRAS down), the
0017 poller (#9.7) reaches the same `apply_provider_status` through
`fetch_status`. The callback is an accelerator, not a dependency.

---

## 3. Responsibility boundary

| Concern | Owner |
| --- | --- |
| Demands, items, balances, statuses, numbering, idempotency, permissions | `apps.payments` (0017) |
| Provider selection and routing by `Payment.provider` | `apps.payments` (0017 #9.3) |
| Callback endpoint, CSRF, throttling, UI redirect | `apps.payments` (0017 #9.6) |
| Applying an outcome; amount check; late success; mismatch | `apps.payments` (0017 #9.5) |
| Polling schedule; pending-horizon enforcement; cancel check | `apps.payments` (0017 #9.7, #9.8) |
| API error codes and the error response shape | `apps.payments` (0017 #12.5) |
| e-GRAS configuration loading | addon `config.py` |
| Charge line → scheme mapping, whole-rupee check | addon `schemes.py` |
| Field character sets, lengths, fallbacks | addon `sanitise.py` |
| e-Challan form fields, `Applicationnumber`, financial year | addon `request_builder.py` |
| Return-URL form parsing | addon `callback_parser.py` |
| SOAP verification call, TLS, timeout | addon `verification_client.py` |
| e-GRAS status vocabulary → `ProviderOutcome` | addon `status_mapper.py` |

Rule of thumb, as in 0013: **if removing e-GRAS tomorrow would delete the code,
it belongs in the addon. Otherwise it belongs in `apps.payments`.**

Where e-GRAS identifiers land, all in the generic fields of 0017 #2.3:

| e-GRAS concept | Dristi field |
| --- | --- |
| `Applicationnumber` (our correlation id) | `Payment.provider_payment_id` |
| `GRN` (government receipt number) | `Payment.provider_reference` |
| `CIN`, bank code, bank date | `Payment.metadata["provider"]` |
| failure reason | `Payment.failure_code`, e.g. `EGRAS_PAYMENT_FAILED` |

---

## 4. Initiation

### 4.1 Transport

```text
Browser form POST, application/x-www-form-urlencoded
action = EGRAS_PAYMENT_URL      (NIC-issued e-Challan posting URL, per environment)
```

Dristi never posts this form server-side. The provider returns
`ProviderAction(kind=REDIRECT_FORM, url=EGRAS_PAYMENT_URL, method="POST",
form_fields=...)`; the UI renders a hidden form and submits it, treating
`form_fields` as opaque (0017 #12.2) — exactly as the eSign UI does in
[0015](0015-cdac-esign.md) #6.1. The client carries no e-GRAS knowledge.

Only net banking / UPI (`ptype = N`) is in scope. Manual challans (`ptype = M`)
are out of scope (#14).

### 4.2 Form fields

| e-GRAS field | Source | Format |
| --- | --- | --- |
| `DTO` | `EGRAS_DTO` | 2 digits |
| `STO` | `EGRAS_STO` | 2 digits |
| `DDO` | `EGRAS_DDO` | 4 characters |
| `Deptcode` | `EGRAS_DEPT_CODE` | 3 characters |
| `Officename` | `EGRAS_OFFICE_NAME`, else `DTO + STO + DDO` | 8 characters |
| `USERID` | `EGRAS_USER_ID` | default `guest` |
| `ChallanYear` | financial year of `initiated_at` in IST (#4.5) | 4 digits, e.g. `2627` |
| `Applicationnumber` | `provider_payment_id` (#4.4) | ≤ 20, `[A-Za-z0-9 /-]` |
| `Fullname` | `payer.name` | ≤ 50, alphanumeric and space |
| `Cityname` | `payer.city`, else fallback | ≤ 50, letters and space |
| `Address` | `payer.address`, else fallback | ≤ 100, `[A-Za-z0-9 /,#-]` |
| `PINCODE` | `payer.pincode`, else fallback | 6 digits |
| `Securityemail` | `payer.email` | valid email or blank |
| `Securityphone` | `payer.phone` | 10 digits or blank |
| `bank` | `options["bank"]`, else `EGRAS_DEFAULT_BANK` (#4.6) | NIC bank code |
| `ptype` | constant `N` | — |
| `Remarks` | `EGRAS_REMARKS_TEMPLATE` (#4.7) | ≤ 200, `[A-Za-z0-9 /,#-]` |
| `TotalAmount` | sum of scheme amounts | integer rupees |
| `SCHEMECOUNT` | number of schemes | 1 … `EGRAS_MAX_SCHEMES` |
| `SCHEMENAME{n}` / `FEEAMOUNT{n}` | #4.3 | 17-char scheme code / integer |
| `UURL` | `EGRAS_RETURN_URL` | absolute `https://` URL of the callback endpoint (0017 #9.6) |

`VALID_UPTO`, `CSC_ID` and `CSC_Amount` are not sent: they belong to manual and
CSC modes, which are out of scope. The exact name of the first scheme field is
confirmed during NIC onboarding (#16, Q-3); it is a constant in
`constants.py`, not a setting.

### 4.3 Schemes (heads of account)

e-GRAS is paid **per government scheme**, not per line item. `schemes.py` turns
the request's `ChargeLine`s into `SCHEMENAME`/`FEEAMOUNT` pairs:

```text
for each ChargeLine:
    scheme = EGRAS_SCHEME_MAP[line.account_head]      if present
          or line.account_head                         if it is itself a valid scheme code
          or EGRAS_SCHEME_MAP[line.charge_type]        if present
          or ProviderPermanentError(EGRAS_SCHEME_UNMAPPED)

group lines by scheme, sum amounts per scheme
each scheme amount must be a whole number of rupees  else EGRAS_FRACTIONAL_AMOUNT
number of schemes  <= EGRAS_MAX_SCHEMES               else EGRAS_TOO_MANY_SCHEMES
order schemes by scheme code                          (determinism, 0017 #9.2 rule 2)
TotalAmount = sum of scheme amounts == request.amount
```

- A valid scheme code is 17 characters in the `NNNN-NN-NNN-NN-NN` shape
  (`^\d{4}-\d{2}-\d{3}-\d{2}-\d{2}$`).
- `EGRAS_SCHEME_MAP` keys may be `account_head` values or `charge_type` values;
  `account_head` is looked up first because it is the fee master's own
  snapshot. The map is state configuration, never code.
- **There is no default scheme.** Crediting money to a wrong head of account is
  worse than refusing the payment, so an unmapped charge is a permanent,
  operator-visible configuration error.
- **The addon never rounds.** e-GRAS carries whole rupees; 0017 carries paise.
  Two `₹12.50` lines on the same head sum to `₹25` and pass; a lone `₹12.50` on
  a head fails with `EGRAS_FRACTIONAL_AMOUNT`. Rounding a court fee is a fee
  master decision owned by the raising module, not a transport decision
  (#16, Q-1).
- Only government-charge schemes are used. `EGRAS_MAX_SCHEMES` defaults to the
  government-charge slot count (`4`); service-charge slots (payments to
  non-government accounts) are out of scope.
- A batch across several demands produces one scheme set for the whole e-GRAS
  transaction. The per-demand breakup stays in `apps.payments`
  (`PaymentDemandItem`), which is what each case's receipt is built from.

### 4.4 Application number (`provider_payment_id`)

```text
Applicationnumber = EGRAS_APPLICATION_PREFIX + upper(request.reference.hex)[:20 - len(prefix)]
e.g.  "DR" + "0F9D3A6C1B2E4F5A7B" -> "DR0F9D3A6C1B2E4F5A7B"   (20 characters)
```

- Derived from `reference` (the batch id, or the payment id), so it is
  deterministic, unique per collection attempt, and traceable back to Dristi
  by prefix match.
- A retry is a new `Payment` ([0017](0017-orders-management.md) #4), hence a
  new `reference` and a new application number. e-GRAS never sees the same
  number twice.
- The prefix (≤ 2 characters, default `DR`) separates Dristi traffic from other
  departmental traffic in e-GRAS support queries.

### 4.5 Financial year

`ChallanYear` is the Indian financial year (1 April – 31 March) containing
`request.initiated_at` in IST, written as the last two digits of each year:

```text
2026-10-12 -> FY 2026-27 -> "2627"
2027-03-31 -> FY 2026-27 -> "2627"
2027-04-01 -> FY 2027-28 -> "2728"
```

It uses `initiated_at`, never the clock at build time, so a replay across
midnight on 31 March yields the same form
([0017](0017-orders-management.md) #9.2 rule 2).

### 4.6 Bank selection

The user selects a bank (or UPI) **in Dristi**, because `bank` is a required
field of the posted form.

- `list_options()` returns `EGRAS_BANK_OPTIONS` as `PaymentOption`s; the UI
  renders them from the options endpoint
  ([0017](0017-orders-management.md) #12.4) without knowing they are e-GRAS
  bank codes.
- `options["bank"]` must be one of the configured codes, else
  `ProviderPermanentError(EGRAS_INVALID_BANK, field="bank")`, which
  `apps.payments` returns as `400 E03020` on `provider_options.bank`
  ([0017](0017-orders-management.md) #12.5).
- When the client sends none, `EGRAS_DEFAULT_BANK` is used; when that is empty
  too, `EGRAS_BANK_REQUIRED` with `field="bank"`, returned the same way. A
  deployment with a single aggregator sets the default and the UI can skip the
  picker.
- The bank list is NIC-issued configuration, not code; adding an aggregator is
  an `.env` change.

### 4.7 Remarks

```text
EGRAS_REMARKS_TEMPLATE = "Dristi {demand_numbers}"
```

`{demand_numbers}` joins the request's demand numbers with spaces. When the
sanitised result exceeds 200 characters (a large bulk-filing batch), it is cut
to whole numbers and suffixed `and N more`. Remarks are informational at
e-GRAS; correlation never depends on them.

### 4.8 Sanitisation

`sanitise.py` makes every field acceptable to e-GRAS rather than rejecting the
payment over a payer's punctuation:

- Characters outside the field's allowed set are removed; runs of spaces
  collapse; the result is trimmed and cut to the field length.
- Non-ASCII letters (Malayalam, Hindi, …) are removed from restricted fields.
  If `Fullname` ends up empty, the payer's name is not representable and the
  payment fails with `EGRAS_INVALID_PAYER` (permanent) — a challan with no name
  is not acceptable.
- `Cityname`, `Address`, `PINCODE` fall back to `EGRAS_PAYER_FALLBACK_CITY`,
  `EGRAS_PAYER_FALLBACK_ADDRESS`, `EGRAS_PAYER_FALLBACK_PINCODE` (defaults
  `NA`, `NA`, `000000`) when empty after sanitisation.
- An invalid email or a phone that is not exactly 10 digits after stripping a
  leading `+91`/`0` is sent blank, not rejected.
- Sanitisation is pure and has its own tests; the sanitised payer is what the
  form carries, and the original `Payer` stays on the `Payment` snapshot.

### 4.9 Currency and limits

- `currency` must be `INR`, else `EGRAS_UNSUPPORTED_CURRENCY`.
- `request.amount` must be `> 0` and equal the scheme total; a mismatch is
  `EGRAS_AMOUNT_INCONSISTENT` and indicates a bug in the caller, not in e-GRAS.

---

## 5. Callback

### 5.1 What arrives

After the bank returns, e-GRAS auto-submits a browser form to `UURL`:

| Field | Meaning |
| --- | --- |
| `Applicationnumber` | our `provider_payment_id` |
| `GRN` | e-GRAS receipt number (integer) |
| `status` | `Success` / `Pending` / `Failure` / `Not Found`, or an error description |
| `CIN` | bank challan identification number; present on success |
| `bankcode` | bank used |
| `amount` | integer rupees |
| `tdate` | transaction date, `dd/mm/yyyy` |
| `payment_type` | `N` |

### 5.2 Parsing rules

`callback_parser.parse(payload) -> ProviderCallback`:

- Field names are matched case-insensitively (`status`/`Status`).
- `trusted` is **always `False`**. Nothing in the payload is signed, so it is a
  hint that tells `apps.payments` *which* payment to verify — never *what*
  happened.
- `Applicationnumber` is required and must match the configured prefix and
  length; otherwise `ProviderCallbackMalformed`. An error-only callback
  (`status` with a description and no application number) cannot be correlated:
  `apps.payments` redirects the browser with `status=UNKNOWN` and its poller
  ([0017](0017-orders-management.md) #9.7) resolves the payment through
  `fetch_status`.
- The hinted outcome, `GRN`, `CIN`, `amount` and `tdate` are parsed best-effort
  into `ProviderStatus` and recorded in the `EGRAS_CALLBACK_RECEIVED` log line;
  they are never applied.

### 5.3 Why the callback is never trusted

Anyone can POST a hand-made form to a public URL. If `status=Success` were
believed, a forged callback with a known application number would unlock a
case, a process or a join-a-case access gate without any money moving. Trust
comes only from #6.

---

## 6. Verification

### 6.1 Call

```text
SOAP 1.1 over HTTPS, POST EGRAS_VERIFY_URL   (NIC GRN status service, per environment)
operation: GetGrnDetails_identity(Applicationnumber, Deptcode)
timeout:   EGRAS_TIMEOUT
TLS:       1.2+, certificate verification on (EGRAS_VERIFY_SSL)
```

- The lookup is **always by identity** — our own `Applicationnumber` plus
  `EGRAS_DEPT_CODE`. Lookup by a callback-supplied `GRN` is never used for
  confirmation: a forged callback could otherwise point verification at
  someone else's successful GRN of the same amount.
- The envelope is built by hand and the response parsed with `defusedxml`; no
  SOAP framework dependency is introduced for one operation.
- Transport errors, timeouts, non-2xx responses and unparsable XML raise
  `ProviderTransientError` (`EGRAS_VERIFY_TIMEOUT`,
  `EGRAS_VERIFY_UNAVAILABLE`, `EGRAS_VERIFY_MALFORMED`).

### 6.2 Response

```xml
<GrnDetails>
  <GRN>1231234</GRN>
  <Amount>775</Amount>
  <Purpose>Dristi DMD-2026-000123</Purpose>
  <Status>Successfull</Status>
  <CIN>...</CIN>
  <Bankdate>12/10/2026</Bankdate>
</GrnDetails>
```

### 6.3 Status mapping (`status_mapper.py`)

| e-GRAS `Status` (case-insensitive, trimmed) | Extra conditions | `ProviderOutcome` |
| --- | --- | --- |
| `Successfull` / `Success` | `GRN` and `CIN` non-empty, `Amount` an integer | `SUCCESS` |
| `Successfull` / `Success` | `GRN` or `CIN` missing | `PENDING` (`EGRAS_SUCCESS_INCOMPLETE`) |
| `Failure` | — | `FAILED` (`EGRAS_PAYMENT_FAILED`) |
| `Pending` | — | `PENDING` |
| `Not Found` | — | `NOT_FOUND` |
| every element empty, `Status` = `Pending` | e-GRAS "try later" response | `ProviderTransientError(EGRAS_VERIFY_EMPTY)` |
| anything else | — | `PENDING` (`EGRAS_UNKNOWN_STATUS`, logged at warning) |

- `ProviderStatus.amount` is `Decimal(Amount)`; `provider_reference` is `GRN`;
  `paid_at` is `Bankdate` at IST midnight when parsable, else `None`;
  `metadata` carries `cin`, `bank_date` and, from the callback hint, `bankcode`.
- Unknown vocabulary maps to `PENDING`, never `FAILED`
  ([0017](0017-orders-management.md) #9.2 rule 5): e-GRAS explicitly asks
  departments to re-check any unrecognised status.
- The amount comparison against the Dristi payment happens in `apps.payments`
  ([0017](0017-orders-management.md) #9.5), not here — the provider reports,
  the payments module decides.

### 6.4 Timing

| Provider attribute | e-GRAS value | Why |
| --- | --- | --- |
| `pending_horizon` | `EGRAS_PENDING_HORIZON`, default 9 days | e-GRAS marks a transaction failed on the 8th day when the bank never reports; one day of margin |
| `not_found_grace` | `EGRAS_NOT_FOUND_GRACE`, default 2 hours | the GRN exists once the form reaches e-GRAS; still `Not Found` after this means the user never got there |

---

## 7. Provider surface

```python
# addon/egras_payment_gateway/provider.py
from apps.payments.providers.base import PaymentProvider


class EGRASPaymentProvider(PaymentProvider):
    """Collect payments into government heads of account through e-GRAS."""

    name = "egras"
    pending_horizon = ...   # EGRAS_PENDING_HORIZON, #6.4
    not_found_grace = ...   # EGRAS_NOT_FOUND_GRACE, #6.4

    def list_options(self) -> list[PaymentOption]: ...         # EGRAS_BANK_OPTIONS, #4.6
    def initiate(self, request) -> ProviderInitiation: ...     # #4, no network call
    def fetch_status(self, *, provider_payment_id) -> ProviderStatus: ...   # #6
    def parse_callback(self, payload) -> ProviderCallback: ... # #5, trusted=False
```

`initiate` makes **no network call**: it only builds form fields. It can
therefore fail only permanently (configuration, mapping, payer, amount), never
transiently, which keeps create-payment predictable.

Activation is configuration only:

```python
PAYMENT_PROVIDERS = {
    "mock": "apps.payments.providers.mock.MockPaymentProvider",
    "egras": "addon.egras_payment_gateway.provider.EGRASPaymentProvider",
}
PAYMENT_DEFAULT_PROVIDER = "egras"      # only change needed to go live
```

Recommended per-environment default: `mock` in `config.settings.local` and
`config.settings.test`; `egras` in staging (pointed at the NIC UAT URLs) and
production.

---

## 8. Replacing e-GRAS

The generic procedure is 0017 #9.8. For e-GRAS specifically:

```text
1. Register the new provider in PAYMENT_PROVIDERS; keep "egras".
2. Point PAYMENT_DEFAULT_PROVIDER at it.        -> new payments use it immediately
3. Wait until `manage.py payments_provider_usage egras` shows no PENDING payment
   — at most EGRAS_PENDING_HORIZON.
4. Remove "egras" from PAYMENT_PROVIDERS, the INSTALLED_APPS entry and the
   EGRAS_* block, and delete src/addon/egras_payment_gateway/.
```

Between steps 2 and 3, e-GRAS callbacks and polls still resolve through the
registered e-GRAS provider. Historic payments keep `provider="egras"` and their
GRN in `provider_reference`; they never need the addon again. `EGRAS_ENABLED =
False` is the emergency variant of step 2: new e-GRAS payments are refused
while verification keeps working for those in flight.

---

## 9. Configuration

### 9.1 Namespace

Addon-owned settings use the `EGRAS_` prefix, visibly distinct from
`PAYMENT_*` (owned by 0017). They live in one block in
`config/settings/base.py`, so the integration is removed by deleting that block
plus the `INSTALLED_APPS` and `PAYMENT_PROVIDERS` entries.

One deployment serves one state and collects into one department, so there is
exactly one set of e-GRAS codes, read flat from the environment. A different
state is a different `.env`, never a different code path.

### 9.2 Settings

```python
# config/settings/base.py — e-GRAS payment provider addon (addon.egras_payment_gateway)
# Remove this block, the INSTALLED_APPS entry, and PAYMENT_PROVIDERS["egras"]
# to remove the integration.
EGRAS_PAYMENT_URL = env("EGRAS_PAYMENT_URL", default="")
EGRAS_VERIFY_URL = env("EGRAS_VERIFY_URL", default="")
EGRAS_RETURN_URL = env("EGRAS_RETURN_URL", default="")
EGRAS_DEPT_CODE = env("EGRAS_DEPT_CODE", default="")
...
```

| Setting | Required | Default | Notes |
| --- | --- | --- | --- |
| `EGRAS_PAYMENT_URL` | yes | `""` | e-Challan posting URL (UAT or production) |
| `EGRAS_VERIFY_URL` | yes | `""` | GRN status SOAP service |
| `EGRAS_RETURN_URL` | yes | `""` | absolute `https://…/api/v1/payments/providers/egras/_callback` |
| `EGRAS_DEPT_CODE` | yes | `""` | 3 characters, department code from the budget |
| `EGRAS_DTO` | yes | `""` | 2 digits |
| `EGRAS_STO` | yes | `""` | 2 digits |
| `EGRAS_DDO` | yes | `""` | 4 characters |
| `EGRAS_OFFICE_NAME` | no | `DTO+STO+DDO` | override only if NIC issues a different value |
| `EGRAS_USER_ID` | no | `guest` | |
| `EGRAS_SCHEME_MAP` | yes | `{}` | JSON: `account_head` or `charge_type` → 17-char scheme code |
| `EGRAS_MAX_SCHEMES` | no | `4` | government-charge scheme slots |
| `EGRAS_BANK_OPTIONS` | yes | `[]` | JSON list of `{code, label, group}` issued by NIC |
| `EGRAS_DEFAULT_BANK` | no | `""` | must be one of the option codes |
| `EGRAS_APPLICATION_PREFIX` | no | `DR` | ≤ 2 characters, alphanumeric |
| `EGRAS_REMARKS_TEMPLATE` | no | `Dristi {demand_numbers}` | |
| `EGRAS_PAYER_FALLBACK_CITY` | no | `NA` | |
| `EGRAS_PAYER_FALLBACK_ADDRESS` | no | `NA` | |
| `EGRAS_PAYER_FALLBACK_PINCODE` | no | `000000` | |
| `EGRAS_TIMEOUT` | no | `15` s | verification connect/read timeout |
| `EGRAS_VERIFY_SSL` | no | `True` | rejected as `False` in production |
| `EGRAS_PENDING_HORIZON` | no | `9` d | `pending_horizon`; must be ≥ 8 days |
| `EGRAS_NOT_FOUND_GRACE` | no | `2` h | `not_found_grace` |
| `EGRAS_ENABLED` | no | `True` | kill switch; `initiate` raises `EGRAS_DISABLED` (permanent), verification keeps working so in-flight payments still resolve |

`resolve_config()` loads the `EGRAS_*` values into a frozen `EGRASConfig`
dataclass once and caches it (cleared on `setting_changed` for tests), as
`CDACConfig` does in 0013. e-GRAS has no credential, so nothing needs
redacting; payer data is masked in logs instead (#11).

Every setting is documented in `.env.example`, `.env.prod.example` and
`README.md`.

### 9.3 Startup validation

System checks registered in the addon's `AppConfig.ready()`, error level, only
when `"egras"` is in `PAYMENT_PROVIDERS`:

- every required `EGRAS_*` value is set;
- `EGRAS_PAYMENT_URL`, `EGRAS_VERIFY_URL`, `EGRAS_RETURN_URL` are absolute
  `https://` URLs, and `EGRAS_RETURN_URL` ends with the generic callback path
  for `egras`;
- `EGRAS_DTO`, `EGRAS_STO`, `EGRAS_DDO`, `EGRAS_DEPT_CODE` have the required
  lengths, and the office name is 8 characters;
- every `EGRAS_SCHEME_MAP` value is a valid 17-character scheme code;
- `EGRAS_BANK_OPTIONS` parses, codes are unique, and `EGRAS_DEFAULT_BANK` (if
  set) is among them;
- `EGRAS_APPLICATION_PREFIX` is ≤ 2 alphanumeric characters;
- `EGRAS_PENDING_HORIZON` ≥ 8 days;
- warning when `EGRAS_SCHEME_MAP` has no entry for a `ChargeType` value, so a
  charge that will fail at payment time is visible at deploy time;
- production: `EGRAS_VERIFY_SSL` on.

Checks are silent when the addon is installed but `"egras"` is not a registered
provider, so local/CI need no e-GRAS codes.

---

## 10. Failure codes

e-GRAS never defines API error codes: the addon contributes no `errors.py`, and
nothing it raises reaches a client unchanged. Its codes are **internal failure
codes** in `constants.py`, carried on `ProviderError.code` or
`ProviderStatus.failure_code`. `apps.payments` stores them on
`Payment.failure_code`, logs them, and maps the exception class to its own
registered API code ([0017](0017-orders-management.md) #12.5). Swapping
providers therefore never changes the API's codes.

| Failure code | Raised as | Stored / returned by `apps.payments` |
| --- | --- | --- |
| `EGRAS_DISABLED` | `ProviderPermanentError` | `FAILED`; `422 E03014` |
| `EGRAS_INVALID_CONFIGURATION` | `ProviderPermanentError` | `FAILED`; `422 E03014` |
| `EGRAS_UNSUPPORTED_CURRENCY` | `ProviderPermanentError` | `FAILED`; `422 E03014` |
| `EGRAS_SCHEME_UNMAPPED` | `ProviderPermanentError` | `FAILED`; `422 E03014` |
| `EGRAS_FRACTIONAL_AMOUNT` | `ProviderPermanentError` | `FAILED`; `422 E03014` |
| `EGRAS_TOO_MANY_SCHEMES` | `ProviderPermanentError` | `FAILED`; `422 E03014` |
| `EGRAS_AMOUNT_INCONSISTENT` | `ProviderPermanentError` | `FAILED`; `422 E03014` |
| `EGRAS_INVALID_PAYER` | `ProviderPermanentError` | `FAILED`; `422 E03014` |
| `EGRAS_INVALID_BANK` | `ProviderPermanentError(field="bank")` | `FAILED`; `400 E03020` on `provider_options.bank` |
| `EGRAS_BANK_REQUIRED` | `ProviderPermanentError(field="bank")` | `FAILED`; `400 E03020` on `provider_options.bank` |
| `EGRAS_CALLBACK_MALFORMED` | `ProviderCallbackMalformed` | nothing written; redirect `status=UNKNOWN` |
| `EGRAS_VERIFY_TIMEOUT` | `ProviderTransientError` | unchanged; retried by the poller |
| `EGRAS_VERIFY_UNAVAILABLE` | `ProviderTransientError` | unchanged; retried by the poller |
| `EGRAS_VERIFY_MALFORMED` | `ProviderTransientError` | unchanged; retried by the poller |
| `EGRAS_VERIFY_EMPTY` | `ProviderTransientError` | unchanged; retried by the poller |
| `EGRAS_PAYMENT_FAILED` | `ProviderStatus(FAILED)` | `FAILED` with this `failure_code` |
| `EGRAS_SUCCESS_INCOMPLETE` | `ProviderStatus(PENDING)` | unchanged; logged |
| `EGRAS_UNKNOWN_STATUS` | `ProviderStatus(PENDING)` | unchanged; logged at warning |

The raw e-GRAS `Status` text goes to the log line, never to `failure_message`,
which stays a safe, generic sentence.

---

## 11. Security

- The callback is unauthenticated by necessity and e-GRAS signs nothing.
  Authenticity comes solely from the server-to-server lookup by our own
  application number (#6.1), plus the amount check in 0017 #9.5.
- A callback can only *select* a payment by `Applicationnumber`; it can never
  supply the outcome, amount or GRN that gets applied.
- No access gate (case filing to Scrutiny, process to signing, advocate case
  access) opens on anything but a `SUCCESS` written by `confirm_payment`.
- TLS 1.2+ with certificate verification for the verification call; disabling
  it is rejected in production.
- `defusedxml` parses every verification response, closing entity-expansion
  attacks on XML we do not control.
- Never logged: payer email, phone or address in full (masked: name initial,
  last 4 phone digits), or the full form body. `Applicationnumber`, GRN, CIN
  and amounts are receipt data, not secrets, and are logged.

---

## 12. Logging

One structured line per stage under the `addon.egras_payment_gateway` logger,
always carrying `provider_payment_id` and, where known, `payment_id` or
`batch_id`. The lifecycle events (`PAYMENT_PENDING`, `PAYMENT_CONFIRMED`,
`PAYMENT_AMOUNT_MISMATCH`, …) are logged by `apps.payments`.

| Event | Emitted by |
| --- | --- |
| `EGRAS_REQUEST_BUILT` (scheme count, total, bank, masked payer) | `request_builder.py` |
| `EGRAS_CALLBACK_RECEIVED` (hinted status, GRN) | `callback_parser.py` |
| `EGRAS_VERIFY_REQUEST` / `EGRAS_VERIFY_RESPONSE` (status, GRN, amount, latency) | `verification_client.py` |

```text
event=EGRAS_VERIFY_RESPONSE payment_id=... provider_payment_id=DR0F9D3A6C1B2E4F5A7B
egras_status=Successfull outcome=SUCCESS grn=1231234 amount=775 latency_ms=412
```

---

## 13. Testing

**Unit (no network)**
- schemes: map by `account_head`, by valid-format `account_head`, by
  `charge_type`; precedence; unmapped; grouping and summing; whole-rupee pass
  (`12.50 + 12.50`) and fail (`12.50`); too many schemes; deterministic order.
- request builder: every field and its source; `Officename` derivation and
  override; `ChallanYear` across 31 March / 1 April in IST; application number
  length, prefix and determinism; remarks truncation with `and N more`;
  `TotalAmount == sum(FEEAMOUNT)`; `ptype = N`; `UURL`; identical output on
  replay.
- sanitise: each field's character set and length; Malayalam/Hindi names;
  empty-name rejection; fallbacks; phone normalisation; invalid email blanked.
- bank options: valid code, invalid code and missing code raise with
  `field="bank"`; default used.
- callback parser: success/pending/failure/not-found hints, case-insensitive
  names, missing `Applicationnumber`, wrong prefix, error-only payload,
  `trusted` always `False`.
- verification client: SOAP envelope, identity lookup only, TLS settings,
  timeout, non-2xx, malformed XML, entity expansion rejected.
- status mapper: every row of #6.3, including the empty "try later" response
  and unknown vocabulary → `PENDING`.
- failure codes: every row of #10 raises the stated exception class with the
  stated code.
- config/checks: defaults, each check failure mode, silence when the addon is
  not registered, production guards.

**Flow (DB + stub broker, mocked e-GRAS endpoints, through 0017's APIs)**
- create payment → `201` with a `REDIRECT_FORM` carrying the e-GRAS fields.
- forged `Success` callback with no e-GRAS record → payment still `PENDING`.
- callback → verification `Successfull` → `SUCCESS`, items `PAID`, GRN in
  `provider_reference`, CIN in metadata.
- batch of three demands → one application number, one scheme set, one
  verification → three payments `SUCCESS`.
- unmapped charge → `422 E03014` and a `FAILED` payment with
  `failure_code = EGRAS_SCHEME_UNMAPPED`; invalid bank → `400 E03020` on
  `provider_options.bank`. Assertions on `code` and `field`, never message.
- abandonment → `Not Found` past grace → `FAILED`, items payable again.
- `Failure` → `FAILED` with `EGRAS_PAYMENT_FAILED`.

**Isolation**
- no module under `apps.payments` imports `addon.*` or mentions `egras`;
- the addon imports only `apps.payments.providers.base` and has no
  `errors.py`, `urls.py`, `models.py` or `admin.py`;
- removing `"egras"` from settings leaves `apps.payments` working on the mock.

**Manual / end-to-end** against NIC UAT with the test bank and UPI handles:
success, failure, abandonment and a batch — each confirmed by the GRN status
service and visible in Dristi with the right GRN.

```bash
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest
cd src && ruff check . && ruff format .
cd src && python manage.py check
```

---

## 14. Out of scope

- Manual (bank-branch) challans, challan PDF download, POS and CSC wallet modes.
- Service-charge scheme slots and payments to non-government accounts.
- Refunds, refund notes, reversals, settlement and treasury reconciliation.
- Per-court office (DTO/STO/DDO) routing within one deployment.
- Rounding or re-pricing fees to whole rupees.
- Receipt generation; this spec only makes sure a receipt has the GRN and CIN.
- Any admin UI for e-GRAS configuration; DB-managed configuration.

## 15. Acceptance criteria

- [ ] e-GRAS ships as `src/addon/egras_payment_gateway/` with no models, migrations, URLs, admin or `errors.py`.
- [ ] e-GRAS is selected purely by `PAYMENT_PROVIDERS` / `PAYMENT_DEFAULT_PROVIDER`; no caller changes.
- [ ] The addon imports only `apps.payments.providers.base`; no module under `apps.payments` imports `addon.*` or mentions e-GRAS.
- [ ] Deleting the addon plus its settings leaves `apps.payments` working on the mock provider.
- [ ] `initiate` makes no network call and is deterministic for the same request.
- [ ] Form fields match #4.2; schemes are grouped per #4.3 with no default scheme and no rounding.
- [ ] Application number is deterministic, ≤ 20 characters, and new per payment attempt.
- [ ] `ChallanYear` comes from `initiated_at` in IST.
- [ ] Payer fields are sanitised to e-GRAS character sets with documented fallbacks.
- [ ] `parse_callback` always returns `trusted=False`; verification is always by our own application number.
- [ ] e-GRAS statuses map per #6.3; unknown vocabulary is `PENDING`.
- [ ] `pending_horizon` ≥ 8 days; `not_found_grace` configurable.
- [ ] Every failure is raised as the exception class in #10; e-GRAS codes never appear in an API `errors` array.
- [ ] Batches produce one e-GRAS transaction and one verification for all their payments.
- [ ] GRN lands in `provider_reference`, CIN in `metadata["provider"]`.
- [ ] `manage.py check` fails on invalid e-GRAS configuration and is silent when the addon is not registered.
- [ ] Payer contact data never appears unmasked in logs.
- [ ] Unit, flow and isolation tests pass; Ruff clean.

---

## 16. Open questions

1. **Whole rupees.** Court fee, legal benefit fee and process fees are ₹12.50.
   Are all fees on a head guaranteed to sum to whole rupees, does the fee
   master round (and how), or does the treasury accept a different head
   grouping? Until answered, odd ₹12.50 lines fail with
   `EGRAS_FRACTIONAL_AMOUNT`.
2. **Heads of account.** Which scheme code does each `ChargeType` credit, and
   does any single payment ever need more than four heads (a full filing bill
   has seven fee heads)? If so, is splitting into several e-GRAS transactions
   acceptable, given that a batch must succeed or fail as one?
3. **First scheme field name.** NIC's sample posts the first scheme as
   `SCHEMENAME` while the field list names it `SCHEMENAME1`; confirm during
   onboarding.
4. **Office codes.** Does one DDO collect for every court in a deployment, or
   does each court/establishment need its own DTO/STO/DDO (ties to 0017 Q-3)?
5. **`Not Found` grace.** Confirm with NIC that a GRN always exists once the
   form reaches e-GRAS, so two hours of `Not Found` is safe to treat as
   abandonment.
6. **Manual challans.** Is bank-branch payment (`ptype = M`) needed for
   litigants without net banking or UPI? It would add a `CHALLAN` action kind
   to 0017 and a challan PDF download.
7. **Bank list.** Should `EGRAS_BANK_OPTIONS` move to the configuration store
   ([0018](0018-configuration-store.md)) so NIC changes need no redeploy?

## 17. Design decisions

| Decision | Rationale |
| --- | --- |
| e-GRAS lives in `addon.egras_payment_gateway`, not `apps.payments` | Mirrors 0013/0015. The payment lifecycle outlives any gateway; form fields, scheme codes and SOAP calls are swappable detail. |
| Callback never trusted; identity lookup is the only proof | e-GRAS signs nothing. Looking up by our own application number, not a callback-supplied GRN, stops a forged callback from borrowing someone else's payment. |
| `initiate` is local and deterministic | The browser needs the form now; idempotent replay rebuilds it without storing payer-bearing form bodies, and the financial year from `initiated_at` keeps it stable across 31 March. |
| Unknown status → `PENDING`, never `FAILED` | e-GRAS asks departments to re-check unrecognised statuses; failing early risks money taken with no credit. |
| `pending_horizon` of 9 days | e-GRAS only declares failure on the 8th day; one day of margin. |
| `NOT_FOUND` with a short grace | Frees abandoned attempts quickly without ever failing a transaction e-GRAS actually knows about. |
| No default scheme, no rounding | Money in the wrong head of account, or a re-priced court fee, is worse than a visible failure. Both are fee master decisions. |
| Bank chosen in Dristi through opaque options | The posted form requires a bank code; opaque options keep the UI provider-agnostic. |
| Sanitise payer fields rather than reject | A litigant must not be unable to pay because of punctuation in an address; only an unrepresentable name is fatal. |
| Internal failure codes, no API error codes | API codes are registered per domain app ([0000](0000-api-coding-spec.md) #9.2) and must survive a provider swap; the addon reports, `apps.payments` decides what the client sees. |
| Hand-built SOAP + `defusedxml` | One operation does not justify a SOAP framework; `defusedxml` closes XML entity attacks on a response we do not control. |
| `EGRAS_ENABLED` stops initiation only | Turning e-GRAS off must not strand payments already at the bank. |

## 18. Implementation phases

Blocked on 0017's provider contract (#9) and error codes (#12.5) landing.

1. **Scaffolding** — `egras_payment_gateway` app, `config.py`, `constants.py`,
   settings block, env/README docs, system checks, isolation test.
2. **Pure functions** — `schemes.py`, `sanitise.py`, `request_builder.py`,
   `callback_parser.py`, `status_mapper.py` + unit tests.
3. **Verification** — `verification_client.py` against a mocked SOAP
   endpoint, `provider.py`, flow tests through 0017's APIs.
4. **Rollout** — end-to-end run against NIC UAT, then switch
   `PAYMENT_DEFAULT_PROVIDER` per environment.
