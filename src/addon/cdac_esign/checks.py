"""Django system checks for the C-DAC eSign configuration (spec 0015 #11.1).

Every check is silent when the addon is installed but is not the active
provider, so local and CI environments need no C-DAC credentials or keystore.
"""

from datetime import timedelta

from django.conf import settings
from django.core.checks import Error, Warning, register
from django.utils import timezone

from apps.esign import conf as esign_conf
from apps.esign.checks import is_production_settings

from .config import is_active_provider, resolve_config
from .keystore import CDACKeystoreError, load_key_material

# How long before expiry the ASP certificate starts warning.
CERTIFICATE_EXPIRY_WARNING = timedelta(days=30)

_CODE_IDS = {
    "CDAC_ESIGN_URL": "cdac_esign.E002",
    "CDAC_ESIGN_RESPONSE_URL": "cdac_esign.E002",
    "CDAC_ESIGN_RESPONSE_CERT": "cdac_esign.E003",
    "CDAC_ESIGN_TXN_TEMPLATE": "cdac_esign.E004",
    "CDAC_ESIGN_RESPONSE_MAX_SKEW": "cdac_esign.E005",
}


@register()
def check_cdac_esign_configuration(app_configs, **kwargs):
    """Validate the C-DAC settings when this addon is the active provider."""

    if not is_active_provider() or not esign_conf.is_enabled():
        return []

    config = resolve_config()
    messages = [
        Error(message, id=_CODE_IDS.get(setting_name, "cdac_esign.E001"))
        for setting_name, message in config.validate()
    ]

    messages.extend(_check_keystore(config))
    messages.extend(_check_hash_algorithm(config))

    if is_production_settings():
        if not config.verify_response_signature:
            messages.append(
                Error(
                    "CDAC_ESIGN_VERIFY_RESPONSE_SIGNATURE must be enabled in production; "
                    "the callback is a public endpoint and the response signature is "
                    "the only thing that makes it trustworthy.",
                    id="cdac_esign.E008",
                )
            )
        if not config.response_cert:
            messages.append(
                Error(
                    "CDAC_ESIGN_RESPONSE_CERT is required in production.",
                    id="cdac_esign.E003",
                )
            )
    elif not config.verify_response_signature:
        messages.append(
            Warning(
                "CDAC_ESIGN_VERIFY_RESPONSE_SIGNATURE is disabled; eSign responses are "
                "accepted without verification. Non-production use only.",
                id="cdac_esign.W001",
            )
        )

    return messages


def _check_keystore(config):
    """Confirm the keystore opens and holds usable, unexpired key material."""

    if not config.keystore_path:
        return []

    try:
        key_material = load_key_material(config.keystore_path, config.keystore_password)
    except CDACKeystoreError as exc:
        return [
            Error(
                f"CDAC_ESIGN_KEYSTORE_PATH could not be loaded: {exc}",
                hint="Check the path, the password, and that the PKCS#12 file holds "
                "both the ASP private key and its certificate.",
                id="cdac_esign.E006",
            )
        ]

    expiry = key_material.not_valid_after
    now = timezone.now()
    if expiry <= now:
        return [
            Error(
                f"The ASP certificate expired on {expiry.date().isoformat()}.",
                id="cdac_esign.E007",
            )
        ]
    if expiry - now <= CERTIFICATE_EXPIRY_WARNING:
        return [
            Warning(
                f"The ASP certificate expires on {expiry.date().isoformat()}.",
                hint="Rotate the keystore before it expires.",
                id="cdac_esign.W002",
            )
        ]
    return []


def _check_hash_algorithm(config):
    """The ESP is told which algorithm produced the hash it receives."""

    pdf_algorithm = str(getattr(settings, "PDF_SIGNATURE_HASH_ALGORITHM", "SHA256")).upper()
    if config.hash_algorithm != pdf_algorithm:
        return [
            Error(
                f"CDAC_ESIGN_HASH_ALGORITHM ({config.hash_algorithm}) must match "
                f"PDF_SIGNATURE_HASH_ALGORITHM ({pdf_algorithm}).",
                id="cdac_esign.E009",
            )
        ]
    return []
