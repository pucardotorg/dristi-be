"""Business rule service: the only entry point for consumers (spec 0019 #5)."""

import threading
from collections import OrderedDict

from apps.core.models import BusinessRule

from . import schemas
from .engines import get_engine
from .exceptions import (
    RuleDefinitionError,
    RuleInputError,
    RuleNotFound,
    RuleOutputError,
)

# Compiled JSON Schema validators, keyed on (rule.id, rule.updated_at, side).
_VALIDATORS = OrderedDict()
_VALIDATORS_LOCK = threading.Lock()
_VALIDATORS_MAX_ENTRIES = 512


def _cache_key(rule):
    """Memo key for a rule's compiled artefacts, or None for an unsaved rule.

    ``updated_at`` is mandatory: rules are edited in place, and a key on ``id``
    alone would keep serving the old expression after an admin edit.
    """
    if rule._state.adding or rule.updated_at is None:
        return None
    return (rule.pk, rule.updated_at)


def _validator(rule, side):
    schema = rule.rule_input_schema if side == "input" else rule.rule_output_schema
    key = _cache_key(rule)
    if key is None:
        return schemas.compile_validator(schema)
    key = (*key, side)
    with _VALIDATORS_LOCK:
        if key in _VALIDATORS:
            _VALIDATORS.move_to_end(key)
            return _VALIDATORS[key]
    validator = schemas.compile_validator(schema)
    with _VALIDATORS_LOCK:
        _VALIDATORS[key] = validator
        while len(_VALIDATORS) > _VALIDATORS_MAX_ENTRIES:
            _VALIDATORS.popitem(last=False)
    return validator


class BusinessRuleService:
    """Plain-Python functions over business rules; no HTTP or DRF dependency."""

    @staticmethod
    def get_rule(code):
        """Return the active rule for ``code``; an inactive rule counts as missing."""
        try:
            return BusinessRule.objects.active().get(code=code)
        except BusinessRule.DoesNotExist:
            raise RuleNotFound(f"No active business rule with code {code!r}.") from None

    @staticmethod
    def validate_rule(rule):
        """Check the schemas, compile the expression, and run the #2.6 identifier check.

        Raises RuleSchemaError (with ``field``) or RuleDefinitionError.
        """
        schemas.check_schema(rule.rule_input_schema, field="rule_input_schema")
        schemas.check_schema(rule.rule_output_schema, field="rule_output_schema")
        engine = get_engine(rule.engine)
        engine.validate(rule.rule_expression, rule.rule_input_schema)
        undeclared = engine.referenced_inputs(
            rule.rule_expression, rule.rule_input_schema
        ) - schemas.declared_inputs(rule.rule_input_schema)
        if undeclared:
            raise RuleDefinitionError(
                "Expression reads input(s) not declared in rule_input_schema: "
                + ", ".join(sorted(undeclared))
            )

    @classmethod
    def evaluate(cls, code, payload):
        """Evaluate the active rule ``code`` against ``payload`` and return the envelope."""
        return cls._evaluate(cls.get_rule(code), payload)

    @classmethod
    def dry_run(cls, rule, payload, *, trace=False):
        """Evaluate ``rule`` (saved or not, active or not) through the same path.

        With ``trace=True`` and an engine that supports it, the envelope also
        carries a ``trace`` key. Only the admin dry run asks for this.
        """
        envelope = cls._evaluate(rule, payload)
        if trace:
            engine = get_engine(rule.engine)
            trace_data = engine.trace_with_timeout(
                rule.rule_expression, payload, rule.rule_input_schema
            )
            if trace_data is not None:
                envelope["trace"] = trace_data
        return envelope

    @staticmethod
    def _evaluate(rule, payload):
        # Input is checked before the engine is touched: a bad payload is a
        # caller bug, not a rule failure.
        schemas.ensure_plain_json(payload, error_class=RuleInputError)
        schemas.validate_instance(
            _validator(rule, "input"), payload, error_class=RuleInputError, label="Input"
        )
        engine = get_engine(rule.engine)
        result = engine.evaluate_with_timeout(
            rule.rule_expression, payload, rule.rule_input_schema, cache_key=_cache_key(rule)
        )
        schemas.ensure_plain_json(result, error_class=RuleOutputError)
        schemas.validate_instance(
            _validator(rule, "output"), result, error_class=RuleOutputError, label="Output"
        )
        return {"code": rule.code, "engine": rule.engine, "result": result}
