"""End-to-end scenarios through the API and the stub order (spec 0033 #17.10)."""

import datetime
from unittest import mock

import pytest

from apps.applications.models import Application
from apps.applications.services import workflows
from apps.payments.models import Demand

from .factories import (
    client_for,
    pass_order,
    pay_demand,
    schedule_hearing,
    set_config,
    success_esign,
)

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 12)


def raise_and_sign(world, *, drafter, signer, side="COMPLAINANT", **body):
    litigant = world.complainant if side == "COMPLAINANT" else world.accused
    body = {
        "raised_by": str(signer.pk),
        "litigant": str(litigant.pk),
        "details": "<p>Reasons.</p>",
        **body,
    }
    app_id = (
        client_for(drafter)
        .post(f"/api/v1/cases/{world.case.pk}/applications/", body, format="json")
        .json()["id"]
    )
    response = client_for(drafter).post(f"/api/v1/applications/{app_id}/proceed-to-sign/")
    assert response.status_code == 200, response.json()
    application = Application.objects.get(pk=app_id)
    esign = success_esign(application, signer)
    response = client_for(signer).post(
        f"/api/v1/applications/{app_id}/sign/confirm/",
        {"transaction_id": str(esign.pk)},
        format="json",
    )
    assert response.status_code == 200, response.json()
    return Application.objects.get(pk=app_id)


def test_e01_postpone_from_clerk_to_acceptance(world, django_capture_on_commit_callbacks):
    set_config("applications", "fee.postpone_hearing", "20")
    hearing = schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))
    application = raise_and_sign(
        world,
        drafter=world.c1,
        signer=world.a1,
        application_type="POSTPONE_HEARING",
        data={"reason_code": "ILLNESS", "proposed_date": "2026-12-04"},
    )
    assert application.status == "PENDING_PAYMENT"
    pay_demand(application.demand_id, world.l1)
    application.refresh_from_db()
    assert application.status == "PENDING_REVIEW"

    respond_by = datetime.date(2026, 11, 18)
    decide_on = datetime.date(2026, 11, 19)
    pass_order(
        application, onboard=True, bring_back_on=decide_on, respond=True, respond_by=respond_by
    )

    objection_id = (
        client_for(world.b1).post(f"/api/v1/applications/{application.pk}/objection/").json()["id"]
    )
    client_for(world.b1).patch(
        f"/api/v1/applications/{objection_id}/",
        {"raised_by": str(world.b1.pk), "litigant": str(world.accused.pk), "details": "<p>No.</p>"},
        format="json",
    )
    client_for(world.b1).post(f"/api/v1/applications/{objection_id}/proceed-to-sign/")
    objection = Application.objects.get(pk=objection_id)
    esign = success_esign(objection, world.b1)
    client_for(world.b1).post(
        f"/api/v1/applications/{objection_id}/sign/confirm/",
        {"transaction_id": str(esign.pk)},
        format="json",
    )
    assert Application.objects.get(pk=objection_id).status == "SUBMITTED"

    # The accepting order moves the hearing first (0025 #9.2), then the item runs.
    with mock.patch("apps.applications.services.workflows.enqueue"):
        result = pass_order(application, decides=True, outcome="ACCEPTED", moves_hearing=True)
    assert result.status == "DONE"
    workflows.run(application.pk)
    application.refresh_from_db()
    assert application.status == "ACCEPTED"
    assert application.workflow_status == "DONE"
    detail = client_for(world.staff).get(f"/api/v1/applications/{application.pk}/").json()
    assert detail["objection_status"] == "FILED"
    assert detail["workflow_summary"].startswith("Hearing rescheduled to")
    assert hearing.pk == application.hearing_id


def test_e02_bail_onboarded_and_accepted_the_same_day(world):
    application = raise_and_sign(
        world,
        drafter=world.b1,
        signer=world.b1,
        side="ACCUSED",
        application_type="BAIL",
        data={"bail_type": "CASH", "bail_amount": "10000"},
    )
    with mock.patch("apps.applications.services.workflows.enqueue"):
        pass_order(application, onboard=True, decides=True, outcome="ACCEPTED")
    application.refresh_from_db()
    assert (application.status, application.workflow_status) == ("ACCEPTED", "PENDING")
    assert workflows.run(application.pk)[0] == "DONE"


def test_e03_generic_deferred_then_dismissed(world, django_capture_on_commit_callbacks):
    with (
        mock.patch("apps.applications.services.notifications.enqueue_sms") as sms,
        django_capture_on_commit_callbacks(execute=True),
    ):
        application = raise_and_sign(
            world,
            drafter=world.a1,
            signer=world.a1,
            application_type="GENERIC",
            data={"title": "T"},
        )
    assert world.b1.mobile_number not in {c.args[1]["phone_number"] for c in sms.call_args_list}
    assert client_for(world.b1).get(f"/api/v1/applications/{application.pk}/").status_code == 200
    pass_order(application, onboard=False, decides=False, bring_back_on=datetime.date(2026, 11, 16))
    pass_order(application, onboard=False, decides=True, outcome="DISMISSED")
    application.refresh_from_db()
    assert application.status == "DISMISSED"
    assert application.onboarded_at is None
    assert application.earlier_application_number is None


def test_e04_advance_expires_when_the_court_moves_its_hearing(world):
    from apps.applications.services import expiry

    hearing = schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))
    application = raise_and_sign(
        world,
        drafter=world.a1,
        signer=world.a1,
        application_type="ADVANCE_HEARING",
        data={"reason_code": "ILLNESS", "proposed_date": "2026-11-16"},
    )
    pass_order(
        application,
        onboard=True,
        bring_back_on=datetime.date(2026, 11, 17),
        respond=True,
        respond_by=datetime.date(2026, 11, 16),
    )
    expiry.expire_for_hearing(hearing.pk, "HEARING_MOVED")
    application.refresh_from_db()
    assert application.status == "EXPIRED"
    assert application.transitions.get(action="EXPIRE").metadata["reason"] == "HEARING_MOVED"


def test_e05_edit_litigant_back_to_draft_resigned_paid_accepted(world):
    set_config("applications", "fee.edit_litigant_details", "15")
    body = {
        "application_type": "EDIT_LITIGANT_DETAILS",
        "raised_by": str(world.a1.pk),
        "litigant": str(world.complainant.pk),
        "details": "<p>Name spelt wrong.</p>",
        "data": {
            "participant_id": str(world.complainant.pk),
            "litigant_type": "INDIVIDUAL",
            "details": {
                "name": "Prateek Agarwal",
                "age": 40,
                "phone_number": "+919800000001",
                "addresses": [{"line1": "1 Road", "city": "Kollam"}],
            },
        },
    }
    client = client_for(world.a1)
    app_id = client.post(
        f"/api/v1/cases/{world.case.pk}/applications/", body, format="json"
    ).json()["id"]
    assert client.post(f"/api/v1/applications/{app_id}/proceed-to-sign/").status_code == 200
    assert client.post(f"/api/v1/applications/{app_id}/back-to-draft/").status_code == 200
    client.patch(
        f"/api/v1/applications/{app_id}/", {"details": "<p>Name and age.</p>"}, format="json"
    )
    assert client.post(f"/api/v1/applications/{app_id}/proceed-to-sign/").status_code == 200
    application = Application.objects.get(pk=app_id)
    assert application.data["changes"]["name"] == {
        "from": "Prateek Agrawal",
        "to": "Prateek Agarwal",
    }
    esign = success_esign(application, world.a1)
    client.post(
        f"/api/v1/applications/{app_id}/sign/confirm/",
        {"transaction_id": str(esign.pk)},
        format="json",
    )
    pay_demand(Application.objects.get(pk=app_id).demand_id, world.h1)
    application = Application.objects.get(pk=app_id)
    pass_order(application, onboard=True, bring_back_on=TODAY)
    with mock.patch("apps.applications.services.workflows.enqueue"):
        pass_order(application, decides=True, outcome="ACCEPTED")
    from apps.applications import ports

    with mock.patch.object(ports, "apply_litigant_edit") as edit:
        workflows.run(application.pk)
    edit.assert_called_once()
    assert edit.call_args.args[2]["name"]["to"] == "Prateek Agarwal"


def test_e06_no_objection_date_moved_then_rejected_with_a_cis_outcome(world):
    set_config("applications", "cis_outcomes", '[{"code": "DISALLOWED", "label": "Disallowed"}]')
    application = raise_and_sign(
        world, drafter=world.a1, signer=world.a1, application_type="GENERIC", data={"title": "T"}
    )
    pass_order(
        application,
        onboard=True,
        bring_back_on=datetime.date(2026, 11, 20),
        respond=True,
        respond_by=datetime.date(2026, 11, 19),
    )
    pass_order(application, decides=False, bring_back_on=datetime.date(2026, 11, 27), respond=False)
    result = pass_order(application, decides=True, outcome="REJECTED", cis_outcome="DISALLOWED")
    assert result.status == "DONE"
    application.refresh_from_db()
    assert application.status == "REJECTED"
    assert application.transitions.get(action="REJECT").metadata == {"cis_outcome": "DISALLOWED"}


def test_e07_deleted_in_pending_payment(world):
    set_config("applications", "fee.generic", "5")
    application = raise_and_sign(
        world, drafter=world.a1, signer=world.a1, application_type="GENERIC", data={"title": "T"}
    )
    demand_id = application.demand_id
    assert client_for(world.c1).delete(f"/api/v1/applications/{application.pk}/").status_code == 204
    assert Demand.objects.get(pk=demand_id).status == "CANCELLED"
    for user in (world.a1, world.b1, world.staff):
        assert client_for(user).get(f"/api/v1/applications/{application.pk}/").status_code == 404
