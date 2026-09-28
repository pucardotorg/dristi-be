"""Startup validation of the registration settings.

Django runs registered checks before runserver, migrate and every management
command, so a misconfigured value stops the process instead of surfacing as an
open rate limit in production.
"""

from django.conf import settings
from django.core.checks import Error, register

# Settings that must each be an integer of at least 1.
POSITIVE_INT_SETTINGS = (
    "OTP_RESEND_COOLDOWN_SECONDS",
    "OTP_TTL_SECONDS",
    "OTP_LENGTH",
    "CURRENT_TERMS_VERSION",
)


def check_positive_int_setting(name):
    """Return an Error if the named setting is not an int of at least 1, else None."""
    value = getattr(settings, name, None)
    # bool is a subclass of int, and True would pass a naive check.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return Error(
            f"{name} must be an integer of at least 1, got {value!r}.",
            hint=f"Set {name} in settings or the environment.",
            id=f"users.E001.{name}",
        )
    return None


@register()
def check_registration_settings(app_configs, **kwargs):
    """Validate the OTP and terms settings."""
    results = (check_positive_int_setting(name) for name in POSITIVE_INT_SETTINGS)
    return [error for error in results if error is not None]
