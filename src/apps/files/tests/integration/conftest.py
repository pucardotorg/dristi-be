"""Shared fixtures for the files integration flows (spec 0037).

``apps.files`` has no REST API in this iteration (spec 0014): its real
surfaces are the service functions and the Django admin, so the fixtures here
are an in-memory storage handle, upload builders and an admin client.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.files.tests.factories import make_user


@pytest.fixture
def files_storage(settings):
    """Keep stored objects in memory; return the live backend for assertions."""
    settings.STORAGES = {
        **settings.STORAGES,
        "files": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }
    from django.core.files.storage import storages

    return storages["files"]


@pytest.fixture
def uploader(db):
    """A user uploads are attributed to."""
    return make_user()


@pytest.fixture
def pdf():
    """Return a factory producing small PDF uploads."""

    def factory(name="address-proof.pdf", content=b"%PDF-1.4 fake"):
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    return factory


@pytest.fixture
def admin_client(db):
    """A Django test client logged in as a superuser, for real admin POSTs (§5)."""
    user = make_user(email="files-admin@example.com", is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(user)
    client.user = user
    return client


def stored_paths(storage):
    """Return every object key held by an in-memory storage backend."""
    found = []

    def walk(prefix):
        dirs, files = storage.listdir(prefix)
        found.extend(prefix + name for name in files)
        for name in dirs:
            walk(f"{prefix}{name}/")

    walk("")
    return found
