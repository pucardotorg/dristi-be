"""Document persistence through the File Storage Service (spec 0016 #6).

``apps.pdf`` never touches object storage: bytes go to
``apps.files.services.upload_file`` and come back through ``get_file_content``,
and only the returned ``file_id`` is kept. Nothing here imports
``apps.files.storage``.
"""

from __future__ import annotations

import io
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import File as DjangoFile
from django.utils.text import get_valid_filename

from apps.files.models import FileType
from apps.files.services import FileNotFound, delete_file, get_file_content, upload_file

from ..exceptions import PDFConfigurationError, PDFStorageError

logger = logging.getLogger("apps.pdf")

PDF_CONTENT_TYPE = "application/pdf"


class PDFDocumentNotFound(Exception):  # noqa: N818
    """The referenced document no longer exists in the File Storage Service."""


def _pdf_upload(content: bytes, filename: str) -> DjangoFile:
    upload = DjangoFile(io.BytesIO(content), name=filename)
    upload.content_type = PDF_CONTENT_TYPE
    upload.size = len(content)
    return upload


def resolve_system_user_id():
    """Return the user id background uploads are attributed to.

    ``FILE_SYSTEM_USER_ID`` (spec 0014 #10) identifies the system account by
    its email (``system@dristi.internal``), mobile number (``+91...``) or pk,
    so the same value works in every environment.
    """
    from apps.users.models import User

    configured = str(getattr(settings, "FILE_SYSTEM_USER_ID", "") or "").strip()
    if not configured:
        raise PDFConfigurationError(
            "FILE_SYSTEM_USER_ID must be set to attribute generated documents."
        )
    if "@" in configured:
        lookup = {"email__iexact": configured}
    elif configured.startswith("+"):
        lookup = {"mobile_number": configured}
    else:
        lookup = {"pk": configured}
    try:
        user = User.objects.filter(**lookup).values_list("pk", flat=True).first()
    except (ValidationError, ValueError):
        user = None
    if user is None:
        raise PDFConfigurationError("FILE_SYSTEM_USER_ID does not identify an existing user.")
    return user


def tags_for(key: str, entity_id: str = "") -> list[str]:
    """Return the discovery tags for a generated document."""
    tags = ["pdf", key]
    if entity_id:
        tags.append(entity_id)
    return tags


def store_document(
    content: bytes,
    *,
    filename: str,
    user_id,
    organization_id=None,
    tags: list[str] | None = None,
) -> str:
    """Upload one generated PDF and return its ``file_id``.

    Validation failures (oversized file, bad tag) are configuration problems
    and are not retried; anything else from storage is treated as transient.
    """
    payload = {
        "user_id": user_id,
        "organization_id": organization_id,
        "files": [
            {
                "file": _pdf_upload(content, get_valid_filename(filename) or "document.pdf"),
                "file_type": FileType.PDF,
                "tags": tags or [],
            }
        ],
    }
    try:
        result = upload_file(payload)
    except ValidationError as exc:
        raise PDFConfigurationError(f"Generated document was rejected: {exc.messages[0]}") from exc
    except Exception as exc:
        raise PDFStorageError() from exc
    return str(result["files"][0]["id"])


def open_document(file_id: str):
    """Return a readable file-like object for a stored document (caller closes)."""
    try:
        return get_file_content(file_id)
    except FileNotFound as exc:
        raise PDFDocumentNotFound(file_id) from exc


def read_document(file_id: str) -> bytes:
    """Return the full bytes of a stored document."""
    with open_document(file_id) as handle:
        return handle.read()


def delete_documents(file_ids: list[str]) -> list[str]:
    """Delete stored documents; return the ids that could not be deleted.

    Already-missing documents count as deleted. Other failures are logged and
    returned, so the caller can keep the ids it could not remove.
    """
    remaining = []
    for file_id in file_ids:
        try:
            delete_file(file_id)
        except FileNotFound:
            continue
        except Exception:
            logger.warning("event=PDF_DOCUMENT_DELETE_FAILED file_id=%s", file_id, exc_info=True)
            remaining.append(file_id)
    return remaining
