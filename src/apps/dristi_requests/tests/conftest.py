"""Shared fixtures for the dristi requests app tests."""

import itertools

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.dristi_requests.models import ApprovalStep, RequestType
from apps.users.models import User


@pytest.fixture(autouse=True)
def files_storage(settings):
    """Keep document content in memory, as the apps.files suite does.

    Returns the live storage so a test can assert on what was written.
    """
    settings.STORAGES = {
        **settings.STORAGES,
        "files": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }
    from django.core.files.storage import storages

    return storages["files"]


@pytest.fixture
def make_user(db):
    """Return a factory creating users, optionally in the given groups.

    Mobile numbers are handed out in creation order, which is also the order
    :func:`apps.dristi_requests.services.candidate_approvers` resolves
    approvers in, so "first user added to the group approves" holds in tests.
    """
    counter = itertools.count(1)

    def factory(email, groups=(), **kwargs):
        user = User.objects.create_user(
            mobile_number=kwargs.pop("mobile_number", f"+9190000000{next(counter):02d}"),
            email=email,
            name=kwargs.pop("name", email.split("@")[0]),
            password=kwargs.pop("password", "test-password"),
            **kwargs,
        )
        for group_name in groups:
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)
        return user

    return factory


@pytest.fixture
def requester(make_user):
    """A plain requester."""
    return make_user("requester@example.com")


@pytest.fixture
def approver_one(make_user):
    """First-level approver."""
    return make_user("approver1@example.com", groups=["LEVEL_ONE"])


@pytest.fixture
def approver_two(make_user):
    """Second-level approver."""
    return make_user("approver2@example.com", groups=["LEVEL_TWO"])


@pytest.fixture
def staff_user(make_user):
    """A staff member."""
    return make_user("staff@example.com", is_staff=True)


@pytest.fixture
def outsider(make_user):
    """A user with no relation to any request."""
    return make_user("outsider@example.com")


@pytest.fixture
def simple_type(db):
    """A request type with a single approval step and no documents required."""
    request_type = RequestType.objects.create(
        code="SIMPLE",
        name="Simple request",
        schema={
            "type": "object",
            "required": ["reason"],
            "properties": {"reason": {"type": "string", "minLength": 1}},
        },
        min_documents=0,
    )
    ApprovalStep.objects.create(
        request_type=request_type,
        order=0,
        approver_role="LEVEL_ONE",
    )
    return request_type


@pytest.fixture
def two_step_type(db):
    """A request type with two sequential approval steps."""
    request_type = RequestType.objects.create(
        code="TWO_STEP",
        name="Two step request",
        schema={"type": "object", "properties": {"amount": {"type": "number"}}},
        min_documents=0,
    )
    ApprovalStep.objects.create(request_type=request_type, order=0, approver_role="LEVEL_ONE")
    ApprovalStep.objects.create(request_type=request_type, order=1, approver_role="LEVEL_TWO")
    return request_type


@pytest.fixture
def lawyer_bar_type(db):
    """The seeded LAWYER_BAR_UPDATE request type."""
    return RequestType.objects.get(code="LAWYER_BAR_UPDATE")


@pytest.fixture
def bar_approver(make_user):
    """An approver in the seeded bar ID approver group."""
    return make_user("bar@example.com", groups=["BAR_ID_APPROVER"])


@pytest.fixture
def pdf_file():
    """Return a factory producing small uploaded files."""

    def factory(name="bar-certificate.pdf", content_type="application/pdf", content=None):
        return SimpleUploadedFile(
            name, content if content is not None else b"%PDF-1.4 fake", content_type=content_type
        )

    return factory


@pytest.fixture
def stored_file(pdf_file):
    """Return a factory storing an upload through apps.files, returning the File."""
    from apps.files import services as files
    from apps.files.models import File, FileType

    def factory(user, name="bar-certificate.pdf"):
        result = files.upload_file(
            {"user_id": user.pk, "files": [{"file": pdf_file(name), "file_type": FileType.PDF}]}
        )
        return File.objects.get(pk=result["files"][0]["id"])

    return factory


@pytest.fixture
def api_client():
    """Return an unauthenticated DRF API client."""
    return APIClient()


@pytest.fixture
def auth_client():
    """Return a factory building API clients authenticated as a given user."""

    def factory(user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    return factory
