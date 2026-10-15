"""Cachalot behaviour for Page reads (spec 0018 section 3)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.cms.models import Page


@pytest.mark.django_db
class TestPageCaching:
    """Repeated page reads hit the cache; writes invalidate it."""

    def test_reads_are_cached_and_invalidated_on_write(self):
        # Warm the cache with one evaluation.
        list(Page.objects.all())

        # An identical query is now served by cachalot: no DB query.
        with CaptureQueriesContext(connection) as cached:
            list(Page.objects.all())
        assert len(cached.captured_queries) == 0

        # Writing a page invalidates the cached queryset.
        Page.objects.create(slug="cache-check", title="Cache check", content="x")
        with CaptureQueriesContext(connection) as after_write:
            list(Page.objects.all())
        assert len(after_write.captured_queries) >= 1
