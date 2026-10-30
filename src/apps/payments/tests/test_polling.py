"""The status poller and the operator tooling (spec 0017 #9.7, #15, #18 "Poller")."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.payments.enums import PaymentStatus
from apps.payments.models import DemandItem, Payment
from apps.payments.providers.base import ProviderTransientError
from apps.payments.services import PaymentService, polling
from apps.payments.tasks import poll_pending_payments

from .fakes import FakeProvider, status
from .helpers import item, item_ids

pytestmark = pytest.mark.django_db


@pytest.fixture
def payment(raise_demand, user, fake_provider, settings):
    settings.PAYMENT_STATUS_POLL_INTERVAL_SECONDS = 60
    settings.PAYMENT_STATUS_POLL_MAX_INTERVAL_SECONDS = 600
    demand = raise_demand()
    return PaymentService.create_payment(
        demand=demand, demand_item_ids=item_ids(demand), client_request_id="k", actor=user
    ).payment


def at(payment, seconds):
    return payment.initiated_at + timedelta(seconds=seconds)


class TestBackoff:
    def test_first_poll_waits_one_interval(self, payment):
        assert polling.poll_pending_payments(now=at(payment, 30)) == 0
        assert polling.poll_pending_payments(now=at(payment, 61)) == 1
        payment.refresh_from_db()
        assert payment.poll_count == 1
        assert payment.last_polled_at == at(payment, 61)

    def test_interval_doubles_up_to_the_cap(self, payment):
        payment.poll_count = 3
        payment.last_polled_at = at(payment, 0)
        assert polling.next_poll_at(payment) == at(payment, 480)
        payment.poll_count = 10
        assert polling.next_poll_at(payment) == at(payment, 600)

    def test_batch_is_polled_once(self, raise_demand, user, fake_provider):
        demands = [raise_demand([item()]) for _ in range(3)]
        PaymentService.create_batch(
            selections=[{"demand": d, "demand_item_ids": item_ids(d)} for d in demands],
            client_request_id="b",
            actor=user,
        )
        later = timezone.now() + timedelta(hours=1)
        assert polling.poll_pending_payments(now=later) == 1
        assert len(FakeProvider.fetch_calls) == 1
        assert set(Payment.objects.values_list("poll_count", flat=True)) == {1}

    def test_batch_size_caps_a_run(self, raise_demand, user, fake_provider, settings):
        for key in ("a", "b", "c"):
            demand = raise_demand([item()])
            PaymentService.create_payment(
                demand=demand, demand_item_ids=item_ids(demand), client_request_id=key, actor=user
            )
        settings.PAYMENT_STATUS_POLL_BATCH_SIZE = 2
        assert polling.poll_pending_payments(now=timezone.now() + timedelta(hours=1)) == 2


class TestOutcomes:
    def test_success_is_applied(self, payment):
        FakeProvider.statuses = {
            payment.provider_payment_id: status(payment.provider_payment_id, "SUCCESS", "37.50")
        }
        polling.poll_pending_payments(now=at(payment, 61))
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.SUCCESS

    def test_not_found_inside_grace_keeps_pending_then_fails(self, payment):
        polling.poll_pending_payments(now=at(payment, 61))
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.PENDING

        Payment.objects.filter(pk=payment.pk).update(
            initiated_at=timezone.now() - timedelta(hours=1), last_polled_at=None, poll_count=0
        )
        polling.poll_pending_payments()
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.FAILED
        assert payment.failure_code == "PAYMENT_NOT_FOUND_AT_PROVIDER"

    def test_transient_error_is_retried_next_run(self, payment):
        FakeProvider.fetch_error = ProviderTransientError("TIMEOUT")
        polling.poll_pending_payments(now=at(payment, 61))
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.PENDING
        assert payment.poll_count == 1

    def test_never_fails_on_age_but_flags_past_the_horizon(self, payment):
        FakeProvider.statuses = {
            payment.provider_payment_id: status(payment.provider_payment_id, "PENDING")
        }
        beyond = at(payment, int(FakeProvider.pending_horizon.total_seconds()) + 61)
        polling.poll_pending_payments(now=beyond)
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.PENDING
        assert payment.needs_reconciliation
        assert payment.metadata["reconciliation"]["reason"] == "PAYMENT_STUCK"

    def test_one_failing_payment_does_not_stop_the_run(self, raise_demand, user, fake_provider):
        from unittest.mock import patch

        for key in ("a", "b"):
            demand = raise_demand([item()])
            PaymentService.create_payment(
                demand=demand, demand_item_ids=item_ids(demand), client_request_id=key, actor=user
            )
        real_poll = polling.poll_one
        calls = []

        def first_one_breaks(payment, **kwargs):
            calls.append(payment.pk)
            if len(calls) == 1:
                raise RuntimeError("database hiccup")
            return real_poll(payment, **kwargs)

        with patch.object(polling, "poll_one", side_effect=first_one_breaks):
            assert polling.poll_pending_payments(now=timezone.now() + timedelta(hours=1)) == 2
        assert len(calls) == 2
        assert Payment.objects.filter(poll_count=1).count() == 1

    def test_unregistered_provider_is_skipped(self, payment, settings):
        settings.PAYMENT_PROVIDERS = {"mock": "apps.payments.providers.mock.MockPaymentProvider"}
        from apps.payments.providers import registry

        registry.reset_cache()
        assert polling.poll_pending_payments(now=at(payment, 61)) == 1
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.PENDING

    def test_actor_and_command_run_a_pass(self, payment, capsys):
        assert poll_pending_payments() == 0  # not due yet
        call_command("payments_poll_pending")
        assert "Checked 0" in capsys.readouterr().out


class TestReconciliationTools:
    def test_clear_reconciliation_credits_nothing(self, payment, user):
        PaymentService.apply_provider_status(
            [payment], status(payment.provider_payment_id, "SUCCESS", "1.00")
        )
        payment.refresh_from_db()
        assert payment.needs_reconciliation
        PaymentService.clear_reconciliation(payment, actor=user, note="refunded at the bank")
        payment.refresh_from_db()
        assert not payment.needs_reconciliation
        assert payment.metadata["reconciliation"]["note"] == "refunded at the bank"
        assert payment.status == PaymentStatus.PENDING

    def test_verify_balances_is_clean_then_reports_drift(self, payment, capsys):
        FakeProvider.trusted = True
        PaymentService.apply_provider_status(
            [payment], status(payment.provider_payment_id, "SUCCESS", "37.50")
        )
        call_command("payments_verify_balances")
        assert "consistent" in capsys.readouterr().out

        DemandItem.objects.filter(demand=payment.demand).update(paid_amount=0)
        with pytest.raises(CommandError):
            call_command("payments_verify_balances")
        assert "paid 0.00 != successful payments 12.50" in capsys.readouterr().out


class TestResolvedFlagsStayResolved:
    """Poll -> clear -> poll: an operator's resolution is not undone by the poller."""

    HORIZON = int(FakeProvider.pending_horizon.total_seconds())

    def answer(self, payment, outcome, amount=None):
        FakeProvider.statuses = {
            payment.provider_payment_id: status(payment.provider_payment_id, outcome, amount)
        }

    def reconciliation(self, payment):
        payment.refresh_from_db()
        return payment.needs_reconciliation, payment.metadata.get("reconciliation", {})

    def test_stuck_payment(self, payment, user):
        self.answer(payment, "PENDING")
        polling.poll_pending_payments(now=at(payment, self.HORIZON + 61))
        flagged, record = self.reconciliation(payment)
        assert flagged and record["reason"] == "PAYMENT_STUCK"

        PaymentService.clear_reconciliation(payment, actor=user, note="checked with the bank")
        polling.poll_pending_payments(now=at(payment, self.HORIZON + 5000))
        flagged, record = self.reconciliation(payment)
        assert not flagged
        assert record["note"] == "checked with the bank"
        assert payment.poll_count == 2  # still polled, just not re-flagged

    def test_amount_mismatch(self, payment, user):
        self.answer(payment, "SUCCESS", "1.00")
        polling.poll_pending_payments(now=at(payment, 61))
        flagged, first = self.reconciliation(payment)
        assert flagged and first["reason"] == "PAYMENT_AMOUNT_MISMATCH"

        # A second poll leaves the existing flag and its record alone.
        polling.poll_pending_payments(now=at(payment, 1000))
        flagged, again = self.reconciliation(payment)
        assert flagged and again == first

        PaymentService.clear_reconciliation(payment, actor=user)
        polling.poll_pending_payments(now=at(payment, 2000))
        flagged, record = self.reconciliation(payment)
        assert not flagged and record["resolved_at"]
        assert payment.status == PaymentStatus.PENDING
        assert payment.demand.paid_amount == 0

    def test_late_success_after_an_open_stuck_flag_is_flagged_and_logged(self, payment, caplog):
        """An open STUCK flag must not swallow a later late success."""
        self.answer(payment, "PENDING")
        polling.poll_pending_payments(now=at(payment, self.HORIZON + 61))
        self.answer(payment, "FAILED")
        polling.poll_pending_payments(now=at(payment, self.HORIZON + 5000))
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.FAILED and payment.needs_reconciliation

        self.answer(payment, "SUCCESS", str(payment.amount))
        PaymentService.refresh_from_provider(payment)
        flagged, record = self.reconciliation(payment)
        assert flagged and record["reason"] == "PAYMENT_LATE_SUCCESS"
        history = payment.metadata["reconciliation_history"]
        assert [r["reason"] for r in history] == ["PAYMENT_STUCK"]
        assert "PAYMENT_LATE_SUCCESS" in caplog.text
        assert payment.status == PaymentStatus.FAILED  # never credited

    def test_a_new_problem_is_still_flagged(self, payment, user):
        self.answer(payment, "SUCCESS", "1.00")
        polling.poll_pending_payments(now=at(payment, 61))
        PaymentService.clear_reconciliation(payment, actor=user)

        # Later the payment is also stuck past the provider's horizon.
        self.answer(payment, "PENDING")
        polling.poll_pending_payments(now=at(payment, self.HORIZON + 61))
        flagged, record = self.reconciliation(payment)
        assert flagged and record["reason"] == "PAYMENT_STUCK"
