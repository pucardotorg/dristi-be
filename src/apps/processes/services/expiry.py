"""Expiry of processes never sent (spec 0028 #8.6).

An unsent process expires at 00:00 IST on its hearing date (``EXP-01``).
Before signing the date follows the hearing; from signing it is fixed
(``EXP-01a``). A sent process never expires (``EXP-02``).
"""

import logging

from django.db import transaction
from django.utils import timezone

from .. import conf
from ..enums import EXPIRABLE_STATUSES, EventSource, ProcessStatus
from ..models import Process
from . import transitions

logger = logging.getLogger(__name__)


def expires_at(hearing_date):
    """The end of the day before the hearing; a process with no hearing never expires."""
    return conf.start_of(hearing_date) if hearing_date else None


def follow_hearing(*, hearing_id, hearing_date):
    """The hearing's processes take its new date; an unsigned, unsent one's expiry moves too.

    Every process keeps the date, which the lists sort on (#11.2); only the
    expiry stops following it at signing (``EXP-01a``).
    """
    new = expires_at(hearing_date)
    # One save each, so every change is kept in history.
    for process in Process.objects.filter(hearing_id=hearing_id):
        fields = []
        if process.hearing_date != hearing_date:
            process.hearing_date = hearing_date
            fields.append("hearing_date")
        moves_expiry = not process.expiry_fixed and process.status in EXPIRABLE_STATUSES
        if moves_expiry and process.expires_at != new:
            process.expires_at = new
            fields.append("expires_at")
        if fields:
            process.save(update_fields=[*fields, "updated_at"])


def expire_due():
    """Expire every unsent process past its expiry, up to ``expiry_batch_size``; return the count."""
    now = timezone.now()
    due = Process.objects.filter(status__in=EXPIRABLE_STATUSES, expires_at__lte=now)
    expired = 0
    for process_id in due.order_by("expires_at").values_list("pk", flat=True)[
        : conf.expiry_batch_size()
    ]:
        with transaction.atomic():
            process = transitions.locked(process_id)
            if process.status in EXPIRABLE_STATUSES and process.expires_at <= now:
                transitions.move(process, ProcessStatus.EXPIRED, source=EventSource.SWEEP)
                expired += 1
    if expired:
        logger.info("event=PROCESSES_EXPIRED count=%s", expired)
    return expired
