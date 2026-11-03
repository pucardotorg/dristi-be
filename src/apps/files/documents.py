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
# it may carry, and the signatures its content may match. A signature is the
# bytes the content starts with, or ``(offset, bytes)`` pairs that must all match.
ACCEPTED_FORMATS = {
    "application/pdf": (FileType.PDF, {".pdf"}, (b"%PDF-",)),
    "image/jpeg": (FileType.IMAGE, {".jpg", ".jpeg"}, (b"\xff\xd8\xff",)),
    "image/png": (FileType.IMAGE, {".png"}, (b"\x89PNG\r\n\x1a\n",)),
}

# HEIF brands a phone camera writes (an ISO box: size, then "ftyp" and the brand).
_HEIF_SIGNATURES = tuple(
    ((4, b"ftyp" + brand),) for brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1")
)

# Photo formats phones save in, for callers that accept them (case documents).
# Kept out of ACCEPTED_FORMATS: nothing renders them yet, so other uploads,
# which may be put into generated PDFs, do not take them.
PHONE_IMAGE_FORMATS = {
    "image/webp": (FileType.IMAGE, {".webp"}, (((0, b"RIFF"), (8, b"WEBP")),)),
    "image/heic": (FileType.IMAGE, {".heic", ".heif"}, _HEIF_SIGNATURES),
    "image/heif": (FileType.IMAGE, {".heic", ".heif"}, _HEIF_SIGNATURES),
}

CASE_DOCUMENT_FORMATS = {**ACCEPTED_FORMATS, **PHONE_IMAGE_FORMATS}

# What the formats are called in an error message.
_FORMAT_NAMES = {
    "application/pdf": "PDF",
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WebP",
    "image/heic": "HEIC",
    "image/heif": "HEIC",
}


def _parts(signature):
    """Return ``signature`` as ``(offset, bytes)`` pairs."""
    return ((0, signature),) if isinstance(signature, bytes) else signature


SIGNATURE_LENGTH = max(
    offset + len(part)
    for *_, signatures in CASE_DOCUMENT_FORMATS.values()
    for signature in signatures
    for offset, part in _parts(signature)
)


def _matches(head, signatures):
    """Return whether ``head`` matches any of ``signatures``."""
    return any(
        all(head[offset : offset + len(part)] == part for offset, part in _parts(signature))
        for signature in signatures
    )


def _names(formats):
    """Return "PDF, JPEG or PNG" for ``formats``."""
    names = list(dict.fromkeys(_FORMAT_NAMES[content_type] for content_type in formats))
    return f"{', '.join(names[:-1])} or {names[-1]}" if len(names) > 1 else names[0]


def file_type_for(upload):
    """Return the FileType an upload is stored as, or ``None`` if it is not accepted."""
    accepted = CASE_DOCUMENT_FORMATS.get(_content_type(upload))
    return accepted[0] if accepted else None


def document_error(upload, formats=ACCEPTED_FORMATS):
    """Return why an upload is refused, or ``None`` if it is acceptable.

    The declared type and the file name are client-supplied hints; the
    content's leading bytes decide. ``formats`` are the formats the caller
    accepts: ``ACCEPTED_FORMATS``, or ``CASE_DOCUMENT_FORMATS``.
    """
    content_type = _content_type(upload)
    if content_type not in formats:
        return f"unsupported type {content_type!r}; upload a {_names(formats)} file."

    _, extensions, signatures = formats[content_type]
    extension = os.path.splitext(getattr(upload, "name", "") or "")[1].lower()
    if extension not in extensions:
        return "the file extension does not match its type."

    max_size = settings.FILE_MAX_SIZE_BYTES
    if upload.size > max_size:
        return f"exceeds the {max_size} byte limit."

    upload.seek(0)
    head = upload.read(SIGNATURE_LENGTH)
    upload.seek(0)
    if not _matches(head, signatures):
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


def discard_documents(file_ids):
    """Undo ``store_documents`` when the work that follows it fails.

    Cleanup errors are logged and swallowed so they cannot mask the error
    that caused the rollback.
    """
    for file_id in file_ids:
        try:
            services.delete_file(file_id)
        except Exception:  # noqa: BLE001
            logger.exception("Could not discard document %s", file_id)


def _content_type(upload):
    """Return an upload's declared content type, without parameters, lower-cased."""
    return (getattr(upload, "content_type", "") or "").split(";")[0].strip().lower()
