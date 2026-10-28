"""Configuration loading and validation tests (spec 0022 #9)."""

from datetime import timedelta

from django.test import SimpleTestCase, override_settings

from addon.egras_payment_gateway.config import (
    BankOption,
    EGRASConfig,
    is_active_provider,
    resolve_config,
)

from .base import VALID_SETTINGS, EGRASSettingsMixin


class ConfigDefaultsTests(SimpleTestCase):
    """The optional settings default to the documented values (#9.2)."""

    def test_defaults(self):
        config = EGRASConfig()

        self.assertEqual(config.user_id, "guest")
        self.assertEqual(config.max_schemes, 4)
        self.assertEqual(config.application_prefix, "DR")
        self.assertEqual(config.remarks_template, "Dristi {demand_numbers}")
        self.assertEqual(config.payer_fallback_city, "NA")
        self.assertEqual(config.payer_fallback_pincode, "000000")
        self.assertEqual(config.timeout, 15)
        self.assertTrue(config.verify_ssl)
        self.assertEqual(config.pending_horizon, timedelta(days=9))
        self.assertEqual(config.not_found_grace, timedelta(hours=2))
        self.assertTrue(config.enabled)

    def test_office_name_falls_back_to_office_codes(self):
        config = EGRASConfig(dto="01", sto="02", ddo="DDO1")
        self.assertEqual(config.effective_office_name, "0102DDO1")

        config = EGRASConfig(dto="01", sto="02", ddo="DDO1", office_name="COURT001")
        self.assertEqual(config.effective_office_name, "COURT001")


class ConfigLoadingTests(EGRASSettingsMixin, SimpleTestCase):
    """``resolve_config`` reads settings once and reacts to overrides."""

    def test_settings_are_loaded_and_cached(self):
        self.configure()
        config = resolve_config()

        self.assertEqual(config.dept_code, "DRI")
        self.assertEqual(config.scheme_map, {"COURT_FEE": "0030-01-501-01-00"})
        self.assertEqual(
            config.bank_options[0], BankOption("SBI", "State Bank of India", "NET_BANKING")
        )
        self.assertIs(resolve_config(), config)

    def test_cache_resets_when_an_egras_setting_changes(self):
        self.configure()
        self.assertEqual(resolve_config().dept_code, "DRI")
        with override_settings(EGRAS_DEPT_CODE="XYZ"):
            self.assertEqual(resolve_config().dept_code, "XYZ")


class ConfigValidationTests(SimpleTestCase):
    """``EGRASConfig.validate`` names each problem individually (#9.3)."""

    def test_missing_required_settings_are_reported(self):
        problems = dict(EGRASConfig().validate())
        for name in (
            "EGRAS_PAYMENT_URL",
            "EGRAS_VERIFY_URL",
            "EGRAS_RETURN_URL",
            "EGRAS_DEPT_CODE",
            "EGRAS_DTO",
            "EGRAS_STO",
            "EGRAS_DDO",
            "EGRAS_SCHEME_MAP",
            "EGRAS_BANK_OPTIONS",
        ):
            self.assertIn(name, problems)

    def _valid(self, **overrides):
        base = {
            "payment_url": "https://egras.invalid/echallan",
            "verify_url": "https://egras.invalid/grnstatus",
            "return_url": "https://dristi.invalid/api/v1/payments/providers/egras/_callback",
            "dept_code": "DRI",
            "dto": "01",
            "sto": "02",
            "ddo": "DDO1",
            "scheme_map": {"COURT_FEE": "0030-01-501-01-00"},
            "bank_options": (BankOption("SBI", "State Bank of India"),),
        }
        base.update(overrides)
        return EGRASConfig(**base)

    def test_a_complete_configuration_is_clean(self):
        self.assertEqual(self._valid().validate(), [])

    def test_urls_must_be_absolute_https(self):
        problems = dict(self._valid(payment_url="http://egras.invalid/x").validate())
        self.assertIn("EGRAS_PAYMENT_URL", problems)

    def test_return_url_must_end_with_the_callback_path(self):
        problems = dict(self._valid(return_url="https://dristi.invalid/elsewhere").validate())
        self.assertIn("EGRAS_RETURN_URL", problems)

    def test_office_codes_lengths(self):
        problems = dict(self._valid(dto="1", sto="ab", ddo="D").validate())
        self.assertIn("EGRAS_DTO", problems)
        self.assertIn("EGRAS_STO", problems)
        self.assertIn("EGRAS_DDO", problems)

    def test_nic_issued_short_office_name_is_accepted(self):
        """The NIC v3.6 sample posts a 5-char Officename, so <= 8 is allowed."""
        self.assertNotIn("EGRAS_OFFICE_NAME", dict(self._valid(office_name="12678").validate()))

    def test_overlong_office_name_is_rejected(self):
        problems = dict(self._valid(office_name="TOOLONGOFFICE").validate())
        self.assertIn("EGRAS_OFFICE_NAME", problems)

    def test_scheme_codes_must_be_17_char_codes(self):
        problems = dict(self._valid(scheme_map={"COURT_FEE": "not-a-code"}).validate())
        self.assertIn("EGRAS_SCHEME_MAP", problems)

    def test_bank_codes_must_be_unique_and_default_known(self):
        problems = dict(
            self._valid(
                bank_options=(BankOption("SBI", "a"), BankOption("SBI", "b")),
                default_bank="HDFC",
            ).validate()
        )
        self.assertIn("EGRAS_BANK_OPTIONS", problems)
        self.assertIn("EGRAS_DEFAULT_BANK", problems)

    def test_application_prefix_must_be_short_and_alphanumeric(self):
        problems = dict(self._valid(application_prefix="LONG").validate())
        self.assertIn("EGRAS_APPLICATION_PREFIX", problems)

    def test_pending_horizon_must_be_at_least_eight_days(self):
        problems = dict(self._valid(pending_horizon=timedelta(days=5)).validate())
        self.assertIn("EGRAS_PENDING_HORIZON", problems)


class ActiveProviderTests(SimpleTestCase):
    """The addon only acts when e-GRAS is a registered provider (#9.3)."""

    def test_active_when_registered(self):
        with override_settings(PAYMENT_PROVIDERS=VALID_SETTINGS["PAYMENT_PROVIDERS"]):
            self.assertTrue(is_active_provider())

    def test_inactive_when_not_registered(self):
        with override_settings(
            PAYMENT_PROVIDERS={"mock": "apps.payments.providers.mock.MockPaymentProvider"}
        ):
            self.assertFalse(is_active_provider())
