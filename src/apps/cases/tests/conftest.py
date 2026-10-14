"""Shared fixtures for the cases app tests."""

import itertools

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.cases.models import CaseType
from apps.cases.services import services
from apps.users.models import RegistrationStatus, Role, User

_numbers = itertools.count(1)


@pytest.fixture(autouse=True)
def files_storage(settings):
    """Keep uploaded content in memory, as the apps.files suite does."""
    settings.STORAGES = {
        **settings.STORAGES,
        "files": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture(autouse=True)
def clear_cache():
    """Start every test with no draft sessions."""
    cache.clear()


@pytest.fixture
def make_user(db):
    """Return a factory creating registered litigants."""

    def factory():
        return User.objects.create_user(
            mobile_number=f"+91900000{next(_numbers):04d}",
            name="Filer",
            role=Role.LITIGANT,
            registration_status=RegistrationStatus.COMPLETE,
        )

    return factory


@pytest.fixture
def user(make_user):
    """The filer."""
    return make_user()


@pytest.fixture
def other_user(make_user):
    """A user with no relation to the filer's cases."""
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
    """An API client signed in as the filer."""
    return client_for(user)


@pytest.fixture
def draft(user):
    """A cheque bounce draft session for the filer; returns its id."""
    return services.start_draft(user, CaseType.CHEQUE_BOUNCE)["draft_session_id"]


@pytest.fixture
def pdf():
    """Return a factory producing small PDF uploads."""

    def factory(name="cheque.pdf", content_type="application/pdf"):
        return SimpleUploadedFile(name, b"%PDF-1.4 fake", content_type=content_type)

    return factory


CHEQUE_INFO = {
    "cheque_date": "2024-01-15",
    "amount": 50000.0,
    "cheque_number": "456789",
    "ifsc_code": "SBIN0001234",
    "bank_name": "State Bank of India",
    "bank_branch": "MG Road",
}

RETURN_MEMO_INFO = {
    "presentation_date": "2024-01-18",
    "return_date": "2024-01-22",
    "return_reason": "Funds insufficient",
}

DEMAND_NOTICE_INFO = {
    "nature_of_debt": "Loan",
    "cheque_issue_reason": "Repayment of loan",
    "dispatch_date": "2024-02-01",
    "mode_of_service": "Registered post",
    "tracking_number": "RR123456789IN",
    "is_delivered": True,
    "delivery_date": "2024-02-05",
    "accused_replied": False,
    "payment_status": "No payment",
}
