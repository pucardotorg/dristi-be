"""SMS senders and the dummy HTTP backend."""

import uuid

import requests
from django.conf import settings

from apps.messaging.services import (
    MessageBackendNotConfigured,
    MessageSendError,
    RenderedMessage,
)

from .base import ConfiguredBackendSender


class SMSSender(ConfiguredBackendSender):
    """Sender facade for the SMS channel."""

    message_type = "sms"


class DummySMSBackend(SMSSender):
    """Development SMS backend that POSTs to an HTTP endpoint."""

    def send(self, rendered_message: RenderedMessage):
        # Concrete backends validate directly; calling super().send() would
        # delegate back to this class and recurse.
        self._validate_message_type(rendered_message)
        endpoint = getattr(settings, "MESSAGING_DUMMY_SMS_ENDPOINT", None)
        if not endpoint:
            raise MessageBackendNotConfigured(
                "MESSAGING_DUMMY_SMS_ENDPOINT is required for DummySMSBackend"
            )
        phone_number = rendered_message.recipient.get("phone_number")
        if not phone_number:
            raise MessageSendError(
                "SMS recipient must include a 'phone_number'"
            )

        provider_message_id = str(uuid.uuid4())
        payload = {
            "phone_number": phone_number,
            "message": rendered_message.body,
            "message_key": rendered_message.message_key,
            "provider_message_id": provider_message_id,
        }
        try:
            response = requests.post(
                endpoint,
                json=payload,
                timeout=getattr(settings, "MESSAGING_DUMMY_SMS_TIMEOUT", 30),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise MessageSendError(f"SMS delivery failed: {exc}") from exc
        return provider_message_id
