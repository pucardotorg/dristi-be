"""Expiry of hearing-linked applications (spec 0033 #13, ``ALC-30``).

Only a submitted Advance / Prepone or Postpone, still ``PENDING_REVIEW`` or
``PENDING_DECISION``, expires: when its hearing ends or is abandoned, is moved,
or is cancelled. An application targeted by a live order's *Application action*
item is left alone, so a decision awaiting signature, or the move made by the
order accepting it, never expires it; the nightly sweep looks again later.
"""

import logging

from django.db import transaction

from apps.hearings import selectors as hearings
from apps.hearings.enums import HearingStatus

from .. import conf, ports
from ..enums import OPEN_STATUSES, ApplicationStatus, ExpiryReason
from ..models import Application
from ..types import registry
from . import common, notifications
from .calendar import today
from .common import Action

logger = logging.getLogger(__name__)

S = ApplicationStatus
LIVE_HEARING_STATUSES = (
    HearingStatus.SCHEDULED,
    HearingStatus.IN_PROGRESS,
    HearingStatus.PASSED_OVER,
)


def expiring_type_codes():
    return [code for code in registry.codes() if registry.require(code).expires_with_hearing]


def hearing_gone(application):
    """Why the application's hearing no longer stands, or None (#13)."""
    hearing = hearings.get_hearing(application.hearing_id) if application.hearing_id else None
    if hearing is None:
        return ExpiryReason.HEARING_CANCELLED
    if hearing.status == HearingStatus.CANCELLED:
        return ExpiryReason.HEARING_CANCELLED
    if hearing.status in (HearingStatus.COMPLETED, HearingStatus.ABANDONED):
        return ExpiryReason.HEARING_PASSED
    if hearing.hearing_date < today():
        return ExpiryReason.HEARING_PASSED
    return None


def expire(application, reason, *, hearing_id=None):
    """Expire the locked, open application (#13 step 2)."""
    common.transition(
        application,
        Action.EXPIRE,
        None,
        to_status=S.EXPIRED,
        metadata={"reason": str(reason), "hearing_id": str(hearing_id or application.hearing_id)},
    )
    for task in ("review_application", "decide_application"):
        ports.tasks.expire(task, application, reason="NO_LONGER_RELEVANT")
    ports.tasks.expire("file_objection", application, reason="NO_LONGER_RELEVANT")
    from .objections import close_open_objection

    close_open_objection(application)
    notifications.expired(application)
    logger.info("event=APPLICATION_EXPIRED application_id=%s reason=%s", application.pk, reason)


def expire_for_hearing(hearing_id, reason):
    """Expire the open hearing-linked applications of ``hearing_id`` (a hearing signal); count."""
    candidates = list(
        Application.objects.filter(
            hearing_id=hearing_id,
            status__in=OPEN_STATUSES,
            application_type__code__in=expiring_type_codes(),
        ).values_list("pk", flat=True)
    )
    return _expire_each(candidates, reason)


def _expire_each(application_ids, reason=None):
    live = ports.live_items_targeting(application_ids)
    count = 0
    for application_id in application_ids:
        if application_id in live:
            continue
        with transaction.atomic():
            application = common.lock(application_id)
            if application.status not in OPEN_STATUSES:
                continue
            why = reason or hearing_gone(application)
            if why is None:
                continue
            expire(application, why)
            count += 1
    return count


def sweep():
    """The 00:05 IST sweep (#16.6): anything a missed signal left, in bounded batches."""
    candidates = Application.objects.filter(
        status__in=OPEN_STATUSES, application_type__code__in=expiring_type_codes()
    ).order_by("submitted_at")
    batch = list(candidates.values_list("pk", flat=True)[: conf.expiry_batch_size()])
    count = _expire_each(batch)
    if count:
        logger.info("event=APPLICATION_EXPIRED count=%s", count)
    return count
