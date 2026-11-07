# 0031 — In-App Push Notifications (SSE)

## Status

Proposed

## References

- [0000 — API Coding Spec](0000-api-coding-spec.md): DRF, response envelope, errors, Swagger, tests
- [0009 — Messaging Module](0009-messaging.md): outbound email/SMS/push channels and delivery logs
- [0026 — Scheduled and Delayed Jobs](0026-dramatiq-crontab.md): Dramatiq actors and delayed jobs
- [0027 — Structured Logging](0027-structured-logging.md): event log conventions
- [0030 — Core Language Support](0030-core-language-support.md): language-aware content (future notification copy)
- `AGENTS.md`: app layout, Dramatiq, error-code and Swagger rules

> **Scope note.** "Push" here means **server-push to an authenticated browser
> session over Server-Sent Events (SSE)**. It is not mobile OS push (FCM/APNs)
> and does not replace the `push` channel in `apps.messaging` (spec 0009), which
> remains an external transport and is still unimplemented. This spec adds a
> persistent in-app notification inbox and a live stream of new inbox items.

## Context

Dristi already has a messaging module that can render templates and dispatch
email/SMS messages through external providers (spec 0009). It deliberately does
**not** provide a real-time UI notification channel: `PushSender.send()` raises
`NotImplementedError`, and real-time/WebSocket notifications are listed as a
non-goal of that spec.

The front end now needs to show notification badges and toasts without polling:

- a user should see a notification created for them while their tab is open;
- notifications must survive a disconnect and be available again through REST;
- any backend module must be able to notify one user or a set of users through
  one internal API;
- a client must never be able to subscribe to another user's notifications.

SSE fits the requirement because notifications flow in one direction only
(server → client). It uses ordinary HTTP, reconnects automatically in the
browser, and needs no WebSocket/Channels stack. Dramatiq provides the
asynchronous fan-out so a caller's request never waits on Redis.

## Goals

- Add an `apps.notifications` app that owns the user notification inbox.
- Persist every notification in PostgreSQL with a read/unread state.
- Expose `GET /api/v1/notifications/subscribe/`, an authenticated SSE stream
  scoped to the requesting user.
- Provide a common internal Python API — `notify()` and `notify_many()` — that
  any app or task can call for one user or a set of users.
- Fan out Redis events through a Dramatiq actor, after the database transaction
  commits.
- Use Redis Streams so a reconnecting browser can resume from `Last-Event-ID`,
  with the database as the durable source of truth.
- Expose the per-user inbox over REST: list, retrieve, mark one read, mark all
  read, unread count.
- Follow the existing API, error, Swagger, logging and testing conventions.

## Non-goals

- FCM/APNs or any mobile OS push transport. `apps.messaging.senders.push`
  remains untouched.
- Replacing email/SMS notification flows in `apps.messaging`.
- Notification templates, localization, rich media, attachments or action
  buttons. Callers pass a title, body and opaque JSON data.
- User notification preferences, quiet hours, opt-out, digests or scheduling.
- Broadcast/administration UI. The internal API is the only send path.
- Read-state synchronization across a user's tabs/devices (an optional future
  `notification.read` event).
- Editing or deleting notifications from the client.
- Delivery receipts or guaranteed live delivery. Redis is a short-lived replay
  buffer; PostgreSQL is the record.
- WebSocket/Channels, consumer groups, or per-connection sticky sessions.

## Decision: a new `apps.notifications` app

This is **not** part of `apps.messaging`.

| Concern | `apps.messaging` (spec 0009) | `apps.notifications` (this spec) |
| --- | --- | --- |
| Purpose | Render and send outbound messages through external channels | Own the in-app inbox and live delivery to an open browser |
| Unit of record | `MessageLog` — one dispatch attempt | `Notification` — one item in one user's inbox |
| Recipient | Opaque dict (`email`, `phone_number`, `device_token`) | A real `User`/user id |
| State | Template, retries, provider id, delivery status | Read/unread, event type, title, body, data |
| Real-time | Explicitly out of scope | The point of the app |
| Runtime | Backend providers, retries, backoff | Redis stream, SSE connection, heartbeat |
| Change rate | Template and delivery records | High-volume, user-scoped rows |

Adding the inbox to `apps.messaging` would make a transport module depend on
users, read state and a long-lived HTTP stream, and would turn a module that is
about external providers into a UI notification subsystem. Keeping them apart
also lets `apps.messaging` stay reusable for email/SMS and leaves room for a
future bridge without coupling either side today.

`apps.notifications` depends only on `apps.core` (base model, auditing) and the
user model through Django's `AUTH_USER_MODEL`. It does not import
`apps.messaging` in v1. If notification copy later needs template rendering,
it can import `apps.messaging.services.MessageTemplateRenderer` without creating
a cycle, because messaging will not import notifications.

It is a first-party domain app under `src/apps/`, not an addon: it contributes
models, migrations, URLs and admin, which addons must not do.

### Why SSE, not WebSockets

| Option | Verdict |
| --- | --- |
| **SSE over DRF + Redis Streams (selected)** | One-way notifications only. Plain HTTP, automatic browser reconnect with `Last-Event-ID`, no new protocol dependency. |
| WebSocket / Django Channels | Bidirectional messaging is not needed. Adds Channels, ASGI routing, a second auth path and consumer deployment for no product benefit. |
| Long polling | Simpler, but more requests, more latency and more database load for the same result. |
| Polling an inbox endpoint | Keeps working, but a badge appears only on the next poll; unsuitable as the primary live channel. |

### Why Redis Streams, not Pub/Sub

| Option | Verdict |
| --- | --- |
| In-process broadcaster | Only reaches connections in one worker process. Multi-replica production cannot use it. |
| Redis Pub/Sub | Simple, but an event published while the user is reconnecting is lost. Recovering it needs a separate database cursor protocol. |
| **Redis Streams (selected)** | Persists a bounded recent tail per user, supports blocking reads and `Last-Event-ID` replay, and needs no consumer groups for fan-out. The database still owns full history. |
| Kafka / NATS / another broker | A second infrastructure dependency for one small stream. |

Redis Streams are a replay buffer, not the source of truth. A notification is
created in PostgreSQL first. If it never reaches Redis, or the stream is
trimmed or expired, the client recovers it through the REST inbox.

## Architecture

```text
 Caller (view / service / task)
        │
        │ apps.notifications.services.notify(...) / notify_many(...)
        ▼
 ┌──────────────────────────┐       transaction.on_commit
 │ Notification row(s)      │──────────────────────────────┐
 │ PostgreSQL (source of    │                              │
 │ truth, read/unread)      │                              ▼
 └──────────────────────────┘                 publish_notifications actor
        │                                              │
        │ REST: list / read / count                    │ XADD
        ▼                                              ▼
    Browser  ◀──────── SSE frames ◀──────── Redis Stream per user
        │                 ▲                    (bounded, TTL, replay tail)
        │                 │ XREAD BLOCK
        └── GET /api/v1/notifications/subscribe/ ──► DRF streaming view
```

- The caller creates rows synchronously so ids exist and the inbox sees the
  notification immediately.
- Publishing to Redis happens through Dramatiq after commit. A rollback creates
  and publishes nothing; a broker outage does not lose the notification.
- The SSE view authorizes the session, derives the user id from it, and reads
  only that user's Redis stream.
- Redis stream entries carry the notification payload. The SSE `id:` is the
  Redis stream entry id, so the browser's automatic `Last-Event-ID` reconnect
  can resume from the right point. The notification's UUID is inside the JSON
  body for client-side de-duplication.
- A client that has been offline longer than the stream tail calls the REST
  inbox. The stream never has to hold the full history.

## Module layout

```text
src/apps/notifications/
├── __init__.py
├── apps.py
├── models.py                 # Notification
├── services.py               # notify(), notify_many(), inbox helpers
├── bus.py                    # BaseNotificationBus, RedisStreamBus, InMemoryNotificationBus
├── tasks.py                  # publish_notifications actor
├── serializers.py            # Notification + filter/response serializers
├── views.py                  # inbox viewset + SSE subscribe view
├── urls.py
├── errors.py                 # E11001 stream unavailable
├── checks.py                 # settings sanity checks
├── admin.py                  # read-only admin
├── migrations/
│   ├── __init__.py
│   └── 0001_initial.py
└── tests/
    ├── __init__.py
    ├── test_models.py
    ├── test_services.py
    ├── test_tasks.py
    ├── test_bus.py
    └── test_api.py
```

Register `apps.notifications` in `src/config/settings/base.py` under
`INSTALLED_APPS`.

## 1. Data model

### 1.1 `Notification`

Location: `apps.notifications.models`

Inherits `apps.core.models.BaseModel` (UUID primary key, timestamps, audit
users). It does **not** inherit `BaseAuditableModel`: notifications are
high-volume operational data and do not need a history table.

| Field | Type | Notes |
| --- | --- | --- |
| `recipient` | `ForeignKey(settings.AUTH_USER_MODEL, on_delete=CASCADE, related_name="notifications")` | The only user who can see this row. Indexed through the composite indexes below. |
| `event_type` | `CharField(max_length=64, db_index=True)` | Stable uppercase identifier chosen by the caller, e.g. `CASE_FILED`, `SCRUTINY_SENT_BACK`, `HEARING_SCHEDULED`, `PAYMENT_RECEIVED`. Not a `TextChoices` enum: new event types are added by feature apps without a notifications migration. |
| `title` | `CharField(max_length=256)` | Short display title. Required, non-blank. |
| `body` | `TextField(blank=True)` | Optional body text. |
| `data` | `JSONField(default=dict, blank=True)` | Opaque client payload: ids, route parameters, counts. Must be a JSON object. |
| `priority` | `CharField(max_length=16, choices=Priority, default=NORMAL, db_index=True)` | `HIGH`, `NORMAL`, `LOW`. Presentation hint only; it does not reorder the stream. |
| `read_at` | `DateTimeField(null=True, blank=True, db_index=True)` | `NULL` means unread. The service sets it, not the client. |

`Priority` is a `TextChoices` on the model:

```python
class Priority(models.TextChoices):
    HIGH = "HIGH", "High"
    NORMAL = "NORMAL", "Normal"
    LOW = "LOW", "Low"
```

`is_read` is a read-only property: `read_at is not None`.

`Meta`:

- `ordering = ("-created_at",)` (also inherited from `BaseModel`; keep it
  explicit).
- `constraints`:
  - `CheckConstraint(check=models.Q(event_type__regex=r"^[A-Z][A-Z0-9_]*$"), name="notification_event_type_upper_snake")`
- `indexes`:
  - `Index(fields=["recipient", "read_at"], name="notification_recipient_read_idx")`
  - `Index(fields=["recipient", "-created_at"], name="notification_recipient_created_idx")`

`__str__` returns `f"{self.event_type} -> {self.recipient_id}"`.

### 1.2 Validation rules

- `event_type` is uppercase snake case, max 64 characters. The database check
  pins the format; the service validates before insert so callers get a useful
  exception rather than an `IntegrityError`.
- `title` is required and must be non-blank after stripping.
- `data` must be a `dict` and serializable by `json.dumps`. It is stored as
  given; the backend does not interpret it.
- `priority` must be one of `Notification.Priority.values`.
- A notification belongs to exactly one recipient. There is no "broadcast row";
  a send to N users creates N rows.

### 1.3 Retention

Initial retention is **not** automatic. Rows are kept so the inbox remains
useful and auditable. Pruning is an open question (see §16) and, when added,
will be a periodic actor owned by this app, following spec 0026.

## 2. Common internal send API

Location: `apps.notifications.services`

This is the contract every other module uses. Callers **must not** create
`Notification` rows directly.

```python
class NotificationRecipientError(Exception):
    """The supplied recipient or recipient set is invalid."""


def notify(
    *,
    recipient,                    # User instance or user id (UUID/str)
    event_type: str,
    title: str,
    body: str = "",
    data: dict | None = None,
    priority: str = Notification.Priority.NORMAL,
    actor=None,
) -> Notification: ...


def notify_many(
    *,
    recipients,                   # QuerySet[User], iterable[User], or iterable of ids
    event_type: str,
    title: str,
    body: str = "",
    data: dict | None = None,
    priority: str = Notification.Priority.NORMAL,
    actor=None,
    batch_size: int | None = None,
) -> list[Notification]: ...
```

### 2.1 `notify`

1. Resolve `recipient` to an active `User`. A missing or inactive recipient
   raises `NotificationRecipientError`. This is an internal programming error;
   it is not an HTTP endpoint.
2. Validate `event_type`, `title`, `data` and `priority` (§1.2).
3. Create one `Notification` with `created_by=actor`, `updated_by=actor`.
4. Schedule publication with `transaction.on_commit` (§3).
5. Return the created row.

### 2.2 `notify_many`

1. Accept a `QuerySet`, an iterable of `User` objects, or an iterable of user
   ids. If a `QuerySet` is supplied, evaluate only `pk` values.
2. De-duplicate recipient ids while preserving order.
3. Resolve them against active users. Missing or inactive recipients are
   skipped and logged; if **no** valid recipient remains, raise
   `NotificationRecipientError`. This catches callers that pass an empty or
   entirely wrong set.
4. Build all `Notification` objects and `bulk_create` them in batches
   (`batch_size` defaults to `NOTIFICATIONS_PUBLISH_BATCH_SIZE`), inside one
   `transaction.atomic()` so a failure in a later batch inserts none of them.
5. Schedule publication on commit in the same batches.
6. Return the created rows.

Bulk creation is synchronous in the calling process. It is a single statement
per batch, so a set of a few thousand users is acceptable. There is no
"all users" shorthand; a caller that wants a large audience must pass the
explicit queryset it means (`User.objects.filter(role=...)`).

### 2.3 Transaction and failure semantics

- The row insert and publication scheduling are part of the caller's
  transaction. If the caller rolls back, no row exists and no callback runs.
- `transaction.on_commit` enqueues `publish_notifications` only after the
  outermost transaction commits. Outside a transaction, Django runs the
  callback immediately.
- Publication is **best-effort**. The on-commit callback catches broker
  exceptions, logs `event=NOTIFICATION_PUBLISH_FAILED`, and does not raise.
  Turning a committed business operation into a 500 after commit would be
  worse; the row is durable and the client recovers it through REST.
- A caller may call `notify()` from a worker or another service; the same
  on-commit rule applies.

### 2.4 Usage examples

```python
from apps.notifications.services import notify, notify_many
from apps.users.models import Role, User

notify(
    recipient=case.filer,
    event_type="CASE_FILED",
    title="Case filed",
    body=f"Case {case.filing_number} has been filed.",
    data={"case_id": str(case.id), "route": f"/cases/{case.id}"},
    actor=request.user,
)

notify_many(
    recipients=User.objects.filter(role=Role.ADVOCATE, is_active=True),
    event_type="HEARING_SCHEDULED",
    title="Hearing scheduled",
    data={"case_id": str(case.id), "hearing_date": hearing.date.isoformat()},
)
```

Callers choose `event_type` strings. The value is a stable client contract:
once a front end branches on it, changing it is a breaking change. Event types
are owned by the app that raises the notification, not by `apps.notifications`.

## 3. Async fan-out with Dramatiq

Location: `apps.notifications.tasks`

```python
@actor(
    max_retries=3,
    time_limit=settings.NOTIFICATIONS_TASK_TIME_LIMIT,
)
def publish_notifications(notification_ids: list[str]) -> None:
    """Publish committed Notification rows to each recipient's Redis stream."""
```

Flow:

1. Load the notifications by id, with `recipient`.
2. Skip ids that no longer exist (the user or row was deleted).
3. For each notification, build the event payload and call
   `bus.publish(recipient_id, payload)`.
4. Log one structured line: `event=NOTIFICATIONS_PUBLISHED count=<n>`.
5. If Redis fails, let the exception propagate so Dramatiq retries the actor.
   After the final retry Dramatiq records the failure; the rows remain in the
   database. A failure hook or middleware may log
   `event=NOTIFICATION_PUBLISH_FAILED count=<n>`.

The actor is **idempotent**. A retry or duplicate delivery publishes the same
notification again under a new stream entry id. This is harmless: the client
de-duplicates on the payload's `id` (the notification UUID). The actor does not
mutate notification rows.

`notify()`/`notify_many()` split ids into
`NOTIFICATIONS_PUBLISH_BATCH_SIZE` chunks and enqueue one actor message per
chunk, so one large audience does not become one huge message. Each chunk is a
separate on-commit callback; a failure to enqueue one chunk does not prevent
the others.

The actor must be defined in `tasks.py` so `rundramatiq` discovers it. It is
not scheduled (`@cron` is not used).

## 4. Redis Streams event bus

Location: `apps.notifications.bus`

### 4.1 Abstraction

The SSE view and the actor use an event-bus interface rather than a Redis
client directly. This keeps the Redis dependency out of tests and leaves room
for a future implementation.

```python
class BaseNotificationBus(ABC):
    @abstractmethod
    def ping(self) -> None:
        """Raise if the bus is not reachable."""

    @abstractmethod
    def publish(self, user_id, payload: dict) -> str:
        """Append one event to the user's stream and return the stream entry id."""

    @abstractmethod
    def first_id(self, user_id) -> str | None:
        """Return the oldest retained stream id, or None when the stream is gone."""

    @abstractmethod
    def read(self, user_id, after_id: str | None, block_ms: int) -> list[tuple[str, dict]]:
        """Read events after ``after_id``; None means only new events."""
```

Implementations:

- `RedisStreamBus` — production. Uses `redis.Redis.from_url(settings.NOTIFICATIONS_REDIS_URL, decode_responses=True)`.
- `InMemoryNotificationBus` — tests only. Stores bounded per-user deques and
  supports a blocking read with a short timeout. It is never configured in
  production.

`get_bus()` lazily imports and caches the class named by
`settings.NOTIFICATIONS_EVENT_BUS`, mirroring the messaging sender registry.
`clear_bus_cache()` resets that cache for tests that override the setting.

### 4.2 Redis key and entry shape

- Key: `f"{NOTIFICATIONS_STREAM_PREFIX}:{user_id}"`, default
  `dristi:notifications:<user-uuid>`.
- Append:

  ```text
  XADD <key> MAXLEN ~ <NOTIFICATIONS_STREAM_MAXLEN> * data <json>
  EXPIRE <key> <NOTIFICATIONS_STREAM_TTL_SECONDS>
  ```

- Entry id is generated by Redis (`<milliseconds>-<sequence>`). This is the SSE
  `id:` used for `Last-Event-ID`.
- `data` is one compact JSON object:

  ```json
  {
    "id": "b8f0b8c4-0f4f-4f2e-a4f4-2e4f0f6b9c11",
    "event_type": "CASE_FILED",
    "title": "Case filed",
    "body": "Case FIL-2026-0001 has been filed.",
    "data": {"case_id": "…", "route": "/cases/…"},
    "priority": "NORMAL",
    "created_at": "2026-11-07T10:12:31.123456+00:00"
  }
  ```

  This is a creation-time snapshot, not a read-state update. A stream event
  for a notification the client already has must not reset its read state.

- `XREAD BLOCK <heartbeat_ms> COUNT <batch> STREAMS <key> <after_id|$>`.
- No consumer groups: every SSE connection for the same user reads
  independently from its own position. Two tabs both receive the event.

### 4.3 Retention and loss

- `MAXLEN ~` keeps roughly the newest N entries; Redis may trim in whole
  macro-nodes, so the exact count is approximate.
- The key expires after `NOTIFICATIONS_STREAM_TTL_SECONDS` from the last
  publish. A user who has not received an event for that long has no replay
  tail.
- These limits are intentional. The database has the full inbox. If a stream
  is missing when a client reconnects with a `Last-Event-ID`, the SSE view sends
  a `resync` event and the client calls the REST inbox.
- Redis Streams are not persisted as the source of truth. A Redis flush loses
  only live/replay events, never notifications.

## 5. SSE subscribe endpoint

### 5.1 Route and permissions

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/notifications/subscribe/` | Open the current user's SSE stream. |

- Owned by `apps.notifications`, included under `/api/v1/`.
- Uses the project's default authentication and permission classes (session
  authentication plus the registration/approval/terms gates). There is no
  `AllowAny`; a half-registered or unapproved account cannot subscribe.
- The user id comes **only** from `request.user`. There is no `user_id` query
  parameter or path parameter. A client cannot subscribe to another user's
  stream.
- An unauthenticated or gated request receives the normal JSON error response
  (`E00102`, `E01006`, etc.) with `meta`, before any stream starts.

### 5.2 Response

Return a `StreamingHttpResponse` directly from a DRF `APIView`; it is not a
DRF `Response`, so `MetaJSONRenderer` does not wrap it.

Headers:

```text
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache, no-store
X-Accel-Buffering: no
```

Do not set a `Content-Length`. Do not enable gzip on this route.

Frame format:

```text
retry: 3000

event: connected
data: {"user_id": "...", "server_time": "2026-11-07T10:12:00+00:00"}

id: 1730974351123-0
event: notification
data: {"id": "...", "event_type": "CASE_FILED", ...}

: keep-alive

event: resync
data: {"reason": "stream_unavailable"}
```

Rules:

- `retry:` is `NOTIFICATIONS_SSE_RETRY_MS` and is sent once at the start.
- `connected` confirms the stream is open. It has no `id:`.
- Every notification frame has `id: <redis stream id>` and the JSON payload in
  `data:`.
- A comment line (`: keep-alive`) is emitted after
  `NOTIFICATIONS_SSE_HEARTBEAT_SECONDS` without an event. It keeps proxies and
  load balancers from closing an idle connection.
- `resync` means the replay tail is unavailable. The client should fetch the
  REST inbox; the stream then continues live. It has no `id:`.
- `json.dumps` escapes newlines, so one event is always valid one-line SSE
  data. Titles and bodies are never interpolated into the frame unescaped.

### 5.3 Reconnect and `Last-Event-ID`

`EventSource` automatically reconnects and sends the last received `id:` in the
`Last-Event-ID` request header.

The view supports:

- `Last-Event-ID` header (preferred, sent by the browser);
- `?last_event_id=<id>` query parameter for non-browser clients.

If both are present, a valid header wins; if it is malformed, the query
parameter is tried. The value is an opaque Redis stream id. Invalid values are
ignored and the stream starts live; a malformed header must not produce a 500.

Logic:

1. Open the bus (`ping()`). Any Redis error during preflight (`ping()` or the
   cursor check) raises `BusinessError(errors.NOTIFICATION_STREAM_UNAVAILABLE)`
   before returning the streaming response, so the client gets a normal
   `503 E11001` JSON error.
2. If a cursor was supplied and `first_id(user_id)` is `None`, emit `resync`
   and start live.
3. Otherwise start `XREAD` after the supplied id, or at `$` for a new stream.
4. Keep reading until `NOTIFICATIONS_SSE_MAX_DURATION_SECONDS`, then close.
   The browser reconnects automatically and resumes from its last id.
5. On `GeneratorExit`, `BrokenPipeError` or a client disconnect, stop and
   close the Redis client. No error is written after the stream has started;
   the connection simply closes.

Resuming from an old id that has been trimmed returns only the retained tail;
the client de-duplicates by the payload's `id` and can call REST for anything
older.

### 5.4 Why a maximum duration

A stream is never kept open indefinitely. The maximum duration bounds the
number of threads and lets deploys drain gracefully. It is not a user-visible
timeout: `EventSource` reconnects and resumes with `Last-Event-ID`. The value
must be much larger than the heartbeat interval.

### 5.5 Client startup and reconnect sequence

To avoid a gap between the initial REST read and the live stream, the client
must open the stream first and fetch the inbox only after the `connected`
event:

1. Create the `EventSource` (with credentials when cross-origin).
2. On every `connected` event (including after a reconnect), call
   `GET /api/v1/notifications/` (or the unread list) and merge rows by `id`.
3. On each `notification` event, insert by the payload's `id` if it is new. If
   the id already exists, keep its local read state; a delayed stream event
   must not turn an already-read notification back into unread.
4. On `resync`, fetch the REST inbox again and merge by `id`.
5. On reconnect, `EventSource` sends `Last-Event-ID` automatically.

Because steps 2 and 3 can both produce the same notification, the client must
be idempotent by notification UUID and preserve read state on duplicates. No
ordering between the REST response and streamed events is guaranteed.

## 6. REST inbox API

All endpoints require the default authenticated, registered, approved and
terms-current gates. The queryset is always the requesting user's rows only;
another user's id returns `404 E00105`, not `403`, so existence is not leaked.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/notifications/` | Paginated list of the caller's notifications. |
| `GET` | `/api/v1/notifications/{id}/` | One notification owned by the caller. |
| `POST` | `/api/v1/notifications/{id}/read/` | Mark one notification read (idempotent). |
| `POST` | `/api/v1/notifications/read-all/` | Mark all unread notifications read. |
| `GET` | `/api/v1/notifications/unread-count/` | Return `{"count": n}` for the caller. |

`NotificationViewSet(APIModelReadOnlyViewSet)` implements the list and retrieve
routes plus the read actions; `subscribe` is a separate `APIView`. The viewset
uses a serializer for query-parameter validation and the project's default
pagination.

There is **no** create, update, delete or public send endpoint. Notifications
are created only through the internal service.

### 6.1 List and retrieve

- Ordered newest first (`-created_at`), paginated with the project default
  page-number pagination.
- Optional filters:
  - `is_read=true|false` — any value the filter serializer's `BooleanField`
    rejects is `400 E00001`, field `is_read`.
  - `event_type=<value>` — exact match; no validation against a fixed enum.
  - `priority=HIGH|NORMAL|LOW` — invalid value is `400 E00005`, field
    `priority`.
- `GET /notifications/{id}/` uses the same owner-filtered queryset.

### 6.2 Mark read

`POST /notifications/{id}/read/`:

- Sets `read_at`, `updated_at` and `updated_by` only when currently unread.
- Returns the serialized notification with `200` on the first call and on
  repeated calls (idempotent).
- Does not publish a stream event in v1; see Open Questions §16.

`POST /notifications/read-all/`:

- Updates every unread row for the caller in one `UPDATE`, setting `read_at`,
  `updated_at` and `updated_by`.
- Returns `{"updated": <count>}` with `200`.
- Is idempotent; a second call returns `{"updated": 0}`.

### 6.3 Unread count

`GET /notifications/unread-count/` returns:

```json
{"count": 7, "meta": {...}}
```

`count` is the number of rows with `read_at__isnull=True` for the caller.

### 6.4 Serializers

`apps.notifications.serializers.NotificationSerializer` is read-only:

| Field | Notes |
| --- | --- |
| `id` | Notification UUID. |
| `event_type` | Stable event identifier. |
| `title` | Display title. |
| `body` | Body text. |
| `data` | Opaque JSON object. |
| `priority` | `HIGH`, `NORMAL`, `LOW`. |
| `is_read` | Boolean, from `read_at is not None`. |
| `read_at` | Timestamp or `null`. |
| `created_at` | Creation timestamp. |

All fields are read-only. Do not expose `recipient` or audit users; they are
implicit in the request.

Supporting serializers:

- `NotificationFilterSerializer` — query-parameter validation for `is_read`
  (`BooleanField`), `event_type` (`RegexField`, uppercase snake case) and
  `priority` (`ChoiceField`). It is used only by the list action.
- `NotificationSubscribeQuerySerializer` — optional `last_event_id`
  (`RegexField`); an invalid value is discarded, never a 500.
- `MarkAllReadSerializer` — read-only `updated` integer.
- `UnreadCountSerializer` — read-only `count` integer.

The read actions declare `request=None`; their responses use
`NotificationSerializer`, `MarkAllReadSerializer` and `UnreadCountSerializer`
respectively.

### 6.5 Swagger

- The viewset's tag is inferred from the owning app per spec 0000 §10.2.
- `subscribe` is annotated with the optional `Last-Event-ID` header and
  `last_event_id` query parameter.
- `E11001` is declared on `subscribe` with `error_responses(...)`.
- The subscribe success is documented explicitly as `text/event-stream`, not as
  a JSON body. Use an `OpenApiResponse` and, if the installed schema generator
  would otherwise report the view's default JSON media type, a view-local
  schema renderer or a schema override so the media type is correct.
- The list action declares `parameters=[NotificationFilterSerializer]`;
  `ApiAutoSchema` does not infer query parameters from a serializer otherwise.
- The list/retrieve/action serializers let `ApiAutoSchema` infer the rest.
- No `tags=` override is needed.

## 7. Routing and app wiring

`src/apps/notifications/urls.py`:

```python
router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = [
    path(
        "notifications/subscribe/",
        NotificationSubscribeView.as_view(),
        name="notification-subscribe",
    ),
    path("", include(router.urls)),
]
```

`src/config/urls.py` adds:

```python
path("api/v1/", include("apps.notifications.urls")),
```

Set `lookup_value_regex` to the UUID pattern used elsewhere so
`notifications/read-all/` and `notifications/unread-count/` are not captured as
detail ids.

## 8. Error codes

Allocate domain `11` → `notifications` in `apps.api.errors.DOMAINS` and in the
table in spec 0000 §9.2. Domain `10` is reserved for `core` by spec 0030.

`src/apps/notifications/errors.py`:

| Code | Status | Default message | When |
| --- | --- | --- | --- |
| `E11001` | 503 | `Notification stream is temporarily unavailable.` | The Redis event bus cannot be reached before the SSE response starts. The client should retry; the REST inbox still works. |

No notification-specific code is used for an unknown/foreign id: the inbox
endpoints return the common `404 E00105`, which is also the anti-enumeration
behaviour. Validation of `is_read`/`priority` uses the common `E00001`/`E00005`
codes.

Raise `E11001` from the subscribe view with `BusinessError`; do not hand-build
an error `Response`. Once streaming has started, there is no status code to
change, so log and close instead.

## 9. Settings and environment

Add one block to `src/config/settings/base.py`:

```python
# ---------------------------------------------------------------------------
# In-app notifications (spec 0031)
# ---------------------------------------------------------------------------
NOTIFICATIONS_REDIS_URL = env(
    "NOTIFICATIONS_REDIS_URL",
    default="redis://localhost:6379/4",
)
# Dotted path to the event-bus implementation. Code-level setting; tests use
# the in-memory bus.
NOTIFICATIONS_EVENT_BUS = "apps.notifications.bus.RedisStreamBus"
NOTIFICATIONS_STREAM_PREFIX = env(
    "NOTIFICATIONS_STREAM_PREFIX",
    default="dristi:notifications",
)
# Approximate number of entries retained per user for Last-Event-ID replay.
NOTIFICATIONS_STREAM_MAXLEN = env.int("NOTIFICATIONS_STREAM_MAXLEN", default=1000)
# Replay tail lifetime, refreshed on every publish (7 days by default).
NOTIFICATIONS_STREAM_TTL_SECONDS = env.int(
    "NOTIFICATIONS_STREAM_TTL_SECONDS", default=7 * 24 * 60 * 60
)
# Comment frame interval; must stay below proxy/load-balancer idle timeouts.
NOTIFICATIONS_SSE_HEARTBEAT_SECONDS = env.int(
    "NOTIFICATIONS_SSE_HEARTBEAT_SECONDS", default=15
)
NOTIFICATIONS_SSE_RETRY_MS = env.int("NOTIFICATIONS_SSE_RETRY_MS", default=3000)
# Bounds a single SSE connection; browsers reconnect and resume.
NOTIFICATIONS_SSE_MAX_DURATION_SECONDS = env.int(
    "NOTIFICATIONS_SSE_MAX_DURATION_SECONDS", default=1800
)
NOTIFICATIONS_PUBLISH_BATCH_SIZE = env.int(
    "NOTIFICATIONS_PUBLISH_BATCH_SIZE", default=500
)
NOTIFICATIONS_TASK_TIME_LIMIT = env.int(
    "NOTIFICATIONS_TASK_TIME_LIMIT", default=60000
)
```

`src/config/settings/test.py`:

```python
# No Redis in tests: the event bus is process-local.
NOTIFICATIONS_EVENT_BUS = "apps.notifications.bus.InMemoryNotificationBus"
```

`apps/notifications/checks.py`, registered from `NotificationsConfig.ready()`,
performs soft startup checks:

- `NOTIFICATIONS_REDIS_URL` is non-empty and parses as a Redis URL;
- `NOTIFICATIONS_STREAM_PREFIX` is non-empty;
- stream max length, TTL, publish batch size, retry delay and task time limit
  are positive;
- heartbeat and maximum duration are positive, and max duration is greater
  than the heartbeat.

These are configuration errors (fail fast) rather than request-time failures.

Add to `.env.example` and `.env.prod.example`:

```text
NOTIFICATIONS_REDIS_URL=redis://redis:6379/4
NOTIFICATIONS_STREAM_PREFIX=dristi:notifications
NOTIFICATIONS_STREAM_MAXLEN=1000
NOTIFICATIONS_STREAM_TTL_SECONDS=604800
NOTIFICATIONS_SSE_HEARTBEAT_SECONDS=15
NOTIFICATIONS_SSE_RETRY_MS=3000
NOTIFICATIONS_SSE_MAX_DURATION_SECONDS=1800
NOTIFICATIONS_PUBLISH_BATCH_SIZE=500
NOTIFICATIONS_TASK_TIME_LIMIT=60000
```

`NOTIFICATIONS_EVENT_BUS` stays out of the env files: it is a code-level
setting, overridden only by test settings. Add the Redis URL and settings to the
README environment table.

## 10. Deployment and operations

### 10.1 The sync-worker problem

The production `web` service currently runs Gunicorn with four **sync** workers
(`docker/entrypoint.sh`). A sync worker is occupied for the entire lifetime of
a streaming request. Serving SSE from that pool would take API workers out of
rotation for as long as each browser tab stays open.

Do **not** serve the subscribe route from the existing sync `web` pool.

### 10.2 Dedicated `sse` service

Run a dedicated Gunicorn process with the threaded worker class:

```sh
sse)
    wait_for_db
    echo "Starting SSE server..."
    exec gunicorn config.wsgi:application \
        --bind 0.0.0.0:8001 \
        --workers 2 \
        --worker-class gthread \
        --threads 100 \
        --timeout 0 \
        --access-logfile - \
        --error-logfile - \
        --capture-output \
        --enable-stdio-inheritance
    ;;
```

- Add `sse` to the entrypoint usage line.
- Copy the existing `web` service in `docker/docker-compose.yml` and
  `docker/docker-compose.prod.yml`, changing `command: ["sse"]` and exposing
  `8001` only on the internal network. It does not run migrations or
  `collectstatic`; `web` still owns those. Start `sse` only after the schema is
  current, or it will serve a stream against an un-migrated database.
- Production runs 2 replicas. No sticky sessions are needed: every SSE replica
  reads the same Redis stream from the client's `Last-Event-ID`.
- `--threads` is the maximum concurrent SSE connections per worker process.
  Size it to the expected concurrent tabs and the container memory budget; 100
  threads × 2 workers = 200 streams per replica. Raise it by scaling the `sse`
  replicas or threads; no code change is needed.
- `--timeout 0` disables Gunicorn's worker-silence kill for long streams. The
  application's `NOTIFICATIONS_SSE_MAX_DURATION_SECONDS` still bounds each
  connection.
- Each open stream occupies a Gunicorn thread, and the session-authentication
  queries can leave a PostgreSQL connection open until the streaming response
  closes because Django sends `request_finished` only then. Close the request's
  database connection after authentication before returning the
  `StreamingHttpResponse`, and size `--threads` against PostgreSQL's
  `max_connections`; the stream generator itself needs only Redis.

In local development the Django `runserver` is threaded and can serve SSE
directly. Docker Compose may keep using the `web` service for local streaming.

### 10.3 nginx

Route only the subscribe path to the SSE upstream, with buffering and caching
off:

```nginx
upstream dristi_sse {
    server sse:8001;
}

location = /api/v1/notifications/subscribe/ {
    proxy_pass http://dristi_sse;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
    gzip off;
}
```

The upstream response already carries `X-Accel-Buffering: no`. The
`proxy_read_timeout` must exceed `NOTIFICATIONS_SSE_HEARTBEAT_SECONDS`.
Any load balancer in front of nginx needs the same idle timeout.

### 10.4 Cross-origin front end

SSE uses the session cookie. A same-origin front end needs no extra work. A
separate front-end origin must be in `CORS_ALLOWED_ORIGINS`, with
`CORS_ALLOW_CREDENTIALS=True`, and the browser's `EventSource` must be created
with credentials enabled (`new EventSource(url, { withCredentials: true })`).
The cross-origin preflight must also allow the `Last-Event-ID` request header
(for example in `CORS_ALLOW_HEADERS`), because the browser sends it on
reconnect. Token authentication is not wired in the project today; do not
invent a query token for SSE.

### 10.5 Redis

Use a separate Redis logical database (`/4`) for notification streams. It
holds ephemeral replay data only, so it does not need durability beyond the
existing Redis instance. It must not share the cache database (`/1`) or the
Dramatiq broker database (`/2`), because stream keys would mix with queue and
cache keys.

Add `NOTIFICATIONS_REDIS_URL` to the `web`, `worker` and `sse` environment
blocks (and to the local `.env`); `scheduler` does not need it.

The existing `/health/` check covers Redis reachability. A Redis outage makes
the subscribe endpoint return `503 E11001`; the inbox endpoints continue to
work.

### 10.6 Observability

Use the structured event conventions of spec 0027:

| Event | Where | Fields |
| --- | --- | --- |
| `NOTIFICATION_CREATED` | `services.notify`/`notify_many` | `count`, `event_type` |
| `NOTIFICATIONS_PUBLISHED` | actor | `count`, `duration_ms` |
| `NOTIFICATION_PUBLISH_FAILED` | actor / on-commit callback | `count`, `error` |
| `SSE_CONNECTED` | subscribe view | `user_id` (id only) |
| `SSE_DISCONNECTED` | subscribe view | `user_id`, `duration_ms` |
| `SSE_RESYNC` | subscribe view | `user_id`, `reason` |
| `SSE_FAILED` | subscribe view | `user_id`, `error` |

Do not log notification titles, bodies or `data`: they may contain case or
personal information. Log ids and counts.

`NOTIFICATIONS_REDIS_URL` should be included in the deployment documentation
and the production env template. The `sse` service inherits the same
environment as `worker`/`web`.

## 11. Testing

No test in the default suite needs a real Redis. The test settings use
`InMemoryNotificationBus`; an optional integration suite may exercise
`RedisStreamBus` against a local Redis.

### 11.1 Model tests

- `is_read` is true exactly when `read_at` is set.
- `event_type` check rejects lowercase, spaces and leading digits; accepts
  `CASE_FILED`, `PAYMENT2_RECEIVED`.
- Deleting a user cascades to that user's notifications.
- `Meta.ordering` is newest first.

### 11.2 Service tests

- `notify()` creates one row for the recipient and stamps `created_by`.
- `notify()` rejects a missing/inactive recipient and invalid `event_type`,
  `title`, `data` or `priority`.
- Rows are created and the publish callback is scheduled only after commit:
  use `captureOnCommitCallbacks(execute=True)` and assert `publish_notifications.send`
  is not called before the block exits.
- A rollback creates no row and enqueues nothing.
- `notify_many()` de-duplicates ids, skips inactive users, raises when no valid
  recipient remains, bulk-creates rows and enqueues one actor message per
  batch.
- A broker failure in the on-commit callback is logged and does not re-raise;
  the rows remain.

### 11.3 Bus tests

- `RedisStreamBus` key format, `MAXLEN` and `EXPIRE` are applied (mock the
  Redis client or test against a local Redis in an opt-in integration suite).
- `read(after_id=None)` returns only new entries; `read(after_id=<id>)` returns
  later entries.
- `first_id` returns `None` for a missing stream.
- `InMemoryNotificationBus` mirrors the same contract for the SSE tests.

### 11.4 Actor tests

- `publish_notifications.fn([...])` publishes one event per notification to
  each recipient's stream with the correct payload.
- Missing/deleted notification ids are skipped without error.
- A duplicate invocation publishes a duplicate event under a new stream id.
- Redis failure propagates to Dramatiq (the actor is allowed to retry).
- A structured `NOTIFICATIONS_PUBLISHED` line is emitted.

### 11.5 API tests

- All inbox endpoints require authentication and the default registration /
  approval / terms gates.
- List returns only the caller's rows, newest first, paginated with `meta`; the
  `is_read`, `event_type` and `priority` filters work; invalid filter values
  return the right common codes and fields.
- Retrieve/mark-read of another user's id returns `404 E00105`.
- Mark-read is idempotent; `read-all` returns the updated count and is
  idempotent; unread-count matches the rows.
- Serializer exposes exactly the fields in §6.4 and no `recipient`.
- `subscribe` returns `Content-Type: text/event-stream; charset=utf-8`,
  `Cache-Control: no-cache, no-store` and `X-Accel-Buffering: no`.
- A `connected` frame, notification frames with `id:`/`event:`/`data:` and
  keep-alive comments are formatted correctly (test the frame helper/generator
  without consuming an infinite stream).
- A valid `Last-Event-ID` resumes after that entry; a missing stream with a
  cursor emits `resync`; an invalid cursor starts live rather than erroring.
- Redis unavailability before the stream starts returns `503 E11001`.
- The schema contains the route, the `text/event-stream` response and `E11001`.

### 11.6 Quality checks

```bash
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest
cd src && ruff check . && ruff format .
cd src && python manage.py check
```

Manual check: run the API, open an authenticated `EventSource`, call
`notify()` from a Django shell, confirm the event arrives, disconnect,
create another notification, reconnect, and confirm `Last-Event-ID` replays it.

## 12. Affected files

```text
src/config/settings/base.py                  # app + NOTIFICATIONS_* block
src/config/settings/test.py                  # InMemoryNotificationBus
src/config/urls.py                           # include apps.notifications.urls
src/apps/api/errors.py                       # allocate domain 11
src/apps/notifications/__init__.py
src/apps/notifications/apps.py               # NotificationsConfig + checks
src/apps/notifications/checks.py
src/apps/notifications/models.py             # Notification
src/apps/notifications/services.py           # notify / notify_many
src/apps/notifications/bus.py                # RedisStreamBus + in-memory bus
src/apps/notifications/tasks.py              # publish_notifications
src/apps/notifications/serializers.py
src/apps/notifications/views.py              # inbox viewset + SSE view
src/apps/notifications/urls.py
src/apps/notifications/errors.py             # E11001
src/apps/notifications/admin.py
src/apps/notifications/migrations/0001_initial.py
src/apps/notifications/tests/...
spec/0000-api-coding-spec.md                 # domain 11 in §9.2
spec/0031-push-notification.md               # this file
.env.example
.env.prod.example
docker/entrypoint.sh                         # sse command
docker/docker-compose.yml                    # sse service (optional locally)
docker/docker-compose.prod.yml               # sse service, 2 replicas
docker/nginx.conf                            # unbuffered subscribe route
README.md, docs/development.md               # local usage
docs/production.md, docs/architecture.md     # sse service and Redis
AGENTS.md                                    # internal notify API convention (optional)
```

No new Python dependency is required: `redis>=5.0.0` is already in
`src/requirements/base.txt`, and `dramatiq` is already installed.

## 13. Acceptance criteria

- [ ] `apps.notifications` is installed, migrated, routed and visible in Swagger.
- [ ] `notify()` creates a notification for one user; `notify_many()` creates
      one row per valid recipient in a set, de-duplicating ids.
- [ ] Notifications are published only after the caller's transaction commits.
- [ ] `publish_notifications` appends the correct payload to each recipient's
      Redis stream and retries on transient Redis failure.
- [ ] An authenticated user can open `/api/v1/notifications/subscribe/` and
      receives only their own notifications.
- [ ] The browser can reconnect with `Last-Event-ID`; a missing/expired stream
      produces `resync` and the REST inbox remains complete.
- [ ] The REST inbox supports list, retrieve, mark read, mark all read and
      unread count, always scoped to the caller.
- [ ] No public endpoint or query parameter can send a notification to another
      user.
- [ ] The subscribe route runs on the dedicated `sse` service with buffering
      disabled in nginx; the sync `web` pool is not used for streams.
- [ ] Tests pass without Redis, and `ruff check`, `ruff format` and
      `manage.py check` pass.

## 14. Design decisions

| Decision | Rationale |
| --- | --- |
| New `apps.notifications` app | Inbox state, per-user read model and a long-lived HTTP stream are a different domain from outbound message transport. Messaging stays transport-only. |
| PostgreSQL is the source of truth | SSE and Redis are best-effort. Every notification must survive a disconnect, broker outage or Redis flush. |
| Redis Streams instead of Pub/Sub | `Last-Event-ID` replay is built in, and a reconnect does not need a bespoke database cursor. |
| Dramatiq for fan-out | Publication is retried and isolated from the caller's request; the actor fits the existing worker/queue operations. |
| Publication is best-effort after commit | A Redis/broker failure must not turn a committed business action into a 500; the inbox still has the row. |
| User id from the session only | Prevents horizontal privilege escalation; no `user_id` is accepted on the stream. |
| SSE `id:` is the stream entry id | Matches `XREAD` resume semantics. The notification UUID stays in the payload's `id` for client de-duplication. |
| No client-authored notification API | Notifications are events; clients can only read them and change read state. The only send path is the internal service. |
| Dedicated `sse` service | A sync Gunicorn worker cannot serve a stream without being unavailable for ordinary requests. |
| No templates in v1 | Callers already have the context and can compose copy; template rendering can reuse messaging later without changing the transport. |
| No domain error for a missing notification | Common `E00105` already provides the correct 404 and avoids leaking whether another user's row exists. |

## 15. Out of scope

- Mobile OS push (FCM/APNs), including changes to `apps.messaging.senders.push`.
- Email/SMS/template rendering and the `MessageTemplate`/`MessageLog` models.
- Notification preferences, per-category opt-out, quiet hours and digests.
- Notification grouping, collapsing, badges beyond the unread count, or
  priority-based ordering.
- Rich content, attachments, action buttons and localization.
- Client editing, deleting or archiving notifications.
- Multi-device read-state synchronization.
- Delivery receipts, per-connection acknowledgements and guaranteed live
  delivery.
- A broadcast/admin send UI or a public "send notification" HTTP endpoint.
- WebSocket/Channels and bidirectional messaging.
- Automatic retention/pruning of `Notification` rows (see open questions).

## 16. Open questions

1. **Retention:** how long should `Notification` rows be kept? A periodic
   prune actor (spec 0026) can enforce a configured age once the product
   decides the audit requirement.
2. **Idempotency:** should `notify()` accept an optional `dedupe_key` with a
   unique `(recipient, dedupe_key)` constraint for event-driven callers that
   may retry the same trigger? It is not needed for Dramatiq retries because
   row creation happens once in the caller, but it helps webhook-style callers.
3. **Read-state events:** should marking a notification read publish a
   `notification.read` event so other tabs/devices update immediately? This
   would add a small second event type but no new persistence.
4. **Connection cap:** do we need a per-user connection limit or a global
   admission counter to stop one client opening thousands of streams?
5. **SSE runtime:** is Gunicorn `gthread` sufficient, or should the `sse`
   service move to an ASGI server with an async Redis client for a much higher
   connection count per process?
6. **Messaging bridge:** should `apps.messaging.enqueue_push()` eventually
   create an in-app notification in addition to an external push, or should
   callers invoke both explicitly?
7. **Language:** should notifications carry a language/locale and use
   `apps.core` languages for localized copy (spec 0030), or remain
   caller-rendered text?
8. **Admin visibility:** is a read-only admin search over notification metadata
   sufficient, or does support need a way to resend/inspect payloads while
   respecting privacy?
9. **Session revocation:** an open stream is authenticated only at connect.
   Should the server periodically revalidate the session, or close streams on
   logout/user deactivation, instead of relying on the maximum duration?

## 17. Implementation phases

1. **Model and service** — `Notification`, migration, admin, `notify()` /
   `notify_many()`, validation, retention notes.
2. **Event bus and fan-out** — `BaseNotificationBus`, `RedisStreamBus`,
   `InMemoryNotificationBus`, `publish_notifications`, settings and checks.
3. **REST inbox** — serializer, owner-scoped viewset, list filters, read,
   read-all, unread-count, Swagger.
4. **SSE endpoint** — streaming view, frame helpers, `Last-Event-ID` resume,
   heartbeat, max duration, `E11001`.
5. **Deployment** — `sse` entrypoint command, compose services, nginx route,
   env examples, docs.
6. **First consumers** — have an owning feature spec call `notify()` on commit
   for its existing triggers. Existing messaging calls remain unchanged until
   that feature explicitly adopts the in-app channel.
