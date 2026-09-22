"""Tests for the CDAC backend: form fields, dispatch mapping, failures."""

import hashlib
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from addon.cdac_sms_gateway import constants
from addon.cdac_sms_gateway.backend import CDACSMSBackend
from addon.cdac_sms_gateway.client import TLSv12Adapter, mask_form
from addon.cdac_sms_gateway.config import reset_config_cache
from apps.messaging.services import (
    MessagePermanentError,
    MessageSendError,
    RecipientFilteredError,
    RenderedMessage,
)

GATEWAY_SETTINGS = {
    "CDAC_SMS_URL": "https://gateway.example.com/esms/sendsmsrequestDLT",
    "CDAC_SMS_USERNAME": "user",
    "CDAC_SMS_PASSWORD": "secret",
    "CDAC_SMS_SENDER_ID": "DRISTI",
    "CDAC_SMS_SECURE_KEY": "secure-key",
    "CDAC_SMS_MOBILE_PREFIX": "91",
    "CDAC_SMS_PRINT_RESPONSE": False,
}

SUCCESS_BODY = "402,MsgID = 1234567890msdgsms"


def rendered(body="Your OTP is 1234", category="OTP", **kwargs):
    """Build a RenderedMessage for the SMS channel."""

    defaults = {
        "message_type": "sms",
        "recipient": {"phone_number": "9876512345"},
        "subject": "",
        "body": body,
        "message_key": "ACCOUNT_LOGIN_OTP_SMS",
        "category": category,
        "message_id": "mid-1",
        "correlation_id": "cid-1",
        "attempt": 1,
    }
    defaults.update(kwargs)
    return RenderedMessage(**defaults)


class BackendTestCase(SimpleTestCase):
    """Shared setup: a mocked gateway POST and a clean config cache."""

    def setUp(self):
        reset_config_cache()
        patcher = patch("addon.cdac_sms_gateway.client.requests.Session.post")
        self.post = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(reset_config_cache)
        self.post.return_value.status_code = 200
        self.post.return_value.text = SUCCESS_BODY

    def sent_form(self):
        """Return the form dict posted to the gateway."""

        return self.post.call_args.kwargs["data"]


@override_settings(**GATEWAY_SETTINGS)
class FormBuildingTests(BackendTestCase):
    """Wire-format tests (§5.2, §5.4, §5.8)."""

    def test_returns_parsed_provider_message_id(self):
        self.assertEqual(CDACSMSBackend().send(rendered()), "1234567890")

    def test_posts_urlencoded_form_to_configured_url(self):
        CDACSMSBackend().send(rendered())
        self.assertEqual(self.post.call_args.args[0], GATEWAY_SETTINGS["CDAC_SMS_URL"])
        self.assertEqual(
            self.post.call_args.kwargs["headers"]["Content-Type"],
            "application/x-www-form-urlencoded",
        )

    def test_exact_form_fields(self):
        CDACSMSBackend().send(rendered())
        self.assertEqual(
            set(self.sent_form()),
            {"username", "password", "senderid", "content", "smsservicetype", "mobileno", "key"},
        )

    def test_password_is_sha1_over_iso_8859_1(self):
        CDACSMSBackend().send(rendered())
        self.assertEqual(
            self.sent_form()["password"],
            hashlib.sha1(b"secret").hexdigest(),
        )

    def test_key_is_sha512_over_final_content(self):
        CDACSMSBackend().send(rendered())
        form = self.sent_form()
        expected = hashlib.sha512(f"userDRISTI{form['content']}secure-key".encode()).hexdigest()
        self.assertEqual(form["key"], expected)

    def test_mobile_prefix_is_applied(self):
        CDACSMSBackend().send(rendered())
        self.assertEqual(self.sent_form()["mobileno"], "919876512345")

    @override_settings(**{**GATEWAY_SETTINGS, "CDAC_SMS_MOBILE_PREFIX": ""})
    def test_no_prefix_configured(self):
        CDACSMSBackend().send(rendered())
        self.assertEqual(self.sent_form()["mobileno"], "9876512345")

    def test_plaintext_secrets_are_never_sent(self):
        CDACSMSBackend().send(rendered())
        self.assertNotIn("secret", self.sent_form().values())
        self.assertNotIn("secure-key", self.sent_form().values())

    def test_timeout_and_verification_are_passed_through(self):
        CDACSMSBackend().send(rendered())
        self.assertEqual(self.post.call_args.kwargs["timeout"], 30)
        self.assertTrue(self.post.call_args.kwargs["verify"])


@override_settings(**GATEWAY_SETTINGS)
class DispatchMappingTests(BackendTestCase):
    """Service-type mapping tests (§5.3, §5.6)."""

    def test_otp_text_uses_otpmsg(self):
        CDACSMSBackend().send(rendered(category="OTP"))
        self.assertEqual(self.sent_form()["smsservicetype"], "otpmsg")

    def test_otp_unicode_still_uses_otpmsg(self):
        CDACSMSBackend().send(rendered(body="ओटीपी 1234", category="OTP"))
        self.assertEqual(self.sent_form()["smsservicetype"], "otpmsg")

    def test_notification_text_uses_singlemsg(self):
        CDACSMSBackend().send(rendered(category="NOTIFICATION"))
        self.assertEqual(self.sent_form()["smsservicetype"], "singlemsg")

    def test_notification_unicode_uses_unicodemsg(self):
        CDACSMSBackend().send(rendered(body="नमस्ते", category="NOTIFICATION"))
        self.assertEqual(self.sent_form()["smsservicetype"], "unicodemsg")

    def test_transaction_text_uses_singlemsg(self):
        CDACSMSBackend().send(rendered(category="TRANSACTION"))
        self.assertEqual(self.sent_form()["smsservicetype"], "singlemsg")

    def test_transaction_unicode_uses_unicodemsg(self):
        CDACSMSBackend().send(rendered(body="नमस्ते", category="TRANSACTION"))
        self.assertEqual(self.sent_form()["smsservicetype"], "unicodemsg")

    def test_mobileno_is_used_for_every_service_type(self):
        for body, category in (
            ("Your OTP is 1234", "OTP"),
            ("Hello", "NOTIFICATION"),
            ("नमस्ते", "NOTIFICATION"),
            ("नमस्ते", "TRANSACTION"),
        ):
            with self.subTest(category=category, body=body):
                CDACSMSBackend().send(rendered(body=body, category=category))
                form = self.sent_form()
                self.assertIn("mobileno", form)
                self.assertNotIn("bulkmobno", form)

    def test_unicode_body_is_entity_encoded(self):
        CDACSMSBackend().send(rendered(body="नमस्ते", category="NOTIFICATION"))
        self.assertEqual(
            self.sent_form()["content"],
            "&#2344;&#2350;&#2360;&#2381;&#2340;&#2375;",
        )

    def test_text_body_is_sent_verbatim(self):
        CDACSMSBackend().send(rendered(body="Hello", category="NOTIFICATION"))
        self.assertEqual(self.sent_form()["content"], "Hello")

    def test_context_override_forces_unicode(self):
        CDACSMSBackend().send(
            rendered(body="Hello", category="NOTIFICATION", context={"sms_content_type": "unicode"})
        )
        form = self.sent_form()
        self.assertEqual(form["smsservicetype"], "unicodemsg")
        self.assertEqual(form["content"], "&#72;&#101;&#108;&#108;&#111;")

    def test_context_override_forces_text(self):
        CDACSMSBackend().send(
            rendered(body="नमस्ते", category="NOTIFICATION", context={"sms_content_type": "text"})
        )
        self.assertEqual(self.sent_form()["smsservicetype"], "singlemsg")

    def test_invalid_content_type_override_is_permanent(self):
        with self.assertRaises(MessagePermanentError) as ctx:
            CDACSMSBackend().send(rendered(context={"sms_content_type": "binary"}))
        self.assertEqual(ctx.exception.code, constants.UNSUPPORTED_CONTENT_TYPE)

    def test_unsupported_category_is_permanent(self):
        with self.assertRaises(MessagePermanentError) as ctx:
            CDACSMSBackend().send(rendered(category="MARKETING"))
        self.assertEqual(ctx.exception.code, constants.UNSUPPORTED_CATEGORY)
        self.post.assert_not_called()


@override_settings(**GATEWAY_SETTINGS)
class TemplateIdTests(BackendTestCase):
    """Template-ID resolution tests (§5.7)."""

    @override_settings(**{**GATEWAY_SETTINGS, "CDAC_SMS_TEMPLATE_ID": "config-template"})
    def test_template_field_wins_over_config(self):
        CDACSMSBackend().send(rendered(provider_template_id="template-123"))
        self.assertEqual(self.sent_form()["templateid"], "template-123")

    @override_settings(**{**GATEWAY_SETTINGS, "CDAC_SMS_TEMPLATE_ID": "config-template"})
    def test_falls_back_to_config(self):
        CDACSMSBackend().send(rendered())
        self.assertEqual(self.sent_form()["templateid"], "config-template")

    def test_omitted_when_both_are_empty(self):
        CDACSMSBackend().send(rendered())
        self.assertNotIn("templateid", self.sent_form())


class FailureClassificationTests(BackendTestCase):
    """Permanent, transient, and filtered outcomes."""

    @override_settings(**GATEWAY_SETTINGS)
    def test_missing_recipient_is_permanent(self):
        with self.assertRaises(MessagePermanentError) as ctx:
            CDACSMSBackend().send(rendered(recipient={}))
        self.assertEqual(ctx.exception.code, constants.INVALID_RECIPIENT)
        self.post.assert_not_called()

    @override_settings(CDAC_SMS_URL="", CDAC_SMS_USERNAME="", CDAC_SMS_PASSWORD="")
    def test_missing_configuration_is_permanent(self):
        with self.assertRaises(MessagePermanentError) as ctx:
            CDACSMSBackend().send(rendered())
        self.assertEqual(ctx.exception.code, constants.INVALID_CONFIGURATION)
        self.post.assert_not_called()

    @override_settings(**{**GATEWAY_SETTINGS, "CDAC_SMS_ENABLED": False})
    def test_disabled_gateway_filters_without_contacting_it(self):
        with self.assertRaises(RecipientFilteredError) as ctx:
            CDACSMSBackend().send(rendered())
        self.assertEqual(ctx.exception.reason, constants.REASON_DISABLED)
        self.post.assert_not_called()

    @override_settings(**{**GATEWAY_SETTINGS, "CDAC_SMS_BLACKLIST_NUMBERS": ["9876*"]})
    def test_blacklisted_recipient_filters(self):
        with self.assertRaises(RecipientFilteredError) as ctx:
            CDACSMSBackend().send(rendered())
        self.assertEqual(ctx.exception.reason, constants.REASON_BLACKLIST)
        self.post.assert_not_called()

    @override_settings(**GATEWAY_SETTINGS)
    def test_gateway_error_status_is_transient(self):
        self.post.return_value.status_code = 503
        with self.assertRaises(MessageSendError) as ctx:
            CDACSMSBackend().send(rendered())
        self.assertNotIsInstance(ctx.exception, MessagePermanentError)

    @override_settings(**GATEWAY_SETTINGS)
    def test_wrong_message_type_is_rejected(self):
        with self.assertRaises(MessageSendError):
            CDACSMSBackend().send(rendered(message_type="email"))


@override_settings(**GATEWAY_SETTINGS)
class TransportTests(BackendTestCase):
    """Timeouts, TLS, and connection failures."""

    def test_timeout_is_transient(self):
        import requests

        self.post.side_effect = requests.Timeout("timed out")
        with self.assertRaises(MessageSendError) as ctx:
            CDACSMSBackend().send(rendered())
        self.assertNotIsInstance(ctx.exception, MessagePermanentError)
        self.assertEqual(ctx.exception.code, constants.GATEWAY_TIMEOUT)

    def test_connection_error_is_transient(self):
        import requests

        self.post.side_effect = requests.ConnectionError("refused")
        with self.assertRaises(MessageSendError) as ctx:
            CDACSMSBackend().send(rendered())
        self.assertEqual(ctx.exception.code, constants.GATEWAY_CONNECTION_ERROR)

    def test_other_request_exception_is_transient(self):
        import requests

        self.post.side_effect = requests.RequestException("boom")
        with self.assertRaises(MessageSendError) as ctx:
            CDACSMSBackend().send(rendered())
        self.assertEqual(ctx.exception.code, constants.GATEWAY_UNAVAILABLE)

    @override_settings(**{**GATEWAY_SETTINGS, "CDAC_SMS_VERIFY_SSL": False})
    def test_verification_can_be_disabled(self):
        CDACSMSBackend().send(rendered())
        self.assertFalse(self.post.call_args.kwargs["verify"])

    def test_adapter_requires_tls_1_2(self):
        import ssl

        adapter = TLSv12Adapter()
        context = adapter.poolmanager.connection_pool_kw["ssl_context"]
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)


@override_settings(**{**GATEWAY_SETTINGS, "CDAC_SMS_PRINT_RESPONSE": True})
class LoggingTests(BackendTestCase):
    """GATEWAY_REQUEST masking and secret suppression."""

    def test_request_log_masks_recipient_and_omits_secrets(self):
        with self.assertLogs(constants.LOGGER_NAME, level="INFO") as captured:
            CDACSMSBackend().send(rendered())
        request_line = next(line for line in captured.output if "event=GATEWAY_REQUEST" in line)
        self.assertIn("message_id=mid-1", request_line)
        self.assertIn("correlation_id=cid-1", request_line)
        self.assertIn("service_type=otpmsg", request_line)
        self.assertIn("prefix_applied=True", request_line)
        self.assertNotIn("919876512345", request_line)
        self.assertIn("9198****2345", request_line)

    def test_no_log_line_contains_a_credential(self):
        with self.assertLogs(constants.LOGGER_NAME, level="INFO") as captured:
            CDACSMSBackend().send(rendered())
        blob = "\n".join(captured.output)
        for secret in (
            "secret",
            "secure-key",
            hashlib.sha1(b"secret").hexdigest(),
            self.sent_form()["key"],
        ):
            self.assertNotIn(secret, blob)

    def test_mask_form_drops_password_key_and_content(self):
        masked = mask_form(
            {
                "username": "user",
                "password": "hash",
                "key": "signature",
                "content": "body",
                "mobileno": "919876512345",
            }
        )
        self.assertEqual(set(masked), {"username", "mobileno"})
