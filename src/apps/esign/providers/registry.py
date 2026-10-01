"""Resolution of the active provider from ``ESIGN_PROVIDER`` (spec 0015 #3)."""

from functools import lru_cache

from django.utils.module_loading import import_string

from .. import conf
from ..exceptions import ESignProviderNotConfigured
from .base import ESignProvider


@lru_cache(maxsize=4)
def _load(path: str) -> ESignProvider:
    """Import, validate and instantiate the provider at ``path``."""

    try:
        provider_class = import_string(path)
    except ImportError as exc:
        raise ESignProviderNotConfigured(f"ESIGN_PROVIDER {path!r} could not be imported.") from exc

    if not (isinstance(provider_class, type) and issubclass(provider_class, ESignProvider)):
        raise ESignProviderNotConfigured(
            f"ESIGN_PROVIDER {path!r} must be an ESignProvider subclass."
        )
    if not getattr(provider_class, "name", ""):
        raise ESignProviderNotConfigured(f"ESIGN_PROVIDER {path!r} must declare a name.")

    return provider_class()


def get_provider() -> ESignProvider:
    """Return the configured provider instance."""

    path = conf.provider_path()
    if not path:
        raise ESignProviderNotConfigured("ESIGN_PROVIDER is not set.")
    return _load(path)


def reset_provider_cache() -> None:
    """Clear the resolved-provider cache (needed when overriding settings)."""

    _load.cache_clear()
