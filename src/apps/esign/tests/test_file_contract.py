"""Contract tests against the real ``apps.files`` (spec 0014, spec 0015 #4.2).

The rest of the suite uses ``FakeFileClient``, which accepts any ``file_type``.
That is how upper-case values shipped after ``FileType`` moved to lower-case
values: every upload failed in production while the tests stayed green. These
tests run the real adapter against the real storage module instead.
"""

import pytest
from django.core.checks import Error

from apps.esign import checks, constants
from apps.esign.clients.files import FileClient
from apps.esign.exceptions import ESignFileStorageRejected
from apps.files.models import FileType
from apps.files.services import get_file
from apps.files.tests.factories import make_user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def in_memory_storage(settings):
    """Keep uploaded content in memory so tests never touch the filesystem."""
    settings.STORAGES = {
        **settings.STORAGES,
        "files": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.mark.parametrize("file_type", [constants.FILE_TYPE_PDF, constants.FILE_TYPE_SIGNED_PDF])
def test_the_module_file_types_are_accepted_by_storage(file_type):
    """Both artefact types this module stores are valid ``FileType`` values."""
    user = make_user()
    file_id = FileClient().upload(
        b"%PDF-1.7\n", filename="a.pdf", file_type=file_type, user_id=str(user.pk)
    )
    assert get_file(file_id)["file_type"] == file_type


def test_a_wrong_file_type_is_reported_with_the_reason():
    """Upper-case ``PDF`` is the member name, not the value; storage says so."""
    user = make_user()
    with pytest.raises(ESignFileStorageRejected) as caught:
        FileClient().upload(b"%PDF-1.7\n", filename="a.pdf", file_type="PDF", user_id=str(user.pk))

    assert caught.value.code == constants.ESIGN_FILE_STORAGE_REJECTED
    assert "file_type" in caught.value.message
    assert "pdf" in caught.value.message


def test_system_check_accepts_the_current_file_types():
    assert checks._check_file_types() == []


def test_system_check_flags_a_file_type_storage_does_not_know(monkeypatch):
    monkeypatch.setattr(constants, "FILE_TYPE_PDF", "PDF")

    messages = checks._check_file_types()

    assert [message.id for message in messages] == ["esign.E007"]
    assert isinstance(messages[0], Error)
    assert FileType.PDF.value in messages[0].hint
