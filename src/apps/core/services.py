"""Configuration store services and exceptions.

Consumers read runtime configuration through these functions and never query
``Configuration.objects`` (spec 0018) or ``PublicConfiguration.objects``
(spec 0034) directly, so the active-only rule, normalization, and caching stay
in one place. Read values at the point of use, not at import time, or admin
edits will not be picked up.
"""

import json
from collections.abc import Callable
from typing import Any

from django.core.exceptions import ValidationError

from .models import Configuration, PublicConfiguration, normalize_config_name
from .validators import coerce_integer, parse_config_bool

_UNSET = object()


class ConfigurationError(Exception):
    """Base class for configuration store errors."""


class ConfigurationNotFound(ConfigurationError):  # noqa: N818
    """Raised when a key is missing or inactive and no default was given."""


class ConfigurationValueError(ConfigurationError):
    """Raised when a stored value cannot be parsed into the requested type."""


def _lookup(config_set: str, config_key: str, model=Configuration) -> str | None:
    """Return the active value for a set/key, or ``None`` when absent."""
    return (
        model.objects.active()
        .filter(
            config_set=normalize_config_name(config_set),
            config_key=normalize_config_name(config_key),
        )
        .values_list("config_value", flat=True)
        .first()
    )


def _missing(config_set: str, config_key: str, default: Any) -> Any:
    """Return ``default``, or raise when the caller did not supply one."""
    if default is _UNSET:
        raise ConfigurationNotFound(f"No active configuration for {config_set}.{config_key}.")
    return default


def _get_parsed(
    config_set: str,
    config_key: str,
    default: Any,
    parse: Callable[[str], Any],
    type_name: str,
    model=Configuration,
) -> Any:
    """Return the parsed value; a malformed value raises instead of using ``default``."""
    value = _lookup(config_set, config_key, model)
    if value is None:
        return _missing(config_set, config_key, default)
    try:
        return parse(value)
    except (ValidationError, ValueError) as exc:
        raise ConfigurationValueError(
            f"Configuration {config_set}.{config_key} is not a valid {type_name}: {value!r}."
        ) from exc


def _get_raw(config_set: str, config_key: str, default: Any, model) -> str:
    value = _lookup(config_set, config_key, model)
    if value is None:
        return _missing(config_set, config_key, default)
    return value


def _get_set(config_set: str, model) -> dict[str, str]:
    return dict(
        model.objects.active()
        .filter(config_set=normalize_config_name(config_set))
        .values_list("config_key", "config_value")
    )


def get(config_set: str, config_key: str, default: Any = _UNSET) -> str:
    """Return the raw string value of an active entry."""
    return _get_raw(config_set, config_key, default, Configuration)


def get_set(config_set: str) -> dict[str, str]:
    """Return ``{config_key: config_value}`` for the active entries of a set."""
    return _get_set(config_set, Configuration)


def get_int(config_set: str, config_key: str, default: Any = _UNSET) -> int:
    """Return an active entry parsed as an integer."""
    return _get_parsed(config_set, config_key, default, coerce_integer, "integer")


def get_bool(config_set: str, config_key: str, default: Any = _UNSET) -> bool:
    """Return an active entry parsed as a boolean (true/false, 1/0, yes/no, on/off)."""
    return _get_parsed(config_set, config_key, default, parse_config_bool, "boolean")


def get_json(config_set: str, config_key: str, default: Any = _UNSET) -> Any:
    """Return an active entry parsed as JSON."""
    return _get_parsed(config_set, config_key, default, json.loads, "JSON value")


# Public configuration (spec 0034): the same rules, reading only PublicConfiguration.


def get_public(config_set: str, config_key: str, default: Any = _UNSET) -> str:
    """Return the raw string value of an active public entry."""
    return _get_raw(config_set, config_key, default, PublicConfiguration)


def get_public_set(config_set: str) -> dict[str, str]:
    """Return ``{config_key: config_value}`` for the active public entries of a set."""
    return _get_set(config_set, PublicConfiguration)


def get_public_int(config_set: str, config_key: str, default: Any = _UNSET) -> int:
    """Return an active public entry parsed as an integer."""
    return _get_parsed(
        config_set, config_key, default, coerce_integer, "integer", PublicConfiguration
    )


def get_public_bool(config_set: str, config_key: str, default: Any = _UNSET) -> bool:
    """Return an active public entry parsed as a boolean (true/false, 1/0, yes/no, on/off)."""
    return _get_parsed(
        config_set, config_key, default, parse_config_bool, "boolean", PublicConfiguration
    )


def get_public_json(config_set: str, config_key: str, default: Any = _UNSET) -> Any:
    """Return an active public entry parsed as JSON."""
    return _get_parsed(
        config_set, config_key, default, json.loads, "JSON value", PublicConfiguration
    )


class ConfigurationService:
    """Namespace for the configuration read functions."""

    get = staticmethod(get)
    get_set = staticmethod(get_set)
    get_int = staticmethod(get_int)
    get_bool = staticmethod(get_bool)
    get_json = staticmethod(get_json)


class PublicConfigurationService:
    """Namespace for the public configuration read functions."""

    get_public = staticmethod(get_public)
    get_public_set = staticmethod(get_public_set)
    get_public_int = staticmethod(get_public_int)
    get_public_bool = staticmethod(get_public_bool)
    get_public_json = staticmethod(get_public_json)
