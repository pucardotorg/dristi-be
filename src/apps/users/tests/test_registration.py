"""Service-level tests for completing registration with a document."""

from unittest.mock import patch

from django.core.files.storage import storages
from django.test import TestCase, override_settings

from apps.files.models import File
from apps.files.storage import STORAGE_ALIAS
from apps.users.documents import BAR_COUNCIL_ID_TAG
from apps.users.models import AdvocateProfile, Role, User
from apps.users.services.registration import complete_registration_with_document

from .base import MOBILE, PASSWORD
from .test_api import IN_MEMORY_FILES, pdf_upload


def stored_paths(directory=""):
    """Return every object in the files storage, walking nested directories."""
    storage = storages[STORAGE_ALIAS]
    directories, names = storage.listdir(directory)
    paths = [f"{directory}{name}" for name in names]
    for child in directories:
        paths += stored_paths(f"{directory}{child}/")
    return paths


@override_settings(STORAGES=IN_MEMORY_FILES)
class CompleteRegistrationWithDocumentTests(TestCase):
    """The upload and the registration succeed or fail together."""

    def setUp(self):
        """Create an account sitting at PENDING_PROFILE, with empty file storage.

        The in-memory storage lives as long as the class-level override, so
        an object a test leaves behind would otherwise leak into the next.
        """
        self.user = User.objects.create_user(mobile_number=MOBILE)
        for path in stored_paths():
            storages[STORAGE_ALIAS].delete(path)

    def register(self):
        """Complete an advocate registration with a valid bar ID."""
        return complete_registration_with_document(
            user=self.user,
            document=pdf_upload(),
            document_tag=BAR_COUNCIL_ID_TAG,
            role=Role.ADVOCATE,
            profile_model=AdvocateProfile,
            name="Asha Menon",
            password=PASSWORD,
            profile_fields={"bar_registration_id": "KER/1234/2019"},
        )

    def test_failed_registration_removes_the_stored_file(self):
        """A registration that fails after the upload leaves no file behind.

        The upload commits on its own, outside the registration transaction,
        so without the cleanup both the row and the stored object would stay.
        """
        with (
            patch(
                "apps.users.services.registration.complete_registration",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.register()

        self.assertFalse(File.objects.exists())
        self.assertEqual(stored_paths(), [])
