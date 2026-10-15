"""C-DAC eSign wire constants and error-code mapping (spec 0015 #7, #10)."""

from zoneinfo import ZoneInfo

from apps.esign import constants as esign_constants

PROVIDER_NAME = "cdac"
PROVIDER_PATH = "addon.cdac_esign.provider.CDACESignProvider"

# ---------------------------------------------------------------------------
# Request (#7.1)
# ---------------------------------------------------------------------------
ESIGN_ELEMENT = "Esign"
DOCS_ELEMENT = "Docs"
INPUT_HASH_ELEMENT = "InputHash"

RESPONSE_SIG_TYPE = "pkcs7"

# C-DAC expects IST with no timezone suffix.
IST = ZoneInfo("Asia/Kolkata")
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"

# The ESP rejects longer correlation ids.
MAX_TRANSACTION_ID_LENGTH = 64

FORM_FIELD_REQUEST = "eSignRequest"
FORM_FIELD_ASP_TXN = "aspTxnID"
FORM_FIELD_CONTENT_TYPE = "Content-Type"
FORM_CONTENT_TYPE = "application/xml"

# This iteration signs exactly one document per transaction (#16), so a
# response carrying a different number of signatures is rejected.
EXPECTED_SIGNATURE_COUNT = 1
INPUT_HASH_ID = "1"

# ---------------------------------------------------------------------------
# Response (#7.3)
# ---------------------------------------------------------------------------
RESPONSE_ELEMENT = "EsignResp"
USER_CERTIFICATE_ELEMENT = "UserX509Certificate"
SIGNATURES_ELEMENT = "Signatures"
DOC_SIGNATURE_ELEMENT = "DocSignature"
RESPONSE_SUCCESS_STATUS = "1"

# Form field the response document arrives under. C-DAC's field name is part of
# the ASP onboarding pack and is configurable through
# ``CDAC_ESIGN_RESPONSE_FIELD``; these are the names seen in practice, plus the
# one ``apps.esign.parsers`` uses for a raw XML body.
RESPONSE_FIELD_CANDIDATES = (
    "msg",
    "response",
    "eSignResponse",
    "esignResponse",
    "EsignResp",
    "response_xml",
)

# ---------------------------------------------------------------------------
# Error codes (#10)
# ---------------------------------------------------------------------------
# C-DAC publishes its ``errCode`` list with the ASP onboarding pack. Only the
# structural cases can be mapped without it, so every unrecognised code becomes
# ESIGN_PROVIDER_REJECTED while the raw value is kept in ``response_audit`` for
# support. New codes are added here, not in the domain.
ERROR_CODE_MAP = {
    "": esign_constants.ESIGN_PROVIDER_REJECTED,
    "NA": esign_constants.ESIGN_PROVIDER_REJECTED,
}

DEFAULT_ERROR_CODE = esign_constants.ESIGN_PROVIDER_REJECTED


def map_error_code(error_code: str) -> str:
    """Return the internal failure code for a C-DAC ``errCode``."""

    return ERROR_CODE_MAP.get((error_code or "").strip().upper(), DEFAULT_ERROR_CODE)
