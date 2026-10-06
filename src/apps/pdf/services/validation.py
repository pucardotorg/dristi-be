"""Authoring-time validation of ``format_config`` and ``data_config`` (spec 0016 #9).

Configuration is checked when a ``PDFTemplateVersion`` is saved (model
``clean()``, so the admin and any future API share it), so an invalid template
is rejected at authoring time rather than inside a worker. Validation is a
JSON-schema pass for structure followed by a walk that compiles every Jinja
template/expression and JSONPath, catching syntax errors the schema cannot.
"""

from __future__ import annotations

import jsonschema
from django.core.exceptions import ValidationError
from jinja2 import TemplateError

from ..exceptions import PDFConfigurationError
from .templating import check_expression, check_template

# ---------------------------------------------------------------------------
# format_config
# ---------------------------------------------------------------------------

_NUMBER = {"type": "number", "minimum": 0}
_WHEN = {"type": "string", "minLength": 1}
_ALIGN = {"enum": ["left", "center", "right", "justify"]}
_COMMON = {"type": {"type": "string"}, "when": _WHEN}

_STYLE = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "font": {"type": "string"},
        "size": {"type": "number", "exclusiveMinimum": 0},
        "leading": {"type": ["number", "null"], "exclusiveMinimum": 0},
        "align": _ALIGN,
        "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
        "bold": {"type": "boolean"},
        "italic": {"type": "boolean"},
        "space_before": _NUMBER,
        "space_after": _NUMBER,
    },
}

_BAND = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "left": {"type": "string"},
        "center": {"type": "string"},
        "right": {"type": "string"},
        "style": {"type": "string"},
        "line": {"type": "boolean"},
        "lines": {"type": "integer", "minimum": 1, "maximum": 5},
    },
}

_WIDTH = {"oneOf": [_NUMBER, {"type": "string", "pattern": r"^\d+(\.\d+)?%$"}]}


def _block(kind: str, properties: dict, required: tuple = ()) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", *required],
        "properties": {**_COMMON, "type": {"const": kind}, **properties},
    }


_BLOCKS = [
    _block(
        "paragraph",
        {"text": {"type": "string"}, "style": {"type": "string"}, "align": _ALIGN},
        ("text",),
    ),
    _block(
        "text",
        {"text": {"type": "string"}, "style": {"type": "string"}, "align": _ALIGN},
        ("text",),
    ),
    _block(
        "heading",
        {
            "text": {"type": "string"},
            "level": {"type": "integer", "minimum": 1, "maximum": 3},
            "style": {"type": "string"},
            "align": _ALIGN,
        },
        ("text",),
    ),
    _block("spacer", {"height": _NUMBER}),
    _block("page_break", {}),
    _block(
        "line",
        {
            "thickness": _NUMBER,
            "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
            "space_before": _NUMBER,
            "space_after": _NUMBER,
        },
    ),
    _block(
        "table",
        {
            "columns": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "header": {"type": "string"},
                        "value": {"type": "string"},
                        "width": _WIDTH,
                        "align": _ALIGN,
                    },
                },
            },
            "source": {"type": "string", "minLength": 1},
            "as": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
            "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
            "style": {"type": "string"},
            "header_style": {"type": "string"},
            "show_header": {"type": "boolean"},
            "repeat_header": {"type": "boolean"},
            "border": {"type": "boolean"},
            "padding": _NUMBER,
            "header_background": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
        },
        ("columns",),
    ),
    _block(
        "list",
        {
            "items": {"type": "array", "items": {"type": "string"}},
            "source": {"type": "string", "minLength": 1},
            "as": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
            "item": {"type": "string"},
            "ordered": {"type": "boolean"},
            "start": {"type": "integer", "minimum": 0},
            "indent": _NUMBER,
            "style": {"type": "string"},
        },
    ),
    _block(
        "image",
        {
            "source": {"type": "string", "minLength": 1},
            "width": _NUMBER,
            "height": _NUMBER,
            "size": _NUMBER,
            "align": _ALIGN,
        },
        ("source",),
    ),
    _block(
        "qr",
        {
            "source": {"type": "string", "minLength": 1},
            "value": {"type": "string", "minLength": 1},
            "size": _NUMBER,
            "width": _NUMBER,
            "height": _NUMBER,
            "align": _ALIGN,
            "error_correction": {"enum": ["L", "M", "Q", "H"]},
        },
    ),
    _block(
        "group",
        {
            "blocks": {"type": "array", "items": {"$ref": "#/$defs/block"}},
            "source": {"type": "string", "minLength": 1},
            "as": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
        },
        ("blocks",),
    ),
]

FORMAT_CONFIG_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["body"],
    "properties": {
        "page": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "size": {"enum": ["A3", "A4", "A5", "LETTER", "LEGAL"]},
                "orientation": {"enum": ["portrait", "landscape"]},
                "margins": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": dict.fromkeys(("top", "right", "bottom", "left"), _NUMBER),
                },
            },
        },
        "metadata": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "author": {"type": "string"},
                "subject": {"type": "string"},
            },
        },
        "styles": {"type": "object", "additionalProperties": _STYLE},
        "header": _BAND,
        "footer": _BAND,
        "body": {"type": "array", "items": {"$ref": "#/$defs/block"}},
    },
    "$defs": {
        "block": {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {"enum": [block["properties"]["type"]["const"] for block in _BLOCKS]}
            },
            "allOf": [
                {
                    "if": {"properties": {"type": {"const": block["properties"]["type"]["const"]}}},
                    "then": block,
                }
                for block in _BLOCKS
            ],
        }
    },
}

# ---------------------------------------------------------------------------
# data_config
# ---------------------------------------------------------------------------

_TARGET = {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"}


def _mapping(kind: str, properties: dict, required: tuple = (), any_of: list | None = None):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "target", *required],
        "properties": {
            "type": {"const": kind},
            "target": _TARGET,
            "required": {"type": "boolean"},
            "default": {},
            **properties,
        },
    }
    if any_of:
        schema["anyOf"] = any_of
    return schema


_MAPPINGS = [
    _mapping(
        "direct",
        {
            "path": {"type": "string", "minLength": 1},
            "value": {},
            "many": {"type": "boolean"},
            "columns": {"type": "object", "additionalProperties": {"type": "string"}},
            "labels": {"type": "object"},
            "transform": {"enum": ["upper", "lower", "title", "capitalize", "strip"]},
        },
        any_of=[{"required": ["path"]}, {"required": ["value"]}],
    ),
    _mapping(
        "external_api",
        {
            "method": {"enum": ["GET", "POST", "get", "post"]},
            "url": {"type": "string", "minLength": 1},
            "params": {"type": "object"},
            "credentials": {"type": "string"},
            "path": {"type": "string", "minLength": 1},
            "fields": {"type": "object", "additionalProperties": {"type": "string"}},
            "many": {"type": "boolean"},
        },
        ("url",),
    ),
    _mapping(
        "derived",
        {
            "expression": {"type": "string", "minLength": 1},
            "function": {"type": "string"},
            "args": {"type": "array", "items": {"type": "string"}},
        },
        any_of=[{"required": ["expression"]}, {"required": ["function"]}],
    ),
    _mapping(
        "format",
        {
            "source": {"type": "string", "minLength": 1},
            "format": {
                "enum": ["date", "number", "upper", "lower", "title", "capitalize", "strip"]
            },
            "pattern": {"type": "string"},
            "input_format": {"type": "string"},
            "timezone": {"type": ["string", "null"]},
            "decimals": {"type": "integer", "minimum": 0, "maximum": 10},
            "grouping": {"enum": ["international", "indian", "none", None]},
        },
        ("source", "format"),
    ),
    _mapping(
        "localization",
        {
            "code": {"type": "string"},
            "source": {"type": "string", "minLength": 1},
            "module": {"type": "string"},
            "locale": {"type": "string"},
        },
        any_of=[{"required": ["code"]}, {"required": ["source"]}],
    ),
    _mapping(
        "image",
        {
            "source": {"type": "string", "minLength": 1},
            "source_type": {"enum": ["url", "base64", "file"]},
            "max_width": {"type": "integer", "minimum": 1},
            "max_height": {"type": "integer", "minimum": 1},
            "on_error": {"enum": ["fail", "placeholder"]},
        },
        ("source",),
    ),
    _mapping(
        "qr",
        {
            "source": {"type": "string", "minLength": 1},
            "template": {"type": "string", "minLength": 1},
            "error_correction": {"enum": ["L", "M", "Q", "H"]},
            "box_size": {"type": "integer", "minimum": 1, "maximum": 40},
            "border": {"type": "integer", "minimum": 0, "maximum": 20},
        },
        any_of=[{"required": ["source"]}, {"required": ["template"]}],
    ),
]

DATA_CONFIG_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type"],
                "properties": {
                    "type": {"enum": [m["properties"]["type"]["const"] for m in _MAPPINGS]}
                },
                "allOf": [
                    {
                        "if": {"properties": {"type": {"const": m["properties"]["type"]["const"]}}},
                        "then": m,
                    }
                    for m in _MAPPINGS
                ],
            },
        },
        "localization": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "module": {"type": "string"},
                "messages": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                },
            },
        },
        "significant_fields": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "request_schema": {"type": "object"},
        "sync_render": {"type": "boolean"},
        "filename": {"type": "string", "minLength": 1},
        "bulk": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "records_path": {"type": "string", "minLength": 1},
                "merge": {"type": "boolean"},
                "merge_partial": {"type": "boolean"},
                "bulk_only": {"type": "boolean"},
                "max_records_per_document": {"type": "integer", "minimum": 1},
            },
        },
    },
}

_RESERVED_TARGETS = frozenset({"data", "meta", "record", "records", "loop"})


def _schema_errors(schema: dict, instance) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema)
    messages = []
    for error in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "(root)"
        messages.append(f"{location}: {error.message}")
    return messages


def _check(fn, source: str, where: str, errors: list[str]) -> None:
    try:
        fn(source)
    except TemplateError as exc:
        errors.append(f"{where}: {exc}")


def _walk_blocks(blocks: list, where: str, errors: list[str]) -> None:
    for index, block in enumerate(blocks):
        here = f"{where}/{index}"
        if "when" in block:
            _check(check_expression, block["when"], f"{here}/when", errors)
        if "source" in block:
            _check(check_expression, block["source"], f"{here}/source", errors)
        for field in ("text", "value", "item"):
            if field in block:
                _check(check_template, block[field], f"{here}/{field}", errors)
        for i, column in enumerate(block.get("columns", [])):
            for field in ("header", "value"):
                if field in column:
                    _check(check_template, column[field], f"{here}/columns/{i}/{field}", errors)
        for r, row in enumerate(block.get("rows", [])):
            for c, cell in enumerate(row):
                _check(check_template, cell, f"{here}/rows/{r}/{c}", errors)
        for i, item in enumerate(block.get("items", [])):
            _check(check_template, item, f"{here}/items/{i}", errors)
        if block.get("type") == "group":
            _walk_blocks(block.get("blocks", []), f"{here}/blocks", errors)


def validate_format_config(config) -> None:
    """Raise ``ValidationError`` listing every problem in ``config``."""
    from ..renderer.fonts import PDF_FONTS

    if not isinstance(config, dict):
        raise ValidationError("format_config must be a JSON object.")
    errors = _schema_errors(FORMAT_CONFIG_SCHEMA, config)
    if errors:
        raise ValidationError(errors)

    for name, style in (config.get("styles") or {}).items():
        if "font" in style and style["font"] not in PDF_FONTS:
            errors.append(f"styles/{name}/font: unknown font {style['font']!r}.")
    for band in ("header", "footer"):
        for position in ("left", "center", "right"):
            text = (config.get(band) or {}).get(position)
            if text:
                _check(check_template, text, f"{band}/{position}", errors)
    for field, text in (config.get("metadata") or {}).items():
        _check(check_template, text, f"metadata/{field}", errors)
    _walk_blocks(config["body"], "body", errors)
    if errors:
        raise ValidationError(errors)


def validate_data_config(config) -> None:
    """Raise ``ValidationError`` listing every problem in ``config``."""
    from .mapping.derived import FUNCTIONS
    from .mapping.direct import compile_path

    if not isinstance(config, dict):
        raise ValidationError("data_config must be a JSON object.")
    errors = _schema_errors(DATA_CONFIG_SCHEMA, config)
    if errors:
        raise ValidationError(errors)

    def check_path(path, where):
        try:
            compile_path(path)
        except PDFConfigurationError:
            errors.append(f"{where}: invalid JSONPath {path!r}.")

    seen = set()
    for index, spec in enumerate(config.get("mappings", [])):
        here = f"mappings/{index}"
        target = spec["target"]
        if target in _RESERVED_TARGETS:
            errors.append(f"{here}/target: {target!r} is reserved.")
        if target in seen:
            errors.append(f"{here}/target: duplicate target {target!r}.")
        seen.add(target)

        kind = spec["type"]
        if kind == "direct" and "path" in spec:
            check_path(spec["path"], f"{here}/path")
            for name, path in (spec.get("columns") or {}).items():
                check_path(path, f"{here}/columns/{name}")
        elif kind == "external_api":
            _check(check_template, spec["url"], f"{here}/url", errors)
            for name, value in (spec.get("params") or {}).items():
                if isinstance(value, str):
                    _check(check_template, value, f"{here}/params/{name}", errors)
            if "path" in spec:
                check_path(spec["path"], f"{here}/path")
            for name, path in (spec.get("fields") or {}).items():
                check_path(path, f"{here}/fields/{name}")
        elif kind == "derived":
            if "expression" in spec:
                _check(check_expression, spec["expression"], f"{here}/expression", errors)
            elif spec["function"] not in FUNCTIONS:
                errors.append(f"{here}/function: unknown function {spec['function']!r}.")
            for i, arg in enumerate(spec.get("args", [])):
                _check(check_expression, arg, f"{here}/args/{i}", errors)
        elif kind == "qr" and "template" in spec:
            _check(check_template, spec["template"], f"{here}/template", errors)

        if "source" in spec and kind != "direct":
            _check(check_expression, spec["source"], f"{here}/source", errors)

    for index, path in enumerate(config.get("significant_fields", [])):
        check_path(path, f"significant_fields/{index}")
    if "bulk" in config:
        check_path(config["bulk"].get("records_path", "$.records"), "bulk/records_path")
    if "request_schema" in config:
        try:
            jsonschema.Draft202012Validator.check_schema(config["request_schema"])
        except jsonschema.SchemaError as exc:
            errors.append(f"request_schema: {exc.message}")
    if "filename" in config:
        _check(check_template, config["filename"], "filename", errors)

    if errors:
        raise ValidationError(errors)


def validate_request_data(data_config: dict, request_data) -> None:
    """Validate request data against the template's optional ``request_schema``."""
    from ..exceptions import PDFRequestDataError

    schema = (data_config or {}).get("request_schema")
    if not schema:
        return
    errors = _schema_errors(schema, request_data)
    if errors:
        raise PDFRequestDataError("Request data is invalid: " + "; ".join(errors[:5]))
