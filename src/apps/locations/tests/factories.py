"""Shared Location fixtures for the locations test suite."""

from django.contrib.contenttypes.models import ContentType

from apps.core.models import AdditionalAttribute
from apps.locations.models import Location

DEFAULTS = {
    "code": "IN",
    "name": "India",
    "short_name": "IN",
    "location_type": Location.LocationType.COUNTRY,
    "parent": None,
}


def make_location(**overrides):
    """Create a location, defaulting to the India country node."""
    return Location.objects.create(**{**DEFAULTS, **overrides})


def make_country(**overrides):
    """Create the India country node."""
    return make_location(**overrides)


def make_state(parent=None, code="BR", name="Bihar", **overrides):
    """Create a state under ``parent`` (defaults to Bihar)."""
    return make_location(
        code=code,
        name=name,
        short_name=overrides.pop("short_name", code),
        location_type=Location.LocationType.STATE,
        parent=parent,
        **overrides,
    )


def make_district(parent=None, code="PATNA", name="Patna", **overrides):
    """Create a district under ``parent`` (defaults to Patna)."""
    return make_location(
        code=code,
        name=name,
        short_name=overrides.pop("short_name", name),
        location_type=Location.LocationType.DISTRICT,
        parent=parent,
        **overrides,
    )


def make_bank(
    parent,
    code="SBIN0001234",
    bank="State Bank of India",
    branch="Patna Main",
    address=None,
    **overrides,
):
    """Create a bank branch under ``parent`` in the issue #249 shape.

    ``address`` is stored as an additional attribute, so the ``address``
    definition must exist (``define_address_attribute``) when one is given.
    """
    if address is not None:
        overrides["additional_attributes"] = {"address": address}
    return make_location(
        code=code,
        name=overrides.pop("name", f"{bank} - {branch}"),
        short_name=overrides.pop("short_name", code),
        location_type=Location.LocationType.BANK,
        parent=parent,
        **overrides,
    )


def make_police_station(
    parent, code="15996001", name="THRISSUR EAST", police_district=None, **overrides
):
    """Create a police station under ``parent`` in the issue #250 shape.

    ``police_district`` is stored as an additional attribute, so its definition
    must exist (``define_police_district_attribute``) when one is given.
    """
    if police_district is not None:
        overrides["additional_attributes"] = {"police_district": police_district}
    return make_location(
        code=code,
        name=name,
        short_name=overrides.pop("short_name", ""),
        location_type=Location.LocationType.POLICE_STATION,
        parent=parent,
        **overrides,
    )


def define_police_district_attribute():
    """Define the ``police_district`` additional attribute on Location, as the core seed does."""
    return AdditionalAttribute.objects.get_or_create(
        content_type=ContentType.objects.get_for_model(Location),
        name="police_district",
        defaults={"data_type": "character", "is_nullable": True},
    )[0]


def define_address_attribute():
    """Define the ``address`` additional attribute on Location, as the core seed does."""
    return AdditionalAttribute.objects.get_or_create(
        content_type=ContentType.objects.get_for_model(Location),
        name="address",
        defaults={"data_type": "character", "is_nullable": True},
    )[0]


def make_hierarchy():
    """Create the IN -> BR -> PATNA chain from the spec example."""
    india = make_country()
    bihar = make_state(parent=india)
    patna = make_district(parent=bihar)
    return india, bihar, patna


def make_country_and_state():
    """Create the IN -> BR chain, leaving the state childless."""
    india = make_country()
    return india, make_state(parent=india)
