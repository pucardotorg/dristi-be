"""Reads: the selectors other modules use, the API's queries, the cases contract (spec 0023 #1.1, #10, #11.7)."""

import datetime
import uuid

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.cases import selectors as cases
from apps.cases.models import CaseParticipant, CaseStatus, ParticipantRole, Representation
from apps.hearings import ports, queries, selectors
from apps.hearings.enums import HearingRole
from apps.hearings.services import courtroom as court_service
from apps.hearings.services import listing
from apps.parties.models import Person
from apps.parties.tests.factories import make_address

from .factories import MON, TODAY, TUE, WED, hold, make_case, schedule, set_config

pytestmark = pytest.mark.django_db


class TestSelectors:
    def test_get_hearing(self, case):
        hearing = schedule(case, MON)
        ref = selectors.get_hearing(hearing.pk)
        assert (ref.id, ref.status, ref.purpose_code, ref.hearing_date) == (
            hearing.pk,
            "SCHEDULED",
            "APPEARANCE",
            MON,
        )

    def test_next_hearing_prefers_the_one_in_progress(self, case):
        today = schedule(case, TODAY)
        court_service.start(hearing_id=today.pk)
        schedule(case, MON)
        assert selectors.next_hearing(case.pk).id == today.pk
        assert selectors.has_scheduled_hearing(case.pk)

    def test_no_next_hearing(self, case):
        hold(case, MON)
        assert selectors.next_hearing(case.pk) is None
        assert not selectors.has_scheduled_hearing(case.pk)

    def test_hearings_of_case_hide_holds(self, case):
        schedule(case, MON)
        hold(case, TUE)
        assert [ref.status for ref in selectors.hearings_of_case(case.pk)] == ["SCHEDULED"]

    def test_adjournment_counts(self, case):
        first = schedule(case, TODAY)
        court_service.start(hearing_id=first.pk)
        court_service.end(hearing_id=first.pk, adjournment_sought_by="COMPLAINANT")
        second = schedule(case, MON)
        from apps.hearings.services import reschedule

        reschedule.reschedule(hearing_id=second.pk, hearing_date=TUE, reason_code="NOT_REACHED")
        assert selectors.adjournment_counts(case.pk) == {"COMPLAINANT": 1, "ACCUSED": 0, "COURT": 1}
        assert queries.adjournment_counts_for([case.pk])[case.pk] == selectors.adjournment_counts(
            case.pk
        )

    def test_stale_holds(self, case, courtroom):
        held = hold(case, MON).hearing
        assert selectors.stale_holds(courtroom.pk) == 0
        type(held).objects.filter(pk=held.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=8)
        )
        assert selectors.stale_holds(courtroom.pk) == 1
        set_config("stale_hold_days", "10")
        assert selectors.stale_holds(courtroom.pk) == 0


class TestHearingViews:
    def test_one_batched_call_per_contract_function(self, courtroom, monkeypatch):
        hearings = [schedule(make_case(courtroom), MON) for _ in range(5)]
        calls = []
        real_summaries, real_advocates = cases.get_case_summaries, cases.get_case_advocates
        monkeypatch.setattr(
            queries.cases,
            "get_case_summaries",
            lambda ids: calls.append("s") or real_summaries(ids),
        )
        monkeypatch.setattr(
            queries.cases,
            "get_case_advocates",
            lambda ids: calls.append("a") or real_advocates(ids),
        )
        with CaptureQueriesContext(connection) as captured:
            views = queries.hearing_views(hearings, roles={HearingRole.HEARING_CONTROLLER})
        assert sorted(calls) == ["a", "s"]
        assert len(views) == 5
        assert len(captured) <= 8

    def test_allowed_actions_follow_roles(self, case):
        hearing = schedule(case, TODAY)
        controller = queries.hearing_view(hearing, {HearingRole.HEARING_CONTROLLER})
        setter = queries.hearing_view(hearing, {HearingRole.NEXT_HEARING_SETTER})
        party = queries.hearing_view(hearing, frozenset())
        assert controller["allowed_actions"] == ["start", "pass_over"]
        assert setter["allowed_actions"] == ["reschedule", "cancel"]
        assert "allowed_actions" not in party

    def test_trial_target(self, courtroom):
        old = make_case(courtroom, filed_days_ago=200)
        new = make_case(courtroom, filed_days_ago=5)
        views = {
            v["case"]["id"]: v["case"]
            for v in queries.hearing_views([schedule(old, MON), schedule(new, MON)], roles=set())
        }
        assert views[old.pk]["beyond_trial_target"] is True
        assert views[new.pk]["beyond_trial_target"] is False
        set_config("trial_target_days", "3")
        assert queries.hearing_view(schedule(make_case(courtroom), MON), set())["case"][
            "beyond_trial_target"
        ]


class TestBoard:
    def test_defaults_to_todays_board(self, case, other_case, third_case):
        today = schedule(case, TODAY)
        schedule(other_case, MON)
        hold(third_case, TODAY)
        assert [h.pk for h in queries.board(case.court_id, {})] == [today.pk]

    def test_filters(self, courtroom, case, other_case, advocate_user):
        mine = schedule(case, MON, "ARGUMENTS")
        schedule(other_case, MON)
        advocate = cases.get_case_advocates([case.pk])[case.pk][0]
        assert [
            h.pk for h in queries.board(courtroom.pk, {"date": [MON], "purpose": ["ARGUMENTS"]})
        ] == [mine.pk]
        assert [
            h.pk for h in queries.board(courtroom.pk, {"date": [MON], "advocate": [advocate.id]})
        ] == [mine.pk]
        assert [
            h.pk for h in queries.board(courtroom.pk, {"date": [MON], "search": case.case_number})
        ] == [mine.pk]
        assert [h.pk for h in queries.board(courtroom.pk, {"case": case.pk})] == [mine.pk]

    def test_not_reached_and_changed_since(self, case, other_case):
        abandoned = schedule(case, TODAY)
        court_service.end_day(case.court_id, TODAY)
        set_config("business_date_override", MON.isoformat())
        assert [h.pk for h in queries.board(case.court_id, {"not_reached": True})] == [abandoned.pk]
        since = timezone.now()
        moved = schedule(other_case, TUE)
        found = queries.board(
            case.court_id, {"changed_since": since, "date_from": MON, "date_to": WED}
        )
        assert [h.pk for h in found] == [moved.pk]

    def test_beyond_trial_target_filter(self, courtroom):
        old = schedule(make_case(courtroom, filed_days_ago=200), MON)
        new = schedule(make_case(courtroom, filed_days_ago=5), MON)
        assert [
            h.pk for h in queries.board(courtroom.pk, {"date": [MON], "beyond_trial_target": True})
        ] == [old.pk]
        assert [
            h.pk for h in queries.board(courtroom.pk, {"date": [MON], "beyond_trial_target": False})
        ] == [new.pk]

    def test_ordering(self, case, other_case):
        first, second = schedule(case, MON), schedule(other_case, MON)
        assert [
            h.pk for h in queries.board(case.court_id, {"date": [MON], "ordering": "-sequence"})
        ] == [
            second.pk,
            first.pk,
        ]

    @pytest.mark.parametrize(
        ("filters", "expected"),
        [
            ({}, True),
            ({"date": [MON]}, True),
            ({"date": [MON, TUE]}, False),
            ({"not_reached": True}, False),
            ({"case": "x"}, False),
            ({"case": "x", "date": [MON]}, True),
            ({"date_from": MON}, False),
        ],
    )
    def test_is_one_day(self, filters, expected):
        assert queries.is_one_day(filters) is expected


class TestCountsAndQueue:
    def test_counts(self, case, other_case, courtroom):
        running = schedule(case, TODAY)
        court_service.start(hearing_id=running.pk)
        schedule(other_case, TODAY)
        result = queries.counts(courtroom.pk)
        assert result["today"] == 2
        assert (result["by_status"]["IN_PROGRESS"], result["by_status"]["SCHEDULED"]) == (1, 1)

    def test_queue_reasons(self, courtroom, case, other_case, third_case):
        heard = schedule(other_case, TODAY)
        court_service.start(hearing_id=heard.pk)
        court_service.end(hearing_id=heard.pk)
        cancelled = schedule(third_case, MON)
        listing.cancel_listed_in_error(hearing_id=cancelled.pk)
        reasons = {
            item["case"]["id"]: item["reason"] for item in queries.scheduling_queue(courtroom.pk)
        }
        assert reasons == {
            case.pk: "NEWLY_REGISTERED",
            other_case.pk: "NO_NEXT_DATE",
            third_case.pk: "HEARING_CANCELLED",
        }
        assert queries.counts(courtroom.pk)["scheduling_queue"] == 3

    def test_queue_reason_is_the_latest_event_not_the_latest_date(self, courtroom, case):
        """A hearing cancelled earlier but listed later used to win over today's heard one (bug)."""
        cancelled = schedule(case, WED)
        listing.cancel_listed_in_error(hearing_id=cancelled.pk)
        heard = schedule(case, TODAY)
        court_service.start(hearing_id=heard.pk)
        court_service.end(hearing_id=heard.pk)
        (item,) = queries.scheduling_queue(courtroom.pk)
        assert item["reason"] == "NO_NEXT_DATE"
        heard.refresh_from_db()
        assert item["waiting_since"] == heard.ended_at

    def test_live_hearings_leave_the_queue(self, courtroom, case, other_case):
        schedule(case, MON)
        hold(other_case, MON)
        assert queries.scheduling_queue(courtroom.pk) == []


class TestCasesContract:
    def test_listability(self, courtroom):
        registered = make_case(courtroom)
        draft = make_case(courtroom, status=CaseStatus.UNDER_SCRUTINY)
        assert cases.get_listability(registered.pk).listable
        assert cases.get_listability(draft.pk).reason == "NOT_REGISTERED"
        unknown = cases.get_listability(uuid.uuid4())
        assert (unknown.listable, unknown.reason, unknown.court_id) == (
            False,
            "NOT_REGISTERED",
            None,
        )

    def test_one_advocate_for_two_parties_on_a_side_is_listed_once(self, case, advocate_user):
        second = CaseParticipant.objects.create(
            case=case,
            person=Person.objects.create(name="Second complainant", phone_number="+919811111111"),
            role=ParticipantRole.COMPLAINANT,
            ordinal=2,
            name_at_filing="Second complainant",
            address=make_address(),
            is_party_in_person=False,
        )
        Representation.objects.create(
            case=case, advocate=advocate_user.advocate_profile, case_participant=second
        )
        advocates = [c for c in cases.get_case_contacts(case.pk) if c.kind == "ADVOCATE"]
        assert [(c.phone, c.side) for c in advocates] == [
            (advocate_user.mobile_number, "COMPLAINANT")
        ]
        refs = cases.get_case_advocates([case.pk])[case.pk]
        assert [(ref.id, ref.side) for ref in refs] == [
            (advocate_user.advocate_profile.pk, "COMPLAINANT")
        ]

    def test_contacts_and_summaries(self, case):
        contacts = cases.get_case_contacts(case.pk)
        assert {(c.kind, c.side) for c in contacts} == {
            ("COMPLAINANT", "COMPLAINANT"),
            ("ACCUSED", "ACCUSED"),
            ("ADVOCATE", "COMPLAINANT"),
        }
        summary = cases.get_case_summaries([case.pk])[case.pk]
        assert summary.title.startswith("Complainant") and " v. Accused" in summary.title

    def test_visibility(self, case, complainant_user, advocate_user, stranger):
        assert case.pk in set(cases.case_ids_visible_to(complainant_user))
        assert case.pk in set(cases.case_ids_visible_to(advocate_user))
        assert case.pk in set(cases.case_ids_visible_to(case.created_by))
        assert list(cases.case_ids_visible_to(stranger)) == []

    def test_search_and_awaiting(self, courtroom, case):
        assert list(cases.search_case_ids(case.case_number, courtroom.pk)) == [case.pk]
        assert list(cases.search_case_ids("advocate", courtroom.pk)) == [case.pk]
        assert case.pk in set(cases.cases_awaiting_hearing(courtroom.pk))

    def test_blank_search_does_not_filter(self, courtroom, case, other_case, foreign_court):
        make_case(foreign_court)
        assert set(cases.search_case_ids("   ", courtroom.pk)) == {case.pk, other_case.pk}

    def test_filed_before(self, courtroom):
        old = make_case(courtroom, filed_days_ago=30)
        make_case(courtroom, filed_days_ago=1)
        cutoff = timezone.now() - datetime.timedelta(days=10)
        assert list(cases.case_ids_filed_before(cutoff)) == [old.pk]


class TestCourtRoles:
    """The placeholder roles count at the configured establishment only (``ports``)."""

    def test_establishment_itself_and_its_courtrooms(self, establishment, courtroom, controller):
        assert ports.court_roles(controller, establishment.pk) == {HearingRole.HEARING_CONTROLLER}
        assert ports.court_roles(controller, courtroom.pk) == {HearingRole.HEARING_CONTROLLER}

    def test_misconfigured_establishment_grants_nothing(self, courtroom, controller, settings):
        settings.SCRUTINY_ESTABLISHMENT_ID = "not-a-uuid"
        assert ports.configured_establishment() is None
        assert ports.court_roles(controller, courtroom.pk) == frozenset()
