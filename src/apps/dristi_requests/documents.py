"""Request documents, stored through ``apps.files`` (spec 0014).

Supporting documents are PDFs or images. Each content type maps onto the
``FileType`` it is stored as, and that mapping is also the allowlist.
"""

import logging

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.files import services as files
from apps.files.models import FileType

logger = logging.getLogger(__name__)

# Tag applied to every stored request document, so they can be found with
# ``files.search_file`` without knowing which requests exist.
DOCUMENT_TAG = "dristi-requests"

# Accepted content types and the FileType each is stored as.
CONTENT_TYPE_FILE_TYPES = {
    "application/pdf": FileType.PDF,
    "image/jpeg": FileType.IMAGE,
    "image/png": FileType.IMAGE,
}


def allowed_content_types():
    """Return the accepted content types, sorted for stable error messages."""
    return sorted(CONTENT_TYPE_FILE_TYPES)


def file_type_for(upload):
    """Return the FileType for an upload, or ``None`` if it is not accepted."""
    return CONTENT_TYPE_FILE_TYPES.get(_content_type(upload))


def validate_documents(documents, *, request_type):
    """Validate a set of uploads before anything is written.

    Raises a DRF ``ValidationError`` keyed on ``documents`` so a bad upload is
    a 400 for the client. ``apps.files`` enforces the same size and count
    limits, but reports them as Django ``ValidationError``, which DRF would
    turn into a 500; checking here first keeps those errors on the field.
    """
    count = len(documents)
    if count < request_type.min_documents:
        raise serializers.ValidationError(
            {
                "documents": (
                    f"{request_type.name} requires at least "
                    f"{request_type.min_documents} document(s), got {count}."
                )
            }
        )

    max_count = settings.FILE_MAX_COUNT_PER_UPLOAD
    if count > max_count:
        raise serializers.ValidationError(
            {"documents": f"At most {max_count} documents can be attached, got {count}."}
        )

    max_size = settings.FILE_MAX_SIZE_BYTES
    errors = []
    for upload in documents:
        name = getattr(upload, "name", "") or "document"
        if file_type_for(upload) is None:
            errors.append(
                f"{name}: unsupported type {_content_type(upload)!r}; "
                f"allowed: {', '.join(allowed_content_types())}."
            )
        elif upload.size > max_size:
            errors.append(f"{name}: exceeds the {max_size} byte limit.")
    if errors:
        raise serializers.ValidationError({"documents": errors})


def store_documents(documents, *, requester, request_type):
    """Upload documents through ``apps.files`` and return their file ids, in order.

    One ``upload_file`` call for the whole set, so the documents of a request
    are stored all-or-nothing. Any error ``apps.files`` still raises is
    reported under ``documents`` rather than escaping as a 500.
    """
    if not documents:
        return []

    tags = [DOCUMENT_TAG, request_type.code]
    payload = {
        "user_id": requester.pk,
        "files": [
            {"file": upload, "file_type": file_type_for(upload), "tags": tags}
            for upload in documents
        ],
    }
    try:
        result = files.upload_file(payload)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({"documents": exc.messages}) from exc
    return [entry["id"] for entry in result["files"]]


def discard_documents(file_ids):
    """Delete stored documents whose request was never created.

    Used only to undo ``store_documents`` when creating the request fails
    afterwards. Cleanup errors are logged and swallowed so they cannot mask
    the error that caused the rollback; the worst case is an orphaned file.
    """
    for file_id in file_ids:
        try:
            files.delete_file(file_id)
        except Exception:  # noqa: BLE001
            logger.exception("Could not discard request document file %s", file_id)


def open_document(document):
    """Return ``(stream, metadata)`` for a document's stored content.

    The caller owns the stream. Raises ``files.FileNotFound`` if the file is
    gone, and Django ``ValidationError`` if it exceeds the read limit.
    """
    metadata = files.get_file(document.file_id)
    return files.get_file_content(document.file_id), metadata


def _content_type(upload):
    """Return an upload's declared content type, without parameters, lower-cased."""
    return (getattr(upload, "content_type", "") or "").split(";")[0].strip().lower()
