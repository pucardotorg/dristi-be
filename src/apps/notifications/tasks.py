"""Asynchronous fan-out of notifications to the event bus (spec 0031 §3)."""

import logging
import time

from django.conf import settings
from dramatiq import actor

from .bus import get_bus
from .models import Notification
from .services import notification_payload

logger = logging.getLogger(__name__)


@actor(max_retries=3, time_limit=settings.NOTIFICATIONS_TASK_TIME_LIMIT)
def publish_notification(notification_id: str) -> None:
    """Publish one committed ``Notification`` to its recipient's stream.

    Idempotent: a retry or duplicate delivery re-publishes the same payload
    under a new stream entry id, which the client de-duplicates by the payload's
    ``id``. A Redis failure propagates so Dramatiq retries; the row stays in the
    database and the client can recover it through REST.
    """
    try:
        notification = Notification.objects.select_related("recipient").get(pk=notification_id)
    except Notification.DoesNotExist:
        # Enqueue happens only after commit, so the row was deleted (or its
        # user removed, cascading) between commit and this run.
        logger.warning("event=NOTIFICATION_MISSING notification_id=%s", notification_id)
        return

    started = time.monotonic()
    get_bus().publish(notification.recipient_id, notification_payload(notification))
    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "event=NOTIFICATION_PUBLISHED notification_id=%s duration_ms=%s",
        notification.id,
        duration_ms,
    )
