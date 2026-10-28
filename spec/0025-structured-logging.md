# 0025 — Structured Logging (`apps.core.logs`)

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
4. **Never render exception locals.**
5. **Write a rotating file** with `concurrent-log-handler`'s
   `ConcurrentTimedRotatingFileHandler`, which is safe for many processes, in
   addition to stdout. A host cron job deletes old files.
6. **Carry `request_id` into Dramatiq tasks** with a small broker middleware.
   This is gated on a proof of concept (§9).
7. **Migrate all existing `logger.*` calls** to structured events.
8. **Set `CDAC_SMS_PRINT_RESPONSE` to `False` by default.**

## Goals

- Every log line is one structured event with a stable set of base fields.
- Every line emitted while handling a request carries `request_id`, and so does
  every line from a task that request enqueued.
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
| gzip of rotated files | No | Yes | Yes (`use_gzip`) |
| Fit for Dristi | Low | Medium | **High** |

---

## Technical design

### 1. Dependencies

Add to `src/requirements/base.txt`:

```text
structlog>=25.1.0
django-structlog>=9.0.0
concurrent-log-handler>=0.9.25
```

django-structlog is expected to support Django 5.0, which the repo pins
(`Django>=5.0,<5.1`), and Python 3.11. The PoC (§9) confirms this. The bounds
above are placeholders: pin exact lower bounds against the versions the PoC was
tested on. `rich` is **not** added, so
the console renderer uses plain tracebacks.

### 2. Module layout

```text
src/apps/core/logs/
├── __init__.py        # get_logger() re-export, module docstring
├── config.py          # build_logging(): returns the LOGGING dict and calls structlog.configure()
├── processors.py      # drop_sensitive_events, sanitise, strip_query_string
├── filters.py         # SensitiveRecordFilter, the stdlib counterpart of drop_sensitive_events
├── dramatiq.py        # LogContextMiddleware (§9)
└── checks.py          # system checks (§10.3), imported from CoreConfig.ready()
```

The package is called `logs`, not `logging`, so it can never shadow the stdlib
module. `base.py` calls `build_logging(...)` and assigns the result to
`LOGGING`. The settings module stays declarative, and the processor chain lives
in one importable place that tests can exercise.

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
  drop_sensitive_events   ── may raise DropEvent         ExtraAdder(allow=[…])   (opt-in extras only)
  wrap_for_formatter                                          │
        │                                                     │
        └────────────────────►  ProcessorFormatter.processors  ◄────┘
                                  remove_processors_meta
                                  strip_query_string
                                  sanitise                ── deny / allow / off; strips `sensitive`
                                  exception renderer      ── show_locals=False
                                  renderer                ── "json" or "console" formatter
                                         │
                        ┌────────────────┴────────────────┐
                 StreamHandler (stdout)      ConcurrentTimedRotatingFileHandler
                 formatter: LOG_FORMAT       formatter: always "json"
                                   both carry SensitiveRecordFilter
```

`LOGGING` defines two `ProcessorFormatter`s, `json` and `console`. They share
the processor list above and differ only in the final renderer.

Rules that fall out of this shape:

- **`sanitise` runs in `ProcessorFormatter.processors`**, the last stage before
  rendering. It therefore sees first-party and third-party events alike,
  including context merged from contextvars.
- **`drop_sensitive_events` runs only in the structlog chain.** `DropEvent`
  derives from `BaseException`. Raised inside a formatter, it would escape
  `Handler.emit`'s `except Exception` and crash the caller. The stdlib side
  uses the logging filter `SensitiveRecordFilter` on each handler instead.
- **Only explicitly listed `extra=` keys are copied.** `ExtraAdder` takes an
  opt-in set, which today is only `sensitive`. This stops objects such as
  `django.request`'s `request` from being serialised. Add a key to the set only
  if it is safe under §6.

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
| `request_id` | django-structlog middleware, or the Dramatiq middleware | request- and task-scoped lines |
| `correlation_id` | django-structlog, only when trusted upstream (§5) | as above |
| `user_id` | django-structlog | request-scoped lines (see §5 for the DRF caveat) |
| `ip` | django-structlog | request-scoped lines |
| `task_id`, `actor` | Dramatiq middleware | task-scoped lines |
| `exception` | the exception renderer | lines logged with `exc_info` |

Existing domain events keep their current names (`PDF_RENDERED`,
`GATEWAY_REQUEST` and so on). django-structlog's own events keep theirs
(`request_started`, `request_finished`, `request_failed`).

### 5. Request context

Add `django_structlog.middlewares.RequestMiddleware` to `MIDDLEWARE` directly
after `AuthenticationMiddleware`, so `request.user` is resolved before the
middleware reads it.

| Setting | Value | Why |
| --- | --- | --- |
| `DJANGO_STRUCTLOG_USER_ID_FIELD` | `"pk"` (default) | |
| `DJANGO_STRUCTLOG_IP_LOGGING_ENABLED` | `True` (default) | Needed for abuse investigation |
| `DJANGO_STRUCTLOG_TRUST_UPSTREAM_REQUEST_ID` | `LOG_TRUST_UPSTREAM_REQUEST_ID`, default `False` | Only nginx should set `X-Request-ID`. Turn it on once nginx overwrites the client's header. |
| `DJANGO_STRUCTLOG_TRUST_UPSTREAM_CORRELATION_ID` | `False` | Not used |

Known limitations:

- **`user_id` and DRF auth.** DRF authenticates inside the view, after the
  middleware has run. `user_id` is therefore reliable only on
  `request_finished` and `request_failed`. This is accepted for now. A DRF
  authentication hook that rebinds `user_id` can be added later if needed.
- **Query strings.** django-structlog logs `request` as `"METHOD path"`, and the
  path can include the query string. Query parameters can carry phone numbers,
  OTPs or tokens, so `strip_query_string` cuts everything from `?` onward in the
  `request` field. The PoC (§9) confirms the exact format.

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
}
```

`LOG_DENY_KEYS_EXTRA` (comma-separated) adds keys per environment. Its keys are
added to the set and never replace it.

Matching rules:

- Keys are lower-cased and `-` becomes `_` before comparison.
- A key matches when it **equals** a deny entry or **ends with `_<entry>`**. So
  `user_email`, `recipient_phone` and `x_api_key` match.
- Substring matching is deliberately not used. `pan` would otherwise remove
  `company`, `panel` and `expand`.
- Matching recurses into `dict` values, and into `list` and `tuple` values
  containing dicts. The gateway's `body` form is therefore cleaned too.
- A matching key is removed, not masked. A masked value still leaks length and
  prefix.

#### 6.3 Allow keys

`ALLOW_KEYS` has two parts:

- **Base set, always allowed:** every §4 field, plus django-structlog's
  `request`, `code` and `user_agent`.
- **Extras:** the field names that migrated call sites use, maintained in
  `apps/core/logs/processors.py` next to the base set. Today these are
  `message_id`, `message_key`, `attempt`, `job_id`, `file_id`, `transaction_id`,
  `provider_transaction_id`, `status`, `error_code` and so on. Fill in the full
  list during migration (§11). `LOG_ALLOW_KEYS_EXTRA` adds keys per environment.

Allow mode applies recursively. An allowed key holding a dict keeps only its
allowed sub-keys. In allow mode, adding a field to a log call also means adding
it to the allow set, and a test (§14) fails if a migrated call site logs a key
outside it.

#### 6.4 Free text

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

#### 6.5 Exceptions and locals

structlog's `ExceptionDictTransformer` defaults to `show_locals=True`, and so does
`RichTracebackFormatter`. A frame's locals can hold passwords, OTPs, keys and
whole request bodies.

- **JSON:** `ExceptionRenderer(ExceptionDictTransformer(show_locals=LOG_SHOW_LOCALS, use_rich=False))`.
- **Console:** `ConsoleRenderer(exception_formatter=structlog.dev.plain_traceback)`,
  which never prints locals. `rich` is not installed (§1).
- **`LOG_SHOW_LOCALS`** defaults to `False` in every environment, and
  `production.py` refuses `True` (§10.3). It exists only for a developer chasing
  a bug locally.

#### 6.6 Defaults per environment

| Setting | local | test | production |
| --- | --- | --- | --- |
| `LOG_REDACTION_MODE` | `deny` (`off` allowed) | `deny` | `deny` (see Open questions); `off` refused |
| `LOG_DROP_SENSITIVE_EVENTS` | `False` | `False` | `True` |
| `LOG_SHOW_LOCALS` | `False` | `False` | `False` (`True` refused) |

### 7. Third-party loggers

Third-party libraries use stdlib `logging`, so they skip the structlog chain. To
handle them:

- **Route all formatting through the shared processors.** Every handler in
  `LOGGING` uses one of the two `ProcessorFormatter`s (§3), and both run the same
  processors. `sanitise`, `strip_query_string` and the exception renderer
  therefore apply to every record, whatever logger it came from.
- **Keep the existing named loggers.** `django`, `dramatiq`, `cachalot`,
  `apps.messaging`, `apps.pdf` and `addon.cdac_sms_gateway` keep their
  `propagate: False` entries and point at the same handlers. Nothing is left on
  its own private handler.
- **Pin levels regardless of `LOG_LEVEL`:**

  | Logger | Level | Reason |
  | --- | --- | --- |
  | `django.db.backends` | `WARNING` | At DEBUG it logs SQL with parameter values |
  | `django.request`, `django.security` | `WARNING` | |
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

- **`console`.** A `StreamHandler` on stdout. It is always on, so
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
    "use_gzip": True,
    "chmod": 0o640,
    "formatter": "json",
    "filters": ["sensitive"],
}
```

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
    `chown 10001:10001 /var/log/dristi` once.
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
  early when it reaches `LOG_FILE_MAX_BYTES`. Rotated files are gzipped and
  named `dristi-<host>.log.YYYY-MM-DD[.N].gz`.
- **Stale files after a redeploy.** Every redeploy gets a new container id, so
  the previous container's live `.log` file and its `.__dristi-<host>.lock`
  file stop changing and are never rotated. The cron job therefore matches
  every file type, by age. A running container's live file is always recent, so
  it is never deleted.
- **Deletion by cron.** Old files are deleted by a cron job on the host:

  ```cron
  # /etc/cron.d/dristi-logs: delete log, rotated and lock files untouched for 30 days
  15 1 * * * root find /var/log/dristi -maxdepth 1 -type f \( -name 'dristi-*.log*' -o -name '.__dristi-*.lock' \) -mtime +30 -delete
  ```

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
class LogContextMiddleware(dramatiq.Middleware):
    def before_enqueue(self, broker, message, delay):
        ctx = structlog.contextvars.get_contextvars()
        if request_id := ctx.get("request_id"):
            message.options["log_context"] = {"request_id": request_id}

    def before_process_message(self, broker, message):
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            task_id=message.message_id,
            actor=message.actor_name,
            **message.options.get("log_context", {}),
        )

    def after_process_message(self, broker, message, *, result=None, exception=None):
        structlog.contextvars.clear_contextvars()

    after_skip_message = after_process_message
```

- Register it in `DRAMATIQ_BROKER["MIDDLEWARE"]` in `base.py` and in
  `test.py`.
- It clears the context on entry as well as on exit. Worker threads are reused,
  so a missed `after_*` hook must not leak one task's `request_id` into the
  next.

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
- the exact format of django-structlog's `request` field, so
  `strip_query_string` can be written against it (§5).

**If the PoC fails:** ship everything else, keep `task_id` and `actor` binding
(which needs no cross-process transfer), and record the failure under Open
questions.

### 10. Configuration

#### 10.1 Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `LOG_LEVEL` | Root and first-party logger level | `INFO` |
| `LOG_FORMAT` | `json` or `console` for stdout | `console` locally, `json` in prod |
| `LOG_FILE_ENABLED` | Enable the rotating file handler | `False` locally, `True` in prod |
| `LOG_DIR` | Directory for log files inside the container | `/app/logs` |
| `LOG_FILE_PREFIX` | Filename prefix | `dristi` |
| `LOG_FILE_MAX_BYTES` | Size cap within one day before early rotation | `104857600` (100 MB) |
| `LOG_FILE_BACKUP_COUNT` | Safety cap on rotated files kept | `60` |
| `LOG_REDACTION_MODE` | `deny`, `allow` or `off` (`off` is refused in production) | `deny` |
| `LOG_DENY_KEYS_EXTRA` | Extra deny keys, comma-separated | empty |
| `LOG_ALLOW_KEYS_EXTRA` | Extra allow keys, comma-separated | empty |
| `LOG_DROP_SENSITIVE_EVENTS` | Drop events marked `sensitive=True` | `False` locally, `True` in prod |
| `LOG_SHOW_LOCALS` | Include exception locals (local debugging only) | `False` |
| `LOG_TRUST_UPSTREAM_REQUEST_ID` | Trust the `X-Request-ID` header set by nginx | `False` |
| `LOG_HOST_DIR` | Host path mounted at `LOG_DIR` (compose only) | `/var/log/dristi` |
| `CDAC_SMS_PRINT_RESPONSE` | **Changed:** default is now `False` | `False` |

Following AGENTS.md:

- add every variable to `.env.example`;
- add the production-relevant ones to `.env.prod.example`;
- read them in `base.py`;
- document them in the `README.md` table.

#### 10.2 Settings by environment

`base.py` reads each variable with the local default and calls
`build_logging(...)`. `LOGGING` is a plain dict built at import time, so an
environment module that changes a default must call `build_logging(...)`
again:

- **`local.py`:** no changes. The `base.py` defaults are the local ones.
- **`test.py`:** `LOG_FORMAT=console` and `LOG_FILE_ENABLED=False`. It adds
  `LogContextMiddleware` to the stub broker's middleware.
- **`production.py`:**
  - re-reads `LOG_FORMAT` (default `json`), `LOG_FILE_ENABLED` (default `True`)
    and `LOG_DROP_SENSITIVE_EVENTS` (default `True`), then calls
    `build_logging(...)` again. A deployment that forgets to set them still
    gets production behaviour.
  - Next to the existing "Addon guards", raises `ImproperlyConfigured` when
    `LOG_SHOW_LOCALS=True` or `LOG_REDACTION_MODE=off`. This is the same pattern
    as `CDAC_SMS_VERIFY_SSL`.

#### 10.3 Validation

**Production guards (`production.py`, `ImproperlyConfigured`):**

- `LOG_SHOW_LOCALS=True`
- `LOG_REDACTION_MODE=off`

**System checks (`apps/core/logs/checks.py`)**, imported from `CoreConfig.ready()`
like the existing `apps/pdf/checks.py` and `apps/esign/checks.py`:

| Check | Level |
| --- | --- |
| `LOG_REDACTION_MODE` is not `deny`, `allow` or `off` | Error |
| `LOG_FORMAT` is not `json` or `console` | Error |
| `LOG_FILE_ENABLED=True` and `LOG_DIR` is not writable | Error |
| `LOG_FILE_ENABLED=False` when `DEBUG=False` | Warning |

### 11. Migration of existing log calls

Every `logger.*` call under `src/apps` and `src/addon` moves to
`structlog.get_logger(...)` with an event name and keyword fields. That is about
76 call sites, counting the `log_event` and `_log_event` helpers, in the 22
modules that call `logging.getLogger`. Logger names don't change, so the
`LOGGING` entries keep matching.

| Area | Files | Change |
| --- | --- | --- |
| OTP | `apps/users/services/otp.py:152` | `logger.info("OTP_QUEUED", purpose=purpose, mobile_number=mobile_number)`. `mobile_number` is on the deny list and absent from the allow list, so it is removed in either mode. The line keeps its value as an event marker. |
| eSign | `apps/esign/log.py` | `log_event()` keeps its signature and emits `logger.log(level, event, **fields)` instead of joining a string. Call sites don't change. |
| eSign addon | `addon/cdac_esign/provider.py:86,147,150` | Structured fields. `reason=str(exc)` is reviewed against §6.4. |
| Messaging | `apps/messaging/tasks.py` | `_log_event()` emits keyword fields. Remove the `fields` string join. |
| SMS gateway | `addon/cdac_sms_gateway/{client,response,filtering}.py` | Structured fields. `mask_form()` stays as defence in depth, because the gateway owns its wire secrets, and the form gains `mobileno` coverage from the deny list. |
| SMS default | `base.py:510`, `addon/cdac_sms_gateway/config.py:42,102`, `.env.example:98`, `README.md:192`, `addon/cdac_sms_gateway/tests/test_config.py:40` | `CDAC_SMS_PRINT_RESPONSE` defaults to `False`. Update the test that asserts the old default. |
| PDF | `apps/pdf/tasks.py`, `apps/pdf/services/*` | Replace `event=%s ...` strings and `" ".join(f"{k}={v}")` with keyword fields |
| Others | `apps/users/tasks.py`, `apps/address/services.py`, `apps/files/documents.py`, `apps/dristi_requests/{hooks,services}.py`, `apps/cases/services/services.py`, `apps/core/rules/engines/base.py` | Turn sentence-style messages into an event name plus fields |

Tests that assert on log text move to `structlog.testing.capture_logs()` and
assert on `event` and field values. Eleven test files use `assertLogs` or
`caplog` today:

- `addon/cdac_sms_gateway/tests/test_{backend,response,delivery,filtering}.py`
- `apps/esign/tests/test_{security,callback}.py`
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
   never names, phone numbers, emails or document contents.
4. If an event exists only to carry sensitive detail, pass `sensitive=True` so
   production can drop it.
5. Log a new field name in allow mode only after adding it to `ALLOW_KEYS` in
   `apps/core/logs/processors.py`.
6. Use `logger.exception(...)`, or `exc_info=True`, for errors. Never log
   `locals()`, request bodies or serializer `initial_data`.
7. In tests, assert on `event` and fields with `structlog.testing.capture_logs()`,
   not on rendered text.

### 13. Affected files

```text
src/requirements/base.txt                       # + structlog, django-structlog, concurrent-log-handler
src/apps/core/logs/                             # new package (§2)
src/apps/core/apps.py                           # import logs.checks in ready()
src/config/settings/base.py                     # MIDDLEWARE, LOGGING via build_logging(), DJANGO_STRUCTLOG_*, Dramatiq middleware, CDAC default
src/config/settings/test.py                     # stub broker middleware, logging defaults
src/config/settings/production.py               # prod logging defaults, rebuild LOGGING, guards
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

Tests go in `apps/core/tests/test_logs_*.py` unless noted.

1. **Sanitise, deny mode:** exact and `_<entry>` suffix keys are removed; nested
   dicts and lists are cleaned; `company`, `panel` and `expand` survive.
2. **Sanitise, allow mode:** unknown keys are removed; base fields survive;
   nested dicts are filtered.
3. **Drop sensitive events:**
   - with the setting on, a `sensitive=True` structlog event is dropped, and so
     is a stdlib record with `extra={"sensitive": True}`;
   - with it off, both are rendered and the flag is removed;
   - neither raises.
4. **Locals:** an exception raised with a local `password = "x"` renders without
   the value in JSON and console output.
5. **Third-party records:** a record from `logging.getLogger("django.request")`
   with a denied `extra` key, and with a query string in `request`, renders
   sanitised.
6. **Request context:** two log calls inside one test-client request share the
   `request_id` of `request_finished`.
7. **Dramatiq (stub broker):** a task enqueued inside a bound context logs that
   `request_id`; a task enqueued outside one logs only `task_id` and `actor`;
   back-to-back tasks don't leak context.
8. **File handler:** with `LOG_FILE_ENABLED=True` and a temporary `LOG_DIR`,
   several processes (`multiprocessing`) write to one file without interleaving
   lines. Forcing a rollover produces a gzipped backup.
9. **Validation:**
   - each system check in §10.3;
   - importing production settings with `LOG_SHOW_LOCALS=True` or
     `LOG_REDACTION_MODE=off` raises `ImproperlyConfigured`.
10. **Migration:**
    - the OTP send no longer logs the mobile number;
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
   - create `/var/log/dristi` on the host and `chown` it to `10001:10001`;
   - install the cron entry (§8.3).

   Under `production.py`, JSON output, the file handler and dropping sensitive
   events are the defaults (§10.2). An environment on another settings module
   sets these through the logging env vars (§10.1).

   Tell the team that log output changes from plain text to JSON, so anyone
   grepping `docker logs` for `event=...` knows.

## Acceptance criteria

- Every request-scoped line carries `request_id`. Worker lines for a task
  enqueued by that request carry the same `request_id`, provided the PoC passed.
- No key on `DENY_SENSITIVE_KEYS` appears in output in deny mode, and no key
  outside `ALLOW_KEYS` appears in allow mode. This holds for first-party and
  third-party records alike.
- With `LOG_DROP_SENSITIVE_EVENTS=True`, events marked sensitive never reach a
  handler.
- No rendered traceback contains frame locals. Production settings refuse
  `LOG_SHOW_LOCALS=True` and `LOG_REDACTION_MODE=off`.
- With the file handler on, each container writes one daily-rotated, size-capped
  and gzipped file. Concurrent processes lose no lines.
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
  §14 item 10, and convention rule 5 in §12.
- **The cron job is missing on a host, so the disk fills.** Mitigation:
  `LOG_FILE_BACKUP_COUNT` cap, `maxBytes` per day, and the Docker `json-file`
  limits.
- **Lock contention under load** (up to 4 processes on one file per container).
  Mitigation: one file per container; measure during the PoC; if needed, give
  each process its own file by adding the PID to the filename.
- **A third-party library logs sensitive text inside a message string.**
  Mitigation: pinned levels (§7). Raise a library to `ERROR` if one is found.
- **New dependencies.** Mitigation: all three are pure Python and actively
  released. Pin them after the PoC.
- **The UID change breaks a running deployment.** Existing volumes are owned
  by the old UID. Mitigation: the one-time re-own in §8.2, run as part of
  rollout step 5.

## Open questions

1. **Production redaction mode.** The spec defaults to `deny` everywhere.
   Should production run `allow` from day one, accepting the upkeep of rule 5 in
   §12?
2. **Cron ownership.** Who installs and owns the host cron entry and the
   one-time `chown` of `/var/log/dristi`: ops, or a compose sidecar shipped with
   the repo?
3. **Retention period.** Is 30 days right, or is there a legal or compliance
   requirement?
4. **`X-Request-ID` from nginx.** Should nginx generate and forward
   `X-Request-ID`, which lets us turn on `LOG_TRUST_UPSTREAM_REQUEST_ID`?

## Future enhancements (optional)

- `duration_ms` on `request_finished`, using django-structlog's
  `bind_extra_request_metadata` and `bind_extra_request_finished_metadata`
  signals.
- Rebind `user_id` after DRF authentication, so it appears on every line.
- Ship the JSON files to an aggregator.
- Add Sentry, sharing the same `request_id`.
- Value-pattern scrubbing (for example 10-digit mobile numbers) for free-text
  messages, if pinned levels prove insufficient.
