"""Organization serializers."""

from rest_framework import serializers

from apps.core.fields import StrictBooleanField

from .models import Organization, OrganizationType


class OrganizationSerializer(serializers.ModelSerializer):
    """Read-only serializer for organizations."""

    organization_type_display = serializers.CharField(
        source="get_organization_type_display", read_only=True
    )
    parent_code = serializers.CharField(source="parent.code", read_only=True, default=None)
    jurisdiction_codes = serializers.SlugRelatedField(
        slug_field="code", many=True, read_only=True, source="jurisdictions"
    )

    class Meta:
        """Meta options."""

        model = Organization
        fields = [
            "id",
            "code",
            "organization_type",
            "organization_type_display",
            "name",
            "short_name",
            "description",
            "parent",
            "parent_code",
            "jurisdiction_codes",
            "is_active",
            "additional_attributes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class OrganizationFilterSerializer(serializers.Serializer):
    """Validates and normalizes query params for GET /organizations/."""

    organization_type = serializers.ChoiceField(choices=OrganizationType.choices, required=False)
    parent_id = serializers.UUIDField(required=False)
    parent_code = serializers.CharField(required=False)
    jurisdiction_id = serializers.UUIDField(required=False)
    jurisdiction_code = serializers.CharField(required=False)
    is_active = StrictBooleanField(required=False)

    def validate(self, attrs):
        """Enforce the parent_id/parent_code and jurisdiction_id/jurisdiction_code exclusivity."""
        if attrs.get("parent_id") and attrs.get("parent_code"):
            raise serializers.ValidationError("parent_id and parent_code are mutually exclusive.")

        if attrs.get("jurisdiction_id") and attrs.get("jurisdiction_code"):
            raise serializers.ValidationError(
                "jurisdiction_id and jurisdiction_code are mutually exclusive."
            )

        return attrs
