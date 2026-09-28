"""Domain exceptions carrying the failure codes of spec 0015 #10.

Every exception pairs an internal ``code`` with a message that is safe to show
a user: no stack traces, raw ESP payloads, key material or infrastructure
detail ever travels in one.
"""

from . import constants


class ESignError(Exception):
    """Base class for every eSign failure."""

    code = constants.ESIGN_INVALID_REQUEST
    default_message = "The signing request could not be processed."

    def __init__(self, message: str = "", *, code: str = "", audit: dict | None = None):
        self.code = code or self.code
        self.message = message or self.default_message
        self.audit = dict(audit or {})
        # Set when the failure was recorded on a transaction, so the callback
        # view can return the browser to the UI instead of showing it an error.
        self.transaction = None
        super().__init__(self.message)


class ESignDisabled(ESignError):  # noqa: N818
    """Raised when the module is switched off through ``ESIGN_ENABLED``."""

    code = constants.ESIGN_DISABLED
    default_message = "Electronic signing is temporarily unavailable."


class ESignInvalidTransition(ESignError):  # noqa: N818
    """Raised when a caller attempts an illegal state transition (spec 0015 #5.1)."""

    code = constants.ESIGN_TRANSACTION_NOT_PROCESSABLE
    default_message = "The transaction is not in a state that allows this change."


class ESignProviderNotConfigured(ESignError):  # noqa: N818
    """Raised when ``ESIGN_PROVIDER`` is unset or cannot be imported."""

    code = constants.ESIGN_PROVIDER_NOT_CONFIGURED
    default_message = "No eSign provider is configured."


class ESignRequestBuildFailed(ESignError):  # noqa: N818
    """Raised when the provider cannot build its initiation request."""

    code = constants.ESIGN_REQUEST_BUILD_FAILED
    default_message = "The signing request could not be prepared."


class ESignRequestSigningFailed(ESignRequestBuildFailed):
    """Raised when the provider cannot sign its initiation request."""

    code = constants.ESIGN_REQUEST_SIGNING_FAILED
    default_message = "The signing request could not be signed."


class ESignNotPermitted(ESignError):  # noqa: N818
    """Raised when the caller may not sign the referenced entity."""

    code = constants.ESIGN_NOT_PERMITTED
    default_message = "You are not permitted to sign this document."


class ESignSourceNotFound(ESignError):  # noqa: N818
    """Raised when the source ``file_id`` does not resolve."""

    code = constants.ESIGN_SOURCE_NOT_FOUND
    default_message = "The document to sign could not be found."


class ESignNotAPDF(ESignError):  # noqa: N818
    """Raised when the source document is not a PDF."""

    code = constants.ESIGN_NOT_A_PDF
    default_message = "Only PDF documents can be signed."


class ESignInvalidPlaceholder(ESignError):  # noqa: N818
    """Raised when the signature placement is not usable for the document."""

    code = constants.ESIGN_INVALID_PLACEHOLDER
    default_message = "The signature placement is not valid for this document."


class ESignPDFError(ESignError):
    """Raised when the PDF Service cannot prepare or sign the document."""

    code = constants.ESIGN_PDF_PREPARATION_FAILED
    default_message = "The document could not be prepared for signing."


class ESignPDFEmbedError(ESignPDFError):
    """Raised when the PDF Service cannot embed the returned signature."""

    code = constants.ESIGN_PDF_EMBED_FAILED
    default_message = "The signature could not be embedded in the document."


class ESignFileStorageError(ESignError):
    """Raised when the File Storage Service is unavailable or fails."""

    code = constants.ESIGN_FILE_STORAGE_UNAVAILABLE
    default_message = "Document storage is temporarily unavailable."


class ESignSignedUploadError(ESignFileStorageError):
    """Raised when the signed PDF cannot be stored."""

    code = constants.ESIGN_SIGNED_UPLOAD_FAILED
    default_message = "The signed document could not be stored."


class ESignCallbackMalformed(ESignError):  # noqa: N818
    """Raised when an ESP callback payload cannot be parsed."""

    code = constants.ESIGN_CALLBACK_MALFORMED
    default_message = "The signing response could not be read."


class ESignResponseUntrusted(ESignError):  # noqa: N818
    """Raised when an ESP response fails cryptographic verification."""

    code = constants.ESIGN_RESPONSE_UNTRUSTED
    default_message = "The signing response could not be verified."


class ESignResponseStale(ESignError):  # noqa: N818
    """Raised when an ESP response is outside the accepted time window."""

    code = constants.ESIGN_RESPONSE_STALE
    default_message = "The signing response arrived too late to be accepted."


class ESignTransactionNotFound(ESignError):  # noqa: N818
    """Raised when a verified response references no known transaction."""

    code = constants.ESIGN_TRANSACTION_NOT_FOUND
    default_message = "No signing transaction matches this response."


class ESignNotProcessable(ESignError):  # noqa: N818
    """Raised when a callback arrives for a transaction that cannot accept it."""

    code = constants.ESIGN_TRANSACTION_NOT_PROCESSABLE
    default_message = "This signing transaction can no longer be completed."


class ESignProviderRejected(ESignError):  # noqa: N818
    """Raised when the ESP itself reported a failure."""

    code = constants.ESIGN_PROVIDER_REJECTED
    default_message = "The signing service rejected the request."


class ESignSignatureMissing(ESignError):  # noqa: N818
    """Raised when a successful ESP response carries no signature."""

    code = constants.ESIGN_SIGNATURE_MISSING
    default_message = "The signing service returned no signature."


class ESignSignatureInvalid(ESignError):  # noqa: N818
    """Raised when the returned signature is not a usable PKCS#7 structure."""

    code = constants.ESIGN_SIGNATURE_INVALID
    default_message = "The signature returned by the signing service is not valid."


class ESignSigningInterrupted(ESignError):  # noqa: N818
    """Raised when a transaction was left in ``SIGNING`` by a crashed worker."""

    code = constants.ESIGN_SIGNING_INTERRUPTED
    default_message = "Signing was interrupted before it completed; please try again."


class ESignNotRetryable(ESignError):  # noqa: N818
    """Raised when a transaction is not in a retryable state."""

    code = constants.ESIGN_NOT_RETRYABLE
    default_message = "Only failed or expired signing attempts can be retried."


class ESignMaxAttemptsExceeded(ESignError):  # noqa: N818
    """Raised when the per-document attempt budget is exhausted."""

    code = constants.ESIGN_MAX_ATTEMPTS_EXCEEDED
    default_message = "The maximum number of signing attempts has been reached."


class ESignPlaceholderMissing(ESignError):  # noqa: N818
    """Raised when neither the prepared nor the source document is available."""

    code = constants.ESIGN_PLACEHOLDER_MISSING
    default_message = "The prepared document is no longer available; start a new signature."
