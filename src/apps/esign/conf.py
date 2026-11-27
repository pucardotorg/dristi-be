"""Typed access to the ``ESIGN_*`` settings (spec 0015 #11).

The defaults repeat those declared in ``config.settings.base`` so that a
deployment which has not yet added the block — or a test that overrides one
value — still gets the documented behaviour.
"""

from datetime import timedelta

from django.conf import settings

DEFAULT_PROVIDER = "apps.esign.providers.mock.MockESignProvider"
DEFAULT_TRANSACTION_TTL = 900
DEFAULT_CALLBACK_GRACE_PERIOD = 300
DEFAULT_SIGNING_STUCK_TIMEOUT = 300
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_PLACEHOLDER_RETENTION_DAYS = 7
DEFAULT_CALLBACK_THROTTLE_RATE = "60/min"
DEFAULT_CALLBACK_MAX_BODY_BYTES = 262144
DEFAULT_MAX_CLIENT_SIGNATURE_BYTES = 262144


def provider_path() -> str:
    """Dotted path of the active provider class (deprecated single-provider alias)."""

    return getattr(settings, "ESIGN_PROVIDER", DEFAULT_PROVIDER) or ""


def providers_setting() -> dict:
    """The ``ESIGN_PROVIDERS`` registry (name -> dotted path), possibly empty.

    When unset, the registry falls back to the deprecated single ``ESIGN_PROVIDER``
    (spec 0038 #4), so existing deployments keep working unchanged.
    """

    return dict(getattr(settings, "ESIGN_PROVIDERS", {}) or {})


def default_provider_name() -> str:
    """Name used for initiations that do not name a ``signing_method``."""

    return getattr(settings, "ESIGN_DEFAULT_PROVIDER", "") or ""


def enabled_methods() -> list[str] | None:
    """Signing methods offered to callers, or ``None`` to allow every registered one.

    Per-state ``signingMethods`` (SGM-05) narrow this; absent that, a deployment
    may still pin the list with ``ESIGN_ENABLED_METHODS``.
    """

    value = getattr(settings, "ESIGN_ENABLED_METHODS", None)
    return list(value) if value else None


def max_client_signature_bytes() -> int:
    """Largest client-supplied PKCS#7 accepted at ``_complete``; ``0`` disables the limit."""

    return int(
        getattr(
            settings,
            "ESIGN_MAX_CLIENT_SIGNATURE_BYTES",
            DEFAULT_MAX_CLIENT_SIGNATURE_BYTES,
        )
    )


def is_enabled() -> bool:
    """Whether initiation is allowed at all."""

    return bool(getattr(settings, "ESIGN_ENABLED", True))


def transaction_ttl() -> timedelta:
    """How long a ``PENDING`` transaction waits for its callback."""

    return timedelta(
        seconds=int(getattr(settings, "ESIGN_TRANSACTION_TTL", DEFAULT_TRANSACTION_TTL))
    )


def callback_grace_period() -> timedelta:
    """How late a callback may arrive after ``expires_at``."""

    return timedelta(
        seconds=int(getattr(settings, "ESIGN_CALLBACK_GRACE_PERIOD", DEFAULT_CALLBACK_GRACE_PERIOD))
    )


def signing_stuck_timeout() -> timedelta:
    """How long a row may sit in ``SIGNING`` before reconciliation."""

    return timedelta(
        seconds=int(getattr(settings, "ESIGN_SIGNING_STUCK_TIMEOUT", DEFAULT_SIGNING_STUCK_TIMEOUT))
    )


def max_attempts() -> int:
    """Maximum ESP attempts per source document."""

    return int(getattr(settings, "ESIGN_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS))


def placeholder_retention() -> timedelta:
    """How long placeholder PDFs of terminal transactions are kept."""

    return timedelta(
        days=int(
            getattr(
                settings,
                "ESIGN_PLACEHOLDER_RETENTION",
                DEFAULT_PLACEHOLDER_RETENTION_DAYS,
            )
        )
    )


def ui_redirect_url() -> str:
    """Server-side allow-listed redirect target for the callback."""

    return getattr(settings, "ESIGN_UI_REDIRECT_URL", "") or ""


def callback_throttle_rate() -> str:
    """DRF throttle rate for the public callback; empty disables throttling."""

    return getattr(settings, "ESIGN_CALLBACK_THROTTLE_RATE", DEFAULT_CALLBACK_THROTTLE_RATE) or ""


def callback_max_body_bytes() -> int:
    """Largest callback body accepted; ``0`` disables the limit."""

    return int(getattr(settings, "ESIGN_CALLBACK_MAX_BODY_BYTES", DEFAULT_CALLBACK_MAX_BODY_BYTES))


def system_actor_id() -> str:
    """Actor recorded against uploads when no signer is set (spec 0015 #4.2)."""

    return getattr(settings, "ESIGN_SYSTEM_ACTOR_ID", "system") or "system"


def entity_authorizers() -> dict:
    """Mapping of ``EntityType`` value to a dotted path authorizer callable."""

    return dict(getattr(settings, "ESIGN_ENTITY_AUTHORIZERS", {}) or {})
