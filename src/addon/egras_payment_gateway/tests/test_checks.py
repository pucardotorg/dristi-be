"""``python manage.py check`` behaviour for the e-GRAS addon (spec 0022 #9.3)."""

from django.test import SimpleTestCase, override_settings

from addon.egras_payment_gateway.checks import check_egras_configuration

from .base import EGRASSettingsMixin

PRODUCTION = "config.settings.production"

MOCK_ONLY = {"mock": "apps.payments.providers.mock.MockPaymentProvider"}


def ids(messages):
    """Return the check ids of ``messages``."""

    return sorted(message.id for message in messages)


class AddonCheckTests(EGRASSettingsMixin, SimpleTestCase):
    def test_valid_configuration_is_silent(self):
        self.configure(EGRAS_SCHEME_MAP=dict.fromkeys(_all_charge_types(), "0030-01-501-01-00"))
        self.assertEqual(check_egras_configuration(None), [])

    def test_checks_are_silent_when_the_addon_is_not_registered(self):
        """Local and CI need no e-GRAS codes."""
        with override_settings(PAYMENT_PROVIDERS=MOCK_ONLY, EGRAS_PAYMENT_URL=""):
            self.assertEqual(check_egras_configuration(None), [])

    def test_missing_required_settings_are_errors(self):
        self.configure(EGRAS_PAYMENT_URL="", EGRAS_DEPT_CODE="")
        self.assertIn("egras_payment_gateway.E002", ids(check_egras_configuration(None)))
        self.assertIn("egras_payment_gateway.E003", ids(check_egras_configuration(None)))

    def test_bad_scheme_code_is_an_error(self):
        self.configure(EGRAS_SCHEME_MAP={"COURT_FEE": "nope"})
        self.assertIn("egras_payment_gateway.E004", ids(check_egras_configuration(None)))

    def test_unknown_default_bank_is_an_error(self):
        self.configure(EGRAS_DEFAULT_BANK="HDFC")
        self.assertIn("egras_payment_gateway.E005", ids(check_egras_configuration(None)))

    def test_short_pending_horizon_is_an_error(self):
        self.configure(EGRAS_PENDING_HORIZON=5)
        self.assertIn("egras_payment_gateway.E007", ids(check_egras_configuration(None)))

    def test_unmapped_charge_types_warn(self):
        """A charge type with no scheme mapping is flagged at deploy time."""
        self.configure(EGRAS_SCHEME_MAP={"COURT_FEE": "0030-01-501-01-00"})
        self.assertIn("egras_payment_gateway.W001", ids(check_egras_configuration(None)))

    def test_verify_ssl_off_is_an_error_in_production(self):
        self.configure(SETTINGS_MODULE=PRODUCTION, EGRAS_VERIFY_SSL=False)
        self.assertIn("egras_payment_gateway.E008", ids(check_egras_configuration(None)))


def _all_charge_types():
    from apps.payments.enums import ChargeType

    return [charge.value for charge in ChargeType]
