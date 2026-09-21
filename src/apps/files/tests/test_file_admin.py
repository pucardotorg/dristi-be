"""Tests for the files admin: configuration and the add-permission guard."""

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from apps.files.admin import FileAdmin, FileTagAdmin
from apps.files.models import File, FileTag
from apps.users.models import User


@pytest.fixture
def file_admin():
    """Return a FileAdmin bound to a bare admin site."""
    return FileAdmin(File, AdminSite())


@pytest.fixture
def file_tag_admin():
    """Return a FileTagAdmin bound to a bare admin site."""
    return FileTagAdmin(FileTag, AdminSite())


@pytest.fixture
def superuser_request():
    """Return an admin request from a user who holds every permission."""
    request = RequestFactory().get("/admin/files/")
    request.user = User.objects.create_superuser(
        email="admin@example.com", username="admin", password="test-password"
    )
    return request


class TestFileAdminConfiguration:
    """Admin options for File."""

    def test_list_display_and_filters(self, file_admin):
        assert file_admin.list_display == (
            "file_name",
            "file_type",
            "organization",
            "user",
            "file_size",
            "is_active",
            "created_at",
        )
        assert file_admin.list_filter == ("file_type", "is_active")
        assert file_admin.search_fields == ("file_name", "storage_path", "user__email")
        assert file_admin.list_select_related == ("organization", "user")
        assert file_admin.filter_horizontal == ("tags",)

    def test_storage_owned_fields_are_read_only(self, file_admin):
        assert set(file_admin.readonly_fields) >= {
            "id",
            "created_at",
            "updated_at",
            "storage_path",
            "content_type",
            "file_size",
        }

    @pytest.mark.django_db
    def test_files_cannot_be_added_even_by_a_superuser(self, file_admin, superuser_request):
        """Metadata without a stored object would be an orphan row."""
        assert file_admin.has_add_permission(superuser_request) is False


class TestFileTagAdminConfiguration:
    """Admin options for FileTag."""

    def test_list_display_and_search(self, file_tag_admin):
        assert file_tag_admin.list_display == ("name", "created_at")
        assert file_tag_admin.search_fields == ("name",)
        assert file_tag_admin.readonly_fields == ("id", "created_at", "updated_at")
        assert file_tag_admin.ordering == ("name",)

    @pytest.mark.django_db
    def test_tags_can_be_added_through_the_admin(self, file_tag_admin, superuser_request):
        assert file_tag_admin.has_add_permission(superuser_request) is True
