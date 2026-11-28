"""The user-document format gate that consumers share (spec 0014 §3.1).

``apps.files.documents`` is the seam ``dristi_requests`` and the users
registration call before their own 400s; this module pins the contract once.
"""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.files import documents
from apps.files.models import File

from .conftest import stored_paths

pytestmark = pytest.mark.django_db

JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF fake"
PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR fake"
PDF_BYTES = b"%PDF-1.4 fake"


def upload(name, content, content_type):
    """Return a SimpleUploadedFile with real signature bytes."""
    return SimpleUploadedFile(name, content, content_type=content_type)


@pytest.mark.scenario("FILE-DOCUMENTS-1")
def test_the_accepted_formats_pass_and_are_left_rewound():
    """PDF, JPEG and PNG with matching bytes are acceptable; the upload is rewound for storage."""
    uploads = [
        upload("certificate.pdf", PDF_BYTES, "application/pdf"),
        upload("photo.jpg", JPEG_BYTES, "image/jpeg"),
        upload("scan.png", PNG_BYTES, "image/png"),
    ]

    for item in uploads:
        assert documents.document_error(item) is None
        assert item.tell() == 0  # left rewound for the real storage pass

    assert [documents.file_type_for(item) for item in uploads] == ["pdf", "image", "image"]


@pytest.mark.scenario("FILE-DOCUMENTS-2")
def test_a_pdf_name_on_png_bytes_is_refused():
    """The declared type and the name are client hints; the leading bytes decide."""
    forged = upload("scan.pdf", PNG_BYTES, "application/pdf")

    assert documents.document_error(forged) == "the file content does not match its type."


@pytest.mark.scenario("FILE-DOCUMENTS-3")
def test_an_oversized_document_is_refused_and_nothing_is_stored(uploader, files_storage, settings):
    """The size limit binds in document_error and again in store_documents."""
    settings.FILE_MAX_SIZE_BYTES = 4
    big = upload("big.pdf", PDF_BYTES, "application/pdf")

    assert documents.document_error(big) == "exceeds the 4 byte limit."

    with pytest.raises(ValidationError):
        documents.store_documents([big], user_id=uploader.pk, tags=["case-docs"])
    assert File.objects.count() == 0
    assert stored_paths(files_storage) == []


@pytest.mark.scenario("FILE-DOCUMENTS-4")
def test_store_then_discard_round_trips_and_discard_only_logs(uploader, files_storage, caplog):
    """Three checked uploads store all-or-nothing, then discard removes them quietly."""
    uploads = [
        upload("certificate.pdf", PDF_BYTES, "application/pdf"),
        upload("photo.jpg", JPEG_BYTES, "image/jpeg"),
        upload("scan.png", PNG_BYTES, "image/png"),
    ]

    file_ids = documents.store_documents(uploads, user_id=uploader.pk, tags=["case-docs"])

    assert len(file_ids) == 3
    assert File.objects.count() == 3
    assert [services_get(file_id)["tags"] for file_id in file_ids] == [["case-docs"]] * 3

    documents.discard_documents(file_ids)
    assert File.objects.count() == 0
    assert stored_paths(files_storage) == []

    # A second discard only logs: cleanup failures never raise.
    with caplog.at_level("ERROR", logger="apps.files.documents"):
        documents.discard_documents(file_ids)
    assert len(caplog.records) == 3


def services_get(file_id):
    """Return a file's metadata (a tiny alias to keep assertions readable)."""
    from apps.files import services

    return services.get_file(file_id)
