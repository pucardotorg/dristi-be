"""C-DAC eSign configuration loading (spec 0015 #11).

One deployment talks to one ESP with one ASP identity, so the settings are flat
``CDAC_ESIGN_*`` values read from the environment. The dataclass is frozen,
cached, and redacts the keystore password in ``repr`` so it cannot leak through
a log line or a traceback.
"""

import re
from dataclasses import dataclass, field, fields
from functools import lru_cache

from django.conf import settings

from . import constants

REQUIRED_SETTINGS = (
    ("CDAC_ESIGN_URL", "url"),
    ("CDAC_ESIGN_ASP_ID", "asp_id"),
    ("CDAC_ESIGN_RESPONSE_URL", "response_url"),
    ("CDAC_ESIGN_KEYSTORE_PATH", "keystore_path"),
    ("CDAC_ESIGN_KEYSTORE_PASSWORD", "keystore_password"),
)

HTTPS_URL = re.compile(r"^https://\S+$")

_REDACTED = "***"


@dataclass(frozen=True)
class CDACESignConfig:
    """Immutable snapshot of the C-DAC eSign configuration."""

    url: str = ""
    asp_id: str = ""
    response_url: str = ""
    keystore_path: str = ""
    keystore_password: str = field(default="", repr=False)
    response_cert: str = ""
    version: str = "2.1"
    auth_mode: str = "1"
    hash_algorithm: str = "SHA256"
    ekyc_id_type: str = "A"
    consent: str = "Y"
    txn_template: str = "{module}-{transaction_id}"
    response_max_skew: int = 900
    verify_response_signature: bool = True
    response_field: str = ""

    def __repr__(self):
        """Render the configuration without the keystore password."""

        shown = ", ".join(f"{f.name}={getattr(self, f.name)!r}" for f in fields(self) if f.repr)
        return f"CDACESignConfig({shown}, keystore_password={_REDACTED!r})"

    def validate(self) -> list[tuple[str, str]]:
        """Return a list of ``(setting_name, message)`` configuration problems."""

        problems = []
        for setting_name, attribute in REQUIRED_SETTINGS:
            if not getattr(self, attribute):
                problems.append((setting_name, f"{setting_name} is required."))

        for setting_name, value in (
            ("CDAC_ESIGN_URL", self.url),
            ("CDAC_ESIGN_RESPONSE_URL", self.response_url),
        ):
            if value and not HTTPS_URL.match(value):
                problems.append((setting_name, f"{setting_name} must be an absolute https:// URL."))

        if self.verify_response_signature and not self.response_cert:
            problems.append(
                (
                    "CDAC_ESIGN_RESPONSE_CERT",
                    "CDAC_ESIGN_RESPONSE_CERT is required while "
                    "CDAC_ESIGN_VERIFY_RESPONSE_SIGNATURE is enabled.",
                )
            )

        if "{transaction_id}" not in self.txn_template:
            problems.append(
                (
                    "CDAC_ESIGN_TXN_TEMPLATE",
                    "CDAC_ESIGN_TXN_TEMPLATE must contain {transaction_id} so the "
                    "correlation id stays unique.",
                )
            )

        if self.response_max_skew < 1:
            problems.append(
                (
                    "CDAC_ESIGN_RESPONSE_MAX_SKEW",
                    "CDAC_ESIGN_RESPONSE_MAX_SKEW must be at least 1 second.",
                )
            )

        return problems


@lru_cache(maxsize=1)
def resolve_config() -> CDACESignConfig:
    """Load the C-DAC configuration from Django settings, cached."""

    def get(name, default):
        return getattr(settings, name, default)

    return CDACESignConfig(
        url=get("CDAC_ESIGN_URL", ""),
        asp_id=get("CDAC_ESIGN_ASP_ID", ""),
        response_url=get("CDAC_ESIGN_RESPONSE_URL", ""),
        keystore_path=get("CDAC_ESIGN_KEYSTORE_PATH", ""),
        keystore_password=get("CDAC_ESIGN_KEYSTORE_PASSWORD", ""),
        response_cert=get("CDAC_ESIGN_RESPONSE_CERT", ""),
        version=str(get("CDAC_ESIGN_VERSION", "2.1")),
        auth_mode=str(get("CDAC_ESIGN_AUTH_MODE", "1")),
        hash_algorithm=str(get("CDAC_ESIGN_HASH_ALGORITHM", "SHA256")).upper(),
        ekyc_id_type=str(get("CDAC_ESIGN_EKYC_ID_TYPE", "A")),
        consent=str(get("CDAC_ESIGN_CONSENT", "Y")),
        txn_template=get("CDAC_ESIGN_TXN_TEMPLATE", "") or "{module}-{transaction_id}",
        response_max_skew=int(get("CDAC_ESIGN_RESPONSE_MAX_SKEW", 900)),
        verify_response_signature=bool(get("CDAC_ESIGN_VERIFY_RESPONSE_SIGNATURE", True)),
        response_field=get("CDAC_ESIGN_RESPONSE_FIELD", ""),
    )


def reset_config_cache() -> None:
    """Clear the cached configuration (needed when overriding settings)."""

    resolve_config.cache_clear()


def is_active_provider() -> bool:
    """Return True when this addon is the configured eSign provider."""

    return getattr(settings, "ESIGN_PROVIDER", "") == constants.PROVIDER_PATH
