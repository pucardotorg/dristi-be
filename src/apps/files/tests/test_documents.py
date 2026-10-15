"""Tests for the shared supporting-document rules and store/discard helpers."""

from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.files.documents import (
    discard_documents,
    document_error,
    file_type_for,
    store_documents,
)
from apps.files.models import File, FileType
from apps.files.tests.factories import make_user

PDF = b"%PDF-1.4 test"
JPEG = b"\xff\xd8\xff\xe0 test"
PNG = b"\x89PNG\r\n\x1a\n test"


@pytest.fixture(autouse=True)
def in_memory_storage(settings):
    """Keep uploaded content in memory so tests never touch the filesystem."""
    settings.STORAGES = {
        **settings.STORAGES,
        "files": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


def upload(name="doc.pdf", content=PDF, content_type="application/pdf"):
    """Return an in-memory upload."""
    return SimpleUploadedFile(name, content, content_type=content_type)


class TestDocumentError:
    """What an upload must pass before it is stored."""

    @pytest.mark.parametrize(
        ("name", "content", "content_type", "file_type"),
        [
            ("doc.pdf", PDF, "application/pdf", FileType.PDF),
            ("photo.jpg", JPEG, "image/jpeg", FileType.IMAGE),
            ("photo.jpeg", JPEG, "image/jpeg", FileType.IMAGE),
            ("scan.png", PNG, "image/png", FileType.IMAGE),
            ("DOC.PDF", PDF, "Application/PDF; charset=binary", FileType.PDF),
        ],
    )
    def test_accepted_formats(self, name, content, content_type, file_type):
        document = upload(name, content, content_type)

        assert document_error(document) is None
        assert file_type_for(document) == file_type

    def test_unsupported_type(self):
        document = upload("notes.txt", b"hello", "text/plain")

        assert "unsupported type 'text/plain'" in document_error(document)
        assert file_type_for(document) is None

    def test_extension_must_match_the_type(self):
        assert document_error(upload(name="doc.png")) == (
            "the file extension does not match its type."
        )

    def test_content_must_match_the_type(self):
        assert document_error(upload(content=b"not really a pdf")) == (
            "the file content does not match its type."
        )

    def test_size_limit(self, settings):
        settings.FILE_MAX_SIZE_BYTES = 5

        assert document_error(upload()) == "exceeds the 5 byte limit."

    def test_leaves_the_upload_rewound(self):
        document = upload()
        document_error(document)

        assert document.read() == PDF


@pytest.mark.django_db
class TestStoreAndDiscard:
    """Storing a checked set, and undoing it."""

    def test_stores_in_order_with_tags_and_type(self):
        user = make_user()

        ids = store_documents(
            [upload(), upload("scan.png", PNG, "image/png")], user_id=user.pk, tags=["a-tag"]
        )

        stored = [File.objects.get(pk=file_id) for file_id in ids]
        assert [f.file_name for f in stored] == ["doc.pdf", "scan.png"]
        assert [f.file_type for f in stored] == [FileType.PDF, FileType.IMAGE]
        assert all(list(f.tags.values_list("name", flat=True)) == ["a-tag"] for f in stored)

    def test_discard_removes_stored_files(self):
        ids = store_documents([upload()], user_id=make_user().pk, tags=["a-tag"])

        discard_documents(ids)

        assert not File.objects.exists()

    def test_discard_failure_is_logged_not_raised(self, caplog):
        with patch("apps.files.services.delete_file", side_effect=OSError("storage down")):
            discard_documents(["some-id"])

        assert "Could not discard document some-id" in caplog.text
