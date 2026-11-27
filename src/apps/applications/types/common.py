"""Shapes and helpers several types share (spec 0033 #3.4).

Addresses use the e-filing address composite (0020 §7): the same six fields as
``apps.address.Address``, each optional while drafting, at least one given.
"""

import re
from decimal import Decimal, InvalidOperation

from apps.address.models import CONTENT_FIELDS, PINCODE_REGEX
from apps.api import errors as api_errors
from apps.parties.models import PHONE_NUMBER_REGEX

from .base import FieldProblem

ADDRESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {name: {"type": "string", "maxLength": 255} for name in CONTENT_FIELDS},
}
ADDRESSES_SCHEMA = {"type": "array", "maxItems": 10, "items": ADDRESS_SCHEMA}


def address_problems(address, path):
    """An address with nothing in it, or a malformed pincode (domain 05 rules, 0020 §7)."""
    if address is None:
        return []
    problems = []
    if not any((address.get(name) or "").strip() for name in CONTENT_FIELDS):
        problems.append(
            FieldProblem(path, api_errors.REQUIRED.code, "Enter at least one part of the address.")
        )
    pincode = (address.get("pincode") or "").strip()
    if pincode and not re.fullmatch(PINCODE_REGEX, pincode):
        problems.append(
            FieldProblem(
                f"{path}.pincode",
                api_errors.INVALID.code,
                "Enter a valid 6-digit pincode not starting with 0.",
            )
        )
    return problems


def phone_problem(value, path):
    if value and not re.fullmatch(PHONE_NUMBER_REGEX, value):
        return FieldProblem(
            path,
            api_errors.INVALID.code,
            "Enter the number with its country code, e.g. +919876543210.",
        )
    return None


def address_text(address):
    if not address:
        return ""
    parts = [address.get(name) for name in ("line1", "city", "district", "state", "pincode")]
    text = ", ".join(part.strip() for part in parts if part and part.strip())
    if (address.get("police_station") or "").strip():
        text += f" (Police station: {address['police_station'].strip()})"
    return text


def format_rupees(amount):
    """``50000.00`` -> ``Rs. 50,000`` (Indian grouping)."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError):
        return ""
    whole, _, fraction = f"{value:.2f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[::-1]
        whole = f"{head},{tail}"
    return f"Rs. {sign}{whole}" + ("" if fraction == "00" else f".{fraction}")
