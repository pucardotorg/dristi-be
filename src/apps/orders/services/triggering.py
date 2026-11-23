"""Triggering: the workflow runs of a triggered order (#9).

``write_runs`` records every step in the trigger transaction, in the catalogue's
order; ``run_order_workflows`` executes them after commit. A step already
``DONE`` is skipped, so a redelivered message finishes the order rather than
repeating it. A failed ``HEARING`` step blocks everything after it: processes
and tasks point at the hearing. Any other failure is recorded and the next step
runs. A failed step is retried with backoff up to ``orders.run_max_retries``,
then stays ``FAILED`` until an admin retries it.
"""

import logging

from django.db import transaction

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
    """Enqueue ``run_order_workflows`` once the transaction commits (#12.7)."""
    from ..tasks import run_order_workflows

    def send():
        if delay_ms:
            run_order_workflows.send_with_options(args=(str(order_id),), delay=delay_ms)
        else:
            run_order_workflows.send(str(order_id))

    transaction.on_commit(send)


def run(order_id):
    """Execute the order's pending steps in sequence; return how many remain retryable (#9.2).

    Idempotent: ``DONE`` steps are skipped. A caller (the actor) re-enqueues
    itself with backoff while retryable steps remain.
    """
    order = Order.objects.select_related("order_type", "court").get(pk=order_id)
    runs = list(order.runs.select_related("order_item__item_type").order_by("sequence"))
    blocked = False
    for scheduled in runs:
        if scheduled.status == RunStatus.DONE:
            continue
        if blocked:
            _mark(scheduled, RunStatus.BLOCKED, error_code="HEARING_STEP_FAILED")
            continue
        if scheduled.status == RunStatus.FAILED and scheduled.attempts >= conf.run_max_retries():
            blocked = scheduled.step == RunStep.HEARING
            continue
        status = _execute(order, scheduled)
        if status == RunStatus.FAILED and scheduled.step == RunStep.HEARING:
            blocked = True
    return sum(
        1
        for scheduled in order.runs.all()
        if scheduled.status == RunStatus.FAILED and scheduled.attempts < conf.run_max_retries()
    )


def _mark(run, status, *, result=None, error_code=""):
    run.status = status
    run.error_code = error_code
    if result is not None:
        run.result = result
    run.save(update_fields=["status", "error_code", "result", "updated_at"])


def _execute(order, scheduled):
    """Run one step in its own transaction; return its final status."""
    with transaction.atomic():
        locked = OrderWorkflowRun.objects.select_for_update().get(pk=scheduled.pk)
        if locked.status == RunStatus.DONE:
            return locked.status
        locked.attempts += 1
        locked.save(update_fields=["attempts", "updated_at"])
    try:
        if scheduled.step == RunStep.HEARING:
            result = _hearing_step(order)
        elif scheduled.step == RunStep.ITEM:
            result = _item_step(order, scheduled)
        else:
            result = _stage_step(order)
        status, payload, error = result
    except HearingError as exc:
        status, payload, error = RunStatus.FAILED, {"message": exc.message}, exc.code
    except Exception:
        logger.exception("event=ORDER_RUN_ERROR order=%s run=%s", order.pk, scheduled.pk)
        status, payload, error = RunStatus.FAILED, {}, "UNEXPECTED_ERROR"
    with transaction.atomic():
        _mark(
            OrderWorkflowRun.objects.select_for_update().get(pk=scheduled.pk),
            status,
            result=payload,
            error_code=error,
        )
    if status == RunStatus.FAILED:
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


def _stage_step(order):
    """Stage events, the cognizance task, hearing cancellation and the outcome (#9.4).

    This module never writes a stage or ``Case.status`` (``PUB-05``): it
    dispatches events and the 0011 definition decides.
    """
    done = []
    order_items = list(order.items.select_related("item_type").order_by("position"))
    for item in order_items:
        event = item.item_type.stage_event
        if event:
            ports.dispatch_stage_event(
                order.case_id, event, {"order_id": str(order.pk), "item_code": item.item_type.code}
            )
            done.append(event)
    if any(item.item_type.code in COGNIZANCE_TASK_ITEMS for item in order_items):
        ports.complete_case_task(order.case_id, "take_cognizance")
    for item in order_items:
        reason = item.item_type.closes_case
        if reason:
            listing.cancel_open_hearings(
                case_id=order.case_id, reason=reason, order_id=order.pk, actor=order.signed_by
            )
            done.append(f"closed:{reason}")
        if item.item_type.outcome:
            ports.record_outcome(order.case_id, item.item_type.outcome, order.pk)
    return RunStatus.DONE, {"stage": done}, ""


def retry_failed(order_id):
    """Admin: make every ``FAILED`` and ``BLOCKED`` step pending again and run them (#12.8)."""
    with transaction.atomic():
        retried = OrderWorkflowRun.objects.filter(
            order_id=order_id, status__in=(RunStatus.FAILED, RunStatus.BLOCKED)
        ).update(status=RunStatus.PENDING, attempts=0, error_code="")
        if retried:
            enqueue_on_commit(order_id)
    return retried


__all__ = ["enqueue_on_commit", "retry_failed", "run", "write_runs"]
