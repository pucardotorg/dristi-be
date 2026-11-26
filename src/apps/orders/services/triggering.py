"""Triggering: the workflow runs of a triggered order (#9).

``write_runs`` records every step in the trigger transaction, in the catalogue's
order; ``run_order_workflows`` executes them after commit. A step already
``DONE`` is skipped, so a redelivered message finishes the order rather than
repeating it. A failed ``HEARING`` step blocks everything after it: processes
and tasks point at the hearing. Any other failure is recorded and the next step
runs. A failed step is retried with backoff up to ``orders.run_max_retries``,
then stays ``FAILED`` until an admin retries it. ``sweep_stranded`` re-enqueues
an order whose message was lost.
"""

import logging
import uuid
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.hearings.enums import RescheduleReason, Side
from apps.hearings.exceptions import HearingError
from apps.hearings.services import listing

from .. import conf, ports
from ..enums import RunStatus, RunStep, TriggerPhase
from ..models import Order, OrderWorkflowRun
from . import items

logger = logging.getLogger(__name__)

COGNIZANCE_TASK_ITEMS = ("COGNIZANCE", "DISMISS_CASE")
BACKOFF_SECONDS = 30
LEASE = timedelta(minutes=15)  # a RUNNING step older than this was left by a dead worker


def _has_stage_work(item_type):
    return bool(item_type.stage_event or item_type.closes_case or item_type.outcome)


def write_runs(order):
    """Write the order's ``OrderWorkflowRun`` rows, in execution order (#9.2).

    1. ``HEARING`` — confirm the held date, first, so every other workflow sees it.
    2. ``ITEM``, phase ``NORMAL`` — each other item with a workflow, by position.
    3. ``ITEM``, phase ``LAST`` — the case-closing items.
    4. ``STAGE`` — stage events and hearing cancellation, last.
    """
    if order.runs.exists():
        return list(order.runs.all())
    order_items = list(order.items.select_related("item_type").order_by("position"))
    plan = []
    if order.next_hearing_held:
        plan.append((RunStep.HEARING, None))
    runnable = [
        item
        for item in order_items
        if item.item_type.has_workflow or item.item_type.trigger_phase == TriggerPhase.FIRST
    ]
    for phase in (TriggerPhase.FIRST, TriggerPhase.NORMAL, TriggerPhase.LAST):
        plan += [(RunStep.ITEM, item) for item in runnable if item.item_type.trigger_phase == phase]
    if any(_has_stage_work(item.item_type) for item in order_items):
        plan.append((RunStep.STAGE, None))
    return [
        OrderWorkflowRun.objects.create(order=order, order_item=item, step=step, sequence=index)
        for index, (step, item) in enumerate(plan, start=1)
    ]


def enqueue_on_commit(order_id, *, delay_ms=0):
    """Enqueue ``run_order_workflows`` once the transaction commits (#12.7).

    Robust: the order is already committed, so a broker failure is logged rather
    than failing the request or the callbacks after it; ``sweep_stranded`` picks
    the runs up.
    """
    from ..tasks import run_order_workflows

    def send():
        if delay_ms:
            run_order_workflows.send_with_options(args=(str(order_id),), delay=delay_ms)
        else:
            run_order_workflows.send(str(order_id))

    transaction.on_commit(send, robust=True)


def sweep_stranded(now=None):
    """Enqueue ``run_order_workflows`` for orders whose runs nothing is driving; return how many.

    A step left ``PENDING``, ``RUNNING`` or retryably ``FAILED`` for longer than
    the lease lost its message (a failed enqueue, a dead worker): no backoff
    waits that long. An order with a claim still inside the lease is left to it.
    Enqueueing twice is harmless: ``run`` skips what is done and claimed.
    """
    from ..tasks import run_order_workflows

    now = now or timezone.now()
    cutoff = now - LEASE
    live = OrderWorkflowRun.objects.filter(status=RunStatus.RUNNING, updated_at__gte=cutoff)
    stranded = (
        OrderWorkflowRun.objects.filter(updated_at__lt=cutoff)
        .filter(
            Q(status__in=(RunStatus.PENDING, RunStatus.RUNNING))
            | Q(status=RunStatus.FAILED, attempts__lt=conf.run_max_retries())
        )
        .exclude(order_id__in=live.values("order_id"))
        .order_by()
        .values_list("order_id", flat=True)
        .distinct()
    )
    order_ids = list(stranded)
    for order_id in order_ids:
        run_order_workflows.send(str(order_id))
    if order_ids:
        logger.warning("event=ORDER_RUNS_SWEPT count=%s", len(order_ids))
    return len(order_ids)


def run(order_id):
    """Execute the order's pending steps in sequence; return how many remain retryable (#9.2).

    Idempotent: ``DONE`` steps are skipped. A caller (the actor) re-enqueues
    itself with backoff while retryable steps remain.
    """
    order = Order.objects.select_related("order_type", "court").get(pk=order_id)
    runs = list(order.runs.select_related("order_item__item_type").order_by("sequence"))
    blocker = None  # the failed HEARING step that blocks the steps after it
    busy = False
    for scheduled in runs:
        if scheduled.status == RunStatus.DONE:
            continue
        if blocker is not None:
            _block(blocker, scheduled)
            continue
        if scheduled.status == RunStatus.FAILED and scheduled.attempts >= conf.run_max_retries():
            if scheduled.step == RunStep.HEARING:
                blocker = scheduled
            continue
        status = _execute(order, scheduled)
        if status == RunStatus.RUNNING:
            busy = True  # another delivery runs this step and carries on with the rest
            break
        if status == RunStatus.FAILED and scheduled.step == RunStep.HEARING:
            blocker = scheduled
    retryable = sum(
        1
        for scheduled in order.runs.all()
        if scheduled.status == RunStatus.FAILED and scheduled.attempts < conf.run_max_retries()
    )
    # A claimed step whose worker died is taken over once its lease ends: look again then.
    return retryable + int(busy)


def _block(hearing, scheduled):
    """Mark ``scheduled`` blocked by the failed ``hearing`` step, if it still is.

    Decided under the hearing step's row lock, which its recovery to ``DONE`` also
    takes (``_execute``): once another delivery has recovered the hearing, its
    dependent steps run normally, and a failure of theirs stays retryable. The
    step's own ``DONE``, or a claim on it within the lease, also stands.
    """
    with transaction.atomic():
        status = (
            OrderWorkflowRun.objects.select_for_update()
            .values_list("status", flat=True)
            .get(pk=hearing.pk)
        )
        if status != RunStatus.FAILED:
            return
        now = timezone.now()
        OrderWorkflowRun.objects.filter(pk=scheduled.pk).exclude(status=RunStatus.DONE).exclude(
            status=RunStatus.RUNNING, updated_at__gt=now - LEASE
        ).update(status=RunStatus.BLOCKED, error_code="HEARING_STEP_FAILED", updated_at=now)


def _mark(run, status, *, result=None, error_code=""):
    run.status = status
    run.error_code = error_code
    if result is not None:
        # Progress a step recorded survives its own failure, so a retry resumes from it.
        kept = {"done": run.result["done"]} if "done" in run.result else {}
        run.result = {**kept, **result}
    run.save(update_fields=["status", "error_code", "result", "updated_at"])


def _execute(order, scheduled):
    """Run one step in its own transaction; return its final status."""
    with transaction.atomic():
        locked = OrderWorkflowRun.objects.select_for_update().get(pk=scheduled.pk)
        if locked.status == RunStatus.DONE:
            return locked.status
        if locked.status == RunStatus.RUNNING and timezone.now() - locked.updated_at < LEASE:
            return locked.status
        if locked.status == RunStatus.FAILED and locked.attempts >= conf.run_max_retries():
            # Another delivery spent the last attempt since this one read the runs.
            return locked.status
        locked.attempts += 1
        locked.status = RunStatus.RUNNING
        locked.claim_token = claim = uuid.uuid4()
        locked.save(update_fields=["attempts", "status", "claim_token", "updated_at"])
    try:
        if scheduled.step == RunStep.HEARING:
            result = _hearing_step(order)
        elif scheduled.step == RunStep.ITEM:
            result = _item_step(order, scheduled)
        else:
            result = _stage_step(order, scheduled)
        status, payload, error = result
    except HearingError as exc:
        status, payload, error = RunStatus.FAILED, {"message": exc.message}, exc.code
    except Exception:
        logger.exception("event=ORDER_RUN_ERROR order=%s run=%s", order.pk, scheduled.pk)
        status, payload, error = RunStatus.FAILED, {}, "UNEXPECTED_ERROR"
    with transaction.atomic():
        row = OrderWorkflowRun.objects.select_for_update().get(pk=scheduled.pk)
        # A later worker claimed this step after the lease ran out: its status stands.
        owned = row.claim_token == claim
        if owned:
            _mark(row, status, result=payload, error_code=error)
    if not owned:
        logger.warning(
            "event=ORDER_RUN_SUPERSEDED order_id=%s run=%s step=%s",
            order.pk,
            scheduled.pk,
            scheduled.step,
        )
    elif status == RunStatus.FAILED:
        logger.error(
            "event=ORDER_RUN_FAILED order_id=%s run=%s step=%s error_code=%s",
            order.pk,
            scheduled.pk,
            scheduled.step,
            error,
        )
    scheduled.refresh_from_db()
    return scheduled.status


def _hearing_step(order):
    """Confirm the held date; a rescheduling order moves the original hearing (#9.2)."""
    hearing = listing.confirm(
        order_id=order.pk,
        actor=order.signed_by,
        reason_code=RescheduleReason.JUDICIAL_DIRECTION,
        sought_by=Side.COURT,
    )
    return RunStatus.DONE, {"hearing_id": str(hearing.pk)}, ""


def _item_step(order, scheduled):
    item = scheduled.order_item
    handler = items.handler_for(item.item_type)
    ctx = items.context_for(order, item=item)
    outcome = handler.execute(ctx, item.values, run_id=scheduled.pk)
    status = RunStatus.DONE if outcome.status == "DONE" else RunStatus.FAILED
    return status, outcome.payload, outcome.error_code


def _once(scheduled, key, action):
    """Run ``action`` unless this run already did, and record that it did (re-run safe)."""
    if key in scheduled.result.get("done", []):
        return
    action()
    with transaction.atomic():
        row = OrderWorkflowRun.objects.select_for_update().get(pk=scheduled.pk)
        row.result = {**row.result, "done": [*row.result.get("done", []), key]}
        row.save(update_fields=["result", "updated_at"])
    scheduled.result = row.result


def _stage_step(order, scheduled):
    """Stage events, the cognizance task, hearing cancellation and the outcome (#9.4).

    This module never writes a stage or ``Case.status`` (``PUB-05``): it
    dispatches events and the 0011 definition decides. Each action is recorded
    in the run as it completes, so a re-run after a partial failure does only
    what is left; events carry an ``idempotency_key`` for their receivers.
    """
    scheduled.refresh_from_db()
    done = []
    order_items = list(order.items.select_related("item_type").order_by("position"))
    for item in order_items:
        event = item.item_type.stage_event
        if event:
            context = {
                "order_id": str(order.pk),
                "item_code": item.item_type.code,
                "idempotency_key": f"{scheduled.pk}:{item.pk}:{event}",
            }
            _once(
                scheduled,
                f"event:{item.pk}",
                lambda event=event, context=context: ports.dispatch_stage_event(
                    order.case_id, event, context
                ),
            )
            done.append(event)
    if any(item.item_type.code in COGNIZANCE_TASK_ITEMS for item in order_items):
        _once(
            scheduled,
            "cognizance",
            lambda: ports.complete_case_task(order.case_id, "take_cognizance"),
        )
    for item in order_items:
        reason = item.item_type.closes_case
        if reason:
            _once(
                scheduled,
                f"close:{item.pk}",
                lambda reason=reason: listing.cancel_open_hearings(
                    case_id=order.case_id,
                    reason=reason,
                    order_id=order.pk,
                    actor=order.signed_by,
                ),
            )
            done.append(f"closed:{reason}")
        if item.item_type.outcome:
            _once(
                scheduled,
                f"outcome:{item.pk}",
                lambda outcome=item.item_type.outcome: ports.record_outcome(
                    order.case_id, outcome, order.pk
                ),
            )
    return RunStatus.DONE, {"stage": done}, ""


def retry_failed(order_id):
    """Admin: make every ``FAILED`` and ``BLOCKED`` step pending again and run them (#12.8)."""
    with transaction.atomic():
        stuck = OrderWorkflowRun.objects.filter(
            order_id=order_id, status__in=(RunStatus.FAILED, RunStatus.BLOCKED)
        )
        # Lock in sequence order, the HEARING step first, as ``_block`` does: no deadlock.
        list(stuck.select_for_update().order_by("sequence").values_list("pk", flat=True))
        retried = stuck.update(status=RunStatus.PENDING, attempts=0, error_code="")
        if retried:
            enqueue_on_commit(order_id)
    return retried


__all__ = ["enqueue_on_commit", "retry_failed", "run", "sweep_stranded", "write_runs"]
