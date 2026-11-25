"""What this module hears from payments and hearings (spec 0028 #6.3, #8.6)."""

from django.dispatch import receiver

from apps.hearings.signals import hearing_rescheduled
from apps.payments.enums import ChargeType, DemandItemStatus
from apps.payments.signals import payment_completed

from .services import expiry, steps


@receiver(payment_completed, dispatch_uid="processes.fee_paid")
def on_payment_completed(*, items, **kwargs):
    """Mark the processes whose court fee this payment covered (``FEE-08``)."""
    paid = [
        item.pk
        for item in items
        if item.charge_type == ChargeType.PROCESS_COURT_FEE and item.status == DemandItemStatus.PAID
    ]
    if paid:
        steps.fee_items_paid(paid)


@receiver(hearing_rescheduled, dispatch_uid="processes.follow_hearing")
def on_hearing_rescheduled(*, hearing_id, to_date, **kwargs):
    """An unsigned process's expiry follows its hearing (``EXP-01a``)."""
    expiry.follow_hearing(hearing_id=hearing_id, hearing_date=to_date)
