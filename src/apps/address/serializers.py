"""Address serializers."""

from rest_framework import serializers

from .models import Address


class AddressSerializer(serializers.ModelSerializer):
    """Read-only representation of an address.

    ``created_by`` is deliberately not exposed. One row is shared by every
    party at that address (a complainant and an accused can live at the same
    place), so its creator is only whoever entered it first, not its owner,
    and showing that to everyone who reads the address would leak who on the
    other side recorded it. It stays in the database and the admin for audit.
    """

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
        ]
        read_only_fields = fields
