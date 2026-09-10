"""Tests for messaging senders and backends."""

from unittest.mock import patch

import requests
from django.core import mail
from django.test import TestCase, override_settings

from apps.messaging.senders import clear_backend_cache, get_backend
from apps.messaging.senders.push import PushSender
from apps.messaging.services import (
    MessageBackendNotConfigured,
    MessageSendError,
    RenderedMessage,
)


class SenderRegistryTests(TestCase):
    """Sender registry tests."""

    def tearDown(self):
        clear_backend_cache()

    def test_missing_backend_raises_on_send(self):
        sender = get_backend("email")
        with self.assertRaises(MessageBackendNotConfigured):
            sender.send(
                RenderedMessage(
                    message_type="email",
                    recipient={"email": "user@example.com"},
                    subject="Test",
                    body="Body",
                )
            )

    def test_unknown_channel_raises(self):
        with self.assertRaises(MessageBackendNotConfigured):
            get_backend("unknown")

    def test_push_sender_not_implemented(self):
        sender = get_backend("push")
        self.assertIsInstance(sender, PushSender)
        with self.assertRaises(NotImplementedError):
            sender.send(
                RenderedMessage(
                    message_type="push",
                    recipient={"device_token": "token"},
                    subject="Test",
                    body="Body",
                )
            )

    @override_settings(
        MESSAGING_BACKENDS={"email": "apps.messaging.senders.email.SMTPEmailBackend"}
    )
    def test_backend_must_match_channel(self):
        sender = get_backend("email")
        with self.assertRaises(MessageSendError):
            sender.send(
                RenderedMessage(
                    message_type="sms",
                    recipient={"phone_number": "+1234567890"},
                    subject="Test",
                    body="Body",
                )
            )


class DummySMSBackendTests(TestCase):
    """Dummy SMS backend tests."""

    def setUp(self):
        clear_backend_cache()

    def tearDown(self):
        clear_backend_cache()

    @override_settings(
        MESSAGING_BACKENDS={
            "sms": "apps.messaging.senders.sms.DummySMSBackend"
        },
        MESSAGING_DUMMY_SMS_ENDPOINT="https://example.com/sms",
    )
    @patch("apps.messaging.senders.sms.requests.post")
    def test_post_payload_and_return_provider_id(self, mock_post):
        mock_post.return_value.raise_for_status.return_value = None
        sender = get_backend("sms")
        provider_id = sender.send(
            RenderedMessage(
                message_type="sms",
                recipient={"phone_number": "+1234567890"},
                subject="",
                body="Hello",
                message_key="case_filing_submitted",
            )
        )
        self.assertTrue(provider_id)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["phone_number"], "+1234567890")
        self.assertEqual(payload["message"], "Hello")
        self.assertEqual(payload["message_key"], "case_filing_submitted")
        self.assertEqual(payload["provider_message_id"], provider_id)

    @override_settings(
        MESSAGING_BACKENDS={
            "sms": "apps.messaging.senders.sms.DummySMSBackend"
        },
        MESSAGING_DUMMY_SMS_ENDPOINT="https://example.com/sms",
    )
    def test_missing_phone_number_raises(self):
        sender = get_backend("sms")
        with self.assertRaises(MessageSendError):
            sender.send(
                RenderedMessage(
                    message_type="sms",
                    recipient={},
                    subject="",
                    body="Hello",
                )
            )

    @override_settings(MESSAGING_BACKENDS={"sms": "apps.messaging.senders.sms.DummySMSBackend"})
    def test_missing_endpoint_raises(self):
        sender = get_backend("sms")
        with self.assertRaises(MessageBackendNotConfigured):
            sender.send(
                RenderedMessage(
                    message_type="sms",
                    recipient={"phone_number": "+1234567890"},
                    subject="",
                    body="Hello",
                )
            )

    @override_settings(
        MESSAGING_BACKENDS={
            "sms": "apps.messaging.senders.sms.DummySMSBackend"
        },
        MESSAGING_DUMMY_SMS_ENDPOINT="https://example.com/sms",
    )
    @patch("apps.messaging.senders.sms.requests.post")
    def test_non_2xx_raises(self, mock_post):
        mock_post.return_value.raise_for_status.side_effect = requests.HTTPError("500")
        sender = get_backend("sms")
        with self.assertRaises(MessageSendError):
            sender.send(
                RenderedMessage(
                    message_type="sms",
                    recipient={"phone_number": "+1234567890"},
                    subject="",
                    body="Hello",
                )
            )


class SMTPEmailBackendTests(TestCase):
    """SMTP email backend tests."""

    def setUp(self):
        clear_backend_cache()

    def tearDown(self):
        clear_backend_cache()

    @override_settings(
        MESSAGING_BACKENDS={
            "email": "apps.messaging.senders.email.SMTPEmailBackend"
        },
        MESSAGING_EMAIL_BACKEND="django",
        MESSAGING_EMAIL_DEFAULT_FROM="noreply@example.com",
    )
    def test_send_via_django_backend(self):
        sender = get_backend("email")
        sender.send(
            RenderedMessage(
                message_type="email",
                recipient={"email": "user@example.com"},
                subject="Test subject",
                body="Test body",
            )
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["user@example.com"])
        self.assertEqual(mail.outbox[0].subject, "Test subject")

    @override_settings(
        MESSAGING_BACKENDS={
            "email": "apps.messaging.senders.email.SMTPEmailBackend"
        },
        MESSAGING_EMAIL_BACKEND="django",
        MESSAGING_EMAIL_DEFAULT_FROM="noreply@example.com",
    )
    def test_missing_email_raises(self):
        sender = get_backend("email")
        with self.assertRaises(MessageSendError):
            sender.send(
                RenderedMessage(
                    message_type="email",
                    recipient={},
                    subject="Test",
                    body="Body",
                )
            )

    @override_settings(
        MESSAGING_BACKENDS={
            "email": "apps.messaging.senders.email.SMTPEmailBackend"
        },
        MESSAGING_EMAIL_BACKEND="django",
        MESSAGING_EMAIL_DEFAULT_FROM="noreply@example.com",
    )
    def test_html_content_type(self):
        sender = get_backend("email")
        sender.send(
            RenderedMessage(
                message_type="email",
                recipient={"email": "user@example.com"},
                subject="Test",
                body="<p>Body</p>",
                content_type="html",
            )
        )
        self.assertEqual(mail.outbox[0].content_subtype, "html")
