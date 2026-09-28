"""Statuses, failure codes, log events and integration constants (spec 0015 #5, #10, #13)."""

from django.db import models


class ESignStatus(models.TextChoices):
    """The five states of a signing transaction (spec 0015 #5.1)."""

    PENDING = "PENDING", "Pending"
    SIGNING = "SIGNING", "Signing"
    SUCCESS = "SUCCESS", "Success"
    FAILURE = "FAILURE", "Failure"
    EXPIRED = "EXPIRED", "Expired"


# SUCCESS is terminal; FAILURE and EXPIRED never transition either — a retry
# creates a new row instead (spec 0015 #5.1).
TERMINAL_STATUSES = frozenset(
    {
        ESignStatus.SUCCESS.value,
        ESignStatus.FAILURE.value,
        ESignStatus.EXPIRED.value,
    }
)
RETRYABLE_STATUSES = frozenset(
    {
        ESignStatus.FAILURE.value,
        ESignStatus.EXPIRED.value,
    }
)


class EntityType(models.TextChoices):
    """The bounded set of document kinds that can be signed (spec 0015 #5).

    ``OTHER`` exists so an early consumer is never blocked, not as a permanent
    home; new kinds are added here with a migration.
    """

    ORDER = "ORDER", "Order"
    JUDGEMENT = "JUDGEMENT", "Judgement"
    SUMMONS = "SUMMONS", "Summons"
    NOTICE = "NOTICE", "Notice"
    WARRANT = "WARRANT", "Warrant"
    VAKALATNAMA = "VAKALATNAMA", "Vakalatnama"
    APPLICATION = "APPLICATION", "Application"
    CASE_FILING = "CASE_FILING", "Case filing"
    OTHER = "OTHER", "Other"


# ---------------------------------------------------------------------------
# Failure codes (spec 0015 #10)
# ---------------------------------------------------------------------------
# Initiation
ESIGN_INVALID_REQUEST = "ESIGN_INVALID_REQUEST"
ESIGN_SOURCE_NOT_FOUND = "ESIGN_SOURCE_NOT_FOUND"
ESIGN_NOT_A_PDF = "ESIGN_NOT_A_PDF"
ESIGN_INVALID_PLACEHOLDER = "ESIGN_INVALID_PLACEHOLDER"
ESIGN_NOT_PERMITTED = "ESIGN_NOT_PERMITTED"
ESIGN_PDF_PREPARATION_FAILED = "ESIGN_PDF_PREPARATION_FAILED"
ESIGN_FILE_STORAGE_UNAVAILABLE = "ESIGN_FILE_STORAGE_UNAVAILABLE"
ESIGN_PROVIDER_NOT_CONFIGURED = "ESIGN_PROVIDER_NOT_CONFIGURED"
ESIGN_REQUEST_BUILD_FAILED = "ESIGN_REQUEST_BUILD_FAILED"
ESIGN_REQUEST_SIGNING_FAILED = "ESIGN_REQUEST_SIGNING_FAILED"

# Callback
ESIGN_CALLBACK_MALFORMED = "ESIGN_CALLBACK_MALFORMED"
ESIGN_RESPONSE_UNTRUSTED = "ESIGN_RESPONSE_UNTRUSTED"
ESIGN_RESPONSE_STALE = "ESIGN_RESPONSE_STALE"
ESIGN_TRANSACTION_NOT_FOUND = "ESIGN_TRANSACTION_NOT_FOUND"
ESIGN_TRANSACTION_NOT_PROCESSABLE = "ESIGN_TRANSACTION_NOT_PROCESSABLE"
ESIGN_PROVIDER_REJECTED = "ESIGN_PROVIDER_REJECTED"
ESIGN_SIGNATURE_MISSING = "ESIGN_SIGNATURE_MISSING"
ESIGN_SIGNATURE_INVALID = "ESIGN_SIGNATURE_INVALID"
ESIGN_PDF_EMBED_FAILED = "ESIGN_PDF_EMBED_FAILED"
ESIGN_SIGNED_UPLOAD_FAILED = "ESIGN_SIGNED_UPLOAD_FAILED"
ESIGN_SIGNING_INTERRUPTED = "ESIGN_SIGNING_INTERRUPTED"

# Retry
ESIGN_NOT_RETRYABLE = "ESIGN_NOT_RETRYABLE"
ESIGN_MAX_ATTEMPTS_EXCEEDED = "ESIGN_MAX_ATTEMPTS_EXCEEDED"
ESIGN_PLACEHOLDER_MISSING = "ESIGN_PLACEHOLDER_MISSING"

# Kill switch
ESIGN_DISABLED = "ESIGN_DISABLED"


# ---------------------------------------------------------------------------
# Log events (spec 0015 #13)
# ---------------------------------------------------------------------------
EVENT_ESIGN_INITIATED = "ESIGN_INITIATED"
EVENT_PDF_PREPARED = "PDF_PREPARED"
EVENT_PLACEHOLDER_STORED = "PLACEHOLDER_STORED"
EVENT_PROVIDER_REQUEST_BUILT = "PROVIDER_REQUEST_BUILT"
EVENT_CALLBACK_RECEIVED = "CALLBACK_RECEIVED"
EVENT_CALLBACK_VERIFIED = "CALLBACK_VERIFIED"
EVENT_CALLBACK_REJECTED = "CALLBACK_REJECTED"
EVENT_SIGNATURE_EMBEDDED = "SIGNATURE_EMBEDDED"
EVENT_SIGNED_STORED = "SIGNED_STORED"
EVENT_ESIGN_SUCCEEDED = "ESIGN_SUCCEEDED"
EVENT_ESIGN_FAILED = "ESIGN_FAILED"
EVENT_ESIGN_EXPIRED = "ESIGN_EXPIRED"
EVENT_ESIGN_RETRIED = "ESIGN_RETRIED"


# ---------------------------------------------------------------------------
# File Storage / PDF Service integration (spec 0014 #1.2, spec 0016 #14)
# ---------------------------------------------------------------------------
PDF_CONTENT_TYPE = "application/pdf"

# ``apps.files`` owns the FileType enum; these are the two values spec 0014
# #1.2 records for this module's artefacts. They are passed as plain strings so
# the domain does not import the storage module's schema.
FILE_TYPE_PDF = "PDF"
FILE_TYPE_SIGNED_PDF = "DIGITALLY_SIGNED"

# Tags make the artefacts discoverable through ``search_file()``.
FILE_TAG_ESIGN = "esign"

PLACEHOLDER_FILENAME_SUFFIX = "-prepared.pdf"
SIGNED_FILENAME_SUFFIX = "-signed.pdf"

# Placement keys ``apps.pdf.services.signing`` accepts (spec 0016 #14.1). The
# adapter drops anything else, because 0016 rejects unknown keys while this
# module stores the caller's placement verbatim for audit.
PDF_PLACEHOLDER_KEYS = (
    "page",
    "x",
    "y",
    "width",
    "height",
    "reason",
    "location",
    "signer_name",
)
