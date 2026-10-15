"""Request documents, stored through ``apps.files`` (spec 0014).

Which formats are accepted, and how an upload is checked, stored and
discarded, is ``apps.files.documents``'s to say. This module adds what is
specific to requests: the per-type document count, the tags a request
document is stored with, and reporting refusals under ``documents``.
"""

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.files import documents as file_documents
from apps.files import services as files

from . import errors

# Tag applied to every stored request document, so they can be found with
# ``files.search_file`` without knowing which requests exist.
DOCUMENT_TAG = "dristi-requests"


def validate_documents(documents, *, request_type):
    """Validate a set of uploads before anything is written.

    Raises a DRF ``ValidationError`` keyed on ``documents`` so a bad upload is
    a 400 for the client. ``apps.files`` enforces the same size and count
    limits, but reports them as Django ``ValidationError``, which DRF would
    turn into a 500; checking here first keeps those errors on the field.
    """
    count = len(documents)
    if count < request_type.min_documents:
        raise errors.INVALID_DOCUMENTS.validation_error(
            {
                "documents": (
                    f"{request_type.name} requires at least "
                    f"{request_type.min_documents} document(s), got {count}."
                )
            }
        )

    max_count = settings.FILE_MAX_COUNT_PER_UPLOAD
    if count > max_count:
        raise errors.INVALID_DOCUMENTS.validation_error(
            {"documents": f"At most {max_count} documents can be attached, got {count}."}
        )

    problems = []
    for upload in documents:
        error = file_documents.document_error(upload)
        if error:
            problems.append(f"{getattr(upload, 'name', '') or 'document'}: {error}")
    if problems:
        raise errors.INVALID_DOCUMENTS.validation_error({"documents": problems})


def store_documents(documents, *, requester, request_type):
    """Upload documents through ``apps.files`` and return their file ids, in order.

    The documents of a request are stored all-or-nothing. Any error
    ``apps.files`` still raises is reported under ``documents`` rather than
    escaping as a 500.
    """
    try:
        return file_documents.store_documents(
            documents, user_id=requester.pk, tags=[DOCUMENT_TAG, request_type.code]
        )
    except DjangoValidationError as exc:
        raise errors.INVALID_DOCUMENTS.validation_error({"documents": exc.messages}) from exc


def discard_documents(file_ids):
    """Delete stored documents whose request was never created.

    Used only to undo ``store_documents`` when creating the request fails
    afterwards. Cleanup errors are logged and swallowed so they cannot mask
    the error that caused the rollback; the worst case is an orphaned file.
    """
    file_documents.discard_documents(file_ids)


def open_document(document):
    """Return ``(stream, metadata)`` for a document's stored content.

    The caller owns the stream. Raises ``files.FileNotFound`` if the file is
    gone, and Django ``ValidationError`` if it exceeds the read limit.
    """
    metadata = files.get_file(document.file_id)
    return files.get_file_content(document.file_id), metadata
