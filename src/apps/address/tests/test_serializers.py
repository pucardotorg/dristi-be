"""Tests for the read-only Address serializer."""

import pytest

from apps.address.models import Address
from apps.address.serializers import AddressSerializer
from apps.parties.tests.factories import ADDRESS_DEFAULTS
from apps.users.models import User


@pytest.mark.django_db
class TestAddressSerializer:
    """Output shape and read-only behaviour."""

    def test_output_fields(self):
        address, _ = Address.objects.get_or_create_address(**ADDRESS_DEFAULTS)

        data = AddressSerializer(address).data

        assert set(data) == {
            "id",
            "line1",
            "city",
            "state",
            "pincode",
            "district",
            "police_station",
            "created_at",
            "created_by",
        }

    def test_hash_is_not_exposed(self):
        address, _ = Address.objects.get_or_create_address(**ADDRESS_DEFAULTS)

        assert "hash" not in AddressSerializer(address).data

    def test_creator_is_id_and_name_only(self):
        user = User.objects.create_user(mobile_number="+919876543210", name="Priya")
        address, _ = Address.objects.get_or_create_address(created_by=user, **ADDRESS_DEFAULTS)

        assert AddressSerializer(address).data["created_by"] == {
            "id": str(user.id),
            "name": "Priya",
        }

    def test_creator_is_null_when_unknown(self):
        address, _ = Address.objects.get_or_create_address(**ADDRESS_DEFAULTS)

        assert AddressSerializer(address).data["created_by"] is None

    def test_input_is_ignored(self):
        serializer = AddressSerializer(data={**ADDRESS_DEFAULTS})

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data == {}
