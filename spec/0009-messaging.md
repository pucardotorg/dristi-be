# 0009 — Messaging Module

## Status

Proposed

## Context

Dristi needs a centralized way to define, manage, and dispatch notifications across multiple channels (email, SMS, push). Message templates are stored in the database and rendered at send time. The module defines a clean contract between Dristi and any external Django app that provides the actual transport (SMTP provider, SMS gateway, FCM/APNs, etc.).

Template scoping by organization or location is not included in this iteration and is listed as a future TODO.

## Goals

- Provide a reusable `messaging` app under `apps.messaging`.
- Store message templates in the database so non-developers can manage copy.
- Support template variables in both subject and body, rendered at send time.
- Define an abstract sender interface for email, SMS, and push notifications.
- Dispatch every message asynchronously through Dramatiq tasks.
- Let the concrete delivery implementation live in an external Django app that Dristi configures at runtime.

## Non-goals

- Building a message delivery status tracker or delivery receipts UI.
- Real-time / WebSocket notifications in this iteration.
- Multi-language template support in the initial version.

## Proposed changes

### 1. App layout

Create `apps.messaging` with the following structure:

```
src/apps/messaging/
├── __init__.py
├── apps.py
├── models.py
├── tasks.py
├── services.py
├── admin.py
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   └── test_tasks.py
└── senders/
    ├── __init__.py
    ├── base.py
    ├── email.py
    ├── push.py
    └── sms.py
```

Register `apps.messaging` in `src/config/settings/base.py` under `INSTALLED_APPS`.

### 2. `MessageTemplate` model

Location: `apps.messaging.models`

Stores templated content and metadata for outbound messages.

| Field | Type | Notes |
|-------|------|-------|
| `message_key` | `CharField(max_length=255)` | Stable identifier used by code to trigger a template. Example: `case_filing_submitted`. |
| `message_type` | `CharField(max_length=50)` | One of `email`, `sms`, `push`. |
| `subject` | `CharField(max_length=512, blank=True)` | Subject line. Templatized for all message types where a subject is relevant. Required for `email`, optional/blank for `sms` and `push`. |
| `content` | `TextField()` | Message body. Templatized. |
| `data_schema` | `JSONField(default=dict, blank=True)` | JSON Schema describing the context object that must be supplied when rendering the template. |
| `priority` | `CharField(max_length=20, default="MEDIUM")` | One of `HIGH`, `MEDIUM`, `LOW`. May be used by workers for queue ordering or preferential processing. |
| `category` | `CharField(max_length=20, default="NOTIFICATION")` | One of `OTP`, `NOTIFICATION`, `TRANSACTION`. Lets backends apply channel-specific routing or handling rules. |
| `max_retries` | `PositiveSmallIntegerField(default=0)` | Maximum number of retry attempts after the first failure. `0` means no retries. |
| `is_active` | `BooleanField(default=True)` | Allows soft-disabling a template without deleting it. |

Constraints:
- Unique together: (`message_key`, `message_type`).
- `subject` must be non-empty when `message_type == "email"`.

Validation:
- `data_schema` must be a valid JSON Schema (validated via `jsonschema` or lightweight format check).
- `message_key` must match `^[a-z][a-z0-9_]*$` (snake_case).
- `message_type` must be one of the supported choices.

### 3. `MessageLog` model

Location: `apps.messaging.models`

Keeps a persistent record of every message that is dispatched, including its status, retry count, and any failure details.

| Field | Type | Notes |
|-------|------|-------|
| `template` | `ForeignKey(MessageTemplate, on_delete=models.SET_NULL, null=True, blank=True)` | The template used for this message. Nullable so history is retained if the template is deleted. |
| `message_type` | `CharField(max_length=50)` | Denormalized from the template: `email`, `sms`, or `push`. |
| `message_key` | `CharField(max_length=255)` | Denormalized template key for querying without joining. |
| `recipient` | `JSONField()` | Recipient details as provided at enqueue time. |
| `context` | `JSONField(default=dict)` | Render context snapshot used for this attempt. |
| `rendered_subject` | `CharField(max_length=512, blank=True)` | Rendered subject line. |
| `rendered_content` | `TextField(blank=True)` | Rendered message body. |
| `status` | `CharField(max_length=50)` | One of `pending`, `sent`, `failed`, `cancelled`. |
| `attempt_count` | `PositiveSmallIntegerField(default=0)` | Number of delivery attempts made so far. |
| `max_retries` | `PositiveSmallIntegerField(default=0)` | Snapshot of `template.max_retries` at enqueue time. |
| `provider_message_id` | `CharField(max_length=255, blank=True)` | Optional ID returned by the backend provider. |
| `error_message` | `TextField(blank=True)` | Last recorded error, if any. |
| `sent_at` | `DateTimeField(null=True, blank=True)` | Timestamp when the message reached `sent` status. |
| `failed_at` | `DateTimeField(null=True, blank=True)` | Timestamp of the most recent failure. |

Behavior:
- A `MessageLog` row is created as soon as a message is enqueued (`status=pending`, `attempt_count=0`).
- Each delivery attempt increments `attempt_count`.
- On success the row moves to `status=sent` and records `sent_at` and `provider_message_id` if available.
- On failure the row records `failed_at` and `error_message`.
- If `attempt_count > max_retries`, the row moves to `status=failed` and no further retries are attempted.
- A helper method `can_retry()` returns `True` when `status != "sent"` and `attempt_count <= max_retries`.

### Retry policy design note

`max_retries` is stored on `MessageTemplate` and snapshotted into `MessageLog` at enqueue time rather than relying solely on Dramatiq's task-level retry configuration. This choice was made because:

- **Per-template reliability:** different message types have different delivery requirements. A court-filing notification may warrant several retries, while a low-priority informational message may not.
- **Operational visibility:** the exact retry policy that applied to a given send is preserved in the audit log, even if the template is later changed.
- **Self-contained audit:** `MessageLog.attempt_count` and `MessageLog.max_retries` make it easy to see why a message failed without inspecting Dramatiq internals.

The `send_message` Dramatiq actor is decorated with `max_retries=0` so that Dramatiq's built-in retry middleware never re-runs it; all retry decisions are driven by the task based on the persisted log state.

### 4. Template rendering

Location: `apps.messaging.services`

Provide a `MessageTemplateRenderer` service:

```python
class MessageTemplateRenderer:
    template_engine: str = "jinja2"  # or "mustache"

    def render(self, template: MessageTemplate, context: dict) -> RenderedMessage:
        ...
```

Behavior:
1. Validate `context` against `template.data_schema`.
2. Render `subject` and `content` using the configured engine.
3. Return a `RenderedMessage` dataclass containing `message_type`, `recipient`, `subject`, `body`, `category` (copied from the template), and any channel-specific payload fields.

Supported engines:
- **Jinja2** — default. Sandboxed if possible; autoescape enabled.
- **Mustache / pystache** — opt-in via settings (`MESSAGING_TEMPLATE_ENGINE = "mustache"`).

If rendering fails, raise a domain exception (`MessageRenderError`) that the caller or task can handle.

### 5. Message template resolution

Location: `apps.messaging.services`

Resolve a template by exact match on (`message_key`, `message_type`). Only active templates are considered. If no template is found, raise `MessageTemplateNotFound`.

Location/organization scoping is intentionally left out of this iteration and is tracked as a future TODO.

### 6. Abstract sender interface

Location: `apps.messaging.senders.base`

```python
class BaseMessageSender(ABC):
    message_type: ClassVar[str]

    @abstractmethod
    def send(self, rendered_message: RenderedMessage) -> None:
        """Concrete implementations deliver the message through their provider."""
        ...
```

Concrete abstract subclasses (provided by Dristi as hooks):

- `apps.messaging.senders.email.EmailSender`
- `apps.messaging.senders.sms.SMSSender`
- `apps.messaging.senders.push.PushSender`

Each subclass only validates that `rendered_message.message_type` matches its channel and then delegates to the configured backend.

### 7. Sender backend registration

Location: `apps.messaging.senders`

Dristi does not ship with a real provider. Instead, it looks up the backend class from Django settings:

```python
MESSAGING_BACKENDS = {
    "email": "apps.messaging.senders.email.SMTPEmailBackend",
    "sms": "apps.messaging.senders.sms.DummySMSBackend",
}
```

Sender classes are also configurable through `MESSAGING_SENDERS`. Built-in defaults are provided for `email`, `sms`, and `push`, but external Django apps can override an existing channel or register entirely new channels without modifying this module:

```python
MESSAGING_SENDERS = {
    "email": "external_app.senders.MyEmailSender",
    "voice": "external_app.senders.VoiceSender",
}
```

If `MESSAGING_SENDERS` does not contain a channel, the registry falls back to the built-in sender for that channel. Unknown channels raise `MessageBackendNotConfigured`.

Push notification backend is intentionally not implemented in this iteration. Attempting to send a push message raises `NotImplementedError`.

At import/use time the backend class is lazily imported and instantiated. The backend class must inherit from the matching `BaseMessageSender` subclass and implement `send()`.

If a channel is referenced without a configured backend, calling `send()` raises `MessageBackendNotConfigured`.

### 7.1 Built-in dummy SMS backend

Location: `apps.messaging.senders.sms`

A development/testing backend that POSTs the rendered SMS payload to a configurable HTTP endpoint instead of a real SMS gateway.

Configuration (Django settings):

```python
MESSAGING_DUMMY_SMS_ENDPOINT = "https://httpbin.org/post"  # required for this backend
```

Backend import path:

```python
MESSAGING_BACKENDS = {
    "sms": "apps.messaging.senders.sms.DummySMSBackend",
}
```

Behavior:
- Validates that `rendered_message.recipient` contains `phone_number`.
- POSTs a JSON payload to `MESSAGING_DUMMY_SMS_ENDPOINT` with:
  - `phone_number`
  - `message` (rendered content)
  - `message_key`
  - `category` (from the template)
  - `provider_message_id` (a generated UUID for tracing)
- Treats HTTP 2xx responses as success.
- Raises `MessageSendError` on network errors or non-2xx responses.
- Does not retry on its own; relies on the Dramatiq task retry mechanism.

### 7.2 Built-in SMTP email backend

Location: `apps.messaging.senders.email`

A production-ready backend that sends email through an SMTP server using Django's email facilities or `smtplib`.

Configuration (Django settings):

```python
MESSAGING_EMAIL_BACKEND = "smtp"  # or "django" to use Django's configured email backend
MESSAGING_EMAIL_HOST = "smtp.example.com"
MESSAGING_EMAIL_PORT = 587
MESSAGING_EMAIL_HOST_USER = "notifications@example.com"
MESSAGING_EMAIL_HOST_PASSWORD = "..."
MESSAGING_EMAIL_USE_TLS = True
MESSAGING_EMAIL_USE_SSL = False
MESSAGING_EMAIL_DEFAULT_FROM = "Dristi <notifications@example.com>"
MESSAGING_EMAIL_TIMEOUT = 30
```

Backend import path:

```python
MESSAGING_BACKENDS = {
    "email": "apps.messaging.senders.email.SMTPEmailBackend",
}
```

Behavior:
- Validates that `rendered_message.recipient` contains `email`.
- Builds an email message with `rendered_message.subject` and `rendered_message.content`.
- Sends the message via the configured SMTP server.
- Records any provider message ID or SMTP response available.
- Raises `MessageSendError` on SMTP or connection errors.
- Supports both plain-text and HTML content if `rendered_message` provides a content type; default is `text/plain`.

### 7.3 Push sender (not implemented)

Location: `apps.messaging.senders.push`

The `PushSender` class is defined as a placeholder to preserve the abstract interface, but its `send()` method raises `NotImplementedError`.

```python
class PushSender(BaseMessageSender):
    message_type = "push"

    def send(self, rendered_message: RenderedMessage) -> None:
        raise NotImplementedError("Push notification delivery is not implemented yet.")
```

Behavior:
- `enqueue_push(...)` immediately raises `NotImplementedError`.
- Any `MessageLog` created for `message_type="push"` should be marked `status=failed` with `error_message` set to a not-implemented message.
- No Dramatiq message is enqueued for push notifications.

Push support is tracked as a future TODO.

### 8. Async dispatch via Dramatiq

Location: `apps.messaging.tasks`

```python
@actor(max_retries=0)
def send_message(log_id: int):
    ...
```

Flow:
1. Load the `MessageLog` row by `log_id`.
2. Resolve the `MessageTemplate` using `message_key` and `message_type`.
3. Render subject and content with the stored `context`.
4. Save the rendered output back to the log row.
5. Increment `attempt_count`.
6. Instantiate the backend sender for `message_type` and call `sender.send(rendered_message)`.
7. On success: set `status=sent`, record `sent_at` and `provider_message_id` if returned.
8. On failure: record `failed_at` and `error_message`. If `attempt_count <= max_retries`, re-enqueue `send_message(log_id)` with a backoff delay; otherwise set `status=failed`.

Provide convenience enqueue helpers that create the `MessageLog` row synchronously in the calling process and then enqueue the Dramatiq task. The worker only updates the existing log row.

> **Note:** Bulk sending (thousands of messages in one operation) is not supported by these helpers and is out of scope for this iteration.

```python
def enqueue_email(message_key, recipient, context): ...
def enqueue_sms(message_key, recipient, context): ...
def enqueue_push(message_key, recipient, context): ...
```

### 9. Recipient handling

A `recipient` is passed as a dictionary so each backend can interpret it:

| Channel | Expected recipient fields |
|---------|---------------------------|
| `email` | `{"email": "user@example.com"}` |
| `sms` | `{"phone_number": "+1234567890"}` |
| `push` | `{"device_token": "...", "platform": "ios" \| "android"}` |

Backends may validate required recipient fields and raise `MessageSendError` if they are missing.

### 10. Usage example

```python
from apps.messaging.tasks import enqueue_email

enqueue_email(
    message_key="case_filing_submitted",
    recipient={"email": "litigant@example.com"},
    context={
        "case_number": "CASE-2026-0001",
        "court_name": "District Court, Patna",
    },
)
```

### 11. Admin interface

Register `MessageTemplate` in `apps.messaging.admin` with:
- List display: `message_key`, `message_type`, `category`, `priority`, `max_retries`, `is_active`.
- List filters: `message_type`, `category`, `priority`, `is_active`.
- Search fields: `message_key`, `subject`, `content`.
- Read-only: audit fields from `BaseModel`.

Register `MessageLog` as read-only with:
- List display: `id`, `message_key`, `message_type`, `status`, `attempt_count`, `max_retries`, `sent_at`, `failed_at`.
- List filters: `message_type`, `status`.
- Search fields: `message_key`, `recipient`, `provider_message_id`.

## Affected files

- `src/config/settings/base.py`
- `src/apps/messaging/__init__.py`
- `src/apps/messaging/apps.py`
- `src/apps/messaging/models.py`
- `src/apps/messaging/admin.py`
- `src/apps/messaging/services.py`
- `src/apps/messaging/tasks.py`
- `src/apps/messaging/senders/__init__.py`
- `src/apps/messaging/senders/base.py`
- `src/apps/messaging/senders/email.py`
- `src/apps/messaging/senders/sms.py`
- `src/apps/messaging/senders/push.py`
- `src/apps/messaging/tests/test_senders.py`
- `src/apps/messaging/tests/test_models.py`
- `src/apps/messaging/tests/test_tasks.py`
- `src/apps/messaging/tests/test_services.py`

## Open questions

1. Should `MessageLog` rows be pruned/archived after a retention period?
2. Should `MessageTemplate` store a plain-text variant alongside HTML/rich content for email?
3. Should we version templates so that in-flight messages use the version that existed at enqueue time?
4. Should we support CC/BCC for email at the template level or only at enqueue time?
5. Which template engine do we ship as the default — Jinja2 or Mustache?
6. What retry backoff strategy should Dramatiq use — fixed, exponential, or configurable per template?

## Out of scope

- Bulk message sending (thousands of recipients in one operation).
- Third-party provider integrations beyond the built-in dummy SMS and SMTP email backends (e.g., Twilio, SES, FCM, APNs).
- Organization- or location-scoped templates (future TODO).
- Delivery receipts, bounce handling, and detailed retry policies beyond `max_retries`.
- Message scheduling and rate limiting.
- Multi-language / localization support.
- Message preference management for users (opt-in/opt-out).

## Future TODO

- Add organization- and location-level scoping to `MessageTemplate`.
- History/Audit trail for the 'MessageTemplate`
- Implement scoped template resolution (exact → organization-only → location-only → global fallback).
- Store scope snapshots on `MessageLog` so historical sends remain traceable to the correct tenant/location.
- Implement push notification backend and remove the `NotImplementedError` from `PushSender`.
