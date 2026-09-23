"""Gateway response validation, classification, and message-ID parsing."""

import logging
import re

from apps.messaging.services import MessageSendError

from . import constants

logger = logging.getLogger(constants.LOGGER_NAME)

# Bodies look like "402,MsgID = 1234567890msdgsms".
_MESSAGE_ID_RE = re.compile(r"MsgID\s*=\s*(\S+?)msdgsms", re.IGNORECASE)
_SECRET_RE = re.compile(r"((?:password|key)=)[^&\s]+", re.IGNORECASE)


def redact(body: str) -> str:
    """Remove password and key values from a body that echoes the request."""

    return _SECRET_RE.sub(r"\1***", body or "")


def parse_message_id(body: str) -> str | None:
    """Return the CDAC message ID from the body, or None when absent."""

    match = _MESSAGE_ID_RE.search(body or "")
    return match.group(1) if match else None


def classify(status_code: int, body: str, cfg, log_context: dict | None = None) -> str | None:
    """Validate a gateway response and return the provider message ID.

    Every validation failure is transient: a non-success status is usually a
    load or upstream condition that a retry can clear.
    """

    context = log_context or {}

    _log_response(status_code, redact(body) if cfg.print_response else None, context)

    if cfg.verify_response and cfg.verify_response_contains not in (body or ""):
        raise MessageSendError(
            f"Gateway response did not contain '{cfg.verify_response_contains}'",
            code=constants.RESPONSE_VALIDATION_FAILED,
            gateway_status=str(status_code),
        )

    if cfg.success_codes and status_code not in cfg.success_codes:
        raise MessageSendError(
            f"Gateway returned status {status_code}",
            code=constants.GATEWAY_ERROR,
            gateway_status=str(status_code),
        )

    if cfg.error_codes and status_code in cfg.error_codes:
        raise MessageSendError(
            f"Gateway returned error status {status_code}",
            code=constants.GATEWAY_ERROR,
            gateway_status=str(status_code),
        )

    return parse_message_id(body)


def _log_response(status_code: int, body: str | None, context: dict) -> None:
    """Emit the GATEWAY_RESPONSE event; body is omitted when print_response is off.

    Status code and other metadata are always logged, even with print_response
    disabled, so delivery outcomes stay observable without the response body.
    """

    logger.info(
        "event=%s message_id=%s correlation_id=%s gateway=%s category=%s "
        "content_type=%s attempt=%s gateway_status=%s body=%s",
        constants.EVENT_GATEWAY_RESPONSE,
        context.get("message_id", ""),
        context.get("correlation_id", ""),
        constants.PROVIDER_NAME,
        context.get("category", ""),
        context.get("content_type", ""),
        context.get("attempt", ""),
        status_code,
        body if body is not None else "<suppressed>",
    )
