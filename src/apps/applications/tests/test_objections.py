"""Objections (spec 0033 #9, #17.6)."""

import datetime

import pytest

from apps.applications.models import Application
from apps.applications.services import objections
from apps.payments.models import Demand

from .factories import (
    client_for,
    codes_of,
    make_advocate,
    pass_order,
    set_config,
    submitted,
    success_esign,
)

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 12)
D20 = datetime.date(2026, 11, 20)
D19 = datetime.date(2026, 11, 19)


def start(user, target):
    return client_for(user).post(f"/api/v1/applications/{target.pk}/objection/")


def file_objection(world, target, user=None):
    """B1 drafts, completes and sends the objection for signature."""
    user = user or world.b1
    objection_id = start(user, target).json()["id"]
    client = client_for(user)
    client.patch(
        f"/api/v1/applications/{objection_id}/",
        {
            "raised_by": str(world.b1.pk),
            "litigant": str(world.accused.pk),
            "details": "<p>We object.</p>",
        },
        format="json",
    )
    response = client.post(f"/api/v1/applications/{objection_id}/proceed-to-sign/")
    assert response.status_code == 200, response.json()
    return Application.objects.get(pk=objection_id)


def sign(world, application):
    esign = success_esign(application, world.b1)
    return client_for(world.b1).post(
        f"/api/v1/applications/{application.pk}/sign/confirm/",
        {"transaction_id": str(esign.pk)},
        format="json",
    )


@pytest.fixture
def target(world):
    application = submitted(world)
    pass_order(application, onboard=True, bring_back_on=D20, respond=True, respond_by=D19)
    return Application.objects.get(pk=application.pk)


def test_t76_other_side_starts_the_objection(world, target):
    response = start(world.b1, target)
    assert response.status_code == 201, response.json()
    body = response.json()
    assert (body["side"], body["type"]["code"]) == ("ACCUSED", "OBJECTION")
    assert body["objection_to"]["id"] == str(target.pk)


def test_t77_same_draft_returned_to_the_drafter_and_their_clerk(world, target):
    first = start(world.b1, target).json()["id"]
    from apps.users.models import Role

    from .factories import make_user, office

    clerk = make_user(name="Clerk to Bijini", role=Role.CLERK)
    office(clerk, world.b1)
    for user in (world.b1, clerk):
        response = start(user, target)
        assert response.status_code == 200
        assert response.json()["id"] == first


def test_t78_another_advocate_of_the_side_outside_the_circle(world, target):
    from apps.cases.models import ParticipantRole

    from .factories import add_party, represent

    other = make_advocate("Other accused advocate")
    second = add_party(world.case, ParticipantRole.ACCUSED, "Second accused", ordinal=2)
    represent(world.case, other, second)
    start(world.b1, target)
    response = start(other, target)
    assert response.status_code == 409
    assert codes_of(response) == ["E13022"]


def test_t79_own_side_cannot_object(world, target):
    assert codes_of(start(world.a1, target)) == ["E13020"]


def test_litigant_cannot_object(world, target):
    assert codes_of(start(world.l1, target)) == ["E13020"]


def test_t80_no_invitation_needed(world):
    application = submitted(world)
    assert start(world.b1, application).status_code == 201


def test_t09_objection_through_the_generic_endpoint(world, target):
    response = client_for(world.b1).post(
        f"/api/v1/cases/{world.case.pk}/applications/",
        {"application_type": "OBJECTION", "objection_to": str(target.pk)},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["objection_to"]["id"] == str(target.pk)


def test_t09_objecting_to_a_decided_application(world):
    application = submitted(world)
    pass_order(application, onboard=False, decides=True, outcome="DISMISSED")
    assert codes_of(start(world.b1, application)) == ["E13023"]


def test_no_objection_to_an_objection(world, target):
    objection = file_objection(world, target)
    sign(world, objection)
    assert codes_of(start(world.a1, objection)) == ["E13020"]


def test_t81_after_respond_by_while_undecided(world, target):
    objection = file_objection(world, target)
    set_config("hearings", "business_date_override", "2026-11-20")
    assert sign(world, objection).status_code == 200
    objection.refresh_from_db()
    assert objection.status == "SUBMITTED"
    body = client_for(world.a1).get(f"/api/v1/applications/{objection.pk}/").json()
    assert body["filed_after_deadline"] is True


def test_t82_submitted_objection(world, target):
    objection = file_objection(world, target)
    assert sign(world, objection).status_code == 200
    objection.refresh_from_db()
    assert objection.status == "SUBMITTED"
    assert objection.review_due_date is None
    body = client_for(world.a1).get(f"/api/v1/applications/{target.pk}/").json()
    assert body["objection_status"] == "FILED"
    assert body["objection"]["id"] == str(objection.pk)
    assert body["objection"]["details"] == "<p>We object.</p>"


def test_t84_window_closes_and_nothing_else_changes(world, target):
    set_config("hearings", "business_date_override", "2026-11-20")
    assert objections.close_windows() == 1
    target.refresh_from_db()
    assert target.status == "PENDING_DECISION"
    body = client_for(world.a1).get(f"/api/v1/applications/{target.pk}/").json()
    assert body["objection_status"] == "NONE_RECEIVED"


def test_t85_target_decided_while_the_objection_is_unsigned(world, target):
    set_config("applications", "fee.objection", "10")
    objection = file_objection(world, target)
    pass_order(target, decides=True, outcome="ACCEPTED")
    response = client_for(world.b1).post(
        f"/api/v1/applications/{objection.pk}/sign/",
        {"method": "AADHAAR_ESIGN"},
        format="json",
    )
    assert codes_of(response) == ["E13023"]
    assert client_for(world.b1).delete(f"/api/v1/applications/{objection.pk}/").status_code == 204


def test_t85_unpaid_objection_demand_cancelled(world, target):
    set_config("applications", "fee.objection", "10")
    objection = file_objection(world, target)
    assert sign(world, objection).status_code == 200
    objection.refresh_from_db()
    assert objection.status == "PENDING_PAYMENT"
    pass_order(target, decides=True, outcome="REJECTED")
    assert Demand.objects.get(pk=objection.demand_id).status == "CANCELLED"


def test_t87_draft_objection_hidden_submitted_one_visible(world, target):
    objection = file_objection(world, target)
    for user in (world.a1, world.staff):
        assert client_for(user).get(f"/api/v1/applications/{objection.pk}/").status_code == 404
    sign(world, objection)
    for user in (world.a1, world.staff):
        assert client_for(user).get(f"/api/v1/applications/{objection.pk}/").status_code == 200


def test_t86_one_objection_per_application(world, target):
    first, created = objections.start_objection(target.pk, world.b1)
    second, created_again = objections.start_objection(target.pk, world.b1)
    assert created and not created_again
    assert first.pk == second.pk
    assert Application.objects.filter(objection_to=target).count() == 1


def test_objection_needs_its_type_switched_on(world, target):
    from apps.applications.models import ApplicationType

    ApplicationType.objects.filter(code="OBJECTION").update(is_active=False)
    assert codes_of(start(world.b1, target)) == ["E13002"]


def test_objectable_lists_only_undecided_applications_of_the_other_side(world, target):
    decided = submitted(world)
    pass_order(decided, onboard=False, decides=True, outcome="DISMISSED")
    assert list(objections.objectable(world.case.pk, "ACCUSED")) == [target]
    assert list(objections.objectable(world.case.pk, "COMPLAINANT")) == []


def test_objection_paid_after_its_target_was_decided_stays_unsubmitted(world, target):
    from .factories import pay_demand

    set_config("applications", "fee.objection", "10")
    objection = file_objection(world, target)
    sign(world, objection)
    objection.refresh_from_db()
    with __import__("unittest").mock.patch(
        "apps.payments.services.demands.DemandService.cancel_demand"
    ):
        pass_order(target, decides=True, outcome="ACCEPTED")
    pay_demand(objection.demand_id, world.b1)
    objection.refresh_from_db()
    assert objection.status == "PENDING_PAYMENT"


def test_each_window_closes_once(world, target):
    set_config("hearings", "business_date_override", "2026-11-20")
    assert objections.close_windows() == 1
    set_config("hearings", "business_date_override", "2026-11-21")
    assert objections.close_windows() == 0
