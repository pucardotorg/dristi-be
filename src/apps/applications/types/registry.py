"""Type code -> spec (spec 0033 #3.2).

Specs register at import (``types/__init__.py``). A second spec for a code is
refused, so two modules can never claim one type.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import ApplicationTypeSpec

_REGISTRY: dict[str, ApplicationTypeSpec] = {}


def register(spec: ApplicationTypeSpec) -> ApplicationTypeSpec:
    """Register ``spec`` under its code; raise if the code is taken."""
    if spec.code in _REGISTRY:
        raise ImproperlyConfigured(f"Application type {spec.code} is already registered.")
    _REGISTRY[spec.code] = spec
    return spec


def get(code: str) -> ApplicationTypeSpec | None:
    return _REGISTRY.get(code)


def require(code: str) -> ApplicationTypeSpec:
    spec = _REGISTRY.get(code)
    if spec is None:
        raise ImproperlyConfigured(f"No application type spec for {code}.")
    return spec


def codes() -> list[str]:
    return sorted(_REGISTRY)
