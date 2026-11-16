"""Settings-driven provider lookup and routing (spec 0017 #9.3, spec 0032 #4.2).

``get_default()`` and ``get_for_new_payment()`` are used only to initiate a new
payment; every callback, poll, cancel and attestation goes through
``get(payment.provider)``, so changing the default or the selectable list never
re-routes a payment already in flight.
"""

from functools import lru_cache

from django.utils.module_loading import import_string

from apps.api.errors import BusinessError

from .. import conf, errors
from .base import ConfirmationMode, PaymentProvider, ProviderNotConfigured


@lru_cache(maxsize=16)
def _load(name: str, path: str) -> PaymentProvider:
    """Import, validate and instantiate the provider at ``path``."""

    try:
        provider_class = import_string(path)
    except ImportError as exc:
        raise ProviderNotConfigured(
            f"Payment provider {name!r} ({path!r}) cannot be imported."
        ) from exc

    if not (isinstance(provider_class, type) and issubclass(provider_class, PaymentProvider)):
        raise ProviderNotConfigured(
            f"Payment provider {name!r} ({path!r}) must be a PaymentProvider subclass."
        )
    if getattr(provider_class, "name", "") != name:
        raise ProviderNotConfigured(
            f"Payment provider {path!r} declares name "
            f"{getattr(provider_class, 'name', '')!r}, but is registered as {name!r}."
        )
    return provider_class()


def names() -> list[str]:
    """Every registered provider name."""

    return list(conf.providers())


def get(name: str) -> PaymentProvider:
    """Return the provider registered as ``name``."""

    path = conf.providers().get(name or "")
    if not path:
        raise ProviderNotConfigured(f"No payment provider is registered as {name!r}.")
    return _load(name, path)


def get_default() -> PaymentProvider | None:
    """Return the provider for new payments, or ``None`` when none is configured."""

    name = conf.default_provider()
    if not name:
        return None
    return get(name)


def selectable_names() -> list[str]:
    """Names a payer may choose for a new payment, in order; the default when unset."""

    names = conf.selectable_providers()
    if names:
        return list(dict.fromkeys(names))
    default = conf.default_provider()
    return [default] if default else []


def selectable() -> list[PaymentProvider]:
    """The providers a payer may choose for a new payment, in order."""

    return [get(name) for name in selectable_names()]


def get_for_new_payment(name: str | None) -> PaymentProvider | None:
    """The provider to initiate a new payment with (spec 0032 #4.2).

    An empty ``name`` means the default (``None`` when no default is set). A
    name outside the selectable list is refused with ``E06023``.
    """

    name = (name or "").strip()
    if not name:
        return get_default()
    if name not in selectable_names():
        raise BusinessError(errors.PROVIDER_NOT_AVAILABLE, field="provider")
    return get(name)


def is_attested(name: str) -> bool:
    """Whether ``name`` is a registered provider completed by attestation."""

    try:
        return get(name).confirmation == ConfirmationMode.ATTESTED
    except ProviderNotConfigured:
        return False


def attested_names() -> list[str]:
    """Registered providers whose payments are completed by attestation (spec 0032 #4.7)."""

    return [name for name in names() if is_attested(name)]


def reset_cache() -> None:
    """Forget resolved providers (needed when overriding settings in tests)."""

    _load.cache_clear()
