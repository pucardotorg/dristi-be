"""Locations serializers."""

from rest_framework import serializers

from .models import Location


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
