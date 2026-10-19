"""Configuration store services and exceptions.

Consumers read runtime configuration through these functions and never query
``Configuration.objects`` directly, so the active-only rule, normalization,
and caching stay in one place. Read values at the point of use, not at import
time, or admin edits will not be picked up.
"""

import json
from collections.abc import Callable
from typing import Any

from django.core.exceptions import ValidationError

from .models import Configuration, normalize_config_name
from .validators import coerce_integer

_UNSET = object()

_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
_FALSE_VALUES = frozenset({"false", "0", "no", "off"})


class ConfigurationError(Exception):
    """Base class for configuration store errors."""


class ConfigurationNotFound(ConfigurationError):  # noqa: N818
    """Raised when a key is missing or inactive and no default was given."""


class ConfigurationValueError(ConfigurationError):
    """Raised when a stored value cannot be parsed into the requested type."""


def _lookup(config_set: str, config_key: str) -> str | None:
    """Return the active value for a set/key, or ``None`` when absent."""
    return (
        Configuration.objects.active()
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
    config_set: str, config_key: str, default: Any, parse: Callable[[str], Any], type_name: str
) -> Any:
    """Return the parsed value; a malformed value raises instead of using ``default``."""
    value = _lookup(config_set, config_key)
    if value is None:
        return _missing(config_set, config_key, default)
    try:
        return parse(value)
    except (ValidationError, ValueError) as exc:
        raise ConfigurationValueError(
            f"Configuration {config_set}.{config_key} is not a valid {type_name}: {value!r}."
        ) from exc


def get(config_set: str, config_key: str, default: Any = _UNSET) -> str:
    """Return the raw string value of an active entry."""
    value = _lookup(config_set, config_key)
    if value is None:
        return _missing(config_set, config_key, default)
    return value


def get_set(config_set: str) -> dict[str, str]:
    """Return ``{config_key: config_value}`` for the active entries of a set."""
    return dict(
        Configuration.objects.active()
        .filter(config_set=normalize_config_name(config_set))
        .values_list("config_key", "config_value")
    )


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(value)


def get_int(config_set: str, config_key: str, default: Any = _UNSET) -> int:
    """Return an active entry parsed as an integer."""
    return _get_parsed(config_set, config_key, default, coerce_integer, "integer")


def get_bool(config_set: str, config_key: str, default: Any = _UNSET) -> bool:
    """Return an active entry parsed as a boolean (true/false, 1/0, yes/no, on/off)."""
    return _get_parsed(config_set, config_key, default, _parse_bool, "boolean")


def get_json(config_set: str, config_key: str, default: Any = _UNSET) -> Any:
    """Return an active entry parsed as JSON."""
    return _get_parsed(config_set, config_key, default, json.loads, "JSON value")


class ConfigurationService:
    """Namespace for the configuration read functions."""

    get = staticmethod(get)
    get_set = staticmethod(get_set)
    get_int = staticmethod(get_int)
    get_bool = staticmethod(get_bool)
    get_json = staticmethod(get_json)
