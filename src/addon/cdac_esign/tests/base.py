"""Shared fixtures for the C-DAC eSign addon tests."""

import tempfile

from django.test import override_settings

from addon.cdac_esign import constants
from addon.cdac_esign.config import reset_config_cache
from addon.cdac_esign.keystore import reset_keystore_cache

from .keys import KEYSTORE_PASSWORD, esp_key_pair, write_keystore


class CDACSettingsMixin:
    """Points the addon at a generated keystore and the stand-in ESP cert."""

    def configure(self, **overrides):
        """Apply a complete, valid C-DAC configuration for this test."""

        directory = tempfile.mkdtemp()
        settings = {
            "ESIGN_PROVIDER": constants.PROVIDER_PATH,
            "CDAC_ESIGN_URL": "https://esign.cdac.invalid/esign",
            "CDAC_ESIGN_ASP_ID": "ASP-TEST",
            "CDAC_ESIGN_RESPONSE_URL": "https://dristi.invalid/api/v1/esign/_signed",
            "CDAC_ESIGN_KEYSTORE_PATH": write_keystore(directory),
            "CDAC_ESIGN_KEYSTORE_PASSWORD": KEYSTORE_PASSWORD,
            "CDAC_ESIGN_RESPONSE_CERT": esp_key_pair().certificate_pem,
        }
        settings.update(overrides)

        patcher = override_settings(**settings)
        patcher.enable()
        self.addCleanup(patcher.disable)
        self.reset_caches()
        self.addCleanup(self.reset_caches)
        return settings

    @staticmethod
    def reset_caches():
        """Clear the cached configuration and key material."""

        reset_config_cache()
        reset_keystore_cache()
