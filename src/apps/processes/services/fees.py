"""The court fee of new processes, drawn from the case's pool (spec 0028 #6).

Court fee paid on a case, at filing or in earlier rounds, is one pool
(``FEE-04``). New processes draw on it in creation order; whatever they do not
cover becomes one demand item per process, so each moves on its own when its
item is paid (``FEE-08``). Nothing is refunded (``FEE-07``).
"""

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.payments.enums import ChargeType, ReferenceType
from apps.payments.selectors import paid_on_items, paid_total
from apps.payments.services import DemandService

from .. import conf
from ..models import Process

ZERO = Decimal("0.00")


def pool(case_id) -> Decimal:
    """Process court fee paid on the case and not yet spent by its processes (#6.1).

    Spent is what each process drew from the pool, and whatever was paid on
    its own balance item: that money paid for that process.
    """
    processes = Process.objects.filter(case_id=case_id)
    drawn = processes.aggregate(total=Sum("fee_from_pool"))["total"] or ZERO
    own_items = processes.exclude(demand_item_id=None).values_list("demand_item_id", flat=True)
    paid = paid_total(case=case_id, charge_types=[ChargeType.PROCESS_COURT_FEE])
    return paid - drawn - paid_on_items(own_items)


def allocate(processes, *, case_id, order_id, actor=None):
    """Set the fee fields of unsaved ``processes``; raise a demand for what the pool leaves (#6.2).

    Call under the case's lock (``ProcessCaseLock``), so two rounds never draw
    the same money.
    """
    left = max(pool(case_id), ZERO)
    now = timezone.now()
    due = []
    for process in processes:
        process.court_fee = conf.court_fee(process.process_type.code)
        process.fee_from_pool = min(process.court_fee, left)
        left -= process.fee_from_pool
        process.fee_paid = process.fee_from_pool == process.court_fee
        process.fee_paid_at = now if process.fee_paid and process.court_fee else None
        if not process.fee_paid:
            due.append(process)
    if due:
        _raise_demand(due, case_id=case_id, order_id=order_id, actor=actor)


def _raise_demand(processes, *, case_id, order_id, actor):
    demand = DemandService.raise_demand(
        case=case_id,
        reference_type=ReferenceType.ORDER,
        reference_id=str(order_id),
        items=[_item(process) for process in processes],
        actor=actor,
    )
    for process, item in zip(processes, demand.items.order_by("position"), strict=True):
        process.demand_item_id = item.pk


def _item(process):
    code = process.process_type.code
    return {
        "charge_type": ChargeType.PROCESS_COURT_FEE,
        "reference_type": code if code in ReferenceType.values else ReferenceType.OTHER,
        "reference_id": str(process.pk),
        "description": (
            f"Court fee: {process.process_type.label} to {process.recipient_name}"
            f" by {process.channel.label}"
        ),
        "unit_amount": process.court_fee - process.fee_from_pool,
    }
