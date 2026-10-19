"""Jinja2 text placeholders for configuration strings (design decision 3).

One sandboxed environment renders every configuration string: block text,
table cells, URLs of external API mappings, and so on. Autoescaping is on
because rendered text is fed to the renderer's inline markup (``<b>``,
``<i>``, ``<u>``, ``<br/>``, ``<font>``): markup written in the template is
trusted configuration, values coming from request data are escaped.

``StrictUndefined`` turns a reference to a missing value into an error so a
document is never silently produced with blanks; templates opt into optional
values with ``| default(...)``.

URL templates (``render_url``) use a third environment that percent-encodes
every inserted value, see ``render_url``.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

from jinja2 import StrictUndefined, TemplateError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment, SecurityError
from markupsafe import Markup, escape

from ..exceptions import PDFConfigurationError, PDFRequestDataError

# Dot segments would still navigate after percent-encoding, because ``quote``
# leaves ``.`` alone and servers resolve ``.``/``..`` path segments.
_DOT_SEGMENTS = frozenset({".", ".."})


def _nl2br(value) -> Markup:
    """Escape ``value`` and turn newlines into line breaks."""
    return Markup("<br/>").join(escape(str(value)).split("\n"))


@lru_cache(maxsize=2)
def get_environment(autoescape: bool = True) -> SandboxedEnvironment:
    """Return the shared sandboxed environment (one per autoescape mode)."""
    from .mapping.formatting import format_date, format_number

    env = SandboxedEnvironment(autoescape=autoescape, undefined=StrictUndefined)
    env.filters["format_date"] = format_date
    env.filters["format_number"] = format_number
    env.filters["nl2br"] = _nl2br
    return env


class URLPath(str):
    """A value already encoded by the ``url_path`` filter; inserted verbatim."""


def encode_url_value(value) -> str:
    """Percent-encode ``value`` as exactly one URL path segment or query value.

    Every reserved character (``/ ? # & = @ : +`` and so on) is encoded, so the
    value can never add a segment, start a query or fragment, add a parameter,
    or change the host. A value that is only ``.`` or ``..`` is rejected,
    because ``quote`` leaves dots alone and such a segment would navigate.
    """
    if isinstance(value, URLPath):
        return str(value)
    text = "" if value is None else str(value)
    if text in _DOT_SEGMENTS:
        raise PDFRequestDataError("A URL value cannot be '.' or '..'.")
    return quote(text, safe="")


def _url_path(value) -> URLPath:
    """Encode a multi-segment path, keeping ``/`` between segments.

    The explicit opt-out for templates that take several path segments from
    one value: ``{{ data.path | url_path }}``. Every segment is still encoded,
    and empty, ``.`` and ``..`` segments are rejected, so the value can add
    path segments but cannot climb out of the template's path, start a query
    or change the host.
    """
    text = "" if value is None else str(value)
    segments = text.split("/")
    if any(segment in _DOT_SEGMENTS or segment == "" for segment in segments):
        raise PDFRequestDataError("A URL path value cannot contain empty, '.' or '..' segments.")
    return URLPath("/".join(quote(segment, safe="") for segment in segments))


@lru_cache(maxsize=1)
def get_url_environment() -> SandboxedEnvironment:
    """Return the environment for URL templates: every output is URL-encoded."""
    from .mapping.formatting import format_date, format_number

    env = SandboxedEnvironment(
        autoescape=False, undefined=StrictUndefined, finalize=encode_url_value
    )
    env.filters["format_date"] = format_date
    env.filters["format_number"] = format_number
    env.filters["url_path"] = _url_path
    return env


@lru_cache(maxsize=1024)
def _compile_template(source: str, autoescape: bool = True):
    return get_environment(autoescape).from_string(source)


@lru_cache(maxsize=512)
def _compile_url_template(source: str):
    return get_url_environment().from_string(source)


@lru_cache(maxsize=512)
def _compile_expression(source: str):
    return get_environment(False).compile_expression(source, undefined_to_none=False)


def check_template(source: str) -> None:
    """Raise ``TemplateError`` if ``source`` is not valid template syntax."""
    _compile_template(source)


def check_url_template(source: str) -> None:
    """Raise ``TemplateError`` if ``source`` is not a valid URL template."""
    _compile_url_template(source)


def check_expression(source: str) -> None:
    """Raise ``TemplateError`` if ``source`` is not a valid expression."""
    _compile_expression(source)


def render_text(source: str, variables: dict, *, escape_output: bool = True) -> str:
    """Render a template string.

    ``escape_output=False`` is for values that are not fed to the renderer's
    markup, such as URLs and query parameters, where HTML escaping would
    corrupt the value.
    """
    if not isinstance(source, str):
        return "" if source is None else str(source)
    if "{" not in source:
        # Literal configuration text: trusted, nothing to substitute.
        return source
    try:
        return _compile_template(source, escape_output).render(**variables)
    except UndefinedError as exc:
        raise PDFRequestDataError(f"Template references a missing value: {exc.message}") from exc
    except SecurityError as exc:
        raise PDFConfigurationError("Template uses a forbidden operation.") from exc
    except TemplateError as exc:
        raise PDFConfigurationError(f"Template error: {exc.message}") from exc


def render_url(source: str, variables: dict) -> str:
    """Render a URL template, percent-encoding every inserted value.

    Literal template text -- scheme, host, fixed path, ``?``, ``&`` -- is
    trusted configuration and kept exactly as written. Each ``{{ ... }}``
    output is encoded with ``encode_url_value``, whatever the shape of the URL
    (path segment, query value, anything else), so request data can only ever
    fill in one value and never change the URL's structure or target. A value
    that should span several path segments must opt in explicitly with
    ``| url_path``.
    """
    if not isinstance(source, str):
        raise PDFConfigurationError("A URL template must be a string.")
    if "{" not in source:
        return source
    try:
        return _compile_url_template(source).render(**variables)
    except UndefinedError as exc:
        raise PDFRequestDataError(f"URL references a missing value: {exc.message}") from exc
    except SecurityError as exc:
        raise PDFConfigurationError("URL template uses a forbidden operation.") from exc
    except TemplateError as exc:
        raise PDFConfigurationError(f"URL template error: {exc.message}") from exc


def evaluate(expression: str, variables: dict):
    """Evaluate a template expression and return its Python value."""
    try:
        return _compile_expression(expression)(**variables)
    except UndefinedError as exc:
        raise PDFRequestDataError(f"Expression references a missing value: {exc.message}") from exc
    except SecurityError as exc:
        raise PDFConfigurationError("Expression uses a forbidden operation.") from exc
    except TemplateError as exc:
        raise PDFConfigurationError(f"Expression error: {exc.message}") from exc
    except (TypeError, ValueError, ArithmeticError, LookupError) as exc:
        raise PDFRequestDataError(
            f"Expression could not be evaluated: {type(exc).__name__}"
        ) from exc
