"""CDAC-specific constants: service types, error codes, and log events."""

PROVIDER_NAME = "cdac"
BACKEND_PATH = "addon.cdac_sms_gateway.backend.CDACSMSBackend"

# Content types the gateway distinguishes.
CONTENT_TYPE_TEXT = "text"
CONTENT_TYPE_UNICODE = "unicode"
CONTENT_TYPES = (CONTENT_TYPE_TEXT, CONTENT_TYPE_UNICODE)

# CDAC smsservicetype values.
SERVICE_TYPE_OTP = "otpmsg"
SERVICE_TYPE_SINGLE = "singlemsg"
SERVICE_TYPE_UNICODE = "unicodemsg"

# MessageTemplate.Category -> service type. OTP uses otpmsg for both content
# types; the remaining supported categories split on content type.
SERVICE_TYPE_BY_CATEGORY = {
    "OTP": {
        CONTENT_TYPE_TEXT: SERVICE_TYPE_OTP,
        CONTENT_TYPE_UNICODE: SERVICE_TYPE_OTP,
    },
    "NOTIFICATION": {
        CONTENT_TYPE_TEXT: SERVICE_TYPE_SINGLE,
        CONTENT_TYPE_UNICODE: SERVICE_TYPE_UNICODE,
    },
    "TRANSACTION": {
        CONTENT_TYPE_TEXT: SERVICE_TYPE_SINGLE,
        CONTENT_TYPE_UNICODE: SERVICE_TYPE_UNICODE,
    },
}

# Permanent failure codes: retrying cannot fix these.
INVALID_REQUEST = "INVALID_REQUEST"
INVALID_RECIPIENT = "INVALID_RECIPIENT"
INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
UNSUPPORTED_CATEGORY = "UNSUPPORTED_CATEGORY"
UNSUPPORTED_CONTENT_TYPE = "UNSUPPORTED_CONTENT_TYPE"

# Transient failure codes: the messaging module may retry these.
GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"
GATEWAY_CONNECTION_ERROR = "GATEWAY_CONNECTION_ERROR"
GATEWAY_UNAVAILABLE = "GATEWAY_UNAVAILABLE"
GATEWAY_ERROR = "GATEWAY_ERROR"
RESPONSE_VALIDATION_FAILED = "RESPONSE_VALIDATION_FAILED"

# Recipient filtering reasons.
REASON_DISABLED = "disabled"
REASON_WHITELIST = "whitelist"
REASON_BLACKLIST = "blacklist"

# Log events owned by the addon.
EVENT_FILTERED = "FILTERED"
EVENT_GATEWAY_REQUEST = "GATEWAY_REQUEST"
EVENT_GATEWAY_RESPONSE = "GATEWAY_RESPONSE"

LOGGER_NAME = "addon.cdac_sms_gateway"
