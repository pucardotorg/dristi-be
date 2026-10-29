# 0027 — Structured Logging (`apps.core.logs`)

## Status

Proposed

## References

- [0000 — API Coding Spec](0000-api-coding-spec.md): style constraints
- [0009 — Messaging Module](0009-messaging.md), [0013 — CDAC SMS Gateway](0013-addon-cdac-sms-gateway.md), [0015 — CDAC eSign](0015-cdac-esign.md), [0016 — PDF Service](0016-pdf-services.md): modules whose ad hoc `event=...` logging is migrated here
- [django-structlog](https://django-structlog.readthedocs.io/en/latest/), [structlog](https://www.structlog.org/en/stable/), [concurrent-log-handler](https://pypi.org/project/concurrent-log-handler/)

> **Scope note.** This spec defines how every module in `apps.*` and `addon.*`
> logs: the event shape, the request and task context, the rules for sensitive
> data, and where the output goes. It is the reference for people and coding
> agents writing log calls. It adds no models, migrations or endpoints.

## Context

Logging is the Django default. `LOGGING` in `src/config/settings/base.py` has one
plain-text `standard` formatter and one `StreamHandler`. The level is hard-coded
to `INFO` and nothing is written to disk.

Problems with this:

- **Lines can't be queried by field.** Several modules work around this by
  hand-building `key=value` strings: `apps/esign/log.py` (`log_event`),
  `apps/messaging/tasks.py` (`_log_event`), `apps/pdf/*` and
  `addon/cdac_sms_gateway/*`. Each module formats them differently.
- **Nothing ties log lines together.** No request id exists. An HTTP request,
  the Dramatiq messages it enqueues and their log lines can't be correlated.
- **Sensitive data reaches the log.** `apps/users/services/otp.py:152` logs the
  full mobile number. `CDAC_SMS_PRINT_RESPONSE` defaults to `True`, so gateway
  response bodies are logged. Exceptions are formatted with no control over
  what they include.
- **No bounded file output.** Logs exist only on stdout. Docker's default
  json-file driver collects them with no size cap.

Runtime facts this design must respect:

- **web:** Gunicorn with `--workers 4`, sync worker class and no `--preload`
  (`docker/entrypoint.sh`).
- **worker:** `rundramatiq --processes 2 --threads 8`.
- **Replicas:** production compose runs 2 replicas of each service.

So up to 4 processes in a web container, or 2 processes with 8 threads each in
a worker container, write logs at the same time.

No logs are consumed by any tool yet (no aggregator, no dashboards), so the
format can change now with no migration. The design must still work on hosts
that already run the stack. It applies to every deployed environment the same
way, through settings and env vars.

## Decision summary

1. **Adopt `structlog` with `django-structlog`** as the logging layer for all
   first-party code. Production renders JSON. Local and test environments render
   for a human reader.
2. **Route stdlib and third-party records through the same pipeline**, using
   `structlog.stdlib.ProcessorFormatter` with a `foreign_pre_chain`. Records
   from Django, Dramatiq, Gunicorn and other libraries get the same fields and
   the same sanitising.
3. **Sanitise every event before it is rendered.** The rules are controlled per
   environment:
   - drop a whole event marked sensitive;
   - in **deny** mode, drop keys on `DENY_SENSITIVE_KEYS`;
   - in **allow** mode, keep only keys on `ALLOW_KEYS`;
   - **off** is allowed only locally, and production refuses it.
4. **Never render exception locals.** There is no setting to turn them on.
5. **Write a rotating file** with `concurrent-log-handler`'s
   `ConcurrentTimedRotatingFileHandler`, which is safe for many processes, in
   addition to stdout. A host cron job deletes old files.
6. **Carry `request_id` into Dramatiq tasks** with a small broker middleware.
   This is gated on a proof of concept (§9).
7. **Return `request_id` to clients**, in an `X-Request-ID` response header and
   in the response `meta`, so a user's error report can be matched to log
   lines.
8. **Migrate all existing `logger.*` calls** to structured events.
9. **Set `CDAC_SMS_PRINT_RESPONSE` to `False` by default.**

## Goals

- Every log line is one structured event with a stable set of base fields.
- Every line emitted while handling a request carries `request_id`, including
  responses produced by early middleware (redirects, CORS preflight, rejected
  hosts). So does every task-scoped line (§9.1) of a task that request
  enqueued.
- The client receives the same `request_id` it can quote to support, on every
  response Django produces. Responses that nginx produces on its own
  (`/static/`, proxy errors) are out of scope (Non-goals).
- No configured sensitive key, and no exception local, ever reaches a handler.
- A single log file can't grow without bound, and old files can be removed by
  age.
- One documented convention that new code and agents follow (§12).

## Non-goals

- Log shipping, an aggregator (ELK, Loki, CloudWatch), dashboards or alerting.
- Error tracking (Sentry).
- Metrics or tracing (OpenTelemetry).
- Audit trails. `simple_history` and `MessageLog` remain the audit stores.
  Logs are operational data.
- Request latency fields (see Future enhancements).
- nginx's own access log. It runs outside Django and is configured in
  `docker/nginx.conf`.
- `X-Request-ID` on responses nginx produces without reaching Django:
  `/static/` (served from the `staticfiles` volume by `location /static/`) and
  nginx-generated errors (`502`/`504` when `web` is down or slow, `413` over
  `client_max_body_size`). These requests write no application log line, so
  there is nothing to correlate. Open question 4 covers having nginx issue the
  id.

---

## Why this approach

### Options considered

1. **Keep stdlib logging and add a JSON formatter** (`python-json-logger`)
   - Pros: one small dependency, no change to call sites.
   - Cons: no context propagation, so each call site would pass `request_id` by
     hand. No processor chain to hang redaction on. `%s` messages stay
     unstructured.

2. **`structlog` + `django-structlog` (selected)**
   - Pros: a processor pipeline (context, redaction, rendering) applied in one
     place. The middleware binds `request_id`, `user_id` and `ip` to
     contextvars, with no change at call sites. Existing `logging.getLogger`
     calls keep working during migration.
   - Cons: two new dependencies. Dramatiq is not covered (Celery is), so task
     context needs our own middleware.

3. **`concurrent-log-handler` on its own**
   - This is a handler, not a logging design. It answers "how do several
     processes safely write and rotate one file". It does nothing for structure,
     context or redaction.
   - **Selected as the file handler** under option 2, because rotation is now a
     requirement.

### File rotation: why `concurrent-log-handler`

| Criterion | stdlib `RotatingFileHandler` / `TimedRotatingFileHandler` | `WatchedFileHandler` + logrotate | `ConcurrentTimedRotatingFileHandler` |
| --- | --- | --- | --- |
| Several processes writing one file | Unsafe. Every process rotates on its own, so lines are lost or files clobbered. | Safe | Safe (file lock, `portalocker`) |
| Rotation owned by | Each process | Host logrotate config | The app |
| Extra moving part | None | logrotate inside the container or on the host | None |
| gzip of rotated files | No | Yes | Yes (`use_gzip`), but it compresses inside `emit()` under the lock, so Dristi compresses by cron instead (§8.1) |
| Fit for Dristi | Low | Medium | **High** |

---

## Technical design

### 1. Dependencies

Add to `src/requirements/base.txt`:

```text
structlog>=25.1.0
django-structlog>=10.1.0,<11
django-ipware>=7.0.1,<8
concurrent-log-handler>=0.9.25
```

**django-structlog is capped below 11.** The repo pins `Django>=5.0,<5.1`.
django-structlog 11.0.0 requires `django>=5.2`. 10.1.0 is the newest release
that supports Django 5.0 (it declares 4.2–5.2 and Python ≥3.10).

10.x has no `DJANGO_STRUCTLOG_TRUST_UPSTREAM_*` settings. It copies the client's
`X-Request-ID` and `X-Correlation-ID` headers into the context unconditionally.
That trust boundary is therefore enforced locally (§5).

When the project moves to Django ≥5.2:
- lift the cap to 11.x;
- replace the local middleware with the library's trust settings.

**django-ipware is listed explicitly** although django-structlog pulls it in.
django-structlog uses it to resolve `ip`, and §5 configures it through
`IPWARE_META_PRECEDENCE_ORDER`, so its version must not float. django-ipware
8.x requires `django>=5.2`, so 7.0.1 is what resolves today. Lift the cap with
django-structlog's.

**Transitive dependencies.** These also arrive and get pinned with the rest:
`python-ipware` (through django-ipware) and `portalocker` (through
concurrent-log-handler, used for the file lock).

The other bounds are placeholders. Pin exact lower bounds against the versions
the PoC (§9) is tested on. `rich` is **not** added, so the console renderer uses
plain tracebacks.

### 2. Module layout

```text
src/apps/core/logs/
├── __init__.py        # get_logger() re-export, module docstring
├── config.py          # configure(): the LOGGING_CONFIG callable (§10.2)
├── processors.py      # rename_status_code, drop_quiet_paths, drop_sensitive_events,
│                      # strip_query_string, sanitise
├── filters.py         # SensitiveRecordFilter, the stdlib counterpart of drop_sensitive_events
├── middleware.py      # RequestIdMiddleware, UserContextMiddleware (§5)
├── dramatiq.py        # LogContextMiddleware (§9)
└── checks.py          # one soft warning (§10.3), imported from CoreConfig.ready()
```

The package is called `logs`, not `logging`, so it can never shadow the stdlib
module.

Settings modules only hold plain `LOG_*` values. `base.py` sets
`LOGGING_CONFIG = "apps.core.logs.config.configure"`. Django calls that function
once, from `django.setup()`, after settings are final. It reads the `LOG_*`
settings, validates them, and then runs `dictConfig` and `structlog.configure()`
together. Nothing has a side effect at settings import time, and the processor
chain lives in one importable place that tests can exercise.

Addons import `structlog` directly. They may import `apps.core.logs`, because
an addon may import from `apps.*` (AGENTS.md). Nothing under `apps.*` imports
an addon.

### 3. Pipeline

```text
structlog.get_logger().info("EVENT", k=v)          logging.getLogger(x).info("%s", v)
        │                                                     │
        ▼  structlog.configure(processors=…)                  ▼  ProcessorFormatter.foreign_pre_chain
  merge_contextvars                                     merge_contextvars
  add_log_level, add_logger_name                        add_log_level, add_logger_name
  TimeStamper(fmt="iso", utc=True)                      TimeStamper(fmt="iso", utc=True)
  rename_status_code      ── code → status_code          ExtraAdder(allow=[…])   (opt-in extras only)
  drop_quiet_paths        ── may raise DropEvent              │
  drop_sensitive_events   ── may raise DropEvent              │
  wrap_for_formatter                                          │
        │                                                     │
        └────────────────────►  ProcessorFormatter.processors  ◄────┘
                                         │
              "json" formatter           │            "console" formatter
              remove_processors_meta     │            remove_processors_meta
              strip_query_string         │            strip_query_string
              ExceptionRenderer(         │            sanitise   ── keeps exc_info
                ExceptionDictTransformer)│            ConsoleRenderer(
              sanitise                   │              exception_formatter=plain_traceback)
              JSONRenderer               │
                                         │
                        ┌────────────────┴────────────────┐
                 StreamHandler (stdout)      ConcurrentTimedRotatingFileHandler
                 formatter: LOG_FORMAT       formatter: always "json"
                                   both carry SensitiveRecordFilter
```

`LOGGING` defines two `ProcessorFormatter`s, `json` and `console`. They share
every processor except exception handling and the final renderer.

`configure()` sets structlog up to log **through stdlib**. Without
`logger_factory` and `wrapper_class`, structlog defaults to `PrintLogger`, and
events would bypass `ProcessorFormatter`, `SensitiveRecordFilter` and both
handlers.

```python
structlog.configure(
    processors=[...],  # the left-hand chain above
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=settings.LOG_CACHE_LOGGERS,  # True; False in test.py
)
```

**Logger caching.** `LOG_CACHE_LOGGERS` is a plain setting, not an env var.
It is `True` in `base.py` and `False` in `test.py`. A logger cached on first use
keeps the processor chain it was built with. `structlog.testing.capture_logs()`
swaps that chain, so with caching on it would miss events from module-level
loggers that had already logged, and results would depend on test order.

Processors that run only in the structlog chain:

- **`rename_status_code`** renames `code` to `status_code`, but only on
  django-structlog's own request events (`request_finished`, `request_failed`,
  `streaming_*`, from the `django_structlog.middlewares.request` logger). There,
  `code` means the HTTP status. Everywhere else in this codebase `code` can mean
  an OTP, so after the rename `code` is denied (§6.2). A `code=` passed by our
  own code is never renamed.
- **`drop_quiet_paths`** drops `request_finished` for paths in
  `LOG_QUIET_PATHS` (default `/health/`, `/static/`) when the status is below
  400. A health poll from 2 replicas would otherwise log forever, while a
  failing health check still logs. `request_started` needs no filter: it is
  logged at `DEBUG` (§5).

Rules that fall out of this shape:

- **`sanitise` runs in `ProcessorFormatter.processors`**, just before the
  renderer. It therefore sees first-party and third-party events alike,
  including context merged from contextvars.
- **In `json`, exceptions are rendered before `sanitise`.** `sanitise` then sees
  the final `exception` field. In `console`, `ConsoleRenderer` formats `exc_info`
  itself, so `sanitise` runs first and keeps `exc_info` (§6.6).
- **The `drop_*` processors run only in the structlog chain.** `DropEvent`
  derives from `BaseException`. Raised inside a formatter, it would escape
  `Handler.emit`'s `except Exception` and crash the caller. The stdlib side
  uses the logging filter `SensitiveRecordFilter` on each handler instead.
- **`SensitiveRecordFilter` handles both record shapes.** On a stdlib record
  the flag is the attribute `record.sensitive`, set through `extra=`. On a
  structlog-originated record `record.msg` is the event dict and has no such
  attribute, so the filter also checks
  `isinstance(record.msg, dict) and record.msg.get("sensitive")`. When
  `LOG_DROP_SENSITIVE_EVENTS` is on, a matching record of either shape is
  filtered out. When it is off, the filter passes every record. It never
  raises.
- **Only explicitly listed `extra=` keys are copied.** `ExtraAdder` takes an
  opt-in set, which today is only `sensitive`. This stops objects such as
  `django.request`'s `request` from being serialised. Add a key to the set only
  if it is safe under §6. Every other `extra` key on a stdlib record is
  discarded before `sanitise` runs, so the only fields on a third-party line
  come from the pre-chain and from contextvars.

### 4. Event shape

A log call names an event and passes fields as keyword arguments:

```python
logger = structlog.get_logger(__name__)
logger.info("PDF_RENDERED", key=config.key, version=version, bytes=size, duration_ms=elapsed)
```

| Field | Source | Present on |
| --- | --- | --- |
| `event` | the first argument (an `UPPER_SNAKE` name, §12) | every line |
| `timestamp` | `TimeStamper`, ISO 8601, UTC | every line |
| `level` | `add_log_level` | every line |
| `logger` | `add_logger_name` | every line |
| `request_id` | `RequestIdMiddleware` via django-structlog, or the Dramatiq middleware | request-scoped and task-scoped lines |
| `user_id` | `UserContextMiddleware`, re-bound by django-structlog at `request_finished` | request lines after authentication (§5) |
| `ip` | django-structlog | request-scoped lines |
| `status_code` | `rename_status_code`, from django-structlog's `code` | `request_finished`, `request_failed` |
| `task_id`, `actor` | Dramatiq middleware | task-scoped lines (§9.1) |
| `exception` | the `json` exception renderer | JSON lines logged with `exc_info` (console prints a plain traceback instead) |

`correlation_id` is not used. Its header is always stripped (§5), so it is never
bound. Only `request_id` crosses into tasks.

Existing domain events keep their current names (`PDF_RENDERED`,
`GATEWAY_REQUEST` and so on). django-structlog's own events keep theirs
(`request_started`, `request_finished`, `request_failed`).

### 5. Request context

Bind the request id **first** and add the user **later**:

```python
MIDDLEWARE = [
    "apps.core.logs.middleware.RequestIdMiddleware",    # 1st: id + trust boundary + response header
    "django_structlog.middlewares.RequestMiddleware",   # 2nd: binds request_id, ip; logs request_*
    "corsheaders.middleware.CorsMiddleware",            # 3rd: moved up, before anything that answers early
    "django.middleware.security.SecurityMiddleware",
    # … WhiteNoise, Session, Common, Csrf …
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.logs.middleware.UserContextMiddleware",  # right after auth: binds user_id
    # … the rest unchanged …
]
```

Putting both request-id middlewares first matters, because Django middleware
can answer a request before later middleware runs. With `RequestMiddleware`
after `AuthenticationMiddleware`, these responses would carry no `request_id`
and have no `request_finished` line:

- `SecurityMiddleware` HTTPS redirects;
- `CommonMiddleware` `APPEND_SLASH` redirects and `DisallowedHost`;
- `CorsMiddleware` preflight responses.

At the top of the list, every request is covered.

**`RequestIdMiddleware`** (outermost) owns the id:

- **Trust boundary.** django-structlog 10.x copies `X-Request-ID` and
  `X-Correlation-ID` from any client (§1), and today's `docker/nginx.conf`
  passes both through untouched. So the middleware:
  - always deletes `HTTP_X_CORRELATION_ID`;
  - keeps an incoming `X-Request-ID` only when `LOG_TRUST_UPSTREAM_REQUEST_ID=True`
    **and** the whole value matches `REQUEST_ID_PATTERN`,
    `re.compile(r"[A-Za-z0-9-]{1,64}")` used with `fullmatch`: 1 to 64
    characters, never empty;
  - otherwise (header absent, empty, too long or with other characters)
    generates `uuid4().hex`.

  The chosen id is therefore always a non-empty string. The Dramatiq middleware
  (§9.1) relies on this and validates propagated ids with the same pattern.
- **It writes the chosen id back into `request.META["HTTP_X_REQUEST_ID"]`.**
  django-structlog 10.x reads that header unconditionally, through
  `request.headers`, so it binds our id instead of generating its own. This
  works only because `request.headers` is a `cached_property` built from
  `META` on first access, and nothing reads it before the outermost
  middleware runs. So `RequestIdMiddleware` itself must read and write
  `request.META` only, never `request.headers`. Reading `request.headers`
  first would cache the client's value, and django-structlog would bind that
  instead.
- **It sets `request.request_id`.**
- **It returns the id to the client**, as the `X-Request-ID` header on every
  response that passes through Django, error pages and WhiteNoise static files
  included. Responses nginx produces on its own carry no id (Non-goals).
  `build_response_meta()` (`apps/api/meta.py`) adds `"request_id"` to the API
  JSON `meta` (spec 0000 §8), reading it from the bound context. It omits the
  key when no id is bound, for example when a response is built outside a
  request. Spec 0000 §8 and the `ResponseMeta` schema example are updated to
  match.
- **Browsers can read the header.** A cross-origin frontend
  (`CORS_ALLOWED_ORIGINS`) can only read response headers that CORS exposes,
  and `X-Request-ID` is not a safelisted header. `base.py` sets
  `CORS_EXPOSE_HEADERS = ["X-Request-ID"]`, so the id is readable on responses
  that have no `meta`, such as file downloads and HTML error pages.
- **`CorsMiddleware` moves up, directly after the two request-id
  middlewares.** It adds CORS headers only to responses that pass back through
  it. Today it sits after `SecurityMiddleware` and `WhiteNoiseMiddleware`, and
  both can return a response without calling the rest of the chain: the HTTPS
  redirect (`SECURE_SSL_REDIRECT` defaults to `True` in `production.py`) and
  WhiteNoise static files. Those responses carry `X-Request-ID` but no CORS
  headers, so a browser can't read them. django-cors-headers documents the same
  rule: place it as high as possible, before any middleware that can generate
  responses, naming WhiteNoise. It still sits inside `RequestIdMiddleware`, so
  its preflight responses keep their id. Nothing else depends on its current
  position.

Turn the trust setting on only after nginx overwrites the header on every
request (Open question 4).

**`UserContextMiddleware`** (directly after `AuthenticationMiddleware`) calls
django-structlog's static `RequestMiddleware.bind_user_id(request)`. In 10.1.0
that method:
- reads `request.user` immediately and binds its primary key as `user_id`
  (`None` for an anonymous user; a `UUID` pk becomes a string);
- then restores `request.session.accessed` if reading the user flipped it.

Don't wrap it in a lazy object. It binds a plain value, which §6.4 renders
unchanged. `request_started` is logged before authentication, so it has no
`user_id`. Every later line has one, and django-structlog binds it again for
`request_finished`.

| Setting | Value | Why |
| --- | --- | --- |
| `DJANGO_STRUCTLOG_USER_ID_FIELD` | `"pk"` (default) | |
| `DJANGO_STRUCTLOG_IP_LOGGING_ENABLED` | `True` (default) | Needed for abuse investigation. Only useful with the `IPWARE_*` setting below. |
| `DJANGO_STRUCTLOG_STATUS_START_LOG_LEVEL` | `logging.DEBUG` | `request_started` would roughly double the line count. `request_finished` carries the same `request` field. |
| `DJANGO_STRUCTLOG_STATUS_2XX_LOG_LEVEL` | `logging.INFO` (default) | |
| `DJANGO_STRUCTLOG_STATUS_4XX_LOG_LEVEL` | `logging.WARNING` (default) | |
| `DJANGO_STRUCTLOG_STATUS_5XX_LOG_LEVEL` | `logging.ERROR` (default) | |

django-structlog 10.x has no setting to ignore a path. `drop_quiet_paths` (§3)
does that job.

**Client IP.** django-structlog binds `ip` from django-ipware's
`get_client_ip(request)`, called with no arguments. By default that checks
`X-Forwarded-For` first and takes its **left-most** address. `docker/nginx.conf`
sets `X-Forwarded-For` to `$proxy_add_x_forwarded_for`, which appends to
whatever the client sent, so the left-most address is chosen by the client.
nginx overwrites `X-Real-IP` with `$remote_addr`, and `web` publishes no port in
the production compose, so every request reaches Django through nginx. So
`base.py` sets:

```python
# nginx overwrites X-Real-IP; X-Forwarded-For is client-controlled.
IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_REAL_IP", "REMOTE_ADDR")
```

If a load balancer is ever placed in front of nginx, `$remote_addr` becomes the
balancer's address. nginx must then restore the client address with its
`real_ip` module (`set_real_ip_from` the balancer, `real_ip_header
X-Forwarded-For`) before this setting gives the right answer.

**One closing event per request.** django-structlog 10.1.0 logs exactly one of
these:
- `request_finished` (with `code`, then `status_code`) when the view returns a
  response, whatever its status. A health check that fails by returning a 500
  response logs `request_finished`.
- `request_failed` (logged with `exc_info`, `code=500`) when the view raises.
  `request_finished` is then skipped.

`drop_quiet_paths` only ever drops `request_finished` with a status below 400.
It never drops `request_failed`.

Notes:

- **`user_id` and DRF.** `DEFAULT_AUTHENTICATION_CLASSES` today contains only
  `SessionAuthentication`. That class reads the same user that
  `AuthenticationMiddleware` set, so `user_id` is correct on every line after
  `UserContextMiddleware`. This changes only when `TokenAuthentication` is wired
  (spec 0000 §6.3). A token-authenticated user is resolved inside the DRF view,
  so that change must also rebind `user_id` in its authentication class.
  Nothing needs building for it today.
- **Query strings.** django-structlog 10.1 logs `request` as
  `f"{request.method} {request.get_full_path()}"`, which includes the query
  string. Query parameters can carry phone numbers, OTPs or tokens, so
  `strip_query_string` cuts everything from `?` onward in the `request` field.

### 6. Sensitive data

#### 6.1 Three controls, chosen per environment

| Control | What it does | Setting |
| --- | --- | --- |
| Drop the event | Removes the whole event when the call marks it `sensitive=True` | `LOG_DROP_SENSITIVE_EVENTS` |
| Deny mode | Removes every key that matches `DENY_SENSITIVE_KEYS` and keeps the rest | `LOG_REDACTION_MODE=deny` |
| Allow mode | Keeps only keys in `ALLOW_KEYS` and removes the rest | `LOG_REDACTION_MODE=allow` |
| Off | Removes no keys. For a developer debugging locally, for example an OTP flow. | `LOG_REDACTION_MODE=off` |

The modes are exclusive. Production refuses `off` at startup (§10.3). Dropping
events is independent of the mode. When dropping is off, a `sensitive=True`
event is still rendered, with the active mode applied. In every mode, `sanitise`
removes the `sensitive` flag itself before rendering.

#### 6.2 Deny keys

```python
DENY_SENSITIVE_KEYS = {
    "password",
    "token",
    "access_token",
    "authorization",
    "api_key",
    "secret",
    "license_no",
    "pan",
    "phone",
    "email",
    # Dristi additions
    "mobile",
    "mobile_number",
    "mobileno",
    "phone_number",
    "otp",
    "aadhaar",
    "refresh_token",
    "cookie",
    "secure_key",
    "session",
    "private_key",
    "signature",
    "dob",
    "address",
    "full_name",
    "first_name",
    "last_name",
    "username",
    # Compound names with no underscore before the sensitive word
    "csrftoken",
    "csrfmiddlewaretoken",
    "sessionid",
    "apikey",
    # Sensitive word followed by a qualifier, which suffix matching misses
    "phone_number_at_filing",
}

# Matched exactly, never as a suffix (see below)
DENY_EXACT_KEYS = {"code", "name"}
```

`LOG_DENY_KEYS_EXTRA` (comma-separated) adds keys to `DENY_SENSITIVE_KEYS` per
environment. Its keys are added to the set and never replace it.

Matching rules:

- Keys are lower-cased and `-` becomes `_` before comparison.
- A key matches a `DENY_SENSITIVE_KEYS` entry when it **equals** the entry or
  **ends with `_<entry>`**. So `user_email`, `recipient_phone`, `x_api_key`,
  `ip_address` and `db_session` match.
- A key matches a `DENY_EXACT_KEYS` entry only when it **equals** it. Suffix
  matching on `code` or `name` would remove `status_code`, `error_code`,
  `file_name` and `queue_name`. So `code` (an OTP in this codebase, §3) and
  `name` (a person's name) are denied exactly. Name-like compounds are listed
  explicitly above.
- Substring matching is deliberately not used. `pan` would otherwise remove
  `company`, `panel` and `expand`.
- **Suffix matching needs the underscore.** A rule that also matched a bare
  suffix would remove `span` and `japan` (for `pan`). So compound names with no
  underscore (`csrftoken`, `sessionid`, `apikey`) are listed explicitly.
- **A qualifier after the sensitive word defeats suffix matching.**
  `phone_number_at_filing` (`apps/cases/serializers.py`) ends with
  `_at_filing`, so it is listed explicitly. Prefix matching is not used
  instead, because it would remove useful fields such as `address_id` and
  `signature_valid`. A test (§14 item 1) catches new names of this shape.
- Matching recurses into `dict` values, and into `list` and `tuple` values
  containing dicts. The gateway's `body` form is therefore cleaned too.
- A matching key is removed, not masked. A masked value still leaks length and
  prefix.

#### 6.3 Allow keys

`ALLOW_KEYS` has two parts:

- **Base set, always allowed:** every §4 field (including `status_code`), plus
  django-structlog's `request` and `user_agent`, plus `exc_info` for the console
  formatter (§6.6). `code` is **not** in it. It is renamed to `status_code` on
  request events (§3) and denied everywhere else (§6.2).
- **Extras:** the field names that migrated call sites use, maintained in
  `apps/core/logs/processors.py` next to the base set. Today these are
  `message_id`, `message_key`, `attempt`, `job_id`, `file_id`, `transaction_id`,
  `provider_transaction_id`, `status`, `error_code` and so on. Fill in the full
  list during migration (§11). `LOG_ALLOW_KEYS_EXTRA` adds keys per environment.

Allow mode applies recursively. An allowed key holding a dict keeps only its
allowed sub-keys. In allow mode, adding a field to a log call also means adding
it to the allow set, and a test (§14) fails if a migrated call site logs a key
outside it.

#### 6.4 Value types

After key filtering, `sanitise` makes every value safe to render. Without this
step, `JSONRenderer` and `ConsoleRenderer` fall back to `repr()`/`str()`, so a
model instance passed under an allowed key could leak a name or phone number
through its `__str__`.

| Value | Rendered as |
| --- | --- |
| `str`, `int`, `float`, `bool`, `None` | unchanged |
| `dict`, `list`, `tuple` | recursed into, with the same rules |
| `uuid.UUID`, `datetime`/`date`/`time`, `Decimal` | `str(value)` (ids and timestamps stay readable) |
| `Enum` | `value.value`, then the rules above |
| anything else (model instances, querysets, requests, objects) | its type name, for example `"<User>"` |

`exc_info` and `exception` are exempt, because §6.6 handles them. The coercion
applies in every mode, `off` included.

#### 6.5 Free text

Redaction works on keys. It can't see a phone number formatted into the `event`
string or into a `%s` message from a stdlib logger. Three rules follow:

- **First-party code must not format values into the event.** No f-strings, no
  `%s`, no `.format()` in the event argument. This is enforced by review and by
  the §12 convention, and §11 removes every existing case.
- **Third-party messages are not rewritten.** Their levels are raised instead
  (§7), so DEBUG-level request and SQL detail never reaches a handler.
- **Exception messages (`str(exc)`) are free text.** Log them under a `reason`
  key only when the exception comes from our own code or from a library known
  not to echo input. `addon/cdac_esign/provider.py:86,147` is reviewed against
  this rule during migration.

#### 6.6 Exceptions and locals

structlog's `ExceptionDictTransformer` defaults to `show_locals=True`, and so does
`RichTracebackFormatter`. A frame's locals can hold passwords, OTPs, keys and
whole request bodies.

Locals can't be redacted after the transformer runs. It renders each local as
a `repr()` string, so `payload={"phone": "…"}` reaches `sanitise` as the text
`"{'phone': '…'}"`, which key matching can't see into. So locals are never
collected at all.

Each formatter handles exceptions with its own processor, because a console
formatter can't consume a traceback that has already been turned into dicts:

- **JSON:** `ExceptionRenderer(ExceptionDictTransformer(show_locals=False, use_rich=False))`
  runs **before** `sanitise`. It replaces `exc_info` with an `exception` list
  (type, value, frames). `show_locals=False` is hard-coded, in every
  environment and every redaction mode, `off` included.
- **Console:** no exception processor. `exc_info` is left for
  `ConsoleRenderer(exception_formatter=structlog.dev.plain_traceback, colors=sys.stdout.isatty())`,
  which never prints locals. `rich` is not installed (§1). structlog enables
  colours by default on non-Windows systems, which would put ANSI codes into
  `docker compose logs` and test output.
- **No setting enables locals.** A developer who needs them uses a debugger.

**How `sanitise` treats exceptions** (nested exception policy):

- **`exception` and `exc_info` are always kept, in every mode.** They are in the
  allow base set (§6.3), so allow mode never drops a traceback.
- **`sanitise` does not filter the transformer's own structure** (`exc_type`,
  `exc_value`, `frames`, `filename`, `lineno`, `name`). That structure is
  library-defined and holds no request data. Frames never carry `locals`.
- **The exception message (`exc_value`, and the text in a console traceback)**
  is free text. Keys can't redact it, so the §6.5 rules apply: don't raise
  exceptions whose message contains user input.
- **`sanitise` keeps only the first line of every `exc_value`** in the JSON
  `exception` list, including chained causes, in every mode except `off`.
  Library exceptions carry user data that our rules can't prevent. With
  psycopg 3, `str()` of a database error is PostgreSQL's full error message,
  for example:

  ```text
  duplicate key value violates unique constraint "users_user_mobile_number_key"
  DETAIL:  Key (mobile_number)=(9876543210) already exists.
  ```

  Django's `IntegrityError` copies that text. PostgreSQL puts the summary on
  the first line and the row values on `DETAIL` lines, so keeping the first
  line keeps the diagnosis and drops the values. The transformer records only
  the class name (`exc_type.__name__`), so the rule can't be limited to
  database errors by type. It applies to every exception.
- **Console output prints the full message.** `plain_traceback` formats the
  live exception, so the first-line rule can't apply to it. So `console` is
  for local and test only, and `production.py` refuses it (§10.3). The file
  handler is always `json` whatever `LOG_FORMAT` says.

#### 6.7 Defaults per environment

| Setting | local | test | production |
| --- | --- | --- | --- |
| `LOG_REDACTION_MODE` | `deny` (`off` allowed) | `deny` | `deny` (see Open questions); `off` refused |
| `LOG_DROP_SENSITIVE_EVENTS` | `False` | `False` | `True` |
| `LOG_FORMAT` | `console` | `console` | `json`; `console` refused |

### 7. Third-party loggers

Third-party libraries use stdlib `logging`, so they skip the structlog chain. To
handle them:

- **Route all formatting through the shared processors.** Every handler in
  `LOGGING` uses one of the two `ProcessorFormatter`s (§3). `sanitise`,
  `strip_query_string` and the formatter's exception handling therefore apply
  to every record, whatever logger it came from.
- **Keep the existing named loggers.** `django`, `dramatiq`, `cachalot`,
  `apps.messaging`, `apps.pdf` and `addon.cdac_sms_gateway` keep their
  `propagate: False` entries and point at the same handlers. No logger keeps a
  handler outside the pipeline.
- **Take over `django.server`.** Django applies its `DEFAULT_LOGGING` before
  calling `configure()`. That config gives `django.server` (runserver's access
  log, which prints full paths with query strings) its own plain handler and
  `propagate: False`. With `disable_existing_loggers: False` it would survive
  our config and bypass redaction. `configure()` therefore **silences**
  `django.server`:
  - its access lines carry the full URL, query string included, inside the
    message text, where `strip_query_string` can't reach it;
  - Django logs them at `INFO` for 1xx–3xx, `WARNING` for 4xx and `ERROR` for
    5xx, so pinning a level would still leak `/x?token=…` on a 404 or a 500;
  - django-structlog's `request_finished` / `request_failed` already cover
    access logging, with the query string stripped.

  So `django.server` gets `{"handlers": ["null"], "propagate": False}`, where
  `null` is a `logging.NullHandler`. The handler list must not be empty: a
  logger with no handlers and `propagate: False` falls back to
  `logging.lastResort`, which prints `WARNING` and above to stderr, outside the
  pipeline.

  `django` is declared explicitly too, so its default `mail_admins` handler is
  replaced by ours.
- **Pin levels regardless of `LOG_LEVEL`:**

  | Logger | Level | Reason |
  | --- | --- | --- |
  | `django.db.backends` | `WARNING` | At DEBUG it logs SQL with parameter values |
  | `django.request`, `django.security` | `WARNING` | |
  | `django.server` | silenced (`NullHandler`) | runserver access lines put the full URL in the message text at every level |
  | `urllib3`, `requests` | `WARNING` | At DEBUG they log full URLs |
  | `botocore`, `boto3`, `s3transfer` | `WARNING` | At DEBUG they log request headers, including auth |
  | `pyhanko`, `signxml` | `WARNING` | Signing detail |
  | `gunicorn.error` | `INFO` | Routed through `LOGGING` (see below) |

  `LOG_LEVEL` sets the root level and the first-party loggers only.

- **Gunicorn.** Remove `--access-logfile -` from `docker/entrypoint.sh`.
  django-structlog's `request_finished` replaces the access log, and the access
  log would otherwise print full URLs, query strings included, outside the
  pipeline. Add `gunicorn.error` to `LOGGING`, so worker-level errors render
  through the formatter once Django's `dictConfig` runs in each worker. The
  master process's own startup lines stay in Gunicorn's plain format, which is
  acceptable.
- **Dramatiq CLI.** The `dramatiq` main process sets up its own stderr logging
  before it forks. Worker processes apply `LOGGING` when Django starts. The PoC
  (§9) checks that worker output is structured and that the main process's
  lines are the only plain ones.

### 8. Output and rotation

#### 8.1 Handlers

- **`console`.** A `logging.StreamHandler` with `"stream": "ext://sys.stdout"`.
  Without an explicit stream it writes to stderr. It is always on, so
  `docker compose logs` keeps working.
- **`file`.** `concurrent_log_handler.ConcurrentTimedRotatingFileHandler`, on
  when `LOG_FILE_ENABLED=True`. It always uses the `json` formatter, whatever
  `LOG_FORMAT` is set to.

```python
"file": {
    "class": "concurrent_log_handler.ConcurrentTimedRotatingFileHandler",
    "filename": f"{LOG_DIR}/{LOG_FILE_PREFIX}-{socket.gethostname()}.log",
    "when": "midnight",
    "utc": True,
    "maxBytes": LOG_FILE_MAX_BYTES,       # size cap inside one day
    "backupCount": LOG_FILE_BACKUP_COUNT,  # hard safety cap, see 8.3
    "use_gzip": False,                     # compressed by cron, see below
    "lock_file_directory": "/tmp/dristi-log-locks",  # inside the container, see below
    "chmod": 0o640,
    "formatter": "json",
    "filters": ["sensitive"],
}
```

- **No in-process gzip.** With `use_gzip=True`, the handler compresses the
  rotated file inside `emit()` while holding the cross-process lock (confirmed
  in the library source: `emit` → `doRollover` → `do_gzip`). The request that
  triggers a rollover would stall for seconds compressing up to
  `LOG_FILE_MAX_BYTES`, and every other worker in the container would block on
  its next log call. Rollover is therefore only a rename. The host cron job
  compresses closed files (§8.3). The PoC (§9.2) measures rollover latency under
  load. If even the rename stalls workers, the fallback is a
  `QueueHandler`/`QueueListener` in front of the file handler. The stdlib
  `QueueHandler.prepare()` formats the record in the calling thread, replaces
  `msg` with the formatted string and clears `exc_info`. So the `json`
  `ProcessorFormatter` and `SensitiveRecordFilter` go on the `QueueHandler`,
  and the file handler behind the listener uses a plain `%(message)s`
  formatter. This also resolves `exc_info=True` while the exception is still
  active.

- **Lock file inside the container, not in `LOG_DIR`.** The handler opens its
  lock file (`.__<LOG_FILE_PREFIX>-<host>.lock`) once per process and never
  writes to it, so its modification time never changes. In the bind-mounted
  `LOG_DIR`, the age-based cron cleanup (§8.3) would delete the lock file of
  any container running longer than `LOG_RETENTION_DAYS`. A worker that
  restarts after that creates a new lock file, while the others keep locking
  the deleted one, so rotations race. The lock is only ever shared within one
  container, so it lives in the container's own filesystem: it disappears with
  the container and is never in reach of the cron job. The handler creates the
  directory if it is missing, and `/tmp` is writable by `appuser`.

- **One file per container.** The hostname, which is the container id in Docker,
  goes in the filename. The processes inside a container (4 Gunicorn workers, or
  2 Dramatiq processes) share that one file through the handler's lock. No lock
  is shared across containers or replicas. This avoids the documented weakness
  of advisory locks on shared or network filesystems.
- **One handler per process.** There is no `--preload`, so every Gunicorn worker
  and every Dramatiq process runs `dictConfig` itself and gets its own handler,
  which the library requires. If `--preload` is ever added, logging must be
  re-initialised after fork (`os.register_at_fork`).

#### 8.2 Container changes

- **`docker/Dockerfile`:**
  - create `/app/logs` before the `chown -R appuser:appuser /app` step;
  - pin `appuser` to a fixed UID and GID (`10001`). Today `useradd -r` assigns
    an arbitrary system UID, so the host directory in the bind mount below
    can't be given the right owner. The host runs
    `chown 10001:10001 "$LOG_HOST_DIR"` once (default `/var/log/dristi`).
  - **Existing hosts.** On any host that already runs the stack, the
    `staticfiles` named volume belongs to the old UID. `entrypoint.sh` runs
    `collectstatic --clear` into it on every start, which would fail with
    permission errors after the UID changes. So re-own the volume once per
    host, before the new image starts:

    ```sh
    docker run --rm -v <project>_staticfiles:/v alpine chown -R 10001:10001 /v
    ```

    Alternatively, remove the volume and let it be recreated.
- **`docker/docker-compose.prod.yml`:**
  - mount `${LOG_HOST_DIR:-/var/log/dristi}:/app/logs` on `web` and `worker`;
  - add a `logging:` block (`json-file`, `max-size: 10m`, `max-file: "5"`) on
    every service, so Docker's copy of stdout is bounded too.
- **`docker/docker-compose.yml` (dev):** no file mount. `LOG_FILE_ENABLED`
  defaults to `False` locally.
- **`.gitignore`:** already ignores `*.log`. Add `logs/`.

#### 8.3 Retention

- **Rotation.** Rotation happens at UTC midnight. A day's file also rotates
  early when it reaches `LOG_FILE_MAX_BYTES`. Rotated files are named
  `<LOG_FILE_PREFIX>-<host>.log.YYYY-MM-DD[.N]`, and cron later gzips them to
  `….gz`. The handler's `backupCount` cleanup counts both the plain and the
  `.gz` forms.
- **Stale files after a redeploy.** Every redeploy gets a new container id, so
  the previous container's live `.log` file stops changing and is never
  rotated. The cron job therefore deletes plain `.log` files by age too. A
  running container's live file is written to and rotated daily, so it stays
  recent. Lock files are not in `LOG_HOST_DIR` (§8.1).
- **Compression and deletion by cron.** A cron job on the host compresses
  rotated files and deletes old ones. The folder, prefix and retention period
  are variables at the top of the cron file. They **must equal** the
  deployment's `LOG_HOST_DIR` and `LOG_FILE_PREFIX`, or files fall outside the
  patterns:

  ```cron
  # /etc/cron.d/dristi-logs
  # Keep these in sync with the deployment's LOG_HOST_DIR and LOG_FILE_PREFIX.
  LOG_HOST_DIR=/var/log/dristi
  LOG_FILE_PREFIX=dristi
  LOG_RETENTION_DAYS=30
  # Hourly: gzip rotated files untouched for over 24 hours. The live .log never matches.
  5 * * * * root find "$LOG_HOST_DIR" -maxdepth 1 -type f -name "$LOG_FILE_PREFIX-*.log.20*" ! -name '*.gz' -mtime +0 -exec gzip {} +
  # Daily: delete log and rotated files untouched for LOG_RETENTION_DAYS.
  15 1 * * * root find "$LOG_HOST_DIR" -maxdepth 1 -type f -name "$LOG_FILE_PREFIX-*.log*" -mtime +"$LOG_RETENTION_DAYS" -delete
  ```

  **Why `-mtime +0`.** With `use_gzip=False` the handler checks only whether
  the plain dated name exists before it renames. Once cron has gzipped
  `….log.2026-10-30`, a second size rotation that day reuses the plain name.
  The next gzip then fails with "`….gz` already exists -- skipping", and the
  file stays uncompressed. A file untouched for over 24 hours belongs to an
  earlier UTC day, and rotation only ever names files after the current day,
  so the two can't collide. Uncompressed files wait at most about a day, which
  `LOG_FILE_MAX_BYTES` and `LOG_FILE_BACKUP_COUNT` already bound.

  `docs/production.md` lists these three variables next to the compose env.
  Changing `LOG_HOST_DIR` or `LOG_FILE_PREFIX` on a host means changing them in
  both places.

- **Safety net.** `LOG_FILE_BACKUP_COUNT` is a backstop in case the cron job is
  missing. Set it high enough (default 60) that cron is what normally removes
  files.
- **Documentation.** The cron line and the volume are documented in
  `docs/production.md`.

### 9. Dramatiq context propagation (PoC first)

django-structlog has no Dramatiq integration, so this is our own code. It is
built as a proof of concept first, and is merged only if every PoC check passes.

#### 9.1 Design: `apps.core.logs.dramatiq.LogContextMiddleware`

```python
from apps.core.logs.middleware import REQUEST_ID_PATTERN


def _propagated_request_id(message):
    """Return the propagated request id, or None if absent or malformed."""
    log_context = message.options.get("log_context")
    if not isinstance(log_context, dict):
        return None
    request_id = log_context.get("request_id")
    if isinstance(request_id, str) and REQUEST_ID_PATTERN.fullmatch(request_id):
        return request_id
    return None


class LogContextMiddleware(dramatiq.Middleware):
    def before_enqueue(self, broker, message, delay):
        ctx = structlog.contextvars.get_contextvars()
        if request_id := ctx.get("request_id"):
            message.options["log_context"] = {"request_id": request_id}

    def before_process_message(self, broker, message):
        structlog.contextvars.clear_contextvars()
        context = {}
        if request_id := _propagated_request_id(message):
            context["request_id"] = request_id
        structlog.contextvars.bind_contextvars(
            **context,
            task_id=message.message_id,
            actor=message.actor_name,
        )

    def after_process_message(self, broker, message, *, result=None, exception=None):
        structlog.contextvars.clear_contextvars()

    after_skip_message = after_process_message
```

- **Register it first** in `DRAMATIQ_BROKER["MIDDLEWARE"]`, in `base.py` and in
  `test.py`, ahead of `AgeLimit`, `TimeLimit`, `Callbacks` and `Retries`.
  Dramatiq runs `before_*` hooks in list order and `after_*` hooks in reverse.
  Being first therefore means:
  - its `before_process_message` binds context before any other middleware
    runs, so `AgeLimit`'s and `TimeLimit`'s lines carry it;
  - its `after_process_message` clears context last, so `Retries`' retry and
    give-up lines carry it.
- It clears the context on entry as well as on exit. Worker threads are reused,
  so a missed `after_*` hook must not leak one task's `request_id` into the
  next.
- **`log_context` is untrusted input.** It travels in the serialised message,
  and any producer with broker access can set it through `send_with_options`.
  So `before_process_message` never expands it:
  - it accepts only a `dict`; anything else (`None`, a string, a list) is
    ignored;
  - it reads only `request_id`, and only when it is a string matching
    `REQUEST_ID_PATTERN` (§5); every other key is dropped;
  - `task_id` and `actor` come from the message itself and are always bound,
    so a propagated key can never override them or collide with them.

  This matters because Dramatiq (2.2.1) catches an exception from a `before_*`
  hook, logs it at `CRITICAL` and carries on. A `TypeError` from expanding a
  bad `log_context` would let the task run with no context at all, since the
  context was already cleared.
- **Compatibility.** Messages already queued before this ships have no
  `log_context`, and log with `task_id` and `actor` only. No caller sets
  `log_context` today: the `send_with_options` calls in `apps/pdf/tasks.py`
  and `apps/messaging/tasks.py` pass only `args` and `delay`. Those requeues
  run on the worker thread, so `before_enqueue` re-attaches the task's
  `request_id`. (The `log_context` argument in `addon/cdac_sms_gateway` is an
  unrelated local dict, not a message option.)

**Task-scoped lines**, which carry `task_id`, `actor` and the propagated
`request_id`, are every line emitted on the worker thread between
`before_process_message` and `after_process_message`. That covers:

- the actor body and everything it calls;
- every Dramatiq middleware hook in that window.

**Out of scope:**

- Dramatiq's own ack and nack lines (`Acknowledging message …`,
  `Rejecting message …`). Dramatiq logs them at DEBUG on the **consumer
  thread**, after the after-hooks have run. That is another thread with its own
  context, so no worker-thread middleware can tag them.
- The `dramatiq` main process lines (§7).

The goal and the acceptance criterion about task lines refer to task-scoped
lines only.

#### 9.2 PoC checks

Each check passes or fails.

1. A request that enqueues a task (for example an OTP send) produces worker
   lines with the same `request_id` as the request's `request_finished` line.
   Test this on the real Redis broker, not the stub.
2. `transaction.on_commit` enqueues (`enqueue_sms`) still carry the
   `request_id`, because the commit runs inside the request.
3. Retries (`Retries` middleware) keep `log_context`, because the options are
   copied on requeue.
4. Two tasks that run back to back on the same worker thread never share
   context.
5. A task enqueued outside a request (management command, scheduled job) logs
   with `task_id` and no `request_id`, and raises no error.
6. Worker processes emit JSON through the file handler. Only the `dramatiq` main
   process's startup lines are plain.

The same PoC run also confirms two things outside Dramatiq:

- `gunicorn.error` lines from workers render through the formatter (§7);
- **file rollover latency.** Under load on the web container (4 workers),
  force a size rollover and measure how long the triggering request and
  concurrent log calls block. Without in-process gzip this should be a rename
  of milliseconds. If not, adopt the `QueueHandler` fallback (§8.1).

**If the PoC fails:** ship everything else, keep `task_id` and `actor` binding
(which needs no cross-process transfer), and record the failure under Open
questions.

### 10. Configuration

#### 10.1 Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `LOG_LEVEL` | Root and first-party logger level | `INFO` |
| `LOG_FORMAT` | `json` or `console` for stdout (`console` is refused in production) | `console` locally, `json` in prod |
| `LOG_FILE_ENABLED` | Enable the rotating file handler | `False` locally, `True` in prod |
| `LOG_DIR` | Directory for log files inside the container | `/app/logs` |
| `LOG_FILE_PREFIX` | Filename prefix | `dristi` |
| `LOG_FILE_MAX_BYTES` | Size cap within one day before early rotation; must be positive (§10.3) | `104857600` (100 MB) |
| `LOG_FILE_BACKUP_COUNT` | Safety cap on rotated files kept; must be positive (§10.3) | `60` |
| `LOG_REDACTION_MODE` | `deny`, `allow` or `off` (`off` is refused in production) | `deny` |
| `LOG_DENY_KEYS_EXTRA` | Extra deny keys, comma-separated | empty |
| `LOG_ALLOW_KEYS_EXTRA` | Extra allow keys, comma-separated | empty |
| `LOG_DROP_SENSITIVE_EVENTS` | Drop events marked `sensitive=True` | `False` locally, `True` in prod |
| `LOG_TRUST_UPSTREAM_REQUEST_ID` | Keep a well-formed incoming `X-Request-ID` instead of generating one (§5) | `False` |
| `LOG_QUIET_PATHS` | Path prefixes whose successful `request_finished` is dropped, comma-separated (§3) | `/health/,/static/` |
| `LOG_HOST_DIR` | Host path mounted at `LOG_DIR` (compose and the cron file only) | `/var/log/dristi` |
| `LOG_RETENTION_DAYS` | Age after which the host cron job deletes log files (cron file only, §8.3) | `30` |
| `CDAC_SMS_PRINT_RESPONSE` | **Changed:** default is now `False` | `False` |

Following AGENTS.md:

- add every variable to `.env.example`;
- add the production-relevant ones to `.env.prod.example`;
- read them in `base.py`;
- document them in the `README.md` table.

#### 10.2 Settings by environment

Logging is configured through Django's `LOGGING_CONFIG` hook, not by building
the config at settings import:

```python
# base.py
LOGGING_CONFIG = "apps.core.logs.config.configure"
LOGGING = {"version": 1, "disable_existing_loggers": False}  # must stay non-empty
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOG_FORMAT = env("LOG_FORMAT", default="console")
# … the other LOG_* values from §10.1, plain values only …
LOG_CACHE_LOGGERS = True
```

- **Django calls `configure(LOGGING)` once from `django.setup()`**, after every
  settings module has loaded. Gunicorn workers (through the WSGI app),
  `rundramatiq` workers, management commands and pytest-django all run
  `django.setup()`.
- **`configure()` reads `django.conf.settings.LOG_*`**, validates them (§10.3),
  builds the full `dictConfig` (handlers, both formatters, the named loggers
  and the pinned levels of §7) on top of the `LOGGING` base, applies it, and
  then calls `structlog.configure()`.
- **`LOGGING` must not be empty.** Django calls the `LOGGING_CONFIG` function
  only when `LOGGING` is truthy (`django.utils.log.configure_logging`).

Environment modules therefore only set plain values. There is no "remember to
rebuild" rule:

- **`local.py`:** no changes. The `base.py` defaults are the local ones.
- **`test.py`:**
  - sets `LOG_FORMAT = "console"`, `LOG_FILE_ENABLED = False` and
    `LOG_CACHE_LOGGERS = False` (§3);
  - adds `LogContextMiddleware` to the stub broker's middleware;
  - silences the soft warning (§10.3) with `SILENCED_SYSTEM_CHECKS`. CI runs
    `manage.py check --fail-level WARNING` with test settings, so otherwise it
    would fail on every run.
- **`production.py`:**
  - sets `LOG_FORMAT = env("LOG_FORMAT", default="json")`, `LOG_FILE_ENABLED`
    (default `True`) and `LOG_DROP_SENSITIVE_EVENTS` (default `True`). A
    deployment that forgets them still gets production behaviour.
  - Next to the existing "Addon guards", raises `ImproperlyConfigured` when
    `LOG_REDACTION_MODE=off` or `LOG_FORMAT` is not `json`. This is the same
    pattern as `CDAC_SMS_VERIFY_SSL`. `LOG_FORMAT` stays an env read, so a
    `console` override fails loudly at startup instead of being silently
    ignored.
- **`.env.ci`:** sets `LOG_DIR=/tmp/dristi-ci-logs`. The CI deploy check loads
  production settings, where the file handler is on by default, and
  `/app/logs` doesn't exist on the runner.

#### 10.3 Validation

Most of this validation can't be a system check:
- `rundramatiq` and Gunicorn never run checks;
- a bad value would already have broken `dictConfig` inside `django.setup()`,
  before any check ran.

So the hard failures live in `configure()`.

**`configure()` raises `ImproperlyConfigured`** with a message naming the
setting when:

- `LOG_REDACTION_MODE` is not `deny`, `allow` or `off`;
- `LOG_FORMAT` is not `json` or `console`;
- `LOG_LEVEL` is not a standard level name;
- `LOG_FILE_MAX_BYTES` or `LOG_FILE_BACKUP_COUNT` is not a positive integer.
  `concurrent-log-handler` treats `maxBytes=0` as "no size rotation" and
  `backupCount=0` as "delete nothing", so a typo would silently remove the disk
  caps of §8.3. Both are checked whether or not the file handler is on, so a
  bad value fails before it is first enabled;
- `LOG_FILE_ENABLED=True` and `LOG_DIR` can't be created
  (`os.makedirs(..., exist_ok=True)`) or isn't writable (`os.access(..., W_OK)`).
  This is checked before `dictConfig` would fail inside the file handler.

**Production guards (`production.py`, `ImproperlyConfigured`):**

- `LOG_REDACTION_MODE=off`
- `LOG_FORMAT` other than `json`. Console output can't apply the first-line
  rule for exception messages (§6.6).

**System checks (`apps/core/logs/checks.py`)** hold soft warnings only. It is
imported from `CoreConfig.ready()`, like `apps/pdf/checks.py` and
`apps/esign/checks.py`:

| Check | Level |
| --- | --- |
| `logs.W001`: `LOG_FILE_ENABLED=False` while `DEBUG=False` | Warning (silenced in `test.py`) |

### 11. Migration of existing log calls

Every `logger.*` call under `src/apps` and `src/addon` moves to
`structlog.get_logger(...)` with an event name and keyword fields. That is about
70 call sites, counting the `log_event` and `_log_event` helpers, in the 21
modules that call `logging.getLogger`. Logger names don't change, so the
`LOGGING` entries keep matching.

| Area | Files | Change |
| --- | --- | --- |
| OTP | `apps/users/services/otp.py:152` | `logger.info("OTP_QUEUED", purpose=purpose)`. No phone number and no code. Redaction is a safety net, not something a call site relies on (§12 rule 3). `_send_sms()` has no user in scope; the request's bound `user_id`, if any, comes from context. |
| eSign | `apps/esign/log.py` | `log_event()` keeps its signature and emits `logger.log(level, event, **fields)` instead of joining a string. Call sites don't change. |
| eSign addon | `addon/cdac_esign/provider.py:86,147,150` | Structured fields. `reason=str(exc)` is reviewed against §6.5. |
| Messaging | `apps/messaging/tasks.py` | `_log_event()` emits keyword fields. Remove the `fields` string join. |
| SMS gateway | `addon/cdac_sms_gateway/{client,response,filtering}.py` | Structured fields. `mask_form()` stays as defence in depth, because the gateway owns its wire secrets, and the form gains `mobileno` coverage from the deny list. |
| SMS default | `base.py:500`, `addon/cdac_sms_gateway/config.py:42,102`, `.env.example:91`, `README.md:195`, `addon/cdac_sms_gateway/tests/test_config.py:40` | `CDAC_SMS_PRINT_RESPONSE` defaults to `False`. Update the test that asserts the old default. |
| PDF | `apps/pdf/tasks.py`, `apps/pdf/services/*` | Replace `event=%s ...` strings and `" ".join(f"{k}={v}")` with keyword fields. `log_event()` in `apps/pdf/services/generator.py` keeps its signature, like the eSign helper. |
| Requests | `apps/dristi_requests/hooks.py:112` | Logs the request type under the bare name `code`. Migrate to `logger.info("HOOK_RUN", on=on, request_pk=request.pk, request_type=code)`, because `code` is denied (§6.2). |
| Others | `apps/users/tasks.py`, `apps/address/services.py`, `apps/files/documents.py`, `apps/dristi_requests/services.py`, `apps/cases/services/services.py`, `apps/core/rules/engines/base.py` | Turn sentence-style messages into an event name plus fields |

Tests that assert on log text move to `structlog.testing.capture_logs()` and
assert on `event` and field values. Twelve test files use `assertLogs` or
`caplog` today:

- `addon/cdac_sms_gateway/tests/test_{backend,response,delivery,filtering}.py`
- `apps/esign/tests/test_{security,callback,clients}.py`
- `apps/pdf/tests/test_{signing,tasks}.py`
- `apps/files/tests/test_documents.py`
- `apps/messaging/tests/test_tasks.py`
- `apps/core/tests/test_rules_engines.py`

`apps/esign/tests/test_security.py` asserts that secrets never reach logs. Keep
its intent when you port it.

### 12. Convention for new code (people and agents)

Add this as a "Logging" section in `AGENTS.md` and `CONTRIBUTING.md`:

1. Get a logger with `structlog.get_logger(__name__)`. An addon uses its
   `constants.LOGGER_NAME`.
2. The first argument is an `UPPER_SNAKE` event name and a constant string. Never
   format values into it.
3. Pass data as keyword fields. Use ids (`user_id`, `case_id`, `message_id`),
   never names, phone numbers, emails or document contents. Don't pass a value
   on the assumption that redaction will remove it. Redaction is a safety net.
4. Never use the bare field name `code`. Name what it is: `error_code`,
   `request_type`, `status_code`. Bare `code` is denied (§6.2), because here it
   can be an OTP.
5. Pass plain values (strings, numbers, ids), not model instances or other
   objects. Non-primitive values are rendered as their type name (§6.4).
6. If an event exists only to carry sensitive detail, pass `sensitive=True` so
   production can drop it.
7. Log a new field name in allow mode only after adding it to `ALLOW_KEYS` in
   `apps/core/logs/processors.py`.
8. Use `logger.exception(...)`, or `exc_info=True`, for errors. Never log
   `locals()`, request bodies or serializer `initial_data`.
9. In tests, assert on `event` and fields with `structlog.testing.capture_logs()`,
   not on rendered text.

### 13. Affected files

```text
src/requirements/base.txt                       # + structlog, django-structlog, django-ipware, concurrent-log-handler
src/apps/core/logs/                             # new package (§2)
src/apps/core/apps.py                           # import logs.checks in ready()
src/apps/api/meta.py, src/apps/api/schema.py    # request_id in meta and the ResponseMeta example
src/config/settings/base.py                     # MIDDLEWARE, LOGGING_CONFIG, LOG_* values, DJANGO_STRUCTLOG_*, IPWARE_META_PRECEDENCE_ORDER, CORS_EXPOSE_HEADERS, Dramatiq middleware, CDAC default
src/config/settings/test.py                     # stub broker middleware, LOG_* values, LOG_CACHE_LOGGERS, silenced W001
src/config/settings/production.py               # prod LOG_* defaults, guards
.env.ci                                         # LOG_DIR for the CI deploy check
spec/0000-api-coding-spec.md                    # §8: request_id in meta
docker/entrypoint.sh                            # drop --access-logfile
docker/Dockerfile                               # create /app/logs, fixed appuser UID/GID
docker/docker-compose.prod.yml                  # log volume, logging driver limits
.env.example, .env.prod.example, README.md      # §10.1
docs/production.md                              # volume and cron retention
AGENTS.md, CONTRIBUTING.md                      # §12 convention
.gitignore                                      # logs/
src/apps/**, src/addon/**                       # §11 migration
```

### 14. Testing

Tests go in `apps/core/tests/test_logs_*.py` unless noted. They run with
`LOG_CACHE_LOGGERS=False` (§3), so `capture_logs()` results don't depend on
test order.

1. **Sanitise, deny mode:**
   - every model field name (`django.apps.apps.get_models()`) and every
     declared field of a `Serializer` subclass in `apps.*.serializers` that
     contains `phone`, `mobile`, `email`, `aadhaar`, `otp`, `password`, `dob`
     or `pan` as an underscore-separated word is denied, unless it is on a
     short reviewed exemption list in the test (for example `mobile_prefix`);
   - exact keys and `_<entry>` suffix keys are removed;
   - `csrftoken`, `sessionid` and `apikey` are removed;
   - `code` and `name` are removed, while `status_code`, `error_code` and
     `file_name` survive;
   - nested dicts and lists are cleaned;
   - `company`, `panel`, `expand` and `span` survive.
2. **Sanitise, allow mode:** unknown keys are removed; base fields survive;
   nested dicts are filtered.
3. **Value types:**
   - a model instance under an allowed key renders as `"<User>"`, never its
     `__str__`;
   - a `UUID`, a `datetime` and a `Decimal` render as their string;
   - an arbitrary object renders as its type name.
4. **Drop sensitive events:**
   - with the setting on, a `sensitive=True` structlog event is dropped, and so
     is a stdlib record with `extra={"sensitive": True}`;
   - `SensitiveRecordFilter` is unit-tested on both record shapes: a stdlib
     record with the attribute, and a record whose `msg` is a structlog event
     dict carrying `sensitive`;
   - with the setting off, both are rendered and the flag is removed;
   - nothing raises.
5. **Exceptions:**
   - an exception raised with locals `password = "x"` and
     `payload = {"phone": "9999999999"}` renders without either value in JSON
     and console output, and no JSON frame has a `locals` key, in `deny`,
     `allow` **and** `off` mode;
   - in allow mode, a `logger.exception(...)` still renders its traceback (the
     `exception` field in JSON, a plain traceback in console);
   - an exception whose message is `"summary\nDETAIL:  Key (mobile_number)=(9876543210) already exists."`,
     raised from another exception with a similar message, renders in JSON
     with only `"summary"` as `exc_value` in every stack, in `deny` and
     `allow` mode.
6. **Third-party records:**
   - a `logging.getLogger("django.request")` record with
     `extra={"phone": "…", "request": object()}` renders without either key,
     because `ExtraAdder` copies only `sensitive`;
   - a stdlib record logged while a denied key is bound in contextvars renders
     without that key.
7. **Request events:**
   - `strip_query_string` is tested directly on `{"request": "GET /x?phone=1"}`;
   - a test-client `GET` with a query string produces a `request_finished`
     line whose `request` has no `?`;
   - that line has `status_code` and no `code`;
   - a first-party `logger.info("X", code="123456")` renders without `code`;
   - `request_started` is not emitted at `INFO`;
   - a successful `GET /health/` produces no `request_finished` line;
   - a health check whose view **returns** a 500 response (for example a failing
     backend check) produces `request_finished` with `status_code=500`;
   - a view under a quiet path that **raises** produces `request_failed`, which
     is never dropped;
   - after `configure()`, `logging.getLogger("django.server")` has only a
     `NullHandler` and `propagate=False`; access lines for
     `GET /x?token=abc` logged at `INFO`, `WARNING` (404) and `ERROR` (500)
     reach neither handler nor stderr (`lastResort`).
8. **Request id and trust boundary:**
   - two log calls inside one test-client request share the `request_id` of
     `request_finished`;
   - the response carries the same value in `X-Request-ID` and in `meta`;
   - a request that early middleware answers, such as an `APPEND_SLASH`
     redirect or a `DisallowedHost`, still gets a `request_id` and a
     `request_finished` or `request_failed` line;
   - a request sent with `X-Request-ID: forged` and `X-Correlation-ID: forged`
     gets a generated `request_id` and no `correlation_id`;
   - with `LOG_TRUST_UPSTREAM_REQUEST_ID=True`, a well-formed `X-Request-ID` is
     kept, and an empty, too long (65 characters) or badly formed one is
     replaced with a generated id;
   - a non-API response, such as the Django 404 page or `/health/`, carries
     `X-Request-ID`. (WhiteNoise is removed in `test.py`, so static files are
     not tested here);
   - a cross-origin request from an allowed origin gets
     `Access-Control-Expose-Headers` containing `X-Request-ID`;
   - with `SECURE_SSL_REDIRECT=True`, a plain-HTTP request from an allowed
     origin gets the redirect with `Access-Control-Allow-Origin`,
     `Access-Control-Expose-Headers` and `X-Request-ID`;
   - in `base.py`'s `MIDDLEWARE`, `CorsMiddleware` comes before
     `SecurityMiddleware` and `WhiteNoiseMiddleware`. (`test.py` removes
     WhiteNoise, so the order is asserted on the base list instead of with a
     static request);
   - a request with `X-Forwarded-For: 1.2.3.4` and `X-Real-IP: 5.6.7.8` binds
     `ip=5.6.7.8`.
9. **User context:** a view line inside a session-authenticated request carries
   that user's `user_id`. `request_started` has none.
10. **Routing through stdlib:** with `LOG_FILE_ENABLED=True` and a temporary
    `LOG_DIR`, a migrated event logged through `structlog.get_logger(...)` with
    a denied field appears on stdout **and** in the file, with the denied field
    removed in both. This guards the `logger_factory` configuration (§3).
11. **Dramatiq (stub broker):**
    - a task enqueued inside a bound context logs that `request_id`;
    - a task enqueued outside one logs only `task_id` and `actor`;
    - back-to-back tasks don't leak context;
    - a message whose `log_context` is `None`, a string, a dict with an empty,
      non-string or malformed `request_id`, or a dict carrying `task_id`,
      `actor` or other extra keys runs normally, logs no `CRITICAL` middleware
      failure, binds the message's own `task_id` and `actor`, and binds
      `request_id` only when it is valid;
    - `LogContextMiddleware` is first in the configured middleware list.
12. **File handler:** with `LOG_FILE_ENABLED=True` and a temporary `LOG_DIR`,
    several processes (`multiprocessing`) write to one file without
    interleaving lines. Forcing a rollover produces a dated, uncompressed
    backup, and `emit()` never gzips. No lock file is created in `LOG_DIR`.
13. **Configuration and validation:**
    - `configure()` raises `ImproperlyConfigured` for an invalid
      `LOG_REDACTION_MODE`, `LOG_FORMAT` or `LOG_LEVEL`, for a
      `LOG_FILE_MAX_BYTES` or `LOG_FILE_BACKUP_COUNT` of `0` or below, and for
      an unwritable `LOG_DIR` when the file handler is on;
    - `LOGGING_CONFIG` points at `configure`, and `LOGGING` is non-empty;
    - importing production settings with `LOG_REDACTION_MODE=off` or
      `LOG_FORMAT=console` raises `ImproperlyConfigured`, and with neither set
      gives `LOG_FORMAT == "json"`;
    - `logs.W001` fires with `DEBUG=False` and the file handler off, and is
      silenced under test settings.

    Two rules for writing these tests:

    - **Restore global logging.** `configure()` reconfigures logging for the
      whole process. A test that calls it with other settings, for example
      under `override_settings`, must call `configure(settings.LOGGING)` again
      during teardown (a fixture's `yield` / `addCleanup`), so later tests see
      the test-settings pipeline.
    - **Import production settings in isolation.** `production.py` reads
      required env vars (`SECRET_KEY`, `ALLOWED_HOSTS` and the others in
      `.env.ci`). Patch them with `mock.patch.dict(os.environ, …)`, then import
      `config.settings.production` freshly (`importlib.import_module` after
      removing it from `sys.modules`). Never replace the live settings.
14. **Migration:**
    - the OTP send logs `OTP_QUEUED` with `purpose` and nothing else;
    - the CDAC default for `print_response` is `False`;
    - an allow-mode test runs the migrated call sites and fails on any key
      missing from `ALLOW_KEYS`.

Run `ruff check .`, `ruff format .`, `python manage.py check` and the test suite
before merging.

## Rollout plan

1. **PoC (§9).**
   - Wire structlog, the Dramatiq middleware and the file handler on a branch.
   - Run the §9.2 checks on the dev compose stack with the real Redis broker.
   - Record the results in this spec.
2. **Foundation.**
   - Add the dependencies, `apps/core/logs/`, the settings and the system checks.
   - Make the Docker and compose changes.
   - Update the env files, README and production docs.
   - Make the `CDAC_SMS_PRINT_RESPONSE` default change.
3. **Migration (§11).** Migrate one area per commit (OTP and SMS first, then
   eSign, messaging, PDF, others) and update tests as you go.
4. **Convention.** Add the AGENTS.md and CONTRIBUTING.md section.
5. **Each deployed environment.** On each host, when the release containing
   step 2 is deployed:
   - before the new image starts, re-own the `staticfiles` volume if it exists
     (§8.2);
   - create `LOG_HOST_DIR` (default `/var/log/dristi`) on the host and `chown`
     it to `10001:10001`;
   - install the cron entry (§8.3), with its variables matching this host's
     `LOG_HOST_DIR` and `LOG_FILE_PREFIX`.

   Under `production.py`, JSON output, the file handler and dropping sensitive
   events are the defaults (§10.2). An environment on another settings module
   sets these through the logging env vars (§10.1).

   Tell the team that log output changes from plain text to JSON, so anyone
   grepping `docker logs` for `event=...` knows.

## Acceptance criteria

- Every request-scoped line carries `request_id`. Every task-scoped line (§9.1)
  of a task enqueued by that request carries the same `request_id`, provided the
  PoC passed. This includes responses produced by early middleware. A
  client-supplied `X-Request-ID` or `X-Correlation-ID` is never used unless
  `LOG_TRUST_UPSTREAM_REQUEST_ID=True`.
- Every response that passes through Django carries a non-empty
  `X-Request-ID`, exposed to cross-origin callers, and every API JSON response
  (the ones with a `meta` block) carries the same value as `meta.request_id`. Responses nginx serves or generates on its own
  (`/static/`, `502`/`504`/`413`) are excluded (Non-goals).
- Successful health and static requests produce no `request_finished` line.
  `request_started` is not logged at `INFO`.
- Logs never contain a bare `code` field, and never contain a non-primitive
  value's `__str__`.
- No key on `DENY_SENSITIVE_KEYS` appears in output in deny mode, and no key
  outside `ALLOW_KEYS` appears in allow mode. This holds for first-party and
  third-party records alike.
- With `LOG_DROP_SENSITIVE_EVENTS=True`, events marked sensitive never reach a
  handler.
- No rendered traceback contains frame locals, in any mode or environment.
  In JSON output, no `exc_value` has more than one line unless the mode is
  `off`.
- `ip` is never taken from a client-supplied `X-Forwarded-For`.
  Production settings refuse `LOG_REDACTION_MODE=off` and `LOG_FORMAT=console`.
- `django.server` access lines never reach a handler, at any level.
- A malformed propagated `log_context` never stops a task from binding
  `task_id` and `actor`.
- `configure()` refuses a non-positive `LOG_FILE_MAX_BYTES` or
  `LOG_FILE_BACKUP_COUNT`.
- With the file handler on, each container writes one daily-rotated and
  size-capped file. Rotation never compresses in-process; cron gzips closed
  files. Concurrent processes lose no lines. No lock file lives in
  `LOG_HOST_DIR`.
- No existing `logger.*` call formats values into its message.
  `otp.py` no longer logs the mobile number.
- `CDAC_SMS_PRINT_RESPONSE` defaults to `False` in code, env examples and the
  README.
- `ruff check`, `ruff format`, `manage.py check` and the test suite pass.

## Risks and mitigations

- **Dramatiq propagation doesn't hold** (thread reuse, retries, CLI logging
  setup). Mitigation: the PoC gate in §9, and the fallback of task-local context
  only.
- **Allow mode silently hides a new field.** Mitigation: the allow-list test in
  §14 item 14, and convention rule 7 in §12.
- **django-structlog stays on 10.x while Django is pinned to 5.0** (§1).
  Mitigation: `RequestIdMiddleware` enforces the trust boundary that 11.x
  would provide. Revisit when Django moves to ≥5.2.
- **The cron job is missing on a host, so the disk fills.** Mitigation:
  `LOG_FILE_BACKUP_COUNT` cap, `maxBytes` per day, and the Docker `json-file`
  limits.
- **Lock contention under load** (up to 4 processes on one file per container).
  Mitigation: one file per container, and no gzip inside the lock (§8.1).
  Measure rollover latency in the PoC. If needed, add a
  `QueueHandler`/`QueueListener`, or give each process its own file by adding
  the PID to the filename.
- **A third-party library logs sensitive text inside a message string.**
  Mitigation: pinned levels (§7). Raise a library to `ERROR` if one is found.
- **New dependencies.** Mitigation: all three are pure Python and actively
  released. Pin them after the PoC.
- **The UID change breaks a running deployment.** Existing volumes are owned
  by the old UID. Mitigation: the one-time re-own in §8.2, run as part of
  rollout step 5.

## Open questions

1. **Production redaction mode.** The spec defaults to `deny` everywhere.
   Should production run `allow` from day one, accepting the upkeep of rule 7 in
   §12?
2. **Cron ownership.** Who installs and owns the host cron entry and the
   one-time `chown` of `LOG_HOST_DIR`: ops, or a compose sidecar shipped with
   the repo?
3. **Retention period.** Is 30 days right, or is there a legal or compliance
   requirement?
4. **`X-Request-ID` from nginx.** Should nginx issue the id? One shape:
   `proxy_set_header X-Request-ID $request_id;` (overwrites any client value;
   nginx's `$request_id` is 32 hex characters, so it matches
   `REQUEST_ID_PATTERN`), `proxy_hide_header X-Request-ID;` and
   `add_header X-Request-ID $request_id always;` at `server` level, plus
   `$request_id` in nginx's `log_format`. Then `LOG_TRUST_UPSTREAM_REQUEST_ID`
   can be turned on, `/static/` and nginx-generated errors also carry an id,
   and that id matches the nginx access log. This would bring those responses
   into the acceptance criterion and needs tests on the compose stack.

## Future enhancements (optional)

- `duration_ms` on `request_finished`, using django-structlog's
  `bind_extra_request_metadata` and `bind_extra_request_finished_metadata`
  signals.
- When `TokenAuthentication` is wired (spec 0000 §6.3), rebind `user_id` in its
  authentication class (§5).
- Ship the JSON files to an aggregator.
- Add Sentry, sharing the same `request_id`.
- Value-pattern scrubbing (for example 10-digit mobile numbers) for free-text
  messages, if pinned levels prove insufficient.
