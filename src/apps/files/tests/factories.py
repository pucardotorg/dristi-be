"""Shared File fixtures for the files test suite."""

from uuid import uuid4

from apps.files.models import File, FileTag, FileType
from apps.users.models import User

DEFAULTS = {
    "file_type": FileType.DOCUMENT,
    "file_name": "address-proof.pdf",
    "content_type": "application/pdf",
    "file_size": 245678,
}


def make_user(**overrides):
    """Create a user that uploads can be attributed to.

    Email and username default to unique values so repeated calls do not
    collide on the uniqueness constraints of the user model.
    """
    handle = overrides.pop("username", f"uploader-{uuid4().hex[:8]}")
    return User.objects.create_user(
        email=overrides.pop("email", f"{handle}@example.com"),
        username=handle,
        password="test-password",
        **overrides,
    )


def make_tag(name="verification"):
    """Create a file tag, normalized by the model's clean()."""
    return FileTag.objects.create(name=name)


def make_file(user=None, tags=None, **overrides):
    """Create a File with sensible defaults and an unused storage path."""
    storage_path = overrides.pop("storage_path", f"files/2026/09/{uuid4()}/address-proof.pdf")
    file = File.objects.create(
        user=user if user is not None else make_user(),
        storage_path=storage_path,
        **{**DEFAULTS, **overrides},
    )
    if tags is not None:
        file.tags.set(tags)
    return file
