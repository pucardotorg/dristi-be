"""Parties serializers.

``created_by`` and ``updated_by`` are deliberately not exposed. A person or
institution is often entered by the other side (the complainant's advocate
records the accused), so showing who entered a record to everyone who reads it
would reveal who on the other side typed it. They stay in the database, the
history tables and the admin for audit.
"""

from rest_framework import serializers

from apps.address.serializers import AddressSerializer

from .models import Institution, Person


class InstitutionSerializer(serializers.ModelSerializer):
    """Read-only representation of an institution, with its address nested."""

    address = AddressSerializer(read_only=True)

    class Meta:
        """Meta options."""

        model = Institution
        fields = [
            "id",
            "entity_type",
            "entity_name",
            "pan",
            "cin",
            "contact_number",
            "email_address",
            "address",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PersonSerializer(serializers.ModelSerializer):
    """Read-only representation of a person, with addresses and institution nested."""

    institution = InstitutionSerializer(read_only=True)
    # Today's age: from the date of birth when known, else the stated age.
    age = serializers.IntegerField(source="current_age", read_only=True, allow_null=True)
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
            "age",
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
        ]
        read_only_fields = fields
