"""Telling parties and advocates about an order (spec 0039 #12.2).

Queued on commit, so a rolled-back change tells no one. The next hearing is
announced by ``apps.hearings`` when it is confirmed, never from here
(``PUB-07``). A messaging failure never fails the order.
"""

import logging
from functools import partial

from django.db import transaction

from apps.cases.selectors import get_case_contacts, get_case_summaries
from apps.messaging.services import MessageTemplateNotFound
from apps.messaging.tasks import enqueue_email, enqueue_sms

logger = logging.getLogger(__name__)

ORDER_SIGNED = "ORDER_SIGNED"


def notify_signed_on_commit(order):
    """Queue *order signed* to every party and advocate of the case once the signature commits."""
    transaction.on_commit(
        partial(_notify, order.case_id, ORDER_SIGNED, order.pk, order.title, order.order_date)
    )


def _notify(case_id, message_key, order_id, title, order_date):
    try:
        summary = get_case_summaries([case_id]).get(case_id)
        context = {
            "case_number": summary.display_number if summary else "",
            "case_title": summary.title if summary else "",
            "order_title": title,
            "order_date": order_date.isoformat() if order_date else "",
        }
        contacts = get_case_contacts(case_id)
    except Exception:
        logger.exception("event=ORDER_NOTIFY_FAILED case=%s key=%s", case_id, message_key)
        return
    sent = 0
    for contact in contacts:
        for enqueue, address, recipient in (
            (enqueue_sms, contact.phone, {"phone_number": contact.phone}),
            (enqueue_email, contact.email, {"email": contact.email}),
        ):
            if not address:
                continue
            try:
                enqueue(message_key, recipient, context, correlation_id=f"order:{order_id}")
                sent += 1
            except MessageTemplateNotFound:
                logger.debug("event=ORDER_NOTIFY_NO_TEMPLATE key=%s", message_key)
            except Exception:
                logger.exception("event=ORDER_NOTIFY_FAILED case=%s key=%s", case_id, message_key)
    if not sent:
        logger.warning("event=ORDER_NOTIFY_NO_RECIPIENTS case=%s key=%s", case_id, message_key)
