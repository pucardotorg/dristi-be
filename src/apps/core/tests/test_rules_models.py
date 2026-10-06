"""Tests for the BusinessRule model: fields, clean(), history and caching (spec 0019)."""

import pytest
from cachalot.settings import cachalot_settings
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core.models import BusinessRule
from apps.core.rules.engines import get_engine
from apps.core.rules.services import BusinessRuleService

from .rules_samples import (
    COURT_FEE_EXPRESSION,
    COURT_FEE_INPUT,
    COURT_FEE_OUTPUT,
    INPUT_NODE,
    OUTPUT_NODE,
    edge,
    jdm,
    make_gorules_rule,
    make_rule,
)


def build_rule(**overrides):
    """An unsaved rule-engine rule, valid unless overridden."""
    fields = {
        "code": "COURT_FEE_CALCULATION",
        "name": "Court fee calculation",
        "engine": BusinessRule.RuleEngineType.RULE_ENGINE,
        "rule_expression": "case_value > 100000 ? {'fee': 500} : {'fee': 100}",
        "rule_input_schema": COURT_FEE_INPUT,
        "rule_output_schema": COURT_FEE_OUTPUT,
    }
    fields.update(overrides)
    return BusinessRule(**fields)


def clean_errors(rule):
    """Return ``{field: [messages]}`` from ``rule.full_clean()``."""
    with pytest.raises(ValidationError) as exc_info:
        rule.full_clean()
    return exc_info.value.message_dict


@pytest.mark.django_db
class TestFields:
    def test_engine_choices_are_lowercase_values_with_labels(self):
        assert BusinessRule.RuleEngineType.choices == [
            ("rule_engine", "Rule Engine"),
            ("gorules", "GoRules"),
        ]

    def test_meta(self):
        meta = BusinessRule._meta
        assert meta.db_table == "core_businessrule"
        assert BusinessRule.history.model._meta.db_table == "core_historicalbusinessrule"
        assert meta.ordering == ("code",)
        assert meta.get_field("engine").db_index
        assert meta.get_field("code").unique
        assert meta.get_field("is_active").default is True

    def test_str(self):
        assert str(build_rule()) == "Court fee calculation (COURT_FEE_CALCULATION)"

    def test_ordering_by_code(self):
        make_rule(code="B_RULE")
        make_rule(code="A_RULE")
        assert list(BusinessRule.objects.values_list("code", flat=True)) == ["A_RULE", "B_RULE"]


@pytest.mark.django_db
class TestCode:
    def test_code_must_be_unique(self):
        make_rule()
        assert "code" in clean_errors(build_rule())

    @pytest.mark.parametrize("code", ["court_fee", "COURT-FEE", "Court Fee", "COURT FEE", ""])
    def test_code_must_be_uppercase_snake_case(self, code):
        assert "code" in clean_errors(build_rule(code=code))

    def test_valid_code_passes(self):
        build_rule(code="COURT_FEE_2024").full_clean()


@pytest.mark.django_db
class TestClean:
    @pytest.mark.parametrize("expression", ["", "   \n"])
    def test_rejects_empty_expression(self, expression):
        assert "rule_expression" in clean_errors(build_rule(rule_expression=expression))

    def test_rejects_oversized_expression(self, settings):
        settings.RULES_MAX_EXPRESSION_BYTES = 20
        errors = clean_errors(build_rule(rule_expression="case_value > 100000000000000"))
        assert "larger than 20 bytes" in errors["rule_expression"][0]

    def test_size_is_measured_in_utf8_bytes(self, settings):
        settings.RULES_MAX_EXPRESSION_BYTES = 12
        # 6 characters, 18 bytes.
        errors = clean_errors(build_rule(rule_expression="'₹₹₹₹'"))
        assert "larger than 12 bytes" in errors["rule_expression"][0]

    @pytest.mark.parametrize("field", ["rule_input_schema", "rule_output_schema"])
    def test_rejects_invalid_json_schema(self, field):
        errors = clean_errors(build_rule(**{field: {"type": "not-a-type"}}))
        assert "Invalid JSON Schema" in " ".join(errors[field])

    @pytest.mark.parametrize("field", ["rule_input_schema", "rule_output_schema"])
    @pytest.mark.parametrize("missing", [None, {}])
    def test_rejects_missing_schema(self, field, missing):
        assert field in clean_errors(build_rule(**{field: missing}))

    def test_rejects_expression_reading_undeclared_input(self):
        errors = clean_errors(build_rule(rule_expression="court_level > 2"))
        assert "court_level" in errors["rule_expression"][0]

    def test_rejects_gorules_graph_reading_undeclared_input(self):
        graph = jdm(
            [
                INPUT_NODE,
                {
                    "id": "x",
                    "type": "expressionNode",
                    "name": "x",
                    "content": {
                        "expressions": [{"id": "a", "key": "eligible", "value": "court_level > 2"}]
                    },
                },
                OUTPUT_NODE,
            ],
            [edge("in", "x"), edge("x", "out")],
        )
        errors = clean_errors(
            build_rule(engine=BusinessRule.RuleEngineType.GORULES, rule_expression=graph)
        )
        assert "not declared in rule_input_schema: court_level" in errors["rule_expression"][0]

    def test_rejects_expression_that_does_not_compile(self):
        errors = clean_errors(build_rule(rule_expression="case_value >"))
        assert "does not compile" in errors["rule_expression"][0]

    def test_rejects_gorules_document_that_does_not_compile(self):
        errors = clean_errors(
            build_rule(engine=BusinessRule.RuleEngineType.GORULES, rule_expression="{not json")
        )
        assert "not valid JSON" in errors["rule_expression"][0]

    def test_rejects_unknown_engine(self):
        assert "engine" in clean_errors(build_rule(engine="jexl"))

    def test_type_mismatch_is_a_save_time_error_before_any_evaluation(self, monkeypatch):
        adapter = get_engine(BusinessRule.RuleEngineType.RULE_ENGINE)

        def fail(*args, **kwargs):
            raise AssertionError("evaluate() must not run during clean()")

        monkeypatch.setattr(adapter, "evaluate", fail)
        errors = clean_errors(build_rule(rule_expression="case_type > 5"))
        assert "data type mismatch" in errors["rule_expression"][0]

    def test_now_builtin_does_not_trip_undeclared_check(self):
        schema = {
            "type": "object",
            "properties": {"filed_at": {"type": "string", "format": "date-time"}},
            "required": ["filed_at"],
        }
        build_rule(
            rule_expression="$now > filed_at",
            rule_input_schema=schema,
            rule_output_schema={"type": "boolean"},
        ).full_clean()

    def test_save_runs_full_clean(self):
        with pytest.raises(ValidationError):
            make_rule(rule_expression="undeclared_symbol")
        assert not BusinessRule.objects.exists()

    def test_validate_rule_is_the_shared_check(self):
        """clean() and the admin form both delegate to BusinessRuleService.validate_rule."""
        BusinessRuleService.validate_rule(build_rule())


@pytest.mark.django_db
class TestHistory:
    def test_edits_are_recorded_in_history(self):
        rule = make_rule()
        rule.rule_expression = "{'fee': 250}"
        rule.save()
        assert rule.history.count() == 2
        assert rule.history.earliest().rule_expression == COURT_FEE_EXPRESSION
        assert rule.history.latest().rule_expression == "{'fee': 250}"

    def test_gorules_rule_saves(self):
        assert make_gorules_rule().history.count() == 1


class TestCachingSettings:
    def test_only_the_rule_table_is_allow_listed(self):
        assert "core_businessrule" in settings.CACHALOT_ONLY_CACHABLE_TABLES
        assert "core" not in settings.CACHALOT_ONLY_CACHABLE_APPS
        assert "core_historicalbusinessrule" not in cachalot_settings.CACHALOT_ONLY_CACHABLE_TABLES
        assert "core_additionalattribute" not in cachalot_settings.CACHALOT_ONLY_CACHABLE_TABLES


@pytest.mark.django_db
class TestCaching:
    def test_lookup_by_code_is_served_from_cache_and_invalidated_on_write(self):
        rule = make_rule()
        BusinessRuleService.get_rule(rule.code)

        with CaptureQueriesContext(connection) as cached:
            BusinessRuleService.get_rule(rule.code)
        assert len(cached.captured_queries) == 0

        rule.name = "Renamed"
        rule.save()
        with CaptureQueriesContext(connection) as after_write:
            assert BusinessRuleService.get_rule(rule.code).name == "Renamed"
        assert len(after_write.captured_queries) > 0

    def test_history_table_is_not_cached(self):
        rule = make_rule()
        list(rule.history.all())
        with CaptureQueriesContext(connection) as second:
            list(rule.history.all())
        assert len(second.captured_queries) > 0
