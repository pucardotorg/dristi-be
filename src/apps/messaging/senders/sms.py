"""SMS senders and a dummy console backend."""

import uuid

from apps.messaging.services import MessageSendError, RenderedMessage

from .base import ConfiguredBackendSender


class SMSSender(ConfiguredBackendSender):
    """Sender facade for the SMS channel."""

    message_type = "sms"


class DummySMSBackend(SMSSender):
    """Testing SMS backend that prints SMS payloads to stdout."""

    def send(self, rendered_message: RenderedMessage):
        # Concrete backends validate directly; calling super().send() would
        # delegate back to this class and recurse.
        self._validate_message_type(rendered_message)

        phone_number = rendered_message.recipient.get("phone_number")
        if not phone_number:
            raise MessageSendError("SMS recipient must include a 'phone_number'")

        provider_message_id = str(uuid.uuid4())
        payload = {
            "phone_number": phone_number,
            "message": rendered_message.body,
            "message_key": rendered_message.message_key,
            "category": rendered_message.category,
            "provider_message_id": provider_message_id,
        }
        print(f"DummySMSBackend: {payload}")
        return provider_message_id
