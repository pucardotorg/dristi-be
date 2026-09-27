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

MAX_FILE_NAME_LENGTH = File._meta.get_field("file_name").max_length
MAX_CONTENT_TYPE_LENGTH = File._meta.get_field("content_type").max_length


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
    for name in _validated_tag_names(filters.get("tags"), "tags"):
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
    _validate_related_id("user", user_id, "user_id")

    organization_id = payload.get("organization_id")
    if organization_id is not None:
        _validate_related_id("organization", organization_id, "organization_id")

    entries = payload.get("files")
    if not entries:
        raise ValidationError({"files": "At least one file is required."})
    if not isinstance(entries, list | tuple):
        raise ValidationError({"files": "files must be a list."})

    max_count = settings.FILE_MAX_COUNT_PER_UPLOAD
    if len(entries) > max_count:
        raise ValidationError({"files": f"At most {max_count} files can be uploaded in one call."})

    for index, entry in enumerate(entries):
        _validate_entry(index, entry)

    return organization_id, user_id, entries


def _validate_related_id(field_name, value, key):
    """Check that ``value`` identifies an existing row for the ``File`` field.

    ``full_clean`` in ``_create_file`` already rejects a dangling reference,
    but only once the content has been written and then discarded, so the
    lookup is repeated here against the field's own related model. It stays in
    ``_create_file`` as well: a row can be deleted between the two calls.

    The error is reported under the key the caller supplied it as --
    ``user_id`` rather than the ``user`` that ``full_clean`` would use -- so a
    caller can map the message back onto the payload it sent.
    """
    model = File._meta.get_field(field_name).related_model
    try:
        exists = model.objects.filter(pk=value).exists()
    except (ValidationError, ValueError, TypeError) as exc:
        raise ValidationError({key: f"No {field_name} with id {value!r}."}) from exc

    if not exists:
        raise ValidationError({key: f"No {field_name} with id {value!r}."})


def _validate_entry(index, entry):
    """Validate a single ``files[]`` entry.

    The field lengths ``File`` declares are checked here, and not left to the
    ``full_clean`` in ``_create_file``, so an over-long name or content type is
    rejected before the content is written to storage rather than after.
    """
    upload = entry.get("file")
    if upload is None:
        raise ValidationError({f"files[{index}].file": "file is required."})

    if entry.get("file_type") not in FileType.values:
        raise ValidationError(
            {f"files[{index}].file_type": f"file_type must be one of {FileType.values}."}
        )

    _validate_file_name(index, upload)

    content_type = _content_type_of(upload)
    if len(content_type) > MAX_CONTENT_TYPE_LENGTH:
        raise ValidationError(
            {
                f"files[{index}].file": (
                    f"content type exceeds the {MAX_CONTENT_TYPE_LENGTH} character limit."
                )
            }
        )

    max_size = settings.FILE_MAX_SIZE_BYTES
    if _size_of(upload) > max_size:
        raise ValidationError({f"files[{index}].file": f"file exceeds the {max_size} byte limit."})

    _validated_tag_names(entry.get("tags"), f"files[{index}].tags")


def _validate_file_name(index, upload):
    """Reject an upload whose name is missing or longer than the column.

    A missing name never reaches ``full_clean`` as a ``ValidationError``, so it
    is caught here instead. An empty or blank name raises
    ``SuspiciousFileOperation`` in ``build_storage_path``; a ``None`` name gets
    past it as the literal key segment ``None``, and then fails as a
    ``TypeError`` out of ``mimetypes.guess_type`` in ``_content_type_of`` --
    after the content has already been written.
    """
    name = getattr(upload, "name", None) or ""
    if not name.strip():
        raise ValidationError({f"files[{index}].file": "file must have a name."})
    if len(name) > MAX_FILE_NAME_LENGTH:
        raise ValidationError(
            {
                f"files[{index}].file": (
                    f"file name exceeds the {MAX_FILE_NAME_LENGTH} character limit."
                )
            }
        )


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


def _validated_tag_names(names, field):
    """Return ``names`` as a list of tag names, rejecting any other shape.

    A bare string is iterable, so without this check ``"invoices"`` would be
    stored as one tag per character rather than rejected. Only lists and
    tuples are accepted: an iterator would be consumed here and arrive empty
    at ``_resolve_tags``.

    Names are run through ``_normalized_tag`` here, rather than only at write
    time, so an unusable name is reported under the caller's field alongside
    the rest of the payload.
    """
    if names is None:
        return []
    if not isinstance(names, list | tuple):
        raise ValidationError({field: "tags must be a list of strings."})

    for name in names:
        if not isinstance(name, str):
            raise ValidationError({field: "tags must be a list of strings."})
        try:
            _normalized_tag(name)
        except ValidationError as exc:
            raise ValidationError({field: exc.messages}) from exc

    return list(names)


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
