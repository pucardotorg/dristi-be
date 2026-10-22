"""Cachalot behaviour for Page reads (spec 0018 section 3)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.cms.models import Page, PageCategory


@pytest.mark.django_db
class TestPageCaching:
    """Repeated page reads hit the cache; writes invalidate it."""

    def test_list_reads_are_cached_and_invalidated_on_write(self):
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

    def test_by_slug_read_is_cached(self):
        # Warm the by-slug query.
        Page.objects.get(slug="terms")

        with CaptureQueriesContext(connection) as cached:
            Page.objects.get(slug="terms")
        assert len(cached.captured_queries) == 0

    def test_category_mapping_change_invalidates_cache(self):
        page = Page.objects.get(slug="support")
        faq = PageCategory.objects.get(slug="faq")

        # add() writes to the page-category join table and must invalidate
        # any cached read of that page's categories.
        list(page.categories.all())
        page.categories.add(faq)
        with CaptureQueriesContext(connection) as after_add:
            list(page.categories.all())
        assert len(after_add.captured_queries) >= 1

        # remove() must invalidate it too.
        page.categories.remove(faq)
        with CaptureQueriesContext(connection) as after_remove:
            list(page.categories.all())
        assert len(after_remove.captured_queries) >= 1
