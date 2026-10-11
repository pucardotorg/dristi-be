"""Parties serializers."""

from apps.address.serializers import AddressSerializer
from apps.api.serializers import AuditedModelSerializer

from .models import Institution, Person


class InstitutionSerializer(AuditedModelSerializer):
    """Read-only representation of an institution."""

    class Meta:
        """Meta options."""

        model = Institution
        fields = [
            "id",
            "entity_type",
            "entity_name",
            "contact_number",
            "email_address",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]
        read_only_fields = fields


class PersonSerializer(AuditedModelSerializer):
    """Read-only representation of a person, with addresses and institution nested."""

    institution = InstitutionSerializer(read_only=True)
    permanent_address = AddressSerializer(read_only=True)
    correspondence_address = AddressSerializer(read_only=True)

    class Meta:
        """Meta options."""

        model = Person
        fields = [
            "id",
            "name",
            "phone_number",
            "email_address",
            "relation",
            "relative_name",
            "date_of_birth",
            "gender",
            "institution",
            "designation",
            "permanent_address",
            "correspondence_address",
            "disability_status",
            "verification_level",
            "user",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        ]
        read_only_fields = fields
