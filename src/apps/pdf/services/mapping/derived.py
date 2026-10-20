"""Derived / computed values (spec 0016 #5, ``DerivedMapper``).

Two forms::

    # A sandboxed Jinja expression over data, meta and earlier targets
    {"type": "derived", "target": "accused_count", "expression": "accused | length"}
    {"type": "derived", "target": "is_minor", "expression": "data.age < 18"}

    # A named function from a fixed registry
    {"type": "derived", "target": "total", "function": "sum", "args": ["fees"]}
    {"type": "derived", "target": "today", "function": "today"}

``args`` are expressions evaluated before the function is called. Only the
functions registered in ``FUNCTIONS`` are callable, so configuration cannot
reach arbitrary Python.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from ...exceptions import PDFConfigurationError, PDFRequestDataError
from ..templating import evaluate

_IST = ZoneInfo("Asia/Kolkata")


def _numbers(values) -> list[Decimal]:
    try:
        return [Decimal(str(value)) for value in values if value not in (None, "")]
    except (InvalidOperation, ValueError) as exc:
        raise PDFRequestDataError("A value to aggregate is not a number.") from exc


def _sum(values, *_):
    total = sum(_numbers(values), Decimal(0))
    return int(total) if total == total.to_integral_value() else float(total)


def _count(values, *_):
    return len(values or [])


def _join(values, separator=", ", *_):
    return separator.join(str(value) for value in values or [] if value not in (None, ""))


def _concat(*parts):
    return "".join("" if part is None else str(part) for part in parts)


def _coalesce(*values):
    return next((value for value in values if value not in (None, "")), None)


def _today(*_):
    return datetime.now(_IST).date().isoformat()


def _now(*_):
    return datetime.now(_IST).isoformat()


def _age(birth_date, *_):
    from .formatting import parse_datetime

    if not birth_date:
        return None
    born = parse_datetime(birth_date).date()
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _index(values, *_):
    """Number a list of dicts in place: adds ``index`` starting at 1."""
    return [{**row, "index": number} for number, row in enumerate(values or [], start=1)]


FUNCTIONS = {
    "sum": _sum,
    "count": _count,
    "join": _join,
    "concat": _concat,
    "coalesce": _coalesce,
    "today": _today,
    "now": _now,
    "age": _age,
    "index": _index,
}


class DerivedMapper:
    """Resolve ``derived`` mappings."""

    type = "derived"

    def map(self, spec: dict, variables: dict):
        """Return the computed value."""
        if "expression" in spec:
            return evaluate(spec["expression"], variables)

        name = spec.get("function")
        try:
            func = FUNCTIONS[name]
        except KeyError as exc:
            raise PDFConfigurationError(f"Unknown derived function {name!r}.") from exc
        args = [evaluate(arg, variables) for arg in spec.get("args", [])]
        return func(*args)
