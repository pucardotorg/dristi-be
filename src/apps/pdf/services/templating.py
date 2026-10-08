"""Jinja2 text placeholders for configuration strings (design decision 3).

One sandboxed environment renders every configuration string: block text,
table cells, URLs of external API mappings, and so on. Autoescaping is on
because rendered text is fed to the renderer's inline markup (``<b>``,
``<i>``, ``<u>``, ``<br/>``, ``<font>``): markup written in the template is
trusted configuration, values coming from request data are escaped.

``StrictUndefined`` turns a reference to a missing value into an error so a
document is never silently produced with blanks; templates opt into optional
values with ``| default(...)``.
"""

from __future__ import annotations

from functools import lru_cache

from jinja2 import StrictUndefined, TemplateError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment, SecurityError
from markupsafe import Markup, escape

from ..exceptions import PDFConfigurationError, PDFRequestDataError


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


@lru_cache(maxsize=1024)
def _compile_template(source: str, autoescape: bool = True):
    return get_environment(autoescape).from_string(source)


@lru_cache(maxsize=512)
def _compile_expression(source: str):
    return get_environment(False).compile_expression(source, undefined_to_none=False)


def check_template(source: str) -> None:
    """Raise ``TemplateError`` if ``source`` is not valid template syntax."""
    _compile_template(source)


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
