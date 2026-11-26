"""After the decision: the type's workflow (spec 0033 #12, #17.7) and expiry (#13, #17.8)."""

import datetime
from unittest import mock

import pytest

from apps.applications import ports
from apps.applications.models import Application
from apps.applications.services import expiry, workflows
from apps.applications.signals import bail_bond_requested
from apps.applications.tasks import (
    close_objection_windows,
    expire_hearing_linked_applications,
    run_type_workflow,
)
from apps.hearings.enums import CancellationReason
from apps.hearings.services import listing

from .factories import client_for, pass_order, schedule_hearing, set_config, submitted

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 12)
D19 = datetime.date(2026, 11, 19)


def reload(application):
    return Application.objects.get(pk=application.pk)


def accept(application, **kwargs):
    pass_order(application, onboard=True, decides=True, outcome="ACCEPTED", **kwargs)
    return reload(application)


class TestTypeWorkflow:
    def test_t95_accept_bail_requests_the_bail_bond(
        self, world, django_capture_on_commit_callbacks
    ):
        application = submitted(world, "BAIL", side="ACCUSED", data={"bail_type": "CASH"})
        received = []

        def receiver(sender, **kwargs):
            received.append(kwargs)

        bail_bond_requested.connect(receiver)
        try:
            with (
                mock.patch.object(run_type_workflow, "send") as queued,
                django_capture_on_commit_callbacks(execute=True),
            ):
                application = accept(application)
            queued.assert_called_once_with(str(application.pk))
            assert application.status == "ACCEPTED"
            assert application.workflow_status == "PENDING"
            run_type_workflow.fn(str(application.pk))
        finally:
            bail_bond_requested.disconnect(receiver)
        application = reload(application)
        assert application.workflow_status == "DONE"
        assert received[0]["application_id"] == application.pk
        assert application.transitions.filter(action="WORKFLOW_DONE").count() == 1

    def test_t100_failure_keeps_the_decision_and_is_retried(self, world):
        application = submitted(
            world,
            "ADDITION_OF_WITNESS",
            data={"witnesses": [{"name": "W", "addresses": [{"city": "Kollam"}]}]},
        )
        application = accept(application)
        assert application.workflow_status == "PENDING"
        status, attempt = workflows.run(application.pk)
        assert (status, attempt) == ("FAILED", 1)
        application = reload(application)
        assert application.status == "ACCEPTED"
        row = application.transitions.get(action="WORKFLOW_FAILED")
        assert row.metadata == {"error_code": "CONTRACT_NOT_AVAILABLE", "attempt": 1}
        with mock.patch.object(ports, "add_witnesses", return_value=None):
            status, attempt = workflows.run(application.pk)
        assert (status, attempt) == ("DONE", 2)
        detail = client_for(world.a1).get(f"/api/v1/applications/{application.pk}/").json()
        assert detail["workflow_summary"] == "Witness added"

    def test_t101_redelivered_run_does_nothing(self, world):
        application = accept(submitted(world, "BAIL", side="ACCUSED", data={"bail_type": "CASH"}))
        workflows.run(application.pk)
        status, _ = workflows.run(application.pk)
        assert status == "DONE"
        assert reload(application).transitions.filter(action="WORKFLOW_DONE").count() == 1

    def test_actor_reenqueues_until_the_limit(self, world):
        application = accept(
            submitted(
                world,
                "ADDITION_OF_WITNESS",
                data={"witnesses": [{"name": "W", "addresses": [{"city": "Kollam"}]}]},
            )
        )
        set_config("applications", "workflow_max_retries", "2")
        with mock.patch.object(run_type_workflow, "send_with_options") as again:
            assert run_type_workflow.fn(str(application.pk)) == "FAILED"
            again.assert_called_once()
            again.reset_mock()
            assert run_type_workflow.fn(str(application.pk)) == "FAILED"
            again.assert_not_called()

    def test_t98_delay_condonation_on_accept_and_on_reject(self, world):
        for outcome in ("ACCEPTED", "REJECTED"):
            application = submitted(world, "DELAY_CONDONATION")
            pass_order(application, onboard=True, decides=True, outcome=outcome)
            assert reload(application).workflow_status == "PENDING"
            with mock.patch.object(ports, "dispatch_case_event") as dispatch:
                workflows.run(application.pk)
            dispatch.assert_called_once_with(world.case.pk, "DCA_DECIDED")
            assert reload(application).workflow_status == "DONE"

    @pytest.mark.parametrize(
        ("code", "data", "port"),
        [
            (
                "EDIT_LITIGANT_DETAILS",
                {"participant_id": None, "changes": {}},
                "apply_litigant_edit",
            ),
            ("PRODUCTION_OF_DOCUMENTS", {"documents": []}, "add_documents_from_application"),
        ],
    )
    def test_t96_t97_case_effects_go_through_the_ports(self, world, code, data, port):
        if data.get("participant_id", 0) is None:
            data = {**data, "participant_id": str(world.complainant.pk)}
        application = accept(submitted(world, code, data=data))
        with mock.patch.object(ports, port) as effect:
            workflows.run(application.pk)
        effect.assert_called_once()
        assert reload(application).workflow_status == "DONE"

    def test_t120_warrant_by_hand_hint(self, world):
        application = submitted(
            world,
            "WARRANT_BY_HAND",
            data={
                "accused_participant_id": str(world.accused.pk),
                "delivery_address": {"city": "K"},
            },
        )
        detail = client_for(world.staff).get(f"/api/v1/applications/{application.pk}/").json()
        assert detail["decision_hint"] == "Issue a warrant with the channel By hand."
        assert accept(application).workflow_status == "NOT_APPLICABLE"

    def test_t136_no_run_workflow_answer(self, world):
        application = submitted(world, "BAIL", side="ACCUSED", data={"bail_type": "CASH"})
        pass_order(application, onboard=True, decides=True, outcome="ACCEPTED", run_workflow=False)
        assert reload(application).workflow_status in ("PENDING", "DONE")

    def test_not_runnable(self, world):
        application = accept(submitted(world))
        assert workflows.run(application.pk)[0] == "NOT_APPLICABLE"


class TestExpiry:
    @pytest.fixture
    def hearing(self, world):
        return schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))

    def postpone(self, world, hearing):
        return submitted(
            world,
            "POSTPONE_HEARING",
            data={"reason_code": "ILLNESS", "proposed_date": "2026-12-04"},
            hearing_id=hearing.pk,
        )

    def test_t108_hearing_ended(self, world, hearing):
        review = self.postpone(world, hearing)
        decision = self.postpone(world, hearing)
        pass_order(decision, onboard=True, bring_back_on=D19)
        assert expiry.expire_for_hearing(hearing.pk, "HEARING_PASSED") == 2
        for application in (review, decision):
            application = reload(application)
            assert application.status == "EXPIRED"
            row = application.transitions.get(action="EXPIRE")
            assert row.metadata["reason"] == "HEARING_PASSED"

    def test_t109_hearing_moved_by_the_court(
        self, world, hearing, django_capture_on_commit_callbacks
    ):
        application = self.postpone(world, hearing)
        from apps.hearings.models import HearingPurpose
        from apps.hearings.services import reschedule

        with django_capture_on_commit_callbacks(execute=True):
            from django.db import transaction

            with transaction.atomic():
                locked = type(hearing).objects.select_for_update().get(pk=hearing.pk)
                reschedule.move(
                    locked,
                    to_date=TODAY + datetime.timedelta(days=14),
                    to_purpose=HearingPurpose.objects.get(code="APPEARANCE"),
                    reason_code="NOT_REACHED",
                    source="COURT_ADMIN",
                )
        row = reload(application).transitions.get(action="EXPIRE")
        assert row.metadata["reason"] == "HEARING_MOVED"

    def test_t110_hearing_cancelled(self, world, hearing, django_capture_on_commit_callbacks):
        application = self.postpone(world, hearing)
        with django_capture_on_commit_callbacks(execute=True):
            listing.cancel_open_hearings(
                case_id=world.case.pk, reason=CancellationReason.CASE_DISPOSED
            )
        application = reload(application)
        assert application.status == "EXPIRED"
        assert (
            application.transitions.get(action="EXPIRE").metadata["reason"] == "HEARING_CANCELLED"
        )

    def test_t111_live_order_guard(self, world, hearing):
        application = self.postpone(world, hearing)
        with mock.patch.object(ports, "live_items_targeting", return_value={application.pk: {}}):
            assert expiry.expire_for_hearing(hearing.pk, "HEARING_PASSED") == 0
        assert reload(application).status == "PENDING_REVIEW"

    def test_t114_other_types_never_expire(self, world, hearing):
        application = submitted(world)
        expiry.expire_for_hearing(hearing.pk, "HEARING_PASSED")
        set_config("hearings", "business_date_override", "2026-12-30")
        assert expiry.sweep() == 0
        assert reload(application).status == "PENDING_REVIEW"

    def test_t115_sweep_catches_a_missed_signal(self, world, hearing):
        application = self.postpone(world, hearing)
        set_config("hearings", "business_date_override", "2026-11-22")
        assert expire_hearing_linked_applications.fn() == 1
        assert reload(application).status == "EXPIRED"
        assert expiry.sweep() == 0

    def test_t112_unsubmitted_postpone_never_expires_but_cannot_be_signed(self, world, hearing):
        response = client_for(world.a1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {
                "application_type": "POSTPONE_HEARING",
                "raised_by": str(world.a1.pk),
                "litigant": str(world.complainant.pk),
                "details": "<p>Ill.</p>",
                "data": {"reason_code": "ILLNESS", "proposed_date": "2026-12-04"},
            },
            format="json",
        )
        app_id = response.json()["id"]
        set_config("hearings", "business_date_override", "2026-11-22")
        expiry.sweep()
        assert Application.objects.get(pk=app_id).status == "DRAFT"
        response = client_for(world.a1).post(f"/api/v1/applications/{app_id}/proceed-to-sign/")
        assert [e["code"] for e in response.json()["errors"]] == ["E13016"]
        assert client_for(world.a1).delete(f"/api/v1/applications/{app_id}/").status_code == 204

    def test_t113_paid_after_the_hearing_passed(self, world, hearing):
        from .factories import pay_demand, success_esign

        set_config("applications", "fee.postpone_hearing", "10")
        response = client_for(world.a1).post(
            f"/api/v1/cases/{world.case.pk}/applications/",
            {
                "application_type": "POSTPONE_HEARING",
                "raised_by": str(world.a1.pk),
                "litigant": str(world.complainant.pk),
                "details": "<p>Ill.</p>",
                "data": {"reason_code": "ILLNESS", "proposed_date": "2026-12-04"},
            },
            format="json",
        )
        app_id = response.json()["id"]
        client_for(world.a1).post(f"/api/v1/applications/{app_id}/proceed-to-sign/")
        application = Application.objects.get(pk=app_id)
        esign = success_esign(application, world.a1)
        client_for(world.a1).post(
            f"/api/v1/applications/{app_id}/sign/confirm/",
            {"transaction_id": str(esign.pk)},
            format="json",
        )
        set_config("hearings", "business_date_override", "2026-11-22")
        pay_demand(Application.objects.get(pk=app_id).demand_id, world.a1)
        application = Application.objects.get(pk=app_id)
        assert application.status == "EXPIRED"
        assert application.application_number

    def test_purpose_only_move_does_not_expire(self, world, hearing):
        from apps.applications.receivers import on_hearing_rescheduled

        application = self.postpone(world, hearing)
        on_hearing_rescheduled(
            None, hearing.pk, from_date=hearing.hearing_date, to_date=hearing.hearing_date
        )
        assert reload(application).status == "PENDING_REVIEW"

    def test_hearing_gone(self, world, hearing):
        application = self.postpone(world, hearing)
        assert expiry.hearing_gone(application) is None
        application.hearing_id = "00000000-0000-0000-0000-000000000000"
        assert expiry.hearing_gone(application) == "HEARING_CANCELLED"

    def test_close_objection_windows_actor(self, world):
        assert close_objection_windows.fn() == 0
