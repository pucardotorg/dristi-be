"""A messaging failure never fails the hearing change (spec 0023 #11.1)."""

import logging
import uuid

import pytest

from apps.cases.selectors import Contact
from apps.hearings.enums import HearingStatus
from apps.hearings.services import listing, notifications
from apps.messaging.models import MessageLog
from apps.messaging.services import MessageTemplateNotFound

from .factories import MON, hold

pytestmark = pytest.mark.django_db


def confirm_and_notify(case, capture):
    order = uuid.uuid4()
    hold(case, MON, order_id=order)
    with capture(execute=True):
        hearing = listing.confirm(order_id=order)
    hearing.refresh_from_db()
    return hearing


def sent(case):
    return MessageLog.objects.filter(
        correlation_id=f"hearing:{case.pk}", message_key=notifications.HEARING_SCHEDULED
    )


def contact(phone="", email=""):
    return Contact(name="Party", phone=phone, email=email, side="COMPLAINANT", kind="COMPLAINANT")


def test_contacts_unavailable(case, monkeypatch, caplog, django_capture_on_commit_callbacks):
    def boom(case_id):
        raise RuntimeError("cases down")

    monkeypatch.setattr(notifications, "get_case_contacts", boom)
    with caplog.at_level(logging.ERROR, logger=notifications.__name__):
        hearing = confirm_and_notify(case, django_capture_on_commit_callbacks)
    assert hearing.status == HearingStatus.SCHEDULED
    assert "HEARING_NOTIFY_FAILED" in caplog.text
    assert not sent(case).exists()


def test_one_failed_message_does_not_stop_the_rest(
    case, monkeypatch, caplog, django_capture_on_commit_callbacks
):
    real_sms = notifications.enqueue_sms

    def flaky_sms(key, recipient, context, **kwargs):
        if recipient["phone_number"] == "+919800000001":
            raise RuntimeError("gateway down")
        return real_sms(key, recipient, context, **kwargs)

    monkeypatch.setattr(notifications, "enqueue_sms", flaky_sms)
    monkeypatch.setattr(
        notifications,
        "get_case_contacts",
        lambda case_id: [contact(phone="+919800000001"), contact(phone="+919800000002")],
    )
    with caplog.at_level(logging.ERROR, logger=notifications.__name__):
        hearing = confirm_and_notify(case, django_capture_on_commit_callbacks)
    assert hearing.status == HearingStatus.SCHEDULED
    assert "HEARING_NOTIFY_FAILED" in caplog.text
    assert sent(case).count() == 1


def test_missing_template_is_not_an_error(
    case, monkeypatch, caplog, django_capture_on_commit_callbacks
):
    def no_template(*args, **kwargs):
        raise MessageTemplateNotFound("HEARING_SCHEDULED")

    monkeypatch.setattr(notifications, "enqueue_sms", no_template)
    monkeypatch.setattr(notifications, "enqueue_email", no_template)
    with caplog.at_level(logging.DEBUG, logger=notifications.__name__):
        hearing = confirm_and_notify(case, django_capture_on_commit_callbacks)
    assert hearing.status == HearingStatus.SCHEDULED
    assert "HEARING_NOTIFY_FAILED" not in caplog.text
    assert "HEARING_NOTIFY_NO_RECIPIENTS" in caplog.text


def test_nobody_reachable_is_logged(case, monkeypatch, caplog, django_capture_on_commit_callbacks):
    monkeypatch.setattr(notifications, "get_case_contacts", lambda case_id: [contact()])
    with caplog.at_level(logging.WARNING, logger=notifications.__name__):
        confirm_and_notify(case, django_capture_on_commit_callbacks)
    assert "HEARING_NOTIFY_NO_RECIPIENTS" in caplog.text
    assert not sent(case).exists()
