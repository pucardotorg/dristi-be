"""Startup validation of the payment provider settings (spec 0017 #9.3).

Run before ``runserver``, ``migrate`` and every management command, so a
misconfigured deployment fails at boot rather than on a payer's first click.
"""

from django.conf import settings
from django.core.checks import Error, register

from . import conf
from .providers import registry
from .providers.base import ProviderNotConfigured

POSITIVE_INT_SETTINGS = (
    "PAYMENT_STATUS_POLL_INTERVAL_SECONDS",
    "PAYMENT_STATUS_POLL_MAX_INTERVAL_SECONDS",
    "PAYMENT_STATUS_POLL_BATCH_SIZE",
    "PAYMENT_BATCH_MAX_DEMANDS",
)


def is_production_settings() -> bool:
    """Whether the process runs on the production settings module."""

    return str(getattr(settings, "SETTINGS_MODULE", "")).endswith("production")


@register()
def check_payment_settings(app_configs, **kwargs):
    """Validate the provider registry, the default provider and the production guards."""

    messages = []

    for name in POSITIVE_INT_SETTINGS:
        value = getattr(settings, name, None)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            messages.append(
                Error(
                    f"{name} must be an integer of at least 1, got {value!r}.",
                    id=f"payments.E001.{name}",
                )
            )

    providers = conf.providers()
    for name in providers:
        try:
            registry.get(name)
        except ProviderNotConfigured as exc:
            messages.append(
                Error(
                    str(exc),
                    hint=f"PAYMENT_PROVIDERS[{name!r}] must name an importable "
                    "PaymentProvider subclass whose `name` is the same key.",
                    id="payments.E002",
                )
            )

    default = conf.default_provider()
    if default and default not in providers:
        messages.append(
            Error(
                f"PAYMENT_DEFAULT_PROVIDER {default!r} is not a key of PAYMENT_PROVIDERS.",
                id="payments.E003",
            )
        )

    redirect_url = conf.ui_redirect_url()
    if redirect_url and not redirect_url.startswith(("http://", "https://")):
        messages.append(
            Error("PAYMENT_UI_REDIRECT_URL must be an absolute URL.", id="payments.E004")
        )

    if is_production_settings():
        if any(path == conf.MOCK_PROVIDER_PATH for path in providers.values()):
            messages.append(
                Error(
                    "The mock payment provider must not be registered in production.",
                    hint="Remove it from PAYMENT_PROVIDERS.",
                    id="payments.E005",
                )
            )
        if default and not redirect_url.startswith("https://"):
            messages.append(
                Error(
                    "PAYMENT_UI_REDIRECT_URL must be an https:// URL in production.",
                    id="payments.E006",
                )
            )

    return messages
