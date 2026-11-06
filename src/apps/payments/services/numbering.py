"""Human-readable demand and payment numbers (spec 0017 #11).

``DMD-{YYYY}-{seq:06d}`` and ``PAY-{YYYY}-{seq:06d}``, monotonic per year (IST).
The counter row is bumped with an atomic ``UPDATE`` in the caller's
transaction, which holds its row lock until commit, so two concurrent
creations can never draw the same number; ``max(...) + 1`` is never used.
"""

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.api.meta import IST_TIMEZONE

from ..models import PaymentSequence

DEMAND_PREFIX = "DMD"
PAYMENT_PREFIX = "PAY"


def next_number(prefix: str) -> str:
    """Allocate the next number for ``prefix`` in the current year."""

    now = timezone.now()
    year = now.astimezone(IST_TIMEZONE).year
    rows = PaymentSequence.objects.filter(prefix=prefix, year=year)

    with transaction.atomic():
        if not rows.update(value=F("value") + 1, updated_at=now):
            try:
                with transaction.atomic():
                    PaymentSequence.objects.create(prefix=prefix, year=year, value=1)
            except IntegrityError:
                # Another transaction created this year's row first.
                rows.update(value=F("value") + 1, updated_at=now)
        value = rows.values_list("value", flat=True).get()

    return f"{prefix}-{year}-{value:06d}"
