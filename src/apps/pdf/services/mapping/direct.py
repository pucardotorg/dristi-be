"""Direct / JSONPath mapping (spec 0016 #5, ``DirectMapper``).

Copies values out of the request data, optionally reshaping them. Mapping
shapes::

    # scalar (first match) -- strings, numbers, labels
    {"type": "direct", "target": "case_number", "path": "$.case.number",
     "default": "", "transform": "upper"}

    # every match, as a list
    {"type": "direct", "target": "accused", "path": "$.accused[*].name", "many": true}

    # list of objects projected onto named columns (table rows)
    {"type": "direct", "target": "witnesses", "path": "$.witnesses[*]",
     "columns": {"name": "$.name", "age": "$.age"}}

    # code -> label lookup
    {"type": "direct", "target": "court_type", "path": "$.court.type",
     "labels": {"DC": "District Court", "HC": "High Court"}}

    # a constant
    {"type": "direct", "target": "title", "value": "SUMMONS"}

``path`` is evaluated against the request data. A missing value without a
``default`` is an error when ``required`` is true (the default) so that a
document is never produced with silently missing content.
"""

from __future__ import annotations

from functools import lru_cache

from jsonpath_ng.exceptions import JsonPathParserError
from jsonpath_ng.ext import parse as parse_jsonpath

from ...exceptions import PDFConfigurationError, PDFRequestDataError
from .formatting import apply_case

_MISSING = object()


@lru_cache(maxsize=1024)
def compile_path(path: str):
    """Compile and cache a JSONPath expression."""
    try:
        return parse_jsonpath(path)
    except (JsonPathParserError, Exception) as exc:  # jsonpath-ng raises bare Exceptions too
        raise PDFConfigurationError(f"Invalid JSONPath {path!r}.") from exc


def find_all(path: str, data) -> list:
    """Return every value matched by ``path`` in ``data``."""
    return [match.value for match in compile_path(path).find(data)]


def find_first(path: str, data, default=_MISSING):
    """Return the first value matched by ``path``, ``default`` when nothing matches."""
    matches = compile_path(path).find(data)
    if matches:
        return matches[0].value
    return default


class DirectMapper:
    """Resolve ``direct`` mappings against the request data."""

    type = "direct"

    def map(self, spec: dict, data):
        """Return the mapped value for one ``direct`` spec."""
        if "value" in spec:
            return spec["value"]

        path = spec["path"]
        if spec.get("many") or "columns" in spec:
            value = find_all(path, data)
        else:
            value = find_first(path, data)

        if value is _MISSING or value is None:
            if "default" in spec:
                return spec["default"]
            if spec.get("required", True):
                raise PDFRequestDataError(
                    f"Required value for {spec.get('target', path)!r} is missing."
                )
            return None

        if "columns" in spec:
            value = [self._project(row, spec["columns"]) for row in value]

        if "labels" in spec:
            value = self._label(value, spec["labels"], spec.get("default", _MISSING))

        return apply_case(value, spec.get("transform"))

    @staticmethod
    def _project(row, columns: dict) -> dict:
        """Project one matched object onto the configured named columns."""
        return {name: find_first(path, row, None) for name, path in columns.items()}

    @staticmethod
    def _label(value, labels: dict, default):
        """Translate a code (or list of codes) through a label table."""

        def one(code):
            label = labels.get(str(code), default)
            return code if label is _MISSING else label

        if isinstance(value, list):
            return [one(item) for item in value]
        return one(value)
