"""Tests for ActivatableQuerySet and BaseActivatableModel."""

import pytest
from django.db import models

from apps.core.models import (
    ActivatableQuerySet,
    ApiVersionChangeLog,
    BaseActivatableModel,
    BaseModel,
)


@pytest.mark.django_db
class TestActivatableQuerySet:
    """Tests for the activatable queryset helpers using ApiVersionChangeLog."""

    def test_active_returns_only_active_rows(self):
        active = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="active", is_active=True, additional_attributes={}
        )
        inactive = ApiVersionChangeLog.objects.create(
            version="2.0.0", change_log="inactive", is_active=False, additional_attributes={}
        )

        result = ApiVersionChangeLog.objects.active()

        assert active in result
        assert inactive not in result

    def test_inactive_returns_only_inactive_rows(self):
        active = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="active", is_active=True, additional_attributes={}
        )
        inactive = ApiVersionChangeLog.objects.create(
            version="2.0.0", change_log="inactive", is_active=False, additional_attributes={}
        )

        result = ApiVersionChangeLog.objects.inactive()

        assert inactive in result
        assert active not in result

    def test_all_includes_both_active_and_inactive_rows(self):
        active = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="active", is_active=True, additional_attributes={}
        )
        inactive = ApiVersionChangeLog.objects.create(
            version="2.0.0", change_log="inactive", is_active=False, additional_attributes={}
        )

        result = ApiVersionChangeLog.objects.all()

        assert active in result
        assert inactive in result

    def test_chaining_with_other_filters(self):
        ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="match", is_active=True, additional_attributes={}
        )
        ApiVersionChangeLog.objects.create(
            version="2.0.0", change_log="no-match", is_active=True, additional_attributes={}
        )
        ApiVersionChangeLog.objects.create(
            version="3.0.0", change_log="match", is_active=False, additional_attributes={}
        )

        result = ApiVersionChangeLog.objects.active().filter(change_log="match")

        assert result.count() == 1


@pytest.mark.django_db
class TestBaseActivatableModel:
    """Tests for the BaseActivatableModel mixin using ApiVersionChangeLog."""

    def test_default_is_active_is_true(self):
        log = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="default", additional_attributes={}
        )

        assert log.is_active is True

    def test_can_create_inactive_row(self):
        log = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="inactive", is_active=False, additional_attributes={}
        )

        assert log.is_active is False

    def test_can_update_is_active(self):
        log = ApiVersionChangeLog.objects.create(
            version="1.0.0", change_log="demo", is_active=True, additional_attributes={}
        )
        log.is_active = False
        log.save()
        log.refresh_from_db()

        assert log.is_active is False


class TestBaseActivatableModelDefinition:
    """Tests for the abstract mixin definition itself."""

    def test_is_abstract(self):
        assert BaseActivatableModel._meta.abstract is True

    def test_has_is_active_field_with_default_true(self):
        field = BaseActivatableModel._meta.get_field("is_active")

        assert field.__class__.__name__ == "BooleanField"
        assert field.default is True

    def test_api_version_changelog_uses_activatable_manager(self):
        assert isinstance(ApiVersionChangeLog.objects, models.Manager)
        assert hasattr(ApiVersionChangeLog.objects, "active")
        assert hasattr(ApiVersionChangeLog.objects, "inactive")

    def test_queryset_class_provides_active_and_inactive(self):
        qs = ActivatableQuerySet(model=BaseActivatableModel)

        assert hasattr(qs, "active")
        assert hasattr(qs, "inactive")
