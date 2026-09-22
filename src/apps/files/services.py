"""File storage domain services: upload, retrieval, and search.

This module is consumed in-process by other Django apps. Every public function
is a plain callable that takes and returns plain data structures; nothing here
depends on request/response objects, DRF, or HTTP status codes, and failures
are raised as exceptions rather than translated into responses.
"""

import os
import uuid
from contextlib import suppress
from mimetypes import guess_type

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction

from . import storage as file_storage
from .models import File, FileTag, FileType

FALLBACK_CONTENT_TYPE = "application/octet-stream"


class FileNotFound(Exception):  # noqa: N818
    """Raised when no file matches the requested id."""


def upload_file(payload):
    """Store one or more files and return their ids, in input order.

    ``organization_id`` and ``user_id`` are common to the call; ``file_type``
    and ``tags`` are per file. The whole payload is validated before anything
    is written, and the call is all-or-nothing: if any file fails, no metadata
    is kept and every object already written is removed.
    """
    organization_id, user_id, entries = _validated_upload(payload)

    stored = []
    try:
        for entry in entries:
            file_id = uuid.uuid4()
            path = file_storage.build_storage_path(file_id, entry["file"].name)
            stored.append((file_id, file_storage.save(path, entry["file"]), entry))

        with transaction.atomic():
            files = [_create_file(organization_id, user_id, *item) for item in stored]
    except Exception:
        _discard([path for _, path, _ in stored])
        raise

    return {"files": [{"id": file.id} for file in files]}


def get_file(file_id):
    """Return the metadata of a single file.

    Raises ``FileNotFound`` when the file does not exist or has been
    deactivated; it never returns ``None``. ``storage_path`` is deliberately
    excluded from the result.
    """
    return _as_dict(_instance(file_id))


def get_file_content(file_id):
    """Return a readable file-like object for a file's stored content."""
    return file_storage.open_file(_instance(file_id).storage_path)


def get_file_url(file_id):
    """Return a URL for a file's stored content.

    With the S3 backend this is a short-lived pre-signed URL, which lets a
    caller hand the file to a client without proxying the bytes.
    """
    return file_storage.get_url(_instance(file_id).storage_path)


def search_file(filters=None, page=1, page_size=20):
    """Search files by metadata.

    Only active files are returned. Filters are ANDed. When several tags are
    given a file must carry *all* of them. Results use the model's
    ``-created_at`` ordering so pagination is stable.

    The default page size matches ``REST_FRAMEWORK["PAGE_SIZE"]`` so a future
    REST layer can pass its own value through without changing the shape of
    the result.
    """
    filters = filters or {}
    queryset = File.objects.active()

    if filters.get("organization_id") is not None:
        queryset = queryset.filter(organization_id=filters["organization_id"])
    if filters.get("user_id") is not None:
        queryset = queryset.filter(user_id=filters["user_id"])
    if filters.get("file_type"):
        queryset = queryset.filter(file_type=filters["file_type"])
    for name in filters.get("tags") or []:
        queryset = queryset.filter(tags__name=_normalized_tag(name))

    paginator = Paginator(queryset.distinct(), page_size)
    current_page = paginator.get_page(page)
    return {
        "results": [_as_dict(file) for file in current_page],
        "count": paginator.count,
        "page": current_page.number,
        "page_size": page_size,
        "num_pages": paginator.num_pages,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _validated_upload(payload):
    """Validate an upload payload and return ``(organization_id, user_id, files)``."""
    if not isinstance(payload, dict):
        raise ValidationError("payload must be a dict.")

    user_id = payload.get("user_id")
    if user_id is None:
        raise ValidationError({"user_id": "user_id is required."})

    entries = payload.get("files")
    if not entries:
        raise ValidationError({"files": "At least one file is required."})

    max_count = settings.FILE_MAX_COUNT_PER_UPLOAD
    if len(entries) > max_count:
        raise ValidationError({"files": f"At most {max_count} files can be uploaded in one call."})

    for index, entry in enumerate(entries):
        _validate_entry(index, entry)

    return payload.get("organization_id"), user_id, entries


def _validate_entry(index, entry):
    """Validate a single ``files[]`` entry."""
    upload = entry.get("file")
    if upload is None:
        raise ValidationError({f"files[{index}].file": "file is required."})

    if entry.get("file_type") not in FileType.values:
        raise ValidationError(
            {f"files[{index}].file_type": f"file_type must be one of {FileType.values}."}
        )

    max_size = settings.FILE_MAX_SIZE_BYTES
    if _size_of(upload) > max_size:
        raise ValidationError({f"files[{index}].file": f"file exceeds the {max_size} byte limit."})


def _create_file(organization_id, user_id, file_id, storage_path, entry):
    """Create the File row and its tag links for one stored object."""
    upload = entry["file"]
    file = File(
        id=file_id,
        organization_id=organization_id,
        user_id=user_id,
        file_type=entry["file_type"],
        file_name=upload.name,
        content_type=_content_type_of(upload),
        file_size=_size_of(upload),
        storage_path=storage_path,
    )
    file.full_clean()
    file.save()
    file.tags.set(_resolve_tags(entry.get("tags") or []))
    return file


def _resolve_tags(names):
    """Return FileTag rows for ``names``, creating the ones that do not exist."""
    return [FileTag.objects.get_or_create(name=_normalized_tag(name))[0] for name in names]


def _normalized_tag(name):
    """Return the slug FileTag stores for ``name``, validating it on the way."""
    tag = FileTag(name=name)
    tag.clean()
    return tag.name


def _instance(file_id):
    """Return an active File by id, or raise FileNotFound.

    A deactivated file is reported as missing rather than as a distinct state:
    callers of this module have no way to reactivate one, so the difference is
    not actionable for them. The Django admin queries the model directly and
    still sees every row.
    """
    try:
        return File.objects.active().get(pk=file_id)
    except (File.DoesNotExist, ValidationError, ValueError) as exc:
        raise FileNotFound(f"No file with id {file_id!r}.") from exc


def _as_dict(file):
    """Serialize a File for callers, without exposing its storage key."""
    return {
        "id": file.id,
        "organization_id": file.organization_id,
        "user_id": file.user_id,
        "file_type": file.file_type,
        "file_name": file.file_name,
        "content_type": file.content_type,
        "file_size": file.file_size,
        "tags": sorted(file.tags.values_list("name", flat=True)),
        "created_at": file.created_at,
    }


def _discard(storage_paths):
    """Remove objects written by a failed upload.

    Cleanup failures are swallowed so they cannot mask the error that caused
    the rollback; the worst case is an orphaned object, not a lost traceback.
    """
    for path in storage_paths:
        with suppress(Exception):
            file_storage.delete(path)


def _size_of(upload):
    """Return the byte size of an uploaded file.

    ``UploadedFile`` exposes ``size``; a plain file object does not, so fall
    back to seeking and restore the original position.
    """
    size = getattr(upload, "size", None)
    if size is not None:
        return size

    position = upload.tell()
    upload.seek(0, os.SEEK_END)
    size = upload.tell()
    upload.seek(position)
    return size


def _content_type_of(upload):
    """Return the MIME type of an uploaded file.

    ``UploadedFile.content_type`` is supplied by the client and is only a
    hint; plain file objects do not carry one at all.
    """
    return (
        getattr(upload, "content_type", None) or guess_type(upload.name)[0] or FALLBACK_CONTENT_TYPE
    )
