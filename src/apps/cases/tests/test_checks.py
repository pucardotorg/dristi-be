"""Tests for the cases settings checks."""

from django.test import override_settings

from apps.cases.services import checks, services


def test_check_passes_with_a_real_cache():
    assert checks.check_draft_cache(None) == []


def test_check_refuses_a_dummy_cache(settings):
    dummy = {"BACKEND": checks.DUMMY_CACHE}
    with override_settings(CACHES={**settings.CACHES, services.DRAFT_CACHE_ALIAS: dummy}):
        assert [e.id for e in checks.check_draft_cache(None)] == ["cases.E002"]


def test_check_refuses_a_missing_alias(settings):
    with override_settings(CACHES={"default": settings.CACHES["default"]}):
        assert [e.id for e in checks.check_draft_cache(None)] == ["cases.E001"]
