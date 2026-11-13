"""Cancelling, polling and re-showing attested payments (spec 0032 #4.5, #4.8, #17.2 LIF).

Expiry through the real offline provider is covered in
``addon/offline_payment/tests/test_flow.py``.
"""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.payments import errors
from apps.payments.enums import PaymentStatus
from apps.payments.models import Payment
from apps.payments.providers.base import ProviderOutcome
from apps.payments.services import PaymentService, polling

from .fakes import FakeAttestedProvider
from .helpers import assert_error, item_ids

pytestmark = pytest.mark.django_db


@pytest.fixture
def demand(raise_demand):
    return raise_demand()


@pytest.fixture
def pending(demand, user, attested_provider):
    return PaymentService.create_payment(
        demand=demand,
        demand_item_ids=item_ids(demand),
        client_request_id="k",
        provider="counter",
        actor=user,
    ).payment


def payment_url(payment, suffix):
    return reverse(f"payments-payment-{suffix}", kwargs={"payment_id": payment.pk})


class TestPayerCancel:
    def test_lif_01_cancelled_at_once_without_asking_the_provider(self, api, pending):
        response = api.post(payment_url(pending, "cancel"), {"reason": "online"}, format="json")
        assert response.status_code == 200, response.content
        assert response.json()["status"] == PaymentStatus.CANCELLED
        assert FakeAttestedProvider.fetch_calls == []

    def test_lif_02_then_pays_through_the_gateway(self, api, pending, demand):
        api.post(payment_url(pending, "cancel"), {}, format="json")
        body = {"client_request_id": "k2", "demand_item_ids": [str(i) for i in item_ids(demand)]}
        response = api.post(
            reverse("payments-demand-payments", kwargs={"demand_id": demand.pk}),
            body,
            format="json",
        )
        assert response.status_code == 201, response.content
        assert response.json()["provider"] == "fake"

    def test_lif_03_gateway_payment_while_the_request_is_open(self, api, pending, demand):
        body = {"client_request_id": "k2", "demand_item_ids": [str(i) for i in item_ids(demand)]}
        response = api.post(
            reverse("payments-demand-payments", kwargs={"demand_id": demand.pk}),
            body,
            format="json",
        )
        assert_error(response, errors.PAYMENT_IN_FLIGHT, "demand_item_ids[0]")

    def test_lif_04_another_participant_cannot_cancel(self, pending, make_user, involve, case_id):
        other = make_user("Co-complainant")
        involve(other, case_id)
        client = APIClient()
        client.force_authenticate(other)
        assert_error(
            client.post(payment_url(pending, "cancel"), {}, format="json"),
            errors.NOT_PAYMENT_CREATOR,
        )

    def test_terminal_payment_is_not_cancellable(self, api, pending):
        PaymentService.confirm_payment(pending)
        assert_error(
            api.post(payment_url(pending, "cancel"), {}, format="json"),
            errors.PAYMENT_NOT_CANCELLABLE,
        )


class TestPolling:
    def test_lif_08_pending_stays_pending(self, pending):
        polling.poll_one(pending, now=timezone.now() + timedelta(hours=1))
        pending.refresh_from_db()
        assert pending.status == PaymentStatus.PENDING
        assert pending.poll_count == 1

    def test_lif_09_failed_frees_the_items(self, pending, demand, user):
        FakeAttestedProvider.fetch_outcome = ProviderOutcome.FAILED
        polling.poll_one(pending, now=timezone.now() + timedelta(hours=1))
        pending.refresh_from_db()
        assert pending.status == PaymentStatus.FAILED
        again = PaymentService.create_payment(
            demand=demand, demand_item_ids=item_ids(demand), client_request_id="k2", actor=user
        ).payment
        assert again.status == PaymentStatus.PENDING


class TestCallback:
    def test_lif_11_callback_never_credits(self, pending, settings):
        settings.PAYMENT_UI_REDIRECT_URL = "https://app.example.com/return"
        response = APIClient().post(
            reverse("payments-provider-callback", kwargs={"provider": "counter"}),
            {"provider_payment_id": pending.provider_payment_id, "status": "Success"},
        )
        assert response.status_code == 302
        assert parse_qs(urlparse(response["Location"]).query)["status"] == ["UNKNOWN"]
        pending.refresh_from_db()
        assert pending.status == PaymentStatus.PENDING


class TestShowAction:
    def test_lif_13_creator_gets_the_same_details(self, api, user, demand, attested_provider):
        body = {
            "client_request_id": "k",
            "demand_item_ids": [str(i) for i in item_ids(demand)],
            "provider": "counter",
        }
        created = api.post(
            reverse("payments-demand-payments", kwargs={"demand_id": demand.pk}),
            body,
            format="json",
        ).json()
        assert created["provider_action"]["kind"] == "SHOW_INSTRUCTIONS"
        payment = Payment.objects.get()

        response = api.get(payment_url(payment, "action"))
        assert response.status_code == 200, response.content
        shown = response.json()
        assert "meta" in shown
        assert shown["payment_id"] == str(payment.pk)
        assert shown["provider"] == "counter"
        assert shown["provider_payment_id"] == payment.provider_payment_id
        assert shown["provider_action"] == created["provider_action"]

    def test_lif_14_other_participant(self, pending, make_user, involve, case_id):
        other = make_user("Co-complainant")
        involve(other, case_id)
        client = APIClient()
        client.force_authenticate(other)
        assert_error(client.get(payment_url(pending, "action")), errors.NOT_PAYMENT_CREATOR)

    @pytest.mark.parametrize("close", ["confirm", "cancel"])
    def test_lif_14_not_pending(self, api, pending, close):
        if close == "confirm":
            PaymentService.confirm_payment(pending)
        else:
            PaymentService.cancel_payment(pending)
        assert_error(api.get(payment_url(pending, "action")), errors.COLLECTION_NOT_OPEN)

    def test_stranger_gets_not_found(self, pending, other_user):
        client = APIClient()
        client.force_authenticate(other_user)
        response = client.get(payment_url(pending, "action"))
        assert response.status_code == 404

    def test_gateway_action_is_rebuilt_too(self, api, demand, user, attested_provider):
        payment = PaymentService.create_payment(
            demand=demand, demand_item_ids=item_ids(demand), client_request_id="k", actor=user
        ).payment
        body = api.get(payment_url(payment, "action")).json()
        assert body["provider_action"]["kind"] == "REDIRECT_FORM"
        assert body["provider_action"]["details"] == []
