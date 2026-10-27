"""The provider boundary (spec 0017 #9, #18 "Provider contract", "Outcome application")."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.payments import errors
from apps.payments.checks import check_payment_settings
from apps.payments.enums import DemandStatus, PaymentStatus
from apps.payments.models import Payment
from apps.payments.providers import registry
from apps.payments.providers.base import (
    ActionKind,
    ProviderCallbackMalformed,
    ProviderNotConfigured,
    ProviderOutcome,
    ProviderPermanentError,
    ProviderTransientError,
)
from apps.payments.providers.mock import MockPaymentProvider
from apps.payments.services import PaymentService

from .fakes import FakeProvider, status
from .helpers import item, item_ids

pytestmark = pytest.mark.django_db


def pay(demand, user, key="k1", ids=None, **kwargs):
    return PaymentService.create_payment(
        demand=demand,
        demand_item_ids=ids or item_ids(demand),
        client_request_id=key,
        actor=user,
        **kwargs,
    )


def error_of(callable_, *args, **kwargs) -> BusinessError:
    with pytest.raises(BusinessError) as caught:
        callable_(*args, **kwargs)
    return caught.value


class TestInitiation:
    def test_initiate_moves_payment_to_pending(self, raise_demand, user, fake_provider):
        demand = raise_demand()
        collection = pay(demand, user, provider_options={"bank": "BANK-01"})
        payment = collection.payment
        assert payment.status == PaymentStatus.PENDING
        assert payment.provider == "fake"
        assert payment.provider_payment_id.startswith("FAKE")
        assert payment.metadata["provider"] == {"bank": "BANK-01"}
        assert collection.action.kind == ActionKind.REDIRECT_FORM

        [request] = FakeProvider.initiate_calls
        assert request.reference == payment.pk
        assert request.amount == Decimal("37.50") == sum(line.amount for line in request.lines)
        assert request.payment_numbers == (payment.payment_number,)
        assert request.payer.name == "Anjali Menon"
        assert request.payer.email == "anjali@example.com"
        assert request.options == {"bank": "BANK-01"}

    def test_payer_fields_override_the_profile(self, raise_demand, user, fake_provider):
        demand = raise_demand()
        payment = pay(demand, user, payer={"name": "Party", "city": "Kochi"}).payment
        assert payment.payer["name"] == "Party"
        assert payment.payer["city"] == "Kochi"
        assert payment.payer["phone"] == user.mobile_number

    def test_permanent_error_fails_the_payment(self, raise_demand, user, fake_provider):
        FakeProvider.initiate_error = ProviderPermanentError("FAKE_UNMAPPABLE", "no head")
        demand = raise_demand()
        assert error_of(pay, demand, user).error is errors.PROVIDER_REJECTED
        payment = Payment.objects.get()
        assert payment.status == PaymentStatus.FAILED
        assert payment.failure_code == "FAKE_UNMAPPABLE"
        # The items are immediately payable again with a new key.
        FakeProvider.initiate_error = None
        assert pay(demand, user, key="k2").payment.status == PaymentStatus.PENDING

    def test_permanent_error_on_an_option_names_the_field(self, raise_demand, user, fake_provider):
        FakeProvider.initiate_error = ProviderPermanentError("BAD_BANK", "x", field="bank")
        error = error_of(pay, raise_demand(), user)
        assert error.error is errors.PROVIDER_OPTION_INVALID
        assert "provider_options.bank" in error.detail

    def test_transient_error_fails_the_payment(self, raise_demand, user, fake_provider):
        FakeProvider.initiate_error = ProviderTransientError("TIMEOUT")
        assert error_of(pay, raise_demand(), user).error is errors.PROVIDER_UNAVAILABLE
        assert Payment.objects.get().status == PaymentStatus.FAILED

    def test_a_provider_bug_is_reported_as_unavailable(self, raise_demand, user, fake_provider):
        FakeProvider.initiate_error = KeyError("boom")
        assert error_of(pay, raise_demand(), user).error is errors.PROVIDER_UNAVAILABLE
        assert Payment.objects.get().failure_code == "PROVIDER_ERROR"

    def test_misconfigured_default_fails_cleanly(self, raise_demand, user, settings):
        settings.PAYMENT_DEFAULT_PROVIDER = "ghost"
        registry.reset_cache()
        assert error_of(pay, raise_demand(), user).error is errors.PROVIDER_UNAVAILABLE
        assert Payment.objects.get().status == PaymentStatus.FAILED

    def test_no_default_provider_leaves_payment_initiated(self, raise_demand, user, no_provider):
        collection = pay(raise_demand(), user)
        assert collection.action is None
        assert collection.payment.status == PaymentStatus.INITIATED
        assert collection.payment.provider == ""


class TestReplay:
    def test_pending_replay_rebuilds_the_same_action(self, raise_demand, user, fake_provider):
        demand = raise_demand()
        first = pay(demand, user)
        again = pay(demand, user)
        assert not again.created
        assert again.action == first.action
        assert len(FakeProvider.initiate_calls) == 2
        assert FakeProvider.initiate_calls[0] == FakeProvider.initiate_calls[1]

    def test_replay_mismatch_is_a_conflict(self, raise_demand, user, fake_provider):
        demand = raise_demand()
        pay(demand, user)
        FakeProvider.id_suffix = "-DIFFERENT"
        assert error_of(pay, demand, user).error is errors.PROVIDER_REPLAY_MISMATCH

    def test_replay_routes_to_the_recorded_provider(
        self, raise_demand, user, fake_provider, settings
    ):
        demand = raise_demand()
        first = pay(demand, user)
        settings.PAYMENT_DEFAULT_PROVIDER = "mock"
        registry.reset_cache()
        assert pay(demand, user).action == first.action


class TestRegistry:
    def test_unknown_name(self):
        with pytest.raises(ProviderNotConfigured):
            registry.get("nope")

    def test_unimportable_path(self, settings):
        settings.PAYMENT_PROVIDERS = {"x": "apps.payments.nothing.Here"}
        with pytest.raises(ProviderNotConfigured):
            registry.get("x")

    def test_not_a_provider(self, settings):
        settings.PAYMENT_PROVIDERS = {"x": "apps.payments.models.Payment"}
        with pytest.raises(ProviderNotConfigured):
            registry.get("x")

    def test_name_must_match_key(self, settings):
        settings.PAYMENT_PROVIDERS = {"other": "apps.payments.providers.mock.MockPaymentProvider"}
        with pytest.raises(ProviderNotConfigured):
            registry.get("other")

    def test_default(self, settings, no_provider):
        assert registry.get_default() is None
        settings.PAYMENT_DEFAULT_PROVIDER = "mock"
        assert isinstance(registry.get_default(), MockPaymentProvider)


def pending(raise_demand, user, fake_provider, *, n=1):
    """A pending single payment, or a pending batch of ``n``."""

    if n == 1:
        return [pay(raise_demand(), user).payment]
    demands = [raise_demand([item(unit_amount="10.00")]) for _ in range(n)]
    collection = PaymentService.create_batch(
        selections=[{"demand": d, "demand_item_ids": item_ids(d)} for d in demands],
        client_request_id="batch",
        actor=user,
    )
    return collection.payments


def reload(payments):
    return [Payment.objects.get(pk=p.pk) for p in payments]


class TestApplyProviderStatus:
    """Every row of spec 0017 #9.5."""

    def test_success_with_equal_amount_confirms(self, raise_demand, user, fake_provider):
        [payment] = pending(raise_demand, user, fake_provider)
        PaymentService.apply_provider_status(
            [payment],
            status(payment.provider_payment_id, "SUCCESS", "37.50", provider_reference="TR-9"),
        )
        [payment] = reload([payment])
        assert payment.status == PaymentStatus.SUCCESS
        assert payment.provider_reference == "TR-9"
        assert payment.demand.status == DemandStatus.PAID

    def test_success_without_a_reported_amount_is_flagged(self, raise_demand, user, fake_provider):
        """An amount that was not reported cannot be "equal" (spec 0017 #9.5)."""
        [payment] = pending(raise_demand, user, fake_provider)
        PaymentService.apply_provider_status([payment], status(payment.provider_payment_id))
        [payment] = reload([payment])
        assert payment.status == PaymentStatus.PENDING
        assert payment.needs_reconciliation
        assert payment.metadata["reconciliation"]["reason"] == "PAYMENT_AMOUNT_MISMATCH"
        assert payment.metadata["reconciliation"]["amount"] is None
        assert payment.demand.paid_amount == 0

    def test_success_with_a_different_amount_is_flagged(self, raise_demand, user, fake_provider):
        [payment] = pending(raise_demand, user, fake_provider)
        PaymentService.apply_provider_status(
            [payment], status(payment.provider_payment_id, "SUCCESS", "30.00")
        )
        [payment] = reload([payment])
        assert payment.status == PaymentStatus.PENDING
        assert payment.needs_reconciliation
        assert payment.metadata["reconciliation"]["reason"] == "PAYMENT_AMOUNT_MISMATCH"
        assert payment.demand.paid_amount == 0

    def test_failed_fails(self, raise_demand, user, fake_provider):
        [payment] = pending(raise_demand, user, fake_provider)
        PaymentService.apply_provider_status(
            [payment], status(payment.provider_payment_id, "FAILED")
        )
        [payment] = reload([payment])
        assert payment.status == PaymentStatus.FAILED
        assert payment.failure_code == "FAKE_FAILED"

    def test_pending_changes_nothing(self, raise_demand, user, fake_provider):
        [payment] = pending(raise_demand, user, fake_provider)
        PaymentService.apply_provider_status(
            [payment], status(payment.provider_payment_id, "PENDING")
        )
        assert reload([payment])[0].status == PaymentStatus.PENDING

    def test_not_found_waits_for_the_grace_period(self, raise_demand, user, fake_provider):
        [payment] = pending(raise_demand, user, fake_provider)
        verdict = status(payment.provider_payment_id, "NOT_FOUND")
        PaymentService.apply_provider_status([payment], verdict)
        assert reload([payment])[0].status == PaymentStatus.PENDING

        Payment.objects.filter(pk=payment.pk).update(
            initiated_at=timezone.now() - FakeProvider.not_found_grace - timedelta(seconds=1)
        )
        PaymentService.apply_provider_status([payment], verdict)
        [payment] = reload([payment])
        assert payment.status == PaymentStatus.FAILED
        assert payment.failure_code == "PAYMENT_NOT_FOUND_AT_PROVIDER"

    def test_replayed_success_credits_once(self, raise_demand, user, fake_provider):
        [payment] = pending(raise_demand, user, fake_provider)
        verdict = status(payment.provider_payment_id, "SUCCESS", "37.50")
        PaymentService.apply_provider_status([payment], verdict)
        PaymentService.apply_provider_status([payment], verdict)
        [payment] = reload([payment])
        assert payment.demand.paid_amount == Decimal("37.50")
        assert not payment.needs_reconciliation

    @pytest.mark.parametrize("terminal", ["fail", "cancel"])
    def test_late_success_is_flagged_never_credited(
        self, raise_demand, user, fake_provider, terminal
    ):
        [payment] = pending(raise_demand, user, fake_provider)
        if terminal == "fail":
            PaymentService.fail_payment(payment, failure_code="X")
        else:
            PaymentService.cancel_payment(payment)
        PaymentService.apply_provider_status(
            [payment], status(payment.provider_payment_id, "SUCCESS", "37.50")
        )
        [payment] = reload([payment])
        assert payment.status in (PaymentStatus.FAILED, PaymentStatus.CANCELLED)
        assert payment.needs_reconciliation
        assert payment.metadata["reconciliation"]["reason"] == "PAYMENT_LATE_SUCCESS"
        assert payment.demand.paid_amount == 0

    def test_other_outcomes_on_terminal_payments_are_ignored(
        self, raise_demand, user, fake_provider
    ):
        [payment] = pending(raise_demand, user, fake_provider)
        PaymentService.fail_payment(payment, failure_code="X")
        PaymentService.apply_provider_status(
            [payment], status(payment.provider_payment_id, "PENDING")
        )
        [payment] = reload([payment])
        assert payment.status == PaymentStatus.FAILED and not payment.needs_reconciliation

    def test_batch_amount_is_the_sum_of_the_batch(self, raise_demand, user, fake_provider):
        payments = pending(raise_demand, user, fake_provider, n=3)
        assert len({p.provider_payment_id for p in payments}) == 1
        assert len(FakeProvider.initiate_calls) == 1
        provider_id = payments[0].provider_payment_id

        PaymentService.apply_provider_status(payments, status(provider_id, "SUCCESS", "10.00"))
        assert all(p.needs_reconciliation for p in reload(payments))

        PaymentService.apply_provider_status(payments, status(provider_id, "SUCCESS", "30.00"))
        assert {p.status for p in reload(payments)} == {PaymentStatus.SUCCESS}


class TestRoutingAndReplacement:
    def test_payment_keeps_its_provider_after_the_default_changes(
        self, raise_demand, user, fake_provider, settings
    ):
        [payment] = pending(raise_demand, user, fake_provider)
        settings.PAYMENT_DEFAULT_PROVIDER = "mock"
        registry.reset_cache()
        FakeProvider.statuses = {
            payment.provider_payment_id: status(payment.provider_payment_id, "SUCCESS", "37.50")
        }
        PaymentService.refresh_from_provider(payment)
        assert FakeProvider.fetch_calls == [payment.provider_payment_id]
        assert reload([payment])[0].status == PaymentStatus.SUCCESS

        # A new payment goes to the new default.
        assert pay(raise_demand(), user, key="new").payment.provider == "mock"

    def test_provider_usage_command(self, raise_demand, user, fake_provider, capsys):
        [payment] = pending(raise_demand, user, fake_provider)
        call_command("payments_provider_usage", "fake")
        out = capsys.readouterr().out
        assert "PENDING: 1" in out and "keep it registered" in out

        PaymentService.fail_payment(payment, failure_code="X")
        call_command("payments_provider_usage", "fake")
        assert "safe to remove" in capsys.readouterr().out


class TestMockProvider:
    def test_outcome_round_trips_through_the_id(self, raise_demand, user):
        collection = pay(raise_demand(), user, provider_options={"outcome": "FAILED"})
        payment = collection.payment
        assert payment.provider == "mock"
        assert collection.action.url.endswith("/api/v1/payments/providers/mock/_callback")
        assert collection.action.form_fields["provider_payment_id"] == payment.provider_payment_id

        mock = registry.get("mock")
        verdict = mock.fetch_status(provider_payment_id=payment.provider_payment_id)
        assert verdict.outcome == ProviderOutcome.FAILED
        callback = mock.parse_callback(collection.action.form_fields)
        assert callback.trusted and callback.status.outcome == ProviderOutcome.FAILED

    def test_success_reports_the_amount(self, raise_demand, user):
        payment = pay(raise_demand(), user).payment
        verdict = registry.get("mock").fetch_status(provider_payment_id=payment.provider_payment_id)
        assert verdict.outcome == ProviderOutcome.SUCCESS
        assert verdict.amount == Decimal("37.50")

    def test_unknown_outcome_is_an_option_error(self, raise_demand, user):
        error = error_of(pay, raise_demand(), user, provider_options={"outcome": "MAYBE"})
        assert error.error is errors.PROVIDER_OPTION_INVALID
        assert "provider_options.outcome" in error.detail

    def test_malformed_ids_are_rejected(self):
        mock = MockPaymentProvider()
        for bad in ("", "MOCK-x", "OTHER-a-SUCCESS-1.00", "MOCK-a-WHATEVER-1.00"):
            with pytest.raises(ProviderCallbackMalformed):
                mock.parse_callback({"provider_payment_id": bad})

    def test_options(self):
        codes = [o.code for o in MockPaymentProvider().list_options()]
        assert codes == ["SUCCESS", "FAILED", "PENDING", "NOT_FOUND"]


class TestChecks:
    def run(self):
        registry.reset_cache()
        return {message.id for message in check_payment_settings(None)}

    def test_defaults_are_clean(self):
        assert self.run() == set()

    def test_bad_registry_and_default(self, settings):
        settings.PAYMENT_PROVIDERS = {"x": "nowhere.Provider"}
        settings.PAYMENT_DEFAULT_PROVIDER = "y"
        assert {"payments.E002", "payments.E003"} <= self.run()

    def test_bad_numbers_and_redirect(self, settings):
        settings.PAYMENT_STATUS_POLL_BATCH_SIZE = 0
        settings.PAYMENT_UI_REDIRECT_URL = "/relative"
        assert {"payments.E001.PAYMENT_STATUS_POLL_BATCH_SIZE", "payments.E004"} <= self.run()

    @pytest.mark.parametrize(
        "url",
        [
            "https:///payments",
            "https://",
            "ftp://app.example.com/pay",
            "app.example.com",
            "https://[::1/pay",  # urlsplit() raises on an unmatched IPv6 bracket
        ],
    )
    def test_redirect_needs_a_scheme_and_a_host(self, settings, url):
        settings.PAYMENT_UI_REDIRECT_URL = url
        assert "payments.E004" in self.run()

    def test_production_guards(self, settings):
        settings.PAYMENT_UI_REDIRECT_URL = "http://app.example.com/pay"
        with patch("apps.payments.checks.is_production_settings", return_value=True):
            assert {"payments.E005", "payments.E006"} <= self.run()

    def test_unparseable_redirect_is_reported_not_raised_in_production(self, settings):
        settings.PAYMENT_UI_REDIRECT_URL = "https://[::1/pay"
        with patch("apps.payments.checks.is_production_settings", return_value=True):
            assert "payments.E004" in self.run()

    def test_production_https_even_without_a_default_provider(self, settings):
        """Payments pending at a former default still redirect through this URL."""
        settings.PAYMENT_PROVIDERS = {}
        settings.PAYMENT_DEFAULT_PROVIDER = ""
        settings.PAYMENT_UI_REDIRECT_URL = "http://app.example.com/pay"
        with patch("apps.payments.checks.is_production_settings", return_value=True):
            assert self.run() == {"payments.E006"}

    def test_production_requires_a_redirect_once_payments_can_start(self, settings):
        settings.PAYMENT_PROVIDERS = {"fake": "apps.payments.tests.fakes.FakeProvider"}
        settings.PAYMENT_DEFAULT_PROVIDER = "fake"
        settings.PAYMENT_UI_REDIRECT_URL = ""
        with patch("apps.payments.checks.is_production_settings", return_value=True):
            assert self.run() == {"payments.E007"}
        settings.PAYMENT_UI_REDIRECT_URL = "https://app.example.com/pay"
        with patch("apps.payments.checks.is_production_settings", return_value=True):
            assert self.run() == set()
