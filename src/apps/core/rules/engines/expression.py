"""rule-engine adapter (spec 0019 #4.4).

Deliberately not named ``rule_engine.py``: a module named after the library it
imports confuses the next reader even though absolute imports keep it working.
"""

import datetime
from collections.abc import Mapping
from decimal import Decimal

import rule_engine
from django.conf import settings
from rule_engine import errors as rule_engine_errors
from rule_engine.types import DataType

from apps.core.models import BusinessRule

from ..exceptions import RuleDefinitionError, RuleEvaluationError
from ..schemas import datatypes_from_json_schema
from .base import RuleEngine


def _describe(exc):
    """Return a readable one-line description of a rule-engine exception."""
    if isinstance(exc, rule_engine_errors.SymbolResolutionError):
        text = f"undeclared symbol {exc.symbol_name!r}"
        if exc.suggestion:
            text += f" (did you mean {exc.suggestion!r}?)"
        return text
    if isinstance(exc, rule_engine_errors.SymbolTypeError):
        return (
            f"symbol {exc.symbol_name!r} has type {exc.is_type.name}, "
            f"expected {exc.expected_type.name}"
        )
    if isinstance(exc, rule_engine_errors.RuleSyntaxError) and exc.token is not None:
        return f"syntax error at position {exc.token.lexpos} near {exc.token.value!r}"
    message = getattr(exc, "message", "") or str(exc)
    return f"{type(exc).__name__}: {message}"


def normalize(value):
    """Convert rule-engine output into JSON-native data, recursively.

    ``FLOAT`` is ``Decimal``-backed: an integral Decimal becomes ``int`` and
    any other becomes ``float`` (spec 0019 #11.7; lossy beyond ~15 significant
    digits). ``DATETIME`` becomes an ISO-8601 string. Mappings and arrays
    (returned as ``OrderedDict`` / ``tuple``) are walked so nested values are
    converted too.
    """
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise RuleEvaluationError(f"Rule returned a non-finite number: {value}.")
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise RuleEvaluationError(f"Rule returned a non-finite number: {value}.")
        return value
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuleEvaluationError(
                    f"Rule returned a mapping with non-string key {key!r}; JSON objects need string keys."
                )
            normalized[key] = normalize(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    raise RuleEvaluationError(
        f"Rule returned a value of type {type(value).__name__}, which has no JSON representation."
    )


class RuleEngineAdapter(RuleEngine):
    """Evaluates ``rule-engine`` expressions with payload keys as top-level symbols."""

    engine = BusinessRule.RuleEngineType.RULE_ENGINE

    def _context(self, rule_input_schema, input_lookups=None):
        """Build a per-rule Context whose type resolver comes from the input schema.

        When ``input_lookups`` is given, every name the parser asks the type
        resolver about is added to it. Builtins and comprehension variables
        are resolved from their own scopes and never reach this resolver.
        """
        type_resolver = rule_engine.type_resolver_from_dict(
            datatypes_from_json_schema(rule_input_schema)
        )
        if input_lookups is not None:
            schema_resolver = type_resolver

            def type_resolver(name):
                input_lookups.add(name)
                return schema_resolver(name)

        return rule_engine.Context(
            resolver=rule_engine.resolve_item,
            type_resolver=type_resolver,
            default_timezone=settings.TIME_ZONE,
        )

    def _compile(self, rule_expression, rule_input_schema, context=None):
        """Parse and type-check the expression; parse-phase errors are definition errors.

        rule-engine reports type mismatches as ``EvaluationError`` and unknown
        symbols as ``SymbolResolutionError`` even at parse time, so the phase,
        not the exception class, decides the translation.
        """
        try:
            if context is None:
                context = self._context(rule_input_schema)
            return rule_engine.Rule(rule_expression, context=context)
        except Exception as exc:
            raise RuleDefinitionError(f"Expression does not compile: {_describe(exc)}") from exc

    def validate(self, rule_expression, rule_input_schema):
        self._compile(rule_expression, rule_input_schema)

    def referenced_inputs(self, rule_expression, rule_input_schema):
        input_lookups = set()
        context = self._context(rule_input_schema, input_lookups)
        self._compile(rule_expression, rule_input_schema, context=context)
        # Context.symbols holds every name the parser saw. Builtins are recorded
        # without their "$" ("$now" -> "now") and are resolved from
        # context.builtins; comprehension variables are recorded too and are
        # resolved from their assignment scope. Neither reaches the input type
        # resolver, so keeping only the symbols that did drops both. Unlike
        # subtracting set(context.builtins), this keeps an input that shares a
        # builtin's name (an input "today" read next to "$today").
        return {name for name in context.symbols if name in input_lookups}

    def evaluate(self, rule_expression, payload, rule_input_schema, *, cache_key=None):
        rule = self._memoized(cache_key, lambda: self._compile(rule_expression, rule_input_schema))
        thing = self._coerce_payload(payload, rule_input_schema)
        try:
            # evaluate(), never matches(): matches() coerces the result to a bool.
            result = rule.evaluate(thing)
        except Exception as exc:
            raise RuleEvaluationError(f"Evaluation failed: {_describe(exc)}") from exc
        return normalize(result)

    @staticmethod
    def _coerce_payload(payload, rule_input_schema):
        """Parse ISO-8601 strings for symbols typed ``DATETIME``.

        JSON has no datetime type, so callers send strings; rule-engine rejects
        a string for a ``DATETIME`` symbol. ``payload`` is already the guard's
        deep copy, so this never touches the caller's data.
        """
        datatypes = datatypes_from_json_schema(rule_input_schema)
        for name, datatype in datatypes.items():
            value = payload.get(name)
            if datatype is DataType.DATETIME and isinstance(value, str):
                try:
                    payload[name] = datetime.datetime.fromisoformat(value)
                except ValueError as exc:
                    raise RuleEvaluationError(
                        f"$.{name}: {value!r} is not an ISO-8601 date or date-time."
                    ) from exc
        return payload
