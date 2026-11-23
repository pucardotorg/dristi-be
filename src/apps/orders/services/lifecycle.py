"""The order lifecycle: send for signing, move back, mark complete, reopen, trigger (#4, #6.7, #7, #9.1).

Every action runs in ``transaction.atomic()`` under the order's row lock and
re-reads its status (#12.5), so *Sign* and *Mark complete* arriving together
trigger the order exactly once.
"""

from django.db import transaction
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.hearings.exceptions import HearingError
from apps.hearings.services import courtroom, listing

from .. import errors, ports, rendering, signals
from ..enums import NextHearingState, OrderStatus, TaskKey
from ..models import OrderRoznama
from . import common, items, triggering


def _validate_held_date(order):
    """Refuse a held date that could no longer be confirmed (``SND-03``, #6.7, #8.1)."""
    if not order.next_hearing_held:
        return
    for problem in listing.validate(order_id=order.pk):
        raise BusinessError(problem.error, problem.message)


def send_for_signing(order_id, *, actor):
    """Send the draft for signing (#7.1, ``SND-02``-``SND-08``).

    The text must not be empty, the next hearing must be settled and, in a
    hearing, attendance complete. Opens *Sign order*, and *Fill order data*
    unless the data is already complete. The order data need not be filled
    (``SND-04``).
    """
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.require_action(order, "send_for_signing")
        if rendering.is_blank(order.text):
            raise BusinessError(errors.ORDER_TEXT_EMPTY, field="text")
        if order.next_hearing_state == NextHearingState.UNSET:
            raise BusinessError(errors.NEXT_HEARING_NOT_SETTLED)
        _validate_held_date(order)
        if order.hearing_id and not courtroom.attendance_complete(order.hearing_id):
            raise BusinessError(errors.ATTENDANCE_INCOMPLETE)
        if order.data_complete and order.sent_for_signing_at is not None:
            # A re-send after a move back resets completion, keeping the values (SND-08).
            order.data_complete = False
            order.data_completed_by = None
            order.data_completed_at = None
            order.data_version += 1
        order.status = OrderStatus.SENT_FOR_SIGNING
        order.sent_for_signing_by = actor
        order.sent_for_signing_at = timezone.now()
        common.save_order(order, actor, "sent for signing")
        ports.complete_task(order.pk, TaskKey.DRAFT_ORDER)
        ports.open_task(
            order.pk,
            TaskKey.SIGN_ORDER,
            title=f"Sign order — {order.title}",
            role="ORDER_SIGNER",
            court_id=order.court_id,
        )
        if not order.data_complete:
            ports.open_task(
                order.pk,
                TaskKey.FILL_ORDER_DATA,
                title=f"Fill order data — {order.title}",
                role="ORDER_DATA_FILLER",
                court_id=order.court_id,
            )
        return order


def move_to_draft(order_id, *, actor):
    """Move an order sent for signing back to draft (#7.2, ``SND-05``).

    Clears the prepared signing, so a signature begun on the old text can never
    be recorded. Refused after signing (``E14016``).
    """
    with transaction.atomic():
        order = common.lock_order(order_id)
        if order.status in (OrderStatus.SIGNED, OrderStatus.TRIGGERED):
            raise BusinessError(errors.ORDER_ALREADY_SIGNED)
        common.require_action(order, "move_to_draft")
        order.status = OrderStatus.DRAFT
        order.signing_file_id = ""
        common.save_order(order, actor, "moved back to draft")
        ports.expire_task(order.pk, TaskKey.SIGN_ORDER)
        ports.expire_task(order.pk, TaskKey.FILL_ORDER_DATA)
        # A closed task does not reopen: this is a new one (``SND-08``).
        ports.open_task(
            order.pk,
            TaskKey.DRAFT_ORDER,
            title=f"Draft order — {order.title}",
            role="ORDER_DRAFTER",
            court_id=order.court_id,
        )
        return order


def mark_complete(order_id, *, actor):
    """Mark the order data complete; a signed order is triggered by it (#6.7, ``CMP-01``).

    Every mandatory field must be answered and each handler's completeness
    check clean (``E14012`` lists them). A signed order holding a date must
    still be able to confirm it.
    """
    with transaction.atomic():
        order = common.lock_order(order_id)
        if order.data_complete and order.status != OrderStatus.TRIGGERED:
            return order
        common.require_action(order, "mark_complete")
        if problems := items.completion_problems(order):
            raise common.ProblemsError(errors.MANDATORY_FIELDS_MISSING, problems)
        if order.is_signed:
            _validate_held_date(order)
        order.data_complete = True
        order.data_completed_by = actor
        order.data_completed_at = timezone.now()
        order.data_version += 1
        common.save_order(order, actor, "order data complete")
        ports.complete_task(order.pk, TaskKey.FILL_ORDER_DATA)
        if order.status == OrderStatus.SIGNED:
            trigger(order, actor)
        return order


def reopen(order_id, *, actor):
    """Reopen complete order data, until the order is signed (#6.7, ``CMP-05``).

    Refused after signing (``E14016``). While the order is sent for signing a new
    *Fill order data* task opens.
    """
    with transaction.atomic():
        order = common.lock_order(order_id)
        if order.is_signed:
            raise BusinessError(errors.ORDER_ALREADY_SIGNED)
        common.require_action(order, "reopen")
        order.data_complete = False
        order.data_completed_by = None
        order.data_completed_at = None
        order.data_version += 1
        common.save_order(order, actor, "order data reopened")
        if order.status == OrderStatus.SENT_FOR_SIGNING:
            ports.open_task(
                order.pk,
                TaskKey.FILL_ORDER_DATA,
                title=f"Fill order data — {order.title}",
                role="ORDER_DATA_FILLER",
                court_id=order.court_id,
            )
        return order


def trigger(order, actor=None):
    """Trigger the signed order whose data is complete (#9.1). Call with the order lock held.

    Writes the workflow runs in this transaction; they are executed after commit
    by ``run_order_workflows``. Nothing about the order changes after this
    but its diary entry (#6.6).
    """
    order.status = OrderStatus.TRIGGERED
    order.triggered_at = timezone.now()
    common.save_order(order, actor, "triggered")
    ports.expire_task(order.pk, TaskKey.DRAFT_ORDER)
    if order.hearing_id:
        try:
            courtroom.lock_attendance(order.hearing_id, actor)
        except HearingError as exc:
            raise common.hearing_error(exc) from exc
    triggering.write_runs(order)
    if order.order_type.signs_diary_entry:
        OrderRoznama.objects.get_or_create(order=order, defaults={"created_by": actor})
        ports.open_task(
            order.pk,
            TaskKey.SIGN_ROZNAMA,
            title=f"Sign Roznama — {order.title}",
            role="ORDER_SIGNER",
            court_id=order.court_id,
        )
    common.send_on_commit(signals.order_triggered, order)
    triggering.enqueue_on_commit(order.pk)
