"""The diary entry and the Gujarat Roznama's text (#6.6).

An order's diary entry is the order text by default and carries no order data
(``PUB-04``, ``DEN-04``). It is composed on read, never stored, while it is the
same as the text, and never shortened (``ADY-04``).
"""

import html

from django.db import transaction

from apps.api.errors import BusinessError

from .. import errors, rendering, signals
from ..enums import OrderStatus, RoznamaStatus
from . import common


def next_purpose_label(order):
    """The label of the order's next-hearing purpose, or empty."""
    if not order.next_hearing_purpose:
        return ""
    from apps.hearings.models import HearingPurpose

    row = HearingPurpose.objects.filter(code=order.next_hearing_purpose).first()
    return row.label if row else order.next_hearing_purpose


def same_as_text(order):
    """Whether the entry is the order text: chosen, or forced by a type with no separate entry."""
    return order.diary_same_as_text or not order.order_type.separate_diary_entry


def composed_entry(order, purpose_label=None):
    """Return the diary entry as HTML: the order text with attendance and next hearing lines.

    A separate entry is returned as written. Otherwise the entry is composed on
    read, in full (``PUB-04``, ``ADY-04``), with the attendance the order prints.
    ``purpose_label`` is the next hearing's, when the caller has read it already.
    """
    if not same_as_text(order):
        return order.diary_text
    parts = [f"<p>{html.escape(line)}</p>" for line in rendering.order_attendance(order)]
    parts.append(order.text)
    if purpose_label is None:
        purpose_label = next_purpose_label(order)
    if closing := rendering.next_hearing_line(order, purpose_label):
        parts.append(f"<p>{html.escape(closing)}</p>")
    return "".join(parts)


entry_for = composed_entry


def _can_edit_after_triggering(order, roznama):
    return (
        order.order_type.signs_diary_entry
        and roznama is not None
        and roznama.status == RoznamaStatus.AWAITING_SIGNATURE
    )


def set_entry(order_id, *, same_as_text, text="", actor, data_version=None):
    """Set the diary entry (#6.6); an order data filler until triggered.

    A type with no separate entry refuses ``same_as_text = false``
    (``E14026``). After triggering, only a Gujarat Roznama awaiting its signature
    may be edited (by a filler or a signer); an edit clears a signing begun on the
    old text. In Kerala the A-Diary edits (``set_entry_text``); in Punjab & Haryana
    the Summary is fixed (``E14014``). The entry is order data: ``data_version``
    is checked (``E14002``) and bumped.
    """
    with transaction.atomic():
        order = common.lock_order(order_id)
        roznama = common.roznama_of(order)
        if order.status == OrderStatus.TRIGGERED:
            if not _can_edit_after_triggering(order, roznama):
                raise BusinessError(errors.DIARY_ENTRY_LOCKED)
        elif order.status not in (
            OrderStatus.DRAFT,
            OrderStatus.SENT_FOR_SIGNING,
            OrderStatus.SIGNED,
        ):
            common.require_action(order, "edit_diary_entry")
        if not same_as_text and not order.order_type.separate_diary_entry:
            raise BusinessError(errors.DIARY_ENTRY_IS_ORDER_TEXT)
        common.check_version(order, "data", data_version)
        clean = common.clean_text(text)
        if not same_as_text and rendering.is_blank(clean):
            raise errors.ITEM_VALUES_INVALID.validation_error(
                {"text": ["Write the diary entry, or use the order text."]}
            )
        order.diary_same_as_text = same_as_text
        if not same_as_text:
            order.diary_text = clean
        order.data_version += 1
        common.save_order(order, actor, "diary entry changed")
        if roznama is not None and roznama.signing_file_id:
            roznama.signing_file_id = ""
            roznama.save(update_fields=["signing_file_id", "updated_at"])
        if order.status == OrderStatus.TRIGGERED:
            common.send_on_commit(signals.diary_entry_changed, order)
        return order


def set_entry_text(order_id, text, actor):
    """The one function the A-Diary calls when its editor changes an entry (``ADY-09``).

    Stores the text and turns ``diary_same_as_text`` off when it now differs from the
    order's composed entry. The order text never changes. The A-Diary module checks
    its own role and the signed-day rule.
    """
    with transaction.atomic():
        order = common.lock_order(order_id)
        if order.status != OrderStatus.TRIGGERED or not order.order_type.diary_entry_in_a_diary:
            raise BusinessError(errors.DIARY_ENTRY_LOCKED)
        clean = common.clean_text(text)
        if clean == composed_entry(order):
            return order
        order.diary_same_as_text = False
        order.diary_text = clean
        common.save_order(order, actor, "diary entry changed in the A-Diary")
        common.send_on_commit(signals.diary_entry_changed, order)
        return order


__all__ = [
    "composed_entry",
    "entry_for",
    "next_purpose_label",
    "same_as_text",
    "set_entry",
    "set_entry_text",
]
