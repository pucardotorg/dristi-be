"""Sender backend registry."""

from apps.messaging.services import MessageBackendNotConfigured

from .base import BaseMessageSender
from .email import EmailSender
from .push import PushSender
from .sms import SMSSender

_FACADE_CLASSES = {
    "email": EmailSender,
    "sms": SMSSender,
    "push": PushSender,
}

_backend_cache = {}


def get_backend(message_type: str) -> BaseMessageSender:
    """Return a cached sender facade for the given message type."""

    if message_type not in _backend_cache:
        facade_cls = _FACADE_CLASSES.get(message_type)
        if facade_cls is None:
            raise MessageBackendNotConfigured(
                f"No sender available for message type '{message_type}'"
            )
        _backend_cache[message_type] = facade_cls()
    return _backend_cache[message_type]


def clear_backend_cache() -> None:
    """Clear cached sender facades (useful when overriding settings)."""

    _backend_cache.clear()
