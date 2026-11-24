"""Organization serializers."""

from drf_spectacular.utils import extend_schema_field
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
            "court_level",
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


# ---------------------------------------------------------------------------
# GET /court-roles/me/ (spec 0029 #9.2)
# ---------------------------------------------------------------------------

SCOPE_SCHEMA = {
    "type": "object",
    "properties": {
        "process_types": {"type": "array", "items": {"type": "string"}},
        "channels": {"type": "array", "items": {"type": "string"}},
    },
    "description": "A missing key covers every code on that axis.",
}
ACTION_ENTRY_SCHEMA = {
    "oneOf": [
        {"type": "string", "description": "An action code, allowed for everything."},
        {
            "type": "object",
            "description": "A scoped action: allowed where any of its scopes matches.",
            "properties": {
                "action": {"type": "string"},
                "scopes": {"type": "array", "items": SCOPE_SCHEMA},
            },
            "required": ["action", "scopes"],
        },
    ]
}


@extend_schema_field({"type": "array", "items": ACTION_ENTRY_SCHEMA})
class CourtActionListField(serializers.ListField):
    """The effective actions at one court: codes, or ``{action, scopes}`` for a scoped action."""

    child = serializers.JSONField()


class CourtRoleLabelSerializer(serializers.Serializer):
    """A role the caller holds, for display only: never branch on it (``RLE-08``)."""

    code = serializers.CharField()
    name = serializers.CharField()


class MyCourtroomSerializer(serializers.Serializer):
    """A courtroom on the caller's list, with what they may do there."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    roles = CourtRoleLabelSerializer(many=True)
    actions = CourtActionListField()


class MyEstablishmentSerializer(serializers.Serializer):
    """An establishment where the caller acts or is staff of a courtroom."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    actions = CourtActionListField()
    courtrooms = MyCourtroomSerializer(many=True)


class MyCourtRolesSerializer(serializers.Serializer):
    """The caller's courts and what they may do there."""

    establishments = MyEstablishmentSerializer(many=True)
