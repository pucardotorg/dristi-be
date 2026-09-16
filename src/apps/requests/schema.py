"""Minimal JSON-schema style validation for ``Request.data``.

The project has no ``jsonschema`` dependency, so this module implements the
small subset of JSON Schema the request types actually need: ``type``,
``required``, ``properties``, ``additionalProperties``, ``enum``, string
``minLength`` / ``maxLength`` / ``pattern``, numeric ``minimum`` /
``maximum`` and array ``items`` / ``minItems`` / ``maxItems``.
"""

import re
from typing import Any

JSON_TYPE_CHECKS = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "boolean": lambda value: isinstance(value, bool),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, int | float) and not isinstance(value, bool),
    "null": lambda value: value is None,
}


class SchemaValidationError(Exception):
    """Raised when a payload does not satisfy its request type's schema."""

    def __init__(self, errors: list[str]):
        """Store the collected human-readable error messages."""
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_against_schema(schema: dict | None, data: Any) -> None:
    """Validate ``data`` against ``schema``, raising ``SchemaValidationError``."""
    errors = _validate(schema or {}, data, "")
    if errors:
        raise SchemaValidationError(errors)


def _label(path: str) -> str:
    """Return a readable label for a JSON pointer-ish path."""
    return path or "attributes"


def _validate(schema: dict, value: Any, path: str) -> list[str]:
    """Return a list of validation errors for ``value`` against ``schema``."""
    if not isinstance(schema, dict) or not schema:
        return []

    errors: list[str] = []

    expected_types = schema.get("type")
    if expected_types is not None:
        if isinstance(expected_types, str):
            expected_types = [expected_types]
        if not any(JSON_TYPE_CHECKS.get(t, lambda _: True)(value) for t in expected_types):
            return [f"{_label(path)}: expected type {' or '.join(expected_types)}."]

    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(repr(option) for option in schema["enum"])
        errors.append(f"{_label(path)}: must be one of {allowed}.")

    if isinstance(value, str):
        errors.extend(_validate_string(schema, value, path))
    if isinstance(value, int | float) and not isinstance(value, bool):
        errors.extend(_validate_number(schema, value, path))
    if isinstance(value, dict):
        errors.extend(_validate_object(schema, value, path))
    if isinstance(value, list):
        errors.extend(_validate_array(schema, value, path))

    return errors


def _validate_string(schema: dict, value: str, path: str) -> list[str]:
    """Validate string constraints."""
    errors = []
    min_length = schema.get("minLength")
    if min_length is not None and len(value) < min_length:
        errors.append(f"{_label(path)}: must be at least {min_length} character(s) long.")
    max_length = schema.get("maxLength")
    if max_length is not None and len(value) > max_length:
        errors.append(f"{_label(path)}: must be at most {max_length} character(s) long.")
    pattern = schema.get("pattern")
    if pattern is not None and not re.search(pattern, value):
        errors.append(f"{_label(path)}: does not match the required pattern.")
    return errors


def _validate_number(schema: dict, value: float, path: str) -> list[str]:
    """Validate numeric constraints."""
    errors = []
    minimum = schema.get("minimum")
    if minimum is not None and value < minimum:
        errors.append(f"{_label(path)}: must be greater than or equal to {minimum}.")
    maximum = schema.get("maximum")
    if maximum is not None and value > maximum:
        errors.append(f"{_label(path)}: must be less than or equal to {maximum}.")
    return errors


def _validate_object(schema: dict, value: dict, path: str) -> list[str]:
    """Validate object constraints, recursing into known properties."""
    errors = []
    properties = schema.get("properties") or {}

    for name in schema.get("required") or []:
        if name not in value:
            errors.append(f"{_label(path)}: '{name}' is required.")

    if schema.get("additionalProperties") is False:
        unknown = sorted(key for key in value if key not in properties)
        if unknown:
            errors.append(f"{_label(path)}: unknown field(s): {', '.join(unknown)}.")

    for name, subschema in properties.items():
        if name in value:
            child_path = f"{path}.{name}" if path else name
            errors.extend(_validate(subschema, value[name], child_path))

    return errors


def _validate_array(schema: dict, value: list, path: str) -> list[str]:
    """Validate array constraints, recursing into items."""
    errors = []
    min_items = schema.get("minItems")
    if min_items is not None and len(value) < min_items:
        errors.append(f"{_label(path)}: must contain at least {min_items} item(s).")
    max_items = schema.get("maxItems")
    if max_items is not None and len(value) > max_items:
        errors.append(f"{_label(path)}: must contain at most {max_items} item(s).")

    items_schema = schema.get("items")
    if isinstance(items_schema, dict):
        for index, item in enumerate(value):
            errors.extend(_validate(items_schema, item, f"{_label(path)}[{index}]"))
    return errors
