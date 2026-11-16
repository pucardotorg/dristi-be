"""Choosing a provider per payment (spec 0032 #4.2, #17.2 SEL-01 – SEL-14)."""

import pytest
from django.urls import reverse

from apps.api.errors import BusinessError
from apps.payments import errors
from apps.payments.checks import check_payment_settings
from apps.payments.enums import FAILURE_PROVIDER_ID_COLLISION, PaymentStatus
from apps.payments.models import Payment
from apps.payments.providers import registry
from apps.payments.providers.base import ActionKind, ConfirmationMode
from apps.payments.services import PaymentService
from apps.payments.services.polling import poll_one

from .conftest import ATTESTED_PATH, FAKE_PATH, MOCK_PATH
from .fakes import FakeAttestedProvider, FakeProvider
from .helpers import assert_error, item, item_ids

pytestmark = pytest.mark.django_db

PROVIDERS = reverse("payments-providers")


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


class TestChoice:
    def test_sel_01_no_provider_uses_the_default(self, raise_demand, user, attested_provider):
        payment = pay(raise_demand(), user).payment
        assert payment.provider == "fake"
        assert "requested_provider" not in payment.metadata

    def test_sel_02_chosen_provider(self, raise_demand, user, attested_provider):
        collection = pay(raise_demand(), user, provider="counter")
        payment = collection.payment
        assert payment.provider == "counter"
        assert payment.status == PaymentStatus.PENDING
        assert payment.metadata["requested_provider"] == "counter"
        assert collection.action.kind == ActionKind.SHOW_INSTRUCTIONS
        assert not FakeProvider.initiate_calls

    def test_sel_03_registered_but_not_selectable(self, raise_demand, user, attested_provider):
        error = error_of(pay, raise_demand(), user, provider="mock")
        assert error.error is errors.PROVIDER_NOT_AVAILABLE
        assert "provider" in error.detail
        assert not Payment.objects.exists()

    def test_sel_04_unknown_or_blank(self, raise_demand, user, attested_provider):
        demand = raise_demand()
        assert error_of(pay, demand, user, provider="ghost").error is errors.PROVIDER_NOT_AVAILABLE
        assert pay(demand, user, provider="  ").payment.provider == "fake"

    def test_sel_05_empty_list_accepts_only_the_default(self, raise_demand, user, settings):
        settings.PAYMENT_PROVIDERS = {"fake": FAKE_PATH, "counter": ATTESTED_PATH}
        settings.PAYMENT_DEFAULT_PROVIDER = "fake"
        settings.PAYMENT_SELECTABLE_PROVIDERS = []
        registry.reset_cache()
        demand = raise_demand()
        assert error_of(pay, demand, user, provider="counter").error is (
            errors.PROVIDER_NOT_AVAILABLE
        )
        assert pay(demand, user, provider="fake").payment.provider == "fake"

    def test_no_default_and_no_list_refuses_any_name(self, raise_demand, user, no_provider):
        assert error_of(pay, raise_demand(), user, provider="mock").error is (
            errors.PROVIDER_NOT_AVAILABLE
        )

    def test_sel_06_replay_same_provider(self, raise_demand, user, attested_provider):
        demand = raise_demand()
        first = pay(demand, user, provider="counter")
        again = pay(demand, user, provider="counter")
        assert not again.created
        assert again.payment.pk == first.payment.pk
        assert again.action == first.action

    def test_sel_07_replay_different_provider(self, raise_demand, user, attested_provider):
        demand = raise_demand()
        pay(demand, user, provider="counter")
        for other in ("fake", "", None):
            error = error_of(pay, demand, user, provider=other)
            assert error.error is errors.CLIENT_REQUEST_ID_REUSED

    def test_replay_naming_the_default_it_went_to(self, raise_demand, user, attested_provider):
        """Omitting the provider and naming the one it went to are the same request."""
        demand = raise_demand()
        first = pay(demand, user)
        assert pay(demand, user, provider="fake").payment.pk == first.payment.pk
        assert error_of(pay, demand, user, provider="counter").error is (
            errors.CLIENT_REQUEST_ID_REUSED
        )

    def test_replay_after_the_default_changed(
        self, raise_demand, user, attested_provider, settings
    ):
        """An existing client replaying without a provider still gets its payment back."""
        demand = raise_demand()
        first = pay(demand, user)
        settings.PAYMENT_DEFAULT_PROVIDER = "counter"
        settings.PAYMENT_SELECTABLE_PROVIDERS = ["counter", "fake"]
        registry.reset_cache()
        again = pay(demand, user)
        assert not again.created and again.payment.pk == first.payment.pk
        assert again.payment.provider == "fake"

    def test_explicit_default_then_omitted(self, raise_demand, user, attested_provider):
        demand = raise_demand()
        first = pay(demand, user, provider="fake")
        assert pay(demand, user).payment.pk == first.payment.pk

    def test_sel_08_batch(self, raise_demand, user, attested_provider):
        demands = [raise_demand([item()], reference_id=f"o-{n}") for n in range(3)]
        collection = PaymentService.create_batch(
            selections=[{"demand": d, "demand_item_ids": item_ids(d)} for d in demands],
            client_request_id="b",
            provider="counter",
            actor=user,
        )
        payments = collection.payments
        assert {p.provider for p in payments} == {"counter"}
        assert len({p.provider_payment_id for p in payments}) == 1
        assert len({p.batch_id for p in payments}) == 1 and payments[0].batch_id

    def test_sel_09_removed_from_selectable_after_initiation(
        self, raise_demand, user, attested_provider, settings, clerk
    ):
        payment = pay(raise_demand(), user, provider="counter").payment
        settings.PAYMENT_SELECTABLE_PROVIDERS = ["fake"]
        registry.reset_cache()

        poll_one(payment)
        assert FakeAttestedProvider.fetch_calls == [payment.provider_payment_id]
        result = PaymentService.record_collection(
            provider="counter",
            provider_payment_id=payment.provider_payment_id,
            amount=payment.amount,
            method="CASH",
            receipt_number="R-1",
            collected_at=payment.initiated_at,
            actor=clerk,
        )
        assert result.payments[0].status == PaymentStatus.SUCCESS

    def test_provider_withdrawn_between_check_and_initiation(
        self, raise_demand, user, attested_provider, monkeypatch
    ):
        """The rows are failed, so a refused provider never blocks the items."""
        from apps.payments.services import payments as payments_service

        def withdraw(name):
            raise BusinessError(errors.PROVIDER_NOT_AVAILABLE, field="provider")

        monkeypatch.setattr(payments_service.registry, "get_for_new_payment", withdraw)
        error = error_of(pay, raise_demand(), user, provider="counter")
        assert error.error is errors.PROVIDER_NOT_AVAILABLE
        assert Payment.objects.get().status == PaymentStatus.FAILED

    def test_sel_09_cancel_after_removal(self, raise_demand, user, attested_provider, settings):
        payment = pay(raise_demand(), user, provider="counter").payment
        settings.PAYMENT_SELECTABLE_PROVIDERS = ["fake"]
        registry.reset_cache()
        PaymentService.request_cancellation(payment, actor=user)
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.CANCELLED


class TestProviderList:
    @pytest.fixture(autouse=True)
    def _clear_options_cache(self):
        from django.core.cache import cache

        cache.clear()
        yield
        cache.clear()

    def test_sel_10_lists_providers_in_order(self, api, attested_provider):
        response = api.get(PROVIDERS)
        assert response.status_code == 200
        body = response.json()
        assert "meta" in body
        assert body["default"] == "fake"
        assert [p["name"] for p in body["providers"]] == ["fake", "counter"]
        fake, counter = body["providers"]
        assert fake["label"] == "fake"  # no label: falls back to the name
        assert fake["confirmation"] == ConfirmationMode.PROVIDER
        assert fake["options"] == [{"code": "BANK-01", "label": "Bank one", "group": "NET_BANKING"}]
        assert counter["label"] == "Pay at a counter"
        assert counter["confirmation"] == ConfirmationMode.ATTESTED
        assert counter["options"][0]["group"] == "COUNTER"

    def test_sel_11_a_failing_provider_is_left_out(self, api, attested_provider):
        from apps.payments.providers.base import ProviderTransientError

        FakeAttestedProvider.list_error = ProviderTransientError("DOWN")
        body = api.get(PROVIDERS).json()
        assert [p["name"] for p in body["providers"]] == ["fake"]

    def test_a_failing_default_is_unavailable(self, api, attested_provider, monkeypatch):
        from apps.payments.providers.base import ProviderTransientError

        def broken(self):
            raise ProviderTransientError("DOWN")

        monkeypatch.setattr(FakeProvider, "list_options", broken)
        assert_error(api.get(PROVIDERS), errors.PROVIDER_UNAVAILABLE)

    def test_options_are_cached(self, api, attested_provider):
        api.get(PROVIDERS)
        FakeAttestedProvider.list_error = RuntimeError("would fail if called")
        body = api.get(PROVIDERS).json()
        assert [p["name"] for p in body["providers"]] == ["fake", "counter"]

    def test_default_only(self, api, fake_provider):
        body = api.get(PROVIDERS).json()
        assert body["default"] == "fake"
        assert [p["name"] for p in body["providers"]] == ["fake"]

    def test_no_provider(self, api, no_provider):
        assert api.get(PROVIDERS).json()["providers"] == []

    def test_anonymous(self, attested_provider):
        from rest_framework.test import APIClient

        from apps.api import errors as api_errors

        response = APIClient().get(PROVIDERS)
        assert response.json()["errors"][0]["code"] == api_errors.NOT_AUTHENTICATED.code


class TestChecks:
    def ids(self):
        return sorted(message.id for message in check_payment_settings(None))

    def test_valid(self, attested_provider):
        assert self.ids() == []

    def test_sel_12_e008_unknown_selectable(self, attested_provider, settings):
        settings.PAYMENT_SELECTABLE_PROVIDERS = ["fake", "ghost"]
        assert self.ids() == ["payments.E008"]

    def test_sel_12_e009_default_not_selectable(self, attested_provider, settings):
        settings.PAYMENT_SELECTABLE_PROVIDERS = ["counter"]
        assert self.ids() == ["payments.E009"]

    def test_sel_12_e010_attested_without_methods(self, settings, monkeypatch):
        settings.PAYMENT_PROVIDERS = {"counter": ATTESTED_PATH, "mock": MOCK_PATH}
        settings.PAYMENT_DEFAULT_PROVIDER = "mock"
        settings.PAYMENT_SELECTABLE_PROVIDERS = []
        registry.reset_cache()
        assert self.ids() == []
        monkeypatch.setattr(FakeAttestedProvider, "attestation_methods", lambda self: [])
        assert self.ids() == ["payments.E010"]

    def test_sel_12_e010_attested_without_attest(self, settings, monkeypatch):
        from apps.payments.providers.base import PaymentProvider

        settings.PAYMENT_PROVIDERS = {"counter": ATTESTED_PATH, "mock": MOCK_PATH}
        settings.PAYMENT_DEFAULT_PROVIDER = "mock"
        registry.reset_cache()
        monkeypatch.setattr(FakeAttestedProvider, "attest", PaymentProvider.attest)
        assert self.ids() == ["payments.E010"]

    def test_a_provider_gateway_needs_no_methods(self, fake_provider):
        assert self.ids() == []


class TestIdCollision:
    def test_sel_13_collision_fails_the_new_payment(
        self, raise_demand, user, settings, monkeypatch
    ):
        settings.PAYMENT_PROVIDERS = {"fake": FAKE_PATH}
        settings.PAYMENT_DEFAULT_PROVIDER = "fake"
        registry.reset_cache()
        first = pay(raise_demand(reference_id="a"), user).payment

        # The fake derives its id from the reference: make the next one collide.
        original = FakeProvider.initiate

        def colliding(self, request):
            initiation = original(self, request)
            from dataclasses import replace

            return replace(initiation, provider_payment_id=first.provider_payment_id)

        monkeypatch.setattr(FakeProvider, "initiate", colliding)
        error = error_of(pay, raise_demand(reference_id="b"), user, key="k2")
        assert error.error is errors.PROVIDER_UNAVAILABLE

        second = Payment.objects.exclude(pk=first.pk).get()
        assert second.status == PaymentStatus.FAILED
        assert second.failure_code == FAILURE_PROVIDER_ID_COLLISION
        assert second.provider_payment_id == ""
        first.refresh_from_db()
        assert first.status == PaymentStatus.PENDING

    def test_sel_13_mark_pending_refuses_a_held_id(self, raise_demand, user, fake_provider):
        from apps.payments.services.payments import _ProviderIdCollision

        first = pay(raise_demand(reference_id="a"), user).payment
        second = Payment.objects.create(
            payment_number="PAY-X",
            demand=raise_demand(reference_id="b"),
            amount=first.amount,
            currency="INR",
            client_request_id="other",
            initiated_at=first.initiated_at,
        )
        with pytest.raises(_ProviderIdCollision):
            PaymentService.mark_pending(
                [second], provider="fake", provider_payment_id=first.provider_payment_id
            )
        second.refresh_from_db()
        assert second.status == PaymentStatus.INITIATED

    def test_sel_13_collision_is_logged(
        self, raise_demand, user, fake_provider, caplog, monkeypatch
    ):
        first = pay(raise_demand(reference_id="a"), user).payment
        original = FakeProvider.initiate

        def colliding(self, request):
            from dataclasses import replace

            return replace(original(self, request), provider_payment_id=first.provider_payment_id)

        caplog.set_level("ERROR", logger="apps.payments")
        monkeypatch.setattr(FakeProvider, "initiate", colliding)
        error_of(pay, raise_demand(reference_id="b"), user, key="k2")
        assert "event=PROVIDER_ID_COLLISION" in caplog.text

    def test_sel_14_same_id_on_two_providers(self, raise_demand, user, fake_provider):
        first = pay(raise_demand(reference_id="a"), user).payment
        second = Payment.objects.create(
            payment_number="PAY-Y",
            demand=raise_demand(reference_id="b"),
            amount=first.amount,
            currency="INR",
            client_request_id="other",
            initiated_at=first.initiated_at,
        )
        PaymentService.mark_pending(
            [second], provider="mock", provider_payment_id=first.provider_payment_id
        )
        second.refresh_from_db()
        assert second.status == PaymentStatus.PENDING

    def test_a_batch_shares_its_id_without_collision(self, raise_demand, user, fake_provider):
        demands = [raise_demand([item()], reference_id=f"o-{n}") for n in range(2)]
        payments = PaymentService.create_batch(
            selections=[{"demand": d, "demand_item_ids": item_ids(d)} for d in demands],
            client_request_id="b",
            actor=user,
        ).payments
        assert {p.status for p in payments} == {PaymentStatus.PENDING}


def test_registry_helpers(attested_provider, settings):
    assert registry.selectable_names() == ["fake", "counter"]
    assert [p.name for p in registry.selectable()] == ["fake", "counter"]
    assert registry.attested_names() == ["counter"]
    assert registry.is_attested("counter") and not registry.is_attested("fake")
    assert not registry.is_attested("ghost")
    assert registry.get_for_new_payment("").name == "fake"
    settings.PAYMENT_SELECTABLE_PROVIDERS = [" fake ", "", "counter", "fake"]
    assert registry.selectable_names() == ["fake", "counter"]
