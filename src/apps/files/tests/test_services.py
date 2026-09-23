"""Tests for the files service layer (spec 0014 sections 3, 6, 7, 8, 9)."""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError

from apps.files import storage as file_storage
from apps.files.models import File, FileTag, FileType
from apps.files.services import (
    FileNotFound,
    get_file,
    get_file_content,
    get_file_url,
    search_file,
    upload_file,
)
from apps.files.tests.factories import make_user
from apps.organizations.tests.factories import make_organization

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def in_memory_storage(settings):
    """Keep uploaded content in memory so tests never touch the filesystem."""
    settings.STORAGES = {
        **settings.STORAGES,
        "files": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def user():
    """Return a user to attribute uploads to."""
    return make_user()


def upload(name="a.pdf", content=b"hello", file_type=FileType.DOCUMENT, content_type=None):
    """Return an in-memory uploaded file."""
    return SimpleUploadedFile(name, content, content_type=content_type or "application/pdf")


def entry(file=None, file_type=FileType.DOCUMENT, tags=None):
    """Return one ``files[]`` entry."""
    item = {"file": file if file is not None else upload(), "file_type": file_type}
    if tags is not None:
        item["tags"] = tags
    return item


def payload(user, files=None, organization_id=None):
    """Return an upload_file payload."""
    return {
        "organization_id": organization_id,
        "user_id": user.id,
        "files": files if files is not None else [entry()],
    }


def stored_file_count(prefix="files"):
    """Count objects actually held in storage under ``prefix``.

    Counted recursively: deleting an object leaves its empty parent
    directories behind, and an untouched prefix does not exist at all, so
    neither can be judged from a single ``listdir``.
    """
    try:
        directories, names = file_storage.get_file_storage().listdir(prefix)
    except FileNotFoundError:
        return 0
    return len(names) + sum(stored_file_count(f"{prefix}/{d}") for d in directories)


class TestUploadFile:
    """upload_file stores content and records metadata."""

    def test_single_file_creates_one_record(self, user):
        result = upload_file(payload(user))

        assert len(result["files"]) == 1
        file = File.objects.get(pk=result["files"][0]["id"])
        assert file.file_name == "a.pdf"
        assert file.content_type == "application/pdf"
        assert file.file_size == len(b"hello")
        assert file.user_id == user.id

    def test_content_is_written_to_storage(self, user):
        result = upload_file(payload(user))

        file = File.objects.get(pk=result["files"][0]["id"])
        assert file_storage.get_file_storage().exists(file.storage_path)
        assert get_file_content(file.id).read() == b"hello"

    def test_storage_path_embeds_the_file_id(self, user):
        result = upload_file(payload(user))

        file = File.objects.get(pk=result["files"][0]["id"])
        assert str(file.id) in file.storage_path
        assert file.storage_path.startswith("files/")

    def test_multiple_files_of_different_types_keep_input_order(self, user):
        result = upload_file(
            payload(
                user,
                files=[
                    entry(upload("application.pdf"), FileType.DOCUMENT),
                    entry(upload("portrait.png"), FileType.IMAGE),
                    entry(upload("sign.png"), FileType.SIGNATURE),
                ],
            )
        )

        names = [File.objects.get(pk=item["id"]).file_name for item in result["files"]]
        assert names == ["application.pdf", "portrait.png", "sign.png"]

    def test_organization_is_optional(self, user):
        result = upload_file(payload(user))
        assert File.objects.get(pk=result["files"][0]["id"]).organization_id is None

    def test_organization_is_recorded_when_given(self, user):
        org = make_organization(code="UPLOAD_ORG")

        result = upload_file(payload(user, organization_id=org.id))

        assert File.objects.get(pk=result["files"][0]["id"]).organization_id == org.id

    def test_content_type_falls_back_to_the_file_name(self, user):
        uploaded = upload("report.pdf", content_type="")

        result = upload_file(payload(user, files=[entry(uploaded)]))

        assert File.objects.get(pk=result["files"][0]["id"]).content_type == "application/pdf"


class TestUploadFileTags:
    """Tags are normalized on the way in and shared between files."""

    def test_tags_are_normalized(self, user):
        result = upload_file(payload(user, files=[entry(tags=["Address Proof", "IDENTITY"])]))

        file = File.objects.get(pk=result["files"][0]["id"])
        assert sorted(file.tags.values_list("name", flat=True)) == ["address-proof", "identity"]

    def test_tags_are_reused_across_uploads(self, user):
        upload_file(payload(user, files=[entry(upload("a.pdf"), tags=["identity"])]))
        upload_file(payload(user, files=[entry(upload("b.pdf"), tags=["Identity"])]))

        assert FileTag.objects.count() == 1
        assert FileTag.objects.get(name="identity").files.count() == 2

    def test_invalid_tag_is_rejected_and_nothing_is_stored(self, user):
        with pytest.raises(ValidationError):
            upload_file(payload(user, files=[entry(tags=["नीति"])]))

        assert File.objects.count() == 0

    def test_tags_given_as_a_string_are_rejected(self, user):
        """A bare string is iterable: it must not become one tag per character."""
        with pytest.raises(ValidationError):
            upload_file(payload(user, files=[entry(tags="invoices")]))

        assert FileTag.objects.count() == 0
        assert File.objects.count() == 0

    def test_non_string_tags_are_rejected(self, user):
        with pytest.raises(ValidationError):
            upload_file(payload(user, files=[entry(tags=[1, None])]))

        assert FileTag.objects.count() == 0
        assert File.objects.count() == 0

    def test_tags_are_validated_before_anything_is_stored(self, user):
        """An unusable tag on the second entry must not leave the first stored."""
        with pytest.raises(ValidationError):
            upload_file(
                payload(
                    user,
                    files=[entry(upload("good.pdf")), entry(upload("bad.pdf"), tags=["---"])],
                )
            )

        assert FileTag.objects.count() == 0
        assert File.objects.count() == 0


class TestUploadFileValidation:
    """Section 8: the service validates, since there are no serializers."""

    def test_missing_user_id_is_rejected(self, user):
        with pytest.raises(ValidationError):
            upload_file({"user_id": None, "files": [entry()]})

    def test_empty_file_list_is_rejected(self, user):
        with pytest.raises(ValidationError):
            upload_file(payload(user, files=[]))

    def test_files_given_as_a_string_are_rejected(self, user):
        with pytest.raises(ValidationError):
            upload_file(payload(user, files="abc"))

    def test_missing_file_is_rejected(self, user):
        with pytest.raises(ValidationError):
            upload_file(payload(user, files=[{"file_type": FileType.DOCUMENT}]))

    def test_unknown_file_type_is_rejected(self, user):
        with pytest.raises(ValidationError):
            upload_file(payload(user, files=[entry(file_type="not_a_real_type")]))

    def test_file_over_the_size_limit_is_rejected(self, user, settings):
        settings.FILE_MAX_SIZE_BYTES = 4

        with pytest.raises(ValidationError):
            upload_file(payload(user, files=[entry(upload(content=b"too long"))]))

    def test_too_many_files_are_rejected(self, user, settings):
        settings.FILE_MAX_COUNT_PER_UPLOAD = 2

        with pytest.raises(ValidationError):
            upload_file(payload(user, files=[entry(upload(f"{i}.pdf")) for i in range(3)]))

    def test_validation_runs_before_anything_is_stored(self, user):
        """A bad second entry must not leave the first one in storage."""
        with pytest.raises(ValidationError):
            upload_file(
                payload(
                    user,
                    files=[entry(upload("good.pdf")), entry(file_type="not_a_real_type")],
                )
            )

        assert File.objects.count() == 0
        assert stored_file_count() == 0


class TestUploadFailureHandling:
    """Section 9: a failed upload leaves neither metadata nor orphaned objects."""

    def test_storage_failure_creates_no_record(self, user, monkeypatch):
        def fail(path, file):
            raise OSError("bucket unreachable")

        monkeypatch.setattr(file_storage, "save", fail)

        with pytest.raises(OSError, match="bucket unreachable"):
            upload_file(payload(user))

        assert File.objects.count() == 0

    def test_later_storage_failure_discards_earlier_objects(self, user, monkeypatch):
        real_save = file_storage.save
        calls = {"n": 0}

        def fail_on_second(path, file):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("bucket unreachable")
            return real_save(path, file)

        monkeypatch.setattr(file_storage, "save", fail_on_second)

        with pytest.raises(OSError):
            upload_file(payload(user, files=[entry(upload("a.pdf")), entry(upload("b.pdf"))]))

        assert File.objects.count() == 0
        assert stored_file_count() == 0

    def test_database_failure_discards_the_uploaded_object(self, user, monkeypatch):
        def fail(self, *args, **kwargs):
            raise IntegrityError("constraint blew up")

        monkeypatch.setattr(File, "save", fail)

        with pytest.raises(IntegrityError):
            upload_file(payload(user))

        assert File.objects.count() == 0
        assert stored_file_count() == 0


class TestGetFile:
    """Section 6."""

    def test_returns_metadata_without_the_storage_path(self, user):
        result = upload_file(payload(user, files=[entry(tags=["verification"])]))
        file_id = result["files"][0]["id"]

        data = get_file(file_id)

        assert data["id"] == file_id
        assert data["file_name"] == "a.pdf"
        assert data["tags"] == ["verification"]
        assert "storage_path" not in data

    def test_unknown_id_raises_rather_than_returning_none(self):
        import uuid

        with pytest.raises(FileNotFound):
            get_file(uuid.uuid4())

    def test_malformed_id_raises_file_not_found(self):
        with pytest.raises(FileNotFound):
            get_file("not-a-uuid")


class TestSearchFile:
    """Section 7."""

    @pytest.fixture
    def corpus(self, user):
        """Two organizations, two users, a mix of types and tags."""
        org = make_organization(code="SEARCH_ORG")
        other_user = make_user()

        upload_file(
            payload(
                user,
                organization_id=org.id,
                files=[entry(upload("a.pdf"), FileType.DOCUMENT, ["verification", "identity"])],
            )
        )
        upload_file(payload(user, files=[entry(upload("b.png"), FileType.IMAGE, ["verification"])]))
        upload_file(payload(other_user, files=[entry(upload("c.pdf"), FileType.DOCUMENT)]))
        return org, user, other_user

    def test_filter_by_organization(self, corpus):
        org, _, _ = corpus
        assert search_file({"organization_id": org.id})["count"] == 1

    def test_filter_by_user(self, corpus):
        _, uploader, other = corpus

        assert search_file({"user_id": uploader.id})["count"] == 2
        assert search_file({"user_id": other.id})["count"] == 1

    def test_filter_by_file_type(self, corpus):
        assert search_file({"file_type": FileType.DOCUMENT})["count"] == 2
        assert search_file({"file_type": FileType.IMAGE})["count"] == 1

    def test_filter_by_tag(self, corpus):
        assert search_file({"tags": ["verification"]})["count"] == 2

    def test_multiple_tags_require_all_of_them(self, corpus):
        assert search_file({"tags": ["verification", "identity"]})["count"] == 1

    def test_tag_filter_is_normalized(self, corpus):
        assert search_file({"tags": ["Verification"]})["count"] == 2

    def test_tag_filter_given_as_a_string_is_rejected(self, corpus):
        """Iterating a string would AND one filter per character and find nothing."""
        with pytest.raises(ValidationError):
            search_file({"tags": "verification"})

    def test_filters_are_anded(self, corpus):
        org, _, _ = corpus

        assert (
            search_file(
                {
                    "organization_id": org.id,
                    "file_type": FileType.DOCUMENT,
                    "tags": ["verification"],
                }
            )["count"]
            == 1
        )

    def test_no_filters_returns_everything(self, corpus):
        assert search_file()["count"] == 3

    def test_results_are_newest_first(self, corpus):
        names = [item["file_name"] for item in search_file()["results"]]
        assert names == ["c.pdf", "b.png", "a.pdf"]

    def test_pagination(self, corpus):
        first = search_file(page=1, page_size=2)

        assert len(first["results"]) == 2
        assert first["count"] == 3
        assert first["num_pages"] == 2
        assert first["page"] == 1

        second = search_file(page=2, page_size=2)
        assert len(second["results"]) == 1
        assert second["page"] == 2

    def test_results_omit_the_storage_path(self, corpus):
        assert all("storage_path" not in item for item in search_file()["results"])


class TestInactiveFiles:
    """A deactivated file is reported as missing by every read path.

    ``BaseActivatableModel`` deliberately does not filter by default (spec
    0006), so the service layer has to opt in; the admin keeps querying the
    model directly and still sees the row.
    """

    @pytest.fixture
    def deactivated(self, user):
        """Return the id of an uploaded file that has since been deactivated."""
        result = upload_file(payload(user, files=[entry(tags=["retired"])]))
        file_id = result["files"][0]["id"]
        File.objects.filter(pk=file_id).update(is_active=False)
        return file_id

    def test_search_omits_it(self, deactivated):
        assert search_file()["count"] == 0
        assert search_file({"tags": ["retired"]})["count"] == 0

    def test_get_file_raises(self, deactivated):
        with pytest.raises(FileNotFound):
            get_file(deactivated)

    def test_get_file_content_raises(self, deactivated):
        with pytest.raises(FileNotFound):
            get_file_content(deactivated)

    def test_get_file_url_raises(self, deactivated):
        with pytest.raises(FileNotFound):
            get_file_url(deactivated)

    def test_the_row_and_its_content_are_kept(self, deactivated):
        """Deactivating hides a file; it does not delete it."""
        file = File.objects.get(pk=deactivated)
        assert file.is_active is False
        assert file_storage.get_file_storage().exists(file.storage_path)

    def test_reactivating_makes_it_visible_again(self, deactivated):
        File.objects.filter(pk=deactivated).update(is_active=True)

        assert search_file()["count"] == 1
        assert get_file(deactivated)["tags"] == ["retired"]


class TestGetFileUrl:
    """``get_file_url`` signs against S3_PUBLIC_ENDPOINT when one is set.

    The endpoint the server uploads through is not always reachable by a
    client, and a signed URL's host cannot be swapped afterwards because
    SigV4 covers it.
    """

    S3_OPTIONS = {
        "bucket_name": "test-bucket",
        "endpoint_url": "http://internal-host:9000",
        "access_key": "test-access-key",
        "secret_key": "test-secret-key",
        "signature_version": "s3v4",
        "region_name": "us-east-1",
        "querystring_auth": True,
        "location": "media",
    }

    @pytest.fixture
    def stored_file(self, user):
        """Return a File row; its content lives in the in-memory backend."""
        result = upload_file(payload(user))
        return File.objects.get(pk=result["files"][0]["id"])

    @pytest.fixture
    def s3_backend(self, settings, stored_file):
        """Point the files alias at an S3 backend, without reaching the network.

        Depends on ``stored_file`` so the upload happens against the in-memory
        backend first: signing a URL is local, but storing content is not, and
        this endpoint does not exist.
        """
        settings.STORAGES = {
            **settings.STORAGES,
            "files": {
                "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
                "OPTIONS": self.S3_OPTIONS,
            },
        }

    def test_public_endpoint_replaces_the_internal_host(self, settings, s3_backend, stored_file):
        settings.S3_PUBLIC_ENDPOINT = "http://localhost:9000"

        url = get_file_url(stored_file.id)

        assert url.startswith("http://localhost:9000/test-bucket/")
        assert "internal-host" not in url

    def test_the_url_is_signed_and_expires(self, settings, s3_backend, stored_file):
        settings.S3_PUBLIC_ENDPOINT = "http://localhost:9000"

        url = get_file_url(stored_file.id)

        assert "X-Amz-Signature=" in url
        assert "X-Amz-Expires=3600" in url

    def test_the_backend_location_prefix_is_applied(self, settings, s3_backend, stored_file):
        """The key in the URL is the bucket key, not the path the backend was given."""
        settings.S3_PUBLIC_ENDPOINT = "http://localhost:9000"

        url = get_file_url(stored_file.id)

        assert f"/test-bucket/media/{stored_file.storage_path}?" in url

    def test_without_a_public_endpoint_the_backend_url_is_used(self, settings, stored_file):
        """Unset is the production default, and must not change today's behavior."""
        settings.S3_PUBLIC_ENDPOINT = None

        assert get_file_url(stored_file.id) == file_storage.get_file_storage().url(
            stored_file.storage_path
        )

    def test_a_non_s3_backend_ignores_the_public_endpoint(self, settings, stored_file):
        """The filesystem backend has no bucket and signs nothing."""
        settings.S3_PUBLIC_ENDPOINT = "http://localhost:9000"

        assert "localhost:9000" not in get_file_url(stored_file.id)
