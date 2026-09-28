"""Adapter over ``apps.pdf.services.signing`` (spec 0015 #4.1, spec 0016 #14).

The PDF Service owns signature-container reservation, the ByteRange digest and
PKCS#7 embedding; this module only orchestrates. The adapter therefore does no
PDF parsing of its own: it converts placements, enforces the configured size
limit, and maps the module's exceptions onto this module's failure codes.
"""

from dataclasses import dataclass

from django.conf import settings

from ..constants import PDF_PLACEHOLDER_KEYS
from ..exceptions import ESignInvalidPlaceholder, ESignPDFEmbedError, ESignPDFError

SIGNING_SERVICE_MODULE = "apps.pdf.services.signing"

# 0016 #14.3 error names that mean "the placement cannot be used", as opposed to
# "the document cannot be prepared".
PLACEMENT_ERROR_NAMES = frozenset({"PDFPageOutOfRange", "PDFInvalidPlaceholder"})


@dataclass(frozen=True)
class PreparedDocument:
    """A PDF with an empty signature container plus the hash to be signed."""

    prepared_document: bytes
    document_hash: str
    field_name: str


class PDFClient:
    """In-process client for the PDF Service signing primitives."""

    def prepare_for_signing(self, document: bytes, placeholder: dict) -> PreparedDocument:
        """Reserve an empty signature container and return the ByteRange hash."""

        self._check_size(document)
        signing = self._signing_module()
        try:
            prepared = signing.prepare_for_signing(document, self.to_pdf_placeholder(placeholder))
        except Exception as exc:
            raise self._translate(exc, ESignPDFError) from exc

        return self._as_prepared_document(prepared)

    def embed_signature(self, prepared_document: bytes, pkcs7: bytes, field_name: str) -> bytes:
        """Insert the PKCS#7 blob into the reserved container."""

        signing = self._signing_module()
        try:
            signed = signing.embed_signature(prepared_document, pkcs7, field_name)
        except Exception as exc:
            raise self._translate(exc, ESignPDFEmbedError) from exc

        if not isinstance(signed, bytes | bytearray) or not signed:
            raise ESignPDFEmbedError("The PDF Service returned no signed document.")
        return bytes(signed)

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def to_pdf_placeholder(placeholder: dict) -> dict:
        """Return only the placement keys the PDF Service accepts.

        This module stores the caller's placement verbatim for audit, while
        0016 #14.1 rejects unknown keys — so the translation happens here
        rather than by narrowing what callers may send.
        """

        if not isinstance(placeholder, dict):
            raise ESignInvalidPlaceholder()
        return {key: placeholder[key] for key in PDF_PLACEHOLDER_KEYS if key in placeholder}

    @staticmethod
    def _signing_module():
        """Import the PDF Service signing module, or fail with a safe error."""

        try:
            from importlib import import_module

            return import_module(SIGNING_SERVICE_MODULE)
        except ImportError as exc:
            raise ESignPDFError("The PDF service is not available.") from exc

    @staticmethod
    def _check_size(document: bytes) -> None:
        """Reject documents above ``PDF_MAX_SIGN_INPUT_BYTES``."""

        if not document:
            raise ESignPDFError("The document to sign is empty.")
        limit = getattr(settings, "PDF_MAX_SIGN_INPUT_BYTES", 0)
        if limit and len(document) > int(limit):
            raise ESignPDFError("The document is too large to sign.")

    @staticmethod
    def _as_prepared_document(prepared) -> PreparedDocument:
        """Normalise the PDF Service result into :class:`PreparedDocument`."""

        try:
            document = prepared.prepared_document
            document_hash = prepared.document_hash
            field_name = prepared.field_name
        except AttributeError as exc:
            raise ESignPDFError("The PDF service returned an unexpected result.") from exc

        if not document or not document_hash or not field_name:
            raise ESignPDFError("The PDF service returned an incomplete result.")
        return PreparedDocument(
            prepared_document=bytes(document),
            document_hash=str(document_hash).lower(),
            field_name=str(field_name),
        )

    @staticmethod
    def _translate(exc: Exception, default) -> Exception:
        """Map a PDF Service exception onto this module's failure codes."""

        from ..exceptions import ESignError

        if isinstance(exc, ESignError):
            return exc
        if type(exc).__name__ in PLACEMENT_ERROR_NAMES:
            return ESignInvalidPlaceholder()
        # Messages from the PDF module may name internals, so only this
        # module's own safe default text reaches the caller.
        return default()
