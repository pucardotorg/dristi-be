"""Push notification sender placeholder."""

from apps.messaging.services import RenderedMessage

from .base import BaseMessageSender


class PushSender(BaseMessageSender):
    """Placeholder sender; push delivery is not implemented yet."""

    message_type = "push"

    def send(self, rendered_message: RenderedMessage):
        raise NotImplementedError(
            "Push notification delivery is not implemented yet."
        )
