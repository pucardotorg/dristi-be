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


class LocationChildrenFilterSerializer(serializers.Serializer):
    """Validates query params for the children routes, which filter the children.

    The parent is identified by the URL path and only active children of an
    active parent are ever listed, so ``is_active=true`` changes nothing,
    while ``is_active=false`` and the parent filters are rejected rather than
    ignored. As on the other routes, an empty value counts as not sent.
    """

    UNSUPPORTED_MESSAGE = (
        "parent_id and parent_code are not supported; the parent is identified by the URL path."
    )
    INACTIVE_MESSAGE = "Inactive children are never listed; omit is_active or pass 'true'."

    location_type = serializers.ChoiceField(
        choices=Location.LocationType.choices,
        required=False,
        help_text="Only children of this type.",
    )
    is_active = StrictBooleanField(
        required=False,
        help_text=(
            "'true' is accepted and changes nothing: only active children of an active "
            "parent are ever listed. 'false' is rejected."
        ),
    )

    def validate_is_active(self, value):
        """Reject is_active=false, which can never be satisfied."""
        if value is False:
            raise serializers.ValidationError(self.INACTIVE_MESSAGE)
        return value

    def validate(self, attrs):
        """Reject the parent filters, which conflict with the URL path."""
        if any(self.initial_data.get(param) for param in ("parent_id", "parent_code")):
            raise serializers.ValidationError(self.UNSUPPORTED_MESSAGE)
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
