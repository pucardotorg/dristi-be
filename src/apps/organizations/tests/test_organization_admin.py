"""Tests for the Organization admin: jurisdiction validation and configuration."""

import pytest
from django.contrib.admin.sites import AdminSite

from apps.locations.tests.factories import make_hierarchy
from apps.organizations.admin import OrganizationAdmin, OrganizationAdminForm
from apps.organizations.models import Organization, OrganizationType


@pytest.fixture
def admin_instance():
    """Return an OrganizationAdmin bound to a bare admin site."""
    return OrganizationAdmin(Organization, AdminSite())


@pytest.mark.django_db
class TestOrganizationAdminForm:
    """Active organizations must have at least one jurisdiction (spec 0008 section 3)."""

    def test_active_organization_without_jurisdiction_is_invalid(self):
        form = OrganizationAdminForm(
            data={
                "code": "NO_JURIS_ORG",
                "organization_type": OrganizationType.HIGH_COURT,
                "name": "No Jurisdiction Org",
                "is_active": True,
            }
        )

        assert not form.is_valid()
        assert "Active organizations must have at least one jurisdiction location." in str(
            form.errors
        )

    def test_active_organization_with_jurisdiction_is_valid(self):
        _, bihar, _ = make_hierarchy()

        form = OrganizationAdminForm(
            data={
                "code": "WITH_JURIS_ORG",
                "organization_type": OrganizationType.HIGH_COURT,
                "name": "With Jurisdiction Org",
                "is_active": True,
                "jurisdictions": [bihar.pk],
            }
        )

        assert form.is_valid(), form.errors

    def test_inactive_organization_without_jurisdiction_is_valid(self):
        form = OrganizationAdminForm(
            data={
                "code": "INACTIVE_NO_JURIS",
                "organization_type": OrganizationType.HIGH_COURT,
                "name": "Inactive Org",
            }
        )

        assert form.is_valid(), form.errors


class TestOrganizationAdminConfiguration:
    """Admin options required by spec 0008 section 6."""

    def test_list_display_and_filters(self, admin_instance):
        assert admin_instance.list_display == (
            "code",
            "name",
            "short_name",
            "organization_type",
            "parent",
            "is_active",
        )
        assert admin_instance.list_filter == ("organization_type", "is_active")
        assert admin_instance.search_fields == ("code", "name", "short_name")
        assert admin_instance.readonly_fields == ("id", "created_at", "updated_at")
        assert admin_instance.filter_horizontal == ("jurisdictions",)
