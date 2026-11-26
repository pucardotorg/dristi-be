"""Notifications (spec 0033 #16.2).

Queued on commit through ``apps.messaging``; a messaging failure never fails
the step. The copy is the master Notifications table's: this module supplies
the trigger, the recipients and the context. The other side is **not** told
about a submitted application until an order asks it to respond (``ALC-12``,
``ALC-17``). Court users are not messaged.
"""

import logging
from functools import partial

from django.db import transaction

from apps.cases.selectors import get_case_summaries
from apps.messaging.services import MessageTemplateNotFound
from apps.messaging.tasks import enqueue_sms
from apps.users.models import User

from .. import ports
from ..enums import Side

logger = logging.getLogger(__name__)

PENDING_SIGNATURE = "APPLICATION_PENDING_SIGNATURE"
SUBMITTED = "APPLICATION_SUBMITTED"
RESPONSE_REQUESTED = "APPLICATION_RESPONSE_REQUESTED"
DECIDED = "APPLICATION_DECIDED"
DISMISSED = "APPLICATION_DISMISSED"
EXPIRED = "APPLICATION_EXPIRED"
DECISION_DATE_MOVED = "APPLICATION_DECISION_DATE_MOVED"
OBJECTION_FILED = "APPLICATION_OBJECTION_FILED"


def _context(application, **extra):
    summary = get_case_summaries([application.case_id]).get(application.case_id)
    return {
        "case_number": summary.display_number if summary else "",
        "application_type": application.application_type.label,
        "application_number": application.application_number or "",
        **{key: "" if value is None else str(value) for key, value in extra.items()},
    }


def _send(message_key, user_ids, context, application_id):
    phones = User.objects.filter(pk__in=list(user_ids), is_active=True).values_list(
        "mobile_number", flat=True
    )
    for phone in {p for p in phones if p}:
        try:
            enqueue_sms(
                message_key,
                {"phone_number": phone},
                context,
                correlation_id=f"application:{application_id}",
            )
        except MessageTemplateNotFound:
            logger.debug("event=APPLICATION_NOTIFY_NO_TEMPLATE key=%s", message_key)
            return
        except Exception:
            logger.exception(
                "event=APPLICATION_NOTIFY_FAILED application_id=%s key=%s",
                application_id,
                message_key,
            )


def notify_on_commit(message_key, application, user_ids, **extra):
    """Queue ``message_key`` to ``user_ids`` once the step commits."""
    context = _context(application, **extra)
    transaction.on_commit(partial(_send, message_key, set(user_ids), context, application.pk))


def pending_signature(application):
    notify_on_commit(PENDING_SIGNATURE, application, [application.raised_by_id])


def submitted(application):
    """The filer's side only, never the other side (``ALC-17``)."""
    notify_on_commit(
        SUBMITTED, application, ports.side_user_ids(application.case_id, application.side)
    )


def response_requested(application):
    """The first the other side hears of the application (``ALC-12``)."""
    other = Side(application.side).opposite
    notify_on_commit(
        RESPONSE_REQUESTED,
        application,
        ports.side_user_ids(application.case_id, other),
        respond_by=application.respond_by,
        decision_date=application.decision_date,
    )


def decided(application):
    notify_on_commit(
        DECIDED, application, ports.case_user_ids(application.case_id), outcome=application.outcome
    )


def dismissed(application):
    notify_on_commit(
        DISMISSED, application, ports.side_user_ids(application.case_id, application.side)
    )


def expired(application):
    notify_on_commit(
        EXPIRED, application, ports.side_user_ids(application.case_id, application.side)
    )


def decision_date_moved(application):
    users = ports.side_user_ids(application.case_id, application.side)
    if application.objections_invited:
        users |= ports.side_user_ids(application.case_id, Side(application.side).opposite)
    notify_on_commit(
        DECISION_DATE_MOVED, application, users, decision_date=application.decision_date
    )


def objection_filed(objection):
    target = objection.objection_to
    notify_on_commit(OBJECTION_FILED, target, ports.side_user_ids(target.case_id, target.side))
