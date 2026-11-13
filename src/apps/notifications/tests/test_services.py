"""Service (notify + inbox helpers) tests (spec 0031 §11.2)."""

from unittest import mock

import pytest
from django.db import transaction
from django.test import TestCase

from apps.notifications import services
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


def test_notify_creates_one_row_and_stamps_actor(user, other_user):
    notification = services.notify(
        recipient=user,
        event_type="CASE_FILED",
        title="Case filed",
        body="Body",
        data={"case_id": "x"},
        actor=other_user,
    )
    assert Notification.objects.count() == 1
    assert notification.recipient == user
    assert notification.created_by == other_user
    assert notification.updated_by == other_user
    assert notification.data == {"case_id": "x"}


def test_notify_accepts_user_id(user):
    notification = services.notify(recipient=str(user.id), event_type="CASE_FILED", title="t")
    assert notification.recipient == user


def test_notify_rejects_missing_recipient():
    with pytest.raises(services.NotificationRecipientError):
        services.notify(recipient="00000000-0000-0000-0000-000000000000", event_type="X", title="t")


def test_notify_rejects_invalid_recipient_id():
    with pytest.raises(services.NotificationRecipientError):
        services.notify(recipient="not-a-uuid", event_type="X", title="t")


def test_notify_rejects_inactive_recipient(make_user):
    inactive = make_user(is_active=False)
    with pytest.raises(services.NotificationRecipientError):
        services.notify(recipient=inactive, event_type="X", title="t")


@pytest.mark.parametrize("event_type", ["lower", "2BAD", "", 123])
def test_notify_rejects_bad_event_type(user, event_type):
    with pytest.raises(ValueError):
        services.notify(recipient=user, event_type=event_type, title="t")


@pytest.mark.parametrize("title", ["", "   ", None])
def test_notify_rejects_blank_title(user, title):
    with pytest.raises(ValueError):
        services.notify(recipient=user, event_type="X", title=title)


def test_notify_rejects_non_object_data(user):
    with pytest.raises(ValueError):
        services.notify(recipient=user, event_type="X", title="t", data=[1, 2])


def test_notify_rejects_bad_priority(user):
    with pytest.raises(ValueError):
        services.notify(recipient=user, event_type="X", title="t", priority="URGENT")


def test_mark_read_is_idempotent(user):
    notification = services.notify(recipient=user, event_type="X", title="t")
    services.mark_read(notification, actor=user)
    first = notification.read_at
    assert first is not None
    services.mark_read(notification, actor=user)
    assert notification.read_at == first


def test_mark_all_read_and_unread_count(user, make_user):
    other = make_user()
    services.notify(recipient=user, event_type="X", title="a")
    services.notify(recipient=user, event_type="X", title="b")
    services.notify(recipient=other, event_type="X", title="c")

    assert services.unread_count(user) == 2
    assert services.mark_all_read(user, actor=user) == 2
    assert services.unread_count(user) == 0
    # The other user's row is untouched.
    assert services.unread_count(other) == 1
    # Idempotent.
    assert services.mark_all_read(user, actor=user) == 0


class NotifyCommitTests(TestCase):
    """on_commit scheduling needs TestCase.captureOnCommitCallbacks."""

    @classmethod
    def setUpTestData(cls):
        from apps.users.models import RegistrationStatus, Role, User

        cls.user = User.objects.create_user(
            mobile_number="+919000020001",
            name="Commit",
            role=Role.LITIGANT,
            registration_status=RegistrationStatus.COMPLETE,
        )

    def test_publish_scheduled_only_after_commit(self):
        with mock.patch("apps.notifications.tasks.publish_notification.send") as send:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                services.notify(recipient=self.user, event_type="X", title="t")
                # Still inside the atomic block: nothing enqueued yet.
                assert send.call_count == 0
            assert len(callbacks) == 1
        assert send.call_count == 1

    def test_rollback_creates_no_row_and_enqueues_nothing(self):
        with mock.patch("apps.notifications.tasks.publish_notification.send") as send:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    services.notify(recipient=self.user, event_type="X", title="t")
                    transaction.set_rollback(True)
        assert Notification.objects.count() == 0
        assert send.call_count == 0

    def test_broker_failure_is_swallowed(self):
        with mock.patch(
            "apps.notifications.tasks.publish_notification.send",
            side_effect=RuntimeError("broker down"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                services.notify(recipient=self.user, event_type="X", title="t")
        # The row survives even though publication failed.
        assert Notification.objects.filter(recipient=self.user).count() == 1
