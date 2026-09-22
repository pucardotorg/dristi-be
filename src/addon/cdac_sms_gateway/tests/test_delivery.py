"""End-to-end delivery tests: enqueue_sms -> worker -> addon -> MessageLog."""

import hashlib
from unittest.mock import patch

import requests
from django.test import TestCase, override_settings

from addon.cdac_sms_gateway.config import reset_config_cache
from apps.messaging.models import MessageLog, MessageTemplate
from apps.messaging.senders import clear_backend_cache
from apps.messaging.tasks import enqueue_sms, send_message

GATEWAY = {
    "MESSAGING_BACKENDS": {
        "email": "apps.messaging.senders.email.SMTPEmailBackend",
        "sms": "addon.cdac_sms_gateway.backend.CDACSMSBackend",
    },
    "CDAC_SMS_URL": "https://gateway.example.com/esms/sendsmsrequestDLT",
    "CDAC_SMS_USERNAME": "user",
    "CDAC_SMS_PASSWORD": "secret",
    "CDAC_SMS_SENDER_ID": "DRISTI",
    "CDAC_SMS_SECURE_KEY": "secure-key",
    "CDAC_SMS_MOBILE_PREFIX": "91",
    "CDAC_SMS_TEMPLATE_ID": "dlt-template-1",
    "CDAC_SMS_PRINT_RESPONSE": False,
}

SUCCESS_BODY = "402,MsgID = 1234567890msdgsms"


@override_settings(**GATEWAY)
class DeliveryTests(TestCase):
    """Stub-broker delivery against a mocked CDAC endpoint."""

    def setUp(self):
        # ACCOUNT_LOGIN_OTP_SMS is seeded by migration 0005; use a dedicated key.
        self.template = MessageTemplate.objects.create(
            message_key="GATEWAY_TEST_OTP_SMS",
            message_type=MessageTemplate.MessageType.SMS.value,
            subject="",
            content="Use OTP {{ otp }} to log in",
            category=MessageTemplate.Category.OTP.value,
            max_retries=1,
        )
        clear_backend_cache()
        reset_config_cache()
        self.addCleanup(clear_backend_cache)
        self.addCleanup(reset_config_cache)

        patcher = patch("addon.cdac_sms_gateway.client.requests.Session.post")
        self.post = patcher.start()
        self.addCleanup(patcher.stop)
        self.post.return_value.status_code = 200
        self.post.return_value.text = SUCCESS_BODY

        enqueue_patcher = patch("apps.messaging.tasks.send_message.send")
        self.enqueue = enqueue_patcher.start()
        self.addCleanup(enqueue_patcher.stop)

        retry_patcher = patch("apps.messaging.tasks.send_message.send_with_options")
        self.retry = retry_patcher.start()
        self.addCleanup(retry_patcher.stop)

    def enqueue_and_run(self, correlation_id=""):
        """Enqueue an SMS and run the worker body once."""

        log = enqueue_sms(
            "GATEWAY_TEST_OTP_SMS",
            {"phone_number": "9876512345"},
            {"otp": "1234"},
            correlation_id=correlation_id,
        )
        send_message.fn(str(log.id))
        log.refresh_from_db()
        return log

    def test_successful_delivery_records_sent(self):
        log = self.enqueue_and_run()
        self.assertEqual(log.status, MessageLog.Status.SENT.value)
        self.assertEqual(log.provider_message_id, "1234567890")
        self.assertEqual(log.provider, "cdac")
        self.assertEqual(log.rendered_content, "Use OTP 1234 to log in")
        self.assertIsNotNone(log.sent_at)
        self.retry.assert_not_called()

    def test_gateway_receives_the_expected_request(self):
        self.enqueue_and_run()
        self.assertEqual(self.post.call_args.args[0], GATEWAY["CDAC_SMS_URL"])
        self.assertEqual(
            self.post.call_args.kwargs["headers"]["Content-Type"],
            "application/x-www-form-urlencoded",
        )
        form = self.post.call_args.kwargs["data"]
        self.assertEqual(form["username"], "user")
        self.assertEqual(form["password"], hashlib.sha1(b"secret").hexdigest())
        self.assertEqual(form["senderid"], "DRISTI")
        self.assertEqual(form["content"], "Use OTP 1234 to log in")
        self.assertEqual(form["smsservicetype"], "otpmsg")
        self.assertEqual(form["mobileno"], "919876512345")
        self.assertEqual(form["templateid"], "dlt-template-1")
        self.assertEqual(
            form["key"],
            hashlib.sha512(b"userDRISTIUse OTP 1234 to log insecure-key").hexdigest(),
        )

    def test_unicode_body_is_entity_encoded_end_to_end(self):
        self.template.content = "नमस्ते {{ otp }}"
        self.template.category = MessageTemplate.Category.NOTIFICATION.value
        self.template.save()
        self.enqueue_and_run()
        form = self.post.call_args.kwargs["data"]
        self.assertEqual(form["smsservicetype"], "unicodemsg")
        self.assertTrue(form["content"].startswith("&#2344;&#2350;"))
        self.assertNotIn("नमस्ते", form["content"])

    def test_transient_failure_reenqueues_then_fails(self):
        self.post.return_value.status_code = 503
        log = self.enqueue_and_run()
        self.assertEqual(log.status, MessageLog.Status.PENDING.value)
        self.assertEqual(log.attempt_count, 1)
        self.assertEqual(log.failure_code, "GATEWAY_ERROR")
        self.assertEqual(log.gateway_status, "503")
        self.retry.assert_called_once()

        send_message.fn(str(log.id))
        log.refresh_from_db()
        self.assertEqual(log.status, MessageLog.Status.FAILED.value)
        self.assertEqual(log.attempt_count, 2)
        self.assertEqual(self.retry.call_count, 1)

    def test_timeout_is_retried(self):
        self.post.side_effect = requests.Timeout("timed out")
        log = self.enqueue_and_run()
        self.assertEqual(log.status, MessageLog.Status.PENDING.value)
        self.assertEqual(log.failure_code, "GATEWAY_TIMEOUT")
        self.retry.assert_called_once()

    def test_permanent_failure_does_not_reenqueue(self):
        self.template.category = "MARKETING"
        self.template.save(update_fields=["category"])
        log = self.enqueue_and_run()
        self.assertEqual(log.status, MessageLog.Status.FAILED.value)
        self.assertEqual(log.failure_code, "UNSUPPORTED_CATEGORY")
        self.retry.assert_not_called()
        self.post.assert_not_called()

    @override_settings(**{**GATEWAY, "CDAC_SMS_ENABLED": False})
    def test_disabled_gateway_marks_filtered_without_calling_it(self):
        log = self.enqueue_and_run()
        self.assertEqual(log.status, MessageLog.Status.FILTERED.value)
        self.assertEqual(log.failure_code, "disabled")
        self.assertIsNone(log.failed_at)
        self.retry.assert_not_called()
        self.post.assert_not_called()

    @override_settings(**{**GATEWAY, "CDAC_SMS_WHITELIST_NUMBERS": ["91XXXXXXXXX"]})
    def test_filtered_recipient_is_not_retried(self):
        log = self.enqueue_and_run()
        self.assertEqual(log.status, MessageLog.Status.FILTERED.value)
        self.assertEqual(log.failure_code, "whitelist")
        self.retry.assert_not_called()

    def test_filtered_log_is_not_reattempted(self):
        with override_settings(**{**GATEWAY, "CDAC_SMS_ENABLED": False}):
            reset_config_cache()
            log = self.enqueue_and_run()
        reset_config_cache()
        send_message.fn(str(log.id))
        log.refresh_from_db()
        self.assertEqual(log.status, MessageLog.Status.FILTERED.value)
        self.assertEqual(log.attempt_count, 1)
        self.post.assert_not_called()

    def test_correlation_id_defaults_to_the_log_id(self):
        log = self.enqueue_and_run()
        self.assertEqual(log.correlation_id, str(log.id))

    def test_correlation_id_is_preserved_across_attempts(self):
        self.post.return_value.status_code = 503
        log = self.enqueue_and_run(correlation_id="corr-42")
        self.assertEqual(log.correlation_id, "corr-42")
        send_message.fn(str(log.id))
        log.refresh_from_db()
        self.assertEqual(log.correlation_id, "corr-42")

    def test_lifecycle_events_are_logged_with_both_identifiers(self):
        with self.assertLogs("apps.messaging", level="INFO") as messaging_logs:
            log = self.enqueue_and_run(correlation_id="corr-7")
        blob = "\n".join(messaging_logs.output)
        self.assertIn("event=ENQUEUED", blob)
        self.assertIn("event=SENT", blob)
        self.assertIn(f"message_id={log.id}", blob)
        self.assertIn("correlation_id=corr-7", blob)

    @override_settings(**{**GATEWAY, "CDAC_SMS_PRINT_RESPONSE": True})
    def test_gateway_events_are_logged_with_both_identifiers(self):
        with self.assertLogs("addon.cdac_sms_gateway", level="INFO") as gateway_logs:
            log = self.enqueue_and_run(correlation_id="corr-8")
        blob = "\n".join(gateway_logs.output)
        self.assertIn("event=GATEWAY_REQUEST", blob)
        self.assertIn("event=GATEWAY_RESPONSE", blob)
        self.assertIn(f"message_id={log.id}", blob)
        self.assertIn("correlation_id=corr-8", blob)
        self.assertNotIn("secure-key", blob)

    def test_retrying_event_is_logged(self):
        self.post.return_value.status_code = 503
        with self.assertLogs("apps.messaging", level="INFO") as messaging_logs:
            self.enqueue_and_run()
        self.assertIn("event=RETRYING", "\n".join(messaging_logs.output))

    def test_actor_time_limit_exceeds_the_gateway_timeout(self):
        from django.conf import settings

        self.assertGreater(
            send_message.options["time_limit"],
            settings.CDAC_SMS_TIMEOUT * 1000,
        )
