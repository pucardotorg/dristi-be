"""Object Storage access for the files module.

The rest of the module goes through these helpers rather than touching a
storage backend directly, so the storage provider stays an implementation
detail of ``apps.files``. The backend itself is the ``files`` entry in
``settings.STORAGES``: the local filesystem in development, and the
S3-compatible bucket once ``S3_*`` is configured.
"""

import boto3
from botocore.config import Config
from django.conf import settings
from django.core.files.storage import storages
from django.utils import timezone
from django.utils.text import get_valid_filename

STORAGE_ALIAS = "files"

DEFAULT_URL_EXPIRY_SECONDS = 3600


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

    When ``S3_PUBLIC_ENDPOINT`` is set the URL is signed against that endpoint
    instead of the one the server uploads through, so it names a host the
    client can actually reach. The signature covers the host, so the two
    cannot be swapped after the fact.
    """
    options = _s3_options()
    if not settings.S3_PUBLIC_ENDPOINT or not options:
        return get_file_storage().url(storage_path)
    return _public_signed_url(storage_path, options)


def _s3_options():
    """Return the ``OPTIONS`` of the files backend, or ``None`` if it is not S3.

    The local filesystem backend has no bucket and signs nothing, so there is
    no public endpoint to substitute for it.
    """
    options = settings.STORAGES[STORAGE_ALIAS].get("OPTIONS") or {}
    return options if options.get("bucket_name") else None


def _public_signed_url(storage_path, options):
    """Pre-sign ``storage_path`` against ``settings.S3_PUBLIC_ENDPOINT``.

    The backend prefixes every key with its ``location``, so that prefix has
    to be reapplied here: ``storage_path`` is the key as the backend was asked
    for it, not the key as the bucket holds it.
    """
    client = boto3.client(
        "s3",
        endpoint_url=settings.S3_PUBLIC_ENDPOINT,
        aws_access_key_id=options.get("access_key"),
        aws_secret_access_key=options.get("secret_key"),
        region_name=options.get("region_name"),
        config=Config(signature_version=options.get("signature_version", "s3v4")),
    )
    location = (options.get("location") or "").strip("/")
    key = f"{location}/{storage_path}" if location else storage_path
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": options["bucket_name"], "Key": key},
        ExpiresIn=options.get("querystring_expire", DEFAULT_URL_EXPIRY_SECONDS),
    )
