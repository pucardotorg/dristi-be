"""The contract consumers rely on when they reference a file (spec 0014 §5, §6.2).

``RequestDocument.file`` is the referencing foreign key consumers use; these
flows pin what ``delete_file`` does to it (the PROTECT guard and the §6.2
known gap) and that the request lifecycle never deletes documents.
"""

import json

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import ProtectedError
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import Configuration
from apps.dristi_requests.models import ApprovalStep, RequestDocument, RequestType
from apps.files import services
from apps.files.models import File
from apps.files.tests.factories import make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def state_code(db):
    """Configure the state code request numbers need."""
    return Configuration.objects.create(
        config_set="tenant", config_key="state_code", config_value="KL"
    )


@pytest.fixture
def request_setup(db):
    """A one-step request type, its approver and a requester."""
    request_type = RequestType.objects.create(
        code="FILES_CONSUMER",
        name="Files consumer request",
        schema={"type": "object", "properties": {"reason": {"type": "string"}}},
        min_documents=1,
    )
    ApprovalStep.objects.create(request_type=request_type, order=0, approver_role="FILE_APPROVER")
    approver = make_user()
    group, _ = Group.objects.get_or_create(name="FILE_APPROVER")
    approver.groups.add(group)
    return request_type, make_user(), approver


def client_for(user):
    """Return an API client authenticated as ``user``."""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def submit_request(request_setup):
    """Submit a one-document request over the API; return (requester, approver, body)."""
    request_type, requester, approver = request_setup
    response = client_for(requester).post(
        reverse("request-list"),
        {
            "request_type": request_type.code,
            "attributes": json.dumps({"reason": "x"}),
            "documents": [SimpleUploadedFile("proof.pdf", b"%PDF-1.4 fake", "application/pdf")],
        },
        format="multipart",
    )
    assert response.status_code == 201, response.json()
    return requester, approver, response.json()


@pytest.mark.scenario("FILE-CONSUMERS-1")
def test_delete_file_on_a_referenced_file_is_protected(state_code, request_setup, files_storage):
    """RequestDocument.file is PROTECT: the row survives; the object is already gone (§6.2 gap)."""
    _, _, body = submit_request(request_setup)
    file_id = body["documents"][0]["file_id"]
    path = File.objects.get(pk=file_id).storage_path

    with pytest.raises(ProtectedError):
        services.delete_file(file_id)

    # The guard stops the row delete, but the object went first — the known
    # gap of open question 9, pinned so a fix updates this scenario in place.
    assert File.objects.filter(pk=file_id).exists()
    assert not files_storage.exists(path)


@pytest.mark.scenario("FILE-CONSUMERS-2")
def test_the_request_lifecycle_never_deletes_documents(state_code, request_setup, files_storage):
    """Cancel, reject and resubmit all keep the File rows and the RequestDocument links."""
    # Cancel.
    requester, approver, body = submit_request(request_setup)
    client_for(requester).post(reverse("request-cancel", args=[body["id"]]))
    assert_documents_kept(body)

    # Reject, then resubmit.
    requester, approver, body = submit_request(request_setup)
    response = client_for(approver).post(
        reverse("request-approval-decide", args=[body["approvals"][0]["id"]]),
        {"decision": "rejected", "comments": "illegible"},
        format="json",
    )
    assert response.status_code == 200
    assert_documents_kept(body)

    response = client_for(requester).post(reverse("request-resubmit", args=[body["id"]]))
    assert response.status_code == 200
    assert_documents_kept(body)


def assert_documents_kept(body):
    """Assert the request's documents survived a lifecycle transition."""
    file_ids = [document["file_id"] for document in body["documents"]]
    assert File.objects.filter(pk__in=file_ids).count() == len(file_ids)
    assert RequestDocument.objects.filter(request_id=body["id"]).count() == len(file_ids)
