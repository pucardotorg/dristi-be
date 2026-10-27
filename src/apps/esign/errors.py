"""eSign API error codes (spec 0000 section 9, spec 0015 section 10).

Each ``ESIGN_*`` failure code has one registered API code. The failure codes
stay what transactions record in ``failure_code`` and the audit log; the API
codes are what an endpoint returns in the standard error body. Statuses match
``views.ERROR_STATUS``; codes it does not list are server-side failures (500).
"""

from apps.api import errors as api_errors
from apps.api.errors import BusinessError, define

from . import constants

# Initiation
INVALID_REQUEST = define("E03001", "The signing request could not be processed.")
SOURCE_NOT_FOUND = define("E03002", "The document to sign could not be found.", status=404)
NOT_A_PDF = define("E03003", "Only PDF documents can be signed.")
INVALID_PLACEHOLDER = define("E03004", "The signature placement is not valid for this document.")
NOT_PERMITTED = define("E03005", "You are not permitted to sign this document.", status=403)
PDF_PREPARATION_FAILED = define(
    "E03006", "The document could not be prepared for signing.", status=502
)
FILE_STORAGE_UNAVAILABLE = define(
    "E03007", "Document storage is temporarily unavailable.", status=502
)
PROVIDER_NOT_CONFIGURED = define("E03008", "No eSign provider is configured.", status=503)
REQUEST_BUILD_FAILED = define("E03009", "The signing request could not be prepared.", status=502)
REQUEST_SIGNING_FAILED = define("E03010", "The signing request could not be signed.", status=502)
ALREADY_IN_PROGRESS = define(
    "E03011", "A signing request for this document is already in progress.", status=409
)

# Callback
CALLBACK_MALFORMED = define("E03012", "The signing response could not be read.")
RESPONSE_UNTRUSTED = define("E03013", "The signing response could not be verified.")
RESPONSE_STALE = define("E03014", "The signing response arrived too late to be accepted.")
TRANSACTION_NOT_FOUND = define(
    "E03015", "No signing transaction matches this response.", status=404
)
TRANSACTION_NOT_PROCESSABLE = define(
    "E03016", "This signing transaction can no longer be completed.", status=409
)
PROVIDER_REJECTED = define("E03017", "The signing service rejected the request.", status=500)
SIGNATURE_MISSING = define("E03018", "The signing service returned no signature.", status=500)
SIGNATURE_INVALID = define(
    "E03019", "The signature returned by the signing service is not valid.", status=500
)
PDF_EMBED_FAILED = define(
    "E03020", "The signature could not be embedded in the document.", status=502
)
SIGNED_UPLOAD_FAILED = define("E03021", "The signed document could not be stored.", status=502)
SIGNING_INTERRUPTED = define(
    "E03022", "Signing was interrupted before it completed; please try again.", status=500
)

# Retry
NOT_RETRYABLE = define("E03023", "Only failed or expired signing attempts can be retried.")
MAX_ATTEMPTS_EXCEEDED = define("E03024", "The maximum number of signing attempts has been reached.")
PLACEHOLDER_MISSING = define(
    "E03025", "The prepared document is no longer available; start a new signature."
)

# Module
DISABLED = define("E03026", "Electronic signing is temporarily unavailable.", status=503)

# Storage (added after the initial release; never renumber the codes above)
FILE_STORAGE_REJECTED = define("E03027", "Document storage rejected the request.", status=500)

BY_FAILURE_CODE = {
    constants.ESIGN_INVALID_REQUEST: INVALID_REQUEST,
    constants.ESIGN_SOURCE_NOT_FOUND: SOURCE_NOT_FOUND,
    constants.ESIGN_NOT_A_PDF: NOT_A_PDF,
    constants.ESIGN_INVALID_PLACEHOLDER: INVALID_PLACEHOLDER,
    constants.ESIGN_NOT_PERMITTED: NOT_PERMITTED,
    constants.ESIGN_PDF_PREPARATION_FAILED: PDF_PREPARATION_FAILED,
    constants.ESIGN_FILE_STORAGE_UNAVAILABLE: FILE_STORAGE_UNAVAILABLE,
    constants.ESIGN_FILE_STORAGE_REJECTED: FILE_STORAGE_REJECTED,
    constants.ESIGN_PROVIDER_NOT_CONFIGURED: PROVIDER_NOT_CONFIGURED,
    constants.ESIGN_REQUEST_BUILD_FAILED: REQUEST_BUILD_FAILED,
    constants.ESIGN_REQUEST_SIGNING_FAILED: REQUEST_SIGNING_FAILED,
    constants.ESIGN_ALREADY_IN_PROGRESS: ALREADY_IN_PROGRESS,
    constants.ESIGN_CALLBACK_MALFORMED: CALLBACK_MALFORMED,
    constants.ESIGN_RESPONSE_UNTRUSTED: RESPONSE_UNTRUSTED,
    constants.ESIGN_RESPONSE_STALE: RESPONSE_STALE,
    constants.ESIGN_TRANSACTION_NOT_FOUND: TRANSACTION_NOT_FOUND,
    constants.ESIGN_TRANSACTION_NOT_PROCESSABLE: TRANSACTION_NOT_PROCESSABLE,
    constants.ESIGN_PROVIDER_REJECTED: PROVIDER_REJECTED,
    constants.ESIGN_SIGNATURE_MISSING: SIGNATURE_MISSING,
    constants.ESIGN_SIGNATURE_INVALID: SIGNATURE_INVALID,
    constants.ESIGN_PDF_EMBED_FAILED: PDF_EMBED_FAILED,
    constants.ESIGN_SIGNED_UPLOAD_FAILED: SIGNED_UPLOAD_FAILED,
    constants.ESIGN_SIGNING_INTERRUPTED: SIGNING_INTERRUPTED,
    constants.ESIGN_NOT_RETRYABLE: NOT_RETRYABLE,
    constants.ESIGN_MAX_ATTEMPTS_EXCEEDED: MAX_ATTEMPTS_EXCEEDED,
    constants.ESIGN_PLACEHOLDER_MISSING: PLACEHOLDER_MISSING,
    constants.ESIGN_DISABLED: DISABLED,
}


def api_error(error) -> BusinessError:
    """Return the API error for an ``ESignError``, keeping its user-safe message.

    A failure code with no registered counterpart is reported as a server
    error, the status the views have always used for an unmapped code.
    """
    return BusinessError(BY_FAILURE_CODE.get(error.code, api_errors.SERVER_ERROR), error.message)
