"""Notification model tests (spec 0031 §11.1)."""

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


def _make(user, **overrides):
    fields = {"recipient": user, "event_type": "CASE_FILED", "title": "Case filed"}
    fields.update(overrides)
    return Notification.objects.create(**fields)


def test_is_read_reflects_read_at(user):
    notification = _make(user)
    assert notification.is_read is False
    notification.read_at = timezone.now()
    assert notification.is_read is True


@pytest.mark.parametrize("value", ["CASE_FILED", "PAYMENT2_RECEIVED", "A"])
def test_event_type_check_accepts_upper_snake(user, value):
    assert _make(user, event_type=value).pk is not None


@pytest.mark.parametrize("value", ["case_filed", "Case", "2CASE", "WITH SPACE", "_LEADING"])
def test_event_type_check_rejects_bad_format(user, value):
    with pytest.raises(IntegrityError):
        _make(user, event_type=value)


def test_deleting_user_cascades(user):
    _make(user)
    user.delete()
    assert Notification.objects.count() == 0


def test_ordering_is_newest_first(user):
    first = _make(user, title="first")
    second = _make(user, title="second")
    ids = list(Notification.objects.values_list("id", flat=True))
    assert ids == [second.id, first.id]


def test_str(user):
    notification = _make(user)
    assert str(notification) == f"CASE_FILED -> {user.id}"
