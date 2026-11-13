"""Shared fixtures for the notifications app tests."""

import itertools

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from apps.notifications.bus import clear_bus_cache, get_bus
from apps.users.models import RegistrationStatus, Role, User

_numbers = itertools.count(1)


@pytest.fixture(autouse=True)
def fresh_bus():
    """Give every test a clean in-memory bus."""
    clear_bus_cache()
    yield
    clear_bus_cache()


@pytest.fixture
def bus():
    """The process-local in-memory event bus used in tests."""
    return get_bus()


@pytest.fixture
def make_user(db):
    """Return a factory creating registered, approved litigants."""

    def factory(**overrides):
        fields = {
            "mobile_number": f"+91900001{next(_numbers):04d}",
            "name": "Recipient",
            "role": Role.LITIGANT,
            "registration_status": RegistrationStatus.COMPLETE,
            "terms_version_accepted": settings.CURRENT_TERMS_VERSION,
        }
        fields.update(overrides)
        return User.objects.create_user(**fields)

    return factory


@pytest.fixture
def user(make_user):
    """The notification recipient."""
    return make_user()


@pytest.fixture
def other_user(make_user):
    """An unrelated user."""
    return make_user()


@pytest.fixture
def client_for():
    """Return a factory building API clients signed in as a given user."""

    def factory(as_user):
        client = APIClient()
        client.force_authenticate(as_user)
        return client

    return factory


@pytest.fixture
def client(client_for, user):
    """An API client signed in as the recipient."""
    return client_for(user)
