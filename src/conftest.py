"""Project-wide pytest fixtures."""

from io import StringIO

import pytest
from django.conf import settings
from django.core.management import call_command

CORE_SEED = settings.BASE_DIR.parent / "data" / "seed" / "core"
# The reference data that data migrations used to insert (spec 0036), and the order
# catalogue (spec 0039 #3.11), which was never migrated but every orders test needs. The rest
# of core/ (languages, configurations, public configurations, attribute
# definitions) was never in the migrated test database; the tests that need it
# seed it themselves, and some expect those tables to start empty.
MIGRATED_DATA = ("auth", "cms", "dristi_requests", "hearings", "messaging", "orders", "scrutiny")


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Seed the reference data the migrations used to insert, once per session.

    ``--strict`` fails the session if any row is skipped.
    """
    paths = [str(CORE_SEED / name) for name in MIGRATED_DATA]
    with django_db_blocker.unblock():
        call_command("seed", *paths, "--strict", stdout=StringIO())
