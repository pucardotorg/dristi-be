"""The collection desk APIs (spec 0032 #9.2, #9.3, #17.3 API-01 – API-16).

Runs on the fake attested provider ``counter``, whose references are
``CTR-<12 hex>`` and are normalised by upper-casing.
"""

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from apps.api import errors as api_errors
from apps.payments import errors
from apps.payments.enums import AttestationOutcome, PaymentStatus
from apps.payments.models import Payment, PaymentAttestation
from apps.payments.services import PaymentService

from .fakes import FakeAttestedProvider
from .helpers import assert_error, item, item_ids

pytestmark = pytest.mark.django_db

LIST = reverse("payments-collections")
METHODS = reverse("payments-collection-methods")
REGISTER = reverse("payments-collection-register")


def url(name, payment_or_reference, provider="counter"):
    reference = getattr(payment_or_reference, "provider_payment_id", payment_or_reference)
    return reverse(
        f"payments-collection-{name}", kwargs={"provider": provider, "reference": reference}
    )


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def desk(clerk):
    return client_for(clerk)


@pytest.fixture
def make_request(raise_demand, user, attested_provider):
    """Create a pending ``counter`` request on a fresh demand."""

    counter = iter(range(1000))

    def factory(provider="counter", payer=None, **kwargs):
        n = next(counter)
        demand = raise_demand(reference_id=f"order-{n}", **kwargs)
        return PaymentService.create_payment(
            demand=demand,
            demand_item_ids=item_ids(demand),
            client_request_id=f"k-{n}",
            provider=provider,
            payer=payer,
            actor=user,
        ).payment

    return factory


@pytest.fixture
def pending(make_request):
    return make_request()


def confirm_body(**overrides):
    body = {
        "amount": "37.50",
        "method": "CASH",
        "receipt_number": "CJM/EKM/2026/004512",
        "collected_at": timezone.now().isoformat(),
    }
    body.update(overrides)
    return body


class TestAccess:
    def endpoints(self, pending):
        return [
            ("get", LIST, None),
            ("get", f"{METHODS}?provider=counter", None),
            ("get", REGISTER, None),
            ("get", url("detail", pending), None),
            ("post", url("confirm", pending), confirm_body()),
            ("post", url("cancel", pending), {"reason": "x"}),
        ]

    def test_api_01_anonymous(self, pending):
        for method, path, body in self.endpoints(pending):
            response = getattr(APIClient(), method)(path, body, format="json")
            assert response.json()["errors"][0]["code"] == api_errors.NOT_AUTHENTICATED.code, path

    def test_api_01_registration_incomplete(self, pending, make_user, grant):
        from apps.users import errors as user_errors
        from apps.users.models import RegistrationStatus

        staff = make_user("New clerk")
        staff.registration_status = RegistrationStatus.PENDING_PROFILE.value
        staff.save()
        staff = grant(staff, "view_payment_collection", "record_payment_collection")
        client = client_for(staff)
        for method, path, body in self.endpoints(pending):
            response = getattr(client, method)(path, body, format="json")
            assert response.status_code == 403
            assert response.json()["errors"][0]["code"] == (
                user_errors.REGISTRATION_INCOMPLETE.code
            ), path

    def test_api_02_without_the_permission(self, pending, other_user):
        client = client_for(other_user)
        for method, path, body in self.endpoints(pending):
            assert_error(
                getattr(client, method)(path, body, format="json"), api_errors.PERMISSION_DENIED
            )

    def test_api_02_each_endpoint_needs_its_own_permission(self, pending, make_user, grant):
        viewer = client_for(grant(make_user("Viewer"), "view_payment_collection"))
        assert viewer.get(url("detail", pending)).status_code == 200
        assert_error(
            viewer.post(url("confirm", pending), confirm_body(), format="json"),
            api_errors.PERMISSION_DENIED,
        )
        assert_error(
            viewer.post(url("cancel", pending), {"reason": "x"}, format="json"),
            api_errors.PERMISSION_DENIED,
        )
        recorder = client_for(grant(make_user("Recorder"), "record_payment_collection"))
        assert_error(recorder.get(url("detail", pending)), api_errors.PERMISSION_DENIED)
        assert (
            recorder.post(url("confirm", pending), confirm_body(), format="json").status_code == 200
        )

    def test_the_payer_cannot_see_the_desk(self, api, pending):
        assert_error(api.get(url("detail", pending)), api_errors.PERMISSION_DENIED)


class TestLookup:
    def test_api_03_normalised_reference(self, desk, pending):
        response = desk.get(url("detail", pending.provider_payment_id.lower()))
        assert response.status_code == 200, response.content
        assert response.json()["reference"] == pending.provider_payment_id

    def test_api_04_malformed_reference(self, desk, pending):
        assert_error(desk.get(url("detail", "XYZ-1")), api_errors.INVALID, "reference")

    def test_unknown_reference(self, desk):
        assert_error(desk.get(url("detail", "CTR-000000000000")), api_errors.NOT_FOUND)

    def test_api_05_shape(self, desk, make_request):
        payment = make_request(payer={"phone": "+91 98000 03210", "address": "Somewhere"})
        body = desk.get(url("detail", payment)).json()
        assert "meta" in body
        assert body["provider"] == "counter"
        assert body["status"] == PaymentStatus.PENDING
        assert body["amount"] == "37.50" and body["currency"] == "INR"
        assert parse_datetime(body["valid_until"]) == parse_datetime("2099-01-01T00:00:00+05:30")
        assert body["expired"] is False
        assert body["batch_id"] is None
        assert body["payer"] == {"name": "Anjali Menon", "phone": "******3210"}
        assert "email" not in str(body["payer"]) and "Somewhere" not in str(body)
        [row] = body["payments"]
        assert row["payment_number"] == payment.payment_number
        assert row["demand_number"] == payment.demand.demand_number
        assert row["case"]["id"] == str(payment.demand.case_id)
        assert "display_number" in row["case"]
        assert len(row["items"]) == 3
        assert {"demand_item_id", "charge_type", "description", "amount"} <= set(row["items"][0])
        assert body["attestation"] is None

    def test_payer_without_a_phone(self, desk, pending):
        Payment.objects.filter(pk=pending.pk).update(payer={"name": "No Phone"})
        assert desk.get(url("detail", pending)).json()["payer"] == {
            "name": "No Phone",
            "phone": "",
        }

    def test_case_number_comes_from_the_case(self, desk, pending):
        case = pending.demand.case
        case.filing_number = "F-KL-2026-000789"
        case.save()
        body = desk.get(url("detail", pending)).json()
        assert body["payments"][0]["case"]["display_number"] == "F-KL-2026-000789"

    def test_without_valid_until(self, desk, pending):
        Payment.objects.filter(pk=pending.pk).update(metadata={})
        body = desk.get(url("detail", pending)).json()
        assert body["valid_until"] is None and body["expired"] is False

    def test_expired_flag(self, desk, pending):
        Payment.objects.filter(pk=pending.pk).update(
            metadata={"provider": {"valid_until": "2020-01-01T00:00:00+05:30"}}
        )
        assert desk.get(url("detail", pending)).json()["expired"] is True

    def test_gateway_provider_is_not_found(self, desk, make_request):
        payment = make_request(provider="fake")
        assert_error(desk.get(url("detail", payment, provider="fake")), api_errors.NOT_FOUND)
        assert_error(desk.get(url("detail", payment, provider="ghost")), api_errors.NOT_FOUND)


class TestConfirm:
    def test_api_06_happy_path(self, desk, pending, clerk):
        response = desk.post(url("confirm", pending), confirm_body(), format="json")
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["status"] == PaymentStatus.SUCCESS
        attestation = body["attestation"]
        assert attestation["receipt_number"] == "CJM/EKM/2026/004512"
        assert attestation["method"] == "CASH"
        assert attestation["amount"] == "37.50"
        assert attestation["outcome"] == AttestationOutcome.CREDITED
        assert attestation["recorded_by"] == {"id": str(clerk.pk), "name": "Suresh K"}
        assert attestation["recorded_at"]

    def test_identical_replay_returns_the_same_body(self, desk, pending):
        first = desk.post(url("confirm", pending), confirm_body(), format="json").json()
        again = desk.post(url("confirm", pending), confirm_body(), format="json")
        assert again.status_code == 200
        first.pop("meta"), again.json().pop("meta")
        assert {k: v for k, v in again.json().items() if k != "meta"} == first

    def test_api_07_collected_at_defaults_to_now(self, desk, pending):
        before = timezone.now()
        body = confirm_body()
        body.pop("collected_at")
        response = desk.post(url("confirm", pending), body, format="json")
        assert response.status_code == 200, response.content
        collected = PaymentAttestation.objects.get().collected_at
        assert before <= collected <= timezone.now()

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            ({"amount": "abc"}, "amount"),
            ({"amount": "1.234"}, "amount"),
            ({"amount": "0"}, "amount"),
            ({"amount": "-5"}, "amount"),
            ({"method": ""}, "method"),
            ({"receipt_number": ""}, "receipt_number"),
            ({"collected_at": "2026-11-12T11:42:00"}, "collected_at"),
            ({"collected_at": "2026-11-12"}, "collected_at"),
            ({"collected_at": "yesterday"}, "collected_at"),
            ({"details": {"number": {"nested": "x"}}}, "details.number"),
            ({"details": {"number": ["1"]}}, "details.number"),
            ({"details": "flat"}, "details"),
        ],
    )
    def test_api_08_shape_errors(self, desk, pending, change, field):
        response = desk.post(url("confirm", pending), confirm_body(**change), format="json")
        assert response.status_code == 400, response.content
        fields = [error.get("field") for error in response.json()["errors"]]
        assert field in fields
        assert all(error["code"].startswith("E00") for error in response.json()["errors"])

    def test_missing_fields(self, desk, pending):
        response = desk.post(url("confirm", pending), {}, format="json")
        assert {e["field"] for e in response.json()["errors"]} == {
            "amount",
            "method",
            "receipt_number",
        }

    def test_api_09_details_invalid(self, desk, pending):
        assert_error(
            desk.post(url("confirm", pending), confirm_body(amount="37.49"), format="json"),
            errors.COLLECTION_DETAILS_INVALID,
            "amount",
        )

    def test_api_09_collector_is_payer(self, pending, user, grant):
        payer = client_for(grant(user, "record_payment_collection"))
        assert_error(
            payer.post(url("confirm", pending), confirm_body(), format="json"),
            errors.COLLECTOR_IS_PAYER,
        )

    def test_api_09_not_open(self, desk, pending):
        PaymentService.cancel_payment(pending)
        assert_error(
            desk.post(url("confirm", pending), confirm_body(), format="json"),
            errors.COLLECTION_NOT_OPEN,
        )

    def test_api_09_receipt_used(self, desk, make_request):
        first, second = make_request(), make_request()
        desk.post(url("confirm", first), confirm_body(), format="json")
        assert_error(
            desk.post(url("confirm", second), confirm_body(), format="json"),
            errors.RECEIPT_NUMBER_USED,
            "receipt_number",
        )

    def test_api_09_rejected(self, desk, pending):
        from apps.payments.providers.base import ProviderPermanentError

        FakeAttestedProvider.attest_error = ProviderPermanentError("EXPIRED")
        assert_error(
            desk.post(url("confirm", pending), confirm_body(), format="json"),
            errors.COLLECTION_REJECTED,
        )

    def test_late_needs_the_late_permission(self, pending, make_user, grant):
        PaymentService.fail_payment(pending, failure_code="EXPIRED")
        recorder = client_for(grant(make_user("Recorder"), "record_payment_collection"))
        assert_error(
            recorder.post(url("confirm", pending), confirm_body(late=True), format="json"),
            api_errors.PERMISSION_DENIED,
        )
        assert not PaymentAttestation.objects.exists()

    def test_late_with_the_permission(self, desk, pending):
        PaymentService.fail_payment(pending, failure_code="EXPIRED")
        response = desk.post(url("confirm", pending), confirm_body(late=True), format="json")
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["status"] == PaymentStatus.FAILED
        assert body["attestation"]["outcome"] == AttestationOutcome.FLAGGED

    def test_api_14_payer_sees_the_receipt_not_the_recorder(self, api, desk, pending, clerk):
        desk.post(url("confirm", pending), confirm_body(), format="json")
        body = api.get(reverse("payments-payment-detail", kwargs={"payment_id": pending.pk})).json()
        assert body["status"] == PaymentStatus.SUCCESS
        assert body["provider_reference"] == "CJM/EKM/2026/004512"
        assert set(body["attestation"]) == {"receipt_number", "method", "collected_at"}
        assert "Suresh" not in str(body["attestation"])
        assert str(clerk.pk) not in str(body["attestation"])

    def test_payer_list_shows_the_attestation(self, api, desk, pending):
        desk.post(url("confirm", pending), confirm_body(), format="json")
        rows = api.get(
            reverse("payments-demand-payments", kwargs={"demand_id": pending.demand_id})
        ).json()["results"]
        assert rows[0]["attestation"]["receipt_number"] == "CJM/EKM/2026/004512"


class TestCancel:
    def test_cancel(self, desk, pending, clerk):
        response = desk.post(url("cancel", pending), {"reason": "Pays online"}, format="json")
        assert response.status_code == 200, response.content
        assert response.json()["status"] == PaymentStatus.CANCELLED
        pending.refresh_from_db()
        assert pending.failure_message == "Pays online"
        assert pending.updated_by == clerk

    def test_lif_06_reason_required(self, desk, pending):
        assert_error(
            desk.post(url("cancel", pending), {}, format="json"), api_errors.REQUIRED, "reason"
        )
        assert_error(
            desk.post(url("cancel", pending), {"reason": "x" * 256}, format="json"),
            api_errors.MAX_LENGTH,
            "reason",
        )

    def test_lif_07_terminal(self, desk, pending):
        PaymentService.confirm_payment(pending)
        assert_error(
            desk.post(url("cancel", pending), {"reason": "x"}, format="json"),
            errors.PAYMENT_NOT_CANCELLABLE,
        )


class TestList:
    def test_api_10_one_row_per_request_newest_first(
        self, desk, raise_demand, user, attested_provider, make_request
    ):
        demands = [raise_demand([item()], reference_id=f"b{n}") for n in range(3)]
        PaymentService.create_batch(
            selections=[{"demand": d, "demand_item_ids": item_ids(d)} for d in demands],
            client_request_id="batch",
            provider="counter",
            actor=user,
        )
        older = make_request()
        Payment.objects.filter(pk=older.pk).update(initiated_at=timezone.now() - timedelta(days=1))
        body = desk.get(LIST).json()
        assert body["count"] == 2 and "meta" in body
        batch_row, single_row = body["results"]
        assert len(batch_row["payments"]) == 3
        assert batch_row["amount"] == "37.50"
        assert "items" not in batch_row["payments"][0]
        assert single_row["reference"] == older.provider_payment_id

    def test_api_10_filters(self, desk, make_request):
        first, second = make_request(), make_request()
        PaymentService.cancel_payment(second)
        assert [
            r["reference"] for r in desk.get(LIST, {"status": "PENDING"}).json()["results"]
        ] == [first.provider_payment_id]
        assert desk.get(LIST, {"status": "BOGUS"}).status_code == 400
        today = timezone.now().date().isoformat()
        assert desk.get(LIST, {"initiated_from": today}).json()["count"] >= 1
        assert desk.get(LIST, {"initiated_to": "2000-01-01"}).json()["count"] == 0

    @pytest.mark.parametrize("by", ["reference", "lower", "payment", "demand", "case", "payer"])
    def test_api_10_search(self, desk, make_request, make_case, by):
        target = make_request(payer={"name": "Unique Payer"}, case=make_case())
        make_request()
        case = target.demand.case
        case.filing_number = "F-KL-2026-000789"
        case.save()
        term = {
            "reference": target.provider_payment_id,
            "lower": target.provider_payment_id.lower(),
            "payment": target.payment_number,
            "demand": target.demand.demand_number,
            "case": "000789",
            "payer": "unique pay",
        }[by]
        rows = desk.get(LIST, {"search": term}).json()["results"]
        assert [r["reference"] for r in rows] == [target.provider_payment_id]

    def test_search_with_a_bad_reference_is_an_empty_page(self, desk, pending):
        response = desk.get(LIST, {"search": "CTR"})
        assert response.status_code == 200
        assert response.json()["count"] == 0

    def test_search_with_an_unknown_provider_filter(self, desk, pending):
        response = desk.get(LIST, {"provider": "ghost", "search": pending.provider_payment_id})
        assert response.status_code == 200 and response.json()["count"] == 0

    def test_api_11_never_lists_gateway_payments(self, desk, make_request):
        make_request(provider="fake")
        make_request()
        rows = desk.get(LIST).json()["results"]
        assert {r["provider"] for r in rows} == {"counter"}
        assert desk.get(LIST, {"provider": "fake"}).json()["count"] == 0


class TestRegister:
    def record(self, payment, actor, receipt, method="CASH", collected_at=None, details=None):
        return PaymentService.record_collection(
            provider="counter",
            provider_payment_id=payment.provider_payment_id,
            amount=payment.amount,
            method=method,
            receipt_number=receipt,
            collected_at=collected_at or timezone.now(),
            details=details or {},
            actor=actor,
        )

    def test_api_12_rows_totals_and_filters(self, desk, make_request, clerk, make_user, grant):
        other = grant(make_user("Other"), "record_payment_collection")
        a, b, c = make_request(), make_request(), make_request()
        # IST day boundary: 12 Nov 2026 runs 11 Nov 18:30 UTC – 12 Nov 18:30 UTC.
        for payment in (a, b, c):
            Payment.objects.filter(pk=payment.pk).update(
                initiated_at=datetime(2026, 11, 11, 0, 0, tzinfo=UTC)
            )
        self.record(a, clerk, "R1", collected_at=datetime(2026, 11, 11, 18, 30, tzinfo=UTC))
        self.record(
            b,
            clerk,
            "R2",
            method="DD",
            details={"number": "123456"},
            collected_at=datetime(2026, 11, 12, 18, 29, tzinfo=UTC),
        )
        self.record(c, other, "R3", collected_at=datetime(2026, 11, 12, 18, 30, tzinfo=UTC))

        body = desk.get(REGISTER, {"collected_on": "2026-11-12"}).json()
        assert body["count"] == 2 and "meta" in body
        assert [r["receipt_number"] for r in body["results"]] == ["R2", "R1"]
        row = body["results"][0]
        assert row["reference"] == b.provider_payment_id
        assert row["payment_numbers"] == [b.payment_number]
        assert row["recorded_by"]["name"] == "Suresh K"
        assert row["outcome"] == AttestationOutcome.CREDITED
        assert body["totals"] == [
            {"method": "CASH", "count": 1, "amount": "37.50"},
            {"method": "DD", "count": 1, "amount": "37.50"},
        ]

        mine = desk.get(REGISTER, {"recorded_by": str(other.pk)}).json()
        assert [r["receipt_number"] for r in mine["results"]] == ["R3"]
        cash = desk.get(REGISTER, {"method": "cash"}).json()
        assert cash["count"] == 2
        assert cash["totals"] == [{"method": "CASH", "count": 2, "amount": "75.00"}]
        assert desk.get(REGISTER, {"provider": "fake"}).json()["count"] == 0
        assert desk.get(REGISTER, {"collected_on": "12-11-2026"}).status_code == 400

    def test_outcome_filter(self, desk, make_request, clerk):
        credited, flagged = make_request(), make_request()
        self.record(credited, clerk, "R1")
        PaymentService.cancel_payment(flagged)
        PaymentService.record_collection(
            provider="counter",
            provider_payment_id=flagged.provider_payment_id,
            amount=flagged.amount,
            method="CASH",
            receipt_number="R2",
            collected_at=timezone.now(),
            late=True,
            actor=clerk,
        )
        body = desk.get(REGISTER, {"outcome": "FLAGGED"}).json()
        assert [r["receipt_number"] for r in body["results"]] == ["R2"]
        assert body["results"][0]["outcome"] == AttestationOutcome.FLAGGED

    def test_empty_register(self, desk):
        body = desk.get(REGISTER).json()
        assert body["count"] == 0 and body["totals"] == []


class TestMethods:
    def test_api_13_methods(self, desk, attested_provider):
        body = desk.get(METHODS, {"provider": "counter"}).json()
        assert body["provider"] == "counter"
        assert [m["code"] for m in body["methods"]] == ["CASH", "DD"]
        assert body["methods"][1]["fields"] == [
            {
                "key": "number",
                "label": "DD number",
                "kind": "digits",
                "required": True,
                "max_length": 6,
            }
        ]

    def test_api_13_gateway_or_missing_provider(self, desk, attested_provider):
        assert_error(desk.get(METHODS, {"provider": "fake"}), api_errors.NOT_FOUND)
        assert_error(desk.get(METHODS), api_errors.REQUIRED, "provider")


class TestThrottle:
    def test_api_16_failed_lookups_are_throttled(self, desk, pending, settings):
        from django.core.cache import cache

        cache.clear()
        settings.PAYMENT_COLLECTION_LOOKUP_THROTTLE_RATE = "3/min"
        try:
            for _ in range(3):
                assert desk.get(url("detail", "CTR-000000000000")).status_code == 404
            assert_error(desk.get(url("detail", pending)), api_errors.THROTTLED)
        finally:
            cache.clear()

    def test_old_failures_leave_the_window(self, desk, settings):
        from django.core.cache import cache

        cache.clear()
        settings.PAYMENT_COLLECTION_LOOKUP_THROTTLE_RATE = "2/min"
        try:
            with mock.patch("time.time", return_value=1_000_000.0):
                for _ in range(2):
                    desk.get(url("detail", "CTR-000000000000"))
            with mock.patch("time.time", return_value=1_000_100.0):
                assert desk.get(url("detail", "CTR-000000000000")).status_code == 404
        finally:
            cache.clear()

    def test_successful_lookups_are_not_counted(self, desk, pending, settings):
        from django.core.cache import cache

        cache.clear()
        settings.PAYMENT_COLLECTION_LOOKUP_THROTTLE_RATE = "2/min"
        try:
            for _ in range(5):
                assert desk.get(url("detail", pending)).status_code == 200
        finally:
            cache.clear()


def test_api_15_schema(attested_provider):
    schema = SchemaGenerator().get_schema(request=None, public=True)
    paths = schema["paths"]
    expected = {
        "/api/v1/payments/providers/": "get",
        "/api/v1/payments/payments/{payment_id}/action/": "get",
        "/api/v1/payments/collections/": "get",
        "/api/v1/payments/collections/methods/": "get",
        "/api/v1/payments/collections/register/": "get",
        "/api/v1/payments/collections/{provider}/{reference}/": "get",
        "/api/v1/payments/collections/{provider}/{reference}/confirm/": "post",
        "/api/v1/payments/collections/{provider}/{reference}/cancel/": "post",
    }
    for path, method in expected.items():
        assert path in paths, path
        assert paths[path][method]["tags"] == ["payments"], path
    confirm = str(paths["/api/v1/payments/collections/{provider}/{reference}/confirm/"])
    for code in ("E06024", "E06025", "E06026", "E06027", "E06028"):
        assert code in confirm
    components = schema["components"]["schemas"]
    assert "details" in components["ProviderAction"]["properties"]
    assert "attestation" in components["Payment"]["properties"]
