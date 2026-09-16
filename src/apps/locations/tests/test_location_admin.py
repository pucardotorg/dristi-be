"""Tests for the Location admin, focused on protected-deletion messaging."""

import pytest
from django.contrib import messages
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.cookie import CookieStorage
from django.test import RequestFactory

from apps.locations.admin import LocationAdmin
from apps.locations.models import Location
from apps.locations.tests.factories import make_country_and_state


@pytest.fixture
def admin_instance():
    """Return a LocationAdmin bound to a bare admin site."""
    return LocationAdmin(Location, AdminSite())


@pytest.fixture
def request_with_messages():
    """Return a request whose message storage needs no session backend."""
    request = RequestFactory().post("/admin/locations/location/")
    request._messages = CookieStorage(request)
    return request


def collected(request):
    """Return the (level, message) pairs queued on the request."""
    return [(message.level, str(message)) for message in request._messages]


@pytest.mark.django_db
class TestLocationAdminDeletion:
    """Deleting a parent with children must not raise."""

    def test_delete_model_reports_protected_children(self, admin_instance, request_with_messages):
        india, _ = make_country_and_state()

        admin_instance.delete_model(request_with_messages, india)

        levels = [level for level, _ in collected(request_with_messages)]
        assert messages.ERROR in levels
        assert Location.objects.filter(code="IN").exists()

    def test_delete_model_succeeds_for_leaf(self, admin_instance, request_with_messages):
        _, bihar = make_country_and_state()

        admin_instance.delete_model(request_with_messages, bihar)

        assert collected(request_with_messages) == []
        assert not Location.objects.filter(code="BR").exists()

    def test_delete_queryset_reports_protected_children(
        self, admin_instance, request_with_messages
    ):
        make_country_and_state()

        admin_instance.delete_queryset(request_with_messages, Location.objects.filter(code="IN"))

        levels = [level for level, _ in collected(request_with_messages)]
        assert messages.ERROR in levels
        assert Location.objects.filter(code="IN").exists()

    def test_delete_queryset_succeeds_for_leaves(self, admin_instance, request_with_messages):
        make_country_and_state()

        admin_instance.delete_queryset(request_with_messages, Location.objects.filter(code="BR"))

        assert collected(request_with_messages) == []
        assert not Location.objects.filter(code="BR").exists()


class TestLocationAdminConfiguration:
    """Admin options required by spec sections 5 and 0006 section 4."""

    def test_list_display_and_filters(self, admin_instance):
        assert admin_instance.list_display == (
            "code",
            "name",
            "short_name",
            "location_type",
            "parent",
            "is_active",
        )
        assert admin_instance.list_filter == ("location_type", "is_active")
        assert admin_instance.search_fields == ("code", "name", "short_name")
        assert admin_instance.readonly_fields == ("id", "created_at", "updated_at")
