"""Tests for the Address admin: add-only, deduplicated, creator stamped."""

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from apps.address.admin import AddressAdmin
from apps.address.models import Address
from apps.parties.tests.factories import ADDRESS_DEFAULTS, make_address
from apps.users.models import User


@pytest.fixture
def admin_instance():
    """Return an AddressAdmin bound to a bare admin site."""
    return AddressAdmin(Address, AdminSite())


@pytest.fixture
def request_with_admin(db):
    """Return a request made by a superuser."""
    request = RequestFactory().get("/admin/")
    request.user = User.objects.create_superuser(mobile_number="+919876543210")
    return request


@pytest.mark.django_db
class TestAddressAdmin:
    """Existing addresses are view-only; new ones are checked for duplicates."""

    def test_existing_address_cannot_be_changed(self, admin_instance, request_with_admin):
        assert admin_instance.has_change_permission(request_with_admin, make_address()) is False

    def test_existing_address_cannot_be_deleted(self, admin_instance, request_with_admin):
        assert admin_instance.has_delete_permission(request_with_admin, make_address()) is False

    def test_superuser_can_add(self, admin_instance, request_with_admin):
        assert admin_instance.has_add_permission(request_with_admin) is True

    def test_audit_fields_are_read_only(self, admin_instance, request_with_admin):
        readonly = admin_instance.get_readonly_fields(request_with_admin)

        assert {"id", "hash", "created_at", "created_by"} <= set(readonly)

    def test_add_form_rejects_a_duplicate(self, admin_instance, request_with_admin):
        make_address()
        form_class = admin_instance.get_form(request_with_admin)

        form = form_class(data={**ADDRESS_DEFAULTS, "line1": "12 mg road"})

        assert not form.is_valid()
        assert "This address already exists." in str(form.errors)

    def test_add_stamps_the_admin_as_creator(self, admin_instance, request_with_admin):
        form_class = admin_instance.get_form(request_with_admin)
        form = form_class(data=ADDRESS_DEFAULTS)
        assert form.is_valid(), form.errors

        address = form.save(commit=False)
        admin_instance.save_model(request_with_admin, address, form, change=False)

        assert Address.objects.get(pk=address.pk).created_by == request_with_admin.user
