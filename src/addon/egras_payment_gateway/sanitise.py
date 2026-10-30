"""Payer-field sanitisation for the e-GRAS form (spec 0022 #4.8).

e-GRAS restricts the characters and lengths of every payer and remarks field. A
litigant must not be unable to pay because of punctuation in an address, so each
field is made acceptable rather than rejected; only an unrepresentable name is
fatal. These functions are pure: the sanitised payer is what the form carries,
while the original ``Payer`` stays on the ``Payment`` snapshot.
"""

import re
from dataclasses import dataclass

from apps.payments.providers.base import Payer, ProviderPermanentError

from . import constants

# Allowed character sets per field (spec 0022 #4.2). Everything else is removed.
NAME_ALLOWED = re.compile(r"[^A-Za-z0-9 ]")
CITY_ALLOWED = re.compile(r"[^A-Za-z ]")
ADDRESS_ALLOWED = re.compile(r"[^A-Za-z0-9 /,#-]")
REMARKS_ALLOWED = re.compile(r"[^A-Za-z0-9 /,#-]")
APPLICATION_ALLOWED = re.compile(r"[^A-Za-z0-9 /-]")

_SPACES = re.compile(r"\s+")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_NON_DIGIT = re.compile(r"\D")

MAX_NAME = 50
MAX_CITY = 50
MAX_ADDRESS = 100
MAX_REMARKS = 200
PINCODE_LEN = 6
PHONE_LEN = 10


@dataclass(frozen=True)
class SanitisedPayer:
    """Payer fields in the exact shape the e-GRAS form accepts."""

    fullname: str
    cityname: str
    address: str
    pincode: str
    email: str
    phone: str


def clean(value: str, disallowed: re.Pattern, max_len: int) -> str:
    """Strip disallowed characters, collapse spaces, trim and truncate."""

    stripped = disallowed.sub("", value or "")
    collapsed = _SPACES.sub(" ", stripped).strip()
    return collapsed[:max_len]


def clean_pincode(value: str) -> str:
    """Keep the first six digits; empty when fewer than six are present."""

    digits = _NON_DIGIT.sub("", value or "")
    return digits[:PINCODE_LEN] if len(digits) >= PINCODE_LEN else ""


def clean_phone(value: str) -> str:
    """Normalise to exactly ten digits, dropping a leading ``+91`` or ``0``.

    Anything that is not ten digits after normalisation is sent blank rather
    than rejected (spec 0022 #4.8).
    """

    digits = _NON_DIGIT.sub("", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == PHONE_LEN else ""


def clean_email(value: str) -> str:
    """Return the email when it is syntactically valid, else blank."""

    candidate = (value or "").strip()
    return candidate if _EMAIL.match(candidate) else ""


def sanitise_payer(payer: Payer, config) -> SanitisedPayer:
    """Sanitise every payer field, applying the configured fallbacks.

    Raises :class:`ProviderPermanentError` (``EGRAS_INVALID_PAYER``) when the
    name is not representable at all — a challan with no name is not acceptable.
    """

    fullname = clean(payer.name, NAME_ALLOWED, MAX_NAME)
    if not fullname:
        raise ProviderPermanentError(
            constants.EGRAS_INVALID_PAYER,
            "The payer's name is not representable in the e-GRAS character set.",
        )

    return SanitisedPayer(
        fullname=fullname,
        cityname=clean(payer.city, CITY_ALLOWED, MAX_CITY) or config.payer_fallback_city,
        address=clean(payer.address, ADDRESS_ALLOWED, MAX_ADDRESS) or config.payer_fallback_address,
        pincode=clean_pincode(payer.pincode) or config.payer_fallback_pincode,
        email=clean_email(payer.email),
        phone=clean_phone(payer.phone),
    )
