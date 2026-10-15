"""Exception hierarchy for business rules (spec 0019 #6).

Defined in their own module because both the service and the engine adapters
raise them; living in ``services.py`` would make the two import each other.
"""


class RuleError(Exception):
    """Base class for every business-rule failure."""


class RuleNotFound(RuleError):  # noqa: N818 - name fixed by spec 0019 #6
    """No active rule exists for the requested code."""


class EngineNotAvailable(RuleError):  # noqa: N818 - name fixed by spec 0019 #6
    """The rule's engine has no registered adapter."""


class RuleSchemaError(RuleError):
    """``rule_input_schema`` / ``rule_output_schema`` is not a valid JSON Schema.

    ``field`` names the offending model field so ``clean()`` can attach the
    error to it.
    """

    def __init__(self, message, *, field=None):
        super().__init__(message)
        self.field = field


class RuleDefinitionError(RuleError):
    """The expression does not compile, or reads an undeclared input."""


class RuleInputError(RuleError):
    """The payload does not satisfy ``rule_input_schema``."""


class RuleOutputError(RuleError):
    """The engine output does not satisfy ``rule_output_schema``."""


class RuleEvaluationError(RuleError):
    """Evaluation raised, or exceeded ``RULES_EVALUATION_TIMEOUT_SECONDS``."""
