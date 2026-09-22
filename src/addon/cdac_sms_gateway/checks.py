"""Django system checks for the CDAC gateway configuration."""

import re

from django.conf import settings
from django.core.checks import Error, Warning, register

from .config import is_active_backend, resolve_config
from .filtering import compile_pattern

_CODE_IDS = {
    "CDAC_SMS_URL": "cdac_sms.E002",
    "CDAC_SMS_USERNAME": "cdac_sms.E001",
    "CDAC_SMS_PASSWORD": "cdac_sms.E001",
    "CDAC_SMS_SENDER_ID": "cdac_sms.E001",
    "CDAC_SMS_SECURE_KEY": "cdac_sms.E001",
    "CDAC_SMS_DEFAULT_NUMBER": "cdac_sms.E003",
    "CDAC_SMS_VERIFY_RESPONSE_CONTAINS": "cdac_sms.E004",
}


@register()
def check_cdac_sms_configuration(app_configs, **kwargs):
    """Validate gateway settings when CDAC is the active SMS backend."""

    if not is_active_backend():
        return []

    cfg = resolve_config()
    if not cfg.enabled:
        return []

    messages = [
        Error(message, id=_CODE_IDS.get(setting_name, "cdac_sms.E001"))
        for setting_name, message in cfg.validate()
    ]

    for pattern in tuple(cfg.whitelist_numbers) + tuple(cfg.blacklist_numbers):
        try:
            compile_pattern(pattern)
        except re.error as exc:
            messages.append(
                Error(
                    f"Invalid recipient pattern '{pattern}': {exc}",
                    id="cdac_sms.E005",
                )
            )

    time_limit_ms = getattr(settings, "MESSAGING_TASK_TIME_LIMIT", 600000)
    if cfg.timeout * 1000 >= time_limit_ms:
        messages.append(
            Error(
                f"CDAC_SMS_TIMEOUT ({cfg.timeout}s) must be below the messaging actor "
                f"time limit MESSAGING_TASK_TIME_LIMIT ({time_limit_ms}ms).",
                id="cdac_sms.E006",
            )
        )

    if cfg.use_default_number:
        messages.append(
            Warning(
                "CDAC_SMS_USE_DEFAULT_NUMBER redirects every SMS to "
                "CDAC_SMS_DEFAULT_NUMBER. Non-production use only.",
                id="cdac_sms.W001",
            )
        )

    if not cfg.verify_ssl:
        messages.append(
            Warning(
                "CDAC_SMS_VERIFY_SSL is disabled; gateway certificates are not "
                "verified. Non-production use only.",
                id="cdac_sms.W002",
            )
        )

    return messages
