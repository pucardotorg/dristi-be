"""Request documents stored through apps.files (spec 0010 + 0014).

Covers what the integration has to guarantee: documents land in apps.files
with the right metadata, invalid uploads are rejected as 400s before anything
is stored, a submission that fails after upload leaves nothing behind, and the
download still goes through the request's own access rules.
"""

import json

import pytest
from django.db.models import ProtectedError
from django.urls import reverse

from apps.dristi_requests import services
from apps.dristi_requests.documents import DOCUMENT_TAG
from apps.dristi_requests.exceptions import ApprovalRoutingError
from apps.dristi_requests.models import Request, RequestDocument
from apps.files import services as files
from apps.files.models import File, FileType


def submit(client, request_type, attributes, documents):
    """POST a submission with the given documents."""
    return client.post(
        reverse("request-list"),
        {
            "request_type": request_type,
            "attributes": json.dumps(attributes),
            "documents": documents,
        },
        format="multipart",
    )


@pytest.mark.django_db
class TestDocumentsAreStoredByAppsFiles:
    """Successful uploads create apps.files records with the right metadata."""

    def test_upload_creates_file_records(
        self, auth_client, lawyer_bar_type, requester, bar_approver, pdf_file
    ):
        response = submit(
            auth_client(requester),
            "LAWYER_BAR_UPDATE",
            {"name": "Jane", "bar_number": "KAR/1"},
            [pdf_file("cert.pdf")],
        )

        assert response.status_code == 201
        document = Request.objects.get(pk=response.json()["id"]).documents.get()
        stored = document.file
        assert stored.file_name == "cert.pdf"
        assert stored.content_type == "application/pdf"
        assert stored.file_type == FileType.PDF
        assert stored.user == requester
        assert stored.file_size == len(b"%PDF-1.4 fake")
        assert sorted(tag.name for tag in stored.tags.all()) == sorted(
            [DOCUMENT_TAG, "lawyer_bar_update"]
        )

    def test_images_are_stored_as_image_type(
        self, auth_client, simple_type, requester, approver_one, pdf_file
    ):
        response = submit(
            auth_client(requester),
            "SIMPLE",
            {"reason": "x"},
            [
                pdf_file("scan.png", content_type="image/png", content=b"\x89PNG fake"),
                pdf_file("photo.jpg", content_type="image/jpeg", content=b"\xff\xd8 fake"),
            ],
        )

        assert response.status_code == 201
        types = set(File.objects.values_list("file_type", flat=True))
        assert types == {FileType.IMAGE}

    def test_response_exposes_file_id_and_metadata(
        self, auth_client, lawyer_bar_type, requester, bar_approver, pdf_file
    ):
        response = submit(
            auth_client(requester),
            "LAWYER_BAR_UPDATE",
            {"name": "Jane", "bar_number": "KAR/1"},
            [pdf_file("cert.pdf")],
        )

        document = response.json()["documents"][0]
        stored = File.objects.get()
        assert document["file_id"] == str(stored.pk)
        assert document["filename"] == "cert.pdf"
        assert document["content_type"] == "application/pdf"
        assert document["file_type"] == FileType.PDF
        assert document["file_size"] == stored.file_size
        assert document["uploaded_by"]["id"] == str(requester.pk)

    def test_document_order_follows_upload_order(
        self, simple_type, requester, approver_one, pdf_file
    ):
        request = services.create_request(
            request_type=simple_type,
            requester=requester,
            data={"reason": "x"},
            files=[pdf_file("first.pdf"), pdf_file("second.pdf"), pdf_file("third.pdf")],
        )

        names = [document.filename for document in request.documents.all()]
        assert names == ["first.pdf", "second.pdf", "third.pdf"]
        assert request.documents.first().filename == "first.pdf"

    def test_documents_are_audit_attributed_to_the_requester(
        self, simple_type, requester, approver_one, pdf_file
    ):
        request = services.create_request(
            request_type=simple_type,
            requester=requester,
            data={"reason": "x"},
            files=[pdf_file()],
        )

        document = request.documents.get()
        assert document.created_by == requester
        assert document.updated_by == requester


@pytest.mark.django_db
class TestInvalidUploadsAreRejectedBeforeStorage:
    """Bad uploads are 400s on ``documents`` and never reach storage."""

    def test_unsupported_content_type(
        self, auth_client, simple_type, requester, approver_one, pdf_file, files_storage
    ):
        response = submit(
            auth_client(requester),
            "SIMPLE",
            {"reason": "x"},
            [pdf_file("notes.docx", content_type="application/msword")],
        )

        assert response.status_code == 400
        [error] = response.json()["errors"]
        assert error["field"] == "documents"
        assert "unsupported type" in error["msg"]
        assert File.objects.count() == 0
        assert files_storage.listdir("")[1] == []

    def test_oversized_document(
        self, settings, auth_client, simple_type, requester, approver_one, pdf_file
    ):
        settings.FILE_MAX_SIZE_BYTES = 5

        response = submit(auth_client(requester), "SIMPLE", {"reason": "x"}, [pdf_file("big.pdf")])

        assert response.status_code == 400
        [error] = response.json()["errors"]
        assert error["field"] == "documents"
        assert "exceeds the 5 byte limit" in error["msg"]
        assert File.objects.count() == 0

    def test_too_many_documents(
        self, settings, auth_client, simple_type, requester, approver_one, pdf_file
    ):
        settings.FILE_MAX_COUNT_PER_UPLOAD = 1

        response = submit(
            auth_client(requester),
            "SIMPLE",
            {"reason": "x"},
            [pdf_file("a.pdf"), pdf_file("b.pdf")],
        )

        assert response.status_code == 400
        [error] = response.json()["errors"]
        assert error["field"] == "documents"
        assert "At most 1 documents" in error["msg"]
        assert File.objects.count() == 0

    def test_apps_files_validation_errors_become_400(
        self, monkeypatch, auth_client, simple_type, requester, approver_one, pdf_file
    ):
        # Anything apps.files rejects that this app did not pre-check must
        # still reach the client as a 400, not a 500.
        from django.core.exceptions import ValidationError

        def reject(payload):
            raise ValidationError("storage refused this file.")

        monkeypatch.setattr(files, "upload_file", reject)

        response = submit(auth_client(requester), "SIMPLE", {"reason": "x"}, [pdf_file()])

        assert response.status_code == 400
        assert response.json()["errors"] == [
            {"code": "E02007", "msg": "storage refused this file.", "field": "documents"}
        ]


@pytest.mark.django_db
class TestFailedSubmissionLeavesNothingBehind:
    """Regression: a request that fails after upload must not orphan its files.

    Storage writes are not transactional. Before this change a routing error
    rolled the database back but left the uploaded object in storage.
    """

    def test_routing_failure_removes_uploaded_files(
        self, lawyer_bar_type, requester, pdf_file, files_storage
    ):
        # BAR_ID_APPROVER has no members here, so routing fails after upload.
        with pytest.raises(ApprovalRoutingError):
            services.create_request(
                request_type=lawyer_bar_type,
                requester=requester,
                data={"name": "Jane", "bar_number": "KAR/1"},
                files=[pdf_file("cert.pdf")],
            )

        assert Request.objects.count() == 0
        assert RequestDocument.objects.count() == 0
        assert File.objects.count() == 0
        assert files_storage.listdir("")[1] == []

    def test_routing_failure_over_api_is_409_and_clean(
        self, auth_client, lawyer_bar_type, requester, pdf_file, files_storage
    ):
        response = submit(
            auth_client(requester),
            "LAWYER_BAR_UPDATE",
            {"name": "Jane", "bar_number": "KAR/1"},
            [pdf_file("cert.pdf")],
        )

        assert response.status_code == 409
        assert File.objects.count() == 0

    def test_cleanup_failure_does_not_mask_the_original_error(
        self, monkeypatch, lawyer_bar_type, requester, pdf_file
    ):
        def broken_delete(file_id):
            raise RuntimeError("storage unreachable")

        monkeypatch.setattr(files, "delete_file", broken_delete)

        with pytest.raises(ApprovalRoutingError):
            services.create_request(
                request_type=lawyer_bar_type,
                requester=requester,
                data={"name": "Jane", "bar_number": "KAR/1"},
                files=[pdf_file()],
            )


@pytest.mark.django_db
class TestDocumentsAreProtected:
    """A file a request depends on cannot be deleted out from under it."""

    def test_delete_file_is_blocked_while_attached(
        self, simple_type, requester, approver_one, pdf_file
    ):
        request = services.create_request(
            request_type=simple_type,
            requester=requester,
            data={"reason": "x"},
            files=[pdf_file()],
        )
        file_id = request.documents.get().file_id

        with pytest.raises(ProtectedError):
            files.delete_file(file_id)

        assert File.objects.filter(pk=file_id).exists()


@pytest.mark.django_db
class TestDownloadStreamsThroughAppsFiles:
    """Downloads read through apps.files and keep the request's access rules."""

    @pytest.fixture
    def document(self, simple_type, requester, approver_one, pdf_file):
        request = services.create_request(
            request_type=simple_type,
            requester=requester,
            data={"reason": "x"},
            files=[pdf_file("scan.png", content_type="image/png", content=b"\x89PNG bytes")],
        )
        return request.documents.get()

    def url(self, document):
        return reverse("request-document-download", args=[document.request_id, document.pk])

    def test_streams_stored_content_with_recorded_type(self, auth_client, requester, document):
        response = auth_client(requester).get(self.url(document))

        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert 'filename="scan.png"' in response["Content-Disposition"]
        assert b"".join(response.streaming_content) == b"\x89PNG bytes"

    def test_outsider_still_gets_404(self, auth_client, outsider, document):
        assert auth_client(outsider).get(self.url(document)).status_code == 404

    def test_oversized_stored_file_is_413(self, settings, auth_client, requester, document):
        settings.FILE_MAX_READ_BYTES = 1

        response = auth_client(requester).get(self.url(document))

        assert response.status_code == 413

    def test_missing_stored_file_is_404(self, auth_client, requester, document):
        # Deactivated files read as missing in apps.files.
        File.objects.filter(pk=document.file_id).update(is_active=False)

        assert auth_client(requester).get(self.url(document)).status_code == 404
