"""Application numbers (spec 0033 #7, ``ALC-02``, #17.4)."""

import datetime

import pytest
from django.core.management import call_command

from apps.api.errors import BusinessError
from apps.applications.models import Application, ApplicationCounter
from apps.applications.services import numbering
from apps.core.models import Configuration

from .factories import client_for, make_case, pass_order, set_config, submitted

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 12)


def onboard(application, **values):
    from apps.applications.services.calendar import today

    result = pass_order(application, onboard=True, decides=False, bring_back_on=today(), **values)
    assert result.status == "DONE", result
    return Application.objects.get(pk=application.pk)


def test_t57_kerala_number_from_submission(world):
    for _ in range(2):
        submitted(world)
    third = submitted(world)
    assert third.application_number == f"{world.case.filing_number}-AP3"


def test_t58_replaced_at_onboarding_kept_and_searchable(world):
    application = submitted(world)
    first = application.application_number
    application = onboard(application)
    assert application.application_number == "CMP/1/2026"
    assert application.earlier_application_number == first
    rows = (
        client_for(world.b1)
        .get(f"/api/v1/cases/{world.case.pk}/applications/", {"search": first})
        .json()["results"]
    )
    assert [r["id"] for r in rows] == [str(application.pk)]
    second = onboard(submitted(world))
    assert second.application_number == "CMP/2/2026"


def test_t58_new_year_restarts_the_replacement_series(world):
    onboard(submitted(world))
    set_config("hearings", "business_date_override", "2027-01-04")
    application = onboard(submitted(world))
    assert application.application_number == "CMP/1/2027"


def test_t59_court_scope_continues_across_cases(world):
    set_config("applications", "submission_number_format", "CRM/{n}/{year}")
    set_config("applications", "submission_number_scope", "COURT")
    set_config("applications", "replace_on_onboarding", "false")
    first = submitted(world)
    other_world = world
    other_case = make_case(world.court)
    from apps.cases.models import ParticipantRole

    from .factories import add_party, represent

    party = add_party(other_case, ParticipantRole.COMPLAINANT, "Other")
    add_party(other_case, ParticipantRole.ACCUSED, "Other accused")
    represent(other_case, world.a1, party)
    other_world.case = other_case
    other_world.complainant = party
    second = submitted(other_world)
    assert first.application_number == "CRM/1/2026"
    assert second.application_number == "CRM/2/2026"
    assert onboard(second).earlier_application_number is None


def test_t60_counter_gives_consecutive_numbers(world):
    numbers = [submitted(world).application_number for _ in range(5)]
    assert numbers == [f"{world.case.filing_number}-AP{n}" for n in range(1, 6)]
    counter = ApplicationCounter.objects.get(kind="SUBMISSION")
    assert counter.last_number == 5
    assert counter.year == 0  # Kerala's submission series does not restart yearly


def test_t61_hand_set_number_is_skipped(world):
    first = submitted(world)
    Application.objects.filter(pk=first.pk).update(
        application_number=f"{world.case.filing_number}-AP2"
    )
    second = submitted(world)
    assert second.application_number == f"{world.case.filing_number}-AP3"


def test_t62_no_submission_format(world):
    Configuration.objects.filter(config_key="submission_number_format").delete()
    with pytest.raises(BusinessError) as caught:
        submitted(world)
    assert caught.value.error.code == "E13028"


def test_t62_system_check_warns(world):
    Configuration.objects.filter(config_key="submission_number_format").delete()
    from apps.applications.checks import numbering_configured

    warnings = numbering_configured(databases=["default"])
    assert [w.id for w in warnings] == ["applications.W001"]
    set_config("applications", "submission_number_format", "{n}")
    assert numbering_configured(databases=["default"]) == []
    assert numbering_configured(databases=None) == []


def test_t63_gujarat_keeps_its_submission_number(world):
    set_config("applications", "submission_number_format", "APP/{n}/{year}")
    set_config("applications", "replace_on_onboarding", "false")
    application = onboard(submitted(world))
    assert application.application_number == "APP/1/2026"
    assert application.earlier_application_number is None


def test_t64_dismissal_cites_the_number_in_use(world):
    from apps.applications.services import actions

    application = submitted(world)
    assert actions.defaults(application)["application_number"] == application.application_number


def test_numbers_from_cis_submits_without_a_number(world):
    set_config("applications", "numbers_from_cis", "true")
    application = submitted(world)
    assert application.status == "PENDING_REVIEW"
    assert application.application_number is None


def test_number_taken_at_the_same_moment(world):
    from django.db import IntegrityError

    def clash():
        raise IntegrityError("duplicate")

    with pytest.raises(BusinessError) as caught:
        numbering.guard_number_clash(clash)
    assert caught.value.error.code == "E13027"


def test_runaway_series_gives_up(world, monkeypatch):
    monkeypatch.setattr(numbering, "MAX_SKIPS", 2)
    monkeypatch.setattr(numbering, "_taken", lambda *args: True)
    with pytest.raises(BusinessError) as caught:
        submitted(world)
    assert caught.value.error.code == "E13027"


def test_seed_is_idempotent(world):
    call_command("seed", "--list", stdout=__import__("io").StringIO())
    from .factories import seed_applications

    seed_applications()
