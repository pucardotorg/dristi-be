"""Shared fixtures for the address integration flows (spec 0037).

``apps.address`` has no REST API of its own: its real surfaces are the
manager entry points, the admin, and the locations API that pre-fills the
form (spec 0020 §7).
"""

import itertools
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import Client
from rest_framework.test import APIClient

from apps.locations.models import Location
from apps.users.models import User

SEED_DIR = Path(__file__).parent / "data"
# The chain data/locations.toml seeds, children first for the teardown delete.
SEEDED_CODES = ("PIN_682001", "IN_KL_ERN", "IN_KL", "IN")


@pytest.fixture
def make_user(db):
    """Return a factory creating users with unique mobile numbers."""
    counter = itertools.count(1)

    def factory(email, **kwargs):
        return User.objects.create_user(
            mobile_number=kwargs.pop("mobile_number", f"+9191000000{next(counter):02d}"),
            email=email,
            name=kwargs.pop("name", email.split("@")[0]),
            password="test-password",
            **kwargs,
        )

    return factory


@pytest.fixture
def user(make_user):
    """A user recording addresses."""
    return make_user("recorder@example.com")


@pytest.fixture
def admin_client(make_user):
    """A Django test client logged in as a superuser, for real admin POSTs (§5)."""
    superuser = make_user("address-admin@example.com", is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(superuser)
    client.user = superuser
    return client


@pytest.fixture
def client():
    """An unauthenticated API client (the location endpoints are public)."""
    return APIClient()


@pytest.fixture(scope="module")
def seeded_locations(django_db_setup, django_db_blocker):
    """Seed the pincode chain once for the module (spec 0037 §3, §7).

    The rows are committed outside the per-test transactions; the teardown
    deletes exactly what the TOML declares so a later locations module seeds
    the same codes cleanly.
    """
    with django_db_blocker.unblock():
        call_command("seed", str(SEED_DIR), stdout=StringIO())
        yield
        # Location.parent is PROTECT: delete the chain children-first.
        for code in SEEDED_CODES:
            Location.objects.filter(code=code).delete()
