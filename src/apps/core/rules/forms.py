"""Admin form that refuses to save a rule which cannot be evaluated (spec 0019 #9.1)."""

import json

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from apps.core.models import BusinessRule

from .exceptions import (
    EngineNotAvailable,
    RuleDefinitionError,
    RuleError,
    RuleInputError,
    RuleOutputError,
    RuleSchemaError,
)
from .services import BusinessRuleService


def json_equal(left, right):
    """Compare two JSON values strictly: ``True`` is not ``1``, but ``500`` is ``500.0``."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(map(json_equal, left, right))
    return type(left) is type(right) and left == right


class BusinessRuleAdminForm(forms.ModelForm):
    """Validates schemas, compiles the expression, checks identifiers, then dry-runs it.

    ``test_input`` and ``expected_result`` are not persisted (spec 0019 #11.8).
    After a successful ``is_valid()``, ``dry_run_result`` holds the envelope
    returned by :meth:`BusinessRuleService.dry_run`.
    """

    test_input = forms.JSONField(
        required=False,
        label="Test input (JSON)",
        help_text=(
            "Sample payload for the dry run; it must satisfy the input schema. "
            "Required unless RULES_ADMIN_DRY_RUN_REQUIRED is off. Not saved."
        ),
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    expected_result = forms.JSONField(
        required=False,
        label="Expected result (JSON)",
        help_text="Optional. When given, the dry-run result must equal it. Not saved.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = BusinessRule
        fields = (
            "code",
            "name",
            "description",
            "engine",
            "rule_expression",
            "rule_input_schema",
            "rule_output_schema",
            "is_active",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dry_run_result = None

    def _raw_value_given(self, name):
        """True when the author typed something into a non-model JSON field.

        ``forms.JSONField`` turns both an empty box and a literal ``null`` into
        ``None``; only the raw input tells them apart.
        """
        raw = self.data.get(self.add_prefix(name), "")
        return bool(raw.strip())

    def clean(self):
        cleaned = super().clean()
        rule_fields = ("engine", "rule_expression", "rule_input_schema", "rule_output_schema")
        if any(field in self.errors for field in (*rule_fields, "test_input", "expected_result")):
            return cleaned

        rule = BusinessRule(
            **{field: cleaned.get(field) for field in rule_fields},
            code=cleaned.get("code") or "",
        )
        if self.instance.pk:
            rule.pk = self.instance.pk

        # Steps 1-3: check_schema, engine.validate, undeclared-identifier check.
        try:
            BusinessRuleService.validate_rule(rule)
        except RuleSchemaError as exc:
            raise ValidationError({exc.field: str(exc)}) from exc
        except (RuleDefinitionError, EngineNotAvailable) as exc:
            raise ValidationError({"rule_expression": str(exc)}) from exc

        # Step 4: dry run, unless it is optional and no sample was given.
        if not self._raw_value_given("test_input"):
            if settings.RULES_ADMIN_DRY_RUN_REQUIRED:
                raise ValidationError({"test_input": "A sample input is required for the dry run."})
            return cleaned

        try:
            envelope = BusinessRuleService.dry_run(
                rule,
                cleaned.get("test_input"),
                trace=rule.engine == BusinessRule.RuleEngineType.GORULES,
            )
        except RuleInputError as exc:
            raise ValidationError({"test_input": f"Dry run rejected the sample: {exc}"}) from exc
        except RuleOutputError as exc:
            raise ValidationError({"rule_output_schema": f"Dry run failed: {exc}"}) from exc
        except RuleError as exc:
            raise ValidationError({"rule_expression": f"Dry run failed: {exc}"}) from exc

        if self._raw_value_given("expected_result") and not json_equal(
            envelope["result"], cleaned.get("expected_result")
        ):
            raise ValidationError(
                {
                    "expected_result": (
                        "Dry run returned "
                        f"{json.dumps(envelope['result'])}, which differs from the expected result."
                    )
                }
            )

        self.dry_run_result = envelope
        return cleaned
