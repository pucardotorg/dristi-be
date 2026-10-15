"""In-memory stand-ins for the PDF and File Storage modules.

``apps.pdf`` and ``apps.files`` are separate modules of this project, so the
eSign tests exercise the domain against fakes that honour the same contracts
(spec 0015 #4) and can be told to fail on demand.
"""

import hashlib
import uuid

from apps.esign.clients.pdf import PreparedDocument
from apps.esign.constants import PDF_CONTENT_TYPE
from apps.esign.exceptions import ESignSourceNotFound

PREPARED_MARKER = b"\n%%esign-placeholder\n"
SIGNED_MARKER = b"\n%%esign-signature:"
FIELD_NAME = "Signature1"


class FakeFileClient:
    """Mirrors :class:`apps.esign.clients.files.FileClient` in memory."""

    def __init__(self):
        self.storage: dict[str, dict] = {}
        self.deleted: list[str] = []
        self.uploads: list[dict] = []
        self.content_reads: list[tuple[str, int | None]] = []
        self.fail_get_content = None
        self.fail_upload = None
        self.fail_delete = None

    # -- test helpers -------------------------------------------------------
    def add(self, content: bytes, *, content_type: str = PDF_CONTENT_TYPE, file_id=None) -> str:
        """Seed a stored file and return its id."""

        file_id = str(file_id or uuid.uuid4())
        self.storage[file_id] = {
            "id": file_id,
            "content": content,
            "content_type": content_type,
            "file_name": f"{file_id}.pdf",
            "file_size": len(content),
            "file_type": "PDF",
            "tags": [],
        }
        return file_id

    def content_of(self, file_id: str) -> bytes:
        """Return the stored bytes for ``file_id``."""

        return self.storage[str(file_id)]["content"]

    # -- FileClient contract ------------------------------------------------
    def get_metadata(self, file_id: str) -> dict:
        """Return the stored metadata for ``file_id``."""

        record = self.storage.get(str(file_id))
        if record is None:
            raise ESignSourceNotFound()
        return {key: value for key, value in record.items() if key != "content"}

    def get_content(self, file_id: str, *, max_bytes: int | None = None) -> bytes:
        """Return the stored bytes for ``file_id``, recording the requested limit."""

        self.content_reads.append((str(file_id), max_bytes))
        if self.fail_get_content is not None:
            raise self.fail_get_content
        record = self.storage.get(str(file_id))
        if record is None:
            raise ESignSourceNotFound()
        return record["content"]

    def upload(
        self,
        content: bytes,
        *,
        filename: str,
        file_type: str,
        user_id: str,
        organization_id=None,
        tags=None,
    ) -> str:
        """Store ``content`` and return a new file id."""

        if self.fail_upload is not None:
            raise self.fail_upload
        file_id = self.add(content)
        record = self.storage[file_id]
        record.update(
            {
                "file_name": filename,
                "file_type": file_type,
                "user_id": str(user_id),
                "organization_id": str(organization_id) if organization_id else None,
                "tags": list(tags or []),
            }
        )
        self.uploads.append(record)
        return file_id

    def delete(self, file_id: str) -> None:
        """Delete ``file_id`` from storage."""

        if self.fail_delete is not None:
            raise self.fail_delete
        if str(file_id) not in self.storage:
            raise ESignSourceNotFound()
        del self.storage[str(file_id)]
        self.deleted.append(str(file_id))


class FakePDFClient:
    """Mirrors :class:`apps.esign.clients.pdf.PDFClient` deterministically."""

    def __init__(self):
        self.prepare_calls: list[dict] = []
        self.embed_calls: list[tuple[bytes, bytes, str]] = []
        self.fail_prepare = None
        self.fail_embed = None

    def prepare_for_signing(self, document: bytes, placeholder: dict) -> PreparedDocument:
        """Append a marker and hash the result, as a container reservation would."""

        if self.fail_prepare is not None:
            raise self.fail_prepare
        self.prepare_calls.append(dict(placeholder))
        prepared = document + PREPARED_MARKER
        return PreparedDocument(
            prepared_document=prepared,
            document_hash=hashlib.sha256(prepared).hexdigest(),
            field_name=FIELD_NAME,
        )

    def embed_signature(self, prepared_document: bytes, pkcs7: bytes, field_name: str) -> bytes:
        """Append the signature to the reserved container."""

        if self.fail_embed is not None:
            raise self.fail_embed
        self.embed_calls.append((prepared_document, pkcs7, field_name))
        return prepared_document + SIGNED_MARKER + pkcs7
