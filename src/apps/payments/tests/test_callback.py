"""The public provider callback (spec 0017 #9.6, #18 "Callback")."""

from urllib.parse import parse_qs, urlparse

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.api import errors as api_errors
from apps.payments.enums import DemandStatus, PaymentStatus
from apps.payments.models import Payment
from apps.payments.providers.base import ProviderTransientError
from apps.payments.services import PaymentService

from .fakes import FakeProvider, status
from .helpers import assert_error, item, item_ids

pytestmark = pytest.mark.django_db

REDIRECT = "https://app.example.com/payments/return"


@pytest.fixture(autouse=True)
def redirect_target(settings):
    settings.PAYMENT_UI_REDIRECT_URL = REDIRECT


def callback_url(provider="fake"):
    return reverse("payments-provider-callback", kwargs={"provider": provider})


def post(payload, provider="fake", **extra):
    """Post as the browser does: anonymous, form encoded, no CSRF token."""

    client = APIClient(enforce_csrf_checks=True)
    return client.post(callback_url(provider), payload, **extra)


def redirect_params(response):
    assert response.status_code == 302, response.content
    target = urlparse(response["Location"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == REDIRECT
    return {key: values[0] for key, values in parse_qs(target.query).items()}


@pytest.fixture
def payment(raise_demand, user, fake_provider):
    demand = raise_demand()
    return PaymentService.create_payment(
        demand=demand, demand_item_ids=item_ids(demand), client_request_id="k", actor=user
    ).payment


def test_trusted_success_is_applied_and_redirects(payment):
    FakeProvider.trusted = True
    response = post({"id": payment.provider_payment_id, "outcome": "SUCCESS", "amount": "37.50"})
    params = redirect_params(response)
    assert params == {"payment_id": str(payment.pk), "status": PaymentStatus.SUCCESS}
    payment.refresh_from_db()
    assert payment.demand.status == DemandStatus.PAID
    assert FakeProvider.fetch_calls == []


def test_untrusted_callback_is_verified_before_any_write(payment):
    FakeProvider.statuses = {
        payment.provider_payment_id: status(payment.provider_payment_id, "SUCCESS", "37.50")
    }
    params = redirect_params(post({"id": payment.provider_payment_id, "outcome": "FAILED"}))
    # The provider's authoritative answer wins over what the browser claimed.
    assert params["status"] == PaymentStatus.SUCCESS
    assert FakeProvider.fetch_calls == [payment.provider_payment_id]


def test_forged_success_with_no_provider_record_leaves_payment_pending(payment):
    params = redirect_params(post({"id": payment.provider_payment_id, "outcome": "SUCCESS"}))
    assert params["status"] == PaymentStatus.PENDING
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING
    assert payment.demand.paid_amount == 0


def test_transient_verification_error_redirects_pending(payment):
    FakeProvider.fetch_error = ProviderTransientError("TIMEOUT")
    params = redirect_params(post({"id": payment.provider_payment_id}))
    assert params["status"] == PaymentStatus.PENDING


def test_unknown_provider_is_a_404(payment):
    assert_error(post({"id": "x"}, provider="nobody"), api_errors.NOT_FOUND)


@pytest.mark.parametrize("payload", [{}, {"id": "FAKE-NO-SUCH-PAYMENT"}])
def test_malformed_or_unmatched_redirects_unknown(payment, payload):
    params = redirect_params(post(payload))
    assert params == {"status": "UNKNOWN"}
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING


def test_redirect_target_cannot_be_influenced(payment):
    FakeProvider.trusted = True
    response = post(
        {"id": payment.provider_payment_id, "redirect": "https://evil.example", "next": "//evil"},
        QUERY_STRING="redirect=https://evil.example",
    )
    redirect_params(response)
    assert "evil" not in response["Location"]


def test_oversized_body_is_refused(payment, settings):
    settings.PAYMENT_CALLBACK_MAX_BODY_BYTES = 10
    params = redirect_params(post({"id": payment.provider_payment_id, "pad": "x" * 100}))
    assert params == {"status": "UNKNOWN"}
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING


def test_batch_redirects_with_the_batch_id(raise_demand, user, fake_provider):
    demands = [raise_demand([item()]) for _ in range(2)]
    collection = PaymentService.create_batch(
        selections=[{"demand": d, "demand_item_ids": item_ids(d)} for d in demands],
        client_request_id="b",
        actor=user,
    )
    FakeProvider.trusted = True
    provider_payment_id = collection.payments[0].provider_payment_id
    params = redirect_params(post({"id": provider_payment_id, "amount": "25.00"}))
    assert params == {"batch_id": str(collection.batch_id), "status": PaymentStatus.SUCCESS}
    assert {p.status for p in Payment.objects.all()} == {PaymentStatus.SUCCESS}


def test_without_a_redirect_target_a_page_is_rendered(payment, settings):
    settings.PAYMENT_UI_REDIRECT_URL = ""
    FakeProvider.trusted = True
    response = post({"id": payment.provider_payment_id, "amount": "37.50"})
    assert response.status_code == 200
    assert b"SUCCESS" in response.content


def test_mock_flow_end_to_end(raise_demand, api, user):
    """The browser posts the mock's form straight back to the callback."""
    demand = raise_demand()
    created = api.post(
        reverse("payments-demand-payments", kwargs={"demand_id": demand.pk}),
        {
            "client_request_id": "e2e",
            "demand_item_ids": [str(i) for i in item_ids(demand)],
            "provider_options": {"outcome": "SUCCESS"},
        },
        format="json",
    ).json()
    action = created["provider_action"]
    assert action["kind"] == "REDIRECT_FORM"

    response = APIClient(enforce_csrf_checks=True).post(action["url"], action["form_fields"])
    params = redirect_params(response)
    assert params == {"payment_id": created["id"], "status": "SUCCESS"}

    detail = api.get(reverse("payments-payment-detail", kwargs={"payment_id": created["id"]}))
    assert detail.json()["status"] == "SUCCESS"
    demand.refresh_from_db()
    assert demand.status == DemandStatus.PAID


def test_callback_is_throttled_per_ip(payment, settings):
    settings.PAYMENT_CALLBACK_THROTTLE_RATE = "2/min"
    cache.clear()
    try:
        assert post({"id": "a"}).status_code == 302
        assert post({"id": "b"}).status_code == 302
        assert post({"id": "c"}).status_code == 429
    finally:
        cache.clear()


def test_provider_bugs_still_redirect(payment):
    """The callback never answers with an error body (spec 0017 #12.5)."""
    from unittest.mock import patch

    with patch.object(FakeProvider, "parse_callback", side_effect=RuntimeError("bug")):
        assert redirect_params(post({"id": payment.provider_payment_id})) == {"status": "UNKNOWN"}

    FakeProvider.fetch_error = RuntimeError("bug")
    params = redirect_params(post({"id": payment.provider_payment_id}))
    assert params["status"] == PaymentStatus.PENDING


def test_malformed_json_body_redirects_unknown(payment):
    response = APIClient().post(callback_url(), "{not json", content_type="application/json")
    assert redirect_params(response) == {"status": "UNKNOWN"}
