"""Typed access to the ``PAYMENT_*`` settings (spec 0017 #17).

The defaults repeat those declared in ``config.settings.base`` so a test that
overrides one value, or a deployment without the block, still gets the
documented behaviour.
"""

from django.conf import settings

MOCK_PROVIDER_PATH = "apps.payments.providers.mock.MockPaymentProvider"
DEFAULT_PROVIDERS = {"mock": MOCK_PROVIDER_PATH}
DEFAULT_CURRENCY = "INR"
DEFAULT_CALLBACK_THROTTLE_RATE = "60/min"
DEFAULT_CALLBACK_MAX_BODY_BYTES = 65536
DEFAULT_POLL_INTERVAL_SECONDS = 300
DEFAULT_POLL_MAX_INTERVAL_SECONDS = 21600
DEFAULT_POLL_BATCH_SIZE = 200
DEFAULT_BATCH_MAX_DEMANDS = 50


def providers() -> dict[str, str]:
    """Provider name to dotted path."""

    return dict(getattr(settings, "PAYMENT_PROVIDERS", DEFAULT_PROVIDERS) or {})


def default_provider() -> str:
    """Name of the provider new payments are initiated with; empty for none."""

    return getattr(settings, "PAYMENT_DEFAULT_PROVIDER", "") or ""


def default_currency() -> str:
    """Currency a demand is raised in when the caller names none."""

    return getattr(settings, "PAYMENT_DEFAULT_CURRENCY", DEFAULT_CURRENCY) or DEFAULT_CURRENCY


def ui_redirect_url() -> str:
    """Server-side redirect target of the provider callback."""

    return getattr(settings, "PAYMENT_UI_REDIRECT_URL", "") or ""


def callback_throttle_rate() -> str:
    """Per-IP rate of the public callback; empty disables throttling."""

    return getattr(settings, "PAYMENT_CALLBACK_THROTTLE_RATE", DEFAULT_CALLBACK_THROTTLE_RATE) or ""


def callback_max_body_bytes() -> int:
    """Largest callback body accepted; ``0`` disables the limit."""

    return int(
        getattr(settings, "PAYMENT_CALLBACK_MAX_BODY_BYTES", DEFAULT_CALLBACK_MAX_BODY_BYTES)
    )


def poll_interval_seconds() -> int:
    """First status-poll interval."""

    return int(
        getattr(settings, "PAYMENT_STATUS_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS)
    )


def poll_max_interval_seconds() -> int:
    """Cap of the doubling poll interval."""

    return int(
        getattr(
            settings, "PAYMENT_STATUS_POLL_MAX_INTERVAL_SECONDS", DEFAULT_POLL_MAX_INTERVAL_SECONDS
        )
    )


def poll_batch_size() -> int:
    """Payments examined per poller run."""

    return int(getattr(settings, "PAYMENT_STATUS_POLL_BATCH_SIZE", DEFAULT_POLL_BATCH_SIZE))


def batch_max_demands() -> int:
    """Most demands one cross-demand payment may cover."""

    return int(getattr(settings, "PAYMENT_BATCH_MAX_DEMANDS", DEFAULT_BATCH_MAX_DEMANDS))


def mock_callback_base_url() -> str:
    """Origin the mock provider's form posts to; empty posts to a relative path."""

    return getattr(settings, "PAYMENT_MOCK_CALLBACK_BASE_URL", "") or ""
