"""Internal send API and inbox helpers for notifications (spec 0031 §2).

Other modules notify users only through :func:`notify`; they must never create
``Notification`` rows directly. Read-state changes go through the inbox helpers
here so the service, not the client, owns ``read_at``.
"""

from __future__ import annotations

import json
import logging
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.users.models import User

from .models import Notification

logger = logging.getLogger(__name__)

EVENT_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
EVENT_TYPE_MAX_LENGTH = 64
TITLE_MAX_LENGTH = 256


class NotificationRecipientError(Exception):
    """The supplied recipient is invalid."""


def _resolve_recipient(recipient) -> User:
    """Return the active ``User`` for a ``User`` instance or a user id.

    Raises :class:`NotificationRecipientError` for a missing or inactive
    recipient. This is an internal programming error, not an HTTP failure.
    """
    if isinstance(recipient, User):
        if not recipient.is_active:
            raise NotificationRecipientError(f"Recipient {recipient.pk} is not active.")
        return recipient

    if recipient is None:
        raise NotificationRecipientError("A recipient is required.")

    try:
        return User.objects.get(pk=recipient, is_active=True)
    except (User.DoesNotExist, ValidationError, ValueError, TypeError) as exc:
        raise NotificationRecipientError(f"No active recipient for {recipient!r}.") from exc


def _validate_event_type(event_type) -> str:
    """Validate and return an uppercase snake-case event type."""
    if not isinstance(event_type, str) or not EVENT_TYPE_RE.match(event_type):
        raise ValueError(
            f"event_type must be uppercase snake case matching {EVENT_TYPE_RE.pattern!r}, "
            f"got {event_type!r}."
        )
    if len(event_type) > EVENT_TYPE_MAX_LENGTH:
        raise ValueError(f"event_type must be at most {EVENT_TYPE_MAX_LENGTH} characters.")
    return event_type


def _validate_title(title) -> str:
    """Validate a required, non-blank title."""
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required and must be non-blank.")
    if len(title) > TITLE_MAX_LENGTH:
        raise ValueError(f"title must be at most {TITLE_MAX_LENGTH} characters.")
    return title


def _validate_data(data) -> dict:
    """Validate an opaque JSON-object payload, returning it unchanged."""
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("data must be a JSON object (dict).")
    try:
        json.dumps(data)
    except (TypeError, ValueError) as exc:
        raise ValueError("data must be JSON-serializable.") from exc
    return data


def _validate_priority(priority) -> str:
    """Validate a priority against the model's choices."""
    if priority not in Notification.Priority.values:
        raise ValueError(
            f"priority must be one of {Notification.Priority.values}, got {priority!r}."
        )
    return priority


def _schedule_publish(notification_id) -> None:
    """Enqueue publication after the surrounding transaction commits (§3).

    Publication is best-effort: a broker failure is logged and swallowed so a
    committed business operation never becomes a post-commit 500. The row is
    durable and the client recovers it through the REST inbox.
    """

    def _enqueue():
        from .tasks import publish_notification

        try:
            publish_notification.send(str(notification_id))
        except Exception as exc:  # noqa: BLE001 - best-effort, see docstring
            logger.warning(
                "event=NOTIFICATION_PUBLISH_FAILED notification_id=%s error=%r",
                notification_id,
                exc,
            )

    transaction.on_commit(_enqueue)


def notification_payload(notification: Notification) -> dict:
    """Return the creation-time snapshot published to the Redis stream (§4.2)."""
    return {
        "id": str(notification.id),
        "event_type": notification.event_type,
        "title": notification.title,
        "body": notification.body,
        "data": notification.data,
        "priority": notification.priority,
        "created_at": notification.created_at.isoformat(),
    }


def notify(
    *,
    recipient,
    event_type: str,
    title: str,
    body: str = "",
    data: dict | None = None,
    priority: str = Notification.Priority.NORMAL,
    actor=None,
) -> Notification:
    """Create one notification for ``recipient`` and schedule its live publish.

    ``recipient`` is a ``User`` or a user id. ``event_type`` is a stable,
    uppercase snake-case identifier owned by the calling app (for example
    ``CASE_FILED``). ``data`` is an opaque JSON object the backend does not
    interpret. ``actor`` stamps the audit users.
    """
    user = _resolve_recipient(recipient)
    event_type = _validate_event_type(event_type)
    title = _validate_title(title)
    data = _validate_data(data)
    _validate_priority(priority)

    notification = Notification.objects.create(
        recipient=user,
        event_type=event_type,
        title=title,
        body=body or "",
        data=data,
        priority=priority,
        created_by=actor,
        updated_by=actor,
    )
    logger.info(
        "event=NOTIFICATION_CREATED notification_id=%s event_type=%s",
        notification.id,
        event_type,
    )
    _schedule_publish(notification.id)
    return notification


def mark_read(notification: Notification, *, actor=None) -> Notification:
    """Mark one notification read if unread (idempotent)."""
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.updated_by = actor
        notification.save(update_fields=["read_at", "updated_by", "updated_at"])
    return notification


def mark_all_read(user, *, actor=None) -> int:
    """Mark every unread notification for ``user`` read; return the count updated."""
    now = timezone.now()
    return Notification.objects.filter(recipient=user, read_at__isnull=True).update(
        read_at=now,
        updated_by=actor,
        updated_at=now,
    )


def unread_count(user) -> int:
    """Return the number of unread notifications for ``user``."""
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()
