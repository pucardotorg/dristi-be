"""Triggering (spec 0039 #9): the runs, their order, idempotence, failure and retry."""

import datetime

import pytest
from django.utils import timezone

from apps.cases.models import Case
from apps.hearings.enums import HearingStatus
from apps.hearings.models import CourtCalendarEntry, Hearing
from apps.orders import tasks
from apps.orders.enums import RunStatus
from apps.orders.models import Order, OrderWorkflowRun
from apps.orders.services import items, lifecycle, signing, triggering

from .factories import TODAY, schedule

pytestmark = pytest.mark.django_db

COST = {
    "paying_party": "ACCUSED",
    "amount": "250.00",
    "receiving_party": "COMPLAINANT",
    "pay_by": "2026-12-01",
}


def summons(case):
    """A summons to the accused with one channel, as the mandatory fields need."""
    from apps.cases.models import CaseParticipant, ParticipantRole

    accused = CaseParticipant.objects.get(case=case, role=ParticipantRole.ACCUSED)
    return {"recipients": [{"party_id": str(accused.pk), "channels": ["EMAIL"], "addresses": []}]}


def trigger(order, staff, signer, *item_specs, holiday=False):
    """Add the items, complete, send, (optionally close the held date) and sign: triggered."""
    for spec in item_specs:
        code, values = spec if isinstance(spec, tuple) else (spec, {})
        items.add(order.pk, code, actor=staff, values=values)
    lifecycle.mark_complete(order.pk, actor=staff)
    lifecycle.send_for_signing(order.pk, actor=staff)
    if holiday:
        CourtCalendarEntry.objects.create(
            court=order.court, date=order.next_hearing_date, entry_type="HOLIDAY", reason="Closed"
        )
    signing.record_signed_file(order.pk, "signed", "DSC", actor=signer)
    return Order.objects.get(pk=order.pk)


def runs(order):
    return [
        (r.step, r.order_item.item_type.code if r.order_item else None, r.status)
        for r in OrderWorkflowRun.objects.filter(order=order).select_related(
            "order_item__item_type"
        )
    ]


def test_runs_are_written_in_the_catalogues_order(ready, staff, signer):
    # Added in this order: a closing item, a normal one, another normal one.
    order = trigger(
        ready,
        staff,
        signer,
        "JUDGEMENT",
        ("COST", COST),
        "COGNIZANCE",
        ("ISSUE_OF_SUMMONS", summons(ready.case)),
    )
    plan = [(step, code) for step, code, _ in runs(order)]
    assert plan == [
        ("HEARING", None),
        ("ITEM", "COST"),
        ("ITEM", "ISSUE_OF_SUMMONS"),
        ("STAGE", None),
    ]
    assert list(
        OrderWorkflowRun.objects.filter(order=order).values_list("sequence", flat=True)
    ) == [1, 2, 3, 4]


def test_closing_items_run_after_the_others_and_scheduling_items_first(case, staff, signer, setter):
    from apps.orders.services import drafting, next_hearing

    schedule(case, TODAY.replace(day=19))
    order = drafting.create_outside_hearing(case_id=case.pk, actor=staff)
    drafting.edit_text(order.pk, "<p>x</p>", actor=staff)
    next_hearing.set_next_hearing(
        order.pk, state="LISTED", date=TODAY.replace(day=26), purpose="APPEARANCE", actor=setter
    )
    order = trigger(order, staff, signer, ("COST", COST), "BAIL")
    plan = [(step, code) for step, code, _ in runs(order)]
    assert plan[0] == ("HEARING", None)
    assert [code for step, code in plan if step == "ITEM"] == [
        "RESCHEDULING_OF_HEARING_DATE",
        "COST",
        "BAIL",
    ]


def test_running_confirms_the_date_runs_the_items_and_dispatches_the_stage_event(
    ready, staff, signer, record_ports, hearing
):
    order = trigger(ready, staff, signer, ("COST", COST), "COGNIZANCE")
    assert triggering.run(order.pk) == 0
    assert {status for _, _, status in runs(order)} == {RunStatus.DONE}
    confirmed = Hearing.objects.get(source_order_id=order.pk)
    assert confirmed.status == HearingStatus.SCHEDULED
    stage_events = [args[1] for n, args, _ in record_ports if n == "dispatch_stage_event"]
    assert stage_events == ["COGNIZANCE_TAKEN"]
    assert ("complete_case_task", "take_cognizance") in [
        (n, args[1]) for n, args, _ in record_ports if n == "complete_case_task"
    ]
    # Orders never write a case stage or status.
    assert Case.objects.get(pk=order.case_id).status == "REGISTERED"


def test_cost_raises_a_demand_and_a_task(ready, staff, signer, record_ports):
    from apps.payments.models import Demand

    order = trigger(ready, staff, signer, ("COST", COST))
    triggering.run(order.pk)
    demand = Demand.objects.get(reference_type="ORDER")
    assert str(demand.total_amount) == "250.00"
    assert demand.case_id == order.case_id
    assert demand.metadata["receiving_party"] == "COMPLAINANT"
    assert "pay_cost" in [args[2] for n, args, _ in record_ports if n == "open_item_task"]


def test_a_redelivered_run_finishes_instead_of_repeating(ready, staff, signer, record_ports):
    from apps.payments.models import Demand

    order = trigger(ready, staff, signer, ("COST", COST))
    triggering.run(order.pk)
    triggering.run(order.pk)
    triggering.run(order.pk)
    assert Demand.objects.filter(reference_type="ORDER").count() == 1
    assert set(OrderWorkflowRun.objects.filter(order=order).values_list("attempts", flat=True)) == {
        1
    }


def test_a_closing_item_cancels_the_cases_open_hearings(ready, staff, signer, case, record_ports):
    order = trigger(ready, staff, signer, "JUDGEMENT")
    triggering.run(order.pk)
    # The order's own date was confirmed first, then cancelled by the case closing last.
    hearing = Hearing.objects.get(source_order_id=order.pk)
    assert hearing.status == HearingStatus.CANCELLED
    assert hearing.cancellation_reason == "CASE_DISPOSED"


def test_issue_of_notice_leaves_the_cognizance_task_open(ready, staff, signer, record_ports):
    notice = {**summons(ready.case), "notice_type": "SHOW_CAUSE"}
    order = trigger(ready, staff, signer, ("ISSUE_OF_NOTICE", notice))
    triggering.run(order.pk)
    assert [n for n, *_ in record_ports if n == "complete_case_task"] == []


def test_dismiss_case_completes_the_cognizance_task(ready, staff, signer, record_ports):
    order = trigger(ready, staff, signer, "DISMISS_CASE")
    triggering.run(order.pk)
    assert [n for n, *_ in record_ports if n == "complete_case_task"] == ["complete_case_task"]


def test_a_failed_hearing_step_blocks_every_later_step(ready, staff, signer):
    order = trigger(ready, staff, signer, ("COST", COST), "COGNIZANCE", holiday=True)
    triggering.run(order.pk)
    statuses = {step: status for step, _, status in runs(order)}
    assert statuses["HEARING"] == RunStatus.FAILED
    assert {status for step, _, status in runs(order) if step != "HEARING"} == {RunStatus.BLOCKED}
    failed = OrderWorkflowRun.objects.get(order=order, step="HEARING")
    assert failed.error_code == "E10023"


def test_admin_retry_runs_a_blocked_step_once_the_hearing_step_succeeds(
    ready, staff, signer, django_capture_on_commit_callbacks
):
    order = trigger(ready, staff, signer, ("COST", COST), holiday=True)
    triggering.run(order.pk)
    CourtCalendarEntry.objects.filter(court=order.court).delete()
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        assert triggering.retry_failed(order.pk) == 2
    assert len(callbacks) == 1
    triggering.run(order.pk)
    assert {status for _, _, status in runs(order)} == {RunStatus.DONE}


def test_another_failure_is_recorded_and_the_next_step_runs(ready, staff, signer):
    # Summons has only the placeholder handler (apps.processes is not built).
    order = trigger(ready, staff, signer, ("ISSUE_OF_SUMMONS", summons(ready.case)), ("COST", COST))
    triggering.run(order.pk)
    statuses = {code: status for step, code, status in runs(order) if step == "ITEM"}
    assert statuses["ISSUE_OF_SUMMONS"] == RunStatus.FAILED
    assert statuses["COST"] == RunStatus.DONE
    failed = OrderWorkflowRun.objects.get(order_item__item_type__code="ISSUE_OF_SUMMONS")
    assert failed.error_code == "HANDLER_MODULE_NOT_AVAILABLE"
    assert OrderWorkflowRun.objects.get(order=order, step="HEARING").status == RunStatus.DONE


def test_a_failed_step_is_retried_up_to_the_limit_then_stays_failed(ready, staff, signer):
    order = trigger(ready, staff, signer, ("ISSUE_OF_SUMMONS", summons(ready.case)))
    remaining = [triggering.run(order.pk) for _ in range(4)]
    assert remaining == [1, 1, 0, 0]
    failed = OrderWorkflowRun.objects.get(order_item__item_type__code="ISSUE_OF_SUMMONS")
    assert (failed.attempts, failed.status) == (3, RunStatus.FAILED)


def test_the_actor_schedules_another_pass_while_steps_remain_retryable(ready, staff, signer):
    from unittest import mock

    from apps.orders.tasks import run_order_workflows

    order = trigger(ready, staff, signer, ("ISSUE_OF_SUMMONS", summons(ready.case)))
    with mock.patch.object(run_order_workflows, "send_with_options") as again:
        tasks.run_order_workflows(str(order.pk))
    again.assert_called_once()
    assert again.call_args.kwargs["delay"] == 30_000


def test_an_order_with_no_workflow_items_still_confirms_its_date(ready, staff, signer):
    order = trigger(ready, staff, signer)
    assert runs(order) == [("HEARING", None, RunStatus.PENDING)]
    triggering.run(order.pk)
    assert runs(order) == [("HEARING", None, RunStatus.DONE)]


def test_the_trigger_enqueues_the_actor_on_commit_only(
    ready, staff, signer, django_capture_on_commit_callbacks
):
    from unittest import mock

    from apps.orders.tasks import run_order_workflows

    lifecycle.mark_complete(ready.pk, actor=staff)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    with mock.patch.object(run_order_workflows, "send") as send:
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            signing.record_signed_file(ready.pk, "signed", "DSC", actor=signer)
        send.assert_not_called()
        for callback in callbacks:
            callback()
    send.assert_called_once_with(str(ready.pk))


def test_a_rerun_stage_step_dispatches_only_what_was_not_done(
    ready, staff, signer, record_ports, monkeypatch
):
    from apps.orders import ports
    from apps.orders.enums import RunStatus

    order = trigger(ready, staff, signer, "COGNIZANCE")
    real = ports.dispatch_stage_event
    calls = []

    def dispatch(case_id, event, context):
        calls.append((event, context["idempotency_key"]))
        real(case_id, event, context)

    monkeypatch.setattr(ports, "dispatch_stage_event", dispatch)
    monkeypatch.setattr(
        ports, "complete_case_task", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    )
    triggering.run(order.pk)
    stage = order.runs.get(step="STAGE")
    assert stage.status == RunStatus.FAILED and stage.result["done"]
    monkeypatch.setattr(ports, "complete_case_task", lambda *a, **k: None)
    triggering.retry_failed(order.pk)
    triggering.run(order.pk)
    assert order.runs.get(step="STAGE").status == RunStatus.DONE
    assert len(calls) == 1  # the event sent before the failure is not sent again


def test_a_step_another_delivery_is_running_is_not_started_twice(ready, staff, signer):
    from apps.orders.enums import RunStatus

    order = trigger(ready, staff, signer, "COGNIZANCE")
    stage = order.runs.get(step="STAGE")
    OrderWorkflowRun.objects.filter(pk=stage.pk).update(status=RunStatus.RUNNING)
    assert triggering.run(order.pk) == 1  # the caller looks again later
    stage.refresh_from_db()
    assert stage.status == RunStatus.RUNNING and stage.attempts == 0


def test_a_step_left_running_by_a_dead_worker_is_taken_over_after_the_lease(ready, staff, signer):
    from apps.orders.enums import RunStatus

    order = trigger(ready, staff, signer, "COGNIZANCE")
    stage = order.runs.get(step="STAGE")
    OrderWorkflowRun.objects.filter(pk=stage.pk).update(
        status=RunStatus.RUNNING,
        updated_at=timezone.now() - triggering.LEASE - datetime.timedelta(seconds=1),
    )
    assert triggering.run(order.pk) == 0
    assert order.runs.get(step="STAGE").status == RunStatus.DONE


def test_a_stale_worker_that_fails_after_a_takeover_keeps_the_done_status(
    ready, staff, signer, monkeypatch
):
    import uuid

    order = trigger(ready, staff, signer, "COGNIZANCE")
    stage = order.runs.get(step="STAGE")

    def overrun(order_, scheduled):
        # The lease ran out mid-step: a second worker claimed the row and finished it.
        OrderWorkflowRun.objects.filter(pk=scheduled.pk).update(
            status=RunStatus.DONE, claim_token=uuid.uuid4(), attempts=0
        )
        raise RuntimeError("the first worker fails late")

    monkeypatch.setattr(triggering, "_stage_step", overrun)
    assert triggering._execute(order, stage) == RunStatus.DONE
    stage.refresh_from_db()
    assert stage.status == RunStatus.DONE and stage.error_code == ""


def test_a_stale_worker_does_not_overwrite_a_live_claim(ready, staff, signer, monkeypatch):
    import uuid

    order = trigger(ready, staff, signer, "COGNIZANCE")
    stage = order.runs.get(step="STAGE")

    def overrun(order_, scheduled):
        OrderWorkflowRun.objects.filter(pk=scheduled.pk).update(claim_token=uuid.uuid4())
        return RunStatus.DONE, {}, ""

    monkeypatch.setattr(triggering, "_stage_step", overrun)
    assert triggering._execute(order, stage) == RunStatus.RUNNING  # the live claim stands


def test_an_ordinary_completion_still_writes_its_status(ready, staff, signer, monkeypatch):
    order = trigger(ready, staff, signer, "COGNIZANCE")
    stage = order.runs.get(step="STAGE")
    monkeypatch.setattr(triggering, "_stage_step", lambda o, s: (RunStatus.FAILED, {}, "BOOM"))
    assert triggering._execute(order, stage) == RunStatus.FAILED
    stage.refresh_from_db()
    assert stage.error_code == "BOOM" and stage.claim_token is not None


def test_a_blocked_write_never_overwrites_a_step_another_delivery_finished(
    ready, staff, signer, monkeypatch
):
    """The runs are read once; a later step finished by another delivery stays DONE."""
    order = trigger(ready, staff, signer, ("COST", COST), "COGNIZANCE")
    cost = OrderWorkflowRun.objects.get(order=order, order_item__item_type__code="COST")
    real = triggering._execute

    def racing(order, scheduled):
        if scheduled.step != "HEARING":
            return real(order, scheduled)
        # While this delivery runs the hearing step, another one finishes the COST step.
        OrderWorkflowRun.objects.filter(pk=cost.pk).update(status=RunStatus.DONE)
        OrderWorkflowRun.objects.filter(pk=scheduled.pk).update(
            status=RunStatus.FAILED, attempts=1, error_code="E10023"
        )
        return RunStatus.FAILED

    monkeypatch.setattr(triggering, "_execute", racing)
    assert triggering.run(order.pk) == 1  # only the failed hearing step is retryable
    statuses = {code: status for step, code, status in runs(order) if step != "HEARING"}
    assert statuses["COST"] == RunStatus.DONE
    assert {status for code, status in statuses.items() if code != "COST"} == {RunStatus.BLOCKED}
    assert OrderWorkflowRun.objects.get(pk=cost.pk).error_code == ""
