"""Tests for the CDAC gateway system checks."""

from django.test import SimpleTestCase, override_settings

from addon.cdac_sms_gateway.checks import check_cdac_sms_configuration
from addon.cdac_sms_gateway.config import reset_config_cache

ACTIVE = {"MESSAGING_BACKENDS": {"sms": "addon.cdac_sms_gateway.backend.CDACSMSBackend"}}
VALID = {
    **ACTIVE,
    "CDAC_SMS_URL": "https://gateway.example.com/esms/sendsmsrequestDLT",
    "CDAC_SMS_USERNAME": "user",
    "CDAC_SMS_PASSWORD": "secret",
    "CDAC_SMS_SENDER_ID": "DRISTI",
    "CDAC_SMS_SECURE_KEY": "secure-key",
}


def run_checks():
    """Run the addon's checks and return the messages."""

    return check_cdac_sms_configuration(app_configs=None)


def ids(messages):
    """Return the set of check IDs produced."""

    return {message.id for message in messages}


class CheckTests(SimpleTestCase):
    """System check tests."""

    def setUp(self):
        reset_config_cache()
        self.addCleanup(reset_config_cache)

    @override_settings(**VALID)
    def test_valid_configuration_is_silent(self):
        self.assertEqual(run_checks(), [])

    @override_settings(MESSAGING_BACKENDS={"sms": "apps.messaging.senders.sms.DummySMSBackend"})
    def test_silent_when_addon_is_not_the_active_backend(self):
        self.assertEqual(run_checks(), [])

    @override_settings(**{**ACTIVE, "CDAC_SMS_ENABLED": False})
    def test_silent_when_gateway_is_disabled(self):
        self.assertEqual(run_checks(), [])

    @override_settings(**ACTIVE)
    def test_missing_credentials_are_errors(self):
        messages = run_checks()
        self.assertTrue(messages)
        self.assertTrue(all(message.level >= 40 for message in messages))
        self.assertIn("cdac_sms.E001", ids(messages))

    @override_settings(**{**VALID, "CDAC_SMS_URL": "http://gateway.example.com/esms"})
    def test_non_https_url_is_an_error(self):
        self.assertIn("cdac_sms.E002", ids(run_checks()))

    @override_settings(
        **{**VALID, "CDAC_SMS_USE_DEFAULT_NUMBER": True, "CDAC_SMS_DEFAULT_NUMBER": "123"}
    )
    def test_bad_default_number_is_an_error(self):
        self.assertIn("cdac_sms.E003", ids(run_checks()))

    @override_settings(**{**VALID, "CDAC_SMS_VERIFY_RESPONSE": True})
    def test_verify_response_without_literal_is_an_error(self):
        self.assertIn("cdac_sms.E004", ids(run_checks()))

    @override_settings(**{**VALID, "CDAC_SMS_TIMEOUT": 30, "MESSAGING_TASK_TIME_LIMIT": 10000})
    def test_timeout_above_actor_time_limit_is_an_error(self):
        self.assertIn("cdac_sms.E006", ids(run_checks()))

    @override_settings(**{**VALID, "CDAC_SMS_TIMEOUT": 30, "MESSAGING_TASK_TIME_LIMIT": 600000})
    def test_timeout_below_actor_time_limit_is_accepted(self):
        self.assertNotIn("cdac_sms.E006", ids(run_checks()))

    @override_settings(
        **{
            **VALID,
            "CDAC_SMS_USE_DEFAULT_NUMBER": True,
            "CDAC_SMS_DEFAULT_NUMBER": "9000000000",
        }
    )
    def test_default_number_override_warns(self):
        messages = run_checks()
        self.assertIn("cdac_sms.W001", ids(messages))
        self.assertTrue(all(message.level < 40 for message in messages))

    @override_settings(**{**VALID, "CDAC_SMS_VERIFY_SSL": False})
    def test_disabled_ssl_verification_warns(self):
        messages = run_checks()
        self.assertIn("cdac_sms.W002", ids(messages))
        self.assertTrue(all(message.level < 40 for message in messages))

    @override_settings(**{**VALID, "CDAC_SMS_WHITELIST_NUMBERS": ["98765XXXXX", "9876*"]})
    def test_valid_patterns_are_accepted(self):
        self.assertEqual(run_checks(), [])
