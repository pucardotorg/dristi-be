"""publish_notification actor tests (spec 0031 §11.4)."""

import pytest

from apps.notifications.bus import ZERO_ID, get_bus
from apps.notifications.models import Notification
from apps.notifications.tasks import publish_notification

pytestmark = pytest.mark.django_db


def _create(user, **overrides):
    """Create a row without scheduling publication (so the actor is tested alone)."""
    fields = {"recipient": user, "event_type": "CASE_FILED", "title": "Case filed"}
    fields.update(overrides)
    return Notification.objects.create(**fields)


def test_publish_sends_payload_to_recipient_stream(user, bus):
    notification = _create(user, body="b", data={"k": "v"})
    publish_notification.fn(str(notification.id))

    entries = bus.read(user.id, ZERO_ID, 0)
    assert len(entries) == 1
    _entry_id, payload = entries[0]
    assert payload["id"] == str(notification.id)
    assert payload["event_type"] == "CASE_FILED"
    assert payload["title"] == "Case filed"
    assert payload["body"] == "b"
    assert payload["data"] == {"k": "v"}
    assert payload["priority"] == "NORMAL"
    assert "created_at" in payload


def test_publish_skips_missing_notification(bus):
    # A random id that does not exist must not raise.
    publish_notification.fn("00000000-0000-0000-0000-000000000000")


def test_duplicate_invocation_publishes_twice(user, bus):
    notification = _create(user)
    publish_notification.fn(str(notification.id))
    publish_notification.fn(str(notification.id))
    entries = bus.read(user.id, ZERO_ID, 0)
    assert len(entries) == 2
    # Same notification id in both payloads; distinct stream entry ids.
    assert {p["id"] for _id, p in entries} == {str(notification.id)}
    assert len({entry_id for entry_id, _p in entries}) == 2


def test_redis_failure_propagates(user, monkeypatch):
    notification = _create(user)

    def boom(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(get_bus(), "publish", boom)
    with pytest.raises(RuntimeError):
        publish_notification.fn(str(notification.id))
