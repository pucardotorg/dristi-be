"""Submitting requests: documents, numbering and routing side effects (spec 0010 §7, §9.1).

Every failure row asserts the absence of side effects — no ``Request``, no
``File`` rows, no stored objects — because the create path must leave nothing
behind when it refuses a submission (spec 0010 §7.2).
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.models import Configuration
from apps.dristi_requests.models import Request
from apps.files.models import File

from .conftest import error_codes, stored_paths, submit

pytestmark = pytest.mark.django_db


@pytest.mark.scenario("REQ-SUBMIT-1")
def test_submit_stores_documents_and_routes(
    auth_client, requester, bar_approver, lawyer_bar_type, pdf_file, files_storage
):
    """A valid submission is pending, numbered KL-REQ-00001, documents in upload order."""
    response = submit(
        auth_client(requester),
        lawyer_bar_type,
        {"name": "Advocate One", "bar_number": "K/123/2020"},
        documents=[pdf_file(), pdf_file("enrollment-letter.pdf")],
    )

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["status"] == "pending"
    assert body["request_number"] == "KL-REQ-00001"
    assert body["data"] == {"name": "Advocate One", "bar_number": "K/123/2020"}

    documents = body["documents"]
    assert [d["filename"] for d in documents] == ["bar-certificate.pdf", "enrollment-letter.pdf"]
    assert all(d["file_id"] for d in documents)

    assert len(body["approvals"]) == 1
    approval = body["approvals"][0]
    assert approval["status"] == "pending"
    assert approval["step_order"] == 0
    assert approval["approver"]["id"] == str(bar_approver.pk)

    # The uploads really went through apps.files: rows and stored objects exist.
    assert File.objects.count() == 2
    assert len(stored_paths(files_storage)) == 2


@pytest.mark.scenario("REQ-SUBMIT-2")
def test_request_numbers_are_sequential(auth_client, requester, approver_one, simple_type):
    """Two submissions in a row draw KL-REQ-00001 and KL-REQ-00002 from the counter."""
    client = auth_client(requester)
    first = submit(client, simple_type, {"reason": "one"})
    second = submit(client, simple_type, {"reason": "two"})

    assert first.status_code == 201, first.json()
    assert second.status_code == 201, second.json()
    assert first.json()["request_number"] == "KL-REQ-00001"
    assert second.json()["request_number"] == "KL-REQ-00002"


@pytest.mark.scenario("REQ-SUBMIT-3")
def test_invalid_attributes_store_nothing(
    auth_client, requester, bar_approver, lawyer_bar_type, pdf_file, files_storage
):
    """Attributes failing the type schema are a 400 on attributes; nothing is kept."""
    response = submit(
        auth_client(requester),
        lawyer_bar_type,
        {"name": "Advocate One"},  # bar_number is required
        documents=[pdf_file()],
    )

    assert response.status_code == 400
    assert error_codes(response) == {"attributes": ["E02006"]}
    assert Request.objects.count() == 0
    assert File.objects.count() == 0
    assert stored_paths(files_storage) == []


@pytest.mark.scenario("REQ-SUBMIT-4")
def test_missing_documents_store_nothing(
    auth_client, requester, bar_approver, lawyer_bar_type, files_storage
):
    """Fewer documents than min_documents are a 400 on documents; nothing is kept."""
    response = submit(
        auth_client(requester),
        lawyer_bar_type,
        {"name": "Advocate One", "bar_number": "K/123/2020"},
    )

    assert response.status_code == 400
    assert error_codes(response) == {"documents": ["E02007"]}
    assert Request.objects.count() == 0
    assert File.objects.count() == 0
    assert stored_paths(files_storage) == []


@pytest.mark.scenario("REQ-SUBMIT-5")
def test_a_document_whose_bytes_do_not_match_is_refused(
    auth_client, requester, bar_approver, lawyer_bar_type, files_storage
):
    """A .pdf whose bytes are not %PDF- is refused by content, naming the file."""
    forged = SimpleUploadedFile("forged.pdf", b"not really a pdf", content_type="application/pdf")
    response = submit(
        auth_client(requester),
        lawyer_bar_type,
        {"name": "Advocate One", "bar_number": "K/123/2020"},
        documents=[forged],
    )

    assert response.status_code == 400
    assert error_codes(response) == {"documents": ["E02007"]}
    messages = " ".join(error["message"] for error in response.json()["errors"])
    assert "forged.pdf" in messages
    assert Request.objects.count() == 0
    assert File.objects.count() == 0
    assert stored_paths(files_storage) == []


@pytest.mark.scenario("REQ-SUBMIT-6")
def test_unresolvable_approver_discards_the_documents(
    auth_client, requester, unroutable_type, pdf_file, files_storage
):
    """No eligible approver is a 409, and the already-uploaded documents are discarded."""
    response = submit(
        auth_client(requester), unroutable_type, {"reason": "x"}, documents=[pdf_file()]
    )

    assert response.status_code == 409
    assert error_codes(response) == {None: ["E02003"]}
    assert Request.objects.count() == 0
    assert File.objects.count() == 0
    assert stored_paths(files_storage) == []


@pytest.mark.scenario("REQ-SUBMIT-7")
def test_unconfigured_numbering_discards_the_documents(
    auth_client, requester, bar_approver, lawyer_bar_type, pdf_file, files_storage
):
    """Without tenant.state_code the submission is a 503 and leaves nothing behind."""
    Configuration.objects.filter(config_set="tenant", config_key="state_code").delete()

    response = submit(
        auth_client(requester),
        lawyer_bar_type,
        {"name": "Advocate One", "bar_number": "K/123/2020"},
        documents=[pdf_file()],
    )

    assert response.status_code == 503
    assert error_codes(response) == {None: ["E02008"]}
    assert Request.objects.count() == 0
    assert File.objects.count() == 0
    assert stored_paths(files_storage) == []


@pytest.mark.scenario("REQ-SUBMIT-8")
def test_a_lowercase_state_code_is_normalized(auth_client, requester, approver_one, simple_type):
    """A stored 'kl' is trimmed and upper-cased before it prefixes the number."""
    Configuration.objects.filter(config_set="tenant", config_key="state_code").update(
        config_value="kl"
    )

    response = submit(auth_client(requester), simple_type, {"reason": "x"})

    assert response.status_code == 201, response.json()
    assert response.json()["request_number"] == "KL-REQ-00001"
