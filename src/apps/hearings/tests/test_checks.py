"""The production guard on the pinned business date (spec 0023 #4)."""

import pytest

from apps.hearings import checks, conf

pytestmark = pytest.mark.django_db


def test_override_allowed_outside_production():
    assert checks.check_business_date_override(None, databases=["default"]) == []


def test_override_refused_in_production(monkeypatch):
    monkeypatch.setattr(conf, "is_production", lambda: True)
    errors = checks.check_business_date_override(None, databases=["default"])
    assert [error.id for error in errors] == ["hearings.E001"]


def test_no_override_in_production_is_fine(monkeypatch):
    from apps.core.models import Configuration

    Configuration.objects.filter(
        config_set="hearings", config_key="business_date_override"
    ).delete()
    monkeypatch.setattr(conf, "is_production", lambda: True)
    assert checks.check_business_date_override(None, databases=["default"]) == []


def test_skipped_without_the_database_tag():
    assert checks.check_business_date_override(None) == []


def test_skipped_before_the_tables_exist(monkeypatch):
    """``check --database`` on a fresh database, before ``migrate``, must not crash."""
    from django.db import ProgrammingError

    from apps.core.models import Configuration

    def no_table(*args, **kwargs):
        raise ProgrammingError('relation "core_configuration" does not exist')

    monkeypatch.setattr(conf, "is_production", lambda: True)
    monkeypatch.setattr(Configuration.objects, "active", no_table)
    assert checks.check_business_date_override(None, databases=["default"]) == []
