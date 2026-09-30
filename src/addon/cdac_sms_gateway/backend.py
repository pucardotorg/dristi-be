"""CDAC SMS backend: decides whether and what type of SMS to send."""

import re

from apps.messaging.senders.sms import SMSSender
from apps.messaging.services import MessagePermanentError, RenderedMessage

from . import constants, filtering, response
from .client import CDACClient
from .config import resolve_config
from .hashing import generate_password_hash, generate_signature
from .unicode_encoding import is_unicode_content, to_html_entities

# A bare 10-digit Indian mobile number, optionally prefixed with a '91'
# country code (with or without a leading '+'). CDAC only accepts the bare
# 10-digit form; cfg.mobile_prefix re-adds '91' before the request is sent.
_PHONE_NUMBER_RE = re.compile(r"^\+?(91)?([6-9]\d{9})$")


class CDACSMSBackend(SMSSender):
    """Deliver SMS through the CDAC (msdgweb) DLT gateway."""

    provider_name = constants.PROVIDER_NAME

    def send(self, rendered_message: RenderedMessage) -> str | None:
        """Deliver one SMS.

        Returns the CDAC message ID (stored by apps.messaging as
        MessageLog.provider_message_id) or None when the gateway returns none.

        Raises:
            MessagePermanentError  -- do not retry (bad config/request/category)
            MessageSendError       -- transient; apps.messaging schedules a retry
            RecipientFilteredError -- suppressed by policy, not a failure
        """

        # Concrete backends validate directly; calling super().send() would
        # delegate back to this class and recurse.
        self._validate_message_type(rendered_message)
        cfg = resolve_config()

        log_context = {
            "message_id": rendered_message.message_id,
            "correlation_id": rendered_message.correlation_id,
            "attempt": rendered_message.attempt,
            "category": rendered_message.category,
        }

        problems = cfg.validate()
        if problems:
            raise MessagePermanentError(
                "; ".join(message for _, message in problems),
                code=constants.INVALID_CONFIGURATION,
            )

        phone_number = (rendered_message.recipient or {}).get("phone_number")
        if not phone_number:
            raise MessagePermanentError(
                "SMS recipient must include a 'phone_number'",
                code=constants.INVALID_RECIPIENT,
            )

        number = self._normalize_phone_number(phone_number)
        number = filtering.resolve_recipient(number, cfg, log_context)

        content_type = self._resolve_content_type(rendered_message)
        log_context["content_type"] = content_type

        content = rendered_message.body
        if content_type == constants.CONTENT_TYPE_UNICODE:
            content = to_html_entities(content)

        service_type = self._resolve_service_type(rendered_message.category, content_type)
        form = self._build_form(cfg, number, content, service_type, rendered_message)

        status_code, body = CDACClient(cfg).post(form, log_context)
        return response.classify(status_code, body, cfg, log_context)

    def _normalize_phone_number(self, phone_number) -> str:
        """Strip a '+91'/'91' country code and return the bare 10-digit number.

        Without this, a number that already carries a country code or a '+'
        gets cfg.mobile_prefix prepended again in _build_form.
        """

        normalized = re.sub(r"[\s-]", "", str(phone_number).strip())

        match = _PHONE_NUMBER_RE.match(normalized)
        if not match:
            raise MessagePermanentError(
                f"Invalid recipient phone number '{phone_number}'",
                code=constants.INVALID_RECIPIENT,
            )
        return match.group(2)

    def _resolve_content_type(self, rendered_message: RenderedMessage) -> str:
        """Return 'text' or 'unicode', honouring an explicit context override."""

        override = (rendered_message.context or {}).get("sms_content_type")
        if override is None:
            if is_unicode_content(rendered_message.body):
                return constants.CONTENT_TYPE_UNICODE
            return constants.CONTENT_TYPE_TEXT
        if override not in constants.CONTENT_TYPES:
            raise MessagePermanentError(
                f"Unsupported sms_content_type '{override}'",
                code=constants.UNSUPPORTED_CONTENT_TYPE,
            )
        return override

    def _resolve_service_type(self, category: str, content_type: str) -> str:
        """Map category and content type to the CDAC smsservicetype."""

        try:
            return constants.SERVICE_TYPE_BY_CATEGORY[category][content_type]
        except KeyError as exc:
            raise MessagePermanentError(
                f"Unsupported message category '{category}' for the CDAC gateway",
                code=constants.UNSUPPORTED_CATEGORY,
            ) from exc

    def _build_form(self, cfg, number, content, service_type, rendered_message) -> dict:
        """Build the urlencoded form, including the SHA-512 signature.

        The signed components are trimmed here, once, and the trimmed values are
        what the form carries. Signing a trimmed value while sending an
        untrimmed one would make CDAC's recomputed digest diverge from ours
        whenever a credential or a template leaves surrounding whitespace.
        """

        username = cfg.username.strip()
        sender_id = cfg.sender_id.strip()
        content = content.strip()

        form = {
            "username": username,
            "password": generate_password_hash(cfg.password),
            "senderid": sender_id,
            "content": content,
            "smsservicetype": service_type,
            "mobileno": f"{cfg.mobile_prefix}{number}",
            "key": generate_signature(username, sender_id, content, cfg.secure_key.strip()),
        }
        template_id = rendered_message.provider_template_id or cfg.template_id
        if template_id:
            form["templateid"] = template_id
        return form
