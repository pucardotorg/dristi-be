"""Startup validation of the ``ESIGN_*`` settings (spec 0015 #11.1).

Django runs registered checks before ``runserver``, ``migrate`` and every
management command, so a container with a misconfigured eSign module fails fast
instead of failing on a user's first signature.
"""

from django.conf import settings
from django.core.checks import Error, register

from . import conf
from .exceptions import ESignProviderNotConfigured
from .providers import get_provider
from .providers.mock import MockESignProvider

POSITIVE_INT_SETTINGS = (
    "ESIGN_TRANSACTION_TTL",
    "ESIGN_CALLBACK_GRACE_PERIOD",
    "ESIGN_SIGNING_STUCK_TIMEOUT",
    "ESIGN_MAX_ATTEMPTS",
    "ESIGN_PLACEHOLDER_RETENTION",
)


def is_production_settings() -> bool:
    """Whether the process is running on the production settings module."""

    return str(getattr(settings, "SETTINGS_MODULE", "")).endswith("production")


@register()
def check_esign_settings(app_configs, **kwargs):
    """Validate the domain settings and the production guards."""

    messages = []

    for name in POSITIVE_INT_SETTINGS:
        value = getattr(settings, name, None)
        if value is None:
            continue
        # bool is a subclass of int, and True would pass a naive check.
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            messages.append(
                Error(
                    f"{name} must be an integer of at least 1, got {value!r}.",
                    hint=f"Set {name} in settings or the environment.",
                    id=f"esign.E001.{name}",
                )
            )

    if not conf.is_enabled():
        # The kill switch is on: nothing below can be exercised.
        return messages

    provider = None
    try:
        provider = get_provider()
    except ESignProviderNotConfigured as exc:
        messages.append(
            Error(
                str(exc),
                hint="Set ESIGN_PROVIDER to an importable ESignProvider subclass.",
                id="esign.E002",
            )
        )

    redirect_url = conf.ui_redirect_url()
    if redirect_url and not redirect_url.startswith(("http://", "https://")):
        messages.append(
            Error(
                "ESIGN_UI_REDIRECT_URL must be an absolute URL.",
                id="esign.E003",
            )
        )
    if is_production_settings():
        if isinstance(provider, MockESignProvider):
            messages.append(
                Error(
                    "The mock eSign provider must not be active in production.",
                    hint="Set ESIGN_PROVIDER to a real provider, e.g. "
                    "addon.cdac_esign.provider.CDACESignProvider.",
                    id="esign.E004",
                )
            )
        if not redirect_url:
            messages.append(
                Error(
                    "ESIGN_UI_REDIRECT_URL is required in production.",
                    id="esign.E005",
                )
            )
        elif not redirect_url.startswith("https://"):
            messages.append(
                Error(
                    "ESIGN_UI_REDIRECT_URL must be an https:// URL in production.",
                    id="esign.E006",
                )
            )

    return messages
