"""Base sender interfaces and backend delegation."""

from abc import ABC, abstractmethod
from typing import ClassVar

from django.conf import settings
from django.utils.module_loading import import_string

from apps.messaging.services import MessageBackendNotConfigured, MessageSendError


class BaseMessageSender(ABC):
    """Abstract interface for message delivery backends."""

    message_type: ClassVar[str]

    @abstractmethod
    def send(self, rendered_message) -> None:
        """Deliver a rendered message."""

    def _validate_message_type(self, rendered_message) -> None:
        """Ensure the message matches this sender's channel."""

        if rendered_message.message_type != self.message_type:
            raise MessageSendError(
                f"Expected message_type '{self.message_type}', "
                f"got '{rendered_message.message_type}'"
            )


class ConfiguredBackendSender(BaseMessageSender):
    """Sender facade that delegates to a backend from Django settings."""

    def __init__(self):
        self._configured_backend = None
        self._configured_backend_path = None

    def send(self, rendered_message) -> None:
        """Validate the channel and delegate to the configured backend."""

        self._validate_message_type(rendered_message)
        return self._get_configured_backend().send(rendered_message)

    def _get_configured_backend(self):
        """Lazily load and instantiate the configured backend."""

        backends = getattr(settings, "MESSAGING_BACKENDS", {})
        path = backends.get(self.message_type)
        if not path:
            raise MessageBackendNotConfigured(
                f"No backend configured for message type '{self.message_type}'"
            )

        if (
            self._configured_backend is None
            or self._configured_backend_path != path
        ):
            cls = import_string(path)
            if not issubclass(cls, self.__class__):
                raise TypeError(
                    f"Backend '{path}' must inherit from {self.__class__.__name__}"
                )
            if cls.send is self.__class__.send:
                raise MessageBackendNotConfigured(
                    f"Backend '{path}' must implement send()"
                )
            self._configured_backend = cls()
            self._configured_backend_path = path

        return self._configured_backend
