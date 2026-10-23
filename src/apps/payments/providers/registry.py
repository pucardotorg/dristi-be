"""Settings-driven provider lookup and routing (spec 0017 #9.3).

``get_default()`` is used only to initiate a new payment; every callback, poll
and cancel goes through ``get(payment.provider)``, so changing the default
never re-routes a payment already in flight.
"""

from functools import lru_cache

from django.utils.module_loading import import_string

from .. import conf
from .base import PaymentProvider, ProviderNotConfigured


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


def reset_cache() -> None:
    """Forget resolved providers (needed when overriding settings in tests)."""

    _load.cache_clear()
