"""Gateway credential and option loading."""

import re
from dataclasses import dataclass, field, fields
from functools import lru_cache

from django.conf import settings

from . import constants

REQUIRED_SETTINGS = (
    ("CDAC_SMS_URL", "url"),
    ("CDAC_SMS_USERNAME", "username"),
    ("CDAC_SMS_PASSWORD", "password"),
    ("CDAC_SMS_SENDER_ID", "sender_id"),
    ("CDAC_SMS_SECURE_KEY", "secure_key"),
)

_REDACTED = "***"


@dataclass(frozen=True)
class CDACConfig:
    """Immutable snapshot of the gateway configuration."""

    url: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    sender_id: str = ""
    secure_key: str = field(default="", repr=False)
    template_id: str = ""
    mobile_prefix: str = ""
    enabled: bool = True
    timeout: int = 30
    verify_ssl: bool = True
    success_codes: tuple = (200, 201, 202)
    error_codes: tuple = ()
    verify_response: bool = False
    verify_response_contains: str = ""
    print_response: bool = True
    whitelist_numbers: tuple = ()
    blacklist_numbers: tuple = ()
    use_default_number: bool = False
    default_number: str = ""

    def __repr__(self):
        shown = ", ".join(f"{f.name}={getattr(self, f.name)!r}" for f in fields(self) if f.repr)
        return f"CDACConfig({shown}, password={_REDACTED!r}, secure_key={_REDACTED!r})"

    def validate(self) -> list[tuple[str, str]]:
        """Return a list of (code, message) configuration problems."""

        problems = []
        for setting_name, attribute in REQUIRED_SETTINGS:
            if not getattr(self, attribute):
                problems.append((setting_name, f"{setting_name} is required."))
        if self.url and not re.match(r"^https://\S+$", self.url):
            problems.append(("CDAC_SMS_URL", "CDAC_SMS_URL must be an absolute https:// URL."))
        if self.use_default_number and not re.fullmatch(r"\d{10}", self.default_number):
            problems.append(
                (
                    "CDAC_SMS_DEFAULT_NUMBER",
                    "CDAC_SMS_DEFAULT_NUMBER must be exactly 10 digits when "
                    "CDAC_SMS_USE_DEFAULT_NUMBER is enabled.",
                )
            )
        if self.verify_response and not self.verify_response_contains:
            problems.append(
                (
                    "CDAC_SMS_VERIFY_RESPONSE_CONTAINS",
                    "CDAC_SMS_VERIFY_RESPONSE_CONTAINS is required when "
                    "CDAC_SMS_VERIFY_RESPONSE is enabled.",
                )
            )
        return problems


@lru_cache(maxsize=1)
def resolve_config() -> CDACConfig:
    """Load the gateway configuration from Django settings, cached."""

    def get(name, default):
        return getattr(settings, name, default)

    return CDACConfig(
        url=get("CDAC_SMS_URL", ""),
        username=get("CDAC_SMS_USERNAME", ""),
        password=get("CDAC_SMS_PASSWORD", ""),
        sender_id=get("CDAC_SMS_SENDER_ID", ""),
        secure_key=get("CDAC_SMS_SECURE_KEY", ""),
        template_id=get("CDAC_SMS_TEMPLATE_ID", ""),
        mobile_prefix=get("CDAC_SMS_MOBILE_PREFIX", ""),
        enabled=get("CDAC_SMS_ENABLED", True),
        timeout=int(get("CDAC_SMS_TIMEOUT", 30)),
        verify_ssl=get("CDAC_SMS_VERIFY_SSL", True),
        success_codes=tuple(int(code) for code in get("CDAC_SMS_SUCCESS_CODES", [200, 201, 202])),
        error_codes=tuple(int(code) for code in get("CDAC_SMS_ERROR_CODES", [])),
        verify_response=get("CDAC_SMS_VERIFY_RESPONSE", False),
        verify_response_contains=get("CDAC_SMS_VERIFY_RESPONSE_CONTAINS", ""),
        print_response=get("CDAC_SMS_PRINT_RESPONSE", True),
        whitelist_numbers=tuple(get("CDAC_SMS_WHITELIST_NUMBERS", [])),
        blacklist_numbers=tuple(get("CDAC_SMS_BLACKLIST_NUMBERS", [])),
        use_default_number=get("CDAC_SMS_USE_DEFAULT_NUMBER", False),
        default_number=get("CDAC_SMS_DEFAULT_NUMBER", ""),
    )


def reset_config_cache() -> None:
    """Clear the cached configuration (needed when overriding settings)."""

    resolve_config.cache_clear()


def is_active_backend() -> bool:
    """Return True when this addon is the configured SMS backend."""

    backends = getattr(settings, "MESSAGING_BACKENDS", {})
    return backends.get("sms") == constants.BACKEND_PATH
