"""Date, number and case transforms (spec 0016 #5, ``FormattingMapper``).

The functions here are pure, and are also registered as Jinja filters
(``format_date``, ``format_number``) so templates can format values inline.

Mapping shape::

    {"type": "format", "target": "hearing_on", "source": "hearing_date",
     "format": "date", "pattern": "%d %B %Y", "input_format": "iso",
     "timezone": "Asia/Kolkata"}

    {"type": "format", "target": "fee_text", "source": "data.fee",
     "format": "number", "decimals": 2, "grouping": "indian"}

    {"type": "format", "target": "name_upper", "source": "name", "format": "upper"}

``source`` is a template expression evaluated against the mapping variables,
so it can reference earlier mapping targets or ``data.*``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...exceptions import PDFConfigurationError, PDFRequestDataError

DEFAULT_DATE_PATTERN = "%d/%m/%Y"
DEFAULT_TIMEZONE = "Asia/Kolkata"

CASE_TRANSFORMS = {
    "upper": str.upper,
    "lower": str.lower,
    "title": str.title,
    "capitalize": str.capitalize,
    "strip": str.strip,
}


def apply_case(value, transform: str | None):
    """Apply a named case transform to a string value (non-strings pass through)."""
    if not transform or value is None:
        return value
    try:
        func = CASE_TRANSFORMS[transform]
    except KeyError as exc:
        raise PDFConfigurationError(f"Unknown transform {transform!r}.") from exc
    if isinstance(value, list):
        return [func(item) if isinstance(item, str) else item for item in value]
    return func(value) if isinstance(value, str) else value


def parse_datetime(value, input_format: str = "iso") -> datetime:
    """Parse ``value`` into a datetime according to ``input_format``.

    ``input_format`` is ``iso`` (ISO-8601 string), ``epoch`` (seconds),
    ``epoch_ms`` (milliseconds) or a ``strptime`` pattern.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    try:
        if input_format in ("epoch", "epoch_ms"):
            seconds = float(value) / (1000 if input_format == "epoch_ms" else 1)
            return datetime.fromtimestamp(seconds, tz=UTC)
        if input_format == "iso":
            text = str(value).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return datetime.fromisoformat(text)
        return datetime.strptime(str(value), input_format)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise PDFRequestDataError(
            f"Value is not a valid date for format {input_format!r}."
        ) from exc


def format_date(
    value,
    pattern: str = DEFAULT_DATE_PATTERN,
    input_format: str = "iso",
    tz: str | None = DEFAULT_TIMEZONE,
) -> str:
    """Format a date/datetime-like ``value`` with a ``strftime`` pattern.

    Aware datetimes are converted to ``tz`` first; naive values are formatted
    as given. ``None`` and empty strings format as an empty string.
    """
    if value is None or value == "":
        return ""
    parsed = parse_datetime(value, input_format)
    if tz and parsed.tzinfo is not None:
        try:
            parsed = parsed.astimezone(ZoneInfo(tz))
        except ZoneInfoNotFoundError as exc:
            raise PDFConfigurationError(f"Unknown timezone {tz!r}.") from exc
    return parsed.strftime(pattern)


def _group_indian(integer_digits: str) -> str:
    """Group digits the Indian way: 12,34,56,789."""
    if len(integer_digits) <= 3:
        return integer_digits
    head, tail = integer_digits[:-3], integer_digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail])


def format_number(value, decimals: int = 0, grouping: str | None = "international") -> str:
    """Format a number with fixed decimals and optional thousands grouping.

    ``grouping`` is ``international`` (1,234,567), ``indian`` (12,34,567) or
    ``None``/``none`` for no separators. Rounding is half-up, so currency
    amounts round the way people expect rather than banker's rounding.
    """
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PDFRequestDataError("Value is not a valid number.") from exc
    if not number.is_finite():
        raise PDFRequestDataError("Value is not a finite number.")

    quantum = Decimal(1).scaleb(-int(decimals))
    number = number.quantize(quantum, rounding=ROUND_HALF_UP)
    sign = "-" if number < 0 else ""
    text = f"{abs(number):f}"
    integer_part, _, fraction = text.partition(".")

    if grouping == "indian":
        integer_part = _group_indian(integer_part)
    elif grouping == "international":
        integer_part = f"{int(integer_part):,}"
    elif grouping not in (None, "none"):
        raise PDFConfigurationError(f"Unknown grouping {grouping!r}.")

    return f"{sign}{integer_part}.{fraction}" if fraction else f"{sign}{integer_part}"


def apply(spec: dict, value):
    """Apply one ``format`` mapping to ``value``."""
    kind = spec.get("format")
    if kind == "date":
        return format_date(
            value,
            spec.get("pattern", DEFAULT_DATE_PATTERN),
            spec.get("input_format", "iso"),
            spec.get("timezone", DEFAULT_TIMEZONE),
        )
    if kind == "number":
        return format_number(value, spec.get("decimals", 0), spec.get("grouping", "international"))
    if kind in CASE_TRANSFORMS:
        return apply_case(value, kind)
    raise PDFConfigurationError(f"Unknown format {kind!r}.")


class FormattingMapper:
    """Resolve ``format`` mappings."""

    type = "format"

    def map(self, spec: dict, variables: dict):
        """Return the formatted value of ``spec['source']``."""
        from ..templating import evaluate

        value = evaluate(spec["source"], variables)
        return apply(spec, value)
