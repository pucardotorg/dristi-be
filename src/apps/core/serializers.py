"""Serializers for core app APIs."""

from rest_framework import serializers

from .models import ApiVersionChangeLog, Language


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


class LanguageSerializer(serializers.ModelSerializer):
    """A supported language, as listed by GET /languages/ (spec 0030 section 6)."""

    supports = serializers.ListField(
        child=serializers.ChoiceField(choices=Language.LanguageSupport.choices),
        read_only=True,
    )

    class Meta:
        """Meta options."""

        model = Language
        fields = ["code", "name", "native_name", "is_default", "supports"]
        read_only_fields = fields


class LanguageFilterSerializer(serializers.Serializer):
    """Validates the query parameters of GET /languages/."""

    supports = serializers.ChoiceField(
        choices=Language.LanguageSupport.choices,
        required=False,
        help_text="Only list languages that declare this capability.",
    )
