"""Collecting and crediting payments in-process (spec 0017 #5–#8, #14, #18).

Runs with no default provider, so payments stay INITIATED until confirmed
in-process — the provider-free path of spec 0017 #9.3.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.payments import errors, selectors
from apps.payments.enums import ChargeType, DemandItemStatus, DemandStatus, PaymentStatus
from apps.payments.exceptions import ImmutableRecordError, PaymentNotConfirmable
from apps.payments.models import DemandItem, Payment, PaymentDemandItem
from apps.payments.services import PaymentService
from apps.payments.signals import payment_completed
from apps.payments.tasks import notify_payment_completed

from .helpers import item, item_ids

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("no_provider")]


def pay(demand, ids, *, user, key=None, **kwargs):
    """Create a payment for ``ids`` on ``demand``."""

    return PaymentService.create_payment(
        demand=demand,
        demand_item_ids=ids,
        client_request_id=key or f"key-{'-'.join(str(i)[:8] for i in ids)}",
        actor=user,
        **kwargs,
    )


def statuses(demand):
    return [i.status for i in demand.items.order_by("position")]


def business_error(callable_, *args, **kwargs) -> BusinessError:
    with pytest.raises(BusinessError) as caught:
        callable_(*args, **kwargs)
    return caught.value


class TestLineItemWise:
    def test_one_item_at_a_time(self, raise_demand, user):
        demand = raise_demand()
        ids = item_ids(demand)

        p1 = pay(demand, ids[:1], user=user).payment
        assert p1.status == PaymentStatus.INITIATED
        assert p1.amount == Decimal("12.50")
        PaymentService.confirm_payment(p1)
        demand.refresh_from_db()
        assert statuses(demand) == ["PAID", "UNPAID", "UNPAID"]
        assert demand.status == DemandStatus.PARTIALLY_PAID
        assert (demand.paid_amount, demand.due_amount) == (Decimal("12.50"), Decimal("25.00"))

        for remaining in ids[1:]:
            PaymentService.confirm_payment(pay(demand, [remaining], user=user).payment)
        demand.refresh_from_db()
        assert demand.status == DemandStatus.PAID
        assert demand.due_amount == Decimal("0.00")
        assert demand.payments.count() == 3


class TestCombined:
    def test_selected_subset(self, raise_demand, user):
        demand = raise_demand()
        payment = pay(demand, item_ids(demand, 0, 1), user=user).payment
        assert payment.amount == Decimal("25.00")
        assert payment.items.count() == 2
        PaymentService.confirm_payment(payment)
        demand.refresh_from_db()
        assert statuses(demand) == ["PAID", "PAID", "UNPAID"]
        assert demand.status == DemandStatus.PARTIALLY_PAID

    def test_pay_all_is_one_payment(self, raise_demand, user):
        demand = raise_demand()
        payment = pay(demand, item_ids(demand), user=user).payment
        assert payment.amount == Decimal("37.50")
        PaymentService.confirm_payment(payment)
        demand.refresh_from_db()
        assert demand.status == DemandStatus.PAID
        assert demand.payments.count() == 1

    def test_item_wise_and_combined_end_identically(self, raise_demand, user):
        itemwise = raise_demand()
        for one in item_ids(itemwise):
            PaymentService.confirm_payment(pay(itemwise, [one], user=user).payment)
        combined = raise_demand()
        PaymentService.confirm_payment(pay(combined, item_ids(combined), user=user).payment)

        itemwise.refresh_from_db()
        combined.refresh_from_db()
        fields = ("status", "total_amount", "paid_amount", "due_amount")
        assert [getattr(itemwise, f) for f in fields] == [getattr(combined, f) for f in fields]
        assert statuses(itemwise) == statuses(combined)

    def test_two_payers_pay_different_items(self, raise_demand, user, make_user):
        """Anyone may pay; the demand records who paid each payment."""
        clerk = make_user("Clerk")
        demand = raise_demand()
        first = pay(demand, item_ids(demand, 0), user=user).payment
        second = pay(demand, item_ids(demand, 1, 2), user=clerk).payment
        PaymentService.confirm_payment(first)
        PaymentService.confirm_payment(second)
        demand.refresh_from_db()
        assert demand.status == DemandStatus.PAID
        assert {first.created_by, second.created_by} == {user, clerk}


class TestValidation:
    def test_item_from_another_demand(self, raise_demand, user):
        demand, other = raise_demand(), raise_demand()
        error = business_error(pay, demand, [*item_ids(demand, 0), *item_ids(other, 0)], user=user)
        assert error.error is errors.ITEM_NOT_IN_DEMAND
        assert "demand_item_ids[1]" in error.detail

    def test_unknown_item(self, raise_demand, user):
        demand = raise_demand()
        error = business_error(pay, demand, ["not-a-uuid"], user=user)
        assert error.error is errors.ITEM_NOT_IN_DEMAND

    def test_duplicate_item(self, raise_demand, user):
        demand = raise_demand()
        [one] = item_ids(demand, 0)
        error = business_error(pay, demand, [one, one], user=user)
        assert error.error is errors.DUPLICATE_DEMAND_ITEM
        assert "demand_item_ids[1]" in error.detail

    def test_empty_list(self, raise_demand, user):
        demand = raise_demand()
        assert business_error(pay, demand, [], user=user, key="k").error is api_errors.EMPTY

    def test_paid_item(self, raise_demand, user):
        demand = raise_demand()
        PaymentService.confirm_payment(pay(demand, item_ids(demand, 0), user=user).payment)
        error = business_error(pay, demand, item_ids(demand, 0), user=user, key="again")
        assert error.error is errors.ITEM_NOT_PAYABLE

    def test_cancelled_item(self, raise_demand, user):
        from apps.payments.services import DemandService

        demand = raise_demand()
        DemandService.cancel_item(demand.items.order_by("position").first())
        error = business_error(pay, demand, item_ids(demand, 0), user=user)
        assert error.error is errors.ITEM_NOT_PAYABLE

    def test_paid_or_cancelled_demand(self, raise_demand, user):
        from apps.payments.services import DemandService

        paid = raise_demand([item()])
        PaymentService.confirm_payment(pay(paid, item_ids(paid), user=user).payment)
        assert business_error(pay, paid, item_ids(paid), user=user, key="x").error is (
            errors.DEMAND_NOT_PAYABLE
        )

        cancelled = raise_demand([item()])
        DemandService.cancel_demand(cancelled)
        assert business_error(pay, cancelled, item_ids(cancelled), user=user).error is (
            errors.DEMAND_NOT_PAYABLE
        )

    def test_amounts_come_from_the_items(self, raise_demand, user):
        demand = raise_demand([item(unit_amount="99.99", quantity=3)])
        payment = pay(demand, item_ids(demand), user=user).payment
        assert payment.amount == Decimal("299.97")
        assert payment.items.get().amount == Decimal("299.97")
        assert payment.currency == demand.currency == "INR"


class TestIdempotency:
    def test_same_key_returns_the_same_payment(self, raise_demand, user):
        demand = raise_demand()
        first = pay(demand, item_ids(demand, 0), user=user, key="k1")
        again = pay(demand, item_ids(demand, 0), user=user, key="k1")
        assert first.created and not again.created
        assert again.payment.pk == first.payment.pk
        assert Payment.objects.count() == 1

    def test_same_key_with_other_items_is_a_conflict(self, raise_demand, user):
        demand = raise_demand()
        pay(demand, item_ids(demand, 0), user=user, key="k1")
        error = business_error(pay, demand, item_ids(demand, 1), user=user, key="k1")
        assert error.error is errors.CLIENT_REQUEST_ID_REUSED

    def test_replay_of_a_terminal_payment_returns_it(self, raise_demand, user):
        demand = raise_demand()
        first = pay(demand, item_ids(demand, 0), user=user, key="k1").payment
        PaymentService.fail_payment(first, failure_code="X")
        again = pay(demand, item_ids(demand, 0), user=user, key="k1")
        assert again.payment.pk == first.pk and again.payment.status == PaymentStatus.FAILED

    def test_database_constraint_backs_the_key(self, raise_demand, user):
        demand = raise_demand()
        payment = pay(demand, item_ids(demand, 0), user=user, key="k1").payment
        with pytest.raises(IntegrityError), transaction.atomic():
            Payment.objects.create(
                payment_number="PAY-dup",
                demand=demand,
                amount=Decimal("1.00"),
                currency="INR",
                client_request_id="k1",
                initiated_at=payment.initiated_at,
            )

    def test_retry_that_waited_for_the_lock_replays(self, raise_demand, user):
        """A retry that missed the key before the lock replays after it.

        The winner's items are already in flight; without the re-check under the
        lock the retry failed with PAYMENT_IN_FLIGHT (seen with concurrent
        retries on PostgreSQL).
        """
        demand = raise_demand()
        winner = pay(demand, item_ids(demand, 0), user=user, key="k1").payment
        real_find = PaymentService._find_existing
        calls = []

        def miss_first(*args, **kwargs):
            calls.append(1)
            return None if len(calls) == 1 else real_find(*args, **kwargs)

        with patch.object(PaymentService, "_find_existing", side_effect=miss_first):
            again = pay(demand, item_ids(demand, 0), user=user, key="k1")
        assert not again.created and again.payment.pk == winner.pk
        assert Payment.objects.count() == 1

    def test_insert_collision_replays(self, raise_demand, user):
        """The unique constraint is the backstop: an IntegrityError becomes a replay."""
        demand = raise_demand()
        winner = pay(demand, item_ids(demand, 0), user=user, key="k1").payment
        real_find = PaymentService._find_existing
        calls = []

        def miss_first(*args, **kwargs):
            calls.append(1)
            return None if len(calls) == 1 else real_find(*args, **kwargs)

        with (
            patch.object(PaymentService, "_find_existing", side_effect=miss_first),
            patch.object(PaymentService, "_create_rows", side_effect=IntegrityError),
        ):
            again = pay(demand, item_ids(demand, 0), user=user, key="k1")
        assert not again.created and again.payment.pk == winner.pk

    def test_duplicate_confirmation_credits_once(self, raise_demand, user):
        demand = raise_demand([item()])
        payment = pay(demand, item_ids(demand), user=user).payment
        PaymentService.confirm_payment(payment)
        PaymentService.confirm_payment(payment)
        demand.refresh_from_db()
        assert demand.paid_amount == Decimal("12.50")
        assert DemandItem.objects.get().paid_amount == Decimal("12.50")


class TestConcurrency:
    def test_second_payment_over_an_in_flight_item_is_rejected(self, raise_demand, user, make_user):
        demand = raise_demand()
        pay(demand, item_ids(demand, 0), user=user, key="a")
        error = business_error(pay, demand, item_ids(demand, 0, 1), user=make_user(), key="b")
        assert error.error is errors.PAYMENT_IN_FLIGHT
        assert "demand_item_ids[0]" in error.detail

    def test_failed_or_cancelled_payment_frees_the_items(self, raise_demand, user):
        demand = raise_demand()
        failed = pay(demand, item_ids(demand, 0), user=user, key="a").payment
        PaymentService.fail_payment(failed, failure_code="X")
        cancelled = pay(demand, item_ids(demand, 0), user=user, key="b").payment
        PaymentService.cancel_payment(cancelled, reason="changed mind")
        third = pay(demand, item_ids(demand, 0), user=user, key="c").payment
        assert third.status == PaymentStatus.INITIATED
        demand.refresh_from_db()
        assert demand.paid_amount == Decimal("0.00")


class TestState:
    def test_terminal_payments_cannot_be_confirmed(self, raise_demand, user):
        demand = raise_demand()
        failed = pay(demand, item_ids(demand, 0), user=user, key="a").payment
        PaymentService.fail_payment(failed, failure_code="X")
        with pytest.raises(PaymentNotConfirmable):
            PaymentService.confirm_payment(failed)

    def test_successful_payment_cannot_fail_or_cancel(self, raise_demand, user):
        demand = raise_demand()
        payment = pay(demand, item_ids(demand, 0), user=user).payment
        PaymentService.confirm_payment(payment)
        with pytest.raises(PaymentNotConfirmable):
            PaymentService.fail_payment(payment, failure_code="X")
        assert business_error(PaymentService.cancel_payment, payment).error is (
            errors.PAYMENT_NOT_CANCELLABLE
        )

    def test_successful_payment_is_frozen(self, raise_demand, user):
        demand = raise_demand()
        payment = pay(demand, item_ids(demand, 0), user=user).payment
        PaymentService.confirm_payment(payment)
        payment = Payment.objects.get(pk=payment.pk)
        payment.amount = Decimal("1.00")
        with pytest.raises(ImmutableRecordError):
            payment.save()
        with pytest.raises(ImmutableRecordError):
            PaymentDemandItem.objects.first().save()
        with pytest.raises(ImmutableRecordError):
            payment.delete()
        with pytest.raises(ImmutableRecordError):
            Payment.objects.filter(pk=payment.pk).delete()
        with pytest.raises(ImmutableRecordError):
            PaymentDemandItem.objects.filter(payment=payment).delete()


class TestBatch:
    def demands(self, raise_demand, n=3):
        return [
            raise_demand([item(ChargeType.APPLICATION_FEE, unit_amount="10.00")]) for _ in range(n)
        ]

    def batch(self, demands, user, key="batch-1"):
        return PaymentService.create_batch(
            selections=[{"demand": d, "demand_item_ids": item_ids(d)} for d in demands],
            client_request_id=key,
            actor=user,
        )

    def test_payments_share_a_batch(self, raise_demand, user):
        demands = self.demands(raise_demand)
        collection = self.batch(demands, user)
        assert len(collection.payments) == 3
        assert len({p.batch_id for p in collection.payments}) == 1
        assert len({p.payment_number for p in collection.payments}) == 3
        assert collection.amount == Decimal("30.00")

    def test_confirm_credits_every_demand(self, raise_demand, user):
        demands = self.demands(raise_demand)
        collection = self.batch(demands, user)
        PaymentService.confirm_payment(collection.payments[1])
        for demand in demands:
            demand.refresh_from_db()
            assert demand.status == DemandStatus.PAID
        assert {p.status for p in Payment.objects.all()} == {PaymentStatus.SUCCESS}

    def test_failure_leaves_every_demand_unpaid(self, raise_demand, user):
        demands = self.demands(raise_demand)
        collection = self.batch(demands, user)
        PaymentService.fail_payment(collection.payments[0], failure_code="X")
        assert {p.status for p in Payment.objects.all()} == {PaymentStatus.FAILED}
        assert set(DemandItem.objects.values_list("status", flat=True)) == {"UNPAID"}

    def test_one_invalid_selection_creates_nothing(self, raise_demand, user):
        demands = self.demands(raise_demand)
        PaymentService.confirm_payment(pay(demands[2], item_ids(demands[2]), user=user).payment)
        before = Payment.objects.count()
        error = business_error(self.batch, demands, user)
        assert error.error is errors.DEMAND_NOT_PAYABLE
        assert "selections[2].demand_id" in error.detail
        assert Payment.objects.count() == before

    def test_replay_returns_the_batch(self, raise_demand, user):
        demands = self.demands(raise_demand)
        first = self.batch(demands, user)
        again = self.batch(demands, user)
        assert not again.created
        assert {p.pk for p in again.payments} == {p.pk for p in first.payments}

    def test_replay_with_another_selection_is_a_conflict(self, raise_demand, user):
        demands = self.demands(raise_demand)
        self.batch(demands, user)
        assert business_error(self.batch, demands[:2], user).error is (
            errors.CLIENT_REQUEST_ID_REUSED
        )

    def test_repeated_demand_and_size_cap(self, raise_demand, user, settings):
        demands = self.demands(raise_demand, 2)
        error = business_error(self.batch, [demands[0], demands[1], demands[0]], user)
        assert error.error is errors.DEMAND_REPEATED_IN_BATCH
        settings.PAYMENT_BATCH_MAX_DEMANDS = 1
        assert business_error(self.batch, demands, user).error is errors.BATCH_TOO_LARGE

    def test_mixed_currencies_are_rejected(self, raise_demand, user):
        inr = raise_demand([item()])
        usd = raise_demand([item()], currency="USD")
        assert business_error(self.batch, [inr, usd], user).error is errors.CURRENCY_MISMATCH


class TestPaidTotal:
    def test_sums_paid_items_of_the_charge_types_on_the_case(self, raise_demand, user, case_id):
        filing = raise_demand(
            [item(ChargeType.PROCESS_COURT_FEE, quantity=2), item(ChargeType.COURT_FEE)]
        )
        later = raise_demand(
            [item(ChargeType.PROCESS_COURT_FEE), item(ChargeType.PROCESS_COURT_FEE)]
        )
        other_case = raise_demand(
            [item(ChargeType.PROCESS_COURT_FEE)], case="00000000-0000-0000-0000-000000000001"
        )

        PaymentService.confirm_payment(pay(filing, item_ids(filing), user=user).payment)
        PaymentService.confirm_payment(pay(later, item_ids(later, 0), user=user).payment)
        PaymentService.confirm_payment(pay(other_case, item_ids(other_case), user=user).payment)
        # Unpaid (item 1 of `later`) and cancelled items never count.

        total = selectors.paid_total(case=case_id, charge_types=[ChargeType.PROCESS_COURT_FEE])
        assert total == Decimal("37.50")
        assert selectors.paid_total(case=case_id, charge_types=[ChargeType.EPOST_FEE]) == 0


class TestCompletionNotice:
    def test_confirm_enqueues_after_commit_and_the_actor_publishes(
        self, raise_demand, user, django_capture_on_commit_callbacks
    ):
        demand = raise_demand([item()])
        payment = pay(demand, item_ids(demand), user=user).payment
        with patch.object(notify_payment_completed, "send") as send:
            with django_capture_on_commit_callbacks(execute=True):
                PaymentService.confirm_payment(payment)
        send.assert_called_once_with(str(payment.pk))

        received = []

        def receiver(sender, **kwargs):
            received.append(kwargs)

        payment_completed.connect(receiver)
        try:
            assert notify_payment_completed(str(payment.pk)) is True
        finally:
            payment_completed.disconnect(receiver)
        [event] = received
        assert event["payment"].pk == payment.pk
        assert event["demand_paid"] is True
        assert [i.status for i in event["items"]] == [DemandItemStatus.PAID]

    def test_actor_ignores_unsuccessful_payments(self, raise_demand, user):
        demand = raise_demand([item()])
        payment = pay(demand, item_ids(demand), user=user).payment
        assert notify_payment_completed(str(payment.pk)) is False
        assert notify_payment_completed("00000000-0000-0000-0000-000000000000") is False

    def test_broker_outage_does_not_undo_the_credit(
        self, raise_demand, user, django_capture_on_commit_callbacks
    ):
        demand = raise_demand([item()])
        payment = pay(demand, item_ids(demand), user=user).payment
        with patch.object(notify_payment_completed, "send", side_effect=ConnectionError):
            with django_capture_on_commit_callbacks(execute=True):
                PaymentService.confirm_payment(payment)
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.SUCCESS
