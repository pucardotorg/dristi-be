"""Court roles count only at the deployment's establishment (``RLE-00``, ``RLE-02c``, ``RLE-06``).

Roles are Django groups, held across the deployment, so ``SCRUTINY_ESTABLISHMENT_ID``
names the one establishment they apply at. A second court in the same
deployment is closed to everyone: its cases are not found, not listed and not
acted on, and its roles never combine with the configured court's (``SCR-11``).
"""

import pytest
from django.core.checks import run_checks
from django.urls import reverse

from apps.api.errors import BusinessError
from apps.cases.models import CaseStatus
from apps.cases.services import filing
from apps.scrutiny import permissions, ports, selectors
from apps.scrutiny.enums import CourtRole, RoundStage
from apps.scrutiny.models import ScrutinyRound
from apps.scrutiny.services import rounds
from apps.scrutiny.system_checks import check_establishment_exists, check_establishment_setting

from .factories import add_courtroom, code, draft_field, enter, make_case, make_paid_case
from .test_api import client_for, error_codes, registration_url, url

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_case(filer, establishment, other_establishment):
    """A case whose round sits at a court this deployment does not serve.

    Submission always routes to the configured establishment, so the round is
    moved there by hand, as a second deployment's own case would be.
    """
    other = make_case(filer, other_establishment, filing_number="F/OTH/2026/00001")
    ScrutinyRound.objects.filter(case=other).update(establishment_id=other_establishment.pk)
    return other


# Routing (#2.5): a paid case goes to the configured establishment, whatever court the filer gave


def submit(case, user):
    return client_for(user).post(reverse("case-submit-for-scrutiny", args=[case.pk]))


@pytest.fixture
def courtroom(establishment):
    return add_courtroom(establishment, "Courtroom 1")


@pytest.mark.parametrize("filed_in", ["none", "establishment", "courtroom", "other court"])
def test_submission_routes_to_the_configured_establishment(
    filer, officer, establishment, courtroom, other_establishment, filed_in
):
    court = {
        "none": None,
        "establishment": establishment,
        "courtroom": courtroom,
        "other court": other_establishment,
    }[filed_in]
    case = make_paid_case(filer, court)

    response = submit(case, filer)

    assert response.status_code == 200
    assert response.json()["status"] == CaseStatus.UNDER_SCRUTINY
    round_ = ScrutinyRound.objects.get(case=case)
    assert (round_.stage, round_.establishment_id, round_.courtroom_id) == (
        RoundStage.SCRUTINY,
        establishment.pk,
        None,
    )
    # The officer finds it, reads it and can act on it.
    assert permissions.court_case(case.pk, officer) == (case, round_)
    listed = client_for(officer).get("/api/v1/scrutiny/").json()
    assert [row["case_id"] for row in listed["results"]] == [str(case.pk)]
    assert client_for(officer).get(url(case)).status_code == 200


@pytest.mark.parametrize("filed_in", ["none", "other court"])
def test_misfiled_case_can_be_forwarded_to_a_courtroom_here(
    filer, officer, establishment, courtroom, other_establishment, filed_in
):
    case = make_paid_case(filer, None if filed_in == "none" else other_establishment)
    assert submit(case, filer).status_code == 200

    rounds.forward(case.pk, officer, courtroom_id=courtroom.pk)

    case.refresh_from_db()
    assert (case.status, case.court_id) == (CaseStatus.PENDING_REGISTRATION, courtroom.pk)
    registration = ScrutinyRound.objects.get(case=case, decision="")
    assert registration.establishment_id == establishment.pk


@pytest.mark.parametrize("value", ["", "not-a-uuid"])
def test_submission_refused_without_a_configured_establishment(
    filer, establishment, settings, value
):
    case = make_paid_case(filer, establishment)
    settings.SCRUTINY_ESTABLISHMENT_ID = value

    response = submit(case, filer)

    assert (response.status_code, error_codes(response)) == (503, {None: ["E09019"]})
    case.refresh_from_db()
    assert case.status == CaseStatus.PENDING_PAYMENT
    assert not ScrutinyRound.objects.filter(case=case).exists()


def test_service_refuses_and_rolls_back_without_an_establishment(filer, establishment, settings):
    case = make_paid_case(filer, establishment)
    settings.SCRUTINY_ESTABLISHMENT_ID = ""

    with pytest.raises(BusinessError) as excinfo:
        filing.submit_for_scrutiny(case.pk, filer)

    assert code(excinfo) == "E09019"
    case.refresh_from_db()
    assert case.status == CaseStatus.PENDING_PAYMENT


def test_a_case_back_in_scrutiny_keeps_its_establishment(case, officer, establishment, settings):
    draft_field(case, officer, "CHQ-3[0]")
    rounds.send_back(case.pk, officer)
    settings.SCRUTINY_ESTABLISHMENT_ID = ""

    enter(case, CaseStatus.UNDER_SCRUTINY)

    assert ScrutinyRound.objects.get(case=case, decision="").establishment_id == establishment.pk


# Roles


def test_roles_count_only_at_the_configured_establishment(
    officer_registerer, establishment, other_establishment
):
    both = {CourtRole.SCRUTINY_OFFICER, CourtRole.CASE_REGISTERER}
    assert ports.roles_held(officer_registerer, establishment.pk) == both
    assert ports.roles_held(officer_registerer, str(establishment.pk)) == both
    assert ports.roles_held(officer_registerer, other_establishment.pk) == frozenset()
    assert ports.roles_held(officer_registerer, None) == frozenset()


@pytest.mark.parametrize("value", ["", "not-a-uuid"])
def test_no_roles_anywhere_without_a_valid_establishment(officer, establishment, settings, value):
    settings.SCRUTINY_ESTABLISHMENT_ID = value
    assert ports.configured_establishment() is None
    assert ports.roles_held(officer, establishment.pk) == frozenset()


# Reading


def test_other_courts_cases_are_not_found(case, other_case, officer, registerer):
    for user in (officer, registerer):
        client = client_for(user)
        for path in (url(other_case), url(other_case, "history"), registration_url(other_case)):
            assert client.get(path).status_code == 404
        assert client.get(url(case)).status_code == 200


def test_unset_establishment_closes_everything(case, officer, settings):
    settings.SCRUTINY_ESTABLISHMENT_ID = ""
    client = client_for(officer)
    assert client.get(url(case)).status_code == 404
    for path in ("/api/v1/scrutiny/", "/api/v1/registration/"):
        response = client.get(path)
        assert (response.status_code, error_codes(response)) == (403, {None: ["E09008"]})


# Lists


def test_lists_show_only_the_configured_establishment(
    case, other_case, other_establishment, establishment, officer, registerer, settings
):
    listed = client_for(officer).get("/api/v1/scrutiny/").json()
    assert [row["case_id"] for row in listed["results"]] == [str(case.pk)]
    assert listed["counts"]["registry"] == 1

    rounds.forward(case.pk, officer)
    # The other court's case reaches registration as its own deployment would forward it.
    settings.SCRUTINY_ESTABLISHMENT_ID = str(other_establishment.pk)
    rounds.forward(other_case.pk, officer)
    settings.SCRUTINY_ESTABLISHMENT_ID = str(establishment.pk)
    assert ScrutinyRound.objects.filter(stage=RoundStage.REGISTRATION, decision="").count() == 2
    listed = client_for(registerer).get("/api/v1/registration/").json()
    assert [row["case_id"] for row in listed["results"]] == [str(case.pk)]


def test_lists_refuse_another_establishment(case, other_establishment, officer, registerer):
    for user, path in ((officer, "/api/v1/scrutiny/"), (registerer, "/api/v1/registration/")):
        response = client_for(user).get(path, {"establishment": str(other_establishment.pk)})
        assert (response.status_code, error_codes(response)) == (403, {None: ["E09008"]})


def test_list_of_the_configured_establishment_by_name(case, officer, establishment):
    response = client_for(officer).get(
        "/api/v1/scrutiny/", {"establishment": str(establishment.pk)}
    )
    assert [row["case_id"] for row in response.json()["results"]] == [str(case.pk)]
    assert permissions.require_court_reader(officer) == establishment.pk


# Acting


@pytest.mark.parametrize("action", ["start", "send-back", "forward", "register", "title"])
def test_other_courts_cases_cannot_be_acted_on(other_case, officer_registerer, action):
    client = client_for(officer_registerer)
    if action == "title":
        response = client.patch(
            url(other_case, "title"), {"complainant": "A", "accused": "B"}, format="json"
        )
    else:
        response = client.post(url(other_case, action), {}, format="json")
    assert response.status_code == 404
    other_case.refresh_from_db()
    assert (other_case.status, other_case.case_number) == (CaseStatus.UNDER_SCRUTINY, None)


def test_services_refuse_another_courts_case(other_case, officer, officer_registerer):
    with pytest.raises(BusinessError) as excinfo:
        draft_field(other_case, officer, "CHQ-3[0]")
    assert code(excinfo) == "E09008"
    for decide in (rounds.send_back, rounds.forward):
        with pytest.raises(BusinessError) as excinfo:
            decide(other_case.pk, officer)
        assert code(excinfo) == "E09008"
    # SCR-11: both roles are held, but not at this case's court, so it cannot be registered here.
    with pytest.raises(BusinessError) as excinfo:
        rounds.register_at_scrutiny(other_case.pk, officer_registerer)
    assert code(excinfo) == "E09008"
    assert (
        selectors.allowed_actions(
            ScrutinyRound.objects.get(case=other_case),
            ports.roles_held(officer_registerer, other_case.court_id),
        )
        == []
    )


# System checks


def test_check_warns_when_unset(settings):
    settings.SCRUTINY_ESTABLISHMENT_ID = ""
    assert [message.id for message in check_establishment_setting(None)] == ["scrutiny.W001"]


def test_check_refuses_a_malformed_value(settings):
    settings.SCRUTINY_ESTABLISHMENT_ID = "court-a"
    assert [message.id for message in check_establishment_setting(None)] == ["scrutiny.E001"]


def test_check_accepts_the_establishment(establishment):
    assert check_establishment_setting(None) == []
    assert check_establishment_exists(None, databases=["default"]) == []


def test_check_refuses_an_unknown_or_inactive_establishment(establishment, settings):
    establishment.is_active = False
    establishment.save()
    assert [m.id for m in check_establishment_exists(None, databases=["default"])] == [
        "scrutiny.E002"
    ]
    settings.SCRUTINY_ESTABLISHMENT_ID = "00000000-0000-0000-0000-000000000000"
    assert [m.id for m in check_establishment_exists(None, databases=["default"])] == [
        "scrutiny.E002"
    ]


def test_database_check_runs_only_with_a_database(establishment):
    establishment.is_active = False
    establishment.save()
    assert check_establishment_exists(None) == []
    assert "scrutiny.E002" not in {message.id for message in run_checks()}
