"""Adapter-level tests against the real rule-engine and zen-engine libraries (spec 0019 #4)."""

import copy
import threading
import time
from decimal import Decimal

import pytest
import rule_engine
from django.apps import apps
from rule_engine.types import DataType

from apps.core.models import BusinessRule
from apps.core.rules import engines
from apps.core.rules.engines import get_engine
from apps.core.rules.engines import gorules as gorules_module
from apps.core.rules.engines.expression import RuleEngineAdapter, normalize
from apps.core.rules.engines.gorules import GoRulesRuleEngine
from apps.core.rules.exceptions import (
    EngineNotAvailable,
    RuleDefinitionError,
    RuleEvaluationError,
)
from apps.core.rules.schemas import datatype_for_property, datatypes_from_json_schema

from .rules_samples import (
    COURT_FEE_INPUT,
    ELIGIBILITY_GRAPH,
    INPUT_NODE,
    OUTPUT_NODE,
    edge,
    expression_node,
    jdm,
    linear_graph,
    table_node,
)

FILING_INPUT = {
    "type": "object",
    "properties": {
        "case_value": {"type": "number"},
        "filed_at": {"type": "string", "format": "date-time"},
        "items": {"type": "array"},
    },
}


@pytest.fixture
def expression_adapter():
    return get_engine(BusinessRule.RuleEngineType.RULE_ENGINE)


@pytest.fixture
def gorules_adapter():
    return get_engine(BusinessRule.RuleEngineType.GORULES)


def guard_threads():
    return [t for t in threading.enumerate() if t.name.startswith("rule-eval-")]


class TestRegistry:
    def test_both_adapters_are_registered(self):
        assert isinstance(get_engine("rule_engine"), RuleEngineAdapter)
        assert isinstance(get_engine("gorules"), GoRulesRuleEngine)
        assert get_engine("rule_engine").engine == BusinessRule.RuleEngineType.RULE_ENGINE

    def test_unknown_engine_raises_engine_not_available(self):
        with pytest.raises(EngineNotAvailable):
            get_engine("jexl")

    @pytest.mark.django_db
    def test_ready_builds_registry_without_database_access(self, django_assert_num_queries):
        with django_assert_num_queries(0):
            apps.get_app_config("core").ready()
        assert set(engines._REGISTRY) == {"rule_engine", "gorules"}


class TestSchemaToDataType:
    @pytest.mark.parametrize(
        ("property_schema", "expected"),
        [
            ({"type": "string"}, DataType.STRING),
            ({"type": "string", "format": "date-time"}, DataType.DATETIME),
            ({"type": "string", "format": "date"}, DataType.DATETIME),
            ({"type": "string", "format": "email"}, DataType.STRING),
            ({"type": "number"}, DataType.FLOAT),
            ({"type": "integer"}, DataType.FLOAT),
            ({"type": "boolean"}, DataType.BOOLEAN),
            ({"type": "object"}, DataType.MAPPING),
            ({"type": "array"}, DataType.ARRAY),
            ({"type": "null"}, DataType.NULL),
            ({}, DataType.UNDEFINED),
            ({"type": ["string", "null"]}, DataType.UNDEFINED),
            ({"anyOf": [{"type": "string"}, {"type": "number"}]}, DataType.UNDEFINED),
            ({"oneOf": [{"type": "string"}]}, DataType.UNDEFINED),
            ({"type": "string", "anyOf": [{"maxLength": 2}]}, DataType.UNDEFINED),
            ({"enum": ["a", "b"]}, DataType.UNDEFINED),
            (True, DataType.UNDEFINED),
        ],
    )
    def test_mapping(self, property_schema, expected):
        assert datatype_for_property(property_schema) is expected

    def test_schema_maps_every_declared_property(self):
        assert datatypes_from_json_schema(COURT_FEE_INPUT) == {
            "case_value": DataType.FLOAT,
            "case_type": DataType.STRING,
        }

    def test_undefined_disables_type_checking_for_that_symbol_only(self, expression_adapter):
        schema = {
            "type": "object",
            "properties": {
                "loose": {"anyOf": [{"type": "string"}, {"type": "number"}]},
                "n": {"type": "number"},
            },
        }
        expression_adapter.validate("loose > 5", schema)
        expression_adapter.validate('loose == "x"', schema)
        with pytest.raises(RuleDefinitionError, match="data type mismatch"):
            expression_adapter.validate('loose > 5 and n > "x"', schema)


class TestRuleEngineAdapter:
    def test_validate_accepts_typed_expression(self, expression_adapter):
        expression_adapter.validate("case_value > 100000 ? 500 : 100", COURT_FEE_INPUT)

    def test_syntax_error_is_definition_error(self, expression_adapter):
        with pytest.raises(RuleDefinitionError, match="syntax error"):
            expression_adapter.validate("case_value >", COURT_FEE_INPUT)

    def test_type_error_at_parse_is_definition_error(self, expression_adapter):
        # rule-engine raises EvaluationError for this even though it is a parse-time failure.
        with pytest.raises(RuleDefinitionError, match="data type mismatch") as exc_info:
            expression_adapter.validate("case_type > 5", COURT_FEE_INPUT)
        assert isinstance(exc_info.value.__cause__, rule_engine.EvaluationError)

    def test_undeclared_symbol_at_parse_is_definition_error(self, expression_adapter):
        with pytest.raises(
            RuleDefinitionError, match="undeclared symbol 'court_level'"
        ) as exc_info:
            expression_adapter.validate("court_level > 1", COURT_FEE_INPUT)
        assert isinstance(exc_info.value.__cause__, rule_engine.SymbolResolutionError)

    def test_referenced_inputs_reads_context_symbols(self, expression_adapter, monkeypatch):
        seen = {}
        original = rule_engine.Rule.__init__

        def spy(self, text, context=None):
            original(self, text, context=context)
            seen["symbols"] = set(context.symbols)

        monkeypatch.setattr(rule_engine.Rule, "__init__", spy)
        referenced = expression_adapter.referenced_inputs(
            'case_type == "civil" and case_value > 1', COURT_FEE_INPUT
        )
        assert referenced == {"case_type", "case_value"} == seen["symbols"]

    def test_referenced_inputs_excludes_builtins_and_comprehension_variables(
        self, expression_adapter
    ):
        expression = "$now > filed_at and $sum([x * 2 for x in items]) > case_value"
        assert expression_adapter.referenced_inputs(expression, FILING_INPUT) == {
            "filed_at",
            "items",
            "case_value",
        }

    def test_input_sharing_a_builtin_name_is_still_an_input(self, expression_adapter):
        schema = {"type": "object", "properties": {"today": {"type": "string", "format": "date"}}}
        assert expression_adapter.referenced_inputs("today < $today", schema) == {"today"}

    def test_evaluate_returns_the_value_not_a_boolean(self, expression_adapter, monkeypatch):
        def no_matches(*args, **kwargs):
            raise AssertionError("matches() must not be used")

        monkeypatch.setattr(rule_engine.Rule, "matches", no_matches)
        result = expression_adapter.evaluate(
            "case_value * 2", {"case_value": 150000, "case_type": "civil"}, COURT_FEE_INPUT
        )
        assert result == 300000
        assert result is not True

    def test_evaluation_error_is_translated(self, expression_adapter):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        }
        with pytest.raises(RuleEvaluationError, match="division by zero") as exc_info:
            expression_adapter.evaluate("a / b", {"a": 1, "b": 0}, schema)
        assert isinstance(exc_info.value.__cause__, rule_engine.EngineError)

    def test_missing_symbol_at_evaluation_is_evaluation_error(self, expression_adapter):
        # A declared but optional property that the caller omitted.
        with pytest.raises(RuleEvaluationError, match="case_type"):
            expression_adapter.evaluate('case_type == "civil"', {"case_value": 1}, COURT_FEE_INPUT)

    def test_iso_strings_are_parsed_for_datetime_symbols(self, expression_adapter):
        assert (
            expression_adapter.evaluate(
                'filed_at > d"2024-01-01"', {"filed_at": "2024-06-01T10:00:00Z"}, FILING_INPUT
            )
            is True
        )

    def test_unparseable_datetime_string_is_evaluation_error(self, expression_adapter):
        with pytest.raises(RuleEvaluationError, match="ISO-8601"):
            expression_adapter.evaluate("filed_at", {"filed_at": "yesterday"}, FILING_INPUT)

    def test_evaluate_with_timeout_does_not_mutate_payload(self, expression_adapter):
        payload = {"case_value": 5, "filed_at": "2024-06-01T10:00:00Z", "items": [{"n": 1}]}
        snapshot = copy.deepcopy(payload)
        expression_adapter.evaluate_with_timeout("filed_at", payload, FILING_INPUT)
        assert payload == snapshot
        assert isinstance(payload["filed_at"], str)

    def test_timeout_terminates_runaway_expression(self, expression_adapter, settings):
        settings.RULES_EVALUATION_TIMEOUT_SECONDS = 0.2
        schema = {"type": "object", "properties": {"n": {"type": "number"}}}
        started = time.monotonic()
        # Nested comprehensions: many short Python-level steps, each a point at
        # which the guard can interrupt. (A single huge C-level call such as
        # $range(10**9) cannot be preempted until it returns.)
        with pytest.raises(RuleEvaluationError, match="timeout"):
            expression_adapter.evaluate_with_timeout(
                "$sum([$sum([x * y for y in $range(n)]) for x in $range(n)])", {"n": 5000}, schema
            )
        assert time.monotonic() - started < 1.5
        # The guard thread was interrupted, not abandoned.
        for thread in guard_threads():
            thread.join(timeout=2)
        assert not guard_threads()

    def test_late_result_from_uninterruptible_call_is_not_success(
        self, expression_adapter, settings
    ):
        """A backtracking regex runs in C and holds the GIL; its late result must still fail."""
        settings.RULES_EVALUATION_TIMEOUT_SECONDS = 0.05
        schema = {"type": "object", "properties": {"s": {"type": "string"}}}
        with pytest.raises(RuleEvaluationError, match="timeout"):
            expression_adapter.evaluate_with_timeout("s =~ '(a+)+$'", {"s": "a" * 24 + "b"}, schema)

    def test_library_errors_never_escape_evaluate_with_timeout(self, expression_adapter):
        with pytest.raises(RuleDefinitionError):
            expression_adapter.evaluate_with_timeout("case_value >", {}, COURT_FEE_INPUT)


class TestNormalize:
    def test_integral_decimal_becomes_int(self):
        assert normalize(Decimal("500")) == 500
        assert type(normalize(Decimal("500.00"))) is int

    def test_fractional_decimal_becomes_float(self):
        assert normalize(Decimal("2.5")) == 2.5
        assert type(normalize(Decimal("2.5"))) is float

    def test_nested_values_are_normalized(self, expression_adapter):
        result = expression_adapter.evaluate(
            '{"fee": case_value / 4, "history": [case_value, {"at": filed_at}]}',
            {"case_value": 10, "filed_at": "2024-06-01T10:00:00+05:30"},
            FILING_INPUT,
        )
        assert result == {
            "fee": 2.5,
            "history": [10, {"at": "2024-06-01T10:00:00+05:30"}],
        }
        assert type(result) is dict
        assert type(result["history"]) is list

    @pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), {1: "x"}, {1, 2}])
    def test_non_json_output_is_rejected(self, value):
        with pytest.raises(RuleEvaluationError):
            normalize(value)


class TestGoRulesAdapter:
    def test_validate_accepts_decision_table(self, gorules_adapter):
        gorules_adapter.validate(ELIGIBILITY_GRAPH)

    @pytest.mark.parametrize(
        ("document", "message"),
        [
            ("{not json", "not valid JSON"),
            ("[]", "must be a JSON object"),
            ('{"nodes": []}', '"nodes" and "edges"'),
            (jdm([INPUT_NODE, {"type": "expressionNode"}], []), '"id" and "type"'),
            (jdm([OUTPUT_NODE], []), "ZEN refused"),
            (linear_graph(expression_node({"fee": "case_value +* 2"})), "invalid expression"),
        ],
    )
    def test_malformed_documents_are_definition_errors(self, gorules_adapter, document, message):
        with pytest.raises(RuleDefinitionError, match=message):
            gorules_adapter.validate(document)

    def test_cross_graph_reference_is_rejected(self, gorules_adapter):
        graph = linear_graph(
            {"id": "d", "type": "decisionNode", "name": "Other", "content": {"key": "other.json"}}
        )
        with pytest.raises(RuleDefinitionError, match="loader"):
            gorules_adapter.validate(graph)

    def test_function_node_is_rejected(self, gorules_adapter):
        graph = linear_graph(
            {"id": "f", "type": "functionNode", "name": "JS", "content": {"source": ""}}
        )
        with pytest.raises(RuleDefinitionError, match="functionNode"):
            gorules_adapter.validate(graph)

    def test_zen_runtime_error_is_translated(self, gorules_adapter):
        graph = linear_graph(expression_node({"filed": "date(filed_at)"}))
        with pytest.raises(RuleEvaluationError, match="Failed to evaluate") as exc_info:
            gorules_adapter.evaluate(graph, {"filed_at": "garbage"})
        assert isinstance(exc_info.value.__cause__, RuntimeError)

    def test_referenced_inputs_from_table_nodes(self, gorules_adapter):
        assert gorules_adapter.referenced_inputs(ELIGIBILITY_GRAPH) == {"case_value", "case_type"}

    def test_referenced_inputs_from_cells_and_expressions(self, gorules_adapter):
        table = table_node()
        table["content"]["rules"][0]["value"] = "> threshold"
        table["content"]["rules"][0]["eligible"] = "priority or urgent.flag"
        expr = expression_node({"label": "upper(case_type) + suffix"}, node_id="pre")
        graph = linear_graph(expr, table)
        assert gorules_adapter.referenced_inputs(graph) == {
            "case_value",
            "case_type",
            "threshold",
            "priority",
            "urgent",
            "suffix",
        }

    def test_upstream_outputs_are_not_inputs(self, gorules_adapter):
        graph = linear_graph(
            expression_node({"fee": "case_value * 0.01"}, node_id="a"),
            expression_node({"total": "fee + surcharge"}, node_id="b"),
        )
        assert gorules_adapter.referenced_inputs(graph) == {"case_value", "surcharge"}

    def test_switch_conditions_are_read(self, gorules_adapter):
        switch = {
            "id": "s",
            "type": "switchNode",
            "name": "Route",
            "content": {"statements": [{"id": "s1", "condition": 'case_type == "civil"'}]},
        }
        assert gorules_adapter.referenced_inputs(linear_graph(switch)) == {"case_type"}

    @pytest.mark.parametrize(
        "node",
        [
            expression_node({"x": "$root.case_value"}),
            {
                **expression_node({"x": "amount"}),
                "content": {"inputField": "case", "expressions": []},
            },
            expression_node({"x": "'unterminated"}),
        ],
    )
    def test_undecidable_input_set_raises(self, gorules_adapter, node):
        with pytest.raises(RuleDefinitionError, match="Cannot determine"):
            gorules_adapter.referenced_inputs(linear_graph(node))

    def test_result_has_no_trace_or_performance(self, gorules_adapter):
        result = gorules_adapter.evaluate(
            ELIGIBILITY_GRAPH, {"case_value": 150000, "case_type": "civil"}
        )
        assert result == {"eligible": True}

    def test_tracing_is_off_for_evaluation(self, gorules_adapter, monkeypatch):
        seen = []
        original = gorules_module._evaluate_async

        async def spy(decision, payload, options):
            seen.append(options)
            return await original(decision, payload, options)

        monkeypatch.setattr(gorules_module, "_evaluate_async", spy)
        gorules_adapter.evaluate(ELIGIBILITY_GRAPH, {"case_value": 1, "case_type": "civil"})
        assert seen == [{"trace": False}]

    def test_trace_is_available_on_request(self, gorules_adapter):
        trace = gorules_adapter.trace(ELIGIBILITY_GRAPH, {"case_value": 1, "case_type": "civil"})
        assert "table" in trace

    def test_evaluate_with_timeout_does_not_mutate_payload(self, gorules_adapter):
        payload = {"case_value": 150000, "case_type": "civil"}
        snapshot = copy.deepcopy(payload)
        gorules_adapter.evaluate_with_timeout(ELIGIBILITY_GRAPH, payload, COURT_FEE_INPUT)
        assert payload == snapshot

    def test_timeout_releases_caller_during_long_zen_call(self, gorules_adapter, settings):
        """The Rust call cannot be interrupted, but the caller is released on time (#11.5)."""
        settings.RULES_EVALUATION_TIMEOUT_SECONDS = 0.05
        graph = linear_graph(expression_node({"s": "sum(map([0..6000], sum(map([0..6000], #))))"}))
        started = time.monotonic()
        with pytest.raises(RuleEvaluationError, match="timeout"):
            gorules_adapter.evaluate_with_timeout(graph, {}, {"type": "object"})
        assert time.monotonic() - started < 0.4

    def test_graph_with_edges_to_missing_keys_is_rejected(self, gorules_adapter):
        graph = jdm([INPUT_NODE, OUTPUT_NODE], [{"id": "e", "sourceId": "in"}])
        with pytest.raises(RuleDefinitionError, match="sourceId"):
            gorules_adapter.validate(graph)

    def test_output_path_scopes_produced_keys(self, gorules_adapter):
        first = expression_node({"fee": "case_value"}, node_id="a")
        first["content"]["outputPath"] = "calc"
        graph = jdm(
            [INPUT_NODE, first, expression_node({"x": "calc.fee + fee"}, node_id="b"), OUTPUT_NODE],
            [edge("in", "a"), edge("a", "b"), edge("b", "out")],
        )
        assert gorules_adapter.referenced_inputs(graph) == {"case_value", "fee"}
