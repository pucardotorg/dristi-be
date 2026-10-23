"""Raising and cancelling demands (spec 0017 #6.1).

The raising module computes every amount from the fee master and nets off what
was already paid (``selectors.paid_total``); this service only validates,
snapshots and stores. A demand for nothing is refused: where nothing is due the
raising module skips its payment step instead.
"""

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.api import errors as api_errors
from apps.api.errors import BusinessError

from .. import conf, errors
from ..enums import (
    OPEN_PAYMENT_STATUSES,
    ChargeType,
    DemandItemStatus,
    DemandStatus,
    ReferenceType,
)
from ..models import Demand, DemandItem, PaymentDemandItem
from . import balances
from .numbering import DEMAND_PREFIX, next_number

# Width of the reference_id columns on Demand and DemandItem.
REFERENCE_ID_MAX_LENGTH = 64


def case_pk(case):
    """Accept a case instance or its id (``Demand.case`` is an id until cases merge)."""

    return getattr(case, "pk", case)


def breakdown_product(breakdown) -> Decimal:
    """Multiply the factors of a ``quantity_breakdown``; raise ``ValueError`` if unusable."""

    if not isinstance(breakdown, Mapping) or not breakdown:
        raise ValueError("quantity_breakdown must be a non-empty object of factors.")
    product = Decimal(1)
    for value in breakdown.values():
        if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
            raise ValueError("Every quantity_breakdown factor must be a number.")
        try:
            factor = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("Every quantity_breakdown factor must be a number.") from exc
        if not factor.is_finite() or factor <= 0:
            raise ValueError("Every quantity_breakdown factor must be greater than zero.")
        product *= factor
    return product


def quantity_matches_breakdown(quantity: Decimal, metadata) -> bool:
    """Whether ``metadata.quantity_breakdown``, when given, multiplies to ``quantity``."""

    if not isinstance(metadata, Mapping) or "quantity_breakdown" not in metadata:
        return True
    try:
        return breakdown_product(metadata["quantity_breakdown"]) == Decimal(quantity)
    except ValueError:
        return False


def _decimal(value, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BusinessError(api_errors.INVALID, "A valid number is required.", field=field) from exc
    if not number.is_finite():
        raise BusinessError(api_errors.INVALID, "A valid number is required.", field=field)
    return number


def _validated_items(items, *, reference_type: str, reference_id: str) -> list[dict]:
    """Check every item and compute its amount; any failure fails the whole demand."""

    items = list(items or [])
    if not items:
        raise BusinessError(api_errors.EMPTY, "A demand needs at least one item.", field="items")

    cleaned = []
    for index, raw in enumerate(items):
        prefix = f"items[{index}]"
        charge_type = raw.get("charge_type")
        if charge_type not in ChargeType.values:
            raise BusinessError(api_errors.INVALID_CHOICE, field=f"{prefix}.charge_type")
        item_reference_type = raw.get("reference_type") or reference_type
        if item_reference_type not in ReferenceType.values:
            raise BusinessError(api_errors.INVALID_CHOICE, field=f"{prefix}.reference_type")
        description = (raw.get("description") or "").strip()
        if not description:
            raise BusinessError(api_errors.REQUIRED, field=f"{prefix}.description")

        quantity = _decimal(raw.get("quantity", 1), f"{prefix}.quantity")
        if quantity <= 0:
            raise BusinessError(
                api_errors.MIN_VALUE, "Must be greater than zero.", field=f"{prefix}.quantity"
            )
        unit_amount = _decimal(raw.get("unit_amount"), f"{prefix}.unit_amount")
        if unit_amount <= 0:
            raise BusinessError(
                api_errors.MIN_VALUE, "Must be greater than zero.", field=f"{prefix}.unit_amount"
            )
        amount = balances.quantize(quantity * unit_amount)
        if amount <= 0:
            raise BusinessError(
                api_errors.MIN_VALUE, "The item amount rounds to zero.", field=prefix
            )

        metadata = raw.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise BusinessError(api_errors.INCORRECT_TYPE, field=f"{prefix}.metadata")
        if not quantity_matches_breakdown(quantity, metadata):
            raise BusinessError(errors.QUANTITY_BREAKDOWN_MISMATCH, field=f"{prefix}.metadata")

        item_reference_id = str(raw.get("reference_id") or reference_id)
        if len(item_reference_id) > REFERENCE_ID_MAX_LENGTH:
            raise BusinessError(api_errors.MAX_LENGTH, field=f"{prefix}.reference_id")

        cleaned.append(
            {
                "position": index,
                "charge_type": charge_type,
                "reference_type": item_reference_type,
                "reference_id": item_reference_id,
                "description": description[:255],
                "quantity": quantity,
                "unit_amount": unit_amount,
                "amount": amount,
                "account_head": (raw.get("account_head") or "")[:64],
                "metadata": dict(metadata),
            }
        )
    return cleaned


class DemandService:
    """Raise and cancel demands."""

    @staticmethod
    def raise_demand(
        *,
        case,
        reference_type: str,
        reference_id: str,
        items: Iterable[Mapping],
        user_id=None,
        organization_id=None,
        currency: str | None = None,
        due_date=None,
        metadata: Mapping | None = None,
        actor=None,
    ) -> Demand:
        """Create a demand and all its items atomically, or nothing at all.

        ``paid_amount``, ``due_amount`` and ``status`` are never taken from the
        caller. ``case`` is a case instance or its id.
        """

        if reference_type not in ReferenceType.values:
            raise BusinessError(api_errors.INVALID_CHOICE, field="reference_type")
        if not case_pk(case):
            raise BusinessError(api_errors.REQUIRED, field="case_id")
        if not reference_id:
            raise BusinessError(api_errors.REQUIRED, field="reference_id")
        if len(str(reference_id)) > REFERENCE_ID_MAX_LENGTH:
            raise BusinessError(api_errors.MAX_LENGTH, field="reference_id")
        currency = (currency or conf.default_currency()).upper()
        if len(currency) != 3 or not currency.isalpha():
            raise BusinessError(api_errors.INVALID, "Must be an ISO 4217 code.", field="currency")

        cleaned = _validated_items(items, reference_type=reference_type, reference_id=reference_id)
        total = balances.quantize(sum(item["amount"] for item in cleaned))
        if total <= 0:
            raise BusinessError(errors.DEMAND_TOTAL_ZERO)

        with transaction.atomic():
            demand = Demand.objects.create(
                demand_number=next_number(DEMAND_PREFIX),
                case_id=case_pk(case),
                reference_type=reference_type,
                reference_id=str(reference_id),
                organization_id=organization_id,
                user_id=user_id,
                currency=currency,
                status=DemandStatus.RAISED,
                total_amount=total,
                paid_amount=Decimal("0.00"),
                due_amount=total,
                due_date=due_date,
                metadata=dict(metadata or {}),
                created_by=actor,
                updated_by=actor,
            )
            for item in cleaned:
                DemandItem.objects.create(
                    demand=demand,
                    paid_amount=Decimal("0.00"),
                    due_amount=item["amount"],
                    status=DemandItemStatus.UNPAID,
                    created_by=actor,
                    updated_by=actor,
                    **item,
                )
        return demand

    @staticmethod
    def cancel_demand(demand: Demand, *, reason: str = "", actor=None) -> Demand:
        """Cancel a demand nothing has been paid against.

        A partly paid demand is wound down item by item instead, so the paid
        part keeps its demand. Cancelling an already cancelled demand is a no-op.
        """

        with transaction.atomic():
            demand = Demand.objects.select_for_update().get(pk=demand.pk)
            if demand.status == DemandStatus.CANCELLED:
                return demand
            if demand.status != DemandStatus.RAISED:
                raise BusinessError(errors.DEMAND_NOT_CANCELLABLE)

            items = list(
                DemandItem.objects.select_for_update().filter(demand=demand).order_by("pk")
            )
            if PaymentDemandItem.objects.filter(
                demand_item__in=items, payment__status__in=OPEN_PAYMENT_STATUSES
            ).exists():
                raise BusinessError(errors.DEMAND_NOT_CANCELLABLE)

            for item in items:
                if item.status == DemandItemStatus.UNPAID:
                    balances.cancel_item(item, reason=reason, actor=actor)
            demand.cancelled_at = timezone.now()
            demand.cancellation_reason = reason[:255]
            demand.save(update_fields=["cancelled_at", "cancellation_reason", "updated_at"])
            return balances.recompute_demand(demand, actor=actor)

    @staticmethod
    def cancel_item(demand_item: DemandItem, *, reason: str = "", actor=None) -> DemandItem:
        """Cancel one unpaid item and recompute its demand."""

        with transaction.atomic():
            demand = Demand.objects.select_for_update().get(pk=demand_item.demand_id)
            item = DemandItem.objects.select_for_update().get(pk=demand_item.pk)
            if item.status == DemandItemStatus.CANCELLED:
                return item
            in_flight = PaymentDemandItem.objects.filter(
                demand_item=item, payment__status__in=OPEN_PAYMENT_STATUSES
            ).exists()
            if item.status == DemandItemStatus.PAID or in_flight:
                raise BusinessError(errors.ITEM_NOT_CANCELLABLE)

            balances.cancel_item(item, reason=reason, actor=actor)
            balances.recompute_demand(demand, actor=actor)
            return item
