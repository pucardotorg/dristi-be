"""Racing recorders, cancels and the poller (spec 0032 #8.3, #17.2 CON-01 – CON-06).

Real threads on real connections: ``select_for_update`` is a no-op on SQLite,
so these run only on PostgreSQL (CI sets ``DATABASE_URL``).
"""

import threading
from decimal import Decimal

import pytest
from django.db import connection, connections
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.payments import errors
from apps.payments.enums import DemandItemStatus, PaymentStatus
from apps.payments.models import DemandItem, Payment, PaymentAttestation
from apps.payments.providers.base import ProviderOutcome
from apps.payments.services import PaymentService

from .fakes import FakeAttestedProvider, status
from .helpers import item, item_ids

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="row locks need PostgreSQL (spec 0017 #8)"
    ),
]


def race(*calls):
    """Run ``calls`` at the same moment in threads; return each result or exception."""

    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def run(index, call):
        try:
            barrier.wait()
            results[index] = call()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            results[index] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


def codes(results):
    return sorted(
        r.error.code if isinstance(r, BusinessError) else type(r).__name__ for r in results
    )


@pytest.fixture
def make_request(raise_demand, user, attested_provider):
    counter = iter(range(100))

    def factory(**kwargs):
        n = next(counter)
        demand = raise_demand(reference_id=f"order-{n}", **kwargs)
        return PaymentService.create_payment(
            demand=demand,
            demand_item_ids=item_ids(demand),
            client_request_id=f"k-{n}",
            provider="counter",
            actor=user,
        ).payment

    return factory


def recorder(payment, actor, receipt):
    return lambda: PaymentService.record_collection(
        provider="counter",
        provider_payment_id=payment.provider_payment_id,
        amount=payment.amount,
        method="CASH",
        receipt_number=receipt,
        collected_at=timezone.now(),
        actor=actor,
    )


def test_con_01_same_request_same_receipt(make_request, clerk):
    payment = make_request()
    results = race(recorder(payment, clerk, "R-1"), recorder(payment, clerk, "R-1"))
    assert all(not isinstance(r, BaseException) for r in results), results
    assert sorted(r.created for r in results) == [False, True]
    assert PaymentAttestation.objects.count() == 1
    paid = DemandItem.objects.filter(demand=payment.demand)
    assert {i.status for i in paid} == {DemandItemStatus.PAID}
    payment.demand.refresh_from_db()
    assert payment.demand.paid_amount == Decimal("37.50")


def test_con_02_same_request_different_receipts(make_request, clerk):
    payment = make_request()
    results = race(recorder(payment, clerk, "R-1"), recorder(payment, clerk, "R-2"))
    assert codes(results) == sorted(["CollectionResult", errors.COLLECTION_NOT_OPEN.code])
    assert PaymentAttestation.objects.count() == 1


def test_con_03_two_requests_same_receipt(make_request, clerk):
    first, second = make_request(), make_request()
    results = race(recorder(first, clerk, "R-1"), recorder(second, clerk, "R-1"))
    assert codes(results) == sorted(["CollectionResult", errors.RECEIPT_NUMBER_USED.code])
    assert PaymentAttestation.objects.count() == 1
    assert sorted(Payment.objects.values_list("status", flat=True)) == sorted(
        [PaymentStatus.SUCCESS, PaymentStatus.PENDING]
    )


def test_con_04_record_vs_payer_cancel(make_request, clerk, user):
    payment = make_request()
    results = race(
        recorder(payment, clerk, "R-1"),
        lambda: PaymentService.request_cancellation(payment, actor=user),
    )
    payment.refresh_from_db()
    if payment.status == PaymentStatus.SUCCESS:
        assert errors.PAYMENT_NOT_CANCELLABLE.code in codes(results)
    else:
        assert payment.status == PaymentStatus.CANCELLED
        assert errors.COLLECTION_NOT_OPEN.code in codes(results)
        assert not PaymentAttestation.objects.exists()


def test_con_05_record_vs_poller_expiry(make_request, clerk):
    payment = make_request()
    FakeAttestedProvider.fetch_outcome = ProviderOutcome.FAILED
    expiry = status(payment.provider_payment_id, "FAILED")
    results = race(
        recorder(payment, clerk, "R-1"),
        lambda: PaymentService.apply_provider_status([payment], expiry),
    )
    payment.refresh_from_db()
    assert payment.status in (PaymentStatus.SUCCESS, PaymentStatus.FAILED)
    if payment.status == PaymentStatus.FAILED:
        assert errors.COLLECTION_NOT_OPEN.code in codes(results)
    else:
        assert PaymentAttestation.objects.count() == 1


def test_con_06_batch_record_vs_create_payment(raise_demand, user, attested_provider, clerk):
    shared = raise_demand([item(), item()], reference_id="shared")
    other = raise_demand([item()], reference_id="other")
    first_item, second_item = item_ids(shared)
    batch = PaymentService.create_batch(
        selections=[
            {"demand": shared, "demand_item_ids": [first_item]},
            {"demand": other, "demand_item_ids": item_ids(other)},
        ],
        client_request_id="batch",
        provider="counter",
        actor=user,
    ).payments
    results = race(
        lambda: PaymentService.record_collection(
            provider="counter",
            provider_payment_id=batch[0].provider_payment_id,
            amount="25.00",
            method="CASH",
            receipt_number="R-1",
            collected_at=timezone.now(),
            actor=clerk,
        ),
        lambda: PaymentService.create_payment(
            demand=shared, demand_item_ids=[second_item], client_request_id="k2", actor=user
        ),
    )
    assert all(not isinstance(r, BaseException) for r in results), results
    shared.refresh_from_db()
    assert shared.paid_amount == Decimal("12.50")
