"""Organization serializers."""

from rest_framework import serializers
from rest_framework.fields import empty

from .models import Organization, OrganizationType


class StrictBooleanField(serializers.BooleanField):
    """BooleanField that accepts only the literal "true"/"false" (case-insensitive).

    DRF's own BooleanField also accepts "1"/"0"/"yes"/"on"/etc, which is more
    permissive than this API's query-param contract wants.
    """

    default_error_messages = {
        "invalid": 'Must be "true" or "false".',
    }
    # BooleanField normally treats a QueryDict (e.g. request.query_params) as
    # an HTML form and substitutes False when the key is missing, so an
    # absent `is_active` param would otherwise be validated as False instead
    # of being treated as "not provided".
    default_empty_html = empty

    def to_internal_value(self, data):
        """Normalize to lowercase and accept only "true"/"false"."""
        if isinstance(data, str):
            data = data.strip().lower()
        if data == "true":
            return True
        if data == "false":
            return False
        self.fail("invalid", input=data)


class OrganizationSerializer(serializers.ModelSerializer):
    """Read-only serializer for organizations."""

    organization_type_display = serializers.CharField(
        source="get_organization_type_display", read_only=True
    )
    parent_code = serializers.SerializerMethodField()
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

    def get_parent_code(self, obj):
        """Return the parent organization's code, or None for root organizations."""
        return obj.parent.code if obj.parent_id else None


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
