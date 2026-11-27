"""Bulk actions of Pending orders and the cause list (#10.3-#10.5).

Each order is its own transaction: a failure on one is reported for that order
and never rolls back the others. Nothing here marks an order's data complete or
sends one for signing.
"""

from django.db import transaction
from rest_framework.exceptions import APIException

from apps.api.errors import BusinessError
from apps.hearings import selectors as hearing_selectors

from .. import conf, errors, permissions, rendering
from ..enums import EnteredFrom, ItemSource, NextHearingState, OrderStatus
from ..models import Order
from . import drafting, items, next_hearing


def _too_large(count):
    if count > conf.bulk_max_orders():
        raise BusinessError(
            errors.BULK_TOO_LARGE, f"At most {conf.bulk_max_orders()} orders per bulk action."
        )


def _skip(order_id, exc):
    error = getattr(exc, "error", None)
    detail = _first_detail(exc)
    return {
        "order_id": order_id,
        "code": error.code if error else getattr(detail, "code", None) or "ERROR",
        # The first message itself, never the repr of a field-keyed detail.
        "message": str(detail),
    }


def _first_detail(exc):
    """The first message of a DRF exception's ``detail``, however deeply it is nested."""
    detail = getattr(exc, "detail", exc)
    while isinstance(detail, dict | list) and detail:
        detail = next(iter(detail.values())) if isinstance(detail, dict) else detail[0]
    return detail


def bulk_items(*, actor, order_ids, item_specs):
    """Add the same items to several hearing orders of one courtroom (#10.3, ``ITM-10``).

    Defaults are worked out against each order's own case. Fields that need input
    are left for each order; nothing is marked complete.
    """
    order_ids = list(dict.fromkeys(order_ids))
    _too_large(len(order_ids))
    found = Order.objects.filter(pk__in=order_ids)
    # An order in a courtroom the caller is not staff of is not found, as on every
    # other endpoint: its court is never checked, so nothing reveals that it exists (#11.4).
    staff_of = {
        court_id
        for court_id in {o.court_id for o in found}
        if permissions.is_staff(actor, court_id)
    }
    orders = {o.pk: o for o in found if o.court_id in staff_of}
    courts = {o.court_id for o in orders.values()}
    if len(courts) > 1:
        raise BusinessError(errors.BULK_ACROSS_COURTROOMS, field="order_ids")
    if courts:
        permissions.require_role(actor, next(iter(courts)), "bulk_items")
    done, skipped = [], []
    for order_id in order_ids:
        order = orders.get(order_id)
        if order is None:
            skipped.append({"order_id": order_id, "code": "E00105", "message": "Order not found."})
            continue
        if order.hearing_id is None:
            skipped.append(
                {"order_id": order_id, "code": "E14001", "message": "Not an order of a hearing."}
            )
            continue
        try:
            with transaction.atomic():
                for spec in item_specs:
                    items.add(
                        order_id,
                        spec["item_type"],
                        target_id=spec.get("target_id"),
                        values=spec.get("values"),
                        source=ItemSource.BULK,
                        actor=actor,
                    )
            done.append(order_id)
        except APIException as exc:
            skipped.append(_skip(order_id, exc))
    return {"done": done, "skipped": skipped}


def _listings(court_id, hearing_ids):
    hearings = hearing_selectors.get_hearings(hearing_ids)
    return {
        hearing_id: hearing
        for hearing_id, hearing in hearings.items()
        if hearing.court_id == court_id
    }


def bulk_text(*, actor, court_id, hearing_ids, text):
    """Append ``text`` to each listing's draft, creating it for a started hearing (#10.4, ``CLS-12``).

    A listing whose order is sent for signing or signed, or whose hearing has not
    started, is skipped and named. Nothing is sent for signing.
    """
    hearing_ids = list(dict.fromkeys(hearing_ids))
    _too_large(len(hearing_ids))
    permissions.require_role(actor, court_id, "bulk_text")
    # The same text goes to every listing: refuse it once (``E14027``), not once per listing.
    rendering.sanitize_html(text)
    listings = _listings(court_id, hearing_ids)
    done, skipped = [], []
    for hearing_id in hearing_ids:
        hearing = listings.get(hearing_id)
        if hearing is None:
            skipped.append({"hearing_id": hearing_id, "code": "E00105", "message": "Not found."})
            continue
        try:
            if hearing.started_at is None:
                raise BusinessError(errors.HEARING_NOT_STARTED)
            # One transaction per hearing: a failed append drops the draft it just created.
            with transaction.atomic():
                order = drafting.live_order_for_hearing(hearing_id)
                if order is None:
                    order, _ = drafting.create_in_hearing(hearing_id=hearing_id, actor=actor)
                if order.status != OrderStatus.DRAFT:
                    raise BusinessError(
                        errors.INVALID_ORDER_ACTION, "The order is already sent for signing."
                    )
                drafting.append_text(order.pk, text, actor=actor)
            done.append(hearing_id)
        except APIException as exc:
            skipped.append({**_skip(order_id=None, exc=exc), "hearing_id": hearing_id})
    return {"done": done, "skipped": skipped}


def bulk_next_hearing(*, actor, court_id, hearing_ids, state, date=None, purpose=None):
    """Set the next hearing of each listing's draft from the cause list (#10.5, ``CLS-10``).

    The same service as the order's own endpoint, so both edit the one value.
    ``purpose=None`` keeps each order's current purpose, or the hearing's own. A
    listing not yet started gets its draft created to hold the value (``PLC-05``).
    """
    hearing_ids = list(dict.fromkeys(hearing_ids))
    _too_large(len(hearing_ids))
    permissions.require_role(actor, court_id, "bulk_next_hearing")
    listings = _listings(court_id, hearing_ids)
    done, skipped, warnings = [], [], []
    for hearing_id in hearing_ids:
        hearing = listings.get(hearing_id)
        if hearing is None:
            skipped.append({"hearing_id": hearing_id, "code": "E00105", "message": "Not found."})
            continue
        try:
            # One transaction per hearing: a rejected edit drops the draft it just created.
            with transaction.atomic():
                order, _ = drafting.create_in_hearing(
                    hearing_id=hearing_id, actor=actor, require_started=False
                )
                if order.status != OrderStatus.DRAFT:
                    raise BusinessError(
                        errors.INVALID_ORDER_ACTION, "The order is already sent for signing."
                    )
                chosen = purpose or order.next_hearing_purpose or hearing.purpose_code
                # The stored purpose was read before the lock: refuse if the order moved on since.
                keeps_current = not purpose and state == NextHearingState.LISTED
                _, found = next_hearing.set_next_hearing(
                    order.pk,
                    state=state,
                    date=date,
                    purpose=chosen if state == NextHearingState.LISTED else None,
                    actor=actor,
                    entered_from=EnteredFrom.CAUSE_LIST,
                    data_version=order.data_version if keeps_current else None,
                )
            done.append(hearing_id)
            warnings += [
                {"hearing_id": hearing_id, "code": w.code, "message": w.message} for w in found
            ]
        except APIException as exc:
            skipped.append({**_skip(order_id=None, exc=exc), "hearing_id": hearing_id})
    return {"done": done, "skipped": skipped, "warnings": warnings}


def set_for_hearing(*, actor, hearing_id, state, date=None, purpose=None, data_version=None):
    """The cause list's *Next hearing* column for one started listing (#10.5, ``PLC-05``).

    Writes that hearing's order; refused before the hearing starts (``E14004``).
    """
    with transaction.atomic():
        order, _ = drafting.create_in_hearing(hearing_id=hearing_id, actor=actor)
        return next_hearing.set_next_hearing(
            order.pk,
            state=state,
            date=date,
            purpose=purpose,
            actor=actor,
            entered_from=EnteredFrom.CAUSE_LIST,
            data_version=data_version,
        )
