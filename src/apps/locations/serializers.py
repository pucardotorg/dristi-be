"""Locations serializers."""

from rest_framework import serializers

from apps.core.fields import StrictBooleanField

from .models import Location


class LocationFilterSerializer(serializers.Serializer):
    """Validates and normalizes query params for GET /locations/ and lookups."""

    location_type = serializers.ChoiceField(choices=Location.LocationType.choices, required=False)
    parent_id = serializers.UUIDField(required=False)
    parent_code = serializers.CharField(required=False)
    is_active = StrictBooleanField(required=False)

    def validate_parent_code(self, value):
        """Reject codes that match no location."""
        if not Location.objects.filter(code=value).exists():
            raise serializers.ValidationError(f"No location exists with code {value!r}.")
        return value

    def validate(self, attrs):
        """Enforce parent_id/parent_code exclusivity."""
        if "parent_id" in attrs and "parent_code" in attrs:
            raise serializers.ValidationError("parent_id and parent_code are mutually exclusive.")
        return attrs


class LocationSerializer(serializers.ModelSerializer):
    """Read-only representation of a location."""

    parent_code = serializers.CharField(source="parent.code", read_only=True, default=None)
    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        """Meta options."""

        model = Location
        fields = [
            "id",
            "code",
            "name",
            "short_name",
            "location_type",
            "parent",
            "parent_code",
            "full_name",
            "is_active",
            "additional_attributes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
