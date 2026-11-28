"""Uploading files: all-or-nothing, metadata and tags (spec 0014 §3, §6, §9).

The failure rows inject faults where the codebase already does
(``test_services.py``): a failing storage backend through the ``STORAGES``
setting, and a patched ``File.save`` for the database half — there is no
settings boundary for a database fault.
"""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.files import services
from apps.files.models import File, FileTag, FileType

from .conftest import stored_paths

pytestmark = pytest.mark.django_db


def upload(user, entries, **common):
    """Call upload_file with a normalized payload."""
    return services.upload_file({"user_id": user.pk, **common, "files": entries})


class FailOnSecondSaveStorage(InMemoryStorage):
    """An in-memory storage whose second write fails, as a flaky backend's would."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saves = 0

    def save(self, name, content, max_length=None):
        """Raise on the second object written through this backend."""
        self._saves += 1
        if self._saves == 2:
            raise OSError("storage backend unavailable")
        return super().save(name, content, max_length=max_length)


@pytest.mark.scenario("FILE-UPLOAD-1")
def test_upload_returns_ids_in_order_and_metadata_without_the_storage_key(
    uploader, pdf, files_storage
):
    """Two files in one call: ids in input order; get_file hides the storage internals."""
    image = SimpleUploadedFile("photo.png", b"\x89PNG\r\n\x1a\nfake", content_type="image/png")

    result = upload(
        uploader,
        [
            {"file": pdf("first.pdf"), "file_type": FileType.PDF},
            {"file": image, "file_type": FileType.IMAGE, "tags": ["identity"]},
        ],
    )

    ids = [entry["id"] for entry in result["files"]]
    assert len(ids) == 2 and ids[0] != ids[1]

    first, second = (services.get_file(file_id) for file_id in ids)
    assert first["file_name"] == "first.pdf"
    assert first["file_type"] == FileType.PDF
    assert first["tags"] == []
    assert second["file_name"] == "photo.png"
    assert second["tags"] == ["identity"]

    for metadata in (first, second):
        assert {
            "id",
            "organization_id",
            "user_id",
            "file_type",
            "file_name",
            "content_type",
            "file_size",
            "tags",
            "created_at",
        } == set(metadata)
        assert "storage_path" not in metadata
        assert "is_active" not in metadata
        assert metadata["user_id"] == uploader.pk


@pytest.mark.scenario("FILE-UPLOAD-2")
def test_tags_slugify_and_share_rows(uploader, pdf, files_storage):
    """'Identity', ' identity ' and 'Address Proof' collapse to two global tag rows."""
    result = upload(
        uploader,
        [
            {
                "file": pdf(),
                "file_type": FileType.DOCUMENT,
                "tags": ["Identity", " identity ", "Address Proof"],
            }
        ],
    )

    metadata = services.get_file(result["files"][0]["id"])
    assert metadata["tags"] == ["address-proof", "identity"]
    assert FileTag.objects.count() == 2

    # A second upload with the same spelling reuse the same rows.
    other = upload(
        uploader,
        [{"file": pdf("second.pdf"), "file_type": FileType.PDF, "tags": ["address proof"]}],
    )
    assert services.get_file(other["files"][0]["id"])["tags"] == ["address-proof"]
    assert FileTag.objects.count() == 2


@pytest.mark.scenario("FILE-UPLOAD-3")
def test_an_invalid_entry_aborts_the_whole_call(uploader, pdf, files_storage):
    """A bad file_type is a keyed ValidationError; no rows, no stored objects."""
    with pytest.raises(ValidationError) as excinfo:
        upload(
            uploader,
            [
                {"file": pdf("good.pdf"), "file_type": FileType.PDF},
                {"file": pdf("bad.pdf"), "file_type": "PDF"},  # the stored value is lowercase
            ],
        )

    assert "files[1].file_type" in excinfo.value.message_dict
    assert File.objects.count() == 0
    assert stored_paths(files_storage) == []


@pytest.mark.scenario("FILE-UPLOAD-4")
def test_a_storage_failure_discards_the_objects_written_so_far(uploader, pdf, settings):
    """The second object's write fails: the first object is deleted again, no rows."""
    settings.STORAGES = {
        **settings.STORAGES,
        "files": {
            "BACKEND": "apps.files.tests.integration.test_upload_flow.FailOnSecondSaveStorage"
        },
    }
    from django.core.files.storage import storages

    storage = storages["files"]

    with pytest.raises(OSError, match="storage backend unavailable"):
        upload(
            uploader,
            [
                {"file": pdf("first.pdf"), "file_type": FileType.PDF},
                {"file": pdf("second.pdf"), "file_type": FileType.PDF},
            ],
        )

    assert File.objects.count() == 0
    assert stored_paths(storage) == []


@pytest.mark.scenario("FILE-UPLOAD-5")
def test_a_database_failure_discards_the_uploaded_object(uploader, pdf, files_storage, monkeypatch):
    """The insert fails after the storage write: the object is discarded, the error propagates."""

    def fail(self, *args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(File, "save", fail)

    with pytest.raises(RuntimeError, match="database unavailable"):
        upload(uploader, [{"file": pdf(), "file_type": FileType.PDF}])

    assert File.objects.count() == 0
    assert stored_paths(files_storage) == []
