"""The payment request reference a payer quotes at the counter (spec 0032 #5.2).

::

    {PREFIX}-{YYMMDD}-{AAAAA}-{BBBBB}-{C}
    OFL-261111-7K3QF-9XM2H-V

``YYMMDD`` is the IST date of ``initiated_at``; ``AAAAABBBBB`` is the low 50
bits of the request's uuid in Crockford base32; ``C`` is the Crockford check
symbol (mod 37) of ``int(YYMMDD) * 2**50 + body``. Because 37 is prime and
divides neither a single-symbol difference (< 32 in the body, < 10 in the date)
nor the factors of an adjacent swap (31 in the body, 9 in the date), every
single-character typo and every adjacent transposition within the date or the
body changes the check symbol.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from .constants import IST

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U
CHECK_ALPHABET = ALPHABET + "*~$=U"  # values 32..36
CHECK_MODULUS = 37
BODY_BITS = 50
BODY_LENGTH = 10  # 10 symbols x 5 bits
BODY_MASK = (1 << BODY_BITS) - 1
DATE_LENGTH = 6
# Everything after the prefix, without dashes: date, body, check symbol.
COMPACT_LENGTH = DATE_LENGTH + BODY_LENGTH + 1
# Longest input worth normalising; anything longer is rejected outright.
MAX_INPUT_LENGTH = 64

_DATE_RE = re.compile(r"[0-9]{6}")
_BODY_RE = re.compile(f"[{ALPHABET}]{{{BODY_LENGTH}}}")
_SEPARATORS = re.compile(r"[\s\-]+")
_LOOKALIKES = str.maketrans({"I": "1", "L": "1", "O": "0"})


class MalformedReference(ValueError):  # noqa: N818 - a parse failure, not an error
    """The value is not a reference this deployment issued."""


@dataclass(frozen=True)
class ParsedReference:
    """A reference split into its parts."""

    prefix: str
    issued_on: date
    body: int
    canonical: str


def check_symbol(number: int) -> str:
    """The Crockford check symbol of ``number``."""

    return CHECK_ALPHABET[number % CHECK_MODULUS]


def _encode_body(value: int) -> str:
    symbols = []
    for _ in range(BODY_LENGTH):
        symbols.append(ALPHABET[value & 0b11111])
        value >>= 5
    return "".join(reversed(symbols))


def _decode_body(text: str) -> int:
    value = 0
    for symbol in text:
        value = (value << 5) | ALPHABET.index(symbol)
    return value


def _date_text(moment: datetime) -> str:
    return moment.astimezone(IST).strftime("%y%m%d")


def _format(prefix: str, date_text: str, body_text: str, check: str) -> str:
    return f"{prefix}-{date_text}-{body_text[:5]}-{body_text[5:]}-{check}"


def build(reference: UUID, initiated_at: datetime, prefix: str) -> str:
    """The reference of a request; deterministic in ``reference`` and ``initiated_at``."""

    if initiated_at.tzinfo is None:
        raise ValueError("initiated_at must be timezone-aware.")
    body = reference.int & BODY_MASK
    date_text = _date_text(initiated_at)
    number = int(date_text) * (1 << BODY_BITS) + body
    return _format(prefix, date_text, _encode_body(body), check_symbol(number))


def parse(value, prefix: str) -> ParsedReference:
    """Normalise and validate ``value``; raise ``MalformedReference`` if it is not ours.

    Upper-cases, drops spaces and dashes, and — in the body and check symbol
    only — reads ``I``/``L`` as ``1`` and ``O`` as ``0``. The prefix is matched
    as configured, so ``OFL`` is never read as ``0F1``.
    """

    if not isinstance(value, str) or not value or len(value) > MAX_INPUT_LENGTH:
        raise MalformedReference("Not a payment reference.")
    compact = _SEPARATORS.sub("", value).upper()
    if not prefix or not compact.startswith(prefix):
        raise MalformedReference("Wrong reference prefix.")
    rest = compact[len(prefix) :]
    if len(rest) != COMPACT_LENGTH:
        raise MalformedReference("Wrong reference length.")

    date_text = rest[:DATE_LENGTH]
    tail = rest[DATE_LENGTH:].translate(_LOOKALIKES)
    body_text, check = tail[:BODY_LENGTH], tail[BODY_LENGTH:]
    if not _DATE_RE.fullmatch(date_text) or not _BODY_RE.fullmatch(body_text):
        raise MalformedReference("Invalid characters in the reference.")
    if check not in CHECK_ALPHABET:
        raise MalformedReference("Invalid check symbol.")
    try:
        issued_on = date(2000 + int(date_text[:2]), int(date_text[2:4]), int(date_text[4:6]))
    except ValueError as exc:
        raise MalformedReference("Impossible date in the reference.") from exc

    body = _decode_body(body_text)
    if check_symbol(int(date_text) * (1 << BODY_BITS) + body) != check:
        raise MalformedReference("The reference check symbol does not match.")
    return ParsedReference(
        prefix=prefix,
        issued_on=issued_on,
        body=body,
        canonical=_format(prefix, date_text, body_text, check),
    )


def normalise(value, prefix: str) -> str:
    """The canonical form of ``value``; raises ``MalformedReference``."""

    return parse(value, prefix).canonical
