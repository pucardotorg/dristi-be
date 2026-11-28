"""The request lifecycle: reject, resubmit, cancel (spec 0010 §2, §9.3).

Row REQ-LIFECYCLE-2 drives ``services.resubmit`` directly: the API's
resubmit action takes no body, so the corrected-data/replacement-documents
path is only reachable at the service layer (spec 0037 §1 shape 2).
"""

import pytest
from django.urls import reverse

from apps.dristi_requests import services
from apps.dristi_requests.models import Request, RequestApproval, RequestDocument
from apps.files import services as files
from apps.files.models import File, FileType

from .conftest import error_codes, submit

pytestmark = pytest.mark.django_db


def reject(auth_client, approver, created, comments="not acceptable"):
    """Reject the pending approval of a just-created request."""
    client = auth_client(approver)
    response = client.post(
        reverse("request-approval-decide", args=[created["approvals"][0]["id"]]),
        {"decision": "rejected", "comments": comments},
        format="json",
    )
    assert response.status_code == 200
    return response


@pytest.mark.scenario("REQ-LIFECYCLE-1")
def test_a_rejected_request_resubmits_as_a_new_version(
    auth_client, requester, approver_one, simple_type
):
    """Resubmit keeps the number, bumps the version and routes a fresh approval round."""
    requester_client = auth_client(requester)
    created = submit(requester_client, simple_type, {"reason": "x"}).json()
    reject(auth_client, approver_one, created)

    response = requester_client.post(reverse("request-resubmit", args=[created["id"]]))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["version"] == 2
    assert body["current_step"] == 0
    assert body["request_number"] == created["request_number"]

    trail = requester_client.get(reverse("request-approvals", args=[created["id"]])).json()["data"]
    assert [(row["version"], row["status"]) for row in trail] == [
        (1, "rejected"),
        (2, "pending"),
    ]


@pytest.mark.scenario("REQ-LIFECYCLE-2")
def test_resubmit_replaces_the_documents_but_keeps_the_files(
    auth_client, requester, approver_one, lawyer_bar_type, bar_approver, pdf_file, files_storage
):
    """New file_ids replace the RequestDocument links; the old File rows stay for audit."""
    requester_client = auth_client(requester)
    created = submit(
        requester_client,
        lawyer_bar_type,
        {"name": "Advocate One", "bar_number": "K/123/2020"},
        documents=[pdf_file()],
    ).json()
    reject(auth_client, bar_approver, created)
    old_document_id = created["documents"][0]["id"]
    old_file_id = created["documents"][0]["file_id"]

    new_file_id = files.upload_file(
        {
            "user_id": requester.pk,
            "files": [{"file": pdf_file("new-certificate.pdf"), "file_type": FileType.PDF}],
        }
    )["files"][0]["id"]
    services.resubmit(
        Request.objects.get(pk=created["id"]),
        actor=requester,
        data={"name": "Advocate One", "bar_number": "K/999/2021"},
        file_ids=[new_file_id],
    )

    request = Request.objects.get(pk=created["id"])
    assert request.version == 2
    assert request.status == Request.Status.PENDING
    assert request.data == {"name": "Advocate One", "bar_number": "K/999/2021"}

    links = RequestDocument.objects.filter(request=request)
    assert [link.file_id for link in links] == [new_file_id]
    assert not RequestDocument.objects.filter(pk=old_document_id).exists()
    # The superseded upload is still a File row: documents are part of the audit trail.
    assert File.objects.filter(pk=old_file_id).exists()


@pytest.mark.scenario("REQ-LIFECYCLE-3")
def test_a_pending_request_cannot_be_resubmitted(auth_client, requester, approver_one, simple_type):
    """Resubmit is only for rejected requests (E02001)."""
    created = submit(auth_client(requester), simple_type, {"reason": "x"}).json()

    response = auth_client(requester).post(reverse("request-resubmit", args=[created["id"]]))

    assert response.status_code == 400
    assert error_codes(response) == {None: ["E02001"]}


@pytest.mark.scenario("REQ-LIFECYCLE-4")
def test_cancelling_skips_the_pending_approval(
    auth_client, requester, approver_one, lawyer_bar_type, bar_approver, pdf_file
):
    """Cancel marks the request cancelled, skips the approval and keeps the documents."""
    requester_client = auth_client(requester)
    created = submit(
        requester_client,
        lawyer_bar_type,
        {"name": "Advocate One", "bar_number": "K/123/2020"},
        documents=[pdf_file()],
    ).json()

    response = requester_client.post(reverse("request-cancel", args=[created["id"]]))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    approval = body["approvals"][0]
    assert approval["status"] == "skipped"
    assert approval["comments"] == "Request cancelled by the requester."
    assert len(body["documents"]) == 1

    queue = auth_client(approver_one).get(reverse("request-approval-list")).json()
    assert queue["results"] == []


@pytest.mark.scenario("REQ-LIFECYCLE-5")
def test_an_approved_request_cannot_be_cancelled(auth_client, requester, approver_one, simple_type):
    """Cancel is only for open requests (E02001)."""
    requester_client = auth_client(requester)
    created = submit(requester_client, simple_type, {"reason": "x"}).json()
    auth_client(approver_one).post(
        reverse("request-approval-decide", args=[created["approvals"][0]["id"]]),
        {"decision": "approved"},
        format="json",
    )

    response = requester_client.post(reverse("request-cancel", args=[created["id"]]))

    assert response.status_code == 400
    assert error_codes(response) == {None: ["E02001"]}


@pytest.mark.scenario("REQ-LIFECYCLE-6")
def test_a_cancelled_requests_approval_cannot_be_decided(
    auth_client, requester, approver_one, simple_type
):
    """The skipped approval of a cancelled request is not pending (E02002)."""
    requester_client = auth_client(requester)
    created = submit(requester_client, simple_type, {"reason": "x"}).json()
    requester_client.post(reverse("request-cancel", args=[created["id"]]))

    response = auth_client(approver_one).post(
        reverse("request-approval-decide", args=[created["approvals"][0]["id"]]),
        {"decision": "approved"},
        format="json",
    )

    assert response.status_code == 400
    assert error_codes(response) == {None: ["E02002"]}


@pytest.mark.scenario("REQ-LIFECYCLE-7")
def test_only_the_requester_can_resubmit_or_cancel(
    auth_client, requester, approver_one, outsider, simple_type
):
    """The action routes are restricted to the requester: an outsider gets a 404."""
    created = submit(auth_client(requester), simple_type, {"reason": "x"}).json()

    outsider_client = auth_client(outsider)
    for action in ("request-resubmit", "request-cancel"):
        response = outsider_client.post(reverse(action, args=[created["id"]]))
        assert response.status_code == 404, action

    assert Request.objects.get(pk=created["id"]).status == Request.Status.PENDING
    assert (
        RequestApproval.objects.get(pk=created["approvals"][0]["id"]).status
        == RequestApproval.Status.PENDING
    )
