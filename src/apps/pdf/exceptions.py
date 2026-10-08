"""Exceptions raised by the PDF service.

Generation failures carry a short machine-readable ``code`` and a
``safe_message`` that may be persisted on ``PDFJob.error_message``. Neither may
contain tokens, external payloads, or personal data (spec 0016 #13).

``retryable`` drives the dependency-specific retry policy of #10: dependency
failures are retried with backoff, configuration and request-data failures are
not, and renderer failures are retried once.
"""


class PDFError(Exception):
    """Base class for every PDF service error."""

    code = "PDF_ERROR"
    retryable = False
    default_message = "The document could not be generated."

    def __init__(self, message: str = "", *, code: str = ""):
        super().__init__(message or self.default_message)
        if code:
            self.code = code

    @property
    def safe_message(self) -> str:
        """Return the message that may be stored and shown to callers."""
        return str(self)


class PDFTemplateNotFound(PDFError):  # noqa: N818
    """No active template (or active version) matches the requested key."""

    code = "PDF_TEMPLATE_NOT_FOUND"
    default_message = "No active PDF template matches the requested key."


class PDFConfigurationError(PDFError):
    """The stored format/data configuration is invalid. Never retried."""

    code = "PDF_INVALID_CONFIG"
    default_message = "The PDF template configuration is invalid."


class PDFRequestDataError(PDFError):
    """The request payload does not satisfy the template. Never retried."""

    code = "PDF_INVALID_REQUEST_DATA"
    default_message = "The request data does not satisfy the PDF template."


class PDFDependencyError(PDFError):
    """An external API, localization or image dependency failed transiently."""

    code = "PDF_DEPENDENCY_UNAVAILABLE"
    retryable = True
    default_message = "A dependency required to generate the document is unavailable."


class PDFStorageError(PDFError):
    """The File Storage Service failed transiently."""

    code = "PDF_STORAGE_UNAVAILABLE"
    retryable = True
    default_message = "The generated document could not be stored."


class PDFRenderError(PDFError):
    """The renderer failed on a configuration that passed validation."""

    code = "PDF_RENDER_FAILED"
    default_message = "The document could not be rendered."


class PDFJobStateError(PDFError):
    """A job was asked to make a status transition its lifecycle forbids."""

    code = "PDF_INVALID_TRANSITION"
    default_message = "The job cannot move to the requested status."


# ---------------------------------------------------------------------------
# Signing primitives (#14.3)
# ---------------------------------------------------------------------------


class PDFSigningError(PDFError):
    """Base class for the signing-primitive errors of spec 0016 #14.3.

    Messages never include document content.
    """

    code = "PDF_SIGNING_ERROR"
    default_message = "The PDF could not be processed for signing."


class PDFNotParsable(PDFSigningError):  # noqa: N818
    """The input is not a parsable PDF."""

    code = "PDF_NOT_PARSABLE"
    default_message = "The input is not a parsable PDF document."


class PDFEncrypted(PDFSigningError):  # noqa: N818
    """The input PDF is encrypted or password protected."""

    code = "PDF_ENCRYPTED"
    default_message = "The PDF is encrypted or password protected."


class PDFTooLarge(PDFSigningError):  # noqa: N818
    """The input PDF exceeds ``PDF_MAX_SIGN_INPUT_BYTES``."""

    code = "PDF_TOO_LARGE"
    default_message = "The PDF exceeds the maximum size accepted for signing."


class PDFPageOutOfRange(PDFSigningError):  # noqa: N818
    """The requested placeholder page does not exist."""

    code = "PDF_PAGE_OUT_OF_RANGE"
    default_message = "The requested page does not exist in the PDF."


class PDFInvalidPlaceholder(PDFSigningError):  # noqa: N818
    """The signature placeholder description is invalid."""

    code = "PDF_INVALID_PLACEHOLDER"
    default_message = "The signature placeholder is invalid."


class PDFSignatureFieldMissing(PDFSigningError):  # noqa: N818
    """The prepared PDF has no single empty reserved container for the field."""

    code = "PDF_SIGNATURE_FIELD_MISSING"
    default_message = "The prepared PDF has no empty signature container for the field."


class PDFSignatureContainerTooSmall(PDFSigningError):  # noqa: N818
    """The PKCS#7 blob does not fit in the reserved container."""

    code = "PDF_SIGNATURE_CONTAINER_TOO_SMALL"
    default_message = "The signature does not fit in the reserved container."


class PDFInvalidPKCS7(PDFSigningError):  # noqa: N818
    """The supplied signature is not a DER-encoded CMS/PKCS#7 structure."""

    code = "PDF_INVALID_PKCS7"
    default_message = "The signature is not a valid PKCS#7 structure."
