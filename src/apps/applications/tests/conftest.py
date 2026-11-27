"""Fixtures shared by the applications tests (spec 0033 #17)."""

from types import SimpleNamespace

import pytest
from cachalot.api import cachalot_disabled

from apps.cases.models import ParticipantRole, PoaMandate
from apps.users.models import Role

from .factories import (
    ORDER_ROLES,
    TODAY,
    add_party,
    make_advocate,
    make_case,
    make_court,
    make_user,
    office,
    represent,
    seed_applications,
    set_config,
)


@pytest.fixture(autouse=True)
def no_query_cache():
    """Read configuration fresh: the locmem query cache outlives each rolled-back test."""
    with cachalot_disabled():
        yield


@pytest.fixture(autouse=True)
def business_date(db, no_query_cache):
    """Pin the court's today to a Thursday, so every rule on dates is deterministic."""
    set_config("hearings", "business_date_override", TODAY.isoformat())
    return TODAY


@pytest.fixture(autouse=True)
def seeded(db):
    seed_applications()


@pytest.fixture(autouse=True)
def numbering(db):
    """Kerala's provisional settings (#7), as the shared defaults."""
    set_config("applications", "submission_number_format", "{filing_number}-AP{n}")
    set_config("applications", "submission_number_scope", "CASE")
    set_config("applications", "replace_on_onboarding", "true")
    set_config("applications", "replacement_number_format", "CMP/{n}/{year}")
    set_config("applications", "replacement_number_scope", "CASE")


@pytest.fixture
def establishment(settings):
    court = make_court("NI Act Court")
    settings.SCRUTINY_ESTABLISHMENT_ID = str(court.pk)
    return court


@pytest.fixture
def courtroom(establishment):
    return make_court("Courtroom 1", parent=establishment)


@pytest.fixture
def world(courtroom):
    """The fixture world of #17."""
    case = make_case(courtroom)
    a1 = make_advocate("Nisha Thomas")
    b1 = make_advocate("Bijini Rejen")
    c1 = make_user(name="Clerk to Nisha", role=Role.CLERK)
    office(c1, a1)
    l1 = make_user(name="Prateek Agrawal", role=Role.LITIGANT)
    h1 = make_user(name="PoA Holder", role=Role.POWER_OF_ATTORNEY)
    complainant = add_party(case, ParticipantRole.COMPLAINANT, "Prateek Agrawal", user=l1)
    accused = add_party(case, ParticipantRole.ACCUSED, "Deepak Choudhary")
    poa = add_party(case, ParticipantRole.POA_HOLDER, "PoA Holder", user=h1)
    PoaMandate.objects.create(case=case, poa_participant=poa, represented_participant=complainant)
    represent(case, a1, complainant)
    represent(case, b1, accused)
    staff = make_user(*ORDER_ROLES, name="S-ord")
    reader = make_user("Order data filler", name="S-read")
    other_staff = make_user(*ORDER_ROLES, name="S-other")
    stranger = make_user(name="Stranger")
    return SimpleNamespace(
        case=case,
        court=courtroom,
        a1=a1,
        b1=b1,
        c1=c1,
        l1=l1,
        h1=h1,
        complainant=complainant,
        accused=accused,
        poa=poa,
        staff=staff,
        reader=reader,
        other_staff=other_staff,
        stranger=stranger,
    )


@pytest.fixture
def foreign_staff(world, settings):
    """Order-role staff, but of a court the deployment does not serve."""
    return world.other_staff
