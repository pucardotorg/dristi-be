"""Shared fixtures for the cases app tests."""

import itertools

import pytest
from django.conf import settings
from django.core.cache import caches
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.cases.models import CaseType
from apps.cases.services import services
from apps.users.models import RegistrationStatus, Role, User

_numbers = itertools.count(1)


def error_codes(response):
    """Return a standard error body as ``{field: [code, ...]}`` (spec 0000 §9.1).

    An error on the request as a whole is keyed ``None``.
    """
    codes = {}
    for error in response.json()["errors"]:
        codes.setdefault(error.get("field"), []).append(error["code"])
    return codes


def error_roots(response):
    """Return the top-level request fields a standard error body points into.

    ``evidence_info.cheque_number`` and ``evidence_info`` both give ``evidence_info``.
    """
    return {field.split(".")[0].split("[")[0] for field in error_codes(response) if field}


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
    caches[services.DRAFT_CACHE_ALIAS].clear()


@pytest.fixture
def make_user(db):
    """Return a factory creating registered litigants."""

    def factory():
        return User.objects.create_user(
            mobile_number=f"+91900000{next(_numbers):04d}",
            name="Filer",
            role=Role.LITIGANT,
            registration_status=RegistrationStatus.COMPLETE,
            terms_version_accepted=settings.CURRENT_TERMS_VERSION,
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
    "account_number": "30012345678",
}

RETURN_MEMO_INFO = {
    "presentation_date": "2024-01-18",
    "return_date": "2024-01-22",
    "return_reason": "FUNDS_INSUFFICIENT",
}

DEMAND_NOTICE_INFO = {
    "nature_of_debt": "LOAN_OR_ADVANCE_REPAYMENT",
    "dispatch_date": "2024-02-01",
    "mode_of_service": "REGISTERED_POST",
    "tracking_number": "RR123456789IN",
    "is_delivered": True,
    "delivery_date": "2024-02-05",
    "accused_replied": False,
    "payment_status": "NO_PAYMENT_MADE",
}
