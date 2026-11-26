"""The *Application action* item: review, onboarding, deferral, decision (spec 0033 #8, #17.5, #17.7)."""

import datetime
import uuid
from unittest import mock

import pytest

from apps.applications.handlers import ApplicationActionHandler, register_with_orders
from apps.applications.models import Application, ApplicationTransition
from apps.applications.services import actions

from .factories import order_values, pass_order, schedule_hearing, set_config, submitted

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 12)
D20 = datetime.date(2026, 11, 20)
D19 = datetime.date(2026, 11, 19)


def reload(application):
    return Application.objects.get(pk=application.pk)


def transitions(application):
    return list(
        ApplicationTransition.objects.filter(application_ref=application.pk)
        .order_by("created_at")
        .values_list("action", flat=True)
    )


class TestOnboarding:
    def test_t65_onboard_on_a_date_inviting_a_response(
        self, world, django_capture_on_commit_callbacks
    ):
        application = submitted(world)
        first_number = application.application_number
        order_id = uuid.uuid4()
        with (
            mock.patch("apps.applications.services.notifications.enqueue_sms") as sms,
            django_capture_on_commit_callbacks(execute=True),
        ):
            result = pass_order(
                application,
                order_id=order_id,
                onboard=True,
                decides=False,
                bring_back_on=D20,
                respond=True,
                respond_by=D19,
            )
        assert result.status == "DONE"
        application = reload(application)
        assert application.status == "PENDING_DECISION"
        assert application.application_number == "CMP/1/2026"
        assert application.earlier_application_number == first_number
        assert (application.decision_date, application.respond_by) == (D20, D19)
        assert application.objections_invited is True
        assert application.onboarded_at is not None
        assert application.review_due_date is None
        row = application.transitions.get(action="ONBOARD")
        assert row.order_id == order_id
        assert row.summary == "Onboarded as CMP/1/2026; to be decided on 20 Nov; response by 19 Nov"
        assert row.metadata["number_replaced"] == {"from": first_number, "to": "CMP/1/2026"}
        phones = {
            c.args[1]["phone_number"]
            for c in sms.call_args_list
            if c.args[0] == "APPLICATION_RESPONSE_REQUESTED"
        }
        assert phones == {world.b1.mobile_number}

    def test_t67_item_defaults(self, world):
        schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))
        application = submitted(world)
        defaults = actions.defaults(application)
        assert defaults == {
            "application_number": application.application_number,
            "application_type": "Generic",
            "onboard": True,
            "decides": False,
            "bring_back_on": "2026-11-21",
            "respond": True,
            "respond_by": "2026-11-20",
        }

    def test_t68_respond_no_tells_nobody_on_the_other_side(
        self, world, django_capture_on_commit_callbacks
    ):
        application = submitted(world)
        with (
            mock.patch("apps.applications.services.notifications.enqueue_sms") as sms,
            django_capture_on_commit_callbacks(execute=True),
        ):
            pass_order(application, onboard=True, bring_back_on=D20, respond=False)
        application = reload(application)
        assert application.objections_invited is False
        assert application.respond_by is None
        assert not [c for c in sms.call_args_list if c.args[0] == "APPLICATION_RESPONSE_REQUESTED"]

    def test_t69_dates(self, world):
        application = submitted(world)
        past = actions.validate(
            application,
            order_values(bring_back_on=TODAY - datetime.timedelta(days=1)),
            complete=False,
        )
        assert [p.code for p in past] == ["DATE_IN_PAST"]
        late = actions.validate(
            application,
            order_values(bring_back_on=D19, respond=True, respond_by=D20),
            complete=False,
        )
        assert [p.code for p in late] == ["RESPOND_BY_INVALID"]
        which = actions.asked(application, order_values(bring_back_on=TODAY))
        assert which["respond"] is False

    def test_today_invites_no_objection(self, world):
        application = submitted(world)
        pass_order(application, onboard=True, bring_back_on=TODAY, respond=True, respond_by=TODAY)
        application = reload(application)
        assert application.decision_date == TODAY
        assert application.objections_invited is None
        assert application.respond_by is None

    def test_t70_onboard_and_accept_in_one_order(self, world):
        application = submitted(world)
        order_id = uuid.uuid4()
        result = pass_order(
            application, order_id=order_id, onboard=True, decides=True, outcome="ACCEPTED"
        )
        assert result.status == "DONE"
        application = reload(application)
        assert application.status == "ACCEPTED"
        assert application.outcome == "ACCEPTED"
        assert application.decision_date == TODAY
        assert application.deciding_order_id == order_id
        assert transitions(application)[-2:] == ["ONBOARD", "ACCEPT"]
        assert application.transitions.get(action="ONBOARD").summary == "Onboarded as CMP/1/2026"

    def test_t71_outcome_must_match_onboarding(self, world):
        application = submitted(world)
        problems = actions.validate(
            application,
            order_values(onboard=False, decides=True, outcome="ACCEPTED"),
            complete=False,
        )
        assert [p.code for p in problems] == ["OUTCOME_NOT_ALLOWED"]
        pass_order(application, onboard=True, bring_back_on=D20)
        problems = actions.validate(
            reload(application), order_values(decides=True, outcome="DISMISSED"), complete=False
        )
        assert [p.code for p in problems] == ["OUTCOME_NOT_ALLOWED"]

    def test_t72_defer_review_twice(self, world):
        application = submitted(world)
        for day in (D19, D20):
            assert (
                pass_order(application, onboard=False, decides=False, bring_back_on=day).status
                == "DONE"
            )
        application = reload(application)
        assert application.status == "PENDING_REVIEW"
        assert application.review_due_date == D20
        assert transitions(application).count("DEFER_REVIEW") == 2
        last = application.transitions.filter(action="DEFER_REVIEW").last()
        assert last.metadata == {"from_date": "2026-11-19", "to_date": "2026-11-20"}
        assert last.summary == "Review deferred to 20 Nov"

    def test_t73_same_order_twice_is_applied_once(self, world):
        application = submitted(world)
        order_id = uuid.uuid4()
        pass_order(application, order_id=order_id, onboard=True, bring_back_on=D20)
        again = pass_order(application, order_id=order_id, onboard=True, bring_back_on=D20)
        assert again.payload == {"already_applied": True}
        assert transitions(reload(application)).count("ONBOARD") == 1

    def test_t74_suggested_date(self, world):
        application = submitted(world)
        assert actions.suggested_date(application) is None
        hearing = schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))
        assert actions.suggested_date(application) == hearing.hearing_date

    def test_mandatory_answers_when_complete(self, world):
        application = submitted(world)
        problems = actions.validate(application, {"onboard": True}, complete=True)
        fields = sorted(p.field for p in problems)
        assert fields == ["values.bring_back_on", "values.decides"]


class TestDecision:
    @pytest.fixture
    def onboarded(self, world):
        application = submitted(world)
        pass_order(application, onboard=True, bring_back_on=D20, respond=True, respond_by=D19)
        return reload(application)

    def test_t88_not_open(self, world):
        application = submitted(world)
        pass_order(application, onboard=True, decides=True, outcome="REJECTED")
        assert actions.unavailable_reason(reload(application)) == "APPLICATION_NOT_OPEN"

    def test_t91_dismissal_before_onboarding(self, world):
        application = submitted(world)
        order_id = uuid.uuid4()
        result = pass_order(
            application, order_id=order_id, onboard=False, decides=True, outcome="DISMISSED"
        )
        assert result.status == "DONE"
        application = reload(application)
        assert application.status == "DISMISSED"
        assert application.outcome == "DISMISSED"
        assert application.deciding_order_id == order_id
        assert application.onboarded_at is None
        assert application.earlier_application_number is None

    def test_cis_outcome_asked_only_where_the_state_lists_one(self, world):
        application = submitted(world)
        values = order_values(onboard=False, decides=True, outcome="DISMISSED")
        assert actions.asked(application, values)["cis_outcome"] is False
        set_config("applications", "cis_outcomes", '[{"code": "DISPOSED", "label": "Disposed"}]')
        assert actions.asked(application, values)["cis_outcome"] is True
        problems = actions.validate(application, values, complete=True)
        assert [p.code for p in problems] == ["REQUIRED"]
        wrong = actions.validate(application, {**values, "cis_outcome": "NOPE"}, complete=True)
        assert [p.code for p in wrong] == ["CIS_OUTCOME_INVALID"]
        result = pass_order(
            application, onboard=False, decides=True, outcome="DISMISSED", cis_outcome="DISPOSED"
        )
        assert result.status == "DONE"
        row = reload(application).transitions.get(action="DISMISS")
        assert row.metadata == {"cis_outcome": "DISPOSED"}
        assert reload(application).status == "DISMISSED"

    def test_t94_accept_generic_runs_no_workflow(self, onboarded):
        pass_order(onboarded, decides=True, outcome="ACCEPTED")
        application = reload(onboarded)
        assert application.status == "ACCEPTED"
        assert application.workflow_status == "NOT_APPLICABLE"

    def test_t102_reject_never_runs_on_accept(self, onboarded):
        with mock.patch.object(type(onboarded.spec), "on_accept") as on_accept:
            pass_order(onboarded, decides=True, outcome="REJECTED")
        on_accept.assert_not_called()
        assert reload(onboarded).status == "REJECTED"

    def test_t103_second_order_after_the_first_moved_it(self, world):
        application = submitted(world)
        pass_order(application, onboard=True, bring_back_on=D20)
        result = pass_order(application, onboard=False, decides=True, outcome="DISMISSED")
        assert (result.status, result.error_code) == ("FAILED", "OUTCOME_NOT_ALLOWED")
        pass_order(application, decides=True, outcome="ACCEPTED")
        late = pass_order(application, decides=True, outcome="REJECTED")
        assert (late.status, late.error_code) == ("FAILED", "APPLICATION_NOT_IN_STATUS")
        assert reload(application).status == "ACCEPTED"

    def test_t104_move_the_decision_date(self, onboarded):
        new_date = D20 + datetime.timedelta(days=7)
        result = pass_order(
            onboarded,
            decides=False,
            bring_back_on=new_date,
            respond=True,
            respond_by=new_date - datetime.timedelta(days=1),
        )
        assert result.status == "DONE"
        application = reload(onboarded)
        assert application.status == "PENDING_DECISION"
        assert application.decision_date == new_date
        assert application.respond_by == new_date - datetime.timedelta(days=1)
        row = application.transitions.get(action="MOVE_DECISION_DATE")
        assert row.metadata["from_date"] == "2026-11-20"
        assert row.metadata["to_date"] == new_date.isoformat()

    def test_t106_move_a_decision_set_for_today(self, world):
        application = submitted(world)
        pass_order(application, onboard=True, bring_back_on=TODAY)
        pass_order(application, decides=False, bring_back_on=D20, respond=False)
        application = reload(application)
        assert (application.status, application.decision_date) == ("PENDING_DECISION", D20)
        assert application.objections_invited is False

    def test_t105_new_window_after_the_old_closed(self, world, django_capture_on_commit_callbacks):
        application = submitted(world)
        pass_order(application, onboard=True, bring_back_on=D20, respond=True, respond_by=D19)
        set_config("hearings", "business_date_override", "2026-11-20")
        later = datetime.date(2026, 11, 27)
        with (
            mock.patch("apps.applications.services.notifications.enqueue_sms") as sms,
            django_capture_on_commit_callbacks(execute=True),
        ):
            pass_order(
                application,
                decides=False,
                bring_back_on=later,
                respond=True,
                respond_by=later - datetime.timedelta(days=1),
            )
        keys = [c.args[0] for c in sms.call_args_list]
        assert "APPLICATION_RESPONSE_REQUESTED" in keys
        assert "APPLICATION_DECISION_DATE_MOVED" in keys

    def test_t138_orders_list_oldest_first_with_the_deciding_one_marked(self, onboarded, world):
        from .factories import client_for

        pass_order(onboarded, decides=False, bring_back_on=D20 + datetime.timedelta(days=7))
        decider = uuid.uuid4()
        pass_order(onboarded, order_id=decider, decides=True, outcome="ACCEPTED")
        orders = client_for(world.b1).get(f"/api/v1/applications/{onboarded.pk}/").json()["orders"]
        assert [o["title"] for o in orders] == ["Onboarded", "Decision date moved", "Accepted"]
        assert [o["deciding"] for o in orders] == [False, False, True]
        assert orders[-1]["id"] == str(decider)

    def test_t99_accepting_postpone_must_move_the_hearing(self, world):
        hearing = schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))
        application = submitted(
            world,
            "POSTPONE_HEARING",
            data={"reason_code": "ILLNESS", "proposed_date": "2026-12-04"},
            hearing_id=hearing.pk,
        )
        pass_order(application, onboard=True, bring_back_on=D19)
        refused = pass_order(application, decides=True, outcome="ACCEPTED")
        assert (refused.status, refused.error_code) == ("FAILED", "HEARING_MOVE_REQUIRED")
        done = pass_order(application, decides=True, outcome="ACCEPTED", moves_hearing=True)
        assert done.status == "DONE"
        assert reload(application).workflow_status == "PENDING"


class TestHandler:
    def ctx(self, application, **overrides):
        values = {
            "case_id": application.case_id,
            "order_id": uuid.uuid4(),
            "hearing_id": None,
            "target_type": "APPLICATION",
            "target_id": application.pk,
            **overrides,
        }
        return type("Ctx", (), values)()

    def test_hooks(self, world):
        application = submitted(world)
        handler = ApplicationActionHandler()
        ctx = self.ctx(application)
        assert handler.item_codes == ("APPLICATION_ACTION",)
        assert handler.unavailable_reason(ctx) is None
        assert handler.validate_target(ctx) == []
        assert handler.defaults(ctx)["application_type"] == "Generic"
        assert handler.validate(ctx, order_values(bring_back_on=D20), complete=False) == []
        assert handler.summary(ctx, order_values(bring_back_on=D20)).startswith("Onboarded")
        result = handler.execute(ctx, order_values(bring_back_on=D20), run_id=uuid.uuid4())
        assert result.status == "DONE"

    def test_t90_target_of_another_case_or_not_an_application(self, world):
        application = submitted(world)
        handler = ApplicationActionHandler()
        other_case = self.ctx(application, case_id=uuid.uuid4())
        assert [p.field for p in handler.validate_target(other_case)] == ["target_id"]
        nothing = self.ctx(application, target_type="", target_id=None)
        assert handler.unavailable_reason(nothing) is None
        assert handler.defaults(nothing) == {}
        assert handler.summary(nothing, {}) == ""
        assert handler.validate(nothing, {}, complete=False)[0].field == "target_id"

    def test_closed_target(self, world):
        application = submitted(world)
        pass_order(application, onboard=False, decides=True, outcome="DISMISSED")
        handler = ApplicationActionHandler()
        assert handler.validate_target(self.ctx(application))[0].code == "APPLICATION_NOT_OPEN"
        assert handler.unavailable_reason(self.ctx(application)) == "APPLICATION_NOT_OPEN"

    def test_registration_waits_for_the_orders_module(self):
        assert register_with_orders() is False
        registry = mock.Mock()
        with mock.patch("apps.applications.handlers.import_module", return_value=registry):
            assert register_with_orders() is True
        registry.register.assert_called_once()
