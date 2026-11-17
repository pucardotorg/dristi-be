"""Read-only queries (spec 0017 #1, #6.5, #13; spec 0032 #9.2, #9.3).

Every payer-facing REST queryset starts here, already narrowed to what the
caller may see (``access.py``), so a record on someone else's case is a plain
404. The collection desk queries are not case-scoped — court staff are not case
participants — but are restricted to providers completed by attestation.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, Min, Prefetch, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.cases.selectors import get_case_summaries, search_case_ids

from . import access
from .enums import DemandItemStatus
from .models import ZERO, DemandItem, Payment, PaymentAttestation, PaymentDemandItem
from .providers import registry
from .providers.base import ProviderError, ProviderNotConfigured
from .services.demands import case_pk

# Collection dates are court dates (spec 0032 #9.3).
IST = ZoneInfo("Asia/Kolkata")


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


def attestations_for(payments) -> dict[tuple[str, str], PaymentAttestation]:
    """The recorded collections of ``payments``, keyed by provider transaction."""

    keys = {(p.provider, p.provider_payment_id) for p in payments if p.provider_payment_id}
    if not keys:
        return {}
    query = Q()
    for provider, provider_payment_id in keys:
        query |= Q(provider=provider, provider_payment_id=provider_payment_id)
    return {
        (row.provider, row.provider_payment_id): row
        for row in PaymentAttestation.objects.filter(query)
    }


# ---------------------------------------------------------------------------
# Collection desk (spec 0032 #9.2, #9.3)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CollectionRequest:
    """One attested payment request: the payment group sharing a reference."""

    provider: str
    reference: str
    payments: list
    attestation: PaymentAttestation | None
    cases: dict

    @property
    def first(self) -> Payment:
        return self.payments[0]

    @property
    def amount(self) -> Decimal:
        return sum((payment.amount for payment in self.payments), ZERO)

    @property
    def initiated_at(self):
        return min(payment.initiated_at for payment in self.payments)

    @property
    def valid_until(self) -> datetime | None:
        """``metadata["provider"]["valid_until"]``, which ATTESTED providers write."""

        raw = (self.first.metadata.get("provider") or {}).get("valid_until")
        parsed = parse_datetime(raw) if isinstance(raw, str) else None
        return parsed if parsed is not None and timezone.is_aware(parsed) else None


def _collection_payments():
    return Payment.objects.select_related("demand", "created_by").prefetch_related(
        Prefetch(
            "items",
            queryset=PaymentDemandItem.objects.select_related("demand_item").order_by(
                "demand_item__position", "demand_item_id"
            ),
        )
    )


def attested_payments(provider: str | None = None):
    """Payments of ``provider`` (or of every attested provider) handed to it."""

    names = registry.attested_names()
    if provider:
        names = [name for name in names if name == provider]
    return Payment.objects.filter(provider__in=names).exclude(provider_payment_id="")


def collection_request(provider: str, reference: str) -> CollectionRequest | None:
    """The request ``reference`` of ``provider``, or ``None``."""

    payments = list(
        _collection_payments()
        .filter(provider=provider, provider_payment_id=reference)
        .order_by("payment_number")
    )
    if not payments:
        return None
    return _build_requests([(provider, reference)], payments)[0]


def _build_requests(keys, payments) -> list[CollectionRequest]:
    grouped = defaultdict(list)
    for payment in payments:
        grouped[(payment.provider, payment.provider_payment_id)].append(payment)
    attestations = attestations_for(payments)
    cases = get_case_summaries({payment.demand.case_id for payment in payments})
    return [
        CollectionRequest(
            provider=provider,
            reference=reference,
            payments=sorted(grouped[(provider, reference)], key=lambda p: p.payment_number),
            attestation=attestations.get((provider, reference)),
            cases=cases,
        )
        for provider, reference in keys
        if grouped.get((provider, reference))
    ]


def collection_requests(
    *,
    provider: str | None = None,
    status: str | None = None,
    search: str = "",
    initiated_from: date | None = None,
    initiated_to: date | None = None,
):
    """One row per request, newest first, as ``(provider, provider_payment_id)`` values.

    Paginate the result, then pass the page to ``collection_requests_page``.
    """

    payments = attested_payments(provider)
    if status:
        payments = payments.filter(status=status)
    if initiated_from:
        payments = payments.filter(initiated_at__gte=_ist_start(initiated_from))
    if initiated_to:
        payments = payments.filter(initiated_at__lt=_ist_start(initiated_to + timedelta(days=1)))
    search = (search or "").strip()
    if search:
        payments = payments.filter(_search(search, provider))
    return (
        payments.values("provider", "provider_payment_id")
        .annotate(first_initiated_at=Min("initiated_at"))
        .order_by("-first_initiated_at", "provider_payment_id")
    )


def collection_requests_page(rows) -> list[CollectionRequest]:
    """Load the requests of one page of ``collection_requests``."""

    keys = [(row["provider"], row["provider_payment_id"]) for row in rows]
    if not keys:
        return []
    query = Q()
    for provider, reference in keys:
        query |= Q(provider=provider, provider_payment_id=reference)
    return _build_requests(keys, list(_collection_payments().filter(query)))


def _search(text: str, provider: str | None) -> Q:
    """Reference (normalised, exact), payment / demand / case number, payer name."""

    query = (
        Q(payment_number__iexact=text)
        | Q(demand__demand_number__iexact=text)
        | Q(payer__name__icontains=text)
        | Q(demand__case_id__in=search_case_ids(text))
    )
    names = [name for name in registry.attested_names() if not provider or name == provider]
    for name in names:
        try:
            reference = registry.get(name).normalise_reference(text)
        except (ProviderError, ProviderNotConfigured):
            continue  # a bad check symbol finds nothing, it is not an error
        query |= Q(provider=name, provider_payment_id=reference)
    return query


def _ist_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=IST)


def collection_register(
    *,
    provider: str | None = None,
    collected_on: date | None = None,
    recorded_by=None,
    method: str = "",
    outcome: str = "",
):
    """Recorded collections of attested providers, newest collection first (spec 0032 #9.3)."""

    names = registry.attested_names()
    if provider:
        names = [name for name in names if name == provider]
    rows = PaymentAttestation.objects.filter(provider__in=names).select_related("created_by")
    if collected_on:
        rows = rows.filter(
            collected_at__gte=_ist_start(collected_on),
            collected_at__lt=_ist_start(collected_on + timedelta(days=1)),
        )
    if recorded_by:
        rows = rows.filter(created_by_id=recorded_by)
    if method:
        rows = rows.filter(method=method.strip().upper())
    if outcome:
        rows = rows.filter(outcome=outcome)
    return rows.order_by("-collected_at", "-created_at")


def register_totals(rows) -> list[dict]:
    """Count and sum per method over the filtered register."""

    return [
        {"method": row["method"], "count": row["count"], "amount": row["amount"] or ZERO}
        for row in rows.order_by()
        .values("method")
        .annotate(count=Count("pk"), amount=Sum("amount"))
        .order_by("method")
    ]


def register_payment_numbers(rows) -> dict[tuple[str, str], list[str]]:
    """Payment numbers per request, for the rows of one register page."""

    keys = {(row.provider, row.provider_payment_id) for row in rows}
    if not keys:
        return {}
    query = Q()
    for provider, reference in keys:
        query |= Q(provider=provider, provider_payment_id=reference)
    numbers = defaultdict(list)
    for provider, reference, number in (
        Payment.objects.filter(query)
        .order_by("payment_number")
        .values_list("provider", "provider_payment_id", "payment_number")
    ):
        numbers[(provider, reference)].append(number)
    return dict(numbers)
