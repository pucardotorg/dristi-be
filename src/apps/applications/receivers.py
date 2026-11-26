"""Signal receivers (spec 0033 #1, #6.8, #13).

Payments and hearings announce; this module listens. None of them import it.
"""

import logging

from django.dispatch import receiver

from apps.hearings import signals as hearing_signals
from apps.payments.signals import payment_completed

from .enums import ExpiryReason
from .services import expiry, submission

logger = logging.getLogger(__name__)


@receiver(payment_completed, dispatch_uid="applications_payment_completed")
def on_payment_completed(sender, **kwargs):
    submission.on_payment_completed(sender, **kwargs)


@receiver(hearing_signals.hearing_ended, dispatch_uid="applications_hearing_ended")
def on_hearing_ended(sender, hearing_id, **kwargs):
    expiry.expire_for_hearing(hearing_id, ExpiryReason.HEARING_PASSED)


@receiver(hearing_signals.hearing_rescheduled, dispatch_uid="applications_hearing_rescheduled")
def on_hearing_rescheduled(sender, hearing_id, from_date=None, to_date=None, **kwargs):
    if from_date is not None and from_date == to_date:
        return  # a purpose-only move: the hearing still stands on its date
    expiry.expire_for_hearing(hearing_id, ExpiryReason.HEARING_MOVED)


@receiver(hearing_signals.hearing_cancelled, dispatch_uid="applications_hearing_cancelled")
def on_hearing_cancelled(sender, hearing_id, **kwargs):
    expiry.expire_for_hearing(hearing_id, ExpiryReason.HEARING_CANCELLED)
