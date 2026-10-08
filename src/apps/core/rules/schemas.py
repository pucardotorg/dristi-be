"""JSON Schema handling shared by the service, the adapters and the admin form.

This is deliberately separate from :mod:`apps.core.validators`, which serves
additional attributes (spec 0019 #2.5).
"""

import math

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from rule_engine.types import DataType

from .exceptions import RuleSchemaError

# JSON Schema ``type`` -> rule-engine DataType (spec 0019 #2.5).
_TYPE_MAP = {
    "string": DataType.STRING,
    "number": DataType.FLOAT,
    "integer": DataType.FLOAT,
    "boolean": DataType.BOOLEAN,
    "object": DataType.MAPPING,
    "array": DataType.ARRAY,
    "null": DataType.NULL,
}
DATETIME_FORMATS = frozenset({"date-time", "date"})

# Keywords that make a property's type a union or otherwise not statically
# knowable. Such a property is typed UNDEFINED rather than guessed.
_UNTYPABLE_KEYWORDS = ("anyOf", "oneOf", "allOf", "not", "$ref", "if")


def _validator_class(schema):
    """Return the validator class for ``schema``, honouring ``$schema``."""
    return validator_for(schema, default=Draft202012Validator)


def check_schema(schema, *, field):
    """Raise RuleSchemaError unless ``schema`` is a non-empty, valid JSON Schema."""
    if not isinstance(schema, dict) or not schema:
        raise RuleSchemaError("A non-empty JSON Schema object is required.", field=field)
    try:
        _validator_class(schema).check_schema(schema)
    except SchemaError as exc:
        location = _json_path(exc.path)
        raise RuleSchemaError(
            f"Invalid JSON Schema at {location}: {exc.message}", field=field
        ) from exc


def compile_validator(schema):
    """Return a validator instance for an already-checked ``schema``."""
    cls = _validator_class(schema)
    return cls(schema, format_checker=cls.FORMAT_CHECKER)


def validate_instance(validator, instance, *, error_class, label):
    """Validate ``instance`` and raise ``error_class`` naming every failing JSON path."""
    errors = sorted(validator.iter_errors(instance), key=lambda e: [str(p) for p in e.path])
    if errors:
        details = "; ".join(f"{error.json_path}: {error.message}" for error in errors)
        raise error_class(f"{label} failed schema validation: {details}")


def ensure_plain_json(value, *, error_class, path="$"):
    """Reject anything that is not plain JSON data (spec 0019 #4.3).

    JSON Schema alone does not do this: an untyped property (``{}``) accepts
    any Python object, including a model instance.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise error_class(f"{path}: non-finite number {value!r} is not valid JSON.")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            ensure_plain_json(item, error_class=error_class, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise error_class(f"{path}: object key {key!r} is not a string.")
            ensure_plain_json(item, error_class=error_class, path=f"{path}.{key}")
        return
    raise error_class(f"{path}: value of type {type(value).__name__} is not plain JSON data.")


def declared_inputs(rule_input_schema):
    """Return the top-level property names ``rule_input_schema`` declares."""
    properties = (
        rule_input_schema.get("properties") if isinstance(rule_input_schema, dict) else None
    )
    return set(properties) if isinstance(properties, dict) else set()


def datatype_for_property(property_schema):
    """Map one property's JSON Schema onto a rule-engine DataType (spec 0019 #2.5)."""
    if not isinstance(property_schema, dict):
        return DataType.UNDEFINED
    if any(keyword in property_schema for keyword in _UNTYPABLE_KEYWORDS):
        return DataType.UNDEFINED
    json_type = property_schema.get("type")
    if not isinstance(json_type, str):
        # Absent, or a list of types (a union).
        return DataType.UNDEFINED
    if json_type == "string" and property_schema.get("format") in DATETIME_FORMATS:
        return DataType.DATETIME
    return _TYPE_MAP.get(json_type, DataType.UNDEFINED)


def datatypes_from_json_schema(rule_input_schema):
    """Return ``{symbol: DataType}`` for every declared top-level property."""
    properties = rule_input_schema.get("properties") or {}
    return {name: datatype_for_property(schema) for name, schema in properties.items()}


def _json_path(path):
    """Render a jsonschema ``deque`` path as a JSONPath-like string."""
    rendered = "$"
    for part in path:
        rendered += f"[{part}]" if isinstance(part, int) else f".{part}"
    return rendered
