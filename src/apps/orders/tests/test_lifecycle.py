"""The lifecycle (spec 0039 #4, #6.7, #7, #9.1): send, move back, complete, trigger."""

import pytest

from apps.api.errors import BusinessError
from apps.hearings.models import Hearing
from apps.orders import signals
from apps.orders.enums import OrderStatus, TaskKey
from apps.orders.models import Order, OrderWorkflowRun
from apps.orders.services import common, drafting, items, lifecycle, next_hearing, signing

from .factories import TODAY, code, mark_roll

pytestmark = pytest.mark.django_db


def names(calls, kind):
    return [(args[1], kwargs.get("role")) for name, args, kwargs in calls if name == kind]


def sign(order, signer):
    """Record a signature the way a DSC module would: nothing e-sign specific."""
    return signing.record_signed_file(order.pk, "signed-file-1", "DSC", actor=signer)


# -- send for signing ------------------------------------------------------------------


def test_send_needs_text(order, hearing, staff, setter):
    next_hearing.set_next_hearing(order.pk, state="NOT_LISTED_AGAIN", actor=setter)
    mark_roll(hearing, staff)
    for blank in ("", "<p>&nbsp;</p>", "<p> </p>"):
        drafting.edit_text(order.pk, blank, actor=staff)
        with pytest.raises(BusinessError) as excinfo:
            lifecycle.send_for_signing(order.pk, actor=staff)
        assert code(excinfo) == "E14005"


def test_send_needs_a_settled_next_hearing(order, hearing, staff):
    drafting.edit_text(order.pk, "<p>Heard.</p>", actor=staff)
    mark_roll(hearing, staff)
    with pytest.raises(BusinessError) as excinfo:
        lifecycle.send_for_signing(order.pk, actor=staff)
    assert code(excinfo) == "E14006"


def test_send_needs_complete_attendance_in_a_hearing(order, staff, setter):
    drafting.edit_text(order.pk, "<p>Heard.</p>", actor=staff)
    next_hearing.set_next_hearing(order.pk, state="NOT_LISTED_AGAIN", actor=setter)
    with pytest.raises(BusinessError) as excinfo:
        lifecycle.send_for_signing(order.pk, actor=staff)
    assert code(excinfo) == "E14007"


def test_an_order_outside_a_hearing_needs_no_attendance(case, staff, setter):
    order = drafting.create_outside_hearing(case_id=case.pk, actor=staff)
    drafting.edit_text(order.pk, "<p>Cognizance taken.</p>", actor=staff)
    next_hearing.set_next_hearing(order.pk, state="NOT_LISTED_AGAIN", actor=setter)
    assert lifecycle.send_for_signing(order.pk, actor=staff).status == OrderStatus.SENT_FOR_SIGNING


def test_sending_opens_sign_and_fill_tasks_and_closes_the_draft_task(ready, staff, record_ports):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    assert (TaskKey.DRAFT_ORDER, None) in names(record_ports, "complete_task")
    assert [role for _, role in names(record_ports, "open_task")][-2:] == [
        "ORDER_SIGNER",
        "ORDER_DATA_FILLER",
    ]


def test_order_data_need_not_be_filled_to_send(ready, staff):
    items.add(ready.pk, "COST", actor=staff)  # mandatory fields empty
    ready.refresh_from_db()
    assert lifecycle.send_for_signing(ready.pk, actor=staff).status == OrderStatus.SENT_FOR_SIGNING


def test_complete_data_opens_no_fill_task(ready, staff, record_ports):
    items.add(ready.pk, "JUDGEMENT", actor=staff)
    lifecycle.mark_complete(ready.pk, actor=staff)
    record_ports.clear()
    lifecycle.send_for_signing(ready.pk, actor=staff)
    assert TaskKey.FILL_ORDER_DATA not in [
        args[1] for n, args, _ in record_ports if n == "open_task"
    ]


def test_only_a_draft_can_be_sent_and_the_error_names_what_is_allowed(ready, staff):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    with pytest.raises(BusinessError) as excinfo:
        lifecycle.send_for_signing(ready.pk, actor=staff)
    assert code(excinfo) == "E14001"
    assert excinfo.value.allowed_actions == [
        "edit_title",
        "change_type",
        "link_document",
        "move_to_draft",
        "sign",
        "add_item",
        "edit_item",
        "remove_item",
        "confirm_item",
        "mark_complete",
        "edit_diary_entry",
    ]


# -- move back ---------------------------------------------------------------------------


def test_moving_back_clears_the_signing_and_swaps_the_tasks(ready, staff, record_ports):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    Order.objects.filter(pk=ready.pk).update(signing_file_id="prepared")
    record_ports.clear()
    order = lifecycle.move_to_draft(ready.pk, actor=staff)
    assert order.status == OrderStatus.DRAFT
    assert order.signing_file_id == ""
    assert {args[1] for n, args, _ in record_ports if n == "expire_task"} == {
        TaskKey.SIGN_ORDER,
        TaskKey.FILL_ORDER_DATA,
    }
    assert [args[1] for n, args, _ in record_ports if n == "open_task"] == [TaskKey.DRAFT_ORDER]


def test_move_back_is_refused_after_signing(ready, staff, signer):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    sign(ready, signer)
    with pytest.raises(BusinessError) as excinfo:
        lifecycle.move_to_draft(ready.pk, actor=staff)
    assert code(excinfo) == "E14016"


def test_a_resend_resets_complete_data_and_keeps_its_values(ready, staff):
    item = items.add(
        ready.pk,
        "COST",
        actor=staff,
        values={
            "amount": "9.00",
            "paying_party": "ACCUSED",
            "receiving_party": "COURT",
            "pay_by": "2026-12-01",
        },
    )
    lifecycle.mark_complete(ready.pk, actor=staff)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    lifecycle.move_to_draft(ready.pk, actor=staff)
    order = lifecycle.send_for_signing(ready.pk, actor=staff)
    assert order.data_complete is False
    item.refresh_from_db()
    assert item.values["amount"] == "9.00"


# -- completion and triggering --------------------------------------------------------------------


def test_signing_an_order_with_incomplete_data_does_not_trigger_it(ready, staff, signer):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    order = sign(ready, signer)
    assert order.status == OrderStatus.SIGNED
    assert order.signed_by == signer
    assert order.triggered_at is None
    assert not OrderWorkflowRun.objects.filter(order=order).exists()


def test_completing_data_on_a_signed_order_triggers_it(ready, staff, signer):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    sign(ready, signer)
    order = lifecycle.mark_complete(ready.pk, actor=staff)
    assert order.status == OrderStatus.TRIGGERED
    assert order.triggered_at is not None


def test_signing_an_order_with_complete_data_triggers_it(ready, staff, signer):
    lifecycle.mark_complete(ready.pk, actor=staff)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    order = sign(ready, signer)
    assert order.status == OrderStatus.TRIGGERED


def test_sign_and_complete_in_either_order_trigger_exactly_once(
    hearing, order, staff, signer, setter, django_capture_on_commit_callbacks
):
    drafting.edit_text(order.pk, "<p>x</p>", actor=staff)
    next_hearing.set_next_hearing(
        order.pk, state="LISTED", date=TODAY.replace(day=19), purpose="APPEARANCE", actor=setter
    )
    mark_roll(hearing, staff)
    received = []
    receiver = lambda **kw: received.append(kw["order_id"])  # noqa: E731
    signals.order_triggered.connect(receiver, weak=False)
    try:
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            lifecycle.send_for_signing(order.pk, actor=staff)
            sign(order, signer)
            lifecycle.mark_complete(order.pk, actor=staff)
            # Marking complete again, or signing again, is refused: no second trigger.
            with pytest.raises(BusinessError) as again:
                lifecycle.mark_complete(order.pk, actor=staff)
            assert code(again) == "E14001"
            with pytest.raises(BusinessError):
                sign(order, signer)
        assert received == []  # nothing is sent before the commit
        for callback in callbacks:
            callback()
    finally:
        signals.order_triggered.disconnect(receiver)
    assert received == [order.pk]
    assert OrderWorkflowRun.objects.filter(order=order, step="HEARING").count() == 1


def test_triggering_locks_attendance_and_expires_the_draft_task(
    ready, staff, signer, hearing, record_ports
):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    sign(ready, signer)
    lifecycle.mark_complete(ready.pk, actor=staff)
    assert Hearing.objects.get(pk=hearing.pk).attendance_locked_at is not None
    assert TaskKey.DRAFT_ORDER in [args[1] for n, args, _ in record_ports if n == "expire_task"]


def test_a_triggered_order_accepts_nothing_more(ready, staff, signer):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    sign(ready, signer)
    lifecycle.mark_complete(ready.pk, actor=staff)
    for action in (
        lambda: drafting.edit_text(ready.pk, "<p>x</p>", actor=staff),
        lambda: drafting.edit_title(ready.pk, "x", actor=staff),
        lambda: drafting.change_type(ready.pk, "NORMAL", actor=staff),
        lambda: items.add(ready.pk, "BAIL", actor=staff),
        lambda: lifecycle.reopen(ready.pk, actor=staff),
        lambda: drafting.discard(ready.pk, actor=staff),
    ):
        with pytest.raises(BusinessError) as excinfo:
            action()
        assert code(excinfo) in ("E14001", "E14016")


def test_a_held_date_that_can_no_longer_be_confirmed_stops_completion_of_a_signed_order(
    ready, staff, signer, settings
):
    from apps.hearings.models import CourtCalendarEntry

    lifecycle.send_for_signing(ready.pk, actor=staff)
    sign(ready, signer)
    CourtCalendarEntry.objects.create(
        court=ready.court, date=ready.next_hearing_date, entry_type="HOLIDAY", reason="Closed"
    )
    with pytest.raises(BusinessError) as excinfo:
        lifecycle.mark_complete(ready.pk, actor=staff)
    assert code(excinfo) == "E10006"
    assert Order.objects.get(pk=ready.pk).status == OrderStatus.SIGNED


def test_reopen_is_possible_only_before_signing(ready, staff, signer):
    lifecycle.mark_complete(ready.pk, actor=staff)
    assert lifecycle.reopen(ready.pk, actor=staff).data_complete is False
    lifecycle.send_for_signing(ready.pk, actor=staff)
    sign(ready, signer)
    lifecycle.mark_complete(ready.pk, actor=staff)  # triggers
    with pytest.raises(BusinessError) as excinfo:
        lifecycle.reopen(ready.pk, actor=staff)
    assert code(excinfo) == "E14016"


def test_pending_stages_are_read_from_the_facts(ready, staff, signer):
    assert common.stages(ready) == ["DRAFTING"]
    lifecycle.send_for_signing(ready.pk, actor=staff)
    ready.refresh_from_db()
    assert common.stages(ready) == ["AWAITING_SIGNATURE", "ORDER_DATA_TO_FILL"]
    sign(ready, signer)
    ready.refresh_from_db()
    assert common.stages(ready) == ["ORDER_DATA_TO_FILL"]
    lifecycle.mark_complete(ready.pk, actor=staff)
    ready.refresh_from_db()
    assert common.stages(ready) == ["TRIGGERED"]
    assert TODAY
