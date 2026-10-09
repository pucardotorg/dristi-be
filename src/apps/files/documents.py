"""Supporting documents (PDFs and images) that other apps accept from users.

The one place that says which formats are accepted and what an upload must
pass before it is stored. Like ``services``, nothing here depends on DRF.
"""

import logging
import os

from django.conf import settings

from . import services
from .models import FileType

logger = logging.getLogger(__name__)

# Accepted content types: the FileType each is stored as, the file extensions
# it may carry, and the leading bytes its content must start with.
ACCEPTED_FORMATS = {
    "application/pdf": (FileType.PDF, {".pdf"}, (b"%PDF-",)),
    "image/jpeg": (FileType.IMAGE, {".jpg", ".jpeg"}, (b"\xff\xd8\xff",)),
    "image/png": (FileType.IMAGE, {".png"}, (b"\x89PNG\r\n\x1a\n",)),
}

SIGNATURE_LENGTH = max(len(sig) for *_, sigs in ACCEPTED_FORMATS.values() for sig in sigs)


def file_type_for(upload):
    """Return the FileType an upload is stored as, or ``None`` if it is not accepted."""
    accepted = ACCEPTED_FORMATS.get(_content_type(upload))
    return accepted[0] if accepted else None


def document_error(upload):
    """Return why an upload is refused, or ``None`` if it is acceptable.

    The declared type and the file name are client-supplied hints; the
    content's leading bytes decide.
    """
    content_type = _content_type(upload)
    if content_type not in ACCEPTED_FORMATS:
        return f"unsupported type {content_type!r}; upload a PDF, JPEG or PNG file."

    _, extensions, signatures = ACCEPTED_FORMATS[content_type]
    extension = os.path.splitext(getattr(upload, "name", "") or "")[1].lower()
    if extension not in extensions:
        return "the file extension does not match its type."

    max_size = settings.FILE_MAX_SIZE_BYTES
    if upload.size > max_size:
        return f"exceeds the {max_size} byte limit."

    upload.seek(0)
    head = upload.read(SIGNATURE_LENGTH)
    upload.seek(0)
    if not head.startswith(signatures):
        return "the file content does not match its type."

    return None


def store_documents(uploads, *, user_id, tags):
    """Store already-checked uploads against ``user_id`` and return their ids, in order.

    One ``upload_file`` call for the whole set, so it is all-or-nothing.
    Raises Django's ``ValidationError`` if ``apps.files`` refuses the set.
    """
    if not uploads:
        return []

    result = services.upload_file(
        {
            "user_id": user_id,
            "files": [
                {"file": upload, "file_type": file_type_for(upload), "tags": list(tags)}
                for upload in uploads
            ],
        }
    )
    return [entry["id"] for entry in result["files"]]


def discard_documents(file_ids, *, log=logger, message="Could not discard document %s"):
    """Undo ``store_documents`` when the work that follows it fails.

    Cleanup errors are logged on ``log`` and swallowed so they cannot mask the
    error that caused the rollback.
    """
    for file_id in file_ids:
        try:
            services.delete_file(file_id)
        except Exception:  # noqa: BLE001
            log.exception(message, file_id)


def _content_type(upload):
    """Return an upload's declared content type, without parameters, lower-cased."""
    return (getattr(upload, "content_type", "") or "").split(";")[0].strip().lower()
