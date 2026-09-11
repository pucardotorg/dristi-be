"""Tests for audit-field population in the Django admin."""

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from apps.core.admin import AdditionalAttributeAdmin, ApiVersionChangeLogAdmin
from apps.core.models import ApiVersionChangeLog

User = get_user_model()


@pytest.fixture
def admin_instance():
    return ApiVersionChangeLogAdmin(ApiVersionChangeLog, AdminSite())


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        email="staff@example.com", username="staff", password="x", is_staff=True
    )


@pytest.fixture
def request_for(staff_user):
    def _build(user=None):
        request = RequestFactory().post("/admin/")
        request.user = staff_user if user is None else user
        return request

    return _build


@pytest.mark.django_db
class TestAuditUserAdminMixin:
    """The admin must set the audit fields instead of asking the user for them."""

    def test_audit_fields_are_readonly(self, admin_instance, request_for):
        readonly = admin_instance.get_readonly_fields(request_for())
        assert "created_by" in readonly
        assert "updated_by" in readonly
        # Existing read-only fields are preserved.
        assert {"id", "created_at", "updated_at"} <= set(readonly)

    def test_add_form_does_not_ask_for_audit_fields(self, admin_instance, request_for):
        form = admin_instance.get_form(request_for(), obj=None)
        assert "created_by" not in form.base_fields
        assert "updated_by" not in form.base_fields

    def test_save_model_sets_both_fields_on_add(self, admin_instance, request_for, staff_user):
        obj = ApiVersionChangeLog(version="1.0.0", change_log="Created in admin.")
        admin_instance.save_model(request_for(), obj, form=None, change=False)
        obj.refresh_from_db()
        assert obj.created_by == staff_user
        assert obj.updated_by == staff_user

    def test_save_model_keeps_created_by_on_change(self, admin_instance, request_for, staff_user):
        author = User.objects.create_user(
            email="author@example.com", username="author", password="x"
        )
        obj = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="Entry.", created_by=author, updated_by=author
        )
        obj.change_log = "Amended in admin."
        admin_instance.save_model(request_for(), obj, form=None, change=True)
        obj.refresh_from_db()
        assert obj.created_by == author
        assert obj.updated_by == staff_user

    def test_anonymous_request_leaves_fields_null(self, admin_instance, request_for):
        obj = ApiVersionChangeLog(version="1.0.0", change_log="Entry.")
        admin_instance.save_model(request_for(AnonymousUser()), obj, form=None, change=False)
        obj.refresh_from_db()
        assert obj.created_by is None
        assert obj.updated_by is None

    def test_mixin_applied_to_other_core_admins(self, request_for):
        from apps.core.models import AdditionalAttribute

        admin_obj = AdditionalAttributeAdmin(AdditionalAttribute, AdminSite())
        readonly = admin_obj.get_readonly_fields(request_for())
        assert "created_by" in readonly
        assert "updated_by" in readonly
