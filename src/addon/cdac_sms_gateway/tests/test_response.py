"""Tests for gateway response validation and classification."""

from dataclasses import replace

from django.test import SimpleTestCase

from addon.cdac_sms_gateway import constants
from addon.cdac_sms_gateway.config import CDACConfig
from addon.cdac_sms_gateway.response import classify, parse_message_id, redact
from apps.messaging.services import MessagePermanentError, MessageSendError

BASE = CDACConfig(
    url="https://gateway.example.com/esms",
    username="user",
    password="secret",
    sender_id="DRISTI",
    secure_key="key",
    print_response=False,
)

SUCCESS_BODY = "402,MsgID = 1234567890msdgsms"


class ParseMessageIdTests(SimpleTestCase):
    """Message-ID parsing tests."""

    def test_parses_standard_body(self):
        self.assertEqual(parse_message_id(SUCCESS_BODY), "1234567890")

    def test_tolerates_missing_spaces(self):
        self.assertEqual(parse_message_id("402,MsgID=ABC123msdgsms"), "ABC123")

    def test_returns_none_for_unparsable_body(self):
        self.assertIsNone(parse_message_id("402,Message submitted"))

    def test_returns_none_for_empty_body(self):
        self.assertIsNone(parse_message_id(""))


class RedactTests(SimpleTestCase):
    """Body redaction tests."""

    def test_removes_password_and_key_values(self):
        body = "username=user&password=abc123&key=deadbeef&content=hi"
        redacted = redact(body)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("deadbeef", redacted)
        self.assertIn("password=***", redacted)
        self.assertIn("key=***", redacted)
        self.assertIn("username=user", redacted)


class ClassifyTests(SimpleTestCase):
    """Validation-order and classification tests."""

    def test_success_returns_provider_message_id(self):
        self.assertEqual(classify(200, SUCCESS_BODY, BASE), "1234567890")

    def test_success_without_parsable_id_is_still_success(self):
        self.assertIsNone(classify(200, "402,Message submitted", BASE))

    def test_status_outside_success_codes_is_transient(self):
        with self.assertRaises(MessageSendError) as ctx:
            classify(503, SUCCESS_BODY, BASE)
        self.assertNotIsInstance(ctx.exception, MessagePermanentError)
        self.assertEqual(ctx.exception.code, constants.GATEWAY_ERROR)
        self.assertEqual(ctx.exception.gateway_status, "503")

    def test_error_codes_are_transient(self):
        cfg = replace(BASE, success_codes=(), error_codes=(500,))
        with self.assertRaises(MessageSendError) as ctx:
            classify(500, SUCCESS_BODY, cfg)
        self.assertNotIsInstance(ctx.exception, MessagePermanentError)
        self.assertEqual(ctx.exception.code, constants.GATEWAY_ERROR)

    def test_empty_success_codes_allow_any_status(self):
        cfg = replace(BASE, success_codes=(), error_codes=())
        self.assertEqual(classify(418, SUCCESS_BODY, cfg), "1234567890")

    def test_substring_validation_passes(self):
        cfg = replace(BASE, verify_response=True, verify_response_contains="MsgID")
        self.assertEqual(classify(200, SUCCESS_BODY, cfg), "1234567890")

    def test_substring_validation_failure_is_transient(self):
        cfg = replace(BASE, verify_response=True, verify_response_contains="MsgID")
        with self.assertRaises(MessageSendError) as ctx:
            classify(200, "error: invalid request", cfg)
        self.assertNotIsInstance(ctx.exception, MessagePermanentError)
        self.assertEqual(ctx.exception.code, constants.RESPONSE_VALIDATION_FAILED)

    def test_body_validation_runs_before_status_validation(self):
        cfg = replace(BASE, verify_response=True, verify_response_contains="MsgID")
        with self.assertRaises(MessageSendError) as ctx:
            classify(503, "gateway busy", cfg)
        self.assertEqual(ctx.exception.code, constants.RESPONSE_VALIDATION_FAILED)

    def test_malformed_body_with_good_status_is_success(self):
        self.assertIsNone(classify(200, "<html>unexpected</html>", BASE))

    def test_print_response_logs_redacted_body(self):
        cfg = replace(BASE, print_response=True)
        with self.assertLogs(constants.LOGGER_NAME, level="INFO") as captured:
            classify(
                200,
                "password=abc123&key=deadbeef&MsgID = 9msdgsms",
                cfg,
                {"message_id": "mid-1", "correlation_id": "cid-1"},
            )
        line = captured.output[0]
        self.assertIn("event=GATEWAY_RESPONSE", line)
        self.assertIn("message_id=mid-1", line)
        self.assertIn("correlation_id=cid-1", line)
        self.assertIn("gateway_status=200", line)
        self.assertNotIn("abc123", line)
        self.assertNotIn("deadbeef", line)

    def test_print_response_disabled_logs_nothing(self):
        with self.assertNoLogs(constants.LOGGER_NAME, level="INFO"):
            classify(200, SUCCESS_BODY, BASE)
