"""Notifying parties and advocates of a hearing change (spec 0023 #11.1).

Queued on commit, so a rolled-back change notifies no one. Nothing is sent
for a provisional date, a change of one, or a release: the date was never
announced. A messaging failure never fails the hearing change.
"""

import logging
from functools import partial

from django.db import transaction

from apps.cases.selectors import get_case_contacts, get_case_summaries
from apps.messaging.services import MessageTemplateNotFound
from apps.messaging.tasks import enqueue_email, enqueue_sms

logger = logging.getLogger(__name__)

HEARING_SCHEDULED = "HEARING_SCHEDULED"
HEARING_RESCHEDULED = "HEARING_RESCHEDULED"
HEARING_CANCELLED = "HEARING_CANCELLED"


def notify_on_commit(case_id, message_key, context):
    """Queue ``message_key`` to every party and advocate of the case once the change commits."""
    transaction.on_commit(partial(_notify, case_id, message_key, context))


def case_context(case_id):
    """Return the case number and title every hearing message names."""
    summary = get_case_summaries([case_id]).get(case_id)
    return {
        "case_number": summary.display_number if summary else "",
        "case_title": summary.title if summary else "",
    }


def _notify(case_id, message_key, context):
    try:
        contacts = get_case_contacts(case_id)
    except Exception:
        logger.exception("event=HEARING_NOTIFY_FAILED case=%s key=%s", case_id, message_key)
        return
    context = {key: str(value) for key, value in context.items()}
    sent = 0
    for contact in contacts:
        for enqueue, address, recipient in (
            (enqueue_sms, contact.phone, {"phone_number": contact.phone}),
            (enqueue_email, contact.email, {"email": contact.email}),
        ):
            if not address:
                continue
            try:
                enqueue(message_key, recipient, context, correlation_id=f"hearing:{case_id}")
                sent += 1
            except MessageTemplateNotFound:
                logger.debug("event=HEARING_NOTIFY_NO_TEMPLATE key=%s", message_key)
            except Exception:
                logger.exception("event=HEARING_NOTIFY_FAILED case=%s key=%s", case_id, message_key)
    # Each message is logged by apps.messaging under correlation_id hearing:<case>;
    # only a change nobody could be told about needs a line of its own.
    if not sent:
        logger.warning("event=HEARING_NOTIFY_NO_RECIPIENTS case=%s key=%s", case_id, message_key)
