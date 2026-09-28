"""Configuration and system-check tests (spec 0015 #11)."""

import datetime
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from addon.cdac_esign import constants
from addon.cdac_esign.checks import check_cdac_esign_configuration
from addon.cdac_esign.config import CDACESignConfig, is_active_provider, resolve_config
from apps.esign.checks import check_esign_settings

from .base import CDACSettingsMixin
from .keys import KEYSTORE_PASSWORD, generate_key_pair, write_keystore

PRODUCTION = "config.settings.production"


def ids(messages):
    """Return the check ids of ``messages``."""

    return sorted(message.id for message in messages)


class ConfigTests(CDACSettingsMixin, SimpleTestCase):
    """``resolve_config`` and its validation."""

    def test_defaults_match_the_documented_values(self):
        """The optional settings default to the eSign 2.1 values of #11."""
        config = CDACESignConfig()

        self.assertEqual(config.version, "2.1")
        self.assertEqual(config.auth_mode, "1")
        self.assertEqual(config.hash_algorithm, "SHA256")
        self.assertEqual(config.ekyc_id_type, "A")
        self.assertEqual(config.consent, "Y")
        self.assertEqual(config.txn_template, "{module}-{transaction_id}")
        self.assertEqual(config.response_max_skew, 900)
        self.assertTrue(config.verify_response_signature)

    def test_settings_are_loaded_and_cached(self):
        """The configuration is read once per process."""
        self.configure()
        config = resolve_config()

        self.assertEqual(config.asp_id, "ASP-TEST")
        self.assertIs(resolve_config(), config)

    def test_repr_redacts_the_keystore_password(self):
        """A traceback or log line must not expose the secret."""
        self.configure()
        rendered = repr(resolve_config())

        self.assertIn("ASP-TEST", rendered)
        self.assertNotIn(KEYSTORE_PASSWORD, rendered)
        self.assertIn("***", rendered)

    def test_missing_required_settings_are_reported(self):
        """Every required value is named individually."""
        problems = dict(CDACESignConfig().validate())

        for name in (
            "CDAC_ESIGN_URL",
            "CDAC_ESIGN_ASP_ID",
            "CDAC_ESIGN_RESPONSE_URL",
            "CDAC_ESIGN_KEYSTORE_PATH",
            "CDAC_ESIGN_KEYSTORE_PASSWORD",
            "CDAC_ESIGN_RESPONSE_CERT",
        ):
            self.assertIn(name, problems)

    def test_urls_must_be_absolute_https(self):
        """Both endpoints carry Aadhaar-adjacent traffic."""
        problems = dict(
            CDACESignConfig(
                url="http://esign.cdac.invalid",
                response_url="/api/v1/esign/_signed",
            ).validate()
        )

        self.assertIn("CDAC_ESIGN_URL", problems)
        self.assertIn("CDAC_ESIGN_RESPONSE_URL", problems)

    def test_transaction_template_must_keep_the_transaction_id(self):
        """Dropping the UUID would make the ESP id collide."""
        problems = dict(CDACESignConfig(txn_template="{module}-fixed").validate())
        self.assertIn("CDAC_ESIGN_TXN_TEMPLATE", problems)

    def test_skew_must_be_positive(self):
        """A zero window would reject every response."""
        problems = dict(CDACESignConfig(response_max_skew=0).validate())
        self.assertIn("CDAC_ESIGN_RESPONSE_MAX_SKEW", problems)

    def test_active_provider_detection(self):
        """The addon only acts when it is the configured provider."""
        with override_settings(ESIGN_PROVIDER=constants.PROVIDER_PATH):
            self.assertTrue(is_active_provider())
        with override_settings(ESIGN_PROVIDER="apps.esign.providers.mock.MockESignProvider"):
            self.assertFalse(is_active_provider())


class AddonCheckTests(CDACSettingsMixin, SimpleTestCase):
    """``python manage.py check`` behaviour for the addon."""

    def test_valid_configuration_is_silent(self):
        """A correctly configured deployment raises nothing."""
        self.configure()
        self.assertEqual(check_cdac_esign_configuration(None), [])

    def test_checks_are_silent_when_the_addon_is_inactive(self):
        """Local and CI need no C-DAC credentials or keystore."""
        with override_settings(
            ESIGN_PROVIDER="apps.esign.providers.mock.MockESignProvider",
            CDAC_ESIGN_URL="",
            CDAC_ESIGN_ASP_ID="",
        ):
            self.reset_caches()
            self.assertEqual(check_cdac_esign_configuration(None), [])

    def test_checks_are_silent_when_esign_is_disabled(self):
        """The kill switch means nothing below can be exercised."""
        self.configure(ESIGN_ENABLED=False, CDAC_ESIGN_URL="")
        self.assertEqual(check_cdac_esign_configuration(None), [])

    def test_missing_credentials_are_errors(self):
        """A misconfigured container fails at startup, not on first signature."""
        self.configure(CDAC_ESIGN_URL="", CDAC_ESIGN_ASP_ID="")
        self.assertIn("cdac_esign.E001", ids(check_cdac_esign_configuration(None)))

    def test_unopenable_keystore_is_an_error(self):
        """The keystore is proven to open with the given password."""
        self.configure(CDAC_ESIGN_KEYSTORE_PASSWORD="wrong-password")
        self.assertIn("cdac_esign.E006", ids(check_cdac_esign_configuration(None)))

    def test_missing_keystore_file_is_an_error(self):
        """A path that does not exist is reported."""
        self.configure(CDAC_ESIGN_KEYSTORE_PATH=str(Path(tempfile.mkdtemp()) / "absent.p12"))
        self.assertIn("cdac_esign.E006", ids(check_cdac_esign_configuration(None)))

    def test_expired_asp_certificate_is_an_error(self):
        """An expired ASP certificate cannot sign a request C-DAC accepts."""
        expired = generate_key_pair(
            "ASP Expired",
            not_valid_after=datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1),
        )
        self.configure(
            CDAC_ESIGN_KEYSTORE_PATH=write_keystore(tempfile.mkdtemp(), key_pair=expired)
        )
        self.assertIn("cdac_esign.E007", ids(check_cdac_esign_configuration(None)))

    def test_soon_to_expire_certificate_warns(self):
        """Rotation is flagged before it becomes an outage."""
        expiring = generate_key_pair(
            "ASP Expiring",
            not_valid_after=datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=5),
        )
        self.configure(
            CDAC_ESIGN_KEYSTORE_PATH=write_keystore(tempfile.mkdtemp(), key_pair=expiring)
        )
        self.assertIn("cdac_esign.W002", ids(check_cdac_esign_configuration(None)))

    def test_hash_algorithm_must_match_the_pdf_service(self):
        """The ESP is told which algorithm produced the hash it receives."""
        self.configure(CDAC_ESIGN_HASH_ALGORITHM="SHA512", PDF_SIGNATURE_HASH_ALGORITHM="SHA256")
        self.assertIn("cdac_esign.E009", ids(check_cdac_esign_configuration(None)))

    def test_disabled_verification_warns_outside_production(self):
        """Skipping verification is a local affordance and is flagged."""
        self.configure(CDAC_ESIGN_VERIFY_RESPONSE_SIGNATURE=False, CDAC_ESIGN_RESPONSE_CERT="")
        self.assertIn("cdac_esign.W001", ids(check_cdac_esign_configuration(None)))

    def test_disabled_verification_is_an_error_in_production(self):
        """The public callback is only trustworthy with verification on."""
        self.configure(
            SETTINGS_MODULE=PRODUCTION,
            CDAC_ESIGN_VERIFY_RESPONSE_SIGNATURE=False,
            CDAC_ESIGN_RESPONSE_CERT="",
        )
        reported = ids(check_cdac_esign_configuration(None))

        self.assertIn("cdac_esign.E008", reported)
        self.assertIn("cdac_esign.E003", reported)


class DomainCheckTests(CDACSettingsMixin, SimpleTestCase):
    """``python manage.py check`` behaviour for the domain settings."""

    def test_valid_configuration_is_silent(self):
        """The defaults of #11 pass."""
        self.assertEqual(check_esign_settings(None), [])

    def test_non_positive_durations_are_errors(self):
        """A zero TTL would expire every transaction immediately."""
        with override_settings(ESIGN_TRANSACTION_TTL=0, ESIGN_MAX_ATTEMPTS=True):
            reported = ids(check_esign_settings(None))

        self.assertIn("esign.E001.ESIGN_TRANSACTION_TTL", reported)
        self.assertIn("esign.E001.ESIGN_MAX_ATTEMPTS", reported)

    def test_unimportable_provider_is_an_error(self):
        """A provider that cannot be resolved stops the process."""
        with override_settings(ESIGN_PROVIDER="apps.esign.providers.nope.Missing"):
            self.assertIn("esign.E002", ids(check_esign_settings(None)))

    def test_relative_redirect_url_is_an_error(self):
        """A browser mid-navigation needs an absolute target."""
        with override_settings(ESIGN_UI_REDIRECT_URL="/esign/return"):
            self.assertIn("esign.E003", ids(check_esign_settings(None)))

    def test_mock_provider_is_refused_in_production(self):
        """The mock provider signs nothing and verifies nothing."""
        with override_settings(
            SETTINGS_MODULE=PRODUCTION,
            ESIGN_PROVIDER="apps.esign.providers.mock.MockESignProvider",
            ESIGN_UI_REDIRECT_URL="https://ui.example.org/return",
        ):
            self.assertIn("esign.E004", ids(check_esign_settings(None)))

    def test_redirect_url_is_required_and_https_in_production(self):
        """An http redirect would drop the user out of TLS mid-flow."""
        with override_settings(
            SETTINGS_MODULE=PRODUCTION,
            ESIGN_PROVIDER=constants.PROVIDER_PATH,
            ESIGN_UI_REDIRECT_URL="",
        ):
            self.assertIn("esign.E005", ids(check_esign_settings(None)))
        with override_settings(
            SETTINGS_MODULE=PRODUCTION,
            ESIGN_PROVIDER=constants.PROVIDER_PATH,
            ESIGN_UI_REDIRECT_URL="http://ui.example.org/return",
        ):
            self.assertIn("esign.E006", ids(check_esign_settings(None)))

    def test_checks_are_silent_when_esign_is_disabled(self):
        """Only the duration sanity checks run behind the kill switch."""
        with override_settings(
            ESIGN_ENABLED=False, ESIGN_PROVIDER="apps.esign.providers.nope.Missing"
        ):
            self.assertEqual(check_esign_settings(None), [])
