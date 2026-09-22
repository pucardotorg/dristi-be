"""Object Storage access for the files module.

The rest of the module goes through these helpers rather than touching a
storage backend directly, so the storage provider stays an implementation
detail of ``apps.files``. The backend itself is the ``files`` entry in
``settings.STORAGES``: the local filesystem in development, and the
S3-compatible bucket once ``S3_*`` is configured.
"""

from django.core.files.storage import storages
from django.utils import timezone
from django.utils.text import get_valid_filename

STORAGE_ALIAS = "files"


def get_file_storage():
    """Return the storage backend that file content is written to."""
    return storages[STORAGE_ALIAS]


def build_storage_path(file_id, file_name):
    """Return the Object Storage key for a file.

    The key embeds ``file_id``, which the caller generates before the content
    is stored, so it is unique without consulting the database. The file name
    is sanitized because it originates from the uploader.
    """
    return f"files/{timezone.now():%Y/%m}/{file_id}/{get_valid_filename(file_name)}"


def save(path, file):
    """Store ``file`` at ``path`` and return the key it was actually written to.

    Backends may adjust the key to avoid a collision, so the returned value is
    what should be persisted, not the requested ``path``.
    """
    return get_file_storage().save(path, file)


def open_file(storage_path):
    """Return a readable file-like object for a stored file."""
    return get_file_storage().open(storage_path)


def delete(storage_path):
    """Delete a stored object."""
    get_file_storage().delete(storage_path)


def get_url(storage_path):
    """Return a URL for a stored object.

    With the S3 backend this is a short-lived pre-signed URL, because
    ``querystring_auth`` is enabled for that backend in settings.
    """
    return get_file_storage().url(storage_path)
