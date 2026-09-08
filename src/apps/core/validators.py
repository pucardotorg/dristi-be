"""Validation and coercion utilities for additional attributes."""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date, parse_datetime

ATTRIBUTE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
VALID_DATA_TYPES = [
    "integer",
    "float",
    "number",
    "character",
    "boolean",
    "datetime",
    "date",
    "json",
]
DATA_TYPE_CHOICES = [(dt, dt) for dt in VALID_DATA_TYPES]


def validate_attribute_name(name: str) -> None:
    """Validate an attribute name against the project naming convention."""
    if not ATTRIBUTE_NAME_PATTERN.match(name):
        raise ValidationError(
            "Attribute name must start with a lowercase letter and contain only "
            "lowercase letters, numbers, and underscores."
        )


def validate_data_type(data_type: str) -> None:
    """Validate that the supplied data type is supported."""
    if data_type not in VALID_DATA_TYPES:
        raise ValidationError(
            f"Unsupported data type: {data_type!r}. Must be one of {', '.join(VALID_DATA_TYPES)}."
        )


def coerce_boolean(value: Any) -> bool:
    """Coerce a value to a boolean according to the project rules."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValidationError(f"Cannot coerce {value!r} to boolean.")


def coerce_integer(value: Any) -> int:
    """Coerce a value to an integer, rejecting bools and non-numeric data."""
    if isinstance(value, bool):
        raise ValidationError(f"Cannot coerce boolean {value!r} to integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise ValidationError(f"Cannot coerce non-whole float {value!r} to integer.")
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        raise ValidationError(f"Cannot coerce non-whole decimal {value!r} to integer.")
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError as exc:
            raise ValidationError(f"Cannot coerce {value!r} to integer.") from exc
        if parsed.is_integer():
            return int(parsed)
        raise ValidationError(f"Cannot coerce non-whole number {value!r} to integer.")
    raise ValidationError(f"Cannot coerce {value!r} to integer.")


def coerce_float(value: Any) -> float:
    """Coerce a value to a float, rejecting bools and non-numeric data."""
    if isinstance(value, bool):
        raise ValidationError(f"Cannot coerce boolean {value!r} to float.")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise ValidationError(f"Cannot coerce {value!r} to float.") from exc
    raise ValidationError(f"Cannot coerce {value!r} to float.")


def coerce_number(value: Any) -> int | float:
    """Coerce a value to a number, preserving int/float where possible."""
    if isinstance(value, bool):
        raise ValidationError(f"Cannot coerce boolean {value!r} to number.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError as exc:
            raise ValidationError(f"Cannot coerce {value!r} to number.") from exc
        if parsed.is_integer() and not ("e" in value.lower() or "." in value):
            return int(parsed)
        return parsed
    raise ValidationError(f"Cannot coerce {value!r} to number.")


def coerce_character(value: Any) -> str:
    """Coerce a value to a string."""
    if value is None:
        raise ValidationError("Cannot coerce None to character.")
    return str(value)


def coerce_datetime(value: Any) -> str:
    """Coerce a value to an ISO 8601 datetime string."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        if "T" not in value and " " not in value:
            raise ValidationError(f"Cannot parse {value!r} as datetime.")
        parsed = parse_datetime(value)
        if parsed is None:
            raise ValidationError(f"Cannot parse {value!r} as datetime.")
        return parsed.isoformat()
    raise ValidationError(f"Cannot coerce {value!r} to datetime.")


def coerce_date(value: Any) -> str:
    """Coerce a value to an ISO 8601 date string."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        parsed = parse_date(value)
        if parsed is None:
            raise ValidationError(f"Cannot parse {value!r} as date.")
        return parsed.isoformat()
    raise ValidationError(f"Cannot coerce {value!r} to date.")


def coerce_json(value: Any) -> Any:
    """Validate that a value can be serialized as JSON."""
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Cannot serialize {value!r} as JSON: {exc}") from exc
    return value


def coerce_value(value: Any, data_type: str) -> Any:
    """Coerce ``value`` to the requested ``data_type``."""
    validate_data_type(data_type)
    dispatch = {
        "integer": coerce_integer,
        "float": coerce_float,
        "number": coerce_number,
        "character": coerce_character,
        "boolean": coerce_boolean,
        "datetime": coerce_datetime,
        "date": coerce_date,
        "json": coerce_json,
    }
    return dispatch[data_type](value)


def validate_default_value(default_value: Any, data_type: str) -> None:
    """Validate that ``default_value`` is valid for the given ``data_type``."""
    validate_data_type(data_type)
    coerce_value(default_value, data_type)
