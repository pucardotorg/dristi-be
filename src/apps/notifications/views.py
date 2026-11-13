"""Notification inbox viewset and the SSE subscribe view (spec 0031 §5, §6)."""

from __future__ import annotations

import json
import logging
import time

from django.conf import settings
from django.db import connection
from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.renderers import MetaJSONRenderer
from apps.api.viewsets.base import APIModelReadOnlyViewSet

from . import services
from .bus import ZERO_ID, compare_ids, get_bus
from .models import Notification
from .serializers import (
    STREAM_ID_REGEX,
    MarkAllReadSerializer,
    NotificationFilterSerializer,
    NotificationSerializer,
    NotificationSubscribeQuerySerializer,
    UnreadCountSerializer,
)

logger = logging.getLogger(__name__)

UUID_PATTERN = "[0-9a-fA-F-]{36}"


class NotificationViewSet(APIModelReadOnlyViewSet):
    """The caller's own notification inbox: list, retrieve and read actions.

    The queryset is always scoped to ``request.user``; another user's id is a
    ``404 E00105``, never a ``403``, so existence is not leaked. There is no
    create/update/delete or send endpoint — notifications are created only
    through :func:`apps.notifications.services.notify`.
    """

    serializer_class = NotificationSerializer
    lookup_field = "id"
    lookup_value_regex = UUID_PATTERN

    def get_queryset(self):
        """Return only the requesting user's notifications."""
        return Notification.objects.filter(recipient=self.request.user)

    def filter_queryset(self, queryset):
        """Apply the validated list filters (§6.1)."""
        if self.action != "list":
            return queryset
        serializer = NotificationFilterSerializer(data=self.request.query_params)
        serializer.is_valid(raise_exception=True)
        filters = serializer.validated_data
        if "is_read" in filters:
            queryset = queryset.filter(read_at__isnull=not filters["is_read"])
        if "event_type" in filters:
            queryset = queryset.filter(event_type=filters["event_type"])
        if "priority" in filters:
            queryset = queryset.filter(priority=filters["priority"])
        return queryset

    @extend_schema(parameters=[NotificationFilterSerializer])
    def list(self, request, *args, **kwargs):
        """Paginated list of the caller's notifications, newest first."""
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses=NotificationSerializer)
    @action(detail=True, methods=["post"])
    def read(self, request, id=None):
        """Mark one notification read (idempotent)."""
        notification = self.get_object()
        services.mark_read(notification, actor=request.user)
        return Response(NotificationSerializer(notification).data)

    @extend_schema(request=None, responses=MarkAllReadSerializer)
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        """Mark every unread notification read; return how many were updated."""
        updated = services.mark_all_read(request.user, actor=request.user)
        return Response(MarkAllReadSerializer({"updated": updated}).data)

    @extend_schema(responses=UnreadCountSerializer)
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        """Return the caller's unread notification count."""
        count = services.unread_count(request.user)
        return Response(UnreadCountSerializer({"count": count}).data)


# ---------------------------------------------------------------------------
# SSE subscribe
# ---------------------------------------------------------------------------


class EventStreamRenderer(MetaJSONRenderer):
    """Negotiation target for ``text/event-stream``.

    The success path returns a ``StreamingHttpResponse`` directly and never
    touches this renderer. It is reached only when DRF renders a pre-stream
    exception (authentication or permission failure), where it falls back to the
    standard ``meta`` JSON error body so those responses stay machine-readable.
    Without it, ``Accept: text/event-stream`` from a browser ``EventSource``
    would be refused with ``406 E00107`` before the handler ran.
    """

    media_type = "text/event-stream"
    format = "sse"


def sse_frame(*, event=None, data=None, event_id=None, comment=None) -> str:
    """Build one SSE frame. ``data`` is JSON-encoded on one line."""
    lines = []
    if comment is not None:
        lines.append(f": {comment}")
    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event is not None:
        lines.append(f"event: {event}")
    if data is not None:
        lines.append("data: " + json.dumps(data, separators=(",", ":")))
    return "\n".join(lines) + "\n\n"


def resolve_cursor(bus, user_id, raw_cursor):
    """Return ``(cursor, needs_resync)`` for the stream's starting position (§5.3).

    With no client cursor, start from the newest entry at connect time. With a
    cursor, resume only if the stream exists and the cursor is still inside the
    retained tail; otherwise plan a ``resync`` and fall back to the newest id so
    a trimmed or recreated tail is never resumed silently.
    """
    if not raw_cursor:
        return bus.last_id(user_id), False
    first = bus.first_id(user_id)
    if first is None or compare_ids(raw_cursor, first) < 0:
        return bus.last_id(user_id), True
    return raw_cursor, False


def event_stream(user_id, raw_cursor, bus):
    """Yield SSE frames for ``user_id`` until the maximum duration elapses.

    All transient conditions are handled inside this 200 response: a Redis
    outage degrades to keep-alives and emits ``resync`` on recovery, never an
    error status (a native ``EventSource`` closes permanently on any non-200).
    """
    heartbeat_s = settings.NOTIFICATIONS_SSE_HEARTBEAT_SECONDS
    block_ms = heartbeat_s * 1000
    deadline = time.monotonic() + settings.NOTIFICATIONS_SSE_MAX_DURATION_SECONDS
    started = time.monotonic()

    yield f"retry: {settings.NOTIFICATIONS_SSE_RETRY_MS}\n\n"
    yield sse_frame(
        event="connected",
        data={"user_id": str(user_id), "server_time": timezone.now().isoformat()},
    )

    degraded = False
    try:
        cursor, needs_resync = resolve_cursor(bus, user_id, raw_cursor)
    except Exception as exc:  # noqa: BLE001 - Redis down at connect degrades, not errors
        logger.warning("event=SSE_DEGRADED user_id=%s error=%r", user_id, exc)
        cursor, needs_resync, degraded = ZERO_ID, False, True

    if needs_resync:
        logger.info("event=SSE_RESYNC user_id=%s reason=tail_lost", user_id)
        yield sse_frame(event="resync", data={"reason": "tail_lost"})

    try:
        while time.monotonic() < deadline:
            try:
                entries = bus.read(user_id, cursor, block_ms)
            except Exception as exc:  # noqa: BLE001 - degrade, keep the stream open
                if not degraded:
                    degraded = True
                    logger.warning("event=SSE_DEGRADED user_id=%s error=%r", user_id, exc)
                yield sse_frame(comment="keep-alive")
                time.sleep(heartbeat_s)
                continue

            if degraded:
                degraded = False
                cursor = bus.last_id(user_id)
                logger.info("event=SSE_RESYNC user_id=%s reason=bus_recovered", user_id)
                yield sse_frame(event="resync", data={"reason": "bus_recovered"})
                continue

            if not entries:
                yield sse_frame(comment="keep-alive")
                continue

            for entry_id, payload in entries:
                cursor = entry_id
                yield sse_frame(event_id=entry_id, event="notification", data=payload)
    except (GeneratorExit, BrokenPipeError):
        # Client disconnected: stop quietly, no frame after the stream started.
        pass
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info("event=SSE_DISCONNECTED user_id=%s duration_ms=%s", user_id, duration_ms)


def _requested_cursor(request):
    """Return a valid ``Last-Event-ID`` from the header or query, else ``None``.

    A valid header wins; a malformed one falls through to the query parameter.
    Any invalid value is ignored so a reconnect never fails with a 500.
    """
    import re

    header = request.META.get("HTTP_LAST_EVENT_ID")
    if header and re.match(STREAM_ID_REGEX, header):
        return header
    serializer = NotificationSubscribeQuerySerializer(data=request.query_params)
    if serializer.is_valid():
        return serializer.validated_data.get("last_event_id")
    return None


class NotificationSubscribeView(APIView):
    """Open the current user's live SSE stream (§5).

    The user id comes only from ``request.user``; there is no way to subscribe
    to another user's stream. After authentication the endpoint never returns a
    non-200 — transient Redis failures degrade the open stream instead.
    """

    renderer_classes = [EventStreamRenderer, MetaJSONRenderer]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="Last-Event-ID",
                location=OpenApiParameter.HEADER,
                required=False,
                description="Opaque stream id to resume from after a reconnect.",
            ),
            OpenApiParameter(
                name="last_event_id",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Resume cursor for non-browser clients (header is preferred).",
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.STR,
                description="Server-Sent Events stream (text/event-stream).",
            )
        },
    )
    def get(self, request):
        """Return the authenticated user's SSE stream."""
        user_id = request.user.id
        cursor = _requested_cursor(request)
        bus = get_bus()
        logger.info("event=SSE_CONNECTED user_id=%s", user_id)

        response = StreamingHttpResponse(
            event_stream(user_id, cursor, bus),
            content_type="text/event-stream; charset=utf-8",
        )
        response["Cache-Control"] = "no-cache, no-store"
        response["X-Accel-Buffering"] = "no"

        # The stream uses only the event bus. Release the request's DB
        # connection so a long-lived stream does not hold one for its lifetime
        # (§10.2). Never close one that is mid-transaction (ATOMIC_REQUESTS, or
        # the per-test transaction), which would break the caller.
        if not connection.in_atomic_block:
            connection.close()
        return response
