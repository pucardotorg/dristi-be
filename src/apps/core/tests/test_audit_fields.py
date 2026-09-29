"""Tests for the created_by / updated_by audit fields on BaseModel."""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models

from apps.core.models import AdditionalAttribute, ApiVersionChangeLog, BaseModel

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        mobile_number="+919000000001", name="auditor", email="auditor@example.com", password="x"
    )


class TestAuditFieldDefinition:
    """Field-level configuration checks."""

    def test_base_model_is_abstract(self):
        assert BaseModel._meta.abstract is True

    @pytest.mark.parametrize("field_name", ["created_by", "updated_by"])
    @pytest.mark.parametrize("model", [AdditionalAttribute, ApiVersionChangeLog])
    def test_field_targets_auth_user_model(self, model, field_name):
        field = model._meta.get_field(field_name)
        assert field.null is True
        assert field.blank is True
        assert field.remote_field.on_delete is models.SET_NULL
        target = field.remote_field.model
        assert f"{target._meta.app_label}.{target._meta.object_name}" == settings.AUTH_USER_MODEL

    @pytest.mark.parametrize("field_name", ["created_by", "updated_by"])
    @pytest.mark.parametrize("model", [AdditionalAttribute, ApiVersionChangeLog])
    def test_reverse_accessors_are_unique(self, model, field_name):
        field = model._meta.get_field(field_name)
        expected = f"{model._meta.app_label}_{model._meta.model_name}_{field_name}"
        assert field.remote_field.get_accessor_name() == expected

    def test_no_reverse_accessor_clashes_across_concrete_models(self):
        """Every concrete BaseModel subclass gets distinct reverse accessors."""
        accessors = [
            rel.get_accessor_name()
            for rel in User._meta.related_objects
            if issubclass(rel.related_model, BaseModel)
        ]
        assert accessors
        assert len(accessors) == len(set(accessors))


@pytest.mark.django_db
class TestAuditFieldBehavior:
    """Database behaviour of the audit fields."""

    def test_defaults_to_null_without_user(self):
        entry = ApiVersionChangeLog.objects.create(version="1.0.0", change_log="System import.")
        entry.refresh_from_db()
        assert entry.created_by is None
        assert entry.updated_by is None

    def test_can_be_set_explicitly(self, user):
        entry = ApiVersionChangeLog.objects.create(
            version="1.0.0",
            change_log="Manual entry.",
            created_by=user,
            updated_by=user,
        )
        entry.refresh_from_db()
        assert entry.created_by == user
        assert entry.updated_by == user

    def test_deleting_user_sets_audit_fields_to_null(self, user):
        entry = ApiVersionChangeLog.objects.create(
            version="1.0.0",
            change_log="Manual entry.",
            created_by=user,
            updated_by=user,
        )
        user.delete()
        entry.refresh_from_db()
        assert entry.created_by is None
        assert entry.updated_by is None
        assert ApiVersionChangeLog.objects.filter(pk=entry.pk).exists()

    def test_reverse_relation_lookup(self, user):
        ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="Entry.", created_by=user, updated_by=user
        )
        assert user.core_apiversionchangelog_created_by.count() == 1
        assert user.core_apiversionchangelog_updated_by.count() == 1

    def test_background_task_can_save_without_user(self, user):
        """Dramatiq actors / management commands may save without a user context."""
        entry = ApiVersionChangeLog.objects.create(version="1.0.0", change_log="Entry.")
        entry.change_log = "Updated by a background job."
        entry.save()
        entry.refresh_from_db()
        assert entry.created_by is None
        assert entry.updated_by is None
