# 0026 — Scheduled and Delayed Jobs (`dramatiq-crontab`)

## Status

Proposed


> **Scope note.** This spec adds **one** scheduler process that only *enqueues*
> messages on a timetable; all work still runs in the existing Dramatiq
> `worker`. It also fixes the project convention for running a job **once,
> after a delay** (for example "30 minutes from now"), which needs no scheduler
> at all. The sweepers' business logic stays in their owning apps and specs.

## Context

Dramatiq is the project's only background-job system (Redis broker, `worker`
service, `django_dramatiq` for discovery and DB-connection handling). It runs a
message when someone sends one. Nothing in the project sends a message **on a
timetable**: the compose files have no beat/cron/scheduler service, and no
dependency provides one.

As a result, actors written to be periodic never run:

| Actor | Defined by | What happens today |
| --- | --- | --- |
| `apps.esign.tasks.expire_stale_transactions` | 0015 #9 | abandoned `PENDING` rows never become `EXPIRED`; retry eligibility is never decided |
| `apps.esign.tasks.reconcile_signing_transactions` | 0015 #9 | a row left in `SIGNING` by a crashed worker stays there for good |
| `apps.esign.tasks.cleanup_placeholders` | 0015 #9 | placeholder PDFs pile up in storage indefinitely |
| `django_dramatiq.tasks.delete_old_tasks` | `django_dramatiq` | `AdminMiddleware` writes one `django_dramatiq_task` row per message and nothing deletes them |

Other modules need a sweeper that has not been written yet (§7.2): the PDF
service, messaging, payments and registration all have rows that stay in a
non-terminal state forever if a message is lost.

Many flows also need a job to run **once, at a later time** instead of on a
timetable ("expire this OTP-gated action in 30 minutes", "send a reminder an
hour after filing", "re-check the gateway in 5 minutes"). Dramatiq already does
this through delayed messages. 0009 and 0016 use it for retries. But the
guarantees and the pattern are not written down anywhere, so each module
rediscovers them.

## Goals

- Run the existing periodic actors on a schedule with **no change to their
  logic**.
- Give developers one documented way to schedule an actor: a decorator next to
  the actor, discovered automatically.
- Guarantee **at most one active scheduler** across all replicas, so a schedule
  never fires twice per tick.
- Document the **one-off delayed job** pattern ("run once, 30 minutes from
  now") and how to make it effectively exactly-once.
- Keep the change small: one dependency, one installed app, one settings block,
  one compose service, one entrypoint command.

## Non-goals

- A second task system (Celery beat, RQ, Kafka, system `cron` in a container).
- Database-managed or admin-editable schedules. Schedules are code and are
  reviewed like code.
- A durable job store or catch-up of runs missed while the scheduler was down
  (§6.4 explains why sweepers do not need one).
- Writing the missing sweepers of §7.2. Each one is specified by its owning
  module's spec. This spec only reserves its schedule.
- Cancelling a delayed message that has already been sent (§5.5).

---

## 1. Options considered

| Option | Verdict |
| --- | --- |
| **`dramatiq-crontab` (selected)** | A thin layer over Dramatiq + APScheduler. A `@cron("…")` decorator on the actor and `manage.py crontab` for the process. Uses a Redis lock so only one instance runs. Discovers `<app>.tasks` the same way `rundramatiq` does. |
| `periodiq` | Same idea, but it is not Django-aware, has no lock across replicas and is barely maintained. |
| `django-apscheduler` | Stores jobs in the DB and runs them **in-process**, which skips the Dramatiq worker, its time limits, retries and dashboard. |
| System `cron` / Kubernetes `CronJob` calling `manage.py` | Starts a full Django process per tick. The schedule lives outside the repository and is invisible in review. Differs per environment. |
| Celery beat | Would introduce a second broker protocol and a second worker model. |
| Self-rescheduling actor (`send_with_options(delay=…)` at the end of each run) | One lost message stops the chain silently, and nothing starts it after a Redis flush. Fine for one-off delays (§5), not for timetables. |

## 2. Architecture

```text
                    ┌────────────────────────┐
                    │ scheduler (1 replica)  │  python manage.py crontab
                    │ APScheduler, in-memory │  holds Redis lock "dramatiq-scheduler"
                    └───────────┬────────────┘
                                │ actor.send()  (on each tick, no args)
                                ▼
web ── actor.send() ──▶ ┌──────────────┐ ◀── send_with_options(delay=…) ── web / worker
                        │ Redis (db 2) │     <queue>.DQ holds delayed messages
                        └──────┬───────┘
                               ▼
                        ┌──────────────┐
                        │ worker (N)   │  python manage.py rundramatiq
                        └──────────────┘  runs every actor, scheduled or not
```

- The **scheduler** never executes business logic. On each tick it calls
  `actor.send()`, which puts an ordinary message on the actor's queue.
- The **worker** cannot tell a scheduled message from any other message. Time
  limits, retries, `DbConnectionsMiddleware` and the Dramatiq dashboard all
  apply unchanged.
- **One-off delayed jobs** (§5) never pass through the scheduler. They are
  Dramatiq delayed messages, stored in Redis.

## 3. Installation and configuration

### 3.1 Dependency

`src/requirements/base.txt`:

```text
# Scheduler (spec 0026). 1.1+ requires Django >= 5.2.17; lift the cap with
# the Django upgrade. APScheduler 4 has an incompatible API.
dramatiq-crontab[redis]>=1.0.12,<1.1
apscheduler>=3.11,<4
```

`dramatiq-crontab` 1.0.12 leaves APScheduler unpinned, so we pin it ourselves.

### 3.2 Installed app

`src/config/settings/base.py`, alongside `django_dramatiq`:

```python
INSTALLED_APPS = [
    ...
    "django_dramatiq",
    "dramatiq_crontab",
    ...
]
```

This line is required, not optional. `rundramatiq` registers actors by importing
`<app>.tasks` for every installed app. The scheduler sends the built-in
`heartbeat` actor (`dramatiq_crontab.tasks`) every minute, so the worker has to
know that actor too.

### 3.3 Settings

`base.py`, in the existing Dramatiq block:

```python
# Scheduler lock (spec 0026): only the instance holding it fires schedules.
DRAMATIQ_CRONTAB = {
    "REDIS_URL": env("DRAMATIQ_BROKER_URL", default="redis://localhost:6379/2"),
}
```

- Reuses `DRAMATIQ_BROKER_URL`, so **no new environment variable** is
  introduced. The lock key is `dramatiq-scheduler` in the broker's Redis
  database (2), next to the queues it guards.
- Lock timings use the library defaults: refresh every 5 s, TTL 10 s, wait
  15 s to acquire. A standby therefore takes over at most about 10 s after the
  active scheduler dies.
- `test.py` sets `DRAMATIQ_CRONTAB = {}`. Without a lock URL the library uses
  an in-process fake lock, so tests never need Redis.

### 3.4 Time zone

`TIME_ZONE = "UTC"`, so **every cron expression is in UTC**. Court-day jobs
must be converted from IST (UTC+05:30). For example, 00:30 IST is
`"0 19 * * *"` the previous UTC day. Write the IST time in a comment next to
any expression that depends on wall-clock time.

### 3.5 Process

`docker/entrypoint.sh` gains one command:

```sh
    scheduler)
        wait_for_db
        echo "Starting Dramatiq scheduler..."
        exec python manage.py crontab
        ;;
```

and the usage line lists `scheduler`. `manage.py crontab` imports
`<app>.tasks` for every installed app (that import registers the schedules),
takes the lock, and blocks.

`docker/docker-compose.yml`: a `scheduler` service that copies `worker`
(same build, `env_file`, volumes and `depends_on`) with
`command: ["scheduler"]`.

`docker/docker-compose.prod.yml`: the same, with the `worker` environment
block, and:

```yaml
    deploy:
      replicas: 1
      restart_policy:
        condition: any
```

`replicas: 1` because a second instance gains nothing. It waits 15 s for the
lock, prints `Another scheduler is already running.` and **exits with status
0**. That is also why the policy is `any` and not `on-failure`: an `on-failure`
policy would not restart a scheduler that exited cleanly. Running two replicas
by mistake is still safe, because the lock means only one of them fires.

Locally, the scheduler runs under `make up` with the rest of the stack.
Without Docker, run it in its own terminal next to the worker:

```bash
cd src
python manage.py rundramatiq      # terminal 1
python manage.py crontab          # terminal 2
```

## 4. Scheduling a periodic job

### 4.1 Requirements for a schedulable actor

An actor may be put on a schedule only if all of these hold:

1. **It is a module-level `@actor` in `<app>/tasks.py` of an installed app.**
   Both `crontab` and `rundramatiq` discover `<app>.tasks` only. An actor
   defined anywhere else must be imported into `tasks.py`.
2. **It takes no required arguments.** The scheduler calls `actor.send()`
   with no arguments. Read thresholds, retention periods and batch sizes from
   settings inside the actor. Keep the logic in a service function that takes
   `now=None` so tests can drive it (see `apps.esign.services.recovery`).
3. **It is idempotent and safe to overlap.** A slow run can still be going
   when the next tick is consumed by another worker thread, and a message can
   be delivered twice. Select candidates, then re-check each row under
   `select_for_update` (or with a status-conditional `update()`) before
   changing it, as 0015 #9 does.
4. **It is bounded.** Process at most a configured batch per run and leave
   the rest for the next tick. Do not loop until the table is empty.
5. **`max_retries=0`.** The next tick is the retry. Dramatiq's backoff would
   only pile retries on top of fresh ticks.
6. **It finishes well inside its interval.** Set a `time_limit` shorter than
   the interval when a run could be slow.
7. **It logs one structured line per run**: `event=<NAME> count=<n>`. The
   return value is not stored anywhere, because the project has no results
   backend.
8. **It sweeps by state, not by tick.** It acts on "every row past its cutoff",
   never on "rows since the last run". A missed or doubled tick then changes
   nothing (§6.4).

### 4.2 Declaring the schedule

Put the decorator directly on the actor, **outermost**, in the same `tasks.py`:

```python
from dramatiq import actor
from dramatiq_crontab import cron

from .services import recovery


@cron("*/5 * * * *")  # every 5 minutes
@actor(max_retries=0)
def expire_stale_transactions() -> int:
    """Move ``PENDING`` transactions past their TTL plus grace to ``EXPIRED``."""

    return recovery.expire_stale_transactions()
```

- `cron(expr)` takes a standard five-field crontab expression (minute, hour,
  day of month, month, day of week) and has one-minute resolution.
- **Day of week must be a literal** (`Mon`–`Sun`) or `*`. The library raises
  `ValueError` for digits because APScheduler and crontab number weekdays
  differently: `"0 3 * * Sun"`, not `"0 3 * * 0"`.
- For an interval shorter than one minute, use
  `@interval(seconds=30)` from `dramatiq_crontab`. Its phase is relative to
  when the scheduler started, so a restart shifts it. Use it only when
  wall-clock alignment does not matter.
- The decorator returns the actor unchanged. The actor can still be called or
  sent by hand: `expire_stale_transactions.send()`.
- Applying the decorator in the web or worker process only stores a pending job
  in an APScheduler instance that is never started there, so it does nothing.

To schedule an actor we do not own (a third-party actor, or one whose module
should not import `dramatiq_crontab`), wrap it in a no-argument actor in the
owning app's `tasks.py` and schedule the wrapper (see `prune_task_history`,
§7.1).

### 4.3 Checklist: adding a scheduled job

1. Write or reuse the service function. Unit-test it with an explicit `now`.
2. Expose it as an actor in `<app>/tasks.py` that meets §4.1.
3. Add `@cron("…")` above `@actor`, with a comment in plain words (and the
   IST time when it matters, §3.4).
4. Add the actor to the schedule inventory (§7.1) and to the owning app's
   spec.
5. Add the expected `actor_name → expression` pair to the schedule test
   (§8.2).
6. Deploy. The scheduler reads schedules only at start-up, so the release
   must restart the `scheduler` service. A normal compose deploy does this. No
   migration or environment change is needed.
7. Check the scheduler log for `Loaded tasks from apps.<app>.`. Check the
   worker log or the Dramatiq dashboard for the first run.

Pausing or changing a schedule is a code change and a deploy. To switch a
sweeper off in an emergency, give its service function an `<APP>_…_ENABLED`
setting and return `0` when it is false. Never comment out the decorator in
a hotfix.

## 5. Running a job once, after a delay

Use this for "run this job once, 30 minutes from now". The scheduler is **not**
involved. Send a delayed Dramatiq message from wherever the triggering event
happens: a view, a service or another actor.

### 5.1 Pattern

```python
from datetime import timedelta
from functools import partial

from django.db import transaction
from dramatiq import actor


def schedule_payment_link_expiry(payment) -> None:
    """Expire the payment link 30 minutes after it is issued."""

    # Publish only after the row commits (0009, 0016 #10): the worker must find it.
    transaction.on_commit(
        partial(
            expire_payment_link.send_with_options,
            args=(str(payment.pk), payment.link_issued_at.isoformat()),
            delay=timedelta(minutes=30),  # or an int of milliseconds
        )
    )


@actor(max_retries=3)
def expire_payment_link(payment_id: str, issued_at: str) -> None:
    """Runs once, no earlier than 30 minutes after it was scheduled."""

    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(pk=payment_id).first()
        # Guard: the row is gone, already settled, or a newer link replaced this one.
        if payment is None or payment.status != Payment.Status.PENDING:
            return
        if payment.link_issued_at.isoformat() != issued_at:
            return
        payment.expire_link()
```

`Payment` and its fields are illustrative. Use the module's own model and state.

### 5.2 What Dramatiq guarantees

- **Not before the delay.** The message is stored in Redis on the delay queue
  (`<queue>.DQ`) with an `eta`. It becomes eligible at the `eta` and runs as
  soon as a worker thread is free. That is normally within a second, and later
  if the queue is backed up. Treat the delay as "no earlier than", not "at
  exactly".
- **Survives restarts.** The message lives in Redis, not in the process that
  sent it. Web, worker and scheduler restarts do not lose it. A Redis data loss
  does, so production Redis runs with `appendonly yes` (already set in
  `docker-compose.prod.yml`).
- **At-least-once delivery.** If a worker dies mid-run, Redis redelivers the
  message to another worker. Dramatiq does not provide exactly-once.
- **Delay must be under 7 days** on the Redis broker (a `ValueError` otherwise).
- **No cancellation.** A sent message cannot be withdrawn (§5.5).

### 5.3 Making it effectively exactly-once

"Runs exactly once" is achieved by the actor, not by the broker:

1. **Send identifiers, never payloads.** The actor reads current state from the
   database.
2. **Publish with `transaction.on_commit`.** A rolled-back request schedules
   nothing, and the worker never runs before the row is visible.
3. **Guard on state.** Re-read the row under `select_for_update` and do
   nothing unless it is still in the state the job was scheduled for. A
   duplicate delivery, or a delivery after the work was done some other way,
   then becomes a no-op.
4. **Carry a version token when the schedule can be replaced.** Pass
   `issued_at`, a `deadline_at` or a counter, and compare it with the row. This
   is how a superseded message (§5.5) knows it is stale. 0016's `attempt`
   argument is the same idea.
5. **Make the side effect idempotent too.** For outbound calls (SMS, gateway
   requests), record that the call was made in the same transaction as the
   state change, or use a natural key the receiver deduplicates on.

### 5.4 Pitfalls

- **`max_age` counts from when the message was sent, not from its `eta`.**
  `AgeLimit` drops a message older than `max_age`. A delayed message is
  already `delay` old when it becomes eligible, so if an actor sets
  `max_age`, it must be larger than any delay used with it. No actor sets one
  today, and `AgeLimit` has no global default here.
- **Don't use `time.sleep` or long `eta` loops inside an actor** to wait. That
  holds a worker thread for the whole wait.
- **Don't use the scheduler for one-offs**, for example by adding an
  APScheduler `date` job. Its job store is in memory, so a restart loses the
  job, and only the scheduler process can add one.
- **Longer than 7 days, or the time must be queryable or changeable?** Store
  a `due_at` column and let a periodic sweeper (§4) pick up rows where
  `due_at <= now`. That is the durable form of a delay.

### 5.5 Rescheduling and cancelling

Dramatiq cannot remove a message from the delay queue. Change the state
instead, and let the guard in §5.3 drop the old message:

- **Cancel:** move the row out of the awaited state, for example to
  `CANCELLED`. The old message arrives, sees this, and returns.
- **Reschedule:** update the version token (a new `deadline_at`) and send a new
  delayed message carrying the new token. The old message no longer matches
  and returns.

### 5.6 Delay plus a periodic safety net

When missing the job would leave a row stuck forever, use both mechanisms. The
delayed message is the fast path. A periodic sweeper (§4) finds rows past
their deadline that the message missed: the publish failed after commit, Redis
was flushed, or a bug hit. The two must use the same guarded service function,
so whichever runs first wins and the other does nothing. eSign already follows
this shape: `expires_at` on the row and `expire_stale_transactions` as the
sweeper.

### 5.7 Periodic vs delayed: which to use

| Need | Use |
| --- | --- |
| Fixed timetable ("every 5 minutes", "daily at 02:00 IST") | `@cron` (§4) |
| Once, N minutes/hours after an event (< 7 days) | `send_with_options(delay=…)` (§5) |
| Once, at a date far ahead, or a date users can change | `due_at` column + periodic sweeper |
| Retry after a transient failure | `send_with_options(delay=backoff)` (as 0009, 0016) |
| A one-off delay that must never be missed | delayed message + periodic sweeper (§5.6) |

## 6. Operational behaviour

### 6.1 Single active scheduler

The scheduler acquires the Redis lock `dramatiq-scheduler` before starting and
renews it every 5 s. If it cannot renew, it shuts down. On `SIGTERM`, `SIGINT`
or `SIGHUP` it stops and releases the lock, so a deploy hands over cleanly.

### 6.2 Heartbeat

The scheduler sends `dramatiq_crontab.tasks.heartbeat` every minute. The worker
logs it. A heartbeat that is missing from the worker log means the
scheduler → Redis → worker path is broken. Do not run it with `--no-heartbeat`.

### 6.3 Observability

- Scheduler log: `Loaded tasks from <app>.`, `Starting scheduler…`, and lock
  errors.
- Worker log and Dramatiq dashboard (`:8080`): one message per tick, plus the
  sweeper's own `event=… count=…` line.
- Delayed messages are visible in the dashboard on the `<queue>.DQ` queues.

### 6.4 Missed and overlapping runs

- Schedules live in memory and are rebuilt from code on start-up. A tick
  that falls while the scheduler is down is **not** replayed. A sweeper that
  meets §4.1 #8 catches up on its next run, because it acts on everything past
  its cutoff.
- A tick enqueues a message even if the previous run has not finished. Rule
  §4.1 #3 makes overlapping runs safe.

### 6.5 Removal

Remove the `scheduler` service and entrypoint case, `dramatiq_crontab` from
`INSTALLED_APPS`, the `DRAMATIQ_CRONTAB` block, the two requirements and the
`@cron` decorators. The actors are left as ordinary actors.

## 7. Schedule inventory

### 7.1 Scheduled by this spec

| Actor | Schedule | Why this cadence |
| --- | --- | --- |
| `apps.esign.tasks.expire_stale_transactions` | `*/5 * * * *` | TTL 900 s + grace 300 s. A 5-minute lag is small next to that |
| `apps.esign.tasks.reconcile_signing_transactions` | `*/5 * * * *` | `ESIGN_SIGNING_STUCK_TIMEOUT` is 300 s |
| `apps.esign.tasks.cleanup_placeholders` | `30 20 * * *` (02:00 IST) | retention is in days, so run daily off-peak |
| `apps.core.tasks.prune_task_history` | `0 21 * * *` (02:30 IST) | keeps `django_dramatiq_task` bounded |

`prune_task_history` is a new no-argument wrapper in `apps.core.tasks`. It calls
`Task.tasks.delete_old_tasks(...)` with a 7-day age (a module constant). The
library actor `delete_old_tasks` defaults to 1 day, which is too short to
investigate a failure after a weekend, and the scheduler cannot pass arguments
(§4.1 #2).

None of the eSign actors change apart from the added decorator.

### 7.2 Needed, to be scheduled when their owning spec defines them

| Module | Gap | Owner |
| --- | --- | --- |
| `apps.pdf` | A job stays `QUEUED` if `actor.send` fails after commit. A job stays `PROCESSING` if its worker dies mid-render: the redelivered message carries the same `attempt` and `claim_job` drops it as a duplicate (0016 #10). Needs a stalled-job recovery actor. | amendment to 0016 |
| `apps.messaging` | A `MessageLog` stays `PENDING` if `_publish` fails after commit. Log retention is also an open question (0009 Q1). | amendment to 0009 |
| `apps.payments` | `poll_pending_payments` (0017 #9.7) is specified as periodic but not yet implemented. Schedule it every minute; it applies its own per-payment backoff. | 0017 |
| `apps.users` | A verification request is not raised if `_publish_verification` fails after commit. Deleting abandoned `PENDING_PROFILE` accounts is 0005 #8 (non-priority). | 0005 |
| `apps.files` | Reconciliation of orphaned storage objects (0014 Q8, out of scope there). | 0014 |

Each one follows §4.3 when it lands. This table is the place to look for what
runs when.

## 8. Testing

### 8.1 Sweeper logic

Unchanged from the owning specs. Call the service function or the actor
function directly with an explicit `now`, as
`apps/esign/tests/test_tasks.py` does. The scheduler is never started in tests.

### 8.2 Schedule registration

One test in `apps/core/tests/test_schedules.py` pins the inventory of §7.1:

```python
from apscheduler.triggers.cron import CronTrigger
from django.utils import timezone
from django.utils.module_loading import autodiscover_modules
from dramatiq_crontab import scheduler

EXPECTED = {
    "expire_stale_transactions": "*/5 * * * *",
    "reconcile_signing_transactions": "*/5 * * * *",
    "cleanup_placeholders": "30 20 * * *",
    "prune_task_history": "0 21 * * *",
    "heartbeat": "* * * * *",
}


def test_schedule_inventory():
    autodiscover_modules("tasks")  # what `manage.py crontab` does
    jobs = {job.name: str(job.trigger) for job in scheduler.get_jobs()}
    expected = {
        name: str(CronTrigger.from_crontab(expr, timezone=timezone.get_default_timezone()))
        for name, expr in EXPECTED.items()
    }
    assert jobs == expected
```

A schedule that is added, removed or changed by accident now fails CI, and a
deliberate change shows up in review.

### 8.3 Delayed jobs

With the stub broker (`config.settings.test`), assert on the message and do not
wait for it:

```python
def test_link_expiry_is_scheduled_30_minutes_out(broker, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        schedule_payment_link_expiry(payment)

    (message,) = broker.queues["default.DQ"].queue
    assert message.actor_name == "expire_payment_link"
    assert message.options["eta"] - message.message_timestamp >= 30 * 60 * 1000
```

Test the guard separately by calling `expire_payment_link.fn(...)` twice, and
with a stale token. The second call and the stale call must change nothing.

### 8.4 Commands

```bash
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest
cd src && ruff check . && ruff format .
cd src && python manage.py check
```

Manual: `make up`. Check that `docker compose -f docker/docker-compose.yml logs
scheduler` shows every app's tasks loaded and `Starting scheduler…`, and that
the worker log shows the heartbeat each minute. Starting a second scheduler
should print `Another scheduler is already running.` and exit.

## 9. Affected files

```text
src/requirements/base.txt                 # + dramatiq-crontab[redis], apscheduler
src/config/settings/base.py               # + "dramatiq_crontab", DRAMATIQ_CRONTAB
src/config/settings/test.py               # DRAMATIQ_CRONTAB = {}
src/apps/esign/tasks.py                   # + @cron on the three actors
src/apps/core/tasks.py                    # + prune_task_history (@cron)
src/apps/core/tests/test_schedules.py     # new, §8.2
docker/entrypoint.sh                      # + scheduler command
docker/docker-compose.yml                 # + scheduler service
docker/docker-compose.prod.yml            # + scheduler service (1 replica)
README.md, docs/development.md            # how to schedule periodic and delayed jobs
docs/production.md, docs/architecture.md  # scheduler service
AGENTS.md                                 # "Adding a Dramatiq task": scheduling step
```

No models, migrations, URLs or environment variables are added.

## 10. Acceptance criteria

- [ ] `manage.py crontab` starts, loads every installed app's `tasks`, takes the Redis lock and enqueues on schedule.
- [ ] A second scheduler instance does not fire, and takes over within about 10 s of the first one stopping.
- [ ] The four actors of §7.1 run on their schedules; the eSign actors are unchanged apart from the decorator.
- [ ] The worker processes the heartbeat every minute.
- [ ] `django_dramatiq_task` rows older than 7 days are deleted daily.
- [ ] The schedule inventory test (§8.2) passes and fails when a schedule changes.
- [ ] The README and `docs/development.md` explain how to schedule a periodic job and a one-off delayed job.
- [ ] No new environment variable, model or migration; tests need no Redis.

## 11. Design decisions

| Decision | Rationale |
| --- | --- |
| Scheduler only enqueues; worker executes | One execution path, with its time limits, DB-connection handling and dashboard, for every job. The scheduler stays tiny and has nothing to retry. |
| Schedule declared on the actor, in code | The cadence sits next to the code that depends on it, and the inventory test makes changes reviewable. Admin-editable schedules would add a model and a way for production to drift from the repository. |
| Redis lock instead of "make sure only one replica runs" | Deploy overlap and accidental scaling are normal. Correctness should not depend on replica counts. |
| Lock in the broker's Redis database | The lock guards the queues, so it lives and dies with them. Reusing `DRAMATIQ_BROKER_URL` avoids a new setting that could point somewhere else. |
| No catch-up of missed ticks | Sweepers act on state past a cutoff, so the next tick does the same work. A durable job store would add a table and a migration for no benefit. |
| One-off delays via Dramatiq, not the scheduler | Delayed messages are already persisted in Redis and survive restarts. The scheduler's in-memory store would lose them, and only one process could add them. |
| Exactly-once from guards, not the broker | Dramatiq is at-least-once by design. A state guard plus `on_commit` is what 0009, 0015 and 0016 already rely on. |
| Pin `dramatiq-crontab` < 1.1 | 1.1+ requires Django ≥ 5.2.17. The project is on 5.0. |

## 12. Out of scope

- The sweepers of §7.2. Their logic, thresholds and settings belong to their own specs.
- Sentry cron monitors (`dramatiq-crontab[sentry]`). The project does not use Sentry.
- Per-tenant or per-court schedules, and a court-holiday calendar.
- A separate `maintenance` queue for sweepers. Revisit if sweeper runs ever delay user-facing jobs.

## 13. Open questions

1. Should sweepers get a dedicated queue (and worker pool) so a long daily
   cleanup cannot delay OTP SMS delivery on the default queue?
2. Is 7 days the right retention for `django_dramatiq_task`, or should it
   follow an audit-retention policy?
3. Do we need alerting on a missing heartbeat, and where (log-based alert vs
   a health-check endpoint)?

## 14. Implementation phases

1. **Scheduler** — dependency, installed app, settings, entrypoint, compose
   services. Heartbeat visible in the worker log.
2. **Existing sweepers** — `@cron` on the eSign actors, `prune_task_history`,
   schedule inventory test.
3. **Docs** — README, `docs/development.md`, `docs/production.md`,
   `docs/architecture.md`, `AGENTS.md`.
4. **Follow-ups** — each §7.2 sweeper through its owning spec, then the §4.3
   checklist.
