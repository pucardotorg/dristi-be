"""Event bus tests (spec 0031 §11.3)."""

import pytest

from apps.notifications.bus import ZERO_ID, InMemoryNotificationBus, compare_ids

pytestmark = pytest.mark.django_db


def test_compare_ids_is_numeric_not_lexical():
    assert compare_ids("10-0", "9-0") == 1
    assert compare_ids("9-0", "10-0") == -1
    assert compare_ids("5-1", "5-1") == 0
    assert compare_ids("5-2", "5-1") == 1


def test_in_memory_publish_and_read_after_cursor():
    bus = InMemoryNotificationBus()
    id1 = bus.publish("u1", {"n": 1})
    id2 = bus.publish("u1", {"n": 2})

    # From the start: both entries.
    assert [p for _id, p in bus.read("u1", ZERO_ID, 0)] == [{"n": 1}, {"n": 2}]
    # Strictly after id1: only the second.
    assert [p for _id, p in bus.read("u1", id1, 0)] == [{"n": 2}]
    # After the last id: nothing.
    assert bus.read("u1", id2, 0) == []


def test_in_memory_first_and_last_id():
    bus = InMemoryNotificationBus()
    assert bus.first_id("u1") is None
    assert bus.last_id("u1") == ZERO_ID
    first = bus.publish("u1", {"n": 1})
    last = bus.publish("u1", {"n": 2})
    assert bus.first_id("u1") == first
    assert bus.last_id("u1") == last


def test_in_memory_streams_are_per_user():
    bus = InMemoryNotificationBus()
    bus.publish("u1", {"n": 1})
    assert bus.read("u2", ZERO_ID, 0) == []


def test_in_memory_read_blocks_until_timeout():
    bus = InMemoryNotificationBus()
    # No entries: a short blocking read returns empty rather than hanging.
    assert bus.read("u1", ZERO_ID, 10) == []


def test_in_memory_respects_maxlen(settings):
    settings.NOTIFICATIONS_STREAM_MAXLEN = 2
    bus = InMemoryNotificationBus()
    bus.publish("u1", {"n": 1})
    bus.publish("u1", {"n": 2})
    bus.publish("u1", {"n": 3})
    payloads = [p for _id, p in bus.read("u1", ZERO_ID, 0)]
    assert payloads == [{"n": 2}, {"n": 3}]
