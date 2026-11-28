"""The metadata lifecycle: read, search and delete (spec 0014 §6–7)."""

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.files import services
from apps.files.models import File, FileTag, FileType
from apps.files.services import FileNotFound
from apps.files.tests.factories import make_user
from apps.organizations.tests.factories import make_organization

from .conftest import stored_paths

pytestmark = pytest.mark.django_db


def upload_one(user, name="address-proof.pdf", file_type=FileType.DOCUMENT, tags=None, **common):
    """Upload one file and return its id."""
    result = services.upload_file(
        {
            "user_id": user.pk,
            **common,
            "files": [
                {
                    "file": SimpleUploadedFile(name, b"%PDF-1.4 fake", "application/pdf"),
                    "file_type": file_type,
                    **({"tags": tags} if tags else {}),
                }
            ],
        }
    )
    return result["files"][0]["id"]


class OpenCountingStorage(InMemoryStorage):
    """An in-memory storage counting how many objects were opened."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.opens = 0

    def open(self, name, mode="rb"):
        """Count the open, then serve it."""
        self.opens += 1
        return super().open(name, mode)


@pytest.mark.scenario("FILE-LIFECYCLE-1")
def test_get_file_content_returns_the_uploaded_bytes(uploader, files_storage):
    """The content round-trips byte for byte; the caller owns and closes the stream."""
    file_id = upload_one(uploader)

    stream = services.get_file_content(file_id)
    try:
        assert stream.read() == b"%PDF-1.4 fake"
    finally:
        stream.close()


@pytest.mark.scenario("FILE-LIFECYCLE-2")
def test_unknown_and_malformed_ids_are_indistinguishable(uploader, files_storage):
    """Every lookup raises FileNotFound for a malformed or random id; never None."""
    upload_one(uploader)

    for bad_id in ("not-a-uuid", uuid4()):
        with pytest.raises(FileNotFound):
            services.get_file(bad_id)
        with pytest.raises(FileNotFound):
            services.get_file_content(bad_id)
        with pytest.raises(FileNotFound):
            services.delete_file(bad_id)


@pytest.mark.scenario("FILE-LIFECYCLE-3")
def test_the_read_limit_is_checked_before_the_object_is_opened(uploader, settings):
    """An oversized file costs a metadata read, not a transfer: the storage sees no open."""
    settings.STORAGES = {
        **settings.STORAGES,
        "files": {
            "BACKEND": "apps.files.tests.integration.test_lifecycle_flow.OpenCountingStorage"
        },
    }
    from django.core.files.storage import storages

    storage = storages["files"]
    file_id = upload_one(uploader)

    settings.FILE_MAX_READ_BYTES = len(b"%PDF-1.4 fake") - 1
    with pytest.raises(ValidationError):
        services.get_file_content(file_id)

    assert storage.opens == 0


@pytest.mark.scenario("FILE-LIFECYCLE-4")
def test_delete_removes_object_and_row_but_not_the_tags(uploader, files_storage):
    """Deletion is not idempotent; FileTag rows survive for other files to carry."""
    file_id = upload_one(uploader, tags=["identity", "address proof"])
    (path,) = stored_paths(files_storage)

    services.delete_file(file_id)

    assert not files_storage.exists(path)
    assert not File.objects.filter(pk=file_id).exists()
    assert FileTag.objects.count() == 2

    with pytest.raises(FileNotFound):
        services.delete_file(file_id)


@pytest.mark.scenario("FILE-LIFECYCLE-5")
def test_search_filters_are_anded_and_tags_must_all_match(files_storage):
    """organization + user + file_type + all-of tags narrow together; bad type is empty."""
    org_a, org_b = make_organization(code="ORG_A"), make_organization(code="ORG_B")
    user_a, user_b = make_user(), make_user()
    target = upload_one(
        user_a, file_type=FileType.PDF, tags=["identity", "signed"], organization_id=org_a.pk
    )
    image = upload_one(
        user_a, file_type=FileType.IMAGE, tags=["identity"], organization_id=org_a.pk
    )
    other = upload_one(user_b, file_type=FileType.PDF, tags=["identity"], organization_id=org_b.pk)

    def ids(filters):
        return {row["id"] for row in services.search_file(filters)["results"]}

    assert ids({"organization_id": org_a.pk}) == {target, image}
    assert ids({"user_id": user_b.pk}) == {other}
    # Filters are ANDed: org_b's pdfs are just user_b's file.
    assert ids({"file_type": "pdf", "organization_id": org_b.pk}) == {other}
    # Tags must all match; the image carries only one of them.
    assert ids({"tags": ["identity", "signed"]}) == {target}
    assert ids({"tags": ["identity"]}) == {target, image, other}
    # A wrong-case type is an empty page, not an error; unknown keys are ignored.
    assert services.search_file({"file_type": "PDF"})["results"] == []
    assert services.search_file({"bogus": "filter", "file_type": "pdf"})["count"] == 2


@pytest.mark.scenario("FILE-LIFECYCLE-6")
def test_search_paginates_newest_first_and_never_silently_repages(uploader, files_storage):
    """Page 2 holds the oldest rows; a page past the end serves the last page, labelled."""
    for batch in range(3):  # FILE_MAX_COUNT_PER_UPLOAD caps one call at 10
        services.upload_file(
            {
                "user_id": uploader.pk,
                "files": [
                    {
                        "file": _numbered_upload(batch, index),
                        "file_type": FileType.DOCUMENT,
                    }
                    for index in range(10 if batch < 2 else 5)
                ],
            }
        )

    page_two = services.search_file(page=2, page_size=20)
    assert page_two["count"] == 25
    assert page_two["num_pages"] == 2
    assert page_two["page"] == 2
    assert len(page_two["results"]) == 5

    past_the_end = services.search_file(page=9, page_size=20)
    assert past_the_end["page"] == 2
    assert len(past_the_end["results"]) == 5

    with pytest.raises(ValidationError):
        services.search_file(page=0)
    with pytest.raises(ValidationError):
        services.search_file(page_size=0)


def _numbered_upload(batch, index):
    """Return a distinctly named small upload."""
    return SimpleUploadedFile(f"doc-{batch}-{index}.pdf", b"%PDF-1.4 fake", "application/pdf")
