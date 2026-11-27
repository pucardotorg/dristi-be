"""Fixtures shared by the processes tests."""

import datetime

import pytest
from cachalot.api import cachalot_disabled

from apps.hearings.tests.factories import make_case, make_court, make_user, schedule
from apps.hearings.tests.factories import set_config as set_hearings_config

from .factories import MOBILE, accused, add_mobile, make_staff, seed_masters

# A Friday after the pinned business date (Thursday 2026-11-12).
HEARING_DAY = datetime.date(2026, 11, 20)


@pytest.fixture(autouse=True)
def masters(db, settings):
    """Masters seeded, fresh configuration reads, and payments without a gateway."""
    settings.PAYMENT_DEFAULT_PROVIDER = ""
    with cachalot_disabled():
        seed_masters()
        set_hearings_config("business_date_override", "2026-11-12")
        yield


@pytest.fixture
def establishment(settings):
    court = make_court("NI Act Court")
    settings.SCRUTINY_ESTABLISHMENT_ID = str(court.pk)
    return court


@pytest.fixture
def courtroom(establishment):
    return make_court("Courtroom 1", parent=establishment)


@pytest.fixture
def staff(courtroom):
    """Court staff allowed every process action."""
    return make_staff()


@pytest.fixture
def stranger():
    return make_user(name="Stranger")


@pytest.fixture
def complainant_user():
    return make_user(name="Complainant")


@pytest.fixture
def case(courtroom, complainant_user):
    """A registered case with a hearing listed, whose accused has a mobile and an address."""
    case = make_case(courtroom, complainant_user=complainant_user)
    add_mobile(accused(case), MOBILE)
    schedule(case, HEARING_DAY)
    return case
