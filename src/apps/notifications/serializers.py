"""Serializers for the notification inbox and SSE query (spec 0031 §6.4)."""

from __future__ import annotations

from rest_framework import serializers

from .models import Notification

EVENT_TYPE_REGEX = r"^[A-Z][A-Z0-9_]*$"
STREAM_ID_REGEX = r"^\d+-\d+$"


class NotificationSerializer(serializers.ModelSerializer):
    """Read-only representation of one notification.

    ``recipient`` and the audit users are never exposed: they are implicit in
    the authenticated request.
    """

    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        """Meta options."""

        model = Notification
        fields = (
            "id",
            "event_type",
            "title",
            "body",
            "data",
            "priority",
            "is_read",
            "read_at",
            "created_at",
        )
        read_only_fields = fields


class NotificationFilterSerializer(serializers.Serializer):
    """Validates the optional list query parameters (used by the list action)."""

    is_read = serializers.BooleanField(required=False)
    event_type = serializers.RegexField(EVENT_TYPE_REGEX, required=False)
    priority = serializers.ChoiceField(choices=Notification.Priority.choices, required=False)


class NotificationSubscribeQuerySerializer(serializers.Serializer):
    """Validates the optional ``last_event_id`` query parameter for the stream.

    An invalid value is discarded by the view, never turned into an error.
    """

    last_event_id = serializers.RegexField(STREAM_ID_REGEX, required=False)


class MarkAllReadSerializer(serializers.Serializer):
    """Response of the mark-all-read action."""

    updated = serializers.IntegerField(read_only=True)


class UnreadCountSerializer(serializers.Serializer):
    """Response of the unread-count action."""

    count = serializers.IntegerField(read_only=True)
