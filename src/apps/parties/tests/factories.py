"""Shared fixtures for the parties test suite."""

from apps.address.models import Address
from apps.parties.models import EntityType, Institution, Person

ADDRESS_DEFAULTS = {
    "line1": "12 MG Road",
    "city": "Bengaluru",
    "state": "Karnataka",
    "pincode": "560001",
    "district": "Bengaluru Urban",
    "police_station": "Cubbon Park",
}


def make_address(**kwargs):
    """Return an Address with sensible defaults, reusing an identical one."""
    address, _ = Address.objects.get_or_create_address(**{**ADDRESS_DEFAULTS, **kwargs})
    return address


def make_institution(**kwargs):
    """Create an Institution with sensible defaults for tests."""
    defaults = {
        "entity_type": EntityType.PRIVATE_LIMITED_COMPANY,
        "entity_name": "ABC Pvt Ltd",
    }
    return Institution.objects.create(**{**defaults, **kwargs})


def make_person(**kwargs):
    """Create a Person with sensible defaults for tests."""
    defaults = {"name": "Priya Sharma"}
    return Person.objects.create(**{**defaults, **kwargs})
