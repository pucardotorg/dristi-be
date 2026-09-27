# 0013 — CDAC SMS Gateway Addon (`addon.cdac_sms_gateway`)

## Status

Proposed

## References

- [0009 — Messaging Module](0009-messaging.md) — the consuming module (implemented)
- [0000 — API Coding Spec](0000-api-coding-spec.md) — style constraints

> **Scope note.** CDAC is a *gateway*, not a messaging service: it owns the CDAC
> wire protocol and nothing else. Orchestration, templating, queuing, retries,
> and audit remain owned by [0009-messaging.md](0009-messaging.md). The gateway ships inside a shared `addon`
> package as `addon.cdac_sms_gateway` and is consumed purely through the
> `MESSAGING_BACKENDS` setting.

## Context

Dristi already has a channel-agnostic messaging module (0009):

- `MessageTemplate` / `MessageLog` models
- `MessageTemplateRenderer` → `RenderedMessage`
- `BaseMessageSender` → `SMSSender` → `ConfiguredBackendSender`, with backend
  lookup via `settings.MESSAGING_BACKENDS`
- `send_message` Dramatiq actor (Redis broker) with log-driven retries
- A development-only `DummySMSBackend` that POSTs to an HTTP endpoint

What is missing is a SMS gateway. CDAC (`msdgweb.mgov.gov.in`) is the
gateway used by state e-governance deployments, and its wire contract (SHA-1
password hash, SHA-512 request signature, service-type mapping, numeric
HTML-entity Unicode encoding, DLT template IDs) is specific enough to justify an
isolated module.

## Goals

- Ship `CDACSMSBackend` in a standalone, removable module satisfying 0009's SMS
  sender contract.
- Keep every CDAC-specific detail (hashing, signature, service types, Unicode
  encoding, form fields, TLS) inside `addon/cdac_sms_gateway/`.
- Enforce a one-way source dependency: the addon imports from `apps.messaging`;
  `apps.messaging` never imports the addon.
- Reuse 0009's queuing, retry, status, and audit machinery without forking it.
- Keep each gateway concern independently unit-testable.

## Non-goals

- A second messaging service, provider registry, or Dramatiq actor.
- A new SMS request model or SMS audit table (`MessageLog` is the audit store).
- Any models or migrations in the addon.
- Delivery-status polling, bounce handling, provider failover, message expiry,
  or campaign management.
- Any REST API surface. This iteration adds no endpoints, so 0000 applies only
  as a style constraint (no Pydantic, thin logic layers, explicit tests, Ruff,
  system checks). If an operational status endpoint is added later it must carry
  the standard `meta` envelope and its own Swagger tag.

---

## 1. Module placement and dependency direction

```text
src/
├── apps/
│   ├── core/
│   ├── messaging/
│   └── ...
├── addon/                         # pluggable integrations (new)
│   ├── __init__.py
│   └── cdac_sms_gateway/          # THIS SPEC
└── config/
    └── settings/base.py           # the only wiring point
```

`addon` is a plain package (an `__init__.py` with a docstring) and is **not**
itself a Django app. Each integration underneath it is independently
installable, and future addons slot in as `addon.<name>`.

Dependency rules:

```text
addon.cdac_sms_gateway  ---- imports ---->  apps.messaging (senders.sms, services)
apps.messaging          --- never imports -->  addon.*
config.settings.base    ---- references --->  "addon.cdac_sms_gateway.backend.CDACSMSBackend"
```

The addon imports only the *contract* — the `SMSSender` base class, the
exception types, and `RenderedMessage` for typing. It never imports messaging
models, tasks, or services behaviour.

`apps.messaging` references the addon only as a **string** in
`MESSAGING_BACKENDS`, resolved lazily at first send by the existing
`ConfiguredBackendSender._get_configured_backend()` (`import_string`). Deleting
`src/addon/cdac_sms_gateway/` plus its settings entries must leave a working
messaging module on `DummySMSBackend`.

Django registration:

```python
# config/settings/base.py
INSTALLED_APPS = [
    ...
    "apps.messaging",
    "apps.locations",
    # Addons
    "addon.cdac_sms_gateway",
]
```

The addon is an installed app only so it can register system checks. Its
`AppConfig` sets `name = "addon.cdac_sms_gateway"` and an explicit
`label = "cdac_sms_gateway"`. It contributes no models, migrations, templates,
URLs, admin, or middleware.

Imports need no path configuration: `src/` is already the import root
(`manage.py` lives there, the Dockerfile does `COPY src /app` with
`WORKDIR /app`, and pytest's rootdir is `src/`), exactly as `apps.*` and
`config.*` resolve today.

---

## 2. Where the gateway plugs in

```text
caller
  |
  v
enqueue_sms(message_key, recipient, context)      [apps.messaging]
  |
  +-- resolve_template() -> MessageTemplate
  +-- MessageLog.objects.create(status=pending)
  +-- send_message.send(log_id)  ---> Redis ---> worker
                                                   |
                                                   v
                                       send_message(log_id)     [apps.messaging]
                                                   |
                                     +-------------+-------------+
                                     |                           |
                                     v                           v
                          MessageTemplateRenderer        get_backend("sms")
                                     |                           |
                                     +----> RenderedMessage ---> SMSSender
                                                                 |
                                            MESSAGING_BACKENDS["sms"]  (string)
                                                                 |
                                                                 v
                                                        CDACSMSBackend
                                                     [addon.cdac_sms_gateway]
                                                                 |
                                            +--------------------+--------------------+
                                            |                    |                    |
                                            v                    v                    v
                                   recipient filtering   request building     response validation
                                                                 |
                                                                 v
                                                           CDACClient
                                                                 |
                                            +--------------------+--------------------+
                                            |                    |                    |
                                            v                    v                    v
                                     password hash        SHA-512 key        Unicode encoding
                                                                 |
                                                                 v
                                                      HTTP POST (urlencoded, TLS 1.2+)
                                                                 |
                                                                 v
                                                           CDAC gateway
```

The addon is entered exactly once per delivery attempt, synchronously, inside
the Dramatiq worker. It never enqueues, never writes to `MessageLog`, and never
decides retry policy.

---

## 3. Responsibility boundary

The gateway splits into a thin backend and a dumb client: the **backend** decides
*whether* and *which type* of SMS to send; the **client** knows only how to
build, sign, and post the form request, and returns the raw status code and body
without judging success.

| Concern | Owner |
| --- | --- |
| Template resolution, rendering, context validation | `apps.messaging.services` |
| `MessageLog` lifecycle, `attempt_count`, statuses, timestamps | `apps.messaging.tasks` |
| Enqueue, Redis broker, backoff, retry eligibility | `apps.messaging.tasks` |
| Channel dispatch / backend lookup | `apps.messaging.senders` |
| Sender contract and exception vocabulary | `apps.messaging` (public API) |
| Gateway credential + option loading | addon `config.py` |
| Recipient filtering and non-production override | addon `filtering.py` |
| Service-type mapping, template ID, mobile prefix | addon `backend.py` |
| Password hash, request signature | addon `hashing.py` |
| Unicode content encoding | addon `unicode_encoding.py` |
| Form data, TLS, timeout, HTTP POST | addon `client.py` |
| HTTP/body validation and failure classification | addon `response.py` |

Rule of thumb: **if removing the CDAC integration tomorrow would delete the
code, it belongs in the addon. Otherwise it belongs in `apps.messaging`.**

Identity of a message is owned by 0009:

| Concept | Where it lives |
| --- | --- |
| Request ID | `MessageLog.id` (UUID) |
| Correlation ID | `MessageLog.correlation_id` (new field) |
| Recipient | `MessageLog.recipient["phone_number"]` |
| Message body | `MessageLog.rendered_content` |
| Category | `MessageTemplate.category` |
| DLT template ID | `MessageTemplate.provider_template_id` (new field) |

---

## 4. Addon layout and gateway contract

```text
src/addon/
├── __init__.py
└── cdac_sms_gateway/
    ├── __init__.py
    ├── apps.py                  # AppConfig(name="addon.cdac_sms_gateway")
    ├── backend.py               # CDACSMSBackend(SMSSender)
    ├── client.py                # CDACClient (form build, TLS, timeout, POST)
    ├── config.py                # CDACConfig, resolve_config(), validation
    ├── constants.py             # service types, error codes, log events
    ├── checks.py                # Django system checks
    ├── filtering.py             # whitelist/blacklist/default-number override
    ├── hashing.py               # password hash + request signature
    ├── response.py              # response validation + classification
    ├── unicode_encoding.py      # numeric HTML-entity encoding
    └── tests/
        ├── __init__.py
        ├── test_config.py
        ├── test_hashing.py
        ├── test_unicode.py
        ├── test_filtering.py
        ├── test_response.py
        ├── test_backend.py      # form fields, service type, template, prefix
        ├── test_checks.py
        └── test_delivery.py     # stub-broker end-to-end with mocked gateway
```

Addon tests live with the addon. `pytest` runs from `src/`, so they are
collected automatically.

The addon implements the existing sender contract and nothing more:

```python
# addon/cdac_sms_gateway/backend.py
from apps.messaging.senders.sms import SMSSender


class CDACSMSBackend(SMSSender):
    """Deliver SMS through the CDAC (msdgweb) DLT gateway."""

    def send(self, rendered_message) -> str | None:
        """Deliver one SMS.

        Returns the CDAC message ID (stored by apps.messaging as
        MessageLog.provider_message_id) or None when the gateway returns none.

        Raises:
            MessagePermanentError  -- do not retry (bad config/request/category)
            MessageSendError       -- transient; apps.messaging schedules a retry
            RecipientFilteredError -- suppressed by policy, not a failure
        """
```

`send()` is the addon's only public surface. Callers keep using
`enqueue_sms(...)` and never see CDAC endpoints, hashes, service types, or form
fields.

Activation is configuration only:

```python
MESSAGING_BACKENDS = {
    "email": "apps.messaging.senders.email.SMTPEmailBackend",
    "sms": "addon.cdac_sms_gateway.backend.CDACSMSBackend",  # only change needed
}
```

Recommended per-environment default: `DummySMSBackend` in
`config.settings.local` and `config.settings.test`; `CDACSMSBackend` in
staging/production.

---

## 5. CDAC wire contract

### 5.1 Endpoint

```text
POST https://msdgweb.mgov.gov.in/esms/sendsmsrequestDLT
Content-Type: application/x-www-form-urlencoded
```

Only `POST` is supported. The method and content type are fixed properties of
the contract, owned by `CDACClient`; they are not configurable. The URL is
configurable per gateway.

### 5.2 Form fields

| CDAC field | Source |
| --- | --- |
| `username` | gateway config `username` |
| `password` | SHA-1 hash of gateway config `password` |
| `senderid` | gateway config `sender_id` |
| `content` | rendered body; entity-encoded for Unicode |
| `smsservicetype` | category + content type mapping |
| `mobileno` | `mobile_prefix` + `recipient["phone_number"]` |
| `key` | SHA-512 signature |
| `templateid` | `MessageTemplate.provider_template_id`, else config `template_id` |

### 5.3 Dispatch mapping

| `MessageTemplate.category` | Content type | `smsservicetype` | Mobile field |
| --- | --- | --- | --- |
| `OTP` | text or unicode | `otpmsg` | `mobileno` |
| `NOTIFICATION` | text | `singlemsg` | `mobileno` |
| `NOTIFICATION` | unicode | `unicodemsg` | `mobileno` |
| `TRANSACTION` | text | `singlemsg` | `mobileno` |
| `TRANSACTION` | unicode | `unicodemsg` | `mobileno` |
| anything else | any | `MessagePermanentError(UNSUPPORTED_CATEGORY)` | — |

Notes:

- **`mobileno` is used for every service type**, including the Unicode paths.
  The gateway also exposes a bulk mobile field; it is never used here.
- OTP uses `otpmsg` regardless of content type.

### 5.4 Hashing and signature

```text
password --> ISO-8859-1 bytes --> SHA-1 --> lowercase hex --> form field "password"

username.strip() + sender_id.strip() + content.strip() + secure_key.strip()
        --> UTF-8 bytes --> SHA-512 --> lowercase hex --> form field "key"
```

- No separators between signature components.
- The `content` used for the signature is the **final** content, i.e. after
  Unicode entity encoding.
- The plaintext password is never transmitted.
- Functions are named for the algorithm they implement:
  `generate_password_hash()` and `generate_signature()`.

### 5.5 Unicode encoding

When content type is unicode, every code point becomes a numeric HTML entity,
because the CDAC unicode endpoint expects HTML numeric entities rather than raw
UTF-8:

```text
"नमस्ते" -> "&#2344;&#2350;&#2360;&#2381;&#2340;&#2375;"
```

ASCII characters are encoded the same way when Unicode mode is active, so the
function stays pure and independently unit-testable.

### 5.6 Content type determination

The addon derives Unicode mode from the rendered body (any code point > 127)
rather than requiring callers to declare it. An explicit override may be passed
via `context["sms_content_type"] = "unicode" | "text"`. This avoids a model
change and keeps `RenderedMessage.content_type` (a MIME type used by email)
unambiguous.

### 5.7 Template ID resolution

```text
MessageTemplate.provider_template_id   (new field, blank allowed)
        |
        +-- non-empty ---> use it
        |
        +-- empty -------> gateway config template_id
                                |
                                +-- empty ---> send without templateid
```

### 5.8 Mobile number

```text
prefix "91" + "9876543210" -> "919876543210"
```

`apps.messaging` keeps storing the caller-supplied number in
`MessageLog.recipient`; the prefix is applied only when building the CDAC
request. Filtering (§7) matches against the number **before** the prefix is
applied.

### 5.9 TLS and timeouts

- The client requires **TLS 1.2 or higher**.
- `CDAC_SMS_VERIFY_SSL=True` (default) enforces strict certificate verification.
- `CDAC_SMS_VERIFY_SSL=False` is for local/test only, must also suppress
  `InsecureRequestWarning` noise, and is rejected in production.
- `CDAC_SMS_TIMEOUT` (default `30`) is the connect/read timeout.
- The messaging actor's `time_limit` is set explicitly and must be **greater
  than** `CDAC_SMS_TIMEOUT`, so a network hang surfaces as a clean transient
  failure rather than a worker kill.

---

## 6. Configuration

### 6.1 Namespace

Addon-owned settings use the `CDAC_SMS_` prefix, keeping them visibly distinct
from `MESSAGING_*` (owned by 0009). They live in a dedicated block in
`config/settings/base.py` so the whole integration can be removed by deleting
that block plus the `INSTALLED_APPS` and `MESSAGING_BACKENDS` entries.

### 6.2 Gateway credentials

One deployment serves one state, so the gateway has exactly one set of
credentials. They are flat settings read from the environment:

```python
# config/settings/base.py — CDAC SMS gateway addon
CDAC_SMS_URL = env("CDAC_SMS_URL", default="")
CDAC_SMS_USERNAME = env("CDAC_SMS_USERNAME", default="")
CDAC_SMS_PASSWORD = env("CDAC_SMS_PASSWORD", default="")
CDAC_SMS_SENDER_ID = env("CDAC_SMS_SENDER_ID", default="")
CDAC_SMS_SECURE_KEY = env("CDAC_SMS_SECURE_KEY", default="")
CDAC_SMS_TEMPLATE_ID = env("CDAC_SMS_TEMPLATE_ID", default="")
CDAC_SMS_MOBILE_PREFIX = env("CDAC_SMS_MOBILE_PREFIX", default="")
```

| Setting | Required | Notes |
| --- | --- | --- |
| `CDAC_SMS_URL` | yes | `https://msdgweb.mgov.gov.in/esms/sendsmsrequestDLT` |
| `CDAC_SMS_USERNAME` | yes | CDAC username |
| `CDAC_SMS_PASSWORD` | yes | plaintext in config; hashed before transmission |
| `CDAC_SMS_SENDER_ID` | yes | registered sender ID |
| `CDAC_SMS_SECURE_KEY` | yes | signature key; never logged |
| `CDAC_SMS_TEMPLATE_ID` | no | fallback DLT template ID |
| `CDAC_SMS_MOBILE_PREFIX` | no | e.g. `91` |

`config.resolve_config()` loads these into a frozen `CDACConfig` dataclass once
and caches it. State-specific values are supplied by the deployment's
environment, so the code stays state agnostic: a different state is a different
`.env`, never a different code path.

### 6.3 Transport and validation options

| Setting | Type | Default | Notes |
| --- | --- | --- | --- |
| `CDAC_SMS_ENABLED` | bool | `True` | master kill-switch |
| `CDAC_SMS_TIMEOUT` | int (s) | `30` | connect/read timeout |
| `CDAC_SMS_VERIFY_SSL` | bool | `True` | certificate verification |
| `CDAC_SMS_SUCCESS_CODES` | list[int] | `[200, 201, 202]` | allowed HTTP statuses |
| `CDAC_SMS_ERROR_CODES` | list[int] | `[]` | disallowed HTTP statuses |
| `CDAC_SMS_VERIFY_RESPONSE` | bool | `False` | enable body-substring check |
| `CDAC_SMS_VERIFY_RESPONSE_CONTAINS` | str | `""` | literal expected in body |
| `CDAC_SMS_PRINT_RESPONSE` | bool | `True` | log gateway status and body (redacted) |

`CDAC_SMS_ENABLED=False` makes the backend raise `RecipientFilteredError`
(logged as `FILTERED`, reason `disabled`) without contacting the gateway, so
nothing is retried and the outcome stays auditable.

### 6.4 Recipient policy

| Setting | Type | Default | Notes |
| --- | --- | --- | --- |
| `CDAC_SMS_WHITELIST_NUMBERS` | list[str] | `[]` | empty means allow all |
| `CDAC_SMS_BLACKLIST_NUMBERS` | list[str] | `[]` | patterns to suppress |
| `CDAC_SMS_USE_DEFAULT_NUMBER` | bool | `False` | replaces **all** recipients |
| `CDAC_SMS_DEFAULT_NUMBER` | str | `""` | exactly 10 digits when enabled |

The default-number override exists for non-production testing only.
`CDAC_SMS_USE_DEFAULT_NUMBER=True` and `CDAC_SMS_VERIFY_SSL=False` are rejected
by `config/settings/production.py` and should be gated in CI/CD.

Every setting is documented in `.env.example`, `.env.prod.example`, and
`README.md`, per `AGENTS.md`.

---

## 7. Recipient filtering

```text
resolved recipient (recipient["phone_number"])
      |
      v
CDAC_SMS_ENABLED == False ?  --> RecipientFilteredError(reason=disabled)
      |
      v
default-number override (non-production only)
      |
      v
whitelist  (empty = allow all)
      |
      v
blacklist
      |
      +-- rejected --> RecipientFilteredError(reason=whitelist|blacklist)
      |
      v
mobile prefix applied --> CDAC request
```

### Pattern matching

Whitelist and blacklist entries are **patterns, not exact numbers**, supplied as
comma-separated values:

- `X` matches any single digit
- `*` matches any remaining sequence of digits
- every other character matches literally

Patterns are compiled to anchored regular expressions and matched with
`fullmatch` against the number **after** any default-number override and
**before** the mobile prefix is applied:

```text
98765XXXXX  matches 9876512345, not 9123456789
9876*       matches 9876512345 and 98761
9876512345  exact match only
```

Filtering lives in the addon because the policy settings are addon-owned and
gateway-specific. A filtered recipient is **not** a gateway failure:
`apps.messaging` records `MessageLog.status = filtered` and does not retry.

---

## 8. Response handling and failure classification

`CDACClient.post()` returns `(status_code, body)` and makes no business
decision. `response.classify(status_code, body)` applies this order:

1. If `CDAC_SMS_PRINT_RESPONSE`, log the status code and body, redacting any
   `password` and `key` values if the body echoes the request.
2. If `CDAC_SMS_VERIFY_RESPONSE`, the body must contain the literal
   `CDAC_SMS_VERIFY_RESPONSE_CONTAINS`; otherwise `RESPONSE_VALIDATION_FAILED`.
3. If `CDAC_SMS_SUCCESS_CODES` is non-empty, the status must be in the list.
4. If `CDAC_SMS_ERROR_CODES` is non-empty, the status must not be in the list.
5. **Any validation failure is transient** and triggers a retry. The gateway can
   return a non-success status for load or upstream reasons, so no HTTP status
   alone is treated as permanent.

On success the CDAC message ID is parsed from bodies shaped like
`402,MsgID = <id>msdgsms` and returned as `provider_message_id`. A body that
passes validation but yields no parsable ID is still a success with
`provider_message_id = None`. In production `CDAC_SMS_VERIFY_RESPONSE_CONTAINS`
is typically set to `MsgID` or `402`.

Transport errors map to transient: `GATEWAY_TIMEOUT`,
`GATEWAY_CONNECTION_ERROR`, `GATEWAY_UNAVAILABLE`.

Error codes (defined in `constants.py`):

```text
PERMANENT: INVALID_REQUEST, INVALID_RECIPIENT, INVALID_CONFIGURATION,
           UNSUPPORTED_CATEGORY, UNSUPPORTED_CONTENT_TYPE
TRANSIENT: GATEWAY_TIMEOUT, GATEWAY_CONNECTION_ERROR, GATEWAY_UNAVAILABLE,
           GATEWAY_ERROR, RESPONSE_VALIDATION_FAILED
```

Permanent failures are raised only for conditions that retrying cannot fix:
missing or invalid configuration, missing recipient, and unsupported category or
content type.

---

## 9. Retry (owned by `apps.messaging`)

The addon implements no retries, backoff, or Dramatiq retry middleware. 0009
deliberately keeps `send_message` at `max_retries=0` and drives retries from
persisted `MessageLog` state for auditability; that design stands.

`apps.messaging` needs only exception-aware classification:

```text
gateway raises
      |
      +-- RecipientFilteredError --> status=filtered, no retry
      |
      +-- MessagePermanentError ---> status=failed, no retry
      |
      +-- MessageSendError --------> can_retry() ? re-enqueue with backoff
      |                                          : status=failed
      v
success --> status=sent, sent_at, provider_message_id
```

Retry count stays per-template (`MessageTemplate.max_retries`); backoff stays
`MESSAGING_RETRY_DELAY_BASE` / `MESSAGING_RETRY_DELAY_MAX` (exponential,
capped). Recommended template defaults: OTP `max_retries=1`, notifications `2`.

---

## 10. Changes required in `apps.messaging` (0009 amendments)

These live in the messaging module because they are gateway-agnostic; any future
addon benefits from them.

`services.py` — extend the public exception vocabulary:
- `MessagePermanentError(MessageSendError)` — never retried
- `RecipientFilteredError(Exception)` — suppressed by policy, not a failure

`tasks.py`
- classify the three outcomes above in `_record_failure()`
- accept and propagate `correlation_id` through `enqueue_sms()`
- set an explicit actor `time_limit` greater than `CDAC_SMS_TIMEOUT`

`models.py` + one migration
- `MessageTemplate.provider_template_id = CharField(max_length=255, blank=True)`
- `MessageLog.correlation_id = CharField(max_length=255, blank=True, db_index=True)`
- `MessageLog.provider = CharField(max_length=50, blank=True)` (e.g. `cdac`)
- `MessageLog.gateway_status = CharField(max_length=20, blank=True)`
- `MessageLog.failure_code = CharField(max_length=50, blank=True)`
- `MessageLog.Status.FILTERED = "filtered"`

`admin.py` — expose the new `MessageLog` fields and filters.

`MessageLog.id` is the request ID; `correlation_id` defaults to the log ID when
the caller supplies none. No separate SMS audit table is introduced, and the
addon contributes no models or migrations.

---

## 11. Logging

One structured line per stage, carrying both identifiers, under the
`addon.cdac_sms_gateway` logger:

| Event | Emitted by |
| --- | --- |
| `ENQUEUED` | `apps.messaging.tasks.enqueue_sms` |
| `FILTERED` (with reason) | addon `filtering.py` |
| `GATEWAY_REQUEST` | addon `client.py` |
| `GATEWAY_RESPONSE` | addon `response.py` |
| `SENT` / `FAILED` / `RETRYING` | `apps.messaging.tasks` |

```text
event=GATEWAY_RESPONSE message_id=<MessageLog.id> correlation_id=...
gateway=cdac category=OTP content_type=unicode
attempt=1 status=sent gateway_status=200
```

`GATEWAY_REQUEST` logs the URL, service type, whether a mobile prefix was
applied, and a **masked** body (recipient partially masked; `password` and `key`
omitted entirely).

Never logged, in any mode: plaintext password, SHA-1 password hash, secure key,
SHA-512 signature, or an unmasked form body. `CDAC_SMS_PRINT_RESPONSE`
(default on) logs the gateway status code and body with those values redacted.

Monitoring uses these logs plus `MessageLog` aggregates (counts by `status`,
`failure_code`, `attempt_count`; latency from `created_at` → `sent_at`). No
dedicated metrics backend in this iteration.

---

## 12. Startup validation

Validation runs through the Django system check framework, registered in the
addon's `AppConfig.ready()`, so misconfiguration is caught by
`python manage.py check` and at container startup rather than on first send.

Checks (error level, only when `CDACSMSBackend` is the configured SMS backend
and `CDAC_SMS_ENABLED` is true):

- `CDAC_SMS_URL`, `CDAC_SMS_USERNAME`, `CDAC_SMS_PASSWORD`, `CDAC_SMS_SENDER_ID`,
  and `CDAC_SMS_SECURE_KEY` are all set
- `CDAC_SMS_URL` is an absolute `https://` URL
- `CDAC_SMS_DEFAULT_NUMBER` is exactly 10 digits when the override is on
- every whitelist/blacklist pattern compiles
- `CDAC_SMS_TIMEOUT` is below the messaging actor time limit
- `CDAC_SMS_VERIFY_RESPONSE` is on but `CDAC_SMS_VERIFY_RESPONSE_CONTAINS` is empty
- warning when the default-number override is enabled
- warning when SSL verification is disabled
- error in production when the override is enabled or SSL verification is off

Checks are silent when the addon is installed but not the active SMS backend, so
local/test environments using `DummySMSBackend` need no CDAC credentials.

---

## 13. Security

- Credentials come from environment/secret injection only; never committed.
- Credentials, hashes, and signatures are never logged or persisted.
- `CDACConfig.__repr__` redacts `password` and `secure_key`.
- TLS ≥ 1.2 with certificate verification on by default; disabling verification
  is rejected in production.
- The default-number override is rejected in production.

---

## 14. Testing

**Unit (no network; DB only where a template/log is needed)**
- hashing: SHA-1 password hash, ISO-8859-1 encoding, SHA-512 signature, trimming, no separators, signature over the final encoded content
- unicode: single/multiple/mixed characters, ASCII in Unicode mode, empty string
- config: default resolution, named gateway, unknown key, missing required keys, redacted repr
- filtering: kill-switch, empty whitelist, `X`/`*`/literal patterns on both lists, override on/off, invalid default number, matching happens pre-prefix
- backend: exact form fields, service type per category/content type, `mobileno` used for every service type, template ID precedence and fallback, mobile prefix, unsupported category
- response: validation order, success codes, error codes classified transient, substring validation pass/fail, `MsgID` parsing, success without a parsable ID, malformed body
- checks: each failure mode; silent when the addon is not the active backend

**Integration (stub broker + mocked CDAC endpoint)**
- `enqueue_sms` → worker → addon → `MessageLog.status=sent` with `provider_message_id`
- transient failure re-enqueues and respects `max_retries`
- permanent failure sets `failed` without re-enqueue
- filtered recipient sets `filtered` without a gateway call
- `id` / `correlation_id` preserved across attempts
- actor time limit > `CDAC_SMS_TIMEOUT`

**Mock gateway assertions:** HTTP method, content type, `username`, `password`
hash, `senderid`, `content`, `smsservicetype`, `mobileno`, `templateid`, `key`
signature, and Unicode entity encoding.

**Isolation test**
- no module under `apps.messaging` imports `addon.*`

**Checks**

```bash
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest
cd src && ruff check . && ruff format .
cd src && python manage.py check
```

---

## 15. Affected files

New (addon):
- `src/addon/__init__.py`
- `src/addon/cdac_sms_gateway/{__init__,apps,backend,client,config,constants,checks,filtering,hashing,response,unicode_encoding}.py`
- `src/addon/cdac_sms_gateway/tests/*`

Modified (messaging, per §10):
- `src/apps/messaging/services.py`
- `src/apps/messaging/tasks.py`
- `src/apps/messaging/models.py` + new migration
- `src/apps/messaging/admin.py`

Modified (wiring and docs):
- `src/config/settings/base.py` — `INSTALLED_APPS`, `MESSAGING_BACKENDS`, `CDAC_SMS_*` block
- `src/config/settings/local.py`, `src/config/settings/test.py` — keep `DummySMSBackend`
- `src/config/settings/production.py` — production guards
- `.env.example`, `.env.prod.example`, `README.md`
- `AGENTS.md` — short "Addon modules" convention note

---

## 16. Acceptance criteria

- [ ] CDAC ships as `src/addon/cdac_sms_gateway/` under a shared `addon` package, with no models or migrations.
- [ ] CDAC is selected purely by `MESSAGING_BACKENDS["sms"]`; no caller changes.
- [ ] No module under `apps.messaging` imports `addon.*`.
- [ ] Deleting the addon directory plus its settings entries leaves messaging working on `DummySMSBackend`.
- [ ] No new messaging service, actor, broker, or audit table is introduced.
- [ ] Gateway credentials load from flat `CDAC_SMS_*` settings.
- [ ] No state-specific conditionals exist in code; a different state is a different `.env`.
- [ ] Form fields, service type, template ID, and mobile prefix are built per §5.
- [ ] `mobileno` is used for every service type.
- [ ] Password uses SHA-1 over ISO-8859-1 bytes; `key` uses SHA-512, lowercase hex, no separators, over the final content.
- [ ] Unicode bodies are converted to numeric HTML entities.
- [ ] Unsupported categories fail permanently; `TRANSACTION` is supported.
- [ ] Whitelist/blacklist support `X` and `*` patterns and match before the prefix is applied.
- [ ] `CDAC_SMS_ENABLED=False` filters without contacting the gateway.
- [ ] Non-production recipient override works and is blocked in production.
- [ ] TLS 1.2+ enforced; verification on by default; override blocked in production.
- [ ] HTTP timeout is configurable and below the actor time limit.
- [ ] Response validation follows the §8 order; every validation failure is transient.
- [ ] CDAC message ID is parsed from `402,MsgID = ...` into `provider_message_id`.
- [ ] Transient failures retry via `MessageLog`; permanent failures and filtered recipients do not.
- [ ] `ENQUEUED` / `FILTERED` / `GATEWAY_REQUEST` / `GATEWAY_RESPONSE` / `SENT` / `FAILED` / `RETRYING` events are logged with `message_id` and `correlation_id`.
- [ ] Credentials, hashes, signatures, and unmasked bodies never appear in logs.
- [ ] `manage.py check` fails on invalid gateway configuration and is silent when the addon is inactive.
- [ ] Unit, integration, and isolation tests pass; Ruff clean.

---

## 17. Design decisions

| Decision | Rationale |
| --- | --- |
| CDAC lives in `addon.cdac_sms_gateway`, not `apps.messaging` | It is a swappable integration, not a domain app. The shared `addon` package gives future integrations a home. |
| The addon imports the contract; messaging never imports the addon | Dependency inversion: both sides depend on the `SMSSender` abstraction, and the concrete class is resolved from a settings string at first send. Removing the addon cannot break messaging. |
| No separate provider registry or resolver | 0009's `MESSAGING_BACKENDS` + `get_backend()` already performs provider selection. A second selector would be a second source of truth. |
| No provider-class / request-type / content-type settings | The backend import path already selects the implementation, and `POST` + urlencoded are fixed properties of the CDAC contract. Settings whose only alternative value is a hard failure are dead configuration. |
| Flat `CDAC_SMS_*` credentials, no per-message gateway selection | One deployment serves one state, so there is never more than one credential set in a process. A nested registry plus a runtime resolver would be unused indirection. State-specific values come from the deployment's environment. |
| No new SMS audit table | `MessageLog` already records recipient, context, rendered output, attempts, status, and timestamps; five new fields cover the rest. |
| Retries stay log-driven in 0009, not Dramatiq middleware | 0009 chose per-template retry policy with a persisted audit trail; forking that into the addon would split the retry story across two modules. |
| Any response-validation failure is transient | Non-success statuses from the gateway are usually load or upstream conditions, which retrying can fix. |
| Permanent failures are limited to config/request errors | Retrying a missing credential, a bad template, or an unsupported category can never succeed. |
| `TRANSACTION` maps like `NOTIFICATION` | The category already exists in `MessageTemplate.Category` and must not be rejected. |
| Content type is derived, not declared | Avoids a model change and a caller burden; an explicit context override remains available. |
| Startup validation via system checks | Matches the documented `manage.py check` workflow and fails fast in containers. |
| `DummySMSBackend` stays the local/test default | Developers and CI need no CDAC credentials. |

## 18. Out of scope

- Additional SMS gateways, provider failover, delivery-status polling, bounce handling.
- Message expiry handling.
- Bulk/campaign sending, analytics, scheduling, rate limiting.
- Runtime or DB-managed gateway configuration and any admin UI for it.
- Email/WhatsApp/push gateways.
- New REST endpoints.
- Packaging addons for external distribution (the structure allows it; not done now).

## 19. Open questions

1. If a deployment ever has to serve multiple states, does it become a second
   deployment, or does this addon grow a credential registry at that point?
2. Do OTP templates need a shorter retry/backoff profile than the global
   `MESSAGING_RETRY_DELAY_BASE`?
3. Should recipient filtering (kill-switch, whitelist/blacklist, override) be
   promoted into `apps.messaging` so every future addon inherits it, rather than
   staying addon-local?
4. Should `addon/` carry its own `README.md` describing the contract every addon
   must satisfy?

## 20. Implementation phases

1. **Messaging amendments** — new exceptions, model fields/migration, task
   failure classification, `correlation_id`, admin + tests.
2. **Addon scaffolding** — `addon/` package, `cdac_sms_gateway` app, `apps.py`,
   `INSTALLED_APPS`, `constants.py`, settings block, env/README docs.
3. **Pure functions** — `hashing.py`, `unicode_encoding.py`, `response.py`,
   `config.py`, `filtering.py` + unit tests.
4. **Gateway** — `client.py`, `backend.py` + unit tests with a mock gateway,
   `checks.py` + check tests.
5. **End-to-end** — stub-broker delivery tests, isolation test, quality checks.
