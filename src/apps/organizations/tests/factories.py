"""Shared Organization fixtures for the organizations test suite."""

from apps.organizations.models import Organization, OrganizationType

DEFAULTS = {
    "code": "TEST_ORG",
    "organization_type": OrganizationType.HIGH_COURT,
    "name": "Test Organization",
}


def make_organization(**kwargs):
    """Create an Organization with sensible defaults for tests."""
    jurisdictions = kwargs.pop("jurisdictions", None)
    org = Organization.objects.create(**{**DEFAULTS, **kwargs})
    if jurisdictions is not None:
        org.jurisdictions.set(jurisdictions)
    return org
