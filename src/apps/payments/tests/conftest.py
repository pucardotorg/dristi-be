"""Shared fixtures for the payments suite."""

import itertools
import uuid

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.payments.enums import ReferenceType
from apps.payments.providers import registry
from apps.payments.services import DemandService

from .fakes import FakeProvider
from .helpers import item

FAKE_PATH = "apps.payments.tests.fakes.FakeProvider"
MOCK_PATH = "apps.payments.providers.mock.MockPaymentProvider"

_mobile = itertools.count(1)


@pytest.fixture(autouse=True)
def fresh_providers():
    """Each test resolves providers from its own settings and a clean fake."""

    registry.reset_cache()
    FakeProvider.reset()
    yield
    registry.reset_cache()
    FakeProvider.reset()


@pytest.fixture
def make_user(db):
    """Create accounts that have finished registration."""

    from apps.users.models import RegistrationStatus, Role

    def factory(name="Payer", **extra):
        # Registered and on the current terms: both are default API gates.
        extra.setdefault("terms_version_accepted", settings.CURRENT_TERMS_VERSION)
        return get_user_model().objects.create_user(
            mobile_number=f"+9198{next(_mobile):08d}",
            name=name,
            email=extra.pop("email", None),
            role=Role.LITIGANT.value,
            registration_status=RegistrationStatus.COMPLETE.value,
            **extra,
        )

    return factory


@pytest.fixture
def user(make_user):
    """The signed-in payer."""

    return make_user("Anjali Menon", email="anjali@example.com")


@pytest.fixture
def other_user(make_user):
    """Someone with no connection to the caller's demands."""

    return make_user("Outsider")


@pytest.fixture
def api(user):
    """An API client signed in as ``user``."""

    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def case_id():
    """The case demands are raised on (a plain id until apps.cases merges)."""

    return uuid.uuid4()


@pytest.fixture
def raise_demand(user, case_id):
    """Raise a demand in-process, by default three 12.50 process fees."""

    def factory(items=None, *, actor=None, case=None, **kwargs):
        actor = actor or user
        return DemandService.raise_demand(
            case=case or case_id,
            reference_type=kwargs.pop("reference_type", ReferenceType.ORDER),
            reference_id=kwargs.pop("reference_id", "order-77"),
            items=items
            or [
                item(reference_type=ReferenceType.SUMMONS, reference_id="summons-1"),
                item(reference_type=ReferenceType.SUMMONS, reference_id="summons-2"),
                item(reference_type=ReferenceType.WARRANT, reference_id="warrant-1"),
            ],
            user_id=kwargs.pop("user_id", actor.pk),
            actor=actor,
            **kwargs,
        )

    return factory


@pytest.fixture
def no_provider(settings):
    """No default provider: payments stay INITIATED (spec 0017 #9.3)."""

    settings.PAYMENT_DEFAULT_PROVIDER = ""
    registry.reset_cache()


@pytest.fixture
def fake_provider(settings):
    """The scriptable fake provider as the default; the mock stays registered."""

    settings.PAYMENT_PROVIDERS = {"fake": FAKE_PATH, "mock": MOCK_PATH}
    settings.PAYMENT_DEFAULT_PROVIDER = "fake"
    registry.reset_cache()
    return FakeProvider
