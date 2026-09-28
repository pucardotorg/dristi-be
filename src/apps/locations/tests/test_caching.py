"""Tests for cachalot-backed ORM caching on the locations app.

Verifies the Phase-1 rollout from spec/0012-redis-caching.md: repeated reads
are served from cache, writes invalidate the cache, tables outside the
Phase-1 allow-list are never cached, and cachalot can be disabled on demand
without a process restart.
"""

from cachalot.api import cachalot_disabled
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.locations.tests.factories import make_hierarchy
from apps.messaging.models import MessageTemplate


class LocationQueryCachingTests(TestCase):
    """Location is in CACHALOT_ONLY_CACHABLE_APPS, so it should be cached."""

    def setUp(self):
        """Create a small IN -> BR -> PATNA hierarchy."""
        self.india, self.bihar, self.patna = make_hierarchy()
        self.Location = self.india._meta.model

    def test_repeated_read_is_served_from_cache(self):
        """A second identical queryset read should not hit the database."""
        with CaptureQueriesContext(connection) as first:
            list(self.Location.objects.all())
        self.assertGreater(len(first.captured_queries), 0)

        with CaptureQueriesContext(connection) as second:
            list(self.Location.objects.all())
        self.assertEqual(len(second.captured_queries), 0)

    def test_write_invalidates_cached_queryset(self):
        """Creating a new Location invalidates the previously cached read."""
        list(self.Location.objects.all())

        with CaptureQueriesContext(connection) as cached_read:
            list(self.Location.objects.all())
        self.assertEqual(len(cached_read.captured_queries), 0)

        self.Location.objects.create(
            code="GA",
            name="Goa",
            short_name="GA",
            location_type=self.Location.LocationType.STATE,
            parent=self.india,
        )

        with CaptureQueriesContext(connection) as after_write:
            list(self.Location.objects.all())
        self.assertGreater(len(after_write.captured_queries), 0)

    def test_cachalot_disabled_always_hits_database(self):
        """Inside cachalot_disabled(), repeated reads always re-query the DB."""
        list(self.Location.objects.all())

        with cachalot_disabled(all_queries=True):
            with CaptureQueriesContext(connection) as second:
                list(self.Location.objects.all())
        self.assertGreater(len(second.captured_queries), 0)


class ExcludedTableCachingTests(TestCase):
    """messaging_messagetemplate is outside CACHALOT_ONLY_CACHABLE_APPS."""

    def setUp(self):
        """Create a message template outside the Phase-1 allow-list."""
        self.template = MessageTemplate.objects.create(
            message_key="WELCOME",
            message_type=MessageTemplate.MessageType.EMAIL,
            content="Welcome!",
        )

    def test_repeated_read_is_never_cached(self):
        """Reads against an excluded table always re-query the database."""
        list(MessageTemplate.objects.all())

        with CaptureQueriesContext(connection) as second:
            list(MessageTemplate.objects.all())
        self.assertGreater(len(second.captured_queries), 0)
