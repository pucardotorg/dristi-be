# 0013 — CDAC SMS Gateway Addon (`addon_cdac_sms_gateway`)

## Status

Proposed

> **Reframing note.** An earlier draft of this document described CDAC as a
> standalone *messaging service* with its own request model, provider registry,
> Dramatiq actor, retry loop, audit store, and `SMS_*` configuration namespace.
> That duplicated [0009 — Messaging Module](0009-messaging.md), which is already
> implemented in `src/apps/messaging/`.
>
> This document is reframed twice over:
>
> 1. **CDAC is a *gateway*, not a messaging service** — it owns the CDAC wire
>    protocol and nothing else. Orchestration, templating, queuing, retries, and
>    audit remain owned by 0009.
> 2. **The gateway ships as a separate top-level module,
>    `addon_cdac_sms_gateway`** — not as a subpackage of `apps.messaging`. The
>    messaging module consumes it purely through the `MESSAGING_BACKENDS`
>    setting in `config/settings/base.py`.

## Context

Dristi already has a channel-agnostic messaging module (0009):

- `MessageTemplate` / `MessageLog` models
- `MessageTemplateRenderer` → `RenderedMessage`
- `BaseMessageSender` → `SMSSender` → `ConfiguredBackendSender` with backend
  lookup via `settings.MESSAGING_BACKENDS`
- `send_message` Dramatiq actor (Redis broker) with log-driven retries
- A development-only `DummySMSBackend` that POSTs to an HTTP endpoint

0009 explicitly anticipated this shape: *"the concrete delivery implementation
lives in an external Django app that Dristi configures at runtime."*
`addon_cdac_sms_gateway` is the first real instance of such an app. It is
vendored in this repository for convenience, but it is structured so it could be
extracted into its own distributable package without touching `apps.messaging`.

## Goals

- Ship `CDACSMSBackend` in a standalone, removable module that satisfies 0009's
  SMS sender contract.
- Keep every CDAC-specific detail (hashing, signature, service types, Unicode
  encoding, form fields, TLS) inside `addon_cdac_sms_gateway`.
- Enforce a one-way dependency: the addon imports from `apps.messaging`;
  `apps.messaging` never imports the addon.
- Support per-state/tenant gateway credentials through configuration, with no
  state-specific branching in code.
- Reuse 0009's queuing, retry, status, and audit machinery without forking it.
- Keep each gateway concern independently unit-testable.

## Non-goals

- A second messaging service, provider registry, or Dramatiq actor.
- A new SMS request model or SMS audit table (`MessageLog` is the audit store).
- Any models or migrations in the addon.
- Kafka, delivery-status polling, provider failover, or campaign management.
- Any REST API surface. This iteration adds no endpoints, so
  [0000 — API Coding Spec](0000-api-coding-spec.md) applies only as a style
  constraint (no Pydantic, thin logic layers, explicit tests, Ruff, system
  checks). If an operational status endpoint is added later it must carry the
  standard `meta` envelope and its own Swagger tag.

---

## 1. Module placement and dependency direction

```text
src/
├── apps/                          # Dristi domain apps
│   ├── core/
│   ├── messaging/                 # 0009 — knows nothing about CDAC
│   └── ...
├── addon_cdac_sms_gateway/        # THIS SPEC — pluggable gateway addon
└── config/
    └── settings/base.py           # the only wiring point
```

The addon is a top-level package (sibling of `apps/`), not `apps.addon_...`.
This is a deliberate, documented exception to the `AGENTS.md` rule that apps
live under `src/apps/<app>/` with the dotted path `apps.<app>`: the addon is not
a Dristi domain app, it is a swappable integration. `AGENTS.md` should be
amended with a short "Addon modules" note when this lands.

Dependency rules:

```text
addon_cdac_sms_gateway  ---- imports ---->  apps.messaging (senders.base, services)
apps.messaging          --- never imports -->  addon_cdac_sms_gateway
config.settings.base    ---- references --->  "addon_cdac_sms_gateway.backend.CDACSMSBackend"
```

`apps.messaging` may only reference the addon as a **string** in
`MESSAGING_BACKENDS`, resolved lazily by the existing
`ConfiguredBackendSender._get_configured_backend()` (`import_string`). Deleting
the addon directory and the two settings blocks must leave a working messaging
module with the dummy SMS backend.

Django registration:

```python
# config/settings/base.py
INSTALLED_APPS = [
    ...
    "apps.messaging",
    "apps.locations",
    # Addons
    "addon_cdac_sms_gateway",
]
```

The addon is an installed app only so it can register system checks (§14) and
expose its own app label in logs. It contributes no models, migrations,
templates, URLs, admin, or middleware.

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
                                                     [addon_cdac_sms_gateway]
                                                                 |
                                            +--------------------+--------------------+
                                            |                    |                    |
                                            v                    v                    v
                                   recipient filtering   request building     response classification
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
                                                      HTTP POST (urlencoded, TLS)
                                                                 |
                                                                 v
                                                           CDAC gateway
```

The addon is entered exactly once per delivery attempt, synchronously, inside
the Dramatiq worker. It never enqueues, never writes to `MessageLog`, and never
decides retry policy.

---

## 3. Responsibility boundary

| Concern | Owner |
| --- | --- |
| Template resolution, rendering, context validation | `apps.messaging.services` |
| `MessageLog` lifecycle, `attempt_count`, statuses, timestamps | `apps.messaging.tasks` |
| Enqueue, Redis broker, backoff, retry eligibility | `apps.messaging.tasks` |
| Channel dispatch / backend lookup | `apps.messaging.senders` |
| Sender contract and exception vocabulary | `apps.messaging` (public API) |
| Gateway credential + option resolution per state | addon `config.py` |
| Recipient filtering and non-production override | addon `filtering.py` |
| CDAC service-type mapping, template ID, mobile prefix | addon `backend.py` |
| Password hash, request signature | addon `hashing.py` |
| Unicode content encoding | addon `unicode_encoding.py` |
| Form data, TLS, timeout, HTTP POST | addon `client.py` |
| HTTP/body validation and failure classification | addon `response.py` |

Rule of thumb: **if removing the CDAC integration tomorrow would delete the
code, it belongs in the addon. Otherwise it belongs in `apps.messaging`.**

---

## 4. Terminology mapping

The earlier draft invented a parallel vocabulary. It maps onto existing
constructs as follows, and the new terms are dropped:

| Earlier draft | Reframed equivalent |
| --- | --- |
| Messaging Service | `apps.messaging` (0009) — unchanged |
| SMS Request model | `MessageLog` row + `RenderedMessage` |
| `requestId` | `MessageLog.id` (UUID) |
| `correlationId` | new `MessageLog.correlation_id` field |
| Provider interface | existing `BaseMessageSender` / `SMSSender` |
| Provider Resolver | existing `get_backend()` + `MESSAGING_BACKENDS` |
| CDAC Provider + CDAC Client | `CDACSMSBackend` + `CDACClient` (addon) |
| `send_sms_task` actor | existing `send_message` actor |
| `category` | `MessageTemplate.category` |
| `contentType` | derived per message (see §7) |
| `mobileNumber` | `recipient["phone_number"]` |
| `message` | `MessageLog.rendered_content` |
| `templateId` | `MessageTemplate.provider_template_id` (new) |
| Dedicated SMS audit table | `MessageLog` |
| `SMS_*` settings | `CDAC_SMS_*` settings (addon-owned namespace) |

---

## 5. Addon layout

```text
src/addon_cdac_sms_gateway/
├── __init__.py                  # default_app_config-free; exports nothing heavy
├── apps.py                      # AppConfig(name="addon_cdac_sms_gateway")
├── backend.py                   # CDACSMSBackend(SMSSender)
├── client.py                    # CDACClient (HTTP/TLS/timeout)
├── config.py                    # CDACConfig, resolve_config(), validation
├── constants.py                 # service types, error codes
├── checks.py                    # Django system checks
├── filtering.py                 # whitelist/blacklist/default-number override
├── hashing.py                   # password hash + request signature
├── response.py                  # response validation + classification
├── unicode_encoding.py          # numeric HTML-entity encoding
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_hashing.py
    ├── test_unicode.py
    ├── test_filtering.py
    ├── test_response.py
    ├── test_backend.py          # form fields, service type, template, prefix
    ├── test_checks.py
    └── test_delivery.py         # stub-broker end-to-end with mocked gateway
```

Addon tests live with the addon, not in `apps/messaging/tests/`. `pytest` is run
from `src/`, so they are collected automatically.

---

## 6. Gateway contract

The addon implements the existing sender contract and nothing more:

```python
# addon_cdac_sms_gateway/backend.py
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
    "sms": "addon_cdac_sms_gateway.backend.CDACSMSBackend",
}
```

Recommended per-environment default: `DummySMSBackend` in
`config.settings.local` and `config.settings.test`, `CDACSMSBackend` in
staging/production.

---

## 7. Configuration

### 7.1 Namespace

Addon-owned settings use the `CDAC_SMS_` prefix, keeping them visibly distinct
from `MESSAGING_*` (owned by 0009). They are declared in
`config/settings/base.py` in a dedicated block so the whole integration can be
removed by deleting that block plus the `INSTALLED_APPS` and
`MESSAGING_BACKENDS` entries.

`SMS_PROVIDER_CLASS`, `SMS_PROVIDER_REQUEST_TYPE`, and
`SMS_PROVIDER_CONTENT_TYPE` from the earlier draft are removed: the backend
import path already selects the implementation, and the HTTP method and content
type are fixed properties of the CDAC contract owned by `CDACClient`.

### 7.2 Gateway credentials (per state/tenant)

```python
# config/settings/base.py — CDAC SMS gateway addon
CDAC_SMS_GATEWAYS = {
    "default": {
        "url": env("CDAC_SMS_URL", default=""),
        "username": env("CDAC_SMS_USERNAME", default=""),
        "password": env("CDAC_SMS_PASSWORD", default=""),
        "sender_id": env("CDAC_SMS_SENDER_ID", default=""),
        "secure_key": env("CDAC_SMS_SECURE_KEY", default=""),
        "template_id": env("CDAC_SMS_TEMPLATE_ID", default=""),
        "mobile_prefix": env("CDAC_SMS_MOBILE_PREFIX", default=""),
    },
}
```

| Key | Required | Notes |
| --- | --- | --- |
| `url` | yes | e.g. `https://msdgweb.mgov.gov.in/esms/sendsmsrequestDLT` |
| `username` | yes | — |
| `password` | yes | plaintext in config; hashed before transmission |
| `sender_id` | yes | — |
| `secure_key` | yes | never logged |
| `template_id` | no | fallback DLT template ID |
| `mobile_prefix` | no | e.g. `91` |

Additional states are extra keys in the same dict, supplied by the deployment.
No code change is required, and no `if state == ...` branching is permitted.

### 7.3 Transport and validation options

| Setting | Type | Default |
| --- | --- | --- |
| `CDAC_SMS_ENABLED` | bool | `True` |
| `CDAC_SMS_TIMEOUT` | int (s) | `30` |
| `CDAC_SMS_VERIFY_SSL` | bool | `True` |
| `CDAC_SMS_SUCCESS_CODES` | list[int] | `[200, 201, 202]` |
| `CDAC_SMS_ERROR_CODES` | list[int] | `[]` |
| `CDAC_SMS_VERIFY_RESPONSE` | bool | `False` |
| `CDAC_SMS_VERIFY_RESPONSE_CONTAINS` | str | `""` |
| `CDAC_SMS_PRINT_RESPONSE` | bool | `False` |

### 7.4 Recipient policy

| Setting | Type | Default |
| --- | --- | --- |
| `CDAC_SMS_WHITELIST_NUMBERS` | list[str] | `[]` (empty = allow all) |
| `CDAC_SMS_BLACKLIST_NUMBERS` | list[str] | `[]` |
| `CDAC_SMS_USE_DEFAULT_NUMBER` | bool | `False` |
| `CDAC_SMS_DEFAULT_NUMBER` | str | `""` (exactly 10 digits when used) |

`CDAC_SMS_USE_DEFAULT_NUMBER=True` and `CDAC_SMS_VERIFY_SSL=False` are rejected
by `config/settings/production.py`.

Every setting is documented in `.env.example`, `.env.prod.example`, and
`README.md`, per `AGENTS.md`.

### 7.5 Gateway selection per message

```text
context["sms_gateway"]  (optional, e.g. "kerala")
        |
        +-- present and known ---> CDAC_SMS_GATEWAYS[key]
        |
        +-- absent --------------> CDAC_SMS_GATEWAYS["default"]
        |
        +-- present, unknown ----> MessagePermanentError(INVALID_CONFIGURATION)
```

The key travels in the message context, so tenancy stays a caller concern and
`apps.messaging` needs no tenant awareness. When 0008 (Organization) lands, the
organization/location record can supply the key without touching the addon.

---

## 8. Request construction

| CDAC form field | Source |
| --- | --- |
| `username` | gateway config |
| `password` | SHA-1 of configured password (§9) |
| `senderid` | gateway config |
| `content` | rendered body, Unicode-encoded when applicable (§10) |
| `smsservicetype` | category + content type mapping (below) |
| `mobileno` | `mobile_prefix` + `recipient["phone_number"]` |
| `key` | SHA-512 request signature (§9) |
| `templateid` | `MessageTemplate.provider_template_id` or config fallback |

Fixed by `CDACClient`: `POST`,
`Content-Type: application/x-www-form-urlencoded`.

### Service type mapping

| `MessageTemplate.category` | Content type | `smsservicetype` |
| --- | --- | --- |
| `OTP` | any | `otpmsg` |
| `NOTIFICATION` | text | `singlemsg` |
| `NOTIFICATION` | unicode | `unicodemsg` |
| `TRANSACTION` | text | `singlemsg` |
| `TRANSACTION` | unicode | `unicodemsg` |
| anything else | any | `MessagePermanentError(UNSUPPORTED_CATEGORY)` |

`TRANSACTION` is included because it already exists in
`MessageTemplate.Category`; the earlier draft omitted it.

### Content type determination

The addon derives Unicode mode from the rendered body (any code point > 127)
rather than requiring callers to declare it. An explicit override may be passed
via `context["sms_content_type"] = "unicode" | "text"`. This avoids a model
change and keeps `RenderedMessage.content_type` (a MIME type used by email)
unambiguous.

### Template ID resolution

```text
MessageTemplate.provider_template_id   (new field, blank allowed)
        |
        +-- non-empty ---> use it
        |
        +-- empty -------> gateway config template_id
                                |
                                +-- empty ---> send without templateid
```

### Mobile number

```text
prefix "91" + "9876543210" -> "919876543210"
```

`apps.messaging` keeps storing the caller-supplied number in
`MessageLog.recipient`; the prefix is applied only when building the CDAC
request.

---

## 9. Hashing and signature

```text
password --> ISO-8859-1 bytes --> SHA-1 --> lowercase hex --> form field "password"

username.strip() + sender_id.strip() + content.strip() + secure_key.strip()
        --> UTF-8 bytes --> SHA-512 --> lowercase hex --> form field "key"
```

No separators between signature components. Function names must describe the
real algorithm (`generate_password_hash`, `generate_signature`) — not a wrong
algorithm name inherited from the reference implementation.

---

## 10. Unicode encoding

Each code point becomes a numeric HTML entity:

```text
"नमस्ते" -> "&#2344;&#2350;&#2360;&#2381;&#2340;&#2375;"
```

ASCII characters are encoded the same way when Unicode mode is active, so the
function stays pure and independently unit-testable.

---

## 11. Recipient filtering

```text
resolved recipient
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
      +-- rejected --> RecipientFilteredError
      |
      v
CDAC request
```

Filtering lives in the addon because the policy settings are addon-owned and
gateway-specific. A filtered recipient is **not** a gateway failure:
`apps.messaging` records `MessageLog.status = filtered` and does not retry.

---

## 12. Response handling and failure classification

`CDACClient.post()` returns `(status_code, body)` and makes no business
decision. `response.classify(status_code, body)` returns one of `SUCCESS`,
`PERMANENT`, `TRANSIENT`:

- status in `CDAC_SMS_ERROR_CODES` → `PERMANENT`
- status not in `CDAC_SMS_SUCCESS_CODES` → `TRANSIENT`
- `CDAC_SMS_VERIFY_RESPONSE` enabled and body lacks
  `CDAC_SMS_VERIFY_RESPONSE_CONTAINS` → `TRANSIENT`
  (`RESPONSE_VALIDATION_FAILED`)
- otherwise `SUCCESS`; the CDAC message ID is parsed from bodies shaped like
  `402,MsgID = <id>msdgsms` and returned as `provider_message_id`

Transport errors map to `TRANSIENT`: `GATEWAY_TIMEOUT`,
`GATEWAY_CONNECTION_ERROR`, `GATEWAY_UNAVAILABLE`.

Error codes raised by the addon (defined in `constants.py`):

```text
PERMANENT: INVALID_REQUEST, INVALID_RECIPIENT, INVALID_CONFIGURATION,
           UNSUPPORTED_CATEGORY, UNSUPPORTED_CONTENT_TYPE
TRANSIENT: GATEWAY_TIMEOUT, GATEWAY_CONNECTION_ERROR, GATEWAY_UNAVAILABLE,
           GATEWAY_ERROR, RESPONSE_VALIDATION_FAILED
```

---

## 13. Retry (owned by `apps.messaging`)

The addon does **not** implement retries, backoff, or Dramatiq retry
middleware. 0009 deliberately keeps `send_message` at `max_retries=0` and drives
retries from persisted `MessageLog` state for auditability; that design stands.

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

The actor's `time_limit` is set explicitly and must exceed `CDAC_SMS_TIMEOUT` so
an HTTP timeout surfaces as a clean transient failure rather than a worker kill.

---

## 14. Changes required in `apps.messaging` (0009 amendments)

These live in the messaging module because they are gateway-agnostic. Any future
addon benefits from them.

`services.py` — extend the public exception/error vocabulary:
- `MessagePermanentError(MessageSendError)` — never retried
- `RecipientFilteredError(Exception)` — suppressed by policy, not a failure

`tasks.py`
- classify the three outcomes above in `_record_failure()`
- accept and propagate `correlation_id` through `enqueue_sms()`
- set an explicit actor `time_limit`

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
addon itself contributes no models or migrations.

---

## 15. Startup validation

Validation runs through the Django system check framework, registered in the
addon's `AppConfig.ready()`, so failures appear in `python manage.py check` and
at container startup rather than on first send.

Checks (error level, only when `CDACSMSBackend` is the configured SMS backend
and `CDAC_SMS_ENABLED` is true):

- `CDAC_SMS_GATEWAYS` is non-empty and contains `default`
- every gateway entry has `url`, `username`, `password`, `sender_id`, `secure_key`
- `url` is an absolute `https://` URL
- `CDAC_SMS_DEFAULT_NUMBER` is exactly 10 digits when the override is on
- `CDAC_SMS_TIMEOUT` is below the messaging actor time limit
- warning when the default-number override is enabled
- error in production when the override is enabled or SSL verification is off

Checks are silent when the addon is installed but not the active SMS backend, so
local/test environments using `DummySMSBackend` do not need CDAC credentials.

---

## 16. Logging and observability

One structured log line per attempt, emitted by the addon under the
`addon_cdac_sms_gateway` logger:

```text
message_id=<MessageLog.id> correlation_id=... gateway=cdac gateway_key=default
category=OTP content_type=unicode attempt=1 status=sent gateway_status=200
```

Never logged, in any mode: plaintext password, password hash, secure key,
request signature, full form data. `CDAC_SMS_PRINT_RESPONSE` may log the status
code and body with credentials redacted; it defaults to off.

Monitoring uses these logs plus `MessageLog` aggregates (counts by `status`,
`failure_code`, `attempt_count`; latency from `created_at` → `sent_at`). No
Kafka health topic and no bespoke metrics backend in this iteration.

---

## 17. Security

- Credentials come from environment/secret injection only; never committed.
- Credentials, hashes, and signatures are never logged or persisted.
- `CDACConfig.__repr__` redacts `password` and `secure_key`.
- TLS ≥ 1.2 with certificate verification on by default; disabling verification
  is rejected in production.
- Default-number override is rejected in production.

---

## 18. Testing

**Unit (no network; DB only where a template/log is needed)**
- hashing: SHA-1 password hash, ISO-8859-1 encoding, SHA-512 signature, trimming, no separators
- unicode: single/multiple/mixed characters, ASCII in Unicode mode, empty string
- config: default resolution, named gateway, unknown key, missing required keys, redacted repr
- filtering: empty whitelist, whitelist hit/miss, blacklist hit, override on/off, invalid default number
- backend: exact form fields, service type per category/content type, template ID precedence and fallback, mobile prefix, unsupported category
- response: success codes, configured error codes, substring validation pass/fail, message-ID parsing, malformed body
- checks: each failure mode; silent when the addon is not the active backend

**Integration (stub broker + mocked CDAC endpoint)**
- `enqueue_sms` → worker → addon → `MessageLog.status=sent` with `provider_message_id`
- transient failure re-enqueues and respects `max_retries`
- permanent failure sets `failed` without re-enqueue
- filtered recipient sets `filtered` without a gateway call
- `id` / `correlation_id` preserved across attempts
- actor time limit > `CDAC_SMS_TIMEOUT`

**Isolation test**
- with `MESSAGING_BACKENDS["sms"] = DummySMSBackend`, no module under
  `apps.messaging` imports `addon_cdac_sms_gateway`.

**Checks**

```bash
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest
cd src && ruff check . && ruff format .
cd src && python manage.py check
```

---

## 19. Affected files

New (addon):
- `src/addon_cdac_sms_gateway/{__init__,apps,backend,client,config,constants,checks,filtering,hashing,response,unicode_encoding}.py`
- `src/addon_cdac_sms_gateway/tests/*`

Modified (messaging, per §14):
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

## 20. Acceptance criteria

- [ ] CDAC ships as `src/addon_cdac_sms_gateway/`, a standalone installed app with no models or migrations.
- [ ] CDAC is selected purely by `MESSAGING_BACKENDS["sms"]`; no caller changes.
- [ ] No module under `apps.messaging` imports the addon.
- [ ] Deleting the addon directory plus its settings entries leaves messaging working on `DummySMSBackend`.
- [ ] No new messaging service, actor, broker, or audit table is introduced.
- [ ] Gateway credentials resolve per state from `CDAC_SMS_GATEWAYS` with a `default`.
- [ ] No state-specific conditionals exist in code.
- [ ] Form fields, service type, template ID, and mobile prefix are correct.
- [ ] Password uses SHA-1 over ISO-8859-1 bytes; `key` uses SHA-512, lowercase hex, no separators.
- [ ] Unicode bodies are converted to numeric HTML entities.
- [ ] Unsupported categories fail permanently.
- [ ] Whitelist, blacklist, and non-production override behave per §11.
- [ ] TLS verification on by default; override blocked in production.
- [ ] HTTP timeout configurable and below the actor time limit.
- [ ] Transient failures retry via `MessageLog`; permanent failures and filtered recipients do not.
- [ ] Response validation is configurable; CDAC message ID stored as `provider_message_id`.
- [ ] `MessageLog.id` and `correlation_id` appear in every attempt's logs.
- [ ] Credentials, hashes, and signatures never appear in logs.
- [ ] `manage.py check` fails on invalid gateway configuration and is silent when the addon is inactive.
- [ ] Unit, integration, and isolation tests pass; Ruff clean.

---

## 21. Resolved decisions

The earlier draft's open questions are resolved by the gateway-addon framing:

| Question | Decision |
| --- | --- |
| Where does CDAC live? | Standalone top-level module `addon_cdac_sms_gateway`, wired only through settings. |
| State identification | Optional `context["sms_gateway"]` key → `CDAC_SMS_GATEWAYS`, `default` fallback. Organization-driven once 0008 lands. |
| Configuration storage | Django settings from env/secret injection. No DB-stored credentials. |
| Multiple states per deployment | Supported by config shape; resolved per message. |
| Provider abstraction | Already exists (`BaseMessageSender`). No new abstraction. |
| Persistent audit | `MessageLog` plus new fields. No dedicated table. |
| Retry strategy | 0009's log-driven exponential backoff; per-template `max_retries`. |
| Expiry handling | Out of scope. |
| Backup provider / failover | Out of scope. |
| Template strategy | Per-template `provider_template_id`, gateway config fallback. |
| Environment defaults | `DummySMSBackend` in local/test; CDAC in staging/production. |

## 22. Out of scope

- Kafka, additional SMS gateways, failover, delivery-status polling.
- Bulk/campaign sending, analytics, scheduling, rate limiting.
- Runtime/DB-managed gateway configuration and any admin UI for it.
- Email/WhatsApp/push gateways.
- New REST endpoints.
- Packaging the addon for PyPI distribution (structure allows it; not done now).

## 23. Remaining open questions

1. Should `CDAC_SMS_GATEWAYS` entries eventually be keyed by
   Organization/Location records (0008) instead of free-form strings?
2. Do OTP templates need a shorter retry/backoff profile than the global
   `MESSAGING_RETRY_DELAY_BASE`?
3. Should recipient filtering (whitelist/blacklist/override) eventually be
   promoted into `apps.messaging` so every future gateway inherits it, rather
   than staying addon-local?

## 24. Implementation phases

1. **Messaging amendments** — new exceptions, model fields/migration, task
   failure classification, `correlation_id`, admin (§14) + tests.
2. **Addon scaffolding** — package, `apps.py`, `INSTALLED_APPS`, `constants.py`,
   settings block, env/README docs.
3. **Pure functions** — `hashing.py`, `unicode_encoding.py`, `response.py`,
   `config.py`, `filtering.py` + unit tests.
4. **Gateway** — `client.py`, `backend.py` + unit tests with mocked HTTP,
   `checks.py` + check tests.
5. **End-to-end** — stub-broker delivery tests, isolation test, quality checks.
