"""Filing: signature, payment and submission (spec 0033 #6.6-#6.9, #17.3)."""

import datetime
from unittest import mock

import pytest

from apps.applications.models import Application
from apps.applications.services import signing
from apps.esign.models import ESignTransaction
from apps.hearings.models import CourtCalendarEntry
from apps.payments.models import Demand, Payment
from apps.users.models import Role

from .factories import (
    client_for,
    codes_of,
    errors_of,
    make_user,
    office,
    pay_demand,
    pdf_upload,
    set_config,
    success_esign,
)

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 12)  # Thursday


def ready_to_sign(world, user=None, **body):
    """A complete Generic application sent for signature by ``user`` (A1 by default)."""
    user = user or world.a1
    body = {
        "application_type": "GENERIC",
        "raised_by": str(world.a1.pk),
        "litigant": str(world.complainant.pk),
        "details": "<p>Reasons.</p>",
        "data": {"title": "Adjournment"},
        **body,
    }
    app_id = (
        client_for(user)
        .post(f"/api/v1/cases/{world.case.pk}/applications/", body, format="json")
        .json()["id"]
    )
    response = client_for(user).post(f"/api/v1/applications/{app_id}/proceed-to-sign/")
    assert response.status_code == 200, response.json()
    return Application.objects.get(pk=app_id)


def confirm(user, application, transaction_id):
    return client_for(user).post(
        f"/api/v1/applications/{application.pk}/sign/confirm/",
        {"transaction_id": str(transaction_id)},
        format="json",
    )


def sign(world, application, user=None):
    user = user or world.a1
    esign = success_esign(application, user)
    response = confirm(user, application, esign.pk)
    assert response.status_code == 200, response.json()
    application.refresh_from_db()
    return application


class TestSignature:
    def test_t39_clerk_sends_for_signature(self, world):
        application = ready_to_sign(world, user=world.c1)
        assert application.status == "PENDING_SIGNATURE"
        assert application.signing_file_id
        assert application.raised_by == world.a1

    @pytest.mark.parametrize("who", ["c1", "b1"])
    def test_t40_only_raised_by_signs(self, world, who):
        application = ready_to_sign(world)
        user = getattr(world, who)
        response = client_for(user).post(
            f"/api/v1/applications/{application.pk}/sign/",
            {"method": "AADHAAR_ESIGN"},
            format="json",
        )
        if who == "b1":
            # The other side cannot see a pending-signature application at all.
            assert response.status_code == 404
        else:
            assert codes_of(response) == ["E13013"]

    def test_t40_junior_with_their_own_representation_is_not_raised_by(self, world):
        from apps.cases.models import ParticipantRole

        from .factories import add_party, make_advocate, represent

        junior = make_advocate("Junior")
        second = add_party(world.case, ParticipantRole.COMPLAINANT, "Second", ordinal=2)
        represent(world.case, junior, second)
        application = ready_to_sign(world)
        # Another advocate of the same side is outside the drafting circle: not found.
        esign = success_esign(application, junior)
        assert codes_of(confirm(junior, application, esign.pk)) == ["E00105"]
        assert (
            signing.can_sign_application(
                user=junior, entity_type="APPLICATION", entity_id=str(application.pk)
            )
            is False
        )

    def test_clerk_never_signs_even_as_raised_by(self, world):
        application = ready_to_sign(world)
        Application.objects.filter(pk=application.pk).update(raised_by=world.c1)
        application.refresh_from_db()
        assert (
            signing.can_sign_application(
                user=world.c1, entity_type="APPLICATION", entity_id=str(application.pk)
            )
            is False
        )

    def test_t42_method_not_enabled(self, world):
        application = ready_to_sign(world)
        response = client_for(world.a1).post(
            f"/api/v1/applications/{application.pk}/sign/", {"method": "DSC"}, format="json"
        )
        assert errors_of(response) == [("E13014", "method")]

    def test_t43_back_to_draft_keeps_everything(self, world):
        application = ready_to_sign(world, user=world.c1)
        response = client_for(world.c1).post(
            f"/api/v1/applications/{application.pk}/back-to-draft/"
        )
        assert response.status_code == 200, response.json()
        application.refresh_from_db()
        assert application.status == "DRAFT"
        assert application.signing_file_id == ""
        assert application.data == {"title": "Adjournment"}

    def test_back_to_draft_only_from_pending_signature(self, world):
        application = ready_to_sign(world)
        client_for(world.a1).post(f"/api/v1/applications/{application.pk}/back-to-draft/")
        response = client_for(world.a1).post(
            f"/api/v1/applications/{application.pk}/back-to-draft/"
        )
        assert codes_of(response) == ["E13001"]
        assert response.status_code == 409

    def test_t44_esign_from_before_back_to_draft_is_refused(self, world):
        application = ready_to_sign(world)
        old = success_esign(application, world.a1)
        client_for(world.a1).post(f"/api/v1/applications/{application.pk}/back-to-draft/")
        client_for(world.a1).post(f"/api/v1/applications/{application.pk}/proceed-to-sign/")
        application.refresh_from_db()
        assert codes_of(confirm(world.a1, application, old.pk)) == ["E13015"]

    @pytest.mark.parametrize("problem", ["pending", "other_user"])
    def test_t45_pending_or_someone_elses_transaction(self, world, problem):
        application = ready_to_sign(world)
        esign = success_esign(application, world.a1)
        if problem == "pending":
            ESignTransaction.objects.filter(pk=esign.pk).update(status="PENDING")
        else:
            ESignTransaction.objects.filter(pk=esign.pk).update(signer=world.b1)
        assert codes_of(confirm(world.a1, application, esign.pk)) == ["E13015"]

    def test_unknown_transaction(self, world):
        application = ready_to_sign(world)
        response = confirm(world.a1, application, "00000000-0000-0000-0000-000000000000")
        assert codes_of(response) == ["E13015"]

    def test_t46_confirm_twice_is_idempotent(self, world):
        application = ready_to_sign(world)
        esign = success_esign(application, world.a1)
        assert confirm(world.a1, application, esign.pk).status_code == 200
        assert confirm(world.a1, application, esign.pk).status_code == 200
        assert application.transitions.filter(action="SIGN").count() == 1

    def test_t47_authorizer(self, world):
        application = ready_to_sign(world)
        kwargs = {"entity_type": "APPLICATION", "entity_id": str(application.pk)}
        assert signing.can_sign_application(user=world.a1, **kwargs) is True
        assert signing.can_sign_application(user=world.c1, **kwargs) is False
        assert signing.can_sign_application(user=world.a1, file_id="other", **kwargs) is False
        assert (
            signing.can_sign_application(user=world.a1, entity_type="APPLICATION", entity_id="x")
            is False
        )

    def test_initiate_starts_esign_on_the_copy_to_sign(self, world):
        application = ready_to_sign(world)
        fake = mock.Mock()
        with (
            mock.patch.object(signing, "initiate_esign", return_value=fake) as started,
            mock.patch(
                "apps.applications.views.initiation_payload", return_value={"esign_url": "u"}
            ),
        ):
            response = client_for(world.a1).post(
                f"/api/v1/applications/{application.pk}/sign/",
                {"method": "AADHAAR_ESIGN"},
                format="json",
            )
        assert response.status_code == 201, response.json()
        kwargs = started.call_args.kwargs
        assert kwargs["user"] == world.a1
        assert kwargs["file_id"] == application.signing_file_id
        assert kwargs["entity_type"] == "APPLICATION"
        assert kwargs["entity_id"] == str(application.pk)

    def test_esign_errors_pass_through(self, world):
        from apps.esign.exceptions import ESignDisabled

        application = ready_to_sign(world)
        with mock.patch.object(signing, "initiate_esign", side_effect=ESignDisabled()):
            response = client_for(world.a1).post(
                f"/api/v1/applications/{application.pk}/sign/",
                {"method": "AADHAAR_ESIGN"},
                format="json",
            )
        assert response.status_code == 503

    def test_t144_signing_methods_on_the_detail(self, world):
        application = ready_to_sign(world)
        body = client_for(world.a1).get(f"/api/v1/applications/{application.pk}/").json()
        assert body["signing_methods"] == ["AADHAAR_ESIGN"]
        response = client_for(world.a1).post(
            f"/api/v1/applications/{application.pk}/sign/upload/",
            {"file": pdf_upload()},
            format="multipart",
        )
        assert errors_of(response) == [("E13014", "method")]

    def test_upload_signed_copy_where_enabled(self, world):
        set_config("signing", "methods", "AADHAAR_ESIGN,UPLOAD_SIGNED_COPY")
        application = ready_to_sign(world)
        response = client_for(world.c1).post(
            f"/api/v1/applications/{application.pk}/sign/upload/",
            {"file": pdf_upload()},
            format="multipart",
        )
        assert codes_of(response) == ["E13013"]
        response = client_for(world.a1).post(
            f"/api/v1/applications/{application.pk}/sign/upload/",
            {"file": pdf_upload()},
            format="multipart",
        )
        assert response.status_code == 200, response.json()
        row = application.transitions.get(action="SIGN")
        assert row.metadata == {"method": "UPLOAD_SIGNED_COPY"}


class TestPayment:
    def test_t48_fee_due_raises_a_demand(self, world):
        set_config("applications", "fee.generic", "50")
        application = sign(world, ready_to_sign(world))
        assert application.status == "PENDING_PAYMENT"
        demand = Demand.objects.get(pk=application.demand_id)
        assert str(demand.total_amount) == "50.00"
        assert demand.reference_type == "APPLICATION"
        assert demand.items.get().charge_type == "APPLICATION_FEE"
        row = application.transitions.get(action="SIGN")
        assert row.metadata["method"] == "AADHAAR_ESIGN"
        assert row.metadata["esign_transaction_id"]
        body = client_for(world.a1).get(f"/api/v1/applications/{application.pk}/").json()
        assert body["fee"] == "50.00"

    def test_t49_no_fee_submits_at_once(self, world):
        application = sign(world, ready_to_sign(world))
        assert application.status == "PENDING_REVIEW"
        assert application.demand_id is None
        assert application.application_number == f"{world.case.filing_number}-AP1"

    def test_t50_litigant_pays_and_redelivery_does_nothing(self, world):
        set_config("applications", "fee.generic", "50")
        application = sign(world, ready_to_sign(world))
        payment = pay_demand(application.demand_id, world.l1)
        from apps.payments.tasks import notify_payment_completed

        notify_payment_completed.fn(str(payment.pk))
        application.refresh_from_db()
        assert application.status == "PENDING_REVIEW"
        assert application.application_number == f"{world.case.filing_number}-AP1"
        assert application.transitions.filter(action="SUBMIT").count() == 1
        assert application.transitions.filter(action="PAY").count() == 1

    def test_t51_pending_payment_does_not_submit(self, world):
        set_config("applications", "fee.generic", "50")
        application = sign(world, ready_to_sign(world))
        from apps.payments.signals import payment_completed

        demand = Demand.objects.get(pk=application.demand_id)
        payment_completed.send(
            sender=Payment, payment=mock.Mock(pk="p"), demand=demand, items=[], demand_paid=False
        )
        application.refresh_from_db()
        assert application.status == "PENDING_PAYMENT"

    def test_another_modules_demand_is_ignored(self, world):
        from apps.payments.signals import payment_completed

        payment_completed.send(
            sender=Payment,
            payment=mock.Mock(pk="p"),
            demand=mock.Mock(pk="00000000-0000-0000-0000-000000000000"),
            items=[],
            demand_paid=True,
        )

    def test_t52_fee_change_after_signing_does_not_change_the_demand(self, world):
        set_config("applications", "fee.generic", "50")
        application = sign(world, ready_to_sign(world))
        set_config("applications", "fee.generic", "75")
        assert str(Demand.objects.get(pk=application.demand_id).total_amount) == "50.00"

    def test_state_specific_fee(self, world):
        from apps.locations.models import Location

        kerala = Location.objects.create(code="IN_KL", name="Kerala", location_type="state")
        world.court.parent.jurisdictions.add(kerala)
        set_config("applications.in_kl", "fee.generic", "20")
        application = sign(world, ready_to_sign(world))
        assert str(Demand.objects.get(pk=application.demand_id).total_amount) == "20.00"

    def test_t53_three_paid_each_get_their_own_number(self, world):
        set_config("applications", "fee.generic", "10")
        applications = [sign(world, ready_to_sign(world)) for _ in range(3)]
        for application in applications:
            pay_demand(application.demand_id, world.a1)
        numbers = {Application.objects.get(pk=a.pk).application_number for a in applications}
        assert len(numbers) == 3

    def test_t130_delete_cancels_an_unpaid_demand_and_refuses_one_in_flight(self, world):
        set_config("applications", "fee.generic", "50")
        application = sign(world, ready_to_sign(world))
        from apps.payments.services.payments import PaymentService

        demand = Demand.objects.get(pk=application.demand_id)
        PaymentService.create_payment(
            demand=demand,
            demand_item_ids=list(demand.items.values_list("pk", flat=True)),
            client_request_id="in-flight",
            actor=world.a1,
        )
        url = f"/api/v1/applications/{application.pk}/"
        response = client_for(world.a1).delete(url)
        assert response.status_code == 409
        assert codes_of(response) == ["E13030"]
        Payment.objects.update(status="FAILED")
        assert client_for(world.a1).delete(url).status_code == 204
        demand.refresh_from_db()
        assert demand.status == "CANCELLED"
        assert not Application.objects.filter(pk=application.pk).exists()


class TestSubmission:
    def test_t54_review_due_next_working_day(self, world):
        friday = datetime.date(2026, 11, 13)
        set_config("hearings", "business_date_override", friday.isoformat())
        CourtCalendarEntry.objects.create(
            court=world.court,
            date=friday + datetime.timedelta(days=1),
            entry_type="PRESIDING_OFFICER_LEAVE",
            reason="Leave",
        )
        CourtCalendarEntry.objects.create(
            court=world.court,
            date=friday + datetime.timedelta(days=3),
            entry_type="HOLIDAY",
            reason="Holiday",
        )
        application = sign(world, ready_to_sign(world))
        # Saturday: a working day though the court does not sit.
        assert application.review_due_date == friday + datetime.timedelta(days=1)

    def test_t54_holiday_saturday_moves_to_tuesday(self, world):
        friday = datetime.date(2026, 11, 13)
        set_config("hearings", "business_date_override", friday.isoformat())
        for days in (1, 3):
            CourtCalendarEntry.objects.create(
                court=world.court,
                date=friday + datetime.timedelta(days=days),
                entry_type="HOLIDAY",
                reason="Holiday",
            )
        application = sign(world, ready_to_sign(world))
        assert application.review_due_date == friday + datetime.timedelta(days=4)

    def test_t55_submitted_is_visible_to_the_other_side_and_the_court(self, world):
        application = sign(world, ready_to_sign(world))
        for user in (world.b1, world.reader, world.l1):
            response = client_for(user).get(f"/api/v1/applications/{application.pk}/")
            assert response.status_code == 200, user.name

    def test_t56_unsubmitted_hidden_from_court_and_other_side(self, world):
        set_config("applications", "fee.generic", "50")
        application = sign(world, ready_to_sign(world))
        for user in (world.b1, world.reader):
            response = client_for(user).get(f"/api/v1/applications/{application.pk}/")
            assert response.status_code == 404
            assert codes_of(response) == ["E00105"]
        # The litigant may see it, to pay (ALC-29).
        assert (
            client_for(world.l1).get(f"/api/v1/applications/{application.pk}/").status_code == 200
        )

    def test_submitted_notifies_the_filers_side_only(
        self, world, django_capture_on_commit_callbacks
    ):
        with mock.patch("apps.applications.services.notifications.enqueue_sms") as sms:
            application = ready_to_sign(world)
            with django_capture_on_commit_callbacks(execute=True):
                sign(world, application)
        keys = [call.args[0] for call in sms.call_args_list]
        assert "APPLICATION_SUBMITTED" in keys
        phones = {
            call.args[1]["phone_number"]
            for call in sms.call_args_list
            if call.args[0] == "APPLICATION_SUBMITTED"
        }
        assert world.b1.mobile_number not in phones
        assert world.a1.mobile_number in phones

    def test_submission_without_a_number_format(self, world):
        from apps.core.models import Configuration

        Configuration.objects.filter(config_key="submission_number_format").delete()
        application = ready_to_sign(world)
        esign = success_esign(application, world.a1)
        response = confirm(world.a1, application, esign.pk)
        assert response.status_code == 503
        assert codes_of(response) == ["E13028"]
        application.refresh_from_db()
        assert application.status == "PENDING_SIGNATURE"

    def test_clerk_of_another_advocate_sees_nothing(self, world):
        other_clerk = make_user(name="Other clerk", role=Role.CLERK)
        office(other_clerk, world.b1)
        application = ready_to_sign(world)
        response = client_for(other_clerk).get(f"/api/v1/applications/{application.pk}/")
        assert response.status_code == 404


def test_back_to_draft_releases_the_superseded_copy(world, django_capture_on_commit_callbacks):
    from apps.files.models import File

    application = ready_to_sign(world)
    old_file = application.signing_file_id
    with django_capture_on_commit_callbacks(execute=True):
        client_for(world.a1).post(f"/api/v1/applications/{application.pk}/back-to-draft/")
    assert not File.objects.filter(pk=old_file).exists()


def test_back_to_draft_keeps_a_copy_an_esign_is_working_on(
    world, django_capture_on_commit_callbacks
):
    from apps.files.models import File

    application = ready_to_sign(world)
    esign = success_esign(application, world.a1)
    ESignTransaction.objects.filter(pk=esign.pk).update(status="PENDING")
    with django_capture_on_commit_callbacks(execute=True):
        client_for(world.a1).post(f"/api/v1/applications/{application.pk}/back-to-draft/")
    assert File.objects.filter(pk=application.signing_file_id).exists()
