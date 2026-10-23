"""REST endpoints (spec 0017 #12, #18 "API").

Error tests assert the code and field, never the message (spec 0000 #13).
"""

import uuid

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.api import errors as api_errors
from apps.payments import errors
from apps.payments.enums import DemandStatus, PaymentStatus
from apps.payments.models import Demand, Payment
from apps.payments.services import PaymentService

from .helpers import assert_error, item, item_ids

pytestmark = pytest.mark.django_db

DEMANDS = reverse("payments-demand-list")
BATCHES = reverse("payments-batch-list")
OPTIONS = reverse("payments-provider-options")


def demand_url(demand, suffix="detail", **kwargs):
    return reverse(f"payments-demand-{suffix}", kwargs={"demand_id": demand.pk, **kwargs})


def payment_url(payment, suffix="detail"):
    return reverse(f"payments-payment-{suffix}", kwargs={"payment_id": payment.pk})


def strs(ids):
    return [str(i) for i in ids]


def demand_body(case_id, **overrides):
    body = {
        "case_id": str(case_id),
        "reference_type": "CASE_FILING",
        "reference_id": "filing-456",
        "items": [
            {
                "charge_type": "COURT_FEE",
                "description": "Court Fee",
                "quantity": "1",
                "unit_amount": "12.50",
            },
            {
                "charge_type": "PROCESS_COURT_FEE",
                "description": "Summons — Accused 1",
                "quantity": "2",
                "unit_amount": "12.50",
                "metadata": {
                    "accused_id": "accused-1",
                    "quantity_breakdown": {"addresses": 2, "rounds": 1},
                },
            },
        ],
        "metadata": {"court_id": "court-kl-ekm-01"},
    }
    body.update(overrides)
    return body


def pay_body(ids, key="attempt-1", **extra):
    return {"client_request_id": key, "demand_item_ids": strs(ids), **extra}


class TestRaiseDemand:
    def test_created_with_server_computed_fields(self, api, user, case_id):
        response = api.post(DEMANDS, demand_body(case_id), format="json")
        assert response.status_code == 201, response.content
        body = response.json()
        assert "meta" in body
        assert body["demand_number"].startswith("DMD-")
        assert body["status"] == "RAISED"
        assert body["total_amount"] == body["due_amount"] == "37.50"
        assert body["paid_amount"] == "0.00"
        assert body["user_id"] == str(user.pk)
        assert body["created_by"]["id"] == str(user.pk)
        assert [i["amount"] for i in body["items"]] == ["12.50", "25.00"]
        assert body["payment_summary"]["count"] == 0

    def test_client_cannot_set_balances_or_status(self, api, case_id):
        body = demand_body(
            case_id,
            status="PAID",
            paid_amount="37.50",
            demand_number="DMD-X",
            user_id=str(uuid.uuid4()),
        )
        body["items"][0].update(status="PAID", paid_amount="12.50", amount="1.00")
        created = api.post(DEMANDS, body, format="json").json()
        assert created["status"] == "RAISED"
        assert created["paid_amount"] == "0.00"
        assert created["demand_number"] != "DMD-X"
        assert created["items"][0]["amount"] == "12.50"

    def test_case_id_is_required(self, api, case_id):
        body = demand_body(case_id)
        del body["case_id"]
        assert_error(api.post(DEMANDS, body, format="json"), api_errors.REQUIRED, "case_id")

    def test_empty_items(self, api, case_id):
        response = api.post(DEMANDS, demand_body(case_id, items=[]), format="json")
        assert_error(response, api_errors.EMPTY, "items")

    def test_breakdown_mismatch(self, api, case_id):
        body = demand_body(case_id)
        body["items"][1]["quantity"] = "3"
        response = api.post(DEMANDS, body, format="json")
        assert_error(response, errors.QUANTITY_BREAKDOWN_MISMATCH, "items[1].metadata")

    @pytest.mark.parametrize("field,value", [("quantity", "0"), ("unit_amount", "-1")])
    def test_non_positive_numbers(self, api, case_id, field, value):
        body = demand_body(case_id)
        body["items"][0][field] = value
        response = api.post(DEMANDS, body, format="json")
        assert_error(response, api_errors.MIN_VALUE, f"items[0].{field}")

    def test_money_is_never_a_float(self, api, case_id):
        body = demand_body(case_id)
        body["items"][0]["unit_amount"] = "12.505"
        response = api.post(DEMANDS, body, format="json")
        assert_error(response, api_errors.TOO_MANY_DIGITS, "items[0].unit_amount")

    def test_anonymous_is_refused(self, case_id):
        response = APIClient().post(DEMANDS, demand_body(case_id), format="json")
        assert response.status_code == 403
        assert response.json()["errors"][0]["code"] == api_errors.NOT_AUTHENTICATED.code


class TestListAndRetrieve:
    def test_list_is_paginated_newest_first_and_filtered(self, api, raise_demand, case_id):
        older = raise_demand([item()], reference_id="a")
        newer = raise_demand([item()], reference_id="b")
        raise_demand([item()], case=uuid.uuid4())

        body = api.get(DEMANDS).json()
        assert body["count"] == 3 and "meta" in body
        assert body["results"][0]["id"] == str(Demand.objects.latest("created_at").pk)

        filtered = api.get(DEMANDS, {"case_id": str(case_id), "reference_id": "a"}).json()
        assert [r["id"] for r in filtered["results"]] == [str(older.pk)]

        PaymentService.confirm_payment(
            PaymentService.create_payment(
                demand=newer,
                demand_item_ids=item_ids(newer),
                client_request_id="k",
                actor=newer.created_by,
            ).payment
        )
        paid = api.get(DEMANDS, {"status": "PAID"}).json()
        assert [r["id"] for r in paid["results"]] == [str(newer.pk)]

    def test_invalid_filter(self, api):
        assert_error(api.get(DEMANDS, {"status": "SOMETIMES"}), api_errors.INVALID_CHOICE, "status")

    def test_retrieve_has_items_and_payment_summary(self, api, raise_demand):
        demand = raise_demand()
        api.post(demand_url(demand, "payments"), pay_body(item_ids(demand, 0)), format="json")
        body = api.get(demand_url(demand)).json()
        assert len(body["items"]) == 3
        assert body["payment_summary"] == {
            "count": 1,
            "successful": 0,
            "in_flight": 1,
            "failed": 0,
            "cancelled": 0,
        }


class TestCancelDemand:
    def test_only_the_creator_can_cancel(self, raise_demand, make_user):
        """The party a demand is raised on can see and pay it, not cancel it (spec 0017 #13)."""
        party = make_user("Directed party")
        demand = raise_demand(user_id=party.pk)
        [first] = item_ids(demand, 0)
        party_api = APIClient()
        party_api.force_authenticate(party)

        assert_error(party_api.post(demand_url(demand, "cancel"), {}), errors.NOT_DEMAND_CREATOR)
        response = party_api.post(demand_url(demand, "cancel-item", item_id=first), {})
        assert_error(response, errors.NOT_DEMAND_CREATOR)
        demand.refresh_from_db()
        assert demand.status == DemandStatus.RAISED
        assert set(demand.items.values_list("status", flat=True)) == {"UNPAID"}

    def test_system_raised_demand_cannot_be_cancelled_over_rest(self, make_user, case_id):
        """No creator user: only the raising module cancels it, in-process."""
        from apps.payments.services import DemandService

        party = make_user("Directed party")
        demand = DemandService.raise_demand(
            case=case_id,
            reference_type="ORDER",
            reference_id="order-1",
            items=[item()],
            user_id=party.pk,
        )
        party_api = APIClient()
        party_api.force_authenticate(party)
        assert_error(party_api.post(demand_url(demand, "cancel"), {}), errors.NOT_DEMAND_CREATOR)

    def test_cancel_demand(self, api, raise_demand):
        demand = raise_demand()
        response = api.post(
            demand_url(demand, "cancel"), {"reason": "draft deleted"}, format="json"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"

    def test_cancel_item(self, api, raise_demand):
        demand = raise_demand()
        [first] = item_ids(demand, 0)
        response = api.post(demand_url(demand, "cancel-item", item_id=first), {}, format="json")
        assert response.status_code == 200
        body = response.json()
        assert body["total_amount"] == "25.00"
        assert body["items"][0]["status"] == "CANCELLED"

    def test_item_of_another_demand_is_404(self, api, raise_demand):
        demand, other = raise_demand(), raise_demand()
        [foreign] = item_ids(other, 0)
        response = api.post(demand_url(demand, "cancel-item", item_id=foreign), {}, format="json")
        assert_error(response, api_errors.NOT_FOUND)

    def test_paid_item_and_partly_paid_demand(self, api, raise_demand, user, no_provider):
        demand = raise_demand()
        [first] = item_ids(demand, 0)
        payment = PaymentService.create_payment(
            demand=demand, demand_item_ids=[first], client_request_id="k", actor=user
        ).payment
        PaymentService.confirm_payment(payment)
        response = api.post(demand_url(demand, "cancel-item", item_id=first), {}, format="json")
        assert_error(response, errors.ITEM_NOT_CANCELLABLE)
        assert_error(api.post(demand_url(demand, "cancel"), {}), errors.DEMAND_NOT_CANCELLABLE)


class TestCreatePayment:
    def test_created_pending_with_provider_action(self, api, raise_demand):
        demand = raise_demand()
        response = api.post(
            demand_url(demand, "payments"), pay_body(item_ids(demand, 0, 1)), format="json"
        )
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["status"] == "PENDING"
        assert body["amount"] == "25.00"
        assert body["provider"] == "mock"
        assert body["payment_number"].startswith("PAY-")
        assert [i["amount"] for i in body["items"]] == ["12.50", "12.50"]
        assert body["provider_action"]["kind"] == "REDIRECT_FORM"
        assert (
            body["provider_action"]["form_fields"]["provider_payment_id"]
            == body["provider_payment_id"]
        )
        assert "payer" not in body

    def test_replay_returns_200_with_the_same_action(self, api, raise_demand):
        demand = raise_demand()
        url = demand_url(demand, "payments")
        first = api.post(url, pay_body(item_ids(demand, 0)), format="json")
        again = api.post(url, pay_body(item_ids(demand, 0)), format="json")
        assert (first.status_code, again.status_code) == (201, 200)
        assert again.json()["id"] == first.json()["id"]
        assert again.json()["provider_action"] == first.json()["provider_action"]
        assert Payment.objects.count() == 1

    def test_idempotency_key_header(self, api, raise_demand):
        demand = raise_demand()
        url = demand_url(demand, "payments")
        body = {"demand_item_ids": strs(item_ids(demand, 0))}
        first = api.post(url, body, format="json", HTTP_IDEMPOTENCY_KEY="hdr-1")
        again = api.post(url, body, format="json", HTTP_IDEMPOTENCY_KEY="hdr-1")
        assert (first.status_code, again.status_code) == (201, 200)
        assert Payment.objects.get(pk=first.json()["id"]).client_request_id == "hdr-1"
        # The key is never echoed: anyone on the case can read a payment (spec 0017 #12.2).
        assert "client_request_id" not in first.json()

    def test_missing_key(self, api, raise_demand):
        demand = raise_demand()
        response = api.post(
            demand_url(demand, "payments"),
            {"demand_item_ids": strs(item_ids(demand))},
            format="json",
        )
        assert_error(response, api_errors.REQUIRED, "client_request_id")

    def test_key_reused_with_other_items(self, api, raise_demand):
        demand = raise_demand()
        url = demand_url(demand, "payments")
        api.post(url, pay_body(item_ids(demand, 0)), format="json")
        response = api.post(url, pay_body(item_ids(demand, 1)), format="json")
        assert_error(response, errors.CLIENT_REQUEST_ID_REUSED, "client_request_id")

    def test_duplicate_item(self, api, raise_demand):
        demand = raise_demand()
        [one] = item_ids(demand, 0)
        response = api.post(demand_url(demand, "payments"), pay_body([one, one]), format="json")
        assert_error(response, errors.DUPLICATE_DEMAND_ITEM, "demand_item_ids[1]")

    def test_empty_item_list(self, api, raise_demand):
        demand = raise_demand()
        response = api.post(demand_url(demand, "payments"), pay_body([]), format="json")
        assert_error(response, api_errors.EMPTY, "demand_item_ids")

    def test_item_not_in_demand(self, api, raise_demand):
        demand, other = raise_demand(), raise_demand()
        ids = [*item_ids(demand, 0), *item_ids(other, 0)]
        response = api.post(demand_url(demand, "payments"), pay_body(ids), format="json")
        assert_error(response, errors.ITEM_NOT_IN_DEMAND, "demand_item_ids[1]")

    def test_in_flight_item(self, api, raise_demand):
        demand = raise_demand()
        url = demand_url(demand, "payments")
        api.post(url, pay_body(item_ids(demand, 0), key="a"), format="json")
        response = api.post(url, pay_body(item_ids(demand, 1, 0), key="b"), format="json")
        assert_error(response, errors.PAYMENT_IN_FLIGHT, "demand_item_ids[1]")

    def test_paid_item_and_paid_demand(self, api, raise_demand, user):
        demand = raise_demand()
        url = demand_url(demand, "payments")
        api.post(url, pay_body(item_ids(demand, 0), key="a"), format="json")
        payment = Payment.objects.get()
        PaymentService.refresh_from_provider(payment)  # the mock says SUCCESS
        response = api.post(url, pay_body(item_ids(demand, 1, 0), key="b"), format="json")
        assert_error(response, errors.ITEM_NOT_PAYABLE, "demand_item_ids[1]")

        api.post(url, pay_body(item_ids(demand, 1, 2), key="c"), format="json")
        PaymentService.refresh_from_provider(Payment.objects.get(client_request_id="c"))
        response = api.post(url, pay_body(item_ids(demand, 0), key="d"), format="json")
        assert_error(response, errors.DEMAND_NOT_PAYABLE)

    def test_invalid_provider_option(self, api, raise_demand):
        demand = raise_demand()
        body = pay_body(item_ids(demand), provider_options={"outcome": "LATER"})
        response = api.post(demand_url(demand, "payments"), body, format="json")
        assert_error(response, errors.PROVIDER_OPTION_INVALID, "provider_options.outcome")

    def test_provider_rejection_and_outage(self, api, raise_demand, fake_provider):
        from apps.payments.providers.base import ProviderPermanentError, ProviderTransientError

        demand = raise_demand()
        url = demand_url(demand, "payments")
        fake_provider.initiate_error = ProviderPermanentError("NOPE")
        assert_error(
            api.post(url, pay_body(item_ids(demand), key="a"), format="json"),
            errors.PROVIDER_REJECTED,
        )
        fake_provider.initiate_error = ProviderTransientError("DOWN")
        assert_error(
            api.post(url, pay_body(item_ids(demand), key="b"), format="json"),
            errors.PROVIDER_UNAVAILABLE,
        )
        statuses = api.get(demand_url(demand, "payments")).json()["results"]
        assert [p["status"] for p in statuses] == ["FAILED", "FAILED"]

    def test_history(self, api, raise_demand):
        demand = raise_demand()
        url = demand_url(demand, "payments")
        api.post(url, pay_body(item_ids(demand, 0), key="a"), format="json")
        api.post(url, pay_body(item_ids(demand, 1), key="b"), format="json")
        body = api.get(url).json()
        assert body["count"] == 2 and "meta" in body
        keys = [Payment.objects.get(pk=p["id"]).client_request_id for p in body["results"]]
        assert keys == ["b", "a"]


class TestPaymentEndpoints:
    def created(self, api, demand, outcome="SUCCESS", key="k"):
        body = pay_body(item_ids(demand), key=key, provider_options={"outcome": outcome})
        response = api.post(demand_url(demand, "payments"), body, format="json")
        return Payment.objects.get(pk=response.json()["id"])

    def test_retrieve(self, api, raise_demand):
        payment = self.created(api, raise_demand())
        body = api.get(payment_url(payment)).json()
        assert body["id"] == str(payment.pk) and "meta" in body
        assert body["demand_number"] == payment.demand.demand_number
        assert len(body["items"]) == 3

    def test_cancel_when_provider_never_saw_it(self, api, raise_demand):
        payment = self.created(api, raise_demand(), outcome="NOT_FOUND")
        response = api.post(
            payment_url(payment, "cancel"), {"reason": "changed mind"}, format="json"
        )
        assert response.status_code == 200, response.content
        assert response.json()["status"] == "CANCELLED"

    def test_cancel_when_provider_already_failed(self, api, raise_demand):
        payment = self.created(api, raise_demand(), outcome="FAILED")
        assert api.post(payment_url(payment, "cancel"), {}).json()["status"] == "CANCELLED"

    def test_cancel_while_provider_may_complete(self, api, raise_demand):
        payment = self.created(api, raise_demand(), outcome="PENDING")
        assert_error(api.post(payment_url(payment, "cancel"), {}), errors.PAYMENT_OUTCOME_PENDING)
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.PENDING

    def test_cancel_finds_it_already_paid(self, api, raise_demand):
        payment = self.created(api, raise_demand(), outcome="SUCCESS")
        assert_error(api.post(payment_url(payment, "cancel"), {}), errors.PAYMENT_ALREADY_COMPLETED)
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.SUCCESS
        assert payment.demand.status == DemandStatus.PAID

    def test_cancel_terminal(self, api, raise_demand):
        payment = self.created(api, raise_demand(), outcome="FAILED")
        api.post(payment_url(payment, "cancel"), {})
        assert_error(api.post(payment_url(payment, "cancel"), {}), errors.PAYMENT_NOT_CANCELLABLE)

    def test_cancel_by_someone_else(self, raise_demand, user, make_user):
        payer = make_user("Payer")
        demand = raise_demand(user_id=payer.pk)
        payer_api = APIClient()
        payer_api.force_authenticate(payer)
        payment = self.created(payer_api, demand, outcome="PENDING")

        creator_api = APIClient()
        creator_api.force_authenticate(user)
        assert_error(
            creator_api.post(payment_url(payment, "cancel"), {}), errors.NOT_PAYMENT_CREATOR
        )

    def test_provider_unreachable_while_cancelling(self, api, raise_demand, fake_provider):
        from apps.payments.providers.base import ProviderTransientError

        demand = raise_demand()
        api.post(demand_url(demand, "payments"), pay_body(item_ids(demand)), format="json")
        fake_provider.fetch_error = ProviderTransientError("DOWN")
        assert_error(
            api.post(payment_url(Payment.objects.get(), "cancel"), {}), errors.PROVIDER_UNAVAILABLE
        )


class TestBatches:
    def demands(self, raise_demand, n=3):
        return [raise_demand([item(unit_amount="10.00")]) for _ in range(n)]

    def body(self, demands, key="batch-1", **extra):
        return {
            "client_request_id": key,
            "selections": [
                {"demand_id": str(d.pk), "demand_item_ids": strs(item_ids(d))} for d in demands
            ],
            **extra,
        }

    def test_create_and_retrieve(self, api, raise_demand):
        demands = self.demands(raise_demand)
        response = api.post(BATCHES, self.body(demands), format="json")
        assert response.status_code == 201, response.content
        body = response.json()
        assert body["amount"] == "30.00"
        assert body["status"] == "PENDING"
        assert body["provider_action"]["kind"] == "REDIRECT_FORM"
        assert len(body["payments"]) == 3
        assert len({p["payment_number"] for p in body["payments"]}) == 3
        assert len({p["provider_payment_id"] for p in body["payments"]}) == 1

        again = api.post(BATCHES, self.body(demands), format="json")
        assert again.status_code == 200
        assert again.json()["batch_id"] == body["batch_id"]

        detail = api.get(reverse("payments-batch-detail", kwargs={"batch_id": body["batch_id"]}))
        assert detail.status_code == 200
        assert detail.json()["provider_action"] is None
        assert len(detail.json()["payments"]) == 3

    def test_unknown_batch(self, api):
        response = api.get(reverse("payments-batch-detail", kwargs={"batch_id": uuid.uuid4()}))
        assert_error(response, api_errors.NOT_FOUND)

    def test_too_large(self, api, raise_demand, settings):
        settings.PAYMENT_BATCH_MAX_DEMANDS = 2
        response = api.post(BATCHES, self.body(self.demands(raise_demand)), format="json")
        assert_error(response, errors.BATCH_TOO_LARGE, "selections")

    def test_repeated_demand(self, api, raise_demand):
        [one] = self.demands(raise_demand, 1)
        response = api.post(BATCHES, self.body([one, one]), format="json")
        assert_error(response, errors.DEMAND_REPEATED_IN_BATCH, "selections[1].demand_id")

    def test_duplicate_item_in_a_selection(self, api, raise_demand):
        [one] = self.demands(raise_demand, 1)
        body = self.body([one])
        body["selections"][0]["demand_item_ids"] *= 2
        response = api.post(BATCHES, body, format="json")
        assert_error(response, errors.DUPLICATE_DEMAND_ITEM, "selections[0].demand_item_ids[1]")

    def test_not_payable_selection_names_its_field(self, api, raise_demand, user):
        demands = self.demands(raise_demand, 2)
        from apps.payments.services import DemandService

        DemandService.cancel_demand(demands[1])
        response = api.post(BATCHES, self.body(demands), format="json")
        assert_error(response, errors.DEMAND_NOT_PAYABLE, "selections[1].demand_id")

    def test_mixed_currency(self, api, raise_demand):
        demands = [raise_demand([item()]), raise_demand([item()], currency="USD")]
        assert_error(api.post(BATCHES, self.body(demands), format="json"), errors.CURRENCY_MISMATCH)


class TestProviderOptions:
    def test_mock_options(self, api):
        body = api.get(OPTIONS).json()
        assert body["provider"] == "mock"
        assert {o["code"] for o in body["options"]} == {"SUCCESS", "FAILED", "PENDING", "NOT_FOUND"}
        assert "meta" in body

    def test_no_provider(self, api, no_provider):
        assert api.get(OPTIONS).json()["options"] == []

    def test_misconfigured(self, api, settings):
        settings.PAYMENT_DEFAULT_PROVIDER = "ghost"
        assert_error(api.get(OPTIONS), errors.PROVIDER_UNAVAILABLE)
