"""Tests for gateway configuration loading and validation."""

from django.test import SimpleTestCase, override_settings

from addon.cdac_sms_gateway.config import is_active_backend, reset_config_cache, resolve_config

VALID = {
    "CDAC_SMS_URL": "https://msdgweb.mgov.gov.in/esms/sendsmsrequestDLT",
    "CDAC_SMS_USERNAME": "user",
    "CDAC_SMS_PASSWORD": "secret",
    "CDAC_SMS_SENDER_ID": "DRISTI",
    "CDAC_SMS_SECURE_KEY": "secure-key",
}


class ResolveConfigTests(SimpleTestCase):
    """Config resolution tests."""

    def setUp(self):
        reset_config_cache()

    def tearDown(self):
        reset_config_cache()

    @override_settings(**VALID)
    def test_loads_flat_settings(self):
        cfg = resolve_config()
        self.assertEqual(cfg.username, "user")
        self.assertEqual(cfg.sender_id, "DRISTI")
        self.assertEqual(cfg.url, VALID["CDAC_SMS_URL"])

    def test_defaults(self):
        cfg = resolve_config()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.timeout, 30)
        self.assertTrue(cfg.verify_ssl)
        self.assertEqual(cfg.success_codes, (200, 201, 202))
        self.assertEqual(cfg.error_codes, ())
        self.assertFalse(cfg.verify_response)
        self.assertTrue(cfg.print_response)
        self.assertFalse(cfg.use_default_number)

    @override_settings(**VALID)
    def test_result_is_cached_until_reset(self):
        first = resolve_config()
        self.assertIs(first, resolve_config())
        reset_config_cache()
        self.assertIsNot(first, resolve_config())

    @override_settings(**VALID)
    def test_cache_resets_automatically_when_a_setting_changes(self):
        self.assertEqual(resolve_config().username, "user")
        with override_settings(CDAC_SMS_USERNAME="other"):
            self.assertEqual(resolve_config().username, "other")
        self.assertEqual(resolve_config().username, "user")

    @override_settings(**VALID)
    def test_repr_redacts_secrets(self):
        text = repr(resolve_config())
        self.assertNotIn("secret", text)
        self.assertNotIn("secure-key", text)
        self.assertIn("password='***'", text)
        self.assertIn("secure_key='***'", text)


class ValidateTests(SimpleTestCase):
    """Config validation tests."""

    def setUp(self):
        reset_config_cache()

    def tearDown(self):
        reset_config_cache()

    @override_settings(**VALID)
    def test_valid_config_has_no_problems(self):
        self.assertEqual(resolve_config().validate(), [])

    def test_missing_required_keys_reported(self):
        problems = dict(resolve_config().validate())
        for name in VALID:
            self.assertIn(name, problems)

    @override_settings(**{**VALID, "CDAC_SMS_URL": "http://msdgweb.example.com/esms"})
    def test_non_https_url_rejected(self):
        self.assertIn("CDAC_SMS_URL", dict(resolve_config().validate()))

    @override_settings(
        **{**VALID, "CDAC_SMS_USE_DEFAULT_NUMBER": True, "CDAC_SMS_DEFAULT_NUMBER": "12345"}
    )
    def test_invalid_default_number_rejected(self):
        self.assertIn("CDAC_SMS_DEFAULT_NUMBER", dict(resolve_config().validate()))

    @override_settings(
        **{**VALID, "CDAC_SMS_USE_DEFAULT_NUMBER": True, "CDAC_SMS_DEFAULT_NUMBER": "9876543210"}
    )
    def test_valid_default_number_accepted(self):
        self.assertEqual(resolve_config().validate(), [])

    @override_settings(**{**VALID, "CDAC_SMS_VERIFY_RESPONSE": True})
    def test_verify_response_without_literal_rejected(self):
        self.assertIn("CDAC_SMS_VERIFY_RESPONSE_CONTAINS", dict(resolve_config().validate()))


class IsActiveBackendTests(SimpleTestCase):
    """Active-backend detection tests."""

    @override_settings(MESSAGING_BACKENDS={"sms": "addon.cdac_sms_gateway.backend.CDACSMSBackend"})
    def test_active(self):
        self.assertTrue(is_active_backend())

    @override_settings(MESSAGING_BACKENDS={"sms": "apps.messaging.senders.sms.DummySMSBackend"})
    def test_inactive(self):
        self.assertFalse(is_active_backend())
