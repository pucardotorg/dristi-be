"""The next hearing: one value per order, written from the order or the cause list (#6.4).

Both entry points call ``set`` (``PLC-04``), so a change in one shows in the
other. The date is held in ``apps.hearings`` as a ``PROVISIONAL`` hearing from the
moment it is set (``NXT-10``) and announced only when the order is triggered
(``PUB-07``).

In a hearing the order holds the date itself. Outside one, the next hearing
starts as the case's listed hearing, read only (``ORD-08``); a different date or
purpose holds a move and adds a *Rescheduling of hearing date* item, or, where the
case has no listed hearing, a *Scheduling of hearing date* item. Returning to the
listed hearing releases the hold and removes the item. Those items are
``SYSTEM``-added: they follow from the next hearing and are never typed.
"""

from django.db import transaction
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.cases.selectors import get_listability
from apps.hearings import selectors as hearing_selectors
from apps.hearings.enums import ReleaseReason
from apps.hearings.exceptions import HearingError
from apps.hearings.services import calendar, listing

from .. import errors
from ..enums import EnteredFrom, ItemSource, NextHearingState
from ..models import OrderItemType
from . import common, items

SCHEDULING = "SCHEDULING_OF_HEARING_DATE"
RESCHEDULING = "RESCHEDULING_OF_HEARING_DATE"


def _system_date_items(order):
    return list(
        order.items.select_related("item_type").filter(
            item_type__code__in=(SCHEDULING, RESCHEDULING), added_by_source=ItemSource.SYSTEM
        )
    )


def _drop_system_items(order, actor):
    dropped = False
    for item in _system_date_items(order):
        items.remove_locked(order, item, actor=actor)
        dropped = True
    return dropped


def _set_system_item(order, code, values, actor):
    """Make the order's one system date item ``code`` with ``values``."""
    current = _system_date_items(order)
    for item in current:
        if item.item_type.code == code:
            item.values = values
            items._save_item(item, actor, "date item follows next hearing")
            return
    # A new date item is order data: reopen completed data first (``SND-06``). The caller's
    # transaction rolls this back with the hold if the item is refused.
    _reset_complete(order, actor)
    _drop_system_items(order, actor)
    item_type = OrderItemType.objects.get(code=code)
    items.add_locked(order, item_type, values=values, source=ItemSource.SYSTEM, actor=actor)


def _reset_complete(order, actor):
    """Order data changed under a complete order: it needs completing again (``SND-06``)."""
    if order.data_complete:
        order.data_complete = False
        order.data_completed_by = None
        order.data_completed_at = None


def default_from_listed(order, actor=None):
    """Start an order outside a hearing from the case's listed hearing, read only (``ORD-08``)."""
    if order.hearing_id:
        return
    listed = hearing_selectors.scheduled_hearing(order.case_id)
    if listed is None:
        return
    order.next_hearing_state = NextHearingState.LISTED
    order.next_hearing_date = listed.hearing_date
    order.next_hearing_purpose = listed.purpose_code
    order.next_hearing_entered_from = ""
    order.next_hearing_entered_at = None


def follow_listed(order):
    """Bring an order that shows the case's listed hearing up to date; return whether it changed.

    Outside a hearing, a next hearing the order does not hold is the listed hearing
    itself (``ORD-08``), which another order may since have moved or cancelled. It
    follows that hearing, and is unsettled once the case has none (``SND-03``).
    Bumps ``data_version`` on a change; the caller saves the order.
    """
    if (
        order.hearing_id
        or order.next_hearing_held
        or order.next_hearing_state != NextHearingState.LISTED
    ):
        return False
    listed = hearing_selectors.scheduled_hearing(order.case_id)
    if listed is None:
        _clear(order)
        order.next_hearing_state = NextHearingState.UNSET
    elif (listed.hearing_date, listed.purpose_code) != (
        order.next_hearing_date,
        order.next_hearing_purpose,
    ):
        order.next_hearing_date = listed.hearing_date
        order.next_hearing_purpose = listed.purpose_code
    else:
        return False
    order.data_version += 1
    return True


def _clear(order):
    order.next_hearing_date = None
    order.next_hearing_purpose = ""
    order.moves_hearing_id = None
    order.next_hearing_held = False


def set_next_hearing(
    order_id,
    *,
    state,
    date=None,
    purpose=None,
    actor=None,
    entered_from=EnteredFrom.ORDER,
    data_version=None,
):
    """Set the order's next hearing; returns ``(order, warnings)`` (#6.4).

    ``state`` is ``LISTED`` (a date and a purpose, together) or ``NOT_LISTED_AGAIN``.
    Raises the ``apps.hearings`` errors unchanged (``E10003``-``E10009``,
    ``E10014``); its soft warnings come back in ``warnings``.
    """
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.require_action(order, "set_next_hearing")
        common.check_version(order, "data", data_version)
        warnings = _apply(order, state, date, purpose, actor)
        order.next_hearing_entered_from = entered_from
        order.next_hearing_entered_by = actor if getattr(actor, "pk", None) else None
        order.next_hearing_entered_at = timezone.now()
        order.data_version += 1
        common.save_order(order, actor, "next hearing set")
    return order, warnings


def _apply(order, state, date, purpose, actor):
    if state not in (NextHearingState.LISTED, NextHearingState.NOT_LISTED_AGAIN):
        raise errors.ITEM_VALUES_INVALID.validation_error(
            {"state": ["Choose listed or not listed again."]}
        )
    if state == NextHearingState.NOT_LISTED_AGAIN:
        if date or purpose:
            raise errors.ITEM_VALUES_INVALID.validation_error(
                {"date": ["Leave the date and purpose empty when not listed again."]}
            )
        listing.release(order_id=order.pk, reason=ReleaseReason.DATE_REMOVED, actor=actor)
        if _drop_system_items(order, actor):
            _reset_complete(order, actor)
        _clear(order)
        order.next_hearing_state = NextHearingState.NOT_LISTED_AGAIN
        return []

    if not date or not purpose:
        missing = "date" if not date else "purpose"
        raise errors.ITEM_VALUES_INVALID.validation_error(
            {missing: ["A next hearing needs both a date and a purpose."]}
        )
    if order.hearing_id:
        return _hold_in_hearing(order, date, purpose, actor)
    return _hold_outside_hearing(order, date, purpose, actor)


def _hold(order, date, purpose, actor, **kwargs):
    try:
        return listing.hold(
            case_id=order.case_id,
            hearing_date=date,
            purpose_code=purpose,
            order_id=order.pk,
            actor=actor,
            **kwargs,
        )
    except HearingError as exc:
        raise common.hearing_error(exc) from exc


def _hold_in_hearing(order, date, purpose, actor):
    result = _hold(order, date, purpose, actor, previous_hearing_id=order.hearing_id)
    order.next_hearing_state = NextHearingState.LISTED
    order.next_hearing_date = date
    order.next_hearing_purpose = purpose
    order.next_hearing_held = True
    return result.warnings


def _hold_outside_hearing(order, date, purpose, actor):
    # Read the listed hearing under the court lock ``listing.hold`` takes, in this
    # transaction, so a hearing confirmed meanwhile cannot make the target stale.
    listability = get_listability(order.case_id)
    if listability.listable:
        calendar.lock_court(listability.court_id)
    listed = hearing_selectors.scheduled_hearing(order.case_id)
    if listed is not None and (listed.hearing_date, listed.purpose_code) == (date, purpose):
        # Back to the listed hearing: nothing to hold, nothing to move.
        listing.release(order_id=order.pk, reason=ReleaseReason.DATE_REMOVED, actor=actor)
        if _drop_system_items(order, actor):
            _reset_complete(order, actor)
        _clear(order)
        order.next_hearing_state = NextHearingState.LISTED
        order.next_hearing_date = date
        order.next_hearing_purpose = purpose
        return []

    moves = listed.id if listed is not None else None
    if order.next_hearing_held and order.moves_hearing_id != moves:
        # An existing hold cannot change what it moves: replace it in this transaction.
        listing.release(order_id=order.pk, reason=ReleaseReason.DATE_REMOVED, actor=actor)
    result = _hold(order, date, purpose, actor, moves_hearing_id=moves)
    order.next_hearing_state = NextHearingState.LISTED
    order.next_hearing_date = date
    order.next_hearing_purpose = purpose
    order.next_hearing_held = True
    order.moves_hearing_id = moves
    if listed is not None:
        _set_system_item(
            order,
            RESCHEDULING,
            {
                "new_hearing_date": date.isoformat(),
                "hearing_purpose": purpose,
                "original_hearing_date": listed.hearing_date.isoformat(),
            },
            actor,
        )
    else:
        _set_system_item(
            order, SCHEDULING, {"hearing_date": date.isoformat(), "hearing_purpose": purpose}, actor
        )
    _reset_complete(order, actor)
    return result.warnings


def release_on_discard(order, actor=None):
    """Release the held date of a discarded draft (#5.7, ``DFT-06``)."""
    listing.release(order_id=order.pk, reason=ReleaseReason.DRAFT_DISCARDED, actor=actor)
    order.next_hearing_held = False


def view(order, purpose_label=None):
    """The next hearing as the order screen shows it, with the purpose's label.

    ``purpose_label`` is the label when the caller has read it already.
    """
    purpose = None
    if order.next_hearing_purpose:
        if purpose_label is None:
            from apps.hearings.models import HearingPurpose

            row = HearingPurpose.objects.filter(code=order.next_hearing_purpose).first()
            purpose_label = row.label if row else order.next_hearing_purpose
        purpose = {"code": order.next_hearing_purpose, "label": purpose_label}
    return {
        "state": order.next_hearing_state,
        "date": order.next_hearing_date,
        "purpose": purpose,
        "entered_from": order.next_hearing_entered_from,
    }


__all__ = [
    "BusinessError",
    "default_from_listed",
    "follow_listed",
    "release_on_discard",
    "set_next_hearing",
    "view",
]
