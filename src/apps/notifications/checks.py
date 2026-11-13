"""Startup validation of the notifications settings (spec 0031 §9).

Run before ``runserver``, ``migrate`` and every management command, so a
misconfigured deployment fails at boot rather than on a subscriber's first
connection.
"""

from urllib.parse import urlsplit

from django.conf import settings
from django.core.checks import Error, register

POSITIVE_INT_SETTINGS = (
    "NOTIFICATIONS_STREAM_MAXLEN",
    "NOTIFICATIONS_STREAM_TTL_SECONDS",
    "NOTIFICATIONS_SSE_HEARTBEAT_SECONDS",
    "NOTIFICATIONS_SSE_RETRY_MS",
    "NOTIFICATIONS_SSE_MAX_DURATION_SECONDS",
    "NOTIFICATIONS_SSE_READ_COUNT",
    "NOTIFICATIONS_TASK_TIME_LIMIT",
    "NOTIFICATIONS_REDIS_SOCKET_CONNECT_TIMEOUT",
    "NOTIFICATIONS_REDIS_SOCKET_TIMEOUT",
)


@register()
def check_notification_settings(app_configs, **kwargs):
    """Validate the Redis URL, stream prefix and the numeric bounds."""
    messages = []

    redis_url = getattr(settings, "NOTIFICATIONS_REDIS_URL", "")
    if not redis_url:
        messages.append(
            Error("NOTIFICATIONS_REDIS_URL must be a non-empty Redis URL.", id="notifications.E001")
        )
    else:
        parsed = urlsplit(redis_url)
        if parsed.scheme not in ("redis", "rediss", "unix"):
            messages.append(
                Error(
                    "NOTIFICATIONS_REDIS_URL must be a redis://, rediss:// or unix:// URL, "
                    f"got {redis_url!r}.",
                    id="notifications.E002",
                )
            )

    if not getattr(settings, "NOTIFICATIONS_STREAM_PREFIX", ""):
        messages.append(
            Error("NOTIFICATIONS_STREAM_PREFIX must be non-empty.", id="notifications.E003")
        )

    for name in POSITIVE_INT_SETTINGS:
        value = getattr(settings, name, None)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            messages.append(
                Error(
                    f"{name} must be an integer of at least 1, got {value!r}.",
                    id=f"notifications.E004.{name}",
                )
            )

    heartbeat = getattr(settings, "NOTIFICATIONS_SSE_HEARTBEAT_SECONDS", None)
    max_duration = getattr(settings, "NOTIFICATIONS_SSE_MAX_DURATION_SECONDS", None)
    if (
        isinstance(heartbeat, int)
        and isinstance(max_duration, int)
        and not isinstance(heartbeat, bool)
        and not isinstance(max_duration, bool)
        and max_duration <= heartbeat
    ):
        messages.append(
            Error(
                "NOTIFICATIONS_SSE_MAX_DURATION_SECONDS must be greater than "
                "NOTIFICATIONS_SSE_HEARTBEAT_SECONDS.",
                id="notifications.E005",
            )
        )

    socket_timeout = getattr(settings, "NOTIFICATIONS_REDIS_SOCKET_TIMEOUT", None)
    if (
        isinstance(heartbeat, int)
        and isinstance(socket_timeout, int)
        and not isinstance(heartbeat, bool)
        and not isinstance(socket_timeout, bool)
        and socket_timeout <= heartbeat
    ):
        messages.append(
            Error(
                "NOTIFICATIONS_REDIS_SOCKET_TIMEOUT must be greater than "
                "NOTIFICATIONS_SSE_HEARTBEAT_SECONDS so a healthy blocking read "
                "returns before the socket times out.",
                id="notifications.E006",
            )
        )

    return messages
