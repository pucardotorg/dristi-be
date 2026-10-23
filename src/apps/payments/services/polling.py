"""Resolving payments whose callback never came (spec 0017 #9.7).

Tab closed, bank slow, provider down: the poller asks the payment's own
provider, with a doubling interval, and applies the answer through
``PaymentService.apply_provider_status``. It never fails a payment on age:
past the provider's ``pending_horizon`` it flags it for an operator.
"""

import logging
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from .. import conf
from ..enums import PaymentStatus
from ..models import Payment
from ..providers import registry
from ..providers.base import ProviderError, ProviderNotConfigured
from .payments import PaymentService

logger = logging.getLogger(__name__)

# 2 ** 30 intervals is far past any cap; stops the exponent growing unbounded.
MAX_BACKOFF_EXPONENT = 30


def next_poll_at(payment: Payment):
    """When ``payment`` is next due a status check."""

    exponent = min(payment.poll_count, MAX_BACKOFF_EXPONENT)
    interval = min(conf.poll_interval_seconds() * 2**exponent, conf.poll_max_interval_seconds())
    return (payment.last_polled_at or payment.initiated_at) + timedelta(seconds=interval)


def due_payments(now=None) -> list[Payment]:
    """One pending payment per provider transaction whose next poll is due."""

    now = now or timezone.now()
    limit = conf.poll_batch_size()
    candidates = (
        Payment.objects.filter(status=PaymentStatus.PENDING)
        .exclude(provider="")
        .exclude(provider_payment_id="")
        .order_by(F("last_polled_at").asc(nulls_first=True), "initiated_at", "pk")
    )
    seen = set()
    due = []
    for payment in candidates.iterator():
        key = (payment.provider, payment.provider_payment_id)
        if key in seen:
            continue
        seen.add(key)
        if next_poll_at(payment) <= now:
            due.append(payment)
            if len(due) >= limit:
                break
    return due


def poll_pending_payments(now=None) -> int:
    """Check every due payment once; return how many provider transactions were checked."""

    now = now or timezone.now()
    due = due_payments(now)
    for payment in due:
        try:
            poll_one(payment, now=now)
        except Exception:  # noqa: BLE001 - one payment must not stop the rest of the run
            logger.exception("Status poll of %s failed.", payment.payment_number)
    return len(due)


def poll_one(payment: Payment, *, now=None) -> None:
    """Fetch and apply the status of ``payment``'s provider transaction."""

    now = now or timezone.now()
    group = PaymentService.provider_group(payment)
    try:
        provider = registry.get(payment.provider)
    except ProviderNotConfigured:
        logger.error(
            "Payment %s is pending at provider %r, which is no longer registered.",
            payment.payment_number,
            payment.provider,
        )
        _touch(group, now)
        return

    try:
        status = provider.fetch_status(provider_payment_id=payment.provider_payment_id)
    except ProviderError as exc:
        # Retried on a later run, with backoff; never inside this one.
        logger.warning("Status poll of %s failed: %s", payment.payment_number, exc.code)
    except Exception:  # noqa: BLE001 - one bad provider reply must not stop the run
        logger.exception("Status poll of %s failed.", payment.payment_number)
    else:
        PaymentService.apply_provider_status(group, status)

    _touch(group, now)
    still_pending = [
        p
        for p in Payment.objects.filter(pk__in=[p.pk for p in group])
        if p.status == PaymentStatus.PENDING
    ]
    if (
        still_pending
        and now - min(p.initiated_at for p in still_pending) > provider.pending_horizon
    ):
        if not all(p.needs_reconciliation for p in still_pending):
            logger.error(
                "PAYMENT_STUCK: %s is still pending past provider %s's horizon.",
                payment.provider_payment_id,
                payment.provider,
            )
        PaymentService.flag_for_reconciliation(still_pending, "PAYMENT_STUCK")


def _touch(payments: list[Payment], now) -> None:
    """Record a poll attempt (bookkeeping only, so a plain UPDATE)."""

    Payment.objects.filter(pk__in=[p.pk for p in payments]).update(
        last_polled_at=now, poll_count=F("poll_count") + 1
    )
