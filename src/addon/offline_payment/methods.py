"""Collection methods and their fields (spec 0032 #8.1).

Adding a method is a code change here, because its validation is code;
enabling one is a setting (``OFFLINE_PAYMENT_METHODS``). Staff forms render
fields from ``attestation_methods()``, so they need no change when one is added.
Cheques are deliberately not offered: a cheque can bounce after the case has
moved on, and there is no reversal.
"""

import re
from dataclasses import dataclass

from apps.payments.providers.base import AttestationField, AttestationMethod

from . import constants
from .config import OfflineConfig


@dataclass(frozen=True)
class FieldRule:
    """How one detail field is validated, beyond its kind and maximum length."""

    min_length: int = 0
    pattern: re.Pattern | None = None


ALPHANUMERIC = re.compile(r"[A-Za-z0-9]+")

# code -> (label, fields, extra rules per field key)
_DEFINITIONS: dict[str, tuple[str, tuple[AttestationField, ...], dict[str, FieldRule]]] = {
    constants.CASH: ("Cash", (), {}),
    constants.DEMAND_DRAFT: (
        "Demand draft",
        (
            AttestationField(
                constants.INSTRUMENT_NUMBER, "DD number", constants.KIND_DIGITS, max_length=6
            ),
            AttestationField(constants.INSTRUMENT_DATE, "DD date", constants.KIND_DATE),
            AttestationField(
                constants.BANK_NAME, "Issuing bank", constants.KIND_TEXT, max_length=100
            ),
            AttestationField(
                constants.BRANCH, "Branch", constants.KIND_TEXT, required=False, max_length=100
            ),
        ),
        {constants.INSTRUMENT_NUMBER: FieldRule(min_length=6)},
    ),
    constants.POS: (
        "Card / UPI at the counter",
        (
            AttestationField(
                constants.TRANSACTION_REFERENCE,
                "Transaction reference",
                constants.KIND_TEXT,
                max_length=32,
            ),
            AttestationField(
                constants.TERMINAL_ID,
                "Terminal id",
                constants.KIND_TEXT,
                required=False,
                max_length=16,
            ),
        ),
        {constants.TRANSACTION_REFERENCE: FieldRule(min_length=6, pattern=ALPHANUMERIC)},
    ),
}

SUPPORTED = tuple(_DEFINITIONS)


def method(code: str) -> AttestationMethod:
    """The method ``code`` (one of ``SUPPORTED``)."""

    label, fields, _ = _DEFINITIONS[code]
    return AttestationMethod(code=code, label=label, fields=fields)


def rule(code: str, key: str) -> FieldRule:
    """Extra validation for detail ``key`` of method ``code``."""

    return _DEFINITIONS[code][2].get(key, FieldRule())


def enabled(config: OfflineConfig) -> list[AttestationMethod]:
    """The supported methods enabled by configuration, in configured order."""

    return [method(code) for code in config.methods if code in _DEFINITIONS]


def enabled_codes(config: OfflineConfig) -> tuple[str, ...]:
    """Codes of the enabled methods."""

    return tuple(item.code for item in enabled(config))
