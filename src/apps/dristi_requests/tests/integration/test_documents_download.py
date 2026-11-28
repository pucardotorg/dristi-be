"""Downloading request documents: authorization at the request's rules (spec 0010 §9.4).

Access is decided by the request before ``apps.files`` is asked for anything;
a document is never served by ``file_id`` alone.
"""

import pytest
from django.urls import reverse

from apps.files.models import File

from .conftest import error_codes, submit

pytestmark = pytest.mark.django_db

PDF_BYTES = b"%PDF-1.4 fake"


@pytest.fixture
def submitted(auth_client, requester, bar_approver, lawyer_bar_type, pdf_file):
    """A submitted request with one PDF document; returns its response body."""
    response = submit(
        auth_client(requester),
        lawyer_bar_type,
        {"name": "Advocate One", "bar_number": "K/123/2020"},
        documents=[pdf_file()],
    )
    assert response.status_code == 201, response.json()
    return response.json()


def download_url(request_id, document_id):
    """Return the download URL for a request document."""
    return reverse("request-document-download", args=[request_id, document_id])


@pytest.mark.scenario("REQ-DOCS-1")
def test_the_requester_downloads_their_document(auth_client, requester, submitted):
    """The download attaches the recorded name and type, byte for byte."""
    document = submitted["documents"][0]
    response = auth_client(requester).get(download_url(submitted["id"], document["id"]))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert 'attachment; filename="bar-certificate.pdf"' in response["Content-Disposition"]
    assert b"".join(response.streaming_content) == PDF_BYTES


@pytest.mark.scenario("REQ-DOCS-2")
def test_an_approver_on_the_trail_downloads(auth_client, bar_approver, submitted):
    """Any approver on the trail is authorized."""
    document = submitted["documents"][0]
    response = auth_client(bar_approver).get(download_url(submitted["id"], document["id"]))

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PDF_BYTES


@pytest.mark.scenario("REQ-DOCS-3")
def test_an_outsider_gets_a_404_even_with_the_file_id(auth_client, outsider, submitted):
    """Neither the document id nor a bare file_id guess serves an outsider."""
    document = submitted["documents"][0]
    client = auth_client(outsider)

    assert client.get(download_url(submitted["id"], document["id"])).status_code == 404
    # The URL takes the RequestDocument id; the file's own id matches nothing.
    assert client.get(download_url(submitted["id"], document["file_id"])).status_code == 404


@pytest.mark.scenario("REQ-DOCS-4")
def test_staff_download(auth_client, staff_user, submitted):
    """Staff are authorized without being on the trail."""
    document = submitted["documents"][0]
    response = auth_client(staff_user).get(download_url(submitted["id"], document["id"]))

    assert response.status_code == 200


@pytest.mark.scenario("REQ-DOCS-5")
def test_a_deactivated_file_downloads_as_not_found(auth_client, requester, admin_client, submitted):
    """An operator deactivates the file in the files admin; the download is a 404."""
    document = submitted["documents"][0]
    file = File.objects.get(pk=document["file_id"])
    response = admin_client.post(
        reverse("admin:files_file_change", args=[file.pk]),
        {
            "file_name": file.file_name,
            "file_type": file.file_type,
            "organization": "",
            "user": str(file.user_id),
            # is_active left out: the checkbox is unchecked.
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]

    response = auth_client(requester).get(download_url(submitted["id"], document["id"]))
    assert response.status_code == 404


@pytest.mark.scenario("REQ-DOCS-6")
def test_a_document_over_the_read_limit_is_a_413(auth_client, requester, submitted, settings):
    """The read limit is checked from metadata before the object is opened (E02005)."""
    settings.FILE_MAX_READ_BYTES = len(PDF_BYTES) - 1

    document = submitted["documents"][0]
    response = auth_client(requester).get(download_url(submitted["id"], document["id"]))

    assert response.status_code == 413
    assert error_codes(response) == {None: ["E02005"]}
