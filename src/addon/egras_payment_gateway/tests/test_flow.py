"""End-to-end e-GRAS flow through 0017's payment APIs, with e-GRAS mocked.

Covers create → redirect form, forged callback staying pending, callback →
verification → success, a cross-demand batch, and the permanent-failure paths
(unmapped charge, invalid bank). e-GRAS HTTP is replaced by a mocked
``requests.post`` returning canned ``GrnDetails`` documents.
"""

from decimal import Decimal
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from django.urls import reverse
from rest_framework.test import APIClient

from addon.egras_payment_gateway import constants
from apps.api.errors import BusinessError
from apps.payments import errors as payments_errors
from apps.payments.enums import ChargeType, DemandItemStatus, PaymentStatus
from apps.payments.models import Payment
from apps.payments.providers.base import ActionKind
from apps.payments.services import PaymentService
from apps.payments.tests.helpers import item_ids

pytestmark = pytest.mark.django_db


def grn_xml(
    status="Successfull", *, grn="1231234", cin="CIN123", amount="100", bankdate="12/10/2026"
):
    return (
        f"<GrnDetails><GRN>{grn}</GRN><Amount>{amount}</Amount>"
        f"<Status>{status}</Status><CIN>{cin}</CIN><Bankdate>{bankdate}</Bankdate></GrnDetails>"
    ).encode()


def mock_verify(content):
    response = mock.Mock(spec=requests.Response)
    response.content = content
    response.status_code = 200
    response.ok = True
    return mock.patch.object(requests, "post", return_value=response)


def callback(provider_payment_id, status_text="Success"):
    """Post the browser's return-URL form to the public callback endpoint."""

    client = APIClient(enforce_csrf_checks=True)
    url = reverse("payments-provider-callback", kwargs={"provider": "egras"})
    return client.post(
        url, {"Applicationnumber": provider_payment_id, "status": status_text, "GRN": "1231234"}
    )


def redirect_status(response):
    assert response.status_code == 302, response.content
    query = parse_qs(urlparse(response["Location"]).query)
    return query.get("status", [""])[0]


def pay(demand, *, user, bank="SBI"):
    return PaymentService.create_payment(
        demand=demand,
        demand_item_ids=item_ids(demand),
        client_request_id="k",
        provider_options={"bank": bank},
        actor=user,
    )


def test_create_payment_returns_egras_redirect_form(egras, raise_demand, user):
    collection = pay(raise_demand(), user=user)
    payment = collection.payment
    action = collection.action

    assert action.kind == ActionKind.REDIRECT_FORM
    assert action.url == "https://egras.invalid/echallan"
    assert payment.provider == "egras"
    assert payment.status == PaymentStatus.PENDING
    assert payment.provider_payment_id.startswith("DR")
    form = action.form_fields
    assert form[constants.FIELD_APPLICATION_NUMBER] == payment.provider_payment_id
    assert form[constants.FIELD_TOTAL_AMOUNT] == "100"
    assert form[constants.scheme_name_field(1)] == "0030-01-501-01-00"
    assert form[constants.FIELD_UURL].endswith("/providers/egras/_callback")


def test_callback_verifies_to_success(egras, raise_demand, user):
    payment = pay(raise_demand(), user=user).payment

    with mock_verify(grn_xml()):
        assert redirect_status(callback(payment.provider_payment_id)) == PaymentStatus.SUCCESS

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCESS
    assert payment.provider_reference == "1231234"
    assert payment.metadata["provider"]["cin"] == "CIN123"
    assert [i.status for i in payment.demand.items.all()] == [DemandItemStatus.PAID]


def test_forged_success_callback_stays_pending(egras, raise_demand, user):
    """The browser claims success, but verification is the only truth (spec 0022 #5.3)."""
    payment = pay(raise_demand(), user=user).payment

    with mock_verify(grn_xml(status="Pending")):
        assert redirect_status(callback(payment.provider_payment_id)) == PaymentStatus.PENDING

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING
    assert payment.demand.paid_amount == Decimal("0.00")


def test_batch_of_three_is_one_transaction_and_one_verification(egras, raise_demand, user):
    demands = [raise_demand(reference_id=f"order-{n}") for n in range(3)]
    collection = PaymentService.create_batch(
        selections=[{"demand": d, "demand_item_ids": item_ids(d)} for d in demands],
        client_request_id="batch",
        provider_options={"bank": "SBI"},
        actor=user,
    )

    provider_payment_ids = {p.provider_payment_id for p in collection.payments}
    assert len(provider_payment_ids) == 1  # one e-GRAS transaction for the batch
    provider_payment_id = provider_payment_ids.pop()

    with mock_verify(grn_xml(amount="300")) as post:
        assert redirect_status(callback(provider_payment_id)) == PaymentStatus.SUCCESS
        assert post.call_count == 1  # one verification for all three payments

    for payment in collection.payments:
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.SUCCESS


def test_unmapped_charge_is_rejected(egras, raise_demand, user):
    demand = raise_demand(charge_type=ChargeType.APPLICATION_FEE)
    with pytest.raises(BusinessError) as caught:
        pay(demand, user=user)

    assert caught.value.error is payments_errors.PROVIDER_REJECTED
    payment = Payment.objects.get(demand=demand)
    assert payment.status == PaymentStatus.FAILED
    assert payment.failure_code == constants.EGRAS_SCHEME_UNMAPPED


def test_invalid_bank_is_rejected_on_the_option_field(egras, raise_demand, user):
    with pytest.raises(BusinessError) as caught:
        pay(raise_demand(), user=user, bank="HDFC")

    assert caught.value.error is payments_errors.PROVIDER_OPTION_INVALID
    assert "provider_options.bank" in caught.value.detail


def test_failure_status_fails_the_payment(egras, raise_demand, user):
    payment = pay(raise_demand(), user=user).payment

    with mock_verify(grn_xml(status="Failure")):
        assert (
            redirect_status(callback(payment.provider_payment_id, "Failure"))
            == PaymentStatus.FAILED
        )

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED
    assert payment.failure_code == constants.EGRAS_PAYMENT_FAILED
