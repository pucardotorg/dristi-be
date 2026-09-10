"""Sender backend registry.

Built-in channels (email, sms, push) have default sender facades. Projects can
override them or register custom channels via the MESSAGING_SENDERS setting,
which maps a message type to a dotted path to a BaseMessageSender subclass.
This lets external Django apps provide their own sender implementations without
modifying this module.
"""

from django.conf import settings
from django.utils.module_loading import import_string

from apps.messaging.services import MessageBackendNotConfigured

from .base import BaseMessageSender

_DEFAULT_SENDER_CLASSES = {
    "email": "apps.messaging.senders.email.EmailSender",
    "sms": "apps.messaging.senders.sms.SMSSender",
    "push": "apps.messaging.senders.push.PushSender",
}

_backend_cache = {}


def _get_sender_class(message_type: str):
    """Return the sender class for a message type.

    Looks up ``settings.MESSAGING_SENDERS`` first, then falls back to the
    built-in defaults. Raises MessageBackendNotConfigured when no sender is
    registered for the channel or when the configured class is invalid.
    """
    configured_senders = getattr(settings, "MESSAGING_SENDERS", {})
    path = configured_senders.get(message_type) or _DEFAULT_SENDER_CLASSES.get(
        message_type
    )
    if not path:
        raise MessageBackendNotConfigured(
            f"No sender available for message type '{message_type}'"
        )

    try:
        cls = import_string(path)
    except Exception as exc:
        raise MessageBackendNotConfigured(
            f"Could not import sender '{path}' for message type '{message_type}'"
        ) from exc

    if not isinstance(cls, type) or not issubclass(cls, BaseMessageSender):
        raise MessageBackendNotConfigured(
            f"Sender '{path}' must subclass BaseMessageSender"
        )

    return cls


def get_backend(message_type: str) -> BaseMessageSender:
    """Return a cached sender instance for the given message type."""

    if message_type not in _backend_cache:
        sender_cls = _get_sender_class(message_type)
        _backend_cache[message_type] = sender_cls()
    return _backend_cache[message_type]


def clear_backend_cache() -> None:
    """Clear cached sender instances (useful when overriding settings)."""

    _backend_cache.clear()
