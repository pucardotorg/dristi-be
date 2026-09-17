"""Serializers for core app APIs."""

from rest_framework import serializers

from .models import ApiVersionChangeLog


class ApiVersionChangeLogSerializer(serializers.ModelSerializer):
    """Serializer for API version change-log entries."""

    class Meta:
        """Meta options."""

        model = ApiVersionChangeLog
        fields = [
            "id",
            "version",
            "change_log",
            "additional_attributes",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
