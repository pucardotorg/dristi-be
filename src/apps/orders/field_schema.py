"""The shape of an order item's fields and of the values given for them (spec 0039 #6.3).

Pure: no database, no case. Checks that need the case (a person is in it, a
purpose is active) are the services'.
"""

import datetime
import re
from decimal import Decimal, InvalidOperation

from .enums import FieldInput

FIELD_KEYS = {"key", "label", "input", "options", "mandatory", "party_types", "master"}
KEY_RE = re.compile(r"[a-z][a-z0-9_]*")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_TEXT = 2000
MAX_AMOUNT = Decimal("99999999.99")


def schema_errors(schema):
    """Return why ``schema`` is not a valid ``field_schema``; ``[]`` when it is."""
    if not isinstance(schema, dict) or set(schema) - {"fields"}:
        return ['A field schema is an object with a single "fields" list.']
    fields = schema.get("fields")
    if not isinstance(fields, list):
        return ['"fields" must be a list.']
    errors, seen = [], set()
    for index, field in enumerate(fields):
        where = f"fields[{index}]"
        if not isinstance(field, dict):
            errors.append(f"{where} must be an object.")
            continue
        if unknown := set(field) - FIELD_KEYS:
            errors.append(f"{where} has unknown keys: {', '.join(sorted(unknown))}.")
        key = field.get("key")
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            errors.append(f"{where}.key must be lower snake case.")
        elif key in seen:
            errors.append(f"{where}.key {key!r} is used twice.")
        else:
            seen.add(key)
        label = field.get("label")
        if not isinstance(label, str) or not label.strip():
            errors.append(f"{where}.label must be a non-empty string.")
        if field.get("input") not in FieldInput.values:
            errors.append(f"{where}.input must be one of {', '.join(FieldInput.values)}.")
        if field.get("input") == FieldInput.ENUM and not (
            _string_list(field.get("options")) and all(field["options"])
        ):
            errors.append(
                f"{where}.options must be a non-empty list of non-empty strings for an ENUM field."
            )
        if "party_types" in field and not _string_list(field["party_types"], allow_empty=True):
            errors.append(f"{where}.party_types must be a list of strings.")
        if field.get("input") == FieldInput.MASTER and not field.get("master"):
            errors.append(f"{where}.master is required for a MASTER field.")
        if "mandatory" in field and not isinstance(field["mandatory"], bool):
            errors.append(f"{where}.mandatory must be true or false.")
    return errors


def _string_list(value, *, allow_empty=False):
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(isinstance(item, str) for item in value)
    )


def fields_of(schema):
    """Return the schema's fields as ``{key: field}``."""
    return {field["key"]: field for field in (schema or {}).get("fields", [])}


def editable_fields(schema):
    """The fields a person answers: everything but ``RECORD`` fields, read from the record."""
    return {
        key: field
        for key, field in fields_of(schema).items()
        if field["input"] != FieldInput.RECORD
    }


def is_blank(value):
    """Whether a value counts as unanswered."""
    return value is None or value == "" or value == [] or value == {}


def value_problem(field, value):
    """Return ``(code, message)`` if ``value`` has the wrong shape for ``field``; else ``None``."""
    if is_blank(value):
        return None
    kind = field["input"]
    label = field["label"]
    if kind == FieldInput.TEXT:
        if not isinstance(value, str) or len(value) > MAX_TEXT:
            return "INVALID", f"{label} must be text of at most {MAX_TEXT} characters."
    elif kind == FieldInput.DATE:
        try:
            # ``fromisoformat`` also takes "20191204" and week dates (3.11+): insist on the format.
            if not isinstance(value, str) or not DATE_RE.fullmatch(value):
                raise ValueError
            datetime.date.fromisoformat(value)
        except ValueError:
            return "INVALID", f"{label} must be a date as YYYY-MM-DD."
    elif kind == FieldInput.AMOUNT:
        try:
            amount = Decimal(str(value)) if isinstance(value, str | int) else None
            if amount is None or not amount.is_finite() or amount <= 0 or amount > MAX_AMOUNT:
                raise InvalidOperation
            if amount != amount.quantize(Decimal("0.01")):
                raise InvalidOperation
        except InvalidOperation:
            return "INVALID", f"{label} must be an amount above zero with at most two decimals."
    elif kind == FieldInput.ENUM:
        if value not in field["options"]:
            return "NOT_AN_OPTION", f"{label} must be one of {', '.join(field['options'])}."
    elif kind in (FieldInput.MASTER, FieldInput.HEARING_PURPOSE):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
            return "INVALID", f"{label} must be a code."
    elif kind == FieldInput.PARTY:
        if not _is_uuid(value):
            return "INVALID", f"{label} must be the id of a person in the case."
    elif kind == FieldInput.PARTIES:
        if (
            not isinstance(value, list)
            or not all(_is_uuid(item) for item in value)
            or len({_canonical(item) for item in value}) != len(value)
        ):
            return "INVALID", f"{label} must be a list of distinct ids of people in the case."
    elif kind == FieldInput.PROCESS_RECIPIENTS:
        if not isinstance(value, list) or not all(_recipient_ok(item) for item in value):
            return "INVALID", f"{label} must list, per person, the channels and addresses."
    return None


def canonical_id(value):
    """Return a valid id string in canonical lowercase form."""
    import uuid

    return str(uuid.UUID(str(value)))


_canonical = canonical_id


def _is_uuid(value):
    import uuid

    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return False
    return isinstance(value, str)


def _recipient_ok(item):
    return (
        isinstance(item, dict)
        and _is_uuid(item.get("party_id"))
        and _string_list(item.get("channels", []), allow_empty=True)
        and isinstance(item.get("addresses", []), list)
    )
