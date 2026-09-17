"""Tests for messaging dispatch tasks."""

from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.messaging.models import MessageLog, MessageTemplate
from apps.messaging.senders import clear_backend_cache
from apps.messaging.services import MessageTemplateNotFound
from apps.messaging.tasks import (
    enqueue_email,
    enqueue_push,
    enqueue_sms,
    get_retry_delay_ms,
    send_message,
)


class EnqueueHelperTests(TestCase):
    """Convenience enqueue helper tests."""

    def setUp(self):
        self.template = MessageTemplate.objects.create(
            message_key="CASE_FILING_SUBMITTED",
            message_type=MessageTemplate.MessageType.EMAIL.value,
            subject="Case {{ case_number }} filed",
            content="Hello {{ name }}",
            max_retries=2,
        )
        clear_backend_cache()

    def tearDown(self):
        clear_backend_cache()

    @patch("apps.messaging.tasks.send_message.send")
    def test_enqueue_email_creates_log_and_enqueues(self, mock_send):
        log = enqueue_email(
            "CASE_FILING_SUBMITTED",
            {"email": "user@example.com"},
            {"case_number": "CASE-1", "name": "Alice"},
        )
        self.assertEqual(log.status, MessageLog.Status.PENDING.value)
        self.assertEqual(log.attempt_count, 0)
        self.assertEqual(log.max_retries, 2)
        mock_send.assert_called_once_with(str(log.id))

    @patch("apps.messaging.tasks.send_message.send")
    def test_enqueue_sms_creates_log_and_enqueues(self, mock_send):
        self.template.message_type = MessageTemplate.MessageType.SMS.value
        self.template.subject = ""
        self.template.save()
        log = enqueue_sms(
            "CASE_FILING_SUBMITTED",
            {"phone_number": "+1234567890"},
            {"name": "Alice"},
        )
        self.assertEqual(log.message_type, MessageTemplate.MessageType.SMS.value)
        mock_send.assert_called_once_with(str(log.id))

    def test_enqueue_missing_template_raises(self):
        with self.assertRaises(MessageTemplateNotFound):
            enqueue_email("missing", {"email": "user@example.com"}, {})

    def test_enqueue_push_marks_log_failed_and_raises_not_implemented(self):
        MessageTemplate.objects.create(
            message_key="CASE_FILING_SUBMITTED",
            message_type=MessageTemplate.MessageType.PUSH.value,
            subject="",
            content="Push content",
        )
        with self.assertRaises(NotImplementedError):
            enqueue_push(
                "CASE_FILING_SUBMITTED",
                {"device_token": "token"},
                {"case_number": "CASE-1"},
            )
        log = MessageLog.objects.get(message_key="CASE_FILING_SUBMITTED")
        self.assertEqual(log.status, MessageLog.Status.FAILED.value)
        self.assertIn("not implemented", log.error_message.lower())
        self.assertIsNotNone(log.failed_at)

    @override_settings(MESSAGING_RETRY_DELAY_BASE=10, MESSAGING_RETRY_DELAY_MAX=50)
    def test_retry_delay_exponential_backoff(self):
        self.assertEqual(get_retry_delay_ms(1), 10000)
        self.assertEqual(get_retry_delay_ms(2), 20000)
        self.assertEqual(get_retry_delay_ms(3), 40000)
        self.assertEqual(get_retry_delay_ms(4), 50000)

    def test_retry_delay_respects_maximum(self):
        self.assertLessEqual(get_retry_delay_ms(10), 3600000)


class SendMessageTaskTests(TestCase):
    """send_message actor tests."""

    def setUp(self):
        self.template = MessageTemplate.objects.create(
            message_key="CASE_FILING_SUBMITTED",
            message_type=MessageTemplate.MessageType.EMAIL.value,
            subject="Case {{ case_number }} filed",
            content="Hello {{ name }}",
            max_retries=1,
        )
        clear_backend_cache()

    def tearDown(self):
        clear_backend_cache()

    @override_settings(
        MESSAGING_BACKENDS={"email": "apps.messaging.senders.email.SMTPEmailBackend"},
        MESSAGING_EMAIL_BACKEND="django",
        MESSAGING_EMAIL_DEFAULT_FROM="noreply@example.com",
    )
    @patch("apps.messaging.tasks.send_message.send_with_options")
    def test_send_message_marks_sent(self, mock_retry):
        log = MessageLog.objects.create(
            template=self.template,
            message_type=MessageTemplate.MessageType.EMAIL.value,
            message_key="CASE_FILING_SUBMITTED",
            recipient={"email": "user@example.com"},
            context={"case_number": "CASE-1", "name": "Alice"},
            max_retries=1,
        )
        send_message.fn(str(log.id))
        log.refresh_from_db()
        self.assertEqual(log.status, MessageLog.Status.SENT.value)
        self.assertEqual(log.attempt_count, 1)
        self.assertEqual(log.rendered_subject, "Case CASE-1 filed")
        self.assertEqual(log.rendered_content, "Hello Alice")
        self.assertIsNotNone(log.sent_at)
        mock_retry.assert_not_called()

    @override_settings(
        MESSAGING_BACKENDS={"email": "apps.messaging.senders.email.SMTPEmailBackend"},
        MESSAGING_EMAIL_BACKEND="django",
        MESSAGING_EMAIL_DEFAULT_FROM="noreply@example.com",
    )
    @patch("apps.messaging.tasks.send_message.send_with_options")
    def test_send_message_records_provider_id(self, mock_retry):
        log = MessageLog.objects.create(
            template=self.template,
            message_type=MessageTemplate.MessageType.EMAIL.value,
            message_key="CASE_FILING_SUBMITTED",
            recipient={"email": "user@example.com"},
            context={"case_number": "CASE-1", "name": "Alice"},
            max_retries=1,
        )
        with patch(
            "apps.messaging.senders.email.SMTPEmailBackend.send",
            return_value="provider-123",
        ):
            send_message.fn(str(log.id))
        log.refresh_from_db()
        self.assertEqual(log.provider_message_id, "provider-123")

    @override_settings(
        MESSAGING_BACKENDS={"email": "apps.messaging.senders.email.SMTPEmailBackend"},
        MESSAGING_EMAIL_BACKEND="django",
        MESSAGING_EMAIL_DEFAULT_FROM="noreply@example.com",
    )
    @patch("apps.messaging.tasks.send_message.send_with_options")
    def test_send_message_retries_on_failure(self, mock_retry):
        log = MessageLog.objects.create(
            template=self.template,
            message_type=MessageTemplate.MessageType.EMAIL.value,
            message_key="CASE_FILING_SUBMITTED",
            recipient={"email": "user@example.com"},
            context={"case_number": "CASE-1", "name": "Alice"},
            max_retries=1,
        )
        with patch(
            "apps.messaging.senders.email.SMTPEmailBackend.send",
            side_effect=Exception("SMTP failed"),
        ):
            send_message.fn(str(log.id))
        log.refresh_from_db()
        self.assertEqual(log.status, MessageLog.Status.PENDING.value)
        self.assertEqual(log.attempt_count, 1)
        self.assertIsNotNone(log.failed_at)
        self.assertEqual(log.error_message, "SMTP failed")
        mock_retry.assert_called_once()
        args, kwargs = mock_retry.call_args
        self.assertEqual(args, ())
        self.assertEqual(kwargs["args"], (str(log.id),))
        self.assertIn("delay", kwargs)

    @override_settings(
        MESSAGING_BACKENDS={"email": "apps.messaging.senders.email.SMTPEmailBackend"},
        MESSAGING_EMAIL_BACKEND="django",
        MESSAGING_EMAIL_DEFAULT_FROM="noreply@example.com",
    )
    @patch("apps.messaging.tasks.send_message.send_with_options")
    def test_send_message_exhausts_retries(self, mock_retry):
        log = MessageLog.objects.create(
            template=self.template,
            message_type=MessageTemplate.MessageType.EMAIL.value,
            message_key="CASE_FILING_SUBMITTED",
            recipient={"email": "user@example.com"},
            context={"case_number": "CASE-1", "name": "Alice"},
            max_retries=0,
        )
        with patch(
            "apps.messaging.senders.email.SMTPEmailBackend.send",
            side_effect=Exception("SMTP failed"),
        ):
            send_message.fn(str(log.id))
        log.refresh_from_db()
        self.assertEqual(log.status, MessageLog.Status.FAILED.value)
        self.assertEqual(log.attempt_count, 1)
        mock_retry.assert_not_called()

    @patch("apps.messaging.tasks.send_message.send_with_options")
    def test_send_message_missing_template_fails_log(self, mock_retry):
        log = MessageLog.objects.create(
            template=self.template,
            message_type=MessageTemplate.MessageType.EMAIL.value,
            message_key="MISSING_KEY",
            recipient={"email": "user@example.com"},
            context={},
            max_retries=0,
        )
        send_message.fn(str(log.id))
        log.refresh_from_db()
        self.assertEqual(log.status, MessageLog.Status.FAILED.value)
        self.assertIn("No active template", log.error_message)
        mock_retry.assert_not_called()
