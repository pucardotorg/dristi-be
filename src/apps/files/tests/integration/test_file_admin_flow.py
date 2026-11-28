"""The files admin drives visibility (spec 0014 §6.4, §11; spec 0037 §5).

Every beat POSTs the real admin form as a superuser; the service is then
re-queried — the sequence *operator edits in admin → service behavior
changes* is the contract under test.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.files import services
from apps.files.models import File, FileTag, FileType
from apps.files.services import FileNotFound

from .conftest import stored_paths

pytestmark = pytest.mark.django_db


def upload_one(user, tags=None):
    """Upload one small file and return its File row."""
    result = services.upload_file(
        {
            "user_id": user.pk,
            "files": [
                {
                    "file": SimpleUploadedFile("doc.pdf", b"%PDF-1.4 fake", "application/pdf"),
                    "file_type": FileType.DOCUMENT,
                    **({"tags": tags} if tags else {}),
                }
            ],
        }
    )
    return File.objects.get(pk=result["files"][0]["id"])


def set_active(admin_client, file, active):
    """Toggle is_active through the real change-view POST."""
    response = admin_client.post(
        reverse("admin:files_file_change", args=[file.pk]),
        {
            "file_name": file.file_name,
            "file_type": file.file_type,
            "organization": "",
            "user": str(file.user_id),
            **({"is_active": "on"} if active else {}),
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    file.refresh_from_db()


@pytest.mark.scenario("FILE-ADMIN-1")
def test_deactivating_a_file_hides_it_from_every_read_path(uploader, admin_client, files_storage):
    """Unchecked is_active: get_file and get_file_content miss it, search excludes it."""
    file = upload_one(uploader)

    set_active(admin_client, file, False)

    with pytest.raises(FileNotFound):
        services.get_file(file.pk)
    with pytest.raises(FileNotFound):
        services.get_file_content(file.pk)
    assert services.search_file()["count"] == 0


@pytest.mark.scenario("FILE-ADMIN-2")
def test_reactivating_a_file_restores_it(uploader, admin_client, files_storage):
    """Deactivation is a soft hide, not a delete: the file comes back on every path."""
    file = upload_one(uploader)
    set_active(admin_client, file, False)

    set_active(admin_client, file, True)

    assert services.get_file(file.pk)["id"] == file.pk
    assert services.search_file()["count"] == 1


@pytest.mark.scenario("FILE-ADMIN-3")
def test_a_deactivated_file_is_still_deletable(uploader, admin_client, files_storage):
    """Cleanup is the one operation that must reach deactivated files."""
    file = upload_one(uploader)
    set_active(admin_client, file, False)
    (path,) = stored_paths(files_storage)

    services.delete_file(file.pk)

    assert not files_storage.exists(path)
    assert not File.objects.filter(pk=file.pk).exists()


@pytest.mark.scenario("FILE-ADMIN-4")
def test_files_cannot_be_added_through_the_admin(admin_client):
    """The add view is refused: a row created there would point at no stored object."""
    assert admin_client.get(reverse("admin:files_file_add")).status_code == 403


@pytest.mark.scenario("FILE-ADMIN-5")
def test_a_tag_added_through_the_admin_is_slugified_and_reused(
    uploader, admin_client, files_storage
):
    """'Address Proof' stored via FileTagAdmin is address-proof; uploads reuse that row."""
    response = admin_client.post(reverse("admin:files_filetag_add"), {"name": "Address Proof"})
    assert response.status_code == 302, response.content.decode()[:2000]
    assert FileTag.objects.get().name == "address-proof"

    file = upload_one(uploader, tags=["Address Proof"])

    assert services.get_file(file.pk)["tags"] == ["address-proof"]
    assert FileTag.objects.count() == 1
