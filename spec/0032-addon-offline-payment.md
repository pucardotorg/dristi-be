# 0032 — Offline Payment Provider Addon (`addon.offline_payment`)

## Status

Proposed

## References

- [0017 — Payments Module](0017-orders-management.md) — `apps.payments`, the consuming module; owns demands, payments, balances, the provider contract (#9), polling, permissions and the API error codes. This spec amends it in #4.
- [0022 — e-GRAS Payment Gateway Addon](0022-addon-egras-payment-gateway.md) — the first provider; this addon follows its layout, isolation and configuration rules, and runs **alongside** it (#12).
- [0000 — API Coding Spec](0000-api-coding-spec.md) — error shape and codes (#9), Swagger conventions (#10)
- [0004 — Simple Audit History](0004-simple-audit-history.md) — history of every state change
- [0013 — CDAC SMS Gateway Addon](0013-addon-cdac-sms-gateway.md) — the addon pattern and the "changes required in the domain module" section this spec copies
- PRDs: [`efiling-handover.md`](../PRDs/efiling-handover.md) §19 (`PAY`), [`court-roles.md`](../PRDs/court-roles.md) (`RLE-01`, `RLE-04`)

> **Scope note.** An offline payment is money handed over in person — cash, a
> demand draft or a card/UPI swipe at a court counter — and recorded in Dristi
> by court staff. The addon owns only what is specific to that channel: the
> payment request reference the payer quotes at the counter, the instructions
> shown to them, the validity window, and the validation of what staff record.
> Demands, payments, balances, numbering, idempotency, concurrency, case
> access, crediting, polling, audit, the staff APIs and every API error code
> stay in [`apps.payments`](0017-orders-management.md). The addon implements
> the provider contract of 0017 #9 as amended in #4, is selected purely by
> settings, and can be removed or replaced without touching any caller —
> exactly as e-GRAS can.

## Context

[0017](0017-orders-management.md) collects every Dristi charge — filing fees,
upfront process fees, application fees, join-a-case fees, costs — as `Demand`s
paid by `Payment`s through a provider. [0022](0022-addon-egras-payment-gateway.md)
ships the first real provider, e-GRAS, which collects online through net
banking and UPI.

Not every payer can pay online. A litigant without net banking, an advocate
whose bank's e-GRAS aggregator is down, or a court that still runs a fee counter
needs to pay in person. Today that is impossible without leaving Dristi: the
demand stays unpaid, the case stays in *Pending Payment*, and nothing records
the money the court actually received.

What an offline channel needs is different from a gateway in four ways:

| | Gateway (e-GRAS) | Offline |
| --- | --- | --- |
| Who completes the payment | the gateway, then reports it | **court staff**, who see the money and record it |
| Proof of payment | server-to-server lookup at the gateway | the staff member's **attestation** — receipt number, method, instrument — recorded under their account |
| What the payer does next | the browser posts a form | the payer **goes to a counter** with a reference |
| When it ends | the gateway declares the outcome | staff record it, or the request **expires** |

The provider contract of 0017 #9 was written for gateways only. It has no way
for a person to confirm a payment, blocks cancellation while the provider says
`PENDING`, and lets only one provider start new payments. This spec closes
those gaps generically in `apps.payments` (#4) and implements the offline
channel as an addon on top of them.

The money still flows from demands: a raising module raises a `Demand`; the
payer creates a `Payment` against its items, choosing the offline provider; staff
record the collection; `apps.payments` credits the items through
`confirm_payment` (0017 #6.4) and publishes `payment_completed` (0017 #14),
which moves the case on. No new money path is introduced.

## Goals

- Ship `OfflinePaymentProvider` in a standalone, removable module that
  satisfies the provider contract of 0017 #9, as amended in #4.
- Let a payer choose, per payment, between every provider the deployment
  offers — e-GRAS and offline side by side — without the client knowing
  provider internals.
- Give the payer a short, typo-resistant reference and clear instructions to
  pay at a counter.
- Let authorised court staff look up a payment request, check what is due, and
  record that the money was collected — first through the Django admin, later
  through REST APIs a counter screen can use.
- Credit a payment only through `confirm_payment`, only for the exact amount
  due, only once, and only on an attestation recorded by an authorised person
  who is not the payer.
- Make every attestation permanent, unique per receipt number and auditable.
- Expire unpaid requests, so items blocked by an abandoned request become
  payable again.
- Keep every offline detail inside `addon/offline_payment/`, with the same
  one-way dependency rule as e-GRAS.

## Non-goals

- Anything 0017 owns: demands, payments, balances, numbering, case access,
  receipts, the callback endpoint, polling and API error codes.
- Fee calculation, waivers, rounding.
- Cheques, or any instrument whose money is not final when handed over.
- Issuing receipt numbers from Dristi (#21, Q-1), printing receipts or a
  payment slip PDF.
- Cash book, treasury remittance, day-end cash reconciliation and deposit of
  collected money into a bank — beyond the read-only collection register (#9.3).
- Refunds, reversals and excess or short collections.
- A court role for collecting fees; this version uses a Django permission
  (#4.7, #21 Q-2).
- Models, migrations, URLs, views, admin or `errors.py` in the addon.

---

## 1. Module placement and dependency direction

```text
src/
├── apps/
│   ├── payments/                   # 0017 — domain, APIs, contract (amended in #4)
│   └── ...
├── addon/
│   ├── cdac_sms_gateway/           # 0013
│   ├── cdac_esign/                 # 0015
│   ├── egras_payment_gateway/      # 0022 — online, through the treasury
│   └── offline_payment/            # THIS SPEC — in person, recorded by staff
└── config/settings/base.py         # the only wiring point
```

```text
addon.offline_payment  -- imports -->        apps.payments.providers.base
apps.payments          -- never imports -->  addon.*
config.settings.base   -- references -->     "addon.offline_payment.provider.OfflinePaymentProvider"
```

The addon imports the contract — `PaymentProvider`, its dataclasses, enums and
exception types from `apps.payments.providers.base` — plus the read-only helpers
e-GRAS uses: `apps.payments.conf` (is `"offline"` registered?),
`apps.payments.checks.is_production_settings` and the `ChargeType` labels of
`apps.payments.enums` (validating `OFFLINE_PAYMENT_ALLOWED_CHARGE_TYPES`). It
never imports `apps.payments` models, services, selectors, tasks, views,
serializers, signals, the registry or the mock, never receives a model instance,
and never writes a balance. `tests/test_isolation.py` enforces this list, as in
0022.

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
]
```

The addon is an installed app only so it can register system checks. Its
`AppConfig` sets `name = "addon.offline_payment"` and an explicit
`label = "offline_payment"`. Deleting `src/addon/offline_payment/` plus its
settings entries leaves `apps.payments` working on the other providers.

### 1.1 Layout

```text
src/addon/offline_payment/
├── __init__.py
├── apps.py                  # AppConfig(name="addon.offline_payment", label="offline_payment")
├── provider.py              # OfflinePaymentProvider(PaymentProvider)
├── config.py                # OfflineConfig, resolve_config() (cached, frozen)
├── constants.py             # provider name, methods, field keys, failure codes, log events
├── reference.py             # request reference: build, normalise, parse, check symbol (#5.2)
├── validity.py              # valid_until / expires_at from the reference date (#6)
├── instructions.py          # InitiationRequest -> ProviderAction(SHOW_INSTRUCTIONS) (#5.4)
├── methods.py               # collection methods and their fields (#8.1)
├── attestation.py           # Attestation -> ProviderStatus, every rule of #8.2
├── checks.py                # Django system checks (#13.3)
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_config.py
    ├── test_reference.py
    ├── test_validity.py
    ├── test_instructions.py
    ├── test_methods.py
    ├── test_attestation.py
    ├── test_provider.py
    ├── test_checks.py
    ├── test_flow.py         # payer creates → staff records → SUCCESS, through 0017's APIs
    ├── test_coexistence.py  # offline and e-GRAS selectable together (#12)
    └── test_isolation.py
```

---

## 2. End-to-end flow

```text
PAYER (Dristi UI)
   |  GET  /api/v1/payments/providers/                      -> [egras, offline] with options   [#4.2]
   |  POST /api/v1/payments/demands/{id}/payments/
   |       {client_request_id, demand_item_ids, provider: "offline",
   |        provider_options: {counter: "EKM-CJM"}}
   v
apps.payments                                                                  [0017 #6.2]
   +-- Payment(s) INITIATED, COMMIT
   +-- registry.get_for_new_payment("offline") -> OfflinePaymentProvider      [#4.2]
   +-- provider.initiate(InitiationRequest)                                    [addon, #5]
   |       reference OFL-261111-7K3QF-9XM2H-V, valid_until, counter, instructions
   |       -> ProviderInitiation(SHOW_INSTRUCTIONS)
   +-- mark_pending(provider="offline", provider_payment_id=reference)
   v
201 {payment..., status: PENDING, provider_action: {kind: SHOW_INSTRUCTIONS, details: [...]}}
   |
   |  payer goes to the counter with the reference (and the money)
   v
COURT STAFF (Django admin today; counter screen later)
   |  GET  /api/v1/payments/collections/offline/OFL-261111-7K3QF-9XM2H-V/    -> amount due, items, case, payer
   |  takes the money, writes the receipt
   |  POST /api/v1/payments/collections/offline/OFL-261111-7K3QF-9XM2H-V/confirm/
   |       {amount, method: "CASH", receipt_number, collected_at, details, remarks}
   v
apps.payments                                                                  [#4.4]
   +-- permission, not-the-payer, receipt unique, request open   (under lock)
   +-- provider.attest(Attestation) -> ProviderStatus(SUCCESS)                 [addon, #8]
   +-- PaymentAttestation row (immutable)
   +-- apply_provider_status -> confirm_payment -> items PAID                  [0017 #9.5, #6.4]
   +-- on_commit: notify_payment_completed -> payment_completed signal         [0017 #14]
   v
200 {collection..., status: SUCCESS, attestation: {...}}

PAYER UI polls GET /api/v1/payments/payments/{id}/ -> SUCCESS, receipt number shown
```

When nobody records a collection, the 0017 poller (#9.7) calls `fetch_status`,
which reports `FAILED` once the request has expired (#6). The items become
payable again — online or offline.

---

## 3. Responsibility boundary

| Concern | Owner |
| --- | --- |
| Demands, items, balances, statuses, numbering, idempotency, case access | `apps.payments` (0017) |
| Which providers a payer may choose; routing by `Payment.provider` | `apps.payments` (#4.2, 0017 #9.3) |
| Staff APIs, admin form, permissions, "not the payer" rule | `apps.payments` (#4.4–#4.7, #9.2, #10) |
| `PaymentAttestation` storage, receipt-number uniqueness, locking | `apps.payments` (#4.3, #4.4) |
| Applying an outcome; crediting; late success; flags | `apps.payments` (0017 #9.5) |
| Polling, expiry enforcement through `FAILED`, cancellation | `apps.payments` (0017 #9.7, #4.5) |
| API error codes and the error response shape | `apps.payments` (#4.6) |
| Offline configuration loading | addon `config.py` |
| Request reference format, check symbol, normalisation | addon `reference.py` |
| Validity window and expiry | addon `validity.py` |
| Instructions shown to the payer; counters | addon `instructions.py` |
| Collection methods, their fields and limits | addon `methods.py` |
| Validating an attestation; mapping it to `ProviderStatus` | addon `attestation.py` |

Rule of thumb, as in 0013 and 0022: **if removing offline payments tomorrow
would delete the code, it belongs in the addon. Otherwise it belongs in
`apps.payments`.** The staff APIs, the attestation model and the
provider-choice support stay when the addon goes: any future attested channel
(a court-fee stamp vendor, a CSC operator) reuses them.

Where offline identifiers land, all in generic fields:

| Offline concept | Dristi field |
| --- | --- |
| request reference (`OFL-…`) | `Payment.provider_payment_id` |
| receipt number written by staff | `Payment.provider_reference`, `PaymentAttestation.receipt_number` |
| method, instrument details, `collected_at` | `PaymentAttestation`, and `Payment.metadata["provider"]` (non-sensitive subset) |
| who recorded it, when | `PaymentAttestation.created_by` / `created_at`; `Payment.updated_by`; history (0004) |
| expiry | `Payment.failure_code = OFFLINE_REQUEST_EXPIRED` |

---

## 4. Changes required in `apps.payments` (0017 amendments)

These live in the payments module because they are channel-agnostic. They are
backwards compatible: with only e-GRAS (or only the mock) configured, every
existing request and response keeps working unchanged.

### 4.1 Contract additions (`apps.payments.providers.base`)

```python
class ConfirmationMode(StrEnum):
    PROVIDER = "PROVIDER"  # the provider reports the outcome; fetch_status is authoritative
    ATTESTED = "ATTESTED"  # authorised staff record the collection through apps.payments


class ActionKind(StrEnum):
    REDIRECT_FORM = "REDIRECT_FORM"
    SHOW_INSTRUCTIONS = "SHOW_INSTRUCTIONS"  # NEW: show details; nothing to submit
    NONE = "NONE"


@dataclass(frozen=True)
class ActionDetail:  # NEW
    key: str  # stable machine key, e.g. "reference"; lets a client add a copy button
    label: str  # human label, rendered as-is
    value: str


@dataclass(frozen=True)
class ProviderAction:
    kind: ActionKind
    url: str = ""
    method: str = "POST"
    form_fields: Mapping[str, str] = field(default_factory=dict)
    details: tuple[ActionDetail, ...] = ()  # NEW: ordered; for SHOW_INSTRUCTIONS


@dataclass(frozen=True)
class AttestationField:  # NEW: one input a staff form renders
    key: str  # sent back in Attestation.details
    label: str
    kind: str  # "text" | "digits" | "date"
    required: bool = True
    max_length: int = 64


@dataclass(frozen=True)
class AttestationMethod:  # NEW: how money can be handed over
    code: str  # opaque, e.g. "CASH"
    label: str
    fields: tuple[AttestationField, ...] = ()


@dataclass(frozen=True)
class Attestation:  # NEW: what staff recorded, plus what apps.payments knows
    provider_payment_id: str
    expected_amount: Decimal  # sum of Payment.amount over the group, from apps.payments
    currency: str
    initiated_at: datetime  # earliest Payment.initiated_at of the group
    amount: Decimal  # what staff say they received
    method: str
    receipt_number: str
    collected_at: datetime
    details: Mapping[str, str]  # instrument fields keyed by AttestationField.key
    remarks: str


class PaymentProvider(ABC):
    name: ClassVar[str]
    label: ClassVar[str] = ""  # NEW: shown to the payer; falls back to name
    confirmation: ClassVar[ConfirmationMode] = ConfirmationMode.PROVIDER  # NEW
    pending_horizon: ClassVar[timedelta]
    not_found_grace: ClassVar[timedelta]

    # ... list_options, initiate, fetch_status, parse_callback unchanged ...

    def attestation_methods(self) -> list[AttestationMethod]:  # NEW, not abstract
        """Collection methods staff may record; empty for PROVIDER providers."""
        return []

    def attest(self, attestation: Attestation) -> ProviderStatus:  # NEW, not abstract
        """Validate an attestation and return the status to apply.

        Raises ProviderPermanentError(code, message, field=<Attestation field
        or "details.<key>">) when the record is not acceptable.
        """
        raise ProviderPermanentError("ATTESTATION_NOT_SUPPORTED")
```

Rules added to 0017 #9.2:

10. **`attest` is pure.** It validates and maps; it stores nothing, calls no
    network, and never decides whether the payment is still open, who may
    record it, or whether the receipt number was used before — `apps.payments`
    does, under a lock.
11. **An `ATTESTED` provider's `fetch_status` never returns `SUCCESS`.** Money is
    only ever credited through an attestation. A `SUCCESS` from `fetch_status`
    of an `ATTESTED` provider is ignored and logged at error
    (`PAYMENT_ATTESTED_PROVIDER_SUCCESS`).
12. **An `ATTESTED` provider overrides both `attest` and
    `attestation_methods`**, and returns at least one method (system check
    `payments.E010`).
13. **`parse_callback` of an `ATTESTED` provider** raises
    `ProviderCallbackMalformed`: there is no callback, and the generic
    endpoint must never credit through one.

### 4.2 Several providers for new payments

Today `PAYMENT_DEFAULT_PROVIDER` is the only provider new payments can use.
This spec adds:

| Setting | Default | Notes |
| --- | --- | --- |
| `PAYMENT_SELECTABLE_PROVIDERS` | `[]` | ordered names a payer may choose for a **new** payment; empty means "the default only". The environment-driven settings register every name in it, as they do `PAYMENT_REGISTERED_PROVIDERS` |

```text
registry.selectable() -> list[PaymentProvider]
    names = PAYMENT_SELECTABLE_PROVIDERS or [PAYMENT_DEFAULT_PROVIDER]  (empty entries dropped)
registry.get_for_new_payment(name: str | None) -> PaymentProvider | None
    name empty      -> get_default()
    name selectable -> get(name)
    otherwise       -> BusinessError(PROVIDER_NOT_AVAILABLE, field="provider")   # E06023
```

- Create-payment and create-batch bodies accept an optional `provider`. It is
  stored on every row as `metadata["requested_provider"]` when the rows are
  created, so an idempotent replay with a **different** `provider` is `409
  E06009` and a replay with the same one rebuilds the same action.
- `get_for_new_payment` is used **only** to initiate. Callback, poll, cancel
  and attestation keep routing by `Payment.provider` (0017 #9.3), so removing a
  provider from the selectable list never strands its in-flight payments.
- New system checks: every selectable name is a key of `PAYMENT_PROVIDERS`
  (`payments.E008`); when the list is non-empty, it contains
  `PAYMENT_DEFAULT_PROVIDER` (`payments.E009`).
- `mark_pending` refuses a `provider_payment_id` already held by another payment
  group of the same provider (a different `batch_id`, or a different single
  payment): the new payment fails with `failure_code = PROVIDER_ID_COLLISION`,
  `PROVIDER_ID_COLLISION` is logged at error, and the client gets `503 E06015`
  and retries with a new `client_request_id`. This guards every provider whose
  id is derived from a shortened reference.

`GET /api/v1/payments/providers/options/` keeps its 0017 #12.4 shape (the
default provider). A new endpoint lists everything the payer can choose
(#9.1.1).

### 4.3 `PaymentAttestation` model

One row per recorded collection. It is the permanent, generic record of "a
person says this money was received", and it is what makes receipt numbers
unique in the database rather than in application code.

| Field | Type | Notes |
| --- | --- | --- |
| `provider` | `CharField(32)` | the payment's provider |
| `provider_payment_id` | `CharField(128)` | the request reference; identifies the payment group |
| `receipt_number` | `CharField(64)` | normalised: trimmed, upper-cased |
| `amount` | `DecimalField(18, 2)` | `> 0`; what staff recorded |
| `currency` | `CharField(3)` | |
| `method` | `CharField(32)` | the `AttestationMethod.code` |
| `details` | `JSONField(default=dict)` | instrument fields, as validated by the provider |
| `collected_at` | `DateTimeField` | when the money was handed over, per staff |
| `remarks` | `TextField(blank=True)` | |
| `outcome` | `CharField(16, choices=AttestationOutcome)` | `CREDITED` or `FLAGGED` (#8.5) |

- Inherits `BaseModel`; `created_by` is the person who recorded it.
- `UniqueConstraint(provider, receipt_number)` — a receipt can be used once.
- `UniqueConstraint(provider, provider_payment_id)` — a request is attested once.
- `CheckConstraint(amount > 0)`.
- Immutable and undeletable, one row or in bulk, like `Payment` (0017 #10);
  registered read-only in the admin and tracked by history (0004).
- Selector `attestation_for(payment)` reads it by
  `(payment.provider, payment.provider_payment_id)`; no foreign key, the same
  way batches are grouped.

### 4.4 `PaymentService.record_collection`

```text
PaymentService.record_collection(*, provider, provider_payment_id, amount, method,
                                 receipt_number, collected_at, details, remarks,
                                 late=False, actor) -> CollectionResult
```

```text
adapter = registry.get(provider)                       ProviderNotConfigured  -> 404 E00105
adapter.confirmation != ATTESTED                       -> 404 E00105
receipt_number = normalise(receipt_number)
BEGIN
  group = select_for_update(payments with (provider, provider_payment_id)) ordered by pk
  group empty, or spans more than one batch/single payment       -> 404 E00105 / 409 E00108
  existing = PaymentAttestation for (provider, provider_payment_id)
  if existing:
      same receipt_number, amount, method      -> return existing  (200, replay)
      otherwise                                -> 409 E06025 COLLECTION_NOT_OPEN
  any payment.created_by == actor              -> 403 E06027 COLLECTOR_IS_PAYER
  receipt_number used by another attestation   -> 409 E06026 RECEIPT_NUMBER_USED (field receipt_number)
  open   = all payments INITIATED/PENDING
  closed = any payment FAILED/CANCELLED
  not open and not (closed and late)           -> 409 E06025 COLLECTION_NOT_OPEN
  status = adapter.attest(Attestation(expected_amount=sum(amount), initiated_at=min(...), ...))
           ProviderPermanentError(field=f)     -> 400 E06024 COLLECTION_DETAILS_INVALID (field f)
           ProviderPermanentError, no field    -> 422 E06028 COLLECTION_REJECTED
  status.outcome != SUCCESS                    -> 422 E06028 (provider bug; logged at error)
  create PaymentAttestation(outcome=CREDITED if open else FLAGGED, created_by=actor)
           IntegrityError on receipt           -> 409 E06026   (concurrent use of the same receipt)
  apply_provider_status(group, status, actor=actor)            [0017 #9.5]
      open   -> confirm_payment: SUCCESS, items PAID, provider_reference = receipt
      closed -> no credit; needs_reconciliation; PAYMENT_LATE_SUCCESS
COMMIT
on_commit: notify_payment_completed per payment (open case only)            [0017 #14]
```

- Everything runs in one transaction: an attestation row never exists without
  its credit or flag, and a credit never exists without its attestation.
- Lock order is payments, then demands, then items — the existing order of
  0017 — so it cannot deadlock against `create_payment`, `confirm_payment` or
  `cancel_payment`.
- `apply_provider_status` and `confirm_payment` gain an optional `actor`, so
  `Payment.updated_by` and the history record name the person who recorded
  the collection, not the system.
- The amount check of 0017 #9.5 still applies to the status the provider
  returns; the provider has already refused any other amount (#8.2), so a
  mismatch here is a provider bug and is flagged, not credited.
- Replay is keyed on the request reference plus receipt number, so a counter
  screen that retries after a timeout gets `200` with the same result, never a
  second credit and never a confusing error.

### 4.5 Cancelling an attested payment

`request_cancellation` (0017 #9.8) calls `fetch_status` for a `PENDING` payment
and refuses while the provider may still complete it. For an `ATTESTED`
provider there is nobody outside Dristi who can complete it: completion goes
through `record_collection`, which takes the same row locks. So:

- For `confirmation == ATTESTED`, `request_cancellation` skips `fetch_status`
  and cancels under the lock. Whichever of cancel and record takes the lock
  first wins; the other sees a terminal payment (`409 E06011` for cancel,
  `409 E06025` for record).
- The payer (the payment's creator, as today) may cancel, to switch to paying
  online.
- Staff holding `payments.cancel_payment_collection` may cancel any open
  attested request with a reason, through the collection API (#9.2) or the
  admin (#10). The creator check of 0017 #13 does not apply to them.
- `failure_code = PAYMENT_CANCELLED` and the reason go to `failure_message`, as
  for any cancellation.

### 4.6 New error codes

Domain `06`, next free numbers after `E06022`:

| Code | Name | Status | Raised when |
| --- | --- | --- | --- |
| `E06023` | `PROVIDER_NOT_AVAILABLE` | 400 | `provider` is not in the selectable list (#4.2); `field = provider` |
| `E06024` | `COLLECTION_DETAILS_INVALID` | 400 | the provider rejected a recorded value; `field` = `amount`, `method`, `receipt_number`, `collected_at` or `details.<key>` |
| `E06025` | `COLLECTION_NOT_OPEN` | 409 | the request is already paid, failed, cancelled or expired, or was already recorded with a different receipt |
| `E06026` | `RECEIPT_NUMBER_USED` | 409 | the receipt number was already recorded against another request; `field = receipt_number` |
| `E06027` | `COLLECTOR_IS_PAYER` | 403 | the person recording the collection created the payment |
| `E06028` | `COLLECTION_REJECTED` | 422 | the provider refused the record for a reason not tied to one field |

Released codes never change meaning (0000 #9.2). A request for a provider that
is not `ATTESTED`, or a reference that matches nothing, is `404 E00105`, so the
API does not reveal whether a gateway reference exists. Missing permission is
the common `403 E00104`.

### 4.7 Permissions

New `Payment.Meta.permissions`, alongside the three of 0017:

| Codename | Allows |
| --- | --- |
| `view_payment_collection` | look up and list attested payment requests and the collection register (#9.2, #9.3) |
| `record_payment_collection` | record that the money was collected (#9.2, #10) |
| `record_late_payment_collection` | record money taken against a request that is no longer open (#8.5) |
| `cancel_payment_collection` | cancel an open attested request on the payer's behalf (#4.5) |

- The staff endpoints use `IsAuthenticatedAndRegistered` plus a
  `HasPaymentPermission("<codename>")` check. They are **not** case-scoped:
  court staff are not case participants (0017 #13). Every lookup is restricted
  to providers whose `confirmation` is `ATTESTED`.
- `record_payment_collection` implies nothing else; a deployment gives it to the
  counter clerks through a Django group (for example `FEE_COLLECTOR`).
- Separation of duties: nobody records a collection on a payment they created
  (`E06027`), whatever permissions they hold.

### 4.8 Payer-facing additions

- `PaymentSerializer` gains a read-only, nullable `attestation`:
  `{receipt_number, method, collected_at}`. It never exposes who recorded it.
- `provider_action` gains `details` (#4.1); clients ignore it for
  `REDIRECT_FORM`.
- New `GET /api/v1/payments/payments/{id}/action/` returns the rebuilt
  `provider_action` of a `PENDING` payment (0017 #9.4 replay, without the
  `client_request_id`), so a payer can come back to their instructions days
  later. Creator only (it can carry payer details); anyone else on the case
  gets `403 E06017`; a payment that is not `PENDING` gets `409 E06025`.

### 4.9 Amendment summary

| File | Change |
| --- | --- |
| `providers/base.py` | `ConfirmationMode`, `ActionKind.SHOW_INSTRUCTIONS`, `ActionDetail`, `ProviderAction.details`, `AttestationField`, `AttestationMethod`, `Attestation`, `label`, `confirmation`, `attestation_methods()`, `attest()` |
| `providers/registry.py` | `selectable()`, `get_for_new_payment()`, `attested_names()` |
| `models.py` + migration | `PaymentAttestation`, `AttestationOutcome`, four permissions |
| `services/payments.py` | `provider` on create, `record_collection`, `actor` through `apply_provider_status` / `confirm_payment`, cancel rule (#4.5), id-collision guard |
| `services/polling.py` | rule 11: ignore `SUCCESS` from an `ATTESTED` provider's `fetch_status` |
| `serializers.py`, `views.py`, `urls.py` | #9 endpoints; `provider` on create; `details`; `attestation` |
| `admin.py` | #10 |
| `errors.py` | #4.6 |
| `checks.py` | `payments.E008`–`E010` |
| `conf.py` | `selectable_providers()` |

---

## 5. Initiation

### 5.1 What `initiate` does

`initiate` makes **no network call** and touches no state. It validates the
request, derives the reference and returns instructions:

```text
config.enabled is False                          -> ProviderPermanentError(OFFLINE_DISABLED)
request.currency != "INR"                        -> ProviderPermanentError(OFFLINE_UNSUPPORTED_CURRENCY)
request.amount <= 0 or != sum(lines)             -> ProviderPermanentError(OFFLINE_AMOUNT_INCONSISTENT)
OFFLINE_PAYMENT_MAX_AMOUNT set and amount > it   -> ProviderPermanentError(OFFLINE_AMOUNT_TOO_LARGE)
a line's charge_type not allowed (#13.2)         -> ProviderPermanentError(OFFLINE_CHARGE_NOT_ALLOWED)
options["counter"] unknown                       -> ProviderPermanentError(OFFLINE_INVALID_COUNTER, field="counter")
counters configured, none chosen, no default     -> ProviderPermanentError(OFFLINE_COUNTER_REQUIRED, field="counter")
-> ProviderInitiation(provider_payment_id=reference, action=SHOW_INSTRUCTIONS, metadata)
```

`apps.payments` maps these exactly as for e-GRAS (0017 #12.5): a `field` error
is `400 E06020` on `provider_options.counter`, any other permanent error is
`422 E06014`, and the payment is `FAILED` with the addon's code.

### 5.2 Request reference (`provider_payment_id`)

The payer reads it aloud or shows it on a phone at a counter, and staff type it.
It must be short, unambiguous and self-checking:

```text
{PREFIX}-{YYMMDD}-{AAAAA}-{BBBBB}-{C}
OFL-261111-7K3QF-9XM2H-V

PREFIX   OFFLINE_PAYMENT_REFERENCE_PREFIX, 2–4 upper-case letters, default "OFL"
YYMMDD   date of request.initiated_at in IST
AAAAA    the low 50 bits of request.reference (batch id, or payment id; both
BBBBB      uuid4, whose low 62 bits are random), in Crockford base32
           (0-9, A-Z without I, L, O, U)
C        Crockford check symbol (mod 37) of int(YYMMDD) * 2**50 + body
```

- **Deterministic.** Built only from `reference` and `initiated_at`, so a replay
  yields the same reference (0017 #9.2 rule 2). Configuration changes never
  alter it, except the prefix; a prefix change is a deploy-time decision and
  replays of older requests return `409 E06016`, which is logged.
- **New per attempt.** A retry is a new `Payment` with a new `reference`
  (0017 #4).
- **Unique.** 50 random bits per day: at 10,000 requests a day the chance of
  any two colliding is about 4 × 10⁻⁸. The `mark_pending` guard (#4.2) turns a
  collision into a retryable failure rather than a merged request.
- **Self-checking.** The check symbol catches every single-character typo and
  every swap of two adjacent characters within the date or the body (37 is
  prime and divides none of the resulting differences), so a mistyped reference is reported as
  malformed rather than "not found".
- **Normalised on input** by `reference.normalise()`: upper-cased, spaces and
  dashes removed and re-inserted after the configured prefix; in the body and
  check symbol only, `I`/`L` → `1` and `O` → `0` (the prefix is matched as
  configured, so `OFL` is never read as `0F1`). `ofl 261111 7k3qf 9xm2h v` and
  `OFL2611117K3QF9XM2HV` both resolve.
- The date also drives expiry (#6); no other state is needed.

### 5.3 Counters

`OFFLINE_PAYMENT_COUNTERS` is an optional JSON list of where money is accepted:

```json
[
  {"code": "EKM-CJM", "label": "CJM Court, Ernakulam — Fee counter",
   "address": "Ground floor, District Court Complex, Ernakulam 682011",
   "hours": "Mon–Fri 10:30–16:00"}
]
```

- `list_options()` returns them as `PaymentOption(code, label, group="COUNTER")`
  for the payer to pick; with one counter, or `OFFLINE_PAYMENT_DEFAULT_COUNTER`
  set, the UI may skip the picker.
- With no counters configured, `list_options()` is empty and the instructions
  carry only `OFFLINE_PAYMENT_INSTRUCTIONS`.
- The chosen counter is informational: staff at any counter may record any
  request. Restricting recording to the chosen counter is #21 Q-4.

### 5.4 Instructions (`ProviderAction`)

```python
ProviderAction(
    kind=ActionKind.SHOW_INSTRUCTIONS,
    details=(
        ActionDetail("reference", "Payment reference", "OFL-261111-7K3QF-9XM2H-V"),
        ActionDetail("amount", "Amount to pay", "₹ 707.50"),
        ActionDetail("valid_until", "Pay before", "18 Nov 2026, 11:59 PM IST"),
        ActionDetail("counter", "Where to pay", "CJM Court, Ernakulam — Fee counter"),
        ActionDetail("counter_address", "Address", "Ground floor, District Court Complex, ..."),
        ActionDetail("counter_hours", "Counter hours", "Mon–Fri 10:30–16:00"),
        ActionDetail("methods", "Accepted", "Cash, Demand draft"),
        ActionDetail("payable_to", "Demand draft in favour of", "Chief Judicial Magistrate, Ernakulam"),
        ActionDetail("payments", "Payment numbers", "PAY-2026-000456"),
        ActionDetail("instructions", "Instructions", "Quote the payment reference ..."),
    ),
)
```

- Keys are stable and documented here; a client may special-case `reference`
  (copy, QR) and `amount`, and renders the rest as label/value without
  interpreting them. A detail with an empty value is omitted.
- `payable_to` appears only when `DEMAND_DRAFT` is an accepted method and
  `OFFLINE_PAYMENT_PAYABLE_TO` is set.
- `amount` is formatted from `request.amount` with two decimals; no rounding.
- `metadata` stored on the payment is `{"valid_until", "counter"}` — nothing
  personal (0017 #9.2 rule 8).

---

## 6. Status and expiry

### 6.1 Validity

```text
issued_on   = the YYMMDD date in the reference (IST)
valid_until = issued_on + OFFLINE_PAYMENT_VALIDITY_DAYS, at 23:59:59.999999 IST
expires_at  = valid_until + OFFLINE_PAYMENT_RECORDING_GRACE
```

| Example (validity 7 days, grace 24 h) | |
| --- | --- |
| created 11 Nov 2026 09:00 IST | `issued_on` 11 Nov |
| payer may pay until | 18 Nov 23:59:59 IST (`valid_until`) |
| staff may record a payment collected by then until | 19 Nov 23:59:59 IST (`expires_at`) |
| `fetch_status` reports `FAILED` from | 20 Nov 00:00 IST |

- The validity is read from configuration at check time, not frozen into the
  reference: lengthening it extends requests already issued; shortening it can
  expire them early. Both are deliberate operator decisions (#17).
- The grace exists because counters often record the day's collections after
  closing. Money must have been **collected** by `valid_until` (#8.2); it may be
  **recorded** until `expires_at`.

### 6.2 `fetch_status`

```text
parse(provider_payment_id) fails      -> ProviderStatus(NOT_FOUND)   (not one of ours)
now <= expires_at                     -> ProviderStatus(PENDING)
now >  expires_at                     -> ProviderStatus(FAILED, failure_code=OFFLINE_REQUEST_EXPIRED,
                                           failure_message="This payment request expired before payment was recorded.")
```

- It is pure, deterministic and side-effect free (0017 #9.2 rule 4). It never
  returns `SUCCESS` (#4.1 rule 11): only an attestation credits.
- The 0017 poller applies the `FAILED` through `apply_provider_status`; the
  items become payable again. The poller runs at most
  `PAYMENT_STATUS_POLL_MAX_INTERVAL_SECONDS` (6 h) apart, so a request is failed
  within six hours of `expires_at`.
- Until the poller has run, `record_collection` still sees an open payment; the
  provider's `attest` refuses anything collected after `valid_until`, so the
  outcome is the same either way.

### 6.3 Timing attributes

| Provider attribute | Value | Why |
| --- | --- | --- |
| `pending_horizon` | validity + grace + 1 day | the poller must reach `FAILED` before it would flag `PAYMENT_STUCK` (0017 #9.7) |
| `not_found_grace` | same as `pending_horizon` | `fetch_status` returns `NOT_FOUND` only for a reference that is not ours; that must never fail a real request early |

---

## 7. Callback

There is none. Money is never reported by a remote system, so:

- `parse_callback` always raises
  `ProviderCallbackMalformed(OFFLINE_NO_CALLBACK)`.
- `POST /api/v1/payments/providers/offline/_callback` therefore always
  redirects with `status=UNKNOWN` and writes nothing (0017 #9.6). A forged
  "success" for a known reference cannot credit anything.
- No `UURL`, return URL or callback setting exists for this provider.

---

## 8. Recording a collection

### 8.1 Methods

`attestation_methods()` returns the methods enabled by
`OFFLINE_PAYMENT_METHODS`, from this fixed set:

| Code | Label | Fields (`details`) | Final when handed over |
| --- | --- | --- | --- |
| `CASH` | Cash | — | yes |
| `DEMAND_DRAFT` | Demand draft | `instrument_number` (digits, 6), `instrument_date` (date), `bank_name` (text, ≤ 100), `branch` (text, ≤ 100, optional) | yes, once accepted |
| `POS` | Card / UPI at the counter | `transaction_reference` (text, 6–32, `[A-Za-z0-9]`), `terminal_id` (text, ≤ 16, optional) | yes |

- Cheques are not offered: a cheque can bounce after the case has moved on,
  and there is no reversal (Non-goals). Adding a method is a code change in
  `methods.py`, because its validation is code; enabling one is a setting.
- The admin form and the counter screen render fields from
  `attestation_methods()` (#9.2), so they need no change when a method is
  added.

### 8.2 Validation (`attestation.py`)

`attest` checks, in this order, and raises `ProviderPermanentError` with the
`field` shown; `apps.payments` returns `400 E06024` on that field:

| # | Rule | Failure code | `field` |
| --- | --- | --- | --- |
| 1 | `provider_payment_id` parses as one of our references | `OFFLINE_REFERENCE_MALFORMED` | — (→ `422 E06028`) |
| 2 | `currency` is `INR` | `OFFLINE_UNSUPPORTED_CURRENCY` | — (→ `422 E06028`) |
| 3 | `method` is enabled | `OFFLINE_METHOD_NOT_ALLOWED` | `method` |
| 4 | `amount` has at most two decimals and equals `expected_amount` exactly | `OFFLINE_AMOUNT_MISMATCH` | `amount` |
| 5 | `CASH` and `OFFLINE_PAYMENT_CASH_MAX_AMOUNT` set: `amount` ≤ it | `OFFLINE_CASH_LIMIT_EXCEEDED` | `amount` |
| 6 | `receipt_number` matches `OFFLINE_PAYMENT_RECEIPT_PATTERN` after trimming | `OFFLINE_RECEIPT_INVALID` | `receipt_number` |
| 7 | `collected_at` is timezone-aware | `OFFLINE_COLLECTED_AT_INVALID` | `collected_at` |
| 8 | `collected_at` ≥ `initiated_at` | `OFFLINE_COLLECTED_BEFORE_REQUEST` | `collected_at` |
| 9 | `collected_at` ≤ now + 5 minutes (clock skew) | `OFFLINE_COLLECTED_IN_FUTURE` | `collected_at` |
| 10 | `collected_at` ≤ `valid_until` | `OFFLINE_COLLECTED_AFTER_EXPIRY` | `collected_at` |
| 11 | now ≤ `expires_at`, unless `apps.payments` is recording late (#8.5) | `OFFLINE_REQUEST_EXPIRED` | — (→ `422 E06028`) |
| 12 | every required field of the method is present; no unknown keys | `OFFLINE_DETAIL_REQUIRED` / `OFFLINE_DETAIL_UNKNOWN` | `details.<key>` |
| 13 | each field matches its kind and length (#8.1) | `OFFLINE_DETAIL_INVALID` | `details.<key>` |
| 14 | `DEMAND_DRAFT`: `instrument_date` ≤ the IST date of `collected_at`, and not more than `OFFLINE_PAYMENT_DD_MAX_AGE_DAYS` before it | `OFFLINE_DD_DATE_INVALID` / `OFFLINE_DD_STALE` | `details.instrument_date` |
| 15 | `remarks` ≤ 500 characters | `OFFLINE_REMARKS_TOO_LONG` | `remarks` |

- **No over- or under-collection.** Rule 4 refuses any other amount, including
  `707.5` vs `707.50` (equal as decimals, accepted) and `707.49` (refused).
  Staff cannot record a part payment or a tip; change is given at the counter.
- **Exactly the amount due, for the whole request.** A batch request is one
  amount for every payment in it (0017 #5); recording a part of a batch is not
  possible.
- The first failing rule is reported; one error per response, as elsewhere in
  `apps.payments`.

On success, `attest` returns:

```python
ProviderStatus(
    provider_payment_id=attestation.provider_payment_id,
    outcome=ProviderOutcome.SUCCESS,
    amount=attestation.amount,
    provider_reference=normalised_receipt_number,
    paid_at=attestation.collected_at,
    failure_code="",
    failure_message="",
    metadata={"method": "DEMAND_DRAFT", "collected_at": "...", "instrument_number": "123456",
              "instrument_date": "2026-11-10", "bank_name": "State Bank of India"},
)
```

`metadata` carries instrument data needed on a receipt, never payer contact
data.

### 8.3 Idempotency and concurrency

Owned by `apps.payments` (#4.4); listed here because they are the edge cases a
counter meets every day:

| Situation | Result |
| --- | --- |
| Same request, same receipt, amount and method recorded twice (double click, retry after timeout) | second call `200`, same attestation, credited once |
| Same request recorded again with a different receipt | `409 E06025` |
| Two clerks record the same request at once | one wins; the other gets `200` replay if their record is identical, else `409 E06025` |
| Two clerks use the same receipt number on two requests at once | the unique constraint lets one through; the other gets `409 E06026` |
| Payer cancels while a clerk records | whichever locks first wins; the other gets `409` (`E06011` or `E06025`) |
| Poller expires the request while a clerk records | as above; if the record loses, the clerk sees `409 E06025` and may record late (#8.5) |

### 8.4 What the payer sees

- The payment moves `PENDING → SUCCESS`; the demand items become `PAID`; the
  raising module receives `payment_completed` and moves the case on — exactly
  as for e-GRAS.
- `GET /api/v1/payments/payments/{id}/` shows
  `provider_reference = receipt_number` and the `attestation` block (#4.8).

### 8.5 Late recording

Sometimes money is taken against a request that is no longer open: it expired
during the day, the payer cancelled it online after paying, or the poller ran
first. The money is real and must not vanish.

- `record_collection(..., late=True)` — needs
  `payments.record_late_payment_collection` — accepts a `FAILED` or
  `CANCELLED` request (rule 11 of #8.2 is skipped; rules 8–10 still apply, so
  `collected_at` must fall within the original validity window).
- It stores the `PaymentAttestation` with `outcome = FLAGGED`, applies the
  status through `apply_provider_status`, which — per 0017 #9.5 — **does not
  credit**, sets `needs_reconciliation` and logs `PAYMENT_LATE_SUCCESS`.
- An operator then resolves it outside the system (refund the payer, or raise
  a fresh demand) and clears the flag (0017 implementation notes). Crediting a
  late collection automatically is #21 Q-3.
- Without `late`, a closed request is `409 E06025`.
- A `SUCCESS` request can never be recorded late; it is paid.

---

## 9. APIs

All under `/api/v1/payments/`, `drf-spectacular` annotated, `payments` tag,
`meta` envelope and the standard error shape (0000 #8, #9). Amounts are
strings (0017 #16).

### 9.1 Payer side

| Method | Path | Purpose | Change |
| --- | --- | --- | --- |
| GET | `/api/v1/payments/providers/` | providers the payer can choose, with their options | **new** |
| POST | `/api/v1/payments/demands/{id}/payments/` | create a payment; now accepts `provider` | amended |
| POST | `/api/v1/payments/batches/` | pay across demands; now accepts `provider` | amended |
| GET | `/api/v1/payments/payments/{id}/` | status; now includes `attestation` | amended |
| GET | `/api/v1/payments/payments/{id}/action/` | rebuild the instructions of a pending payment | **new** |
| POST | `/api/v1/payments/payments/{id}/cancel/` | cancel; immediate for offline (#4.5) | behaviour |

#### 9.1.1 List providers

```json
GET /api/v1/payments/providers/

200
{
  "default": "egras",
  "providers": [
    {
      "name": "egras",
      "label": "Pay online (net banking / UPI)",
      "confirmation": "PROVIDER",
      "options": [
        { "code": "SBI", "label": "State Bank of India", "group": "NET_BANKING" },
        { "code": "UPI-01", "label": "UPI", "group": "UPI" }
      ]
    },
    {
      "name": "offline",
      "label": "Pay at the court counter",
      "confirmation": "ATTESTED",
      "options": [
        { "code": "EKM-CJM", "label": "CJM Court, Ernakulam — Fee counter", "group": "COUNTER" }
      ]
    }
  ],
  "meta": { "...": "standard envelope" }
}
```

- `IsAuthenticatedAndRegistered`; not case-scoped (no case data); cached per
  provider for five minutes like the options endpoint.
- Order is `PAYMENT_SELECTABLE_PROVIDERS`. A provider whose
  `list_options()` raises is left out and logged, rather than failing the whole
  list; if the default cannot be loaded, `503 E06015`.
- `confirmation` lets a client word the next step ("you will be redirected" vs
  "pay at the counter") without knowing provider names.

#### 9.1.2 Create an offline payment

```json
POST /api/v1/payments/demands/{id}/payments/
{
  "client_request_id": "case-123-filing-attempt-2",
  "payment_mode": "OFFLINE",
  "demand_item_ids": ["item-1", "item-2", "item-3"],
  "provider": "offline",
  "provider_options": { "counter": "EKM-CJM" }
}

201
{
  "id": "payment-uuid",
  "payment_number": "PAY-2026-000456",
  "demand_id": "demand-uuid",
  "amount": "707.50",
  "currency": "INR",
  "status": "PENDING",
  "provider": "offline",
  "provider_payment_id": "OFL-261111-7K3QF-9XM2H-V",
  "provider_reference": "",
  "attestation": null,
  "items": [ { "demand_item_id": "item-1", "amount": "12.50" }, "..." ],
  "provider_action": {
    "kind": "SHOW_INSTRUCTIONS",
    "url": "",
    "method": "",
    "form_fields": {},
    "details": [
      { "key": "reference", "label": "Payment reference", "value": "OFL-261111-7K3QF-9XM2H-V" },
      { "key": "amount", "label": "Amount to pay", "value": "₹ 707.50" },
      { "key": "valid_until", "label": "Pay before", "value": "18 Nov 2026, 11:59 PM IST" },
      { "key": "counter", "label": "Where to pay", "value": "CJM Court, Ernakulam — Fee counter" }
    ]
  },
  "meta": { "...": "standard envelope" }
}
```

Errors, in addition to 0017 #12.5:

| Code | When |
| --- | --- |
| `400 E06023` on `provider` | `provider` not selectable |
| `400 E06020` on `provider_options.counter` | unknown counter, or one required and missing |
| `422 E06014` | offline disabled, amount over the cap, charge type not allowed |
| `409 E06005` | an item already has an open payment — online **or** offline |
| `409 E06009` | `client_request_id` replayed with a different `provider` or items |

#### 9.1.3 Client behaviour

- For `SHOW_INSTRUCTIONS`, render `details` and offer "Cancel and pay online"
  (the cancel endpoint). Do not poll aggressively: an offline payment completes
  in hours or days. Poll on screen focus, or every few minutes while open.
- For `REDIRECT_FORM`, unchanged (0017 #12.2).
- To show instructions again later, call `GET /payments/{id}/action/`.
- A pay-task card for a `PENDING` offline payment shows the reference and
  `valid_until` from `provider_action.details`.

### 9.2 Staff side (collection desk)

Not case-scoped; permission-scoped (#4.7). `{provider}` must be an `ATTESTED`
provider, else `404 E00105`. `{reference}` is normalised by the provider
before lookup (#5.2); a reference that fails its check symbol is `400 E00001`
on `reference`.

| Method | Path | Permission | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/payments/collections/methods/?provider=offline` | `view_payment_collection` | methods and fields to render the form |
| GET | `/api/v1/payments/collections/?provider=&status=&search=&initiated_from=&initiated_to=` | `view_payment_collection` | list requests (paginated, `-initiated_at`) |
| GET | `/api/v1/payments/collections/{provider}/{reference}/` | `view_payment_collection` | one request: amount due, items, case, payer, validity, attestation |
| POST | `/api/v1/payments/collections/{provider}/{reference}/confirm/` | `record_payment_collection` (+ `record_late_payment_collection` with `late`) | record the collection |
| POST | `/api/v1/payments/collections/{provider}/{reference}/cancel/` | `cancel_payment_collection` | cancel an open request, with a reason |
| GET | `/api/v1/payments/collections/register/?provider=&collected_on=&recorded_by=&method=` | `view_payment_collection` | attestations, for the day-end tally (#9.3) |

#### 9.2.1 Look up a request

```json
GET /api/v1/payments/collections/offline/ofl2611117k3qf9xm2hv/

200
{
  "provider": "offline",
  "reference": "OFL-261111-7K3QF-9XM2H-V",
  "status": "PENDING",
  "amount": "707.50",
  "currency": "INR",
  "initiated_at": "2026-11-11T09:00:12+05:30",
  "valid_until": "2026-11-18T23:59:59+05:30",
  "expired": false,
  "batch_id": null,
  "payer": { "name": "Anjali Menon", "phone": "******3210" },
  "payments": [
    {
      "id": "payment-uuid",
      "payment_number": "PAY-2026-000456",
      "demand_number": "DMD-2026-000123",
      "case": { "id": "case-uuid", "filing_number": "F-KL-2026-000789" },
      "amount": "707.50",
      "status": "PENDING",
      "items": [
        { "demand_item_id": "item-1", "charge_type": "COURT_FEE", "description": "Court Fee", "amount": "12.50" }
      ]
    }
  ],
  "attestation": null,
  "meta": { "...": "standard envelope" }
}
```

- `status` is the group's status (every payment of a group shares it, 0017 #15).
- `valid_until` is read from `payment.metadata["provider"]["valid_until"]`,
  which every `ATTESTED` provider writes at initiation (a contract convention,
  documented on `ConfirmationMode.ATTESTED`); `expired` is
  `now > valid_until`. Both are `null` / `false` when the key is absent. The
  collection serializer never names the addon.
- The payer's phone is masked to the last four digits; email and address are
  not returned. Staff need to recognise the payer, not contact them.
- `filing_number` (or `case_number` once registered) comes from the cases
  selector, never a direct query of case tables.

#### 9.2.2 Record the collection

```json
POST /api/v1/payments/collections/offline/OFL-261111-7K3QF-9XM2H-V/confirm/
{
  "amount": "707.50",
  "method": "DEMAND_DRAFT",
  "receipt_number": "CJM/EKM/2026/004512",
  "collected_at": "2026-11-12T11:42:00+05:30",
  "details": {
    "instrument_number": "123456",
    "instrument_date": "2026-11-10",
    "bank_name": "State Bank of India",
    "branch": "MG Road, Kochi"
  },
  "remarks": "",
  "late": false
}

200
{
  "...": "the #9.2.1 body, now with status SUCCESS",
  "attestation": {
    "receipt_number": "CJM/EKM/2026/004512",
    "method": "DEMAND_DRAFT",
    "amount": "707.50",
    "collected_at": "2026-11-12T11:42:00+05:30",
    "details": { "instrument_number": "123456", "...": "..." },
    "remarks": "",
    "outcome": "CREDITED",
    "recorded_by": { "id": "user-uuid", "name": "Suresh K" },
    "recorded_at": "2026-11-12T11:43:05+05:30"
  }
}
```

- `200` both on the first record and on an identical replay (#8.3); the body is
  the same.
- `collected_at` defaults to now when omitted.
- Serializer checks shape only: decimal format (≤ 2 places, > 0), method and
  receipt are non-blank strings, `collected_at` is an ISO-8601 datetime with an
  offset, `details` is a flat string map. Business rules come from the service
  and the provider (#4.4, #8.2).

Errors declared on the endpoint with `error_responses(...)`:

| Code | When |
| --- | --- |
| `400 E06024` (`amount`, `method`, `receipt_number`, `collected_at`, `details.<key>`, `remarks`) | #8.2 |
| `403 E00104` | missing permission, or `late` without the late permission |
| `403 E06027` | the recorder created the payment |
| `404 E00105` | unknown provider, not `ATTESTED`, or no such reference |
| `409 E06025` | not open (and not late), or already recorded differently |
| `409 E06026` on `receipt_number` | receipt already used |
| `422 E06028` | the provider refused the record (expired, malformed reference) |

#### 9.2.3 Cancel a request

```json
POST /api/v1/payments/collections/offline/OFL-261111-7K3QF-9XM2H-V/cancel/
{ "reason": "Payer asked to pay online instead." }
```

`200` with the #9.2.1 body, `status = CANCELLED`. `reason` is required (1–255
characters). A request that is not open is `409 E06011`.

#### 9.2.4 List requests

`GET /api/v1/payments/collections/?provider=offline&status=PENDING&search=Anjali`

- One row per request (payment group), not per payment.
- `search` matches the normalised reference exactly, `payment_number`,
  `demand_number`, the case's filing or case number, and the payer name
  (case-insensitive contains). Searching by reference with a bad check symbol
  returns an empty page, not an error.
- `status` filters on the group status; default all.
- Project default page-number pagination; rows in the #9.2.1 shape without
  `items`.

### 9.3 Collection register

`GET /api/v1/payments/collections/register/?provider=offline&collected_on=2026-11-12`

Paginated `PaymentAttestation` rows with the reference, payment numbers,
amount, method, receipt number, `collected_at`, recorded by/at and `outcome`;
`collected_on` is an IST date. The response adds `totals` per method for the
filter, so a counter can tally its cash at day end:

```json
{ "count": 37, "next": null, "previous": null, "results": [ "..." ],
  "totals": [ { "method": "CASH", "count": 30, "amount": "4120.00" },
              { "method": "DEMAND_DRAFT", "count": 7, "amount": "6512.50" } ],
  "meta": { "...": "standard envelope" } }
```

Read-only; it changes nothing and is not a cash book (Non-goals).

---

## 10. Django admin (first release)

Until the counter screen exists, staff use the admin. Everything goes through
`PaymentService`, so the admin and the API cannot disagree.

- **List filter "Awaiting collection"** on `PaymentAdmin`: `PENDING` payments
  of `ATTESTED` providers. Search already covers `provider_payment_id`; the
  admin search normalises an offline-looking reference through the provider.
- **"Record collection" button** on the change page of an open payment of an
  `ATTESTED` provider, shown to holders of `record_payment_collection`. It opens
  a form (a custom admin view under `get_urls()`) that shows the whole group —
  amount due, payments, items, case, masked payer, `valid_until` — and fields
  built from `attestation_methods()`. Submitting calls `record_collection` and
  shows the business error, if any, against the right form field.
- **"Record late collection"** — the same form with `late=True`, shown for a
  `FAILED`/`CANCELLED` payment of an `ATTESTED` provider to holders of
  `record_late_payment_collection`.
- **"Cancel collection request"** admin action with a reason, for holders of
  `cancel_payment_collection`.
- **`PaymentAttestationAdmin`**: read-only list with filters `provider`,
  `method`, `outcome`, `created_by`, date hierarchy on `collected_at`; search by
  receipt number and reference.
- The existing "Confirm payment collected outside a provider" action (0017
  implementation notes) is unchanged: it is for `INITIATED` payments with no
  provider, and never applies to an offline request.

---

## 11. Provider surface

```python
# addon/offline_payment/provider.py
from apps.payments.providers.base import ConfirmationMode, PaymentProvider


class OfflinePaymentProvider(PaymentProvider):
    """Money handed over in person and recorded by court staff."""

    name = "offline"
    confirmation = ConfirmationMode.ATTESTED

    @property
    def label(self): ...  # OFFLINE_PAYMENT_LABEL

    @property
    def pending_horizon(self): ...  # validity + grace + 1 day, #6.3

    @property
    def not_found_grace(self): ...  # same, #6.3

    def list_options(self) -> list[PaymentOption]: ...  # counters, #5.3
    def initiate(self, request) -> ProviderInitiation: ...  # #5, no I/O, deterministic
    def fetch_status(self, *, provider_payment_id) -> ProviderStatus: ...  # #6.2, never SUCCESS
    def parse_callback(self, payload) -> ProviderCallback: ...  # #7, always malformed
    def attestation_methods(self) -> list[AttestationMethod]: ...  # #8.1
    def attest(self, attestation) -> ProviderStatus: ...  # #8.2, pure
```

Like e-GRAS, attributes depending on configuration are properties reading the
cached `OfflineConfig`.

---

## 12. Running alongside e-GRAS, and replacing it

### 12.1 Together

```python
PAYMENT_PROVIDERS = {
    "egras": "addon.egras_payment_gateway.provider.EGRASPaymentProvider",
    "offline": "addon.offline_payment.provider.OfflinePaymentProvider",
}
PAYMENT_DEFAULT_PROVIDER = "egras"
PAYMENT_SELECTABLE_PROVIDERS = ["egras", "offline"]
```

- Both are offered; the payer chooses per payment. A payer who sends no
  `provider` gets e-GRAS.
- One item can have only one open payment (0017 #6.3 rule 7), whichever
  provider it is on: an offline request blocks an online attempt on the same
  items until it is cancelled or expires, and vice versa.
- Different items of the same demand may be paid through different providers;
  a batch is always one provider.
- Neither addon knows of the other; nothing in `apps.payments` names either.

### 12.2 Offline only

`PAYMENT_DEFAULT_PROVIDER = "offline"` and no selectable list: every payment is
an offline request. Useful for a court before e-GRAS onboarding.

### 12.3 Stopping or removing offline payments

The generic procedure of 0017 #9.8 and 0022 #8:

```text
1. Remove "offline" from PAYMENT_SELECTABLE_PROVIDERS (and from the default).
   Keep it registered (PAYMENT_REGISTERED_PROVIDERS=offline).
   -> payers can no longer start offline payments; staff can still record open ones.
2. Wait until `manage.py payments_provider_usage offline` shows no PENDING payment
   — at most pending_horizon (validity + grace + 1 day).
3. Remove "offline" from PAYMENT_PROVIDERS / PAYMENT_REGISTERED_PROVIDERS, the
   INSTALLED_APPS entry and the OFFLINE_PAYMENT_* block; delete src/addon/offline_payment/.
```

Historic payments keep `provider="offline"`, their reference and receipt
number, and their `PaymentAttestation` rows; they never need the addon again.
`OFFLINE_PAYMENT_ENABLED = False` is the emergency variant of step 1: new
requests are refused while recording keeps working for those in flight.

A replacement attested channel (for example a different counter system with
its own reference format) is a new addon with `confirmation = ATTESTED`; it
reuses every staff API, the admin form and `PaymentAttestation` unchanged.

---

## 13. Configuration

### 13.1 Namespace

Addon settings use the `OFFLINE_PAYMENT_` prefix in one block in
`config/settings/base.py`, removed together with the `INSTALLED_APPS` and
`PAYMENT_PROVIDERS` entries. `production.py` adds `"offline"` to
`_AVAILABLE_PAYMENT_PROVIDERS`; `local.py` registers it when it is the default,
registered or selectable, as it does for e-GRAS.

### 13.2 Settings

```python
# config/settings/base.py — offline payment provider addon (addon.offline_payment, spec 0032)
# Remove this block, the INSTALLED_APPS entry, and PAYMENT_PROVIDERS["offline"]
# to remove the integration.
OFFLINE_PAYMENT_ENABLED = env.bool("OFFLINE_PAYMENT_ENABLED", default=True)
OFFLINE_PAYMENT_LABEL = env("OFFLINE_PAYMENT_LABEL", default="Pay at the court counter")
OFFLINE_PAYMENT_VALIDITY_DAYS = env.int("OFFLINE_PAYMENT_VALIDITY_DAYS", default=7)
...
```

| Setting | Required | Default | Notes |
| --- | --- | --- | --- |
| `OFFLINE_PAYMENT_ENABLED` | no | `True` | kill switch for new requests; recording keeps working |
| `OFFLINE_PAYMENT_LABEL` | no | `Pay at the court counter` | shown in the provider list |
| `OFFLINE_PAYMENT_REFERENCE_PREFIX` | no | `OFL` | 2–4 upper-case letters |
| `OFFLINE_PAYMENT_VALIDITY_DAYS` | no | `7` | 1–90 |
| `OFFLINE_PAYMENT_RECORDING_GRACE_HOURS` | no | `24` | 0–168 |
| `OFFLINE_PAYMENT_METHODS` | no | `CASH,DEMAND_DRAFT` | subset of #8.1, at least one |
| `OFFLINE_PAYMENT_COUNTERS` | no | `[]` | JSON list of `{code, label, address, hours}` |
| `OFFLINE_PAYMENT_DEFAULT_COUNTER` | no | `""` | one of the counter codes |
| `OFFLINE_PAYMENT_INSTRUCTIONS` | no | `Quote the payment reference at the counter and keep the receipt.` | ≤ 500 characters |
| `OFFLINE_PAYMENT_PAYABLE_TO` | when `DEMAND_DRAFT` is enabled | `""` | in whose favour a DD is drawn |
| `OFFLINE_PAYMENT_MAX_AMOUNT` | no | `""` (no cap) | decimal; largest request offered offline |
| `OFFLINE_PAYMENT_CASH_MAX_AMOUNT` | no | `""` (no cap) | decimal; largest amount accepted in cash (e.g. `199999.00`, Income Tax Act s. 269ST) |
| `OFFLINE_PAYMENT_ALLOWED_CHARGE_TYPES` | no | `[]` (all) | `ChargeType` values offline may collect |
| `OFFLINE_PAYMENT_RECEIPT_PATTERN` | no | `^[A-Z0-9][A-Z0-9/-]{0,63}$` | applied to the upper-cased, trimmed receipt number |
| `OFFLINE_PAYMENT_DD_MAX_AGE_DAYS` | no | `90` | a DD older than this is stale |

`PAYMENT_SELECTABLE_PROVIDERS` (#4.2) belongs to 0017's block.

`resolve_config()` loads the values into a frozen `OfflineConfig` once and
caches it, cleared on `setting_changed`, as `EGRASConfig` does. There are no
credentials. Every setting is documented in `.env.example`,
`.env.prod.example` and `README.md`.

### 13.3 Startup validation

System checks registered in `AppConfig.ready()`, error level, only when
`"offline"` is in `PAYMENT_PROVIDERS`:

- `OFFLINE_PAYMENT_REFERENCE_PREFIX` is 2–4 upper-case letters
  (`offline_payment.E001`);
- validity 1–90 days, grace 0–168 hours (`E002`);
- `OFFLINE_PAYMENT_METHODS` is non-empty, every code supported, no duplicates
  (`E003`);
- `OFFLINE_PAYMENT_COUNTERS` parses, codes are unique and non-empty, labels
  non-empty; `OFFLINE_PAYMENT_DEFAULT_COUNTER`, if set, is one of them (`E004`);
- `OFFLINE_PAYMENT_PAYABLE_TO` is set when `DEMAND_DRAFT` is enabled (`E005`);
- both amount caps, if set, are positive decimals with ≤ 2 places (`E006`);
- every `OFFLINE_PAYMENT_ALLOWED_CHARGE_TYPES` value is a `ChargeType` (`E007`);
- `OFFLINE_PAYMENT_RECEIPT_PATTERN` compiles (`E008`);
- `OFFLINE_PAYMENT_DD_MAX_AGE_DAYS` ≥ 1 (`E009`);
- warning when `"offline"` is registered but neither the default nor
  selectable — it can then only finish requests already in flight (`W001`).

The generic checks of #4.2 / #4.1 (`payments.E008`–`E010`) run in
`apps.payments`.

---

## 14. Failure codes

Internal codes in `constants.py`, carried on `ProviderError.code` or
`ProviderStatus.failure_code`, stored on `Payment.failure_code` and logged.
They never appear in an API `errors` array; `apps.payments` maps the exception
to its own codes (0017 #12.5, #4.6).

| Failure code | Raised as | Returned by `apps.payments` |
| --- | --- | --- |
| `OFFLINE_DISABLED` | `ProviderPermanentError` | payment `FAILED`; `422 E06014` |
| `OFFLINE_UNSUPPORTED_CURRENCY` | `ProviderPermanentError` | `422 E06014` at initiation; `422 E06028` at recording |
| `OFFLINE_AMOUNT_INCONSISTENT` | `ProviderPermanentError` | `FAILED`; `422 E06014` |
| `OFFLINE_AMOUNT_TOO_LARGE` | `ProviderPermanentError` | `FAILED`; `422 E06014` |
| `OFFLINE_CHARGE_NOT_ALLOWED` | `ProviderPermanentError` | `FAILED`; `422 E06014` |
| `OFFLINE_INVALID_COUNTER` | `ProviderPermanentError(field="counter")` | `FAILED`; `400 E06020` on `provider_options.counter` |
| `OFFLINE_COUNTER_REQUIRED` | `ProviderPermanentError(field="counter")` | `FAILED`; `400 E06020` on `provider_options.counter` |
| `OFFLINE_NO_CALLBACK` | `ProviderCallbackMalformed` | nothing written; redirect `status=UNKNOWN` |
| `OFFLINE_REQUEST_EXPIRED` | `ProviderStatus(FAILED)` from `fetch_status`; `ProviderPermanentError` from `attest` | payment `FAILED` with this code; `422 E06028` at recording |
| `OFFLINE_REFERENCE_MALFORMED` | `ProviderPermanentError` | `422 E06028` |
| `OFFLINE_METHOD_NOT_ALLOWED` | `ProviderPermanentError(field="method")` | `400 E06024` |
| `OFFLINE_AMOUNT_MISMATCH` | `ProviderPermanentError(field="amount")` | `400 E06024` |
| `OFFLINE_CASH_LIMIT_EXCEEDED` | `ProviderPermanentError(field="amount")` | `400 E06024` |
| `OFFLINE_RECEIPT_INVALID` | `ProviderPermanentError(field="receipt_number")` | `400 E06024` |
| `OFFLINE_COLLECTED_AT_INVALID` | `ProviderPermanentError(field="collected_at")` | `400 E06024` |
| `OFFLINE_COLLECTED_BEFORE_REQUEST` | `ProviderPermanentError(field="collected_at")` | `400 E06024` |
| `OFFLINE_COLLECTED_IN_FUTURE` | `ProviderPermanentError(field="collected_at")` | `400 E06024` |
| `OFFLINE_COLLECTED_AFTER_EXPIRY` | `ProviderPermanentError(field="collected_at")` | `400 E06024` |
| `OFFLINE_DETAIL_REQUIRED` | `ProviderPermanentError(field="details.<key>")` | `400 E06024` |
| `OFFLINE_DETAIL_UNKNOWN` | `ProviderPermanentError(field="details.<key>")` | `400 E06024` |
| `OFFLINE_DETAIL_INVALID` | `ProviderPermanentError(field="details.<key>")` | `400 E06024` |
| `OFFLINE_DD_DATE_INVALID` | `ProviderPermanentError(field="details.instrument_date")` | `400 E06024` |
| `OFFLINE_DD_STALE` | `ProviderPermanentError(field="details.instrument_date")` | `400 E06024` |
| `OFFLINE_REMARKS_TOO_LONG` | `ProviderPermanentError(field="remarks")` | `400 E06024` |

---

## 15. Security

- **Only an authorised person credits.** No anonymous, payer or callback path
  can move an offline payment to `SUCCESS`. The callback always refuses (#7);
  `fetch_status` never reports success, and `apps.payments` ignores one if it
  did (#4.1 rule 11).
- **Separation of duties.** The recorder cannot be the payment's creator
  (`E06027`). A staff member paying their own case fees must have a colleague
  record it.
- **Every credit is attributable.** The `PaymentAttestation` row names who
  recorded it, when, and with which receipt; it cannot be edited or deleted,
  and history (0004) records the payment's change by that user.
- **No double use of a receipt**, enforced by a database constraint, not just
  a lookup.
- **Exact amount.** No part payment, no over-collection, no rounding (#8.2
  rule 4).
- **Server-side permission checks** on every staff endpoint and admin view
  (`RLE-04`); hiding a button is not the control.
- **Minimal payer data to staff.** Name and masked phone only.
- **Throttling.** Staff endpoints use the default user throttle; the lookup
  endpoint additionally rate-limits failed lookups per user
  (`PAYMENT_COLLECTION_LOOKUP_THROTTLE_RATE`, default `120/min`), so the
  reference space cannot be enumerated even by an authorised account.
- References are not secrets — knowing one lets nobody pay or see anything
  without the case access or the staff permission.

---

## 16. Logging

One structured line per stage (0027) under the `addon.offline_payment` logger
for provider events and `apps.payments` for service events, always with
`provider_payment_id` and, where known, `payment_id` or `batch_id`:

| Event | Emitted by |
| --- | --- |
| `OFFLINE_REQUEST_ISSUED` (amount, counter, valid_until) | addon `instructions.py` |
| `OFFLINE_REQUEST_EXPIRED` | addon `provider.fetch_status` (once per transition is not guaranteed; the service logs the change) |
| `OFFLINE_ATTESTATION_REJECTED` (failure code, field) | addon `attestation.py` |
| `PAYMENT_COLLECTION_RECORDED` (receipt, method, amount, recorder id, outcome) | `apps.payments` |
| `PAYMENT_COLLECTION_REPLAYED` | `apps.payments` |
| `PAYMENT_COLLECTION_CANCELLED` (by staff, reason) | `apps.payments` |
| `PAYMENT_LATE_SUCCESS` | `apps.payments` (existing) |
| `PROVIDER_ID_COLLISION` | `apps.payments` (#4.2) |

```text
event=PAYMENT_COLLECTION_RECORDED provider=offline provider_payment_id=OFL-261111-7K3QF-9XM2H-V
payment_id=... receipt_number=CJM/EKM/2026/004512 method=DEMAND_DRAFT amount=707.50
recorded_by=<user id> outcome=CREDITED
```

Never logged: payer phone, email or address; instrument numbers are receipt
data and are logged.

---

## 17. Testing

Tests assert error `code` and `field`, never message text (0000 #13). Time is
frozen (`time_machine` / `freezegun`, whichever the project uses) wherever a
date matters, and every date case is written in IST. Concurrency cases run on
PostgreSQL in CI (`select_for_update` is a no-op on SQLite; 0017 #8), and are
marked so local SQLite runs skip them.

### 17.1 Addon unit tests (no database)

**Reference (`test_reference.py`)**

| ID | Case | Expect |
| --- | --- | --- |
| REF-01 | same `reference` + `initiated_at` twice | identical string |
| REF-02 | two different UUIDs, same day | different strings |
| REF-03 | format | matches `^[A-Z]{2,4}-\d{6}-[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z*~$=U]$` |
| REF-04 | `initiated_at` 2026-11-11T18:29:59Z / 18:30:00Z | date part `261111` / `261112` (IST midnight) |
| REF-05 | custom prefix `CRT` | starts `CRT-` |
| REF-06 | normalise lower case, spaces, missing dashes | canonical form |
| REF-07 | normalise `I`, `L` → `1`, `O` → `0` in the body; prefix `OFL` left intact | canonical form, check passes |
| REF-08 | every single-character substitution in the date, body or check symbol | rejected by the check symbol |
| REF-09 | every adjacent transposition within the date and within the body (across the body's dash too) | rejected |
| REF-10 | wrong prefix, wrong length, impossible date (`261341`), `U` in body | rejected |
| REF-11 | empty string, `None`, 200 characters, non-ASCII digits | rejected, no exception other than the parse error |
| REF-12 | an e-GRAS application number (`DR0F9D…`) | rejected |

**Validity (`test_validity.py`)**

| ID | Case | Expect |
| --- | --- | --- |
| VAL-01 | issued 11 Nov, 7 days | `valid_until` 18 Nov 23:59:59.999999 IST |
| VAL-02 | grace 24 h | `expires_at` 19 Nov 23:59:59.999999 IST |
| VAL-03 | grace 0 | `expires_at == valid_until` |
| VAL-04 | `fetch_status` one microsecond before / at / after `expires_at` | `PENDING` / `PENDING` / `FAILED OFFLINE_REQUEST_EXPIRED` |
| VAL-05 | request issued 31 Mar, validity crossing the year / month | correct date arithmetic |
| VAL-06 | validity setting raised after issue | later expiry for the existing reference |
| VAL-07 | validity lowered after issue | earlier expiry |
| VAL-08 | `fetch_status` on a malformed / foreign reference | `NOT_FOUND`, never `SUCCESS`, never raises |
| VAL-09 | `pending_horizon` > `expires_at - issued_on` for every allowed setting | holds (property over the setting ranges) |

**Instructions and initiation (`test_instructions.py`, `test_provider.py`)**

| ID | Case | Expect |
| --- | --- | --- |
| INI-01 | happy path | `SHOW_INSTRUCTIONS`, `provider_payment_id` = reference, details in documented order |
| INI-02 | replay with identical request | equal `ProviderInitiation` |
| INI-03 | `OFFLINE_PAYMENT_ENABLED=False` | `ProviderPermanentError(OFFLINE_DISABLED)` |
| INI-04 | currency `USD` | `OFFLINE_UNSUPPORTED_CURRENCY` |
| INI-05 | `amount` ≠ sum of lines; `amount` 0 | `OFFLINE_AMOUNT_INCONSISTENT` |
| INI-06 | amount equal to / one paisa over `MAX_AMOUNT` | accepted / `OFFLINE_AMOUNT_TOO_LARGE` |
| INI-07 | a line with a charge type outside `ALLOWED_CHARGE_TYPES`; empty list allows all | refused / accepted |
| INI-08 | unknown counter | `field="counter"`, `OFFLINE_INVALID_COUNTER` |
| INI-09 | counters configured, none chosen, default set / not set | default used / `OFFLINE_COUNTER_REQUIRED` |
| INI-10 | no counters configured, counter option sent | `OFFLINE_INVALID_COUNTER` |
| INI-11 | `DEMAND_DRAFT` disabled | no `payable_to` detail |
| INI-12 | amount `707.5` | detail `₹ 707.50`, no rounding |
| INI-13 | batch reference | one reference, all payment numbers listed |
| INI-14 | `metadata` | only `valid_until`, `counter`; no payer data |
| INI-15 | `parse_callback` with any payload, including a valid reference and `status=Success` | `ProviderCallbackMalformed(OFFLINE_NO_CALLBACK)` |
| INI-16 | `initiate` performs no I/O | passes with sockets blocked |
| INI-17 | `list_options` with 0, 1, many counters | `[]`, one, many in order, `group="COUNTER"` |

**Methods and attestation (`test_methods.py`, `test_attestation.py`)** — one
test per row of #8.2, plus:

| ID | Case | Expect |
| --- | --- | --- |
| ATT-01 | valid `CASH` | `SUCCESS`, amount, `provider_reference` = upper-cased trimmed receipt, `paid_at = collected_at` |
| ATT-02 | valid `DEMAND_DRAFT` with optional `branch` omitted | `SUCCESS`; metadata has instrument fields |
| ATT-03 | valid `POS` | `SUCCESS` |
| ATT-04 | method enabled in code but not in settings | `field="method"` |
| ATT-05 | `amount` `707.50` vs expected `707.5` | accepted |
| ATT-06 | `amount` `707.49`, `707.51`, `0`, `-707.50`, `707.505` | `field="amount"` |
| ATT-07 | cash exactly at / above cash cap; DD above cash cap | accepted / refused / accepted |
| ATT-08 | receipt `" cjm/ekm/2026/1 "` | normalised to `CJM/EKM/2026/1` |
| ATT-09 | receipt blank, 65 chars, with spaces inside, with `#` | `field="receipt_number"` |
| ATT-10 | `collected_at` naive | `OFFLINE_COLLECTED_AT_INVALID` |
| ATT-11 | `collected_at` one second before `initiated_at` | `OFFLINE_COLLECTED_BEFORE_REQUEST` |
| ATT-12 | `collected_at` now + 4 min / + 6 min | accepted / `OFFLINE_COLLECTED_IN_FUTURE` |
| ATT-13 | `collected_at` = `valid_until` / + 1 µs | accepted / `OFFLINE_COLLECTED_AFTER_EXPIRY` |
| ATT-14 | recording within grace for a collection inside validity | accepted |
| ATT-15 | recording after `expires_at`, not late / late | `OFFLINE_REQUEST_EXPIRED` / accepted |
| ATT-16 | DD missing `instrument_number` | `field="details.instrument_number"`, `OFFLINE_DETAIL_REQUIRED` |
| ATT-17 | DD number `12345`, `1234567`, `12a456` | `OFFLINE_DETAIL_INVALID` |
| ATT-18 | DD date in the future / after `collected_at` date | `OFFLINE_DD_DATE_INVALID` |
| ATT-19 | DD date exactly 90 / 91 days before | accepted / `OFFLINE_DD_STALE` |
| ATT-20 | DD date `2026-02-30`, `10/11/2026` | `OFFLINE_DETAIL_INVALID` |
| ATT-21 | `CASH` with any `details` key | `OFFLINE_DETAIL_UNKNOWN` |
| ATT-22 | `remarks` 500 / 501 chars | accepted / `field="remarks"` |
| ATT-23 | malformed reference | `OFFLINE_REFERENCE_MALFORMED`, no `field` |
| ATT-24 | several rules broken at once | the first in #8.2 order is reported |
| ATT-25 | `attest` performs no I/O and returns a fresh object | passes with sockets blocked |

**Config and checks (`test_config.py`, `test_checks.py`)** — defaults; each
check `E001`–`E009` failing on its own; `W001`; all checks silent when
`"offline"` is not registered; cache cleared on `setting_changed`.

### 17.2 Payments amendments (`apps/payments/tests/`)

**Provider choice (`test_provider_selection.py`)**

| ID | Case | Expect |
| --- | --- | --- |
| SEL-01 | no `provider`, selectable `[egras, offline]`, default `egras` | e-GRAS used |
| SEL-02 | `provider: "offline"` | offline used; `Payment.provider = "offline"` |
| SEL-03 | `provider` registered but not selectable | `400 E06023` on `provider`, no payment row |
| SEL-04 | `provider` unknown / blank string | `400 E06023` / default |
| SEL-05 | selectable list empty | only the default is accepted |
| SEL-06 | replay same key, same provider | `200`, same `provider_action` |
| SEL-07 | replay same key, different provider | `409 E06009` |
| SEL-08 | batch with `provider: "offline"` | one reference for every payment, shared `batch_id` |
| SEL-09 | provider removed from selectable after initiation | its pending payment still polls, cancels and records through `Payment.provider` |
| SEL-10 | `GET /providers/` | order, labels, `confirmation`, options per provider; `meta` present |
| SEL-11 | one provider's `list_options` raises | it is omitted, others listed |
| SEL-12 | checks `payments.E008`, `E009`, `E010` | each fires on its own |
| SEL-13 | `mark_pending` with an id held by another group of the same provider | new payment `FAILED PROVIDER_ID_COLLISION`, `503 E06015`, other group untouched |
| SEL-14 | same id on two different providers | allowed |

**Recording (`test_collections_service.py`)**

| ID | Case | Expect |
| --- | --- | --- |
| COL-01 | record on a `PENDING` single payment | `SUCCESS`, items `PAID`, demand status recomputed, attestation `CREDITED`, `provider_reference` = receipt, `updated_by` = recorder |
| COL-02 | record on a batch of three demands | all three `SUCCESS` in one transaction; one attestation |
| COL-03 | partially selected items | only those items `PAID`; demand `PARTIALLY_PAID` |
| COL-04 | `payment_completed` | sent once per payment after commit; not sent when the transaction rolls back |
| COL-05 | identical replay | `200`, no second attestation, no second signal |
| COL-06 | replay with different receipt / amount / method | `409 E06025` |
| COL-07 | receipt used by another request | `409 E06026` on `receipt_number`; payment still `PENDING` |
| COL-08 | receipt differing only in case / surrounding spaces | treated as the same receipt |
| COL-09 | recorder is the payment creator | `403 E06027`, even with every permission |
| COL-10 | recorder created another payment in the batch | `403 E06027` |
| COL-11 | provider is e-GRAS / mock | `404 E00105` |
| COL-12 | reference with no payments | `404 E00105` |
| COL-13 | payment `SUCCESS` via another attestation path | `409 E06025` |
| COL-14 | payment `FAILED` (expired) / `CANCELLED`, not late | `409 E06025` |
| COL-15 | same, late, with the late permission | attestation `FLAGGED`; no credit; `needs_reconciliation`; `PAYMENT_LATE_SUCCESS` logged; items still `UNPAID` |
| COL-16 | late without the late permission | `403 E00104` |
| COL-17 | late on a `SUCCESS` request | `409 E06025` |
| COL-18 | provider raises with a field / without | `400 E06024` with that field / `422 E06028`; no attestation row; payment unchanged |
| COL-19 | provider returns non-`SUCCESS` from `attest` (fake provider) | `422 E06028`, logged at error, nothing written |
| COL-20 | provider returns a different amount (fake provider) | flagged `PAYMENT_AMOUNT_MISMATCH`, not credited, attestation `FLAGGED` |
| COL-21 | an item of the payment was cancelled in-process after initiation | refused by 0017's existing guard (an item with an open payment cannot be cancelled); recording succeeds |
| COL-22 | `fetch_status` of an attested fake provider returns `SUCCESS` during polling | ignored, logged `PAYMENT_ATTESTED_PROVIDER_SUCCESS`, payment stays `PENDING` |
| COL-23 | `PaymentAttestation` update / delete / queryset delete | refused |
| COL-24 | history | one history record for the payment change, `history_user` = recorder |

**Concurrency (`test_collections_concurrency.py`, PostgreSQL)**

| ID | Case | Expect |
| --- | --- | --- |
| CON-01 | two threads record the same request with the same receipt | one `200` credit, one `200` replay; one attestation; items credited once |
| CON-02 | two threads, same request, different receipts | one `200`, one `409 E06025` |
| CON-03 | two threads, two requests, same receipt | one `200`, one `409 E06026` (from the constraint) |
| CON-04 | record vs payer cancel | exactly one of `SUCCESS` / `CANCELLED`; the loser gets its `409` |
| CON-05 | record vs poller expiry | exactly one of `SUCCESS` / `FAILED` |
| CON-06 | record on a batch vs `create_payment` on another item of one of its demands | no deadlock; both complete |

**Cancellation and expiry (`test_collections_lifecycle.py`)**

| ID | Case | Expect |
| --- | --- | --- |
| LIF-01 | payer cancels a `PENDING` offline payment | `CANCELLED` immediately; `fetch_status` not called |
| LIF-02 | then creates an e-GRAS payment for the same items | `201` |
| LIF-03 | e-GRAS payment while the offline request is open | `409 E06005` |
| LIF-04 | non-creator case participant cancels | `403 E06017` |
| LIF-05 | staff cancel with permission and reason | `CANCELLED`, reason in `failure_message`, `updated_by` = staff |
| LIF-06 | staff cancel without reason / without permission | `400 E00002` on `reason` / `403 E00104` |
| LIF-07 | staff cancel a terminal request | `409 E06011` |
| LIF-08 | poller before `expires_at` | stays `PENDING`, backoff recorded |
| LIF-09 | poller after `expires_at` | `FAILED OFFLINE_REQUEST_EXPIRED`; items payable again |
| LIF-10 | never flagged `PAYMENT_STUCK` before it expires | holds for every allowed validity/grace |
| LIF-11 | callback `POST /providers/offline/_callback` with a valid reference and `status=Success` | `302 … status=UNKNOWN`; payment unchanged |
| LIF-12 | `OFFLINE_PAYMENT_ENABLED=False` with one request in flight | new request `422 E06014`; the in-flight one can still be recorded |
| LIF-13 | `GET /payments/{id}/action/` by the creator for a `PENDING` offline payment | same `details` as at creation |
| LIF-14 | the same by another participant / for a `SUCCESS` payment | `403 E06017` / `409 E06025` |

### 17.3 API tests (`test_collections_api.py`)

| ID | Case | Expect |
| --- | --- | --- |
| API-01 | every staff endpoint anonymous / registration incomplete | `401 E00102` / `403` registration code |
| API-02 | every staff endpoint without its permission | `403 E00104` |
| API-03 | lookup with lower-case, unspaced reference | `200`, canonical reference |
| API-04 | lookup with a bad check symbol | `400 E00001` on `reference` |
| API-05 | lookup response | masked phone; no email/address; filing number; items; `valid_until`; `meta` |
| API-06 | confirm happy path | `200`, `status SUCCESS`, `attestation` block |
| API-07 | confirm without `collected_at` | defaults to now |
| API-08 | confirm body shape errors: amount `"abc"`, `"1.234"`, `0`; `collected_at` without offset; `details` nested object | `400` common codes on the field |
| API-09 | every business error of #9.2.2 | its code and field; declared in the schema |
| API-10 | list: pagination, `-initiated_at`, `status`, `search` by reference / payment number / demand number / filing number / payer name | correct rows, one per group |
| API-11 | list never includes e-GRAS or mock payments | holds |
| API-12 | register: `collected_on` IST boundaries, `recorded_by`, `method`, totals | correct |
| API-13 | `GET /collections/methods/?provider=offline` | enabled methods with fields; e-GRAS → `404 E00105` |
| API-14 | payer `GET /payments/{id}/` after recording | `provider_reference`, `attestation` without recorder identity |
| API-15 | OpenAPI schema | every new endpoint present, tagged `payments`, error examples generated, `details` and `attestation` documented |
| API-16 | lookup throttling | `429 E00110` after the configured failed lookups |

### 17.4 Admin (`test_admin_collections.py`)

- "Awaiting collection" filter lists only `PENDING` attested payments.
- The record button and form appear only with the permission and only for an
  open attested payment; the late form only for a closed one with the late
  permission.
- Submitting a valid form credits the payment; a business error is shown on
  the matching form field and nothing is written.
- Cancel action requires a reason and the permission.
- `PaymentAttestationAdmin` is read-only: no add, change or delete.

### 17.5 Flow and coexistence (`addon/offline_payment/tests/`)

- `test_flow.py`: payer creates through the REST API → `201` instructions →
  staff look up → staff record → payer sees `SUCCESS` → receiver of
  `payment_completed` called with `demand_paid=True`.
- Same for a batch of three demands on two cases.
- Abandoned request → poller after expiry → `FAILED` → payer pays online.
- `test_coexistence.py` (e-GRAS mocked as in 0022's flow tests): both providers
  listed; an e-GRAS payment and an offline payment on different items of one
  demand both complete and the demand becomes `PAID`; an e-GRAS callback with
  an offline reference redirects `UNKNOWN`; an offline lookup with an e-GRAS
  application number is `404`.
- Production settings: `PAYMENT_SELECTABLE_PROVIDERS=egras,offline` registers
  both; `PAYMENT_REGISTERED_PROVIDERS=offline` with the default `egras` keeps
  offline recordable but not selectable.

### 17.6 Isolation (`test_isolation.py`)

- No module under `apps.payments` imports `addon.*` or mentions `offline`
  (case-insensitive) outside comments and tests.
- The addon imports only the surface listed in #1, and has no `errors.py`,
  `urls.py`, `models.py`, `admin.py` or `migrations/`.
- With `"offline"` removed from settings, `apps.payments` tests pass on the
  mock and e-GRAS.

```bash
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest
cd src && ruff check . && ruff format .
cd src && python manage.py check
```

---

## 18. Affected files

New (addon):
- `src/addon/offline_payment/{__init__,apps,provider,config,constants,reference,validity,instructions,methods,attestation,checks}.py`
- `src/addon/offline_payment/tests/*`

Modified (payments, per #4):
- `src/apps/payments/providers/base.py`, `providers/registry.py`
- `src/apps/payments/models.py` + new migration (`PaymentAttestation`, permissions)
- `src/apps/payments/services/payments.py`, `services/polling.py`
- `src/apps/payments/selectors.py` (collection lookup, list, register)
- `src/apps/payments/serializers.py`, `views.py`, `urls.py`, `admin.py` (+ admin template for the record form)
- `src/apps/payments/errors.py`, `checks.py`, `conf.py`
- `src/apps/payments/tests/*`
- `src/addon/egras_payment_gateway/provider.py` — `label` only

Modified (wiring and docs):
- `src/config/settings/base.py` — `INSTALLED_APPS`, `PAYMENT_SELECTABLE_PROVIDERS`, `OFFLINE_PAYMENT_*` block
- `src/config/settings/local.py`, `production.py` — register `offline` when default, registered or selectable
- `.env.example`, `.env.prod.example`, `README.md`
- `spec/0017-orders-management.md` — link to this spec from #9 and from the non-goal "Offline/cash counter collection"; close open question 6

---

## 19. Out of scope

- Cheques and any other instrument that can bounce.
- Dristi-issued receipt numbers, printed receipts, payment slip PDFs and QR
  codes (#21).
- Court-fee stamps, e-stamps and vendor channels.
- SMS or email to the payer with the reference or on recording.
- Cash book, treasury remittance and day-end cash reconciliation beyond the
  read-only register.
- Part payments, excess collection and refunds.
- Restricting recording to a counter, courtroom or establishment.
- A counter user interface (this spec provides its APIs).

## 20. Acceptance criteria

- [ ] Offline ships as `src/addon/offline_payment/` with no models, migrations, URLs, admin or `errors.py`.
- [ ] The addon imports only the contract and the read-only helpers listed in #1; no module under `apps.payments` imports `addon.*` or mentions the offline provider.
- [ ] e-GRAS and offline can be offered together; the payer chooses per payment with `provider`; omitting it uses the default.
- [ ] Removing a provider from the selectable list never strands its in-flight payments.
- [ ] `initiate` makes no I/O and is deterministic; the reference follows #5.2 and rejects every single-character typo and adjacent swap.
- [ ] Instructions are returned as `SHOW_INSTRUCTIONS` with ordered `details`, and can be fetched again by the payer.
- [ ] No callback, poll or payer action can credit an offline payment; only `record_collection` can.
- [ ] Recording requires the permission, refuses the payment's creator, refuses any amount other than the exact amount due, and credits the whole group once.
- [ ] Receipt numbers are unique per provider in the database; identical replays return `200` without a second credit.
- [ ] Every recording leaves an immutable `PaymentAttestation` naming the recorder.
- [ ] Requests expire through `fetch_status` → `FAILED`, never through `PAYMENT_STUCK`; items become payable again.
- [ ] Payers can cancel an offline request immediately; staff can cancel with a reason.
- [ ] Late recording flags, never credits.
- [ ] The Django admin can find, record, late-record and cancel requests through `PaymentService`.
- [ ] New error codes `E06023`–`E06028` are registered, declared on their endpoints and covered by tests; offline failure codes never appear in an `errors` array.
- [ ] `manage.py check` fails on invalid offline configuration and is silent when the provider is not registered.
- [ ] Unit, service, concurrency, API, admin, flow, coexistence and isolation tests pass; Ruff clean.

---

## 21. Open questions

1. **Receipt numbers.** Do courts keep a physical receipt book whose number
   staff type (this spec), or should Dristi issue the receipt number
   (`RCT-{YYYY}-{seq}`, 0017 #11 numbering) and print the receipt?
2. **Court role.** Should `court-roles.md` gain a **Fee collector** role, held
   per establishment, replacing the Django permissions of #4.7? Which staff
   title holds it in Kerala, Gujarat and Punjab & Haryana?
3. **Late collections.** May an operator credit a late collection when every
   item is still unpaid, instead of always refunding (0017 open question 13)?
4. **Counter binding.** Must a request be paid at the counter the payer chose,
   or at any counter of the establishment?
5. **Validity.** Is seven days right? Should it differ by charge type — for
   example shorter for process fees tied to a hearing date?
6. **Cash cap.** What cash limit applies to court fees, if any?
7. **Which flows allow offline.** Should offline be refused for some flows
   (for example bulk filing), beyond the charge-type filter?
8. **Payment slip.** Should the payer get a printable slip with a QR code of
   the reference ([0016](0016-pdf-services.md)), and an SMS with the reference
   ([0009](0009-messaging.md))?
9. **Labels.** Instruction labels are English; should they follow the
   language support of [0030](0030-core-language-support.md)?

## 22. Design decisions

| Decision | Rationale |
| --- | --- |
| Offline is a provider addon, not a mode inside `apps.payments` | It is replaceable and removable like e-GRAS; reference format, validity and instrument rules are channel detail. |
| Staff confirmation lives in `apps.payments` as a generic "attested" capability | Addons have no models, URLs or admin; the attestation, its uniqueness and its locking are domain concerns any future attested channel reuses. |
| `attest` is a pure validator returning `ProviderStatus` | Keeps the one-way dependency and the "dataclasses in, dataclasses out" rule; credit still goes only through `apply_provider_status` → `confirm_payment`. |
| `fetch_status` never returns `SUCCESS` for attested providers | Money credited by a computation rather than a person would be a forgery path. |
| Exact amount only | No part payments exist in 0017; over-collection would need refunds, which are out of scope. |
| Receipt uniqueness in the database | Two clerks with the same receipt book page at once is a real race; an application check cannot stop it. |
| Recorder ≠ payer | The simplest separation-of-duties control for staff who are also litigants or advocates. |
| Self-checking, date-stamped reference | Read aloud and typed by hand; the check symbol turns typos into a clear error, and the date makes expiry stateless. |
| Expiry through `FAILED` from `fetch_status` | Reuses 0017's poller unchanged and frees blocked items; 0017's "never fail on age" holds because the provider, not the poller, declares the failure. |
| Recording grace after validity | Counters record after closing; money collected in time must not become a late collection. |
| Cancel without asking the provider | Nobody outside Dristi can complete an offline payment; the lock decides between cancel and record. |
| Several selectable providers, one default | Payers need a choice; the default keeps existing clients working unchanged. |
| Late collections flag, never credit | Same rule as e-GRAS late success: a closed payment never reopens. |
| Django admin first, APIs alongside | The user need is immediate; the API is the same service, so the future counter screen adds no rules. |

## 23. Implementation phases

1. **Payments amendments** — contract additions, `PaymentAttestation`,
   `record_collection`, cancel rule, provider choice, error codes, checks,
   tests (#4, #17.2).
2. **Addon** — scaffolding, config, checks, reference, validity, instructions,
   methods, attestation, provider, unit and isolation tests (#5–#8, #17.1).
3. **Admin** — awaiting-collection filter, record / late / cancel forms,
   attestation admin (#10, #17.4).
4. **APIs** — provider list, action endpoint, collection endpoints, register,
   schema (#9, #17.3).
5. **Flow and rollout** — flow and coexistence tests; enable per environment
   with `PAYMENT_SELECTABLE_PROVIDERS=egras,offline`.
