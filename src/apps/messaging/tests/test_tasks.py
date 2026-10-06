"""Tests for messaging dispatch tasks."""

from unittest.mock import patch

from django.conf import settings
from django.db import transaction
from django.test import TestCase, override_settings

from apps.messaging.models import MessageLog, MessageTemplate
from apps.messaging.senders import clear_backend_cache
from apps.messaging.services import (
    MessagePermanentError,
    MessageSendError,
    MessageTemplateNotFound,
    RecipientFilteredError,
)
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
        with self.captureOnCommitCallbacks(execute=True):
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
        with self.captureOnCommitCallbacks(execute=True):
            log = enqueue_sms(
                "CASE_FILING_SUBMITTED",
                {"phone_number": "+1234567890"},
                {"name": "Alice"},
            )
        self.assertEqual(log.message_type, MessageTemplate.MessageType.SMS.value)
        mock_send.assert_called_once_with(str(log.id))

    @patch("apps.messaging.tasks.send_message.send")
    def test_enqueue_publishes_only_after_commit(self, mock_send):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            log = enqueue_email(
                "CASE_FILING_SUBMITTED",
                {"email": "user@example.com"},
                {"case_number": "CASE-1", "name": "Alice"},
            )
            mock_send.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        mock_send.assert_called_once_with(str(log.id))

    @patch("apps.messaging.tasks.send_message.send")
    def test_enqueue_never_publishes_when_transaction_rolls_back(self, mock_send):
        with (
            self.captureOnCommitCallbacks(execute=True) as callbacks,
            self.assertNoLogs("apps.messaging.tasks", level="INFO"),
        ):
            try:
                with transaction.atomic():
                    enqueue_email(
                        "CASE_FILING_SUBMITTED",
                        {"email": "user@example.com"},
                        {"case_number": "CASE-1", "name": "Alice"},
                    )
                    raise RuntimeError("caller failed")
            except RuntimeError:
                pass
        self.assertEqual(callbacks, [])
        mock_send.assert_not_called()
        self.assertFalse(MessageLog.objects.exists())

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
    def test_send_message_warns_when_log_is_missing(self):
        missing_id = "00000000-0000-0000-0000-000000000000"
        with self.assertLogs("apps.messaging.tasks", level="WARNING") as logs:
            send_message.fn(missing_id)
        self.assertIn(f"event=MISSING message_id={missing_id}", logs.output[0])

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


class FailureClassificationTests(TestCase):
    """Filtered / permanent / transient outcome classification."""

    def setUp(self):
        self.template = MessageTemplate.objects.create(
            message_key="GATEWAY_CLASSIFICATION_SMS",
            message_type=MessageTemplate.MessageType.SMS.value,
            subject="",
            content="Hello {{ name }}",
            max_retries=2,
        )
        clear_backend_cache()

    def tearDown(self):
        clear_backend_cache()

    def _log(self, max_retries=2):
        return MessageLog.objects.create(
            template=self.template,
            message_type=MessageTemplate.MessageType.SMS.value,
            message_key="GATEWAY_CLASSIFICATION_SMS",
            recipient={"phone_number": "9876512345"},
            context={"name": "Alice"},
            max_retries=max_retries,
        )

    def _send(self, exc):
        with patch(
            "apps.messaging.senders.sms.DummySMSBackend.send",
            side_effect=exc,
        ):
            log = self._log()
            send_message.fn(str(log.id))
        log.refresh_from_db()
        return log

    @override_settings(MESSAGING_BACKENDS={"sms": "apps.messaging.senders.sms.DummySMSBackend"})
    @patch("apps.messaging.tasks.send_message.send_with_options")
    def test_filtered_recipient_is_not_retried(self, mock_retry):
        log = self._send(RecipientFilteredError("suppressed", reason="blacklist"))
        self.assertEqual(log.status, MessageLog.Status.FILTERED.value)
        self.assertEqual(log.provider_metadata.get("failure_code"), "blacklist")
        self.assertIsNone(log.failed_at)
        mock_retry.assert_not_called()

    @override_settings(MESSAGING_BACKENDS={"sms": "apps.messaging.senders.sms.DummySMSBackend"})
    @patch("apps.messaging.tasks.send_message.send_with_options")
    def test_permanent_error_fails_without_retry(self, mock_retry):
        log = self._send(
            MessagePermanentError("bad config", code="INVALID_CONFIGURATION", gateway_status="")
        )
        self.assertEqual(log.status, MessageLog.Status.FAILED.value)
        self.assertEqual(log.provider_metadata.get("failure_code"), "INVALID_CONFIGURATION")
        self.assertIsNotNone(log.failed_at)
        mock_retry.assert_not_called()

    @override_settings(MESSAGING_BACKENDS={"sms": "apps.messaging.senders.sms.DummySMSBackend"})
    @patch("apps.messaging.tasks.send_message.send_with_options")
    def test_transient_error_is_retried_and_records_gateway_status(self, mock_retry):
        log = self._send(
            MessageSendError("gateway busy", code="GATEWAY_ERROR", gateway_status="503")
        )
        self.assertEqual(log.status, MessageLog.Status.PENDING.value)
        self.assertEqual(log.provider_metadata.get("failure_code"), "GATEWAY_ERROR")
        self.assertEqual(log.provider_metadata.get("gateway_status"), "503")
        mock_retry.assert_called_once()

    @override_settings(MESSAGING_BACKENDS={"sms": "apps.messaging.senders.sms.DummySMSBackend"})
    @patch("apps.messaging.tasks.send_message.send_with_options")
    def test_filtered_log_is_skipped_on_reentry(self, mock_retry):
        log = self._send(RecipientFilteredError("suppressed", reason="disabled"))
        send_message.fn(str(log.id))
        log.refresh_from_db()
        self.assertEqual(log.attempt_count, 1)
        mock_retry.assert_not_called()

    @override_settings(MESSAGING_BACKENDS={"sms": "apps.messaging.senders.sms.DummySMSBackend"})
    @patch("apps.messaging.tasks.send_message.send_with_options")
    def test_provider_name_is_recorded_on_success(self, mock_retry):
        log = self._log()
        with (
            patch(
                "apps.messaging.senders.sms.DummySMSBackend.send",
                return_value="provider-1",
            ),
            patch(
                "apps.messaging.senders.sms.DummySMSBackend.provider_name",
                "dummy",
            ),
        ):
            send_message.fn(str(log.id))
        log.refresh_from_db()
        self.assertEqual(log.status, MessageLog.Status.SENT.value)
        self.assertEqual(log.provider, "dummy")
        self.assertEqual(log.provider_message_id, "provider-1")


class CorrelationIdTests(TestCase):
    """correlation_id propagation through enqueue helpers."""

    def setUp(self):
        self.template = MessageTemplate.objects.create(
            message_key="CORRELATION_TEST_SMS",
            message_type=MessageTemplate.MessageType.SMS.value,
            subject="",
            content="Hello",
        )

    @patch("apps.messaging.tasks.send_message.send")
    def test_defaults_to_the_log_id(self, mock_send):
        log = enqueue_sms("CORRELATION_TEST_SMS", {"phone_number": "9876512345"}, {})
        self.assertEqual(log.correlation_id, str(log.id))

    @patch("apps.messaging.tasks.send_message.send")
    def test_caller_supplied_value_is_kept(self, mock_send):
        log = enqueue_sms(
            "CORRELATION_TEST_SMS",
            {"phone_number": "9876512345"},
            {},
            correlation_id="corr-1",
        )
        self.assertEqual(log.correlation_id, "corr-1")


class ActorConfigurationTests(TestCase):
    """The actor must carry an explicit time limit."""

    def test_time_limit_is_set_explicitly(self):
        self.assertEqual(
            send_message.options["time_limit"],
            settings.MESSAGING_TASK_TIME_LIMIT,
        )
