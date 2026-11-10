"""Read-only queries (spec 0017 #1, #6.5, #13).

Every REST queryset starts here, already narrowed to what the caller may see
(``access.py``), so a record on someone else's case is a plain 404.
"""

from decimal import Decimal

from django.db.models import Prefetch, Sum

from . import access
from .enums import DemandItemStatus
from .models import ZERO, DemandItem, Payment, PaymentDemandItem
from .services.demands import case_pk


def demands_for(user):
    """Demands ``user`` may see, with items and payments prefetched."""

    return (
        access.visible_demands(user)
        .select_related("created_by", "updated_by")
        .prefetch_related(
            Prefetch("items", queryset=DemandItem.objects.order_by("position", "created_at")),
            "payments",
        )
        .order_by("-created_at")
    )


def payments_for(user):
    """Payments ``user`` may see, with their items prefetched."""

    return (
        access.visible_payments(user)
        .select_related("demand", "created_by", "updated_by")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=PaymentDemandItem.objects.select_related("demand_item").order_by(
                    "demand_item__position"
                ),
            )
        )
        .order_by("-created_at")
    )


def batch_payments(user, batch_id) -> list[Payment]:
    """The payments of one batch, if ``user`` may see every one of them."""

    visible = list(payments_for(user).filter(batch_id=batch_id).order_by("payment_number"))
    if not visible or Payment.objects.filter(batch_id=batch_id).count() != len(visible):
        return []
    return visible


def paid_total(*, case, charge_types) -> Decimal:
    """Sum of PAID items of ``charge_types`` across every demand on ``case``.

    In-process only: the raising module nets this off before raising a demand
    for the balance. ``case`` is a case instance or its id.
    """

    total = DemandItem.objects.filter(
        demand__case_id=case_pk(case),
        charge_type__in=list(charge_types),
        status=DemandItemStatus.PAID,
    ).aggregate(total=Sum("paid_amount"))["total"]
    return total or ZERO
