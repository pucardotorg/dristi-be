"""Background processing (spec 0017 #14).

There is no initiation actor: initiation runs in the request (#9.4). Actors
take identifiers only and are idempotent.
"""

from dramatiq import actor

from .enums import DemandStatus, PaymentStatus
from .models import DemandItem, Payment
from .services import polling
from .signals import payment_completed


@actor(max_retries=0)
def poll_pending_payments() -> int:
    """Resolve pending payments whose callback never came (periodic)."""

    return polling.poll_pending_payments()


@actor(max_retries=3)
def notify_payment_completed(payment_id: str) -> bool:
    """Publish a successful payment to the raising modules.

    Re-reads the payment and publishes only a ``SUCCESS``; never re-applies a
    balance. Returns whether anything was published.
    """

    payment = Payment.objects.select_related("demand").filter(pk=payment_id).first()
    if payment is None or payment.status != PaymentStatus.SUCCESS:
        return False

    items = list(DemandItem.objects.filter(payment_items__payment=payment).order_by("position"))
    payment_completed.send(
        sender=Payment,
        payment=payment,
        demand=payment.demand,
        items=items,
        demand_paid=payment.demand.status == DemandStatus.PAID,
    )
    return True
