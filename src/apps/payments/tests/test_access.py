"""Who may see and pay a demand (spec 0017 #13, #18 "Case access").

Access follows ``Demand.case``: the filer, active complainants, accused and POA
holders, and advocates with an active representation on the case. Everyone
else, witnesses included, gets 404.
"""

from datetime import timedelta

import pytest
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.api import errors as api_errors
from apps.cases.models import ParticipantRole, Representation
from apps.payments import access
from apps.users.models import AdvocateProfile, ApprovalStatus

from .helpers import assert_error, item, item_ids

pytestmark = pytest.mark.django_db


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def detail_url(demand):
    return reverse("payments-demand-detail", kwargs={"demand_id": demand.pk})


def pay_url(demand):
    return reverse("payments-demand-payments", kwargs={"demand_id": demand.pk})


def pay_body(demand, key="k"):
    return {"client_request_id": key, "demand_item_ids": [str(i) for i in item_ids(demand)]}


def sees(user, demand) -> bool:
    return access.visible_demands(user).filter(pk=demand.pk).exists()


@pytest.fixture
def advocate_on(make_user, involve):
    """An approved advocate representing a complainant on the given case."""

    def factory(case_id, **representation):
        advocate = make_user("Advocate")
        profile = AdvocateProfile.objects.create(
            user=advocate,
            bar_registration_id=f"KER/{advocate.pk.hex[:8]}",
            approval_status=ApprovalStatus.ACCEPTED,
        )
        client = involve(make_user("Client"), case_id)
        Representation.objects.create(
            case_id=case_id, advocate=profile, case_participant=client, **representation
        )
        return advocate

    return factory


class TestWhoIsInvolved:
    def test_the_filer(self, raise_demand, user):
        assert sees(user, raise_demand())

    @pytest.mark.parametrize(
        "role",
        [ParticipantRole.COMPLAINANT, ParticipantRole.ACCUSED, ParticipantRole.POA_HOLDER],
    )
    def test_parties_and_poa_holders(self, raise_demand, make_user, involve, role):
        demand = raise_demand()
        party = make_user("Party")
        involve(party, demand.case_id, role)
        assert sees(party, demand)

    def test_an_advocate_on_the_case(self, raise_demand, advocate_on):
        demand = raise_demand()
        assert sees(advocate_on(demand.case_id), demand)

    def test_witnesses_are_not_involved(self, raise_demand, make_user, involve):
        demand = raise_demand()
        witness = make_user("Witness")
        involve(witness, demand.case_id, ParticipantRole.WITNESS)
        assert not sees(witness, demand)

    def test_user_id_alone_grants_nothing(self, raise_demand, make_user):
        """``Demand.user_id`` is informational; access follows the case."""
        party = make_user("Directed party")
        assert not sees(party, raise_demand(user_id=party.pk))

    def test_anonymous_sees_nothing(self, raise_demand, case_id):
        raise_demand()
        assert not access.visible_demands(AnonymousUser()).exists()
        assert not access.can_raise_on_case(AnonymousUser(), case_id)


class TestLeavingTheCase:
    def test_a_removed_participant_loses_access(self, raise_demand, make_user, involve):
        demand = raise_demand()
        party = make_user("Party")
        participant = involve(party, demand.case_id)
        participant.is_active = False
        participant.end_date = timezone.now()
        participant.save()
        assert not sees(party, demand)

    def test_an_ended_participation_loses_access(self, raise_demand, make_user, involve):
        demand = raise_demand()
        party = make_user("Party")
        participant = involve(party, demand.case_id)
        participant.end_date = timezone.now() - timedelta(minutes=1)
        participant.save()
        assert not sees(party, demand)

    def test_an_ended_representation_loses_access(self, raise_demand, advocate_on):
        demand = raise_demand()
        advocate = advocate_on(demand.case_id, to_date=timezone.now() - timedelta(days=1))
        assert not sees(advocate, demand)

    def test_payments_they_made_go_with_it(self, raise_demand, make_user, involve):
        demand = raise_demand()
        party = make_user("Party")
        participant = involve(party, demand.case_id)
        payment_id = (
            client_for(party).post(pay_url(demand), pay_body(demand), format="json").json()["id"]
        )
        participant.is_active = False
        participant.save()
        response = client_for(party).get(
            reverse("payments-payment-detail", kwargs={"payment_id": payment_id})
        )
        assert_error(response, api_errors.NOT_FOUND)


class TestOverTheApi:
    def test_anyone_involved_can_see_and_pay(self, raise_demand, user, make_user, involve):
        demand = raise_demand()
        accused = make_user("Accused")
        involve(accused, demand.case_id, ParticipantRole.ACCUSED)

        assert client_for(accused).get(detail_url(demand)).status_code == 200
        response = client_for(accused).post(pay_url(demand), pay_body(demand), format="json")
        assert response.status_code == 201
        # The filer sees the accused's payment too.
        payment_id = response.json()["id"]
        detail = client_for(user).get(
            reverse("payments-payment-detail", kwargs={"payment_id": payment_id})
        )
        assert detail.status_code == 200

    def test_two_participants_pay_different_items(self, raise_demand, user, make_user, involve):
        """Spec 0017 #13/#18: several involved users may pay items of one demand."""
        from apps.payments.models import Demand
        from apps.payments.services import PaymentService

        demand = raise_demand()
        accused = make_user("Accused")
        involve(accused, demand.case_id, ParticipantRole.ACCUSED)
        first, *rest = (str(i) for i in item_ids(demand))

        for who, ids, key in ((user, [first], "filer"), (accused, rest, "accused")):
            body = {"client_request_id": key, "demand_item_ids": ids}
            response = client_for(who).post(pay_url(demand), body, format="json")
            assert response.status_code == 201, response.content
            PaymentService.refresh_from_provider(
                demand.payments.get(pk=response.json()["id"])
            )  # the mock provider reports success

        demand = Demand.objects.get(pk=demand.pk)
        assert demand.status == "PAID"
        assert {p.created_by for p in demand.payments.all()} == {user, accused}

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
            outsider.get(detail_url(demand)),
            outsider.post(pay_url(demand), pay_body(demand, key="x"), format="json"),
            outsider.get(pay_url(demand)),
            outsider.post(reverse("payments-demand-cancel", kwargs={"demand_id": demand.pk}), {}),
            outsider.get(reverse("payments-payment-detail", kwargs={"payment_id": payment_id})),
            outsider.post(
                reverse("payments-payment-cancel", kwargs={"payment_id": payment_id}), {}
            ),
        ):
            assert_error(response, api_errors.NOT_FOUND)

    def test_raising_needs_involvement_in_the_case(self, other_user, case_id):
        body = {
            "case_id": str(case_id),
            "reference_type": "ORDER",
            "reference_id": "o",
            "items": [{"charge_type": "COST", "description": "c", "unit_amount": "10.00"}],
        }
        response = client_for(other_user).post(reverse("payments-demand-list"), body, format="json")
        assert_error(response, api_errors.NOT_FOUND)

    def test_batch_with_a_demand_on_a_foreign_case_is_rejected(
        self, raise_demand, user, other_user, make_case
    ):
        mine = raise_demand([item()])
        theirs = raise_demand([item()], actor=other_user, case=make_case(created_by=other_user))
        body = {
            "client_request_id": "b",
            "selections": [
                {"demand_id": str(d.pk), "demand_item_ids": [str(i) for i in item_ids(d)]}
                for d in (mine, theirs)
            ],
        }
        response = client_for(user).post(reverse("payments-batch-list"), body, format="json")
        assert_error(response, api_errors.NOT_FOUND)

    def test_batch_across_the_callers_cases_is_allowed(self, raise_demand, user, make_case):
        """A bulk filer pays for demands on several cases at once."""
        demands = [raise_demand([item()], case=make_case()) for _ in range(2)]
        body = {
            "client_request_id": "b",
            "selections": [
                {"demand_id": str(d.pk), "demand_item_ids": [str(i) for i in item_ids(d)]}
                for d in demands
            ],
        }
        response = client_for(user).post(reverse("payments-batch-list"), body, format="json")
        assert response.status_code == 201
