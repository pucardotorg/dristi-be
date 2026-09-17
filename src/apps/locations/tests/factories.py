"""Shared Location fixtures for the locations test suite."""

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
