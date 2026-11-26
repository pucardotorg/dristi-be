"""Scrutiny on court roles (spec 0029 #10.1, #12 "Scrutiny").

A case goes to the deployment's establishment (``SCRUTINY_ESTABLISHMENT_ID``,
``RLE-00``), whatever court it names. Each step is a court
action checked at the round's establishment, lists cover every establishment
where the caller holds the stage's actions, and reading follows any scrutiny
or registration action at the latest round's establishment.
"""

import pytest
from django.contrib.auth.models import Group
from django.core.checks import run_checks
from django.urls import reverse

from apps.api.errors import BusinessError
from apps.cases.models import CaseStatus
from apps.cases.services import filing
from apps.organizations.models import Organization, OrganizationType
from apps.scrutiny import court_actions as actions
from apps.scrutiny import permissions, selectors
from apps.scrutiny.enums import RoundDecision, RoundStage
from apps.scrutiny.models import ScrutinyRound
from apps.scrutiny.services import rounds
from apps.scrutiny.system_checks import check_establishment_exists, check_establishment_setting

from .factories import (
    CASE_REGISTERER,
    SCRUTINY_OFFICER,
    code,
    draft_field,
    enter,
    grant,
    make_case,
    make_establishment,
    make_paid_case,
    make_user,
    open_round,
    place_at,
)
from .test_api import client_for, error_codes, registration_url, url

pytestmark = pytest.mark.django_db


def submit(case, user):
    return client_for(user).post(reverse("case-submit-for-scrutiny", args=[case.pk]))


def offered(case, user):
    round_ = open_round(case)
    return selectors.allowed_actions(
        round_, permissions.actions_held(user, round_.establishment_id)
    )


@pytest.fixture
def other_case(filer, establishment, other_establishment):
    """A case whose round sits at a second establishment."""
    case = make_case(filer, other_establishment, filing_number="F/OTH/2026/00001")
    return place_at(case, other_establishment)


# Routing (#2.5): a paid case goes to the configured establishment, whatever court it names


@pytest.mark.parametrize(
    "filed_in", ["none", "establishment", "courtroom", "other establishment", "not a court"]
)
def test_submission_routes_to_the_configured_establishment(
    filer, officer, establishment, other_establishment, filed_in
):
    court = {
        "none": None,
        "establishment": establishment,
        "courtroom": establishment.children.get(),
        "other establishment": other_establishment,
        "not a court": Organization.objects.create(
            code="DC", name="District court", organization_type=OrganizationType.DISTRICT_COURT
        ),
    }[filed_in]
    case = make_paid_case(filer, court)

    response = submit(case, filer)

    assert (response.status_code, response.json()["status"]) == (200, CaseStatus.UNDER_SCRUTINY)
    round_ = ScrutinyRound.objects.get(case=case)
    assert (round_.stage, round_.establishment_id, round_.courtroom_id) == (
        RoundStage.SCRUTINY,
        establishment.pk,
        None,
    )
    assert permissions.court_case(case.pk, officer) == (case, round_)
    listed = client_for(officer).get("/api/v1/scrutiny/").json()
    assert [row["case_id"] for row in listed["results"]] == [str(case.pk)]


@pytest.mark.parametrize("filed_in", ["none", "other establishment"])
def test_misfiled_case_is_forwarded_to_a_courtroom_here(
    filer, officer, establishment, other_establishment, filed_in
):
    case = make_paid_case(filer, None if filed_in == "none" else other_establishment)
    assert submit(case, filer).status_code == 200
    courtroom = establishment.children.get()

    rounds.forward(case.pk, officer, courtroom_id=courtroom.pk)

    case.refresh_from_db()
    assert (case.status, case.court_id) == (CaseStatus.PENDING_REGISTRATION, courtroom.pk)
    assert open_round(case).establishment_id == establishment.pk


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


def test_a_case_back_in_scrutiny_keeps_its_establishment(
    case, officer, establishment, other_establishment, settings
):
    draft_field(case, officer, "CHQ-3[0]")
    rounds.send_back(case.pk, officer)
    settings.SCRUTINY_ESTABLISHMENT_ID = str(other_establishment.pk)

    enter(case, CaseStatus.UNDER_SCRUTINY)

    assert open_round(case).establishment_id == establishment.pk


def test_courtroom_is_chosen_among_the_establishments_own(case, officer, other_establishment):
    elsewhere = other_establishment.children.get()
    with pytest.raises(BusinessError) as excinfo:
        rounds.forward(case.pk, officer, courtroom_id=elsewhere.pk)
    assert code(excinfo) == "E09017"


def test_an_establishment_without_courtrooms_cannot_forward(filer, establishment):
    bare = make_establishment("BARE", "No courtrooms yet")
    officer = make_user(SCRUTINY_OFFICER, at=bare)
    case = place_at(make_case(filer, bare), bare)
    with pytest.raises(BusinessError) as excinfo:
        rounds.forward(case.pk, officer)
    assert code(excinfo) == "E09017"


# Who may act: one action per step, at the round's establishment


def test_a_role_at_a_courtroom_acts_at_its_establishment(case, filer, establishment):
    courtroom_officer = make_user(SCRUTINY_OFFICER, at=establishment.children.get())
    rounds.start(case.pk, courtroom_officer, RoundStage.SCRUTINY)
    assert open_round(case).started_by == courtroom_officer


def test_flag_without_forward_is_not_offered_forward(case, establishment):
    flagger = make_user(actions.FLAG, at=establishment)
    assert offered(case, flagger) == ["start", "flag"]
    draft_field(case, flagger, "CHQ-3[0]")
    with pytest.raises(BusinessError) as excinfo:
        rounds.forward(case.pk, flagger)
    assert code(excinfo) == "E09008"
    with pytest.raises(BusinessError) as excinfo:
        rounds.send_back(case.pk, flagger)
    assert code(excinfo) == "E09008"


def test_forward_needs_the_courtroom_choice(case, establishment):
    forwarder = make_user(actions.FORWARD, at=establishment)
    assert "forward" not in offered(case, forwarder)
    with pytest.raises(BusinessError) as excinfo:
        rounds.forward(case.pk, forwarder)
    assert code(excinfo) == "E09008"


def test_send_back_only_starts_scrutiny_but_not_registration(case, officer, establishment):
    sender = make_user(actions.SEND_BACK, at=establishment)
    client = client_for(sender)
    assert client.get("/api/v1/scrutiny/").status_code == 200
    rounds.start(case.pk, sender, RoundStage.SCRUTINY)

    rounds.forward(case.pk, officer)
    with pytest.raises(BusinessError) as excinfo:
        rounds.start(case.pk, sender, RoundStage.REGISTRATION)
    assert code(excinfo) == "E09008"
    response = client.get("/api/v1/registration/")
    assert (response.status_code, error_codes(response)) == (403, {None: ["E09008"]})


def test_no_stage_action_cannot_start(case, establishment):
    clerk = make_user(at=establishment)
    with pytest.raises(BusinessError) as excinfo:
        rounds.start(case.pk, clerk, RoundStage.SCRUTINY)
    assert code(excinfo) == "E09008"


def test_registration_steps_need_their_own_actions(case, officer, establishment):
    rounds.forward(case.pk, officer)
    registrar = make_user(actions.REGISTER, at=establishment)
    returner = make_user(actions.REGISTRATION_SEND_BACK, at=establishment)
    assert offered(case, registrar) == ["start", "register"]
    assert offered(case, returner) == ["start", "send_back"]
    with pytest.raises(BusinessError) as excinfo:
        rounds.registration_send_back(case.pk, registrar, "Re-check.")
    assert code(excinfo) == "E09008"
    with pytest.raises(BusinessError) as excinfo:
        rounds.register(case.pk, returner)
    assert code(excinfo) == "E09008"
    rounds.register(case.pk, registrar)
    assert ScrutinyRound.objects.get(case=case, stage=RoundStage.REGISTRATION).decision == (
        RoundDecision.REGISTERED
    )


def test_groups_and_superusers_allow_nothing(case):
    grouped = make_user()
    grouped.groups.add(Group.objects.create(name="SCRUTINY_OFFICER"))
    superuser = make_user()
    superuser.is_superuser = superuser.is_staff = True
    superuser.save()
    for user in (grouped, superuser):
        assert client_for(user).get(url(case)).status_code == 404
        response = client_for(user).get("/api/v1/scrutiny/")
        assert (response.status_code, error_codes(response)) == (403, {None: ["E09008"]})


# SCR-11 across courts: both actions must be held at the round's establishment


def test_register_elsewhere_still_forwards_here(case, establishment, other_establishment):
    user = make_user(SCRUTINY_OFFICER, at=establishment)
    grant(user, other_establishment, CASE_REGISTERER)

    assert offered(case, user) == ["start", "flag", "send_back", "forward"]
    with pytest.raises(BusinessError) as excinfo:
        rounds.register_at_scrutiny(case.pk, user)
    assert code(excinfo) == "E09007"
    rounds.forward(case.pk, user)
    assert open_round(case).stage == RoundStage.REGISTRATION


def test_forward_and_register_here_registers_at_scrutiny(case, officer_registerer):
    with pytest.raises(BusinessError) as excinfo:
        rounds.forward(case.pk, officer_registerer)
    assert code(excinfo) == "E09007"
    rounds.register_at_scrutiny(case.pk, officer_registerer)
    case.refresh_from_db()
    assert case.status == CaseStatus.REGISTERED


# Lists: every establishment where the caller holds the stage's actions


def test_officer_at_two_establishments_sees_both(
    case, other_case, establishment, other_establishment
):
    both = make_user(SCRUTINY_OFFICER, at=establishment)
    grant(both, other_establishment, SCRUTINY_OFFICER)
    client = client_for(both)

    listed = client.get("/api/v1/scrutiny/").json()
    assert {row["case_id"] for row in listed["results"]} == {str(case.pk), str(other_case.pk)}
    assert listed["counts"]["registry"] == 2

    narrowed = client.get("/api/v1/scrutiny/", {"establishment": str(other_establishment.pk)})
    assert [row["case_id"] for row in narrowed.json()["results"]] == [str(other_case.pk)]


def test_registerer_at_two_establishments_sees_both(
    case, other_case, officer, establishment, other_establishment
):
    rounds.forward(case.pk, officer)
    rounds.forward(other_case.pk, make_user(SCRUTINY_OFFICER, at=other_establishment))
    both = make_user(CASE_REGISTERER, at=establishment)
    grant(both, other_establishment, CASE_REGISTERER)

    listed = client_for(both).get("/api/v1/registration/").json()
    assert {row["case_id"] for row in listed["results"]} == {str(case.pk), str(other_case.pk)}


def test_lists_show_only_the_callers_establishments(case, other_case, officer, registerer):
    listed = client_for(officer).get("/api/v1/scrutiny/").json()
    assert [row["case_id"] for row in listed["results"]] == [str(case.pk)]
    assert listed["counts"]["registry"] == 1


def test_lists_refuse_another_establishment(case, other_establishment, officer, registerer):
    for user, path in ((officer, "/api/v1/scrutiny/"), (registerer, "/api/v1/registration/")):
        response = client_for(user).get(path, {"establishment": str(other_establishment.pk)})
        assert (response.status_code, error_codes(response)) == (403, {None: ["E09008"]})


def test_a_registerer_is_not_given_the_scrutiny_list(case, registerer, officer):
    response = client_for(registerer).get("/api/v1/scrutiny/")
    assert (response.status_code, error_codes(response)) == (403, {None: ["E09008"]})
    response = client_for(officer).get("/api/v1/registration/")
    assert (response.status_code, error_codes(response)) == (403, {None: ["E09008"]})


# Reading: any scrutiny or registration action at the latest round's establishment


def test_officer_still_reads_a_forwarded_case_on_the_closed_tab(case, officer):
    rounds.forward(case.pk, officer)
    client = client_for(officer)
    assert client.get(url(case)).status_code == 200
    closed = client.get("/api/v1/scrutiny/", {"tab": "closed"}).json()
    assert [row["case_id"] for row in closed["results"]] == [str(case.pk)]


def test_other_courts_cases_are_not_found(case, other_case, officer, registerer):
    for user in (officer, registerer):
        client = client_for(user)
        for path in (url(other_case), url(other_case, "history"), registration_url(other_case)):
            assert client.get(path).status_code == 404
        assert client.get(url(case)).status_code == 200


@pytest.mark.parametrize("action", ["start", "send-back", "forward", "register"])
def test_other_courts_cases_cannot_be_acted_on(other_case, officer_registerer, action):
    response = client_for(officer_registerer).post(url(other_case, action), {}, format="json")
    assert response.status_code == 404
    other_case.refresh_from_db()
    assert (other_case.status, other_case.case_number) == (CaseStatus.UNDER_SCRUTINY, None)


def test_services_refuse_another_courts_case(other_case, officer, officer_registerer):
    with pytest.raises(BusinessError) as excinfo:
        draft_field(other_case, officer, "CHQ-3[0]")
    assert code(excinfo) == "E09008"
    for decide in (rounds.send_back, rounds.forward, rounds.register_at_scrutiny):
        with pytest.raises(BusinessError) as excinfo:
            decide(other_case.pk, officer_registerer)
        assert code(excinfo) == "E09008"
    assert offered(other_case, officer_registerer) == []


def test_access_removed_mid_way_is_refused_at_once(case, officer, establishment):
    from apps.organizations import services as court_services

    rounds.start(case.pk, officer, RoundStage.SCRUTINY)
    assignment = officer.role_assignments.get()
    court_services.revoke_role(officer, establishment, assignment.role, actor=None)
    officer.refresh_from_db()
    with pytest.raises(BusinessError) as excinfo:
        draft_field(case, officer, "CHQ-3[0]")
    assert code(excinfo) == "E09008"


# System checks (#2.2): the configured establishment is checked at startup


def test_check_warns_when_unset(settings):
    settings.SCRUTINY_ESTABLISHMENT_ID = ""
    assert [message.id for message in check_establishment_setting(None)] == ["scrutiny.W001"]


def test_check_refuses_a_malformed_value(settings):
    settings.SCRUTINY_ESTABLISHMENT_ID = "court-a"
    assert [message.id for message in check_establishment_setting(None)] == ["scrutiny.E001"]


def test_check_accepts_the_establishment(establishment):
    assert check_establishment_setting(None) == []
    assert check_establishment_exists(None, databases=["default"]) == []


@pytest.mark.parametrize("configured", ["inactive", "unknown", "courtroom", "not a court"])
def test_check_refuses_what_is_not_an_active_establishment(establishment, settings, configured):
    if configured == "inactive":
        Organization.objects.filter(pk=establishment.pk).update(is_active=False)
    else:
        settings.SCRUTINY_ESTABLISHMENT_ID = str(
            {
                "unknown": "00000000-0000-0000-0000-000000000000",
                "courtroom": establishment.children.get().pk,
                "not a court": Organization.objects.create(
                    code="DC",
                    name="District court",
                    organization_type=OrganizationType.DISTRICT_COURT,
                ).pk,
            }[configured]
        )
    assert [m.id for m in check_establishment_exists(None, databases=["default"])] == [
        "scrutiny.E002"
    ]


def test_database_check_runs_only_with_a_database(establishment):
    Organization.objects.filter(pk=establishment.pk).update(is_active=False)
    assert check_establishment_exists(None) == []
    assert "scrutiny.E002" not in {message.id for message in run_checks()}
