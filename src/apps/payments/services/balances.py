"""The only code that writes balances and statuses (spec 0017 #1, #4).

``paid_amount``, ``due_amount`` and ``status`` on demands and items change here
and nowhere else. Callers hold the row locks; these helpers only compute and
save.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from ..enums import DemandItemStatus, DemandStatus
from ..models import ZERO, Demand, DemandItem

CENT = Decimal("0.01")


def quantize(value) -> Decimal:
    """Round a money value once, half up, to two places (spec 0017 #16)."""

    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def credit_item(item: DemandItem, amount: Decimal, *, actor=None) -> DemandItem:
    """Mark ``item`` paid in full by ``amount``."""

    item.paid_amount = amount
    item.due_amount = quantize(item.amount - amount)
    item.status = DemandItemStatus.PAID
    item.updated_by = actor or item.updated_by
    item.save(update_fields=["paid_amount", "due_amount", "status", "updated_by", "updated_at"])
    return item


def cancel_item(item: DemandItem, *, reason: str = "", actor=None) -> DemandItem:
    """Cancel an unpaid item. Nothing is due on a cancelled item."""

    item.status = DemandItemStatus.CANCELLED
    item.due_amount = ZERO
    item.cancelled_at = timezone.now()
    item.cancellation_reason = reason[:255]
    item.updated_by = actor or item.updated_by
    item.save(
        update_fields=[
            "status",
            "due_amount",
            "cancelled_at",
            "cancellation_reason",
            "updated_by",
            "updated_at",
        ]
    )
    return item


def recompute_demand(demand: Demand, *, actor=None) -> Demand:
    """Derive ``demand``'s totals and status from its items (spec 0017 #4)."""

    items = list(DemandItem.objects.filter(demand=demand))
    live = [item for item in items if item.status != DemandItemStatus.CANCELLED]

    total = sum((item.amount for item in live), ZERO)
    paid = sum((item.paid_amount for item in live), ZERO)
    demand.total_amount = quantize(total)
    demand.paid_amount = quantize(paid)
    demand.due_amount = quantize(total - paid)

    if not live:
        demand.status = DemandStatus.CANCELLED
        demand.cancelled_at = demand.cancelled_at or timezone.now()
    elif all(item.status == DemandItemStatus.PAID for item in live):
        demand.status = DemandStatus.PAID
    elif any(item.status == DemandItemStatus.PAID for item in live):
        demand.status = DemandStatus.PARTIALLY_PAID
    else:
        demand.status = DemandStatus.RAISED

    demand.updated_by = actor or demand.updated_by
    demand.save(
        update_fields=[
            "total_amount",
            "paid_amount",
            "due_amount",
            "status",
            "cancelled_at",
            "updated_by",
            "updated_at",
        ]
    )
    return demand
