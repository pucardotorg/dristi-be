"""DSC configuration and registration detection (spec 0038 #11)."""

from django.test import SimpleTestCase, override_settings

from addon.dsc_esign.config import is_registered, resolve_config
from addon.dsc_esign.constants import PROVIDER_NAME, PROVIDER_PATH


class ResolveConfigTests(SimpleTestCase):
    """Settings are read live under the DSC_ESIGN_* prefix."""

    @override_settings(
        DSC_ESIGN_AGENT_URL="https://agent.example/sign",
        DSC_ESIGN_REQUIRE_REGISTERED_CERT=True,
        PDF_SIGNATURE_HASH_ALGORITHM="sha384",
    )
    def test_reads_settings(self):
        config = resolve_config()
        self.assertEqual(config.agent_url, "https://agent.example/sign")
        self.assertTrue(config.require_registered_cert)
        self.assertEqual(config.hash_algorithm, "SHA384")


class IsRegisteredTests(SimpleTestCase):
    """DSC is 'registered' via the registry map or the deprecated alias."""

    @override_settings(ESIGN_PROVIDERS={PROVIDER_NAME: PROVIDER_PATH}, ESIGN_PROVIDER="")
    def test_registered_by_name(self):
        self.assertTrue(is_registered())

    @override_settings(ESIGN_PROVIDERS={}, ESIGN_PROVIDER=PROVIDER_PATH)
    def test_registered_by_alias(self):
        self.assertTrue(is_registered())

    @override_settings(
        ESIGN_PROVIDERS={"cdac": "addon.cdac_esign.provider.CDACESignProvider"},
        ESIGN_PROVIDER="",
    )
    def test_not_registered(self):
        self.assertFalse(is_registered())
