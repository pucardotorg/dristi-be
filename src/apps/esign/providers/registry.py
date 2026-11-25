"""Provider registry and resolution (spec 0038 #4, modelled on apps.payments #9.3).

``ESIGN_PROVIDERS`` maps a name to a dotted path; ``ESIGN_DEFAULT_PROVIDER`` names
the one used when a caller does not choose a ``signing_method``. The deprecated
single ``ESIGN_PROVIDER`` is read into a one-entry registry when ``ESIGN_PROVIDERS``
is unset, so existing deployments keep working.

The golden rule: initiation is the only place that *chooses* a provider; every
step after a transaction exists resolves it with ``get(transaction.provider)`` —
never from settings — so changing configuration never re-routes work in flight.
The anonymous callback is the one exception (it must parse before a transaction
is found): it uses ``get_callback_provider()``, the single registered CALLBACK
provider.
"""

from functools import lru_cache

from django.utils.module_loading import import_string

from .. import conf
from ..exceptions import ESignProviderNotConfigured
from .base import Completion, ESignProvider

# Sentinel key for a deprecated ESIGN_PROVIDER whose class could not be loaded or
# declares no name; kept so get_default() surfaces the real import/validation
# error instead of a bland "nothing registered".
_UNRESOLVED = ""


@lru_cache(maxsize=8)
def _load(name: str, path: str) -> ESignProvider:
    """Import, validate and instantiate the provider registered as ``name``."""

    try:
        provider_class = import_string(path)
    except ImportError as exc:
        raise ESignProviderNotConfigured(f"eSign provider {path!r} could not be imported.") from exc

    if not (isinstance(provider_class, type) and issubclass(provider_class, ESignProvider)):
        raise ESignProviderNotConfigured(
            f"eSign provider {path!r} must be an ESignProvider subclass."
        )
    declared = getattr(provider_class, "name", "")
    if not declared:
        raise ESignProviderNotConfigured(f"eSign provider {path!r} must declare a name.")
    # In the deprecated-alias case the registry key is derived from the class, so
    # it matches by construction; an explicit registry must agree with the class.
    if name != _UNRESOLVED and declared != name:
        raise ESignProviderNotConfigured(
            f"eSign provider {path!r} declares name {declared!r}, but is registered as {name!r}."
        )
    return provider_class()


def _provider_paths() -> dict[str, str]:
    """Name -> dotted path for every registered provider (read live from settings)."""

    configured = conf.providers_setting()
    if configured:
        return configured

    path = conf.provider_path()
    if not path:
        return {}
    try:
        name = getattr(import_string(path), "name", "") or _UNRESOLVED
    except ImportError:
        name = _UNRESOLVED
    return {name: path}


def names() -> list[str]:
    """Every registered provider name."""

    return list(_provider_paths())


def get(name: str) -> ESignProvider:
    """Return the provider registered as ``name``."""

    path = _provider_paths().get(name or _UNRESOLVED)
    if not path:
        raise ESignProviderNotConfigured(f"No eSign provider is registered as {name!r}.")
    return _load(name or _UNRESOLVED, path)


def get_default() -> ESignProvider:
    """Return the provider for initiations that do not name a method."""

    name = conf.default_provider_name()
    if not name:
        registered = names()
        if not registered:
            raise ESignProviderNotConfigured("No eSign provider is configured.")
        if len(registered) > 1:
            raise ESignProviderNotConfigured(
                "ESIGN_DEFAULT_PROVIDER must be set when several providers are registered."
            )
        name = registered[0]
    return get(name)


def get_callback_provider() -> ESignProvider:
    """Return the single registered CALLBACK provider for the anonymous callback.

    The anonymous ``/esign/_signed`` parses the payload before a transaction is
    found, so it cannot resolve the parser from ``transaction.provider``. There
    must be exactly one CALLBACK provider; a second callback ESP needs its own
    route (spec 0038 #4.5, #11.1).
    """

    matches = [p for p in (get(name) for name in names()) if Completion.CALLBACK in p.completion]
    if not matches:
        raise ESignProviderNotConfigured("No callback-completed eSign provider is registered.")
    if len(matches) > 1:
        raise ESignProviderNotConfigured(
            "More than one CALLBACK eSign provider is registered; the anonymous callback "
            "cannot choose a parser. Give each callback provider its own route."
        )
    return matches[0]


def get_provider() -> ESignProvider:
    """Deprecated alias for :func:`get_default` (kept for existing callers/tests)."""

    return get_default()


def reset_provider_cache() -> None:
    """Clear the resolved-provider cache (needed when overriding settings)."""

    _load.cache_clear()
