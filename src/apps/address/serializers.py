"""Address serializers."""

from rest_framework import serializers

from apps.users.serializers import AuditUserSerializer

from .models import Address


class AddressSerializer(serializers.ModelSerializer):
    """Read-only representation of an address."""

    created_by = AuditUserSerializer(read_only=True)

    class Meta:
        """Meta options."""

        model = Address
        fields = [
            "id",
            "line1",
            "city",
            "state",
            "pincode",
            "district",
            "police_station",
            "created_at",
            "created_by",
        ]
        read_only_fields = fields
