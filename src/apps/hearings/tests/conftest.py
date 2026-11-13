"""Fixtures shared by the hearings tests."""

import pytest
from cachalot.api import cachalot_disabled

from apps.hearings.enums import HearingRole

from .factories import TODAY, make_case, make_court, make_user, set_config


@pytest.fixture(autouse=True)
def no_query_cache():
    """Read configuration fresh: the locmem query cache outlives each test's rolled-back transaction,
    so a value cached by another test could hide one this test writes."""
    with cachalot_disabled():
        yield


@pytest.fixture(autouse=True)
def business_date(db, no_query_cache):
    """Pin the court's today to a Thursday, so every rule on dates is deterministic."""
    set_config("business_date_override", TODAY.isoformat())
    return TODAY


@pytest.fixture
def establishment(settings):
    """The establishment the deployment serves; placeholder roles count only here."""
    court = make_court("NI Act Court")
    settings.SCRUTINY_ESTABLISHMENT_ID = str(court.pk)
    return court


@pytest.fixture
def courtroom(establishment):
    return make_court("Courtroom 1", parent=establishment)


@pytest.fixture
def sibling_courtroom(establishment):
    return make_court("Courtroom 2", parent=establishment)


@pytest.fixture
def foreign_court():
    """A court the deployment does not serve."""
    return make_court("Kollam Court")


@pytest.fixture
def controller():
    return make_user(HearingRole.HEARING_CONTROLLER, name="Controller")


@pytest.fixture
def setter():
    return make_user(HearingRole.NEXT_HEARING_SETTER, name="Setter")


@pytest.fixture
def filler():
    return make_user(HearingRole.ORDER_DATA_FILLER, name="Filler")


@pytest.fixture
def staff():
    """Court staff holding every hearing role."""
    return make_user(*HearingRole.values, name="All roles")


@pytest.fixture
def stranger():
    return make_user(name="Stranger")


@pytest.fixture
def complainant_user():
    return make_user(name="Complainant")


@pytest.fixture
def advocate_user():
    return make_user(name="Advocate")


@pytest.fixture
def case(courtroom, complainant_user, advocate_user):
    return make_case(courtroom, complainant_user=complainant_user, advocate_user=advocate_user)


@pytest.fixture
def other_case(courtroom):
    return make_case(courtroom)


@pytest.fixture
def third_case(courtroom):
    return make_case(courtroom)
