"""Who may see and pay a demand (spec 0017 #13, #18 "Case access").

TODO(case-person-relationship): these tests pin the TEMPORARY rule in
``apps/payments/access.py`` (creator or ``user_id`` party). When
``CasePersonRelationship`` lands, rewrite them against the spec's rule —
anyone with an active relationship on the case — and drop the tests marked
"temporary" below.
"""

import uuid

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.api import errors as api_errors
from apps.payments import access

from .helpers import assert_error, item, item_ids

pytestmark = pytest.mark.django_db


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def pay_url(demand):
    return reverse("payments-demand-payments", kwargs={"demand_id": demand.pk})


def pay_body(demand, key="k"):
    return {"client_request_id": key, "demand_item_ids": [str(i) for i in item_ids(demand)]}


class TestVisibility:
    def test_creator_and_directed_party_can_see_and_pay(self, raise_demand, user, make_user):
        party = make_user("Directed party")
        demand = raise_demand(user_id=party.pk)
        for who in (user, party):
            client = client_for(who)
            assert (
                client.get(
                    reverse("payments-demand-detail", kwargs={"demand_id": demand.pk})
                ).status_code
                == 200
            )
            assert client.get(reverse("payments-demand-list")).json()["count"] == 1

        response = client_for(party).post(pay_url(demand), pay_body(demand), format="json")
        assert response.status_code == 201
        # The creator sees the party's payment too.
        payment_id = response.json()["id"]
        detail = client_for(user).get(
            reverse("payments-payment-detail", kwargs={"payment_id": payment_id})
        )
        assert detail.status_code == 200

    def test_outsider_gets_404_everywhere(self, raise_demand, other_user):
        demand = raise_demand()
        payment_id = (
            client_for(demand.created_by)
            .post(pay_url(demand), pay_body(demand), format="json")
            .json()["id"]
        )
        outsider = client_for(other_user)

        assert outsider.get(reverse("payments-demand-list")).json()["count"] == 0
        for response in (
            outsider.get(reverse("payments-demand-detail", kwargs={"demand_id": demand.pk})),
            outsider.post(pay_url(demand), pay_body(demand, key="x"), format="json"),
            outsider.get(pay_url(demand)),
            outsider.post(reverse("payments-demand-cancel", kwargs={"demand_id": demand.pk}), {}),
            outsider.get(reverse("payments-payment-detail", kwargs={"payment_id": payment_id})),
            outsider.post(
                reverse("payments-payment-cancel", kwargs={"payment_id": payment_id}), {}
            ),
        ):
            assert_error(response, api_errors.NOT_FOUND)

    def test_batch_with_a_foreign_demand_is_rejected(self, raise_demand, user, other_user):
        mine = raise_demand([item()])
        theirs = raise_demand([item()], actor=other_user)
        body = {
            "client_request_id": "b",
            "selections": [
                {"demand_id": str(d.pk), "demand_item_ids": [str(i) for i in item_ids(d)]}
                for d in (mine, theirs)
            ],
        }
        response = client_for(user).post(reverse("payments-batch-list"), body, format="json")
        assert_error(response, api_errors.NOT_FOUND)

    def test_batch_across_cases_is_allowed(self, raise_demand, user):
        """A bulk filer pays for demands on several cases at once."""
        demands = [raise_demand([item()], case=uuid.uuid4()) for _ in range(2)]
        body = {
            "client_request_id": "b",
            "selections": [
                {"demand_id": str(d.pk), "demand_item_ids": [str(i) for i in item_ids(d)]}
                for d in demands
            ],
        }
        assert (
            client_for(user).post(reverse("payments-batch-list"), body, format="json").status_code
            == 201
        )


class TestTemporaryRule:
    """TODO(case-person-relationship): temporary behaviour, replace with the spec's rule."""

    def test_another_participant_on_the_same_case_does_not_see_it_yet(
        self, raise_demand, make_user, case_id
    ):
        # Under spec 0017 #13 a co-participant on the case would see this demand.
        demand = raise_demand()
        co_participant = make_user("Co-advocate")
        assert not access.visible_demands(co_participant).filter(pk=demand.pk).exists()

    def test_any_case_id_may_be_used_to_raise_over_rest(self, user):
        # Under spec 0017 #13 the caller must be involved in the case.
        assert access.can_raise_on_case(user, uuid.uuid4())

    def test_anonymous_sees_nothing(self, raise_demand):
        from django.contrib.auth.models import AnonymousUser

        raise_demand()
        assert not access.visible_demands(AnonymousUser()).exists()
        assert not access.can_raise_on_case(AnonymousUser(), uuid.uuid4())
