"""Tests for BusinessRuleService (spec 0019 #5-#7).

Resolution, schema validation and error mapping run against a fake in-memory
engine so they stay fast and library-independent. The end-to-end classes at
the bottom use the real rule-engine and zen-engine libraries, unmocked.
"""

import copy
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.models import BusinessRule
from apps.core.rules import engines
from apps.core.rules.engines import get_engine
from apps.core.rules.engines.base import RuleEngine
from apps.core.rules.exceptions import (
    EngineNotAvailable,
    RuleError,
    RuleEvaluationError,
    RuleInputError,
    RuleNotFound,
    RuleOutputError,
)
from apps.core.rules.services import BusinessRuleService

from .rules_samples import (
    COURT_FEE_INPUT,
    ELIGIBILITY_GRAPH,
    make_gorules_rule,
    make_rule,
)

User = get_user_model()

CIVIL_HIGH_VALUE = {"case_value": 150000, "case_type": "civil"}


class FakeEngine(RuleEngine):
    """In-memory engine: returns ``result`` (or calls it with the payload)."""

    engine = BusinessRule.RuleEngineType.RULE_ENGINE

    def __init__(self, result=None):
        super().__init__()
        self.result = result
        self.calls = []

    def validate(self, rule_expression, rule_input_schema):
        pass

    def referenced_inputs(self, rule_expression, rule_input_schema):
        return set()

    def evaluate(self, rule_expression, payload, rule_input_schema, *, cache_key=None):
        self.calls.append(payload)
        return self.result(payload) if callable(self.result) else self.result


@pytest.fixture
def fake_engine(monkeypatch):
    engine = FakeEngine(result={"fee": 500, "currency": "INR"})
    monkeypatch.setitem(engines._REGISTRY, BusinessRule.RuleEngineType.RULE_ENGINE, engine)
    return engine


@pytest.mark.django_db
class TestResolution:
    def test_evaluate_returns_envelope(self, fake_engine):
        make_rule()
        assert BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE) == {
            "code": "COURT_FEE_CALCULATION",
            "engine": "rule_engine",
            "result": {"fee": 500, "currency": "INR"},
        }

    def test_unknown_code_raises_rule_not_found(self, fake_engine):
        with pytest.raises(RuleNotFound):
            BusinessRuleService.evaluate("NO_SUCH_RULE", CIVIL_HIGH_VALUE)

    def test_inactive_rule_raises_rule_not_found(self, fake_engine):
        make_rule(is_active=False)
        with pytest.raises(RuleNotFound):
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)
        assert fake_engine.calls == []

    def test_get_rule_returns_active_rule(self, fake_engine):
        rule = make_rule()
        assert BusinessRuleService.get_rule("COURT_FEE_CALCULATION") == rule

    def test_engine_not_available(self, fake_engine, monkeypatch):
        make_rule()
        monkeypatch.delitem(engines._REGISTRY, BusinessRule.RuleEngineType.RULE_ENGINE)
        with pytest.raises(EngineNotAvailable):
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)

    def test_all_errors_share_a_base(self):
        for exc in (
            RuleNotFound,
            EngineNotAvailable,
            RuleInputError,
            RuleOutputError,
            RuleEvaluationError,
        ):
            assert issubclass(exc, RuleError)


@pytest.mark.django_db
class TestInputValidation:
    @pytest.mark.parametrize(
        ("payload", "path"),
        [
            ({"case_value": 1}, "$: 'case_type' is a required property"),
            (
                {"case_value": "lots", "case_type": "civil"},
                "$.case_value: 'lots' is not of type 'number'",
            ),
            (
                {**CIVIL_HIGH_VALUE, "court": "HC"},
                "$: Additional properties are not allowed ('court'",
            ),
        ],
        ids=["missing-required", "wrong-type", "undeclared-extra"],
    )
    def test_invalid_payload_raises_input_error_naming_the_path(self, fake_engine, payload, path):
        make_rule()
        with pytest.raises(RuleInputError) as exc_info:
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", payload)
        assert path in str(exc_info.value)

    def test_input_is_validated_before_the_engine_runs(self, fake_engine):
        make_rule()
        with pytest.raises(RuleInputError):
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", {"case_value": "lots"})
        assert fake_engine.calls == []

    def test_model_instance_in_payload_is_rejected(self, fake_engine):
        user = User.objects.create_user(mobile_number="+919000000099", name="u", password="x")
        # An untyped property: JSON Schema alone would accept any object here.
        make_rule(rule_input_schema={"type": "object", "properties": {"party": {}}})
        with pytest.raises(
            RuleInputError, match=r"\$\.party: value of type User is not plain JSON"
        ):
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", {"party": user})
        assert fake_engine.calls == []

    def test_non_iso_date_time_is_an_input_error(self, fake_engine):
        make_rule(
            rule_input_schema={
                "type": "object",
                "properties": {"filed_at": {"type": "string", "format": "date-time"}},
            }
        )
        with pytest.raises(RuleInputError, match=r"\$\.filed_at: 'garbage' is not a 'date-time'"):
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", {"filed_at": "garbage"})
        assert fake_engine.calls == []

    def test_engine_receives_a_copy_of_the_payload(self, fake_engine):
        make_rule()
        payload = copy.deepcopy(CIVIL_HIGH_VALUE)
        BusinessRuleService.evaluate("COURT_FEE_CALCULATION", payload)
        assert fake_engine.calls == [payload]
        assert fake_engine.calls[0] is not payload


@pytest.mark.django_db
class TestOutputValidation:
    def test_wrong_shape_raises_output_error_instead_of_returning(self, fake_engine):
        fake_engine.result = {"amount": 500}
        make_rule()
        returned = None
        with pytest.raises(RuleOutputError, match=r"\$: 'fee' is a required property"):
            returned = BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)
        assert returned is None

    def test_wrong_type_names_the_path(self, fake_engine):
        fake_engine.result = {"fee": "500"}
        make_rule()
        with pytest.raises(RuleOutputError, match=r"\$\.fee: '500' is not of type 'number'"):
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)

    def test_non_iso_date_time_output_is_an_output_error(self, fake_engine):
        fake_engine.result = {"deadline": "next week"}
        make_rule(
            rule_output_schema={
                "type": "object",
                "properties": {"deadline": {"type": "string", "format": "date-time"}},
            }
        )
        with pytest.raises(
            RuleOutputError, match=r"\$\.deadline: 'next week' is not a 'date-time'"
        ):
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)

    def test_engine_exception_becomes_evaluation_error(self, fake_engine):
        def explode(payload):
            raise ValueError("boom")

        fake_engine.result = explode
        make_rule()
        with pytest.raises(RuleEvaluationError, match="boom"):
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)


@pytest.mark.django_db
class TestDryRun:
    def test_dry_run_evaluates_unsaved_and_inactive_rules(self, fake_engine):
        rule = BusinessRule(
            code="DRAFT",
            name="Draft",
            engine=BusinessRule.RuleEngineType.RULE_ENGINE,
            rule_expression="anything",
            rule_input_schema=COURT_FEE_INPUT,
            rule_output_schema={"type": "object"},
            is_active=False,
        )
        assert BusinessRuleService.dry_run(rule, CIVIL_HIGH_VALUE)["result"] == {
            "fee": 500,
            "currency": "INR",
        }

    def test_dry_run_shares_input_validation(self, fake_engine):
        rule = make_rule(is_active=False)
        with pytest.raises(RuleInputError):
            BusinessRuleService.dry_run(rule, {"case_value": 1})
        assert fake_engine.calls == []


@pytest.mark.django_db
class TestEndToEndRuleEngine:
    """Saved and evaluated through the real rule-engine library."""

    def test_court_fee_rule(self):
        make_rule()
        assert BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE) == {
            "code": "COURT_FEE_CALCULATION",
            "engine": "rule_engine",
            "result": {"fee": 500, "currency": "INR"},
        }
        low = BusinessRuleService.evaluate(
            "COURT_FEE_CALCULATION", {"case_value": 5000, "case_type": "criminal"}
        )
        assert low["result"] == {"fee": 100, "currency": "INR"}

    def test_numeric_rule_returns_its_number_not_true(self):
        make_rule(
            rule_expression="case_value > 100000 ? 500 : 100",
            rule_output_schema={"type": "number"},
        )
        result = BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)["result"]
        assert result == 500
        assert type(result) is int

    def test_decimal_result_validates_as_number(self):
        make_rule(rule_expression="case_value * 0.015", rule_output_schema={"type": "number"})
        result = BusinessRuleService.evaluate(
            "COURT_FEE_CALCULATION", {"case_value": 1001, "case_type": "civil"}
        )["result"]
        assert result == 15.015
        assert type(result) is float

    def test_datetime_result_validates_as_date_time_string(self):
        schema = {
            "type": "object",
            "properties": {"filed_at": {"type": "string", "format": "date-time"}},
            "required": ["filed_at"],
        }
        make_rule(
            rule_expression='{"deadline": filed_at + t"P30D"}',
            rule_input_schema=schema,
            rule_output_schema={
                "type": "object",
                "properties": {"deadline": {"type": "string", "format": "date-time"}},
                "required": ["deadline"],
            },
        )
        result = BusinessRuleService.evaluate(
            "COURT_FEE_CALCULATION", {"filed_at": "2024-01-01T00:00:00+00:00"}
        )["result"]
        assert result == {"deadline": "2024-01-31T00:00:00+00:00"}

    def test_wrong_shape_from_real_expression_is_output_error(self):
        make_rule(
            rule_expression='{"amount": 500}',
            rule_output_schema={"type": "object", "required": ["fee"]},
        )
        with pytest.raises(RuleOutputError):
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)


@pytest.mark.django_db
class TestEndToEndGoRules:
    """Saved and evaluated through the real zen-engine library."""

    def test_eligibility_decision_table(self):
        make_gorules_rule()
        assert BusinessRuleService.evaluate("SUMMONS_GENERATION_ELIGIBILITY", CIVIL_HIGH_VALUE) == {
            "code": "SUMMONS_GENERATION_ELIGIBILITY",
            "engine": "gorules",
            "result": {"eligible": True},
        }
        assert BusinessRuleService.evaluate(
            "SUMMONS_GENERATION_ELIGIBILITY", {"case_value": 150000, "case_type": "criminal"}
        )["result"] == {"eligible": False}

    def test_input_validation_applies_to_gorules(self):
        make_gorules_rule()
        with pytest.raises(RuleInputError):
            BusinessRuleService.evaluate("SUMMONS_GENERATION_ELIGIBILITY", {"case_value": 1})


@pytest.mark.django_db
class TestCompiledArtefactCache:
    def test_compiled_rule_is_reused_between_evaluations(self, monkeypatch):
        make_rule()
        adapter = get_engine(BusinessRule.RuleEngineType.RULE_ENGINE)
        compiles = []
        original = adapter._compile

        def counting(*args, **kwargs):
            compiles.append(args)
            return original(*args, **kwargs)

        monkeypatch.setattr(adapter, "_compile", counting)
        BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)
        BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)
        assert len(compiles) == 1

    def test_editing_the_expression_changes_the_next_evaluation(self):
        rule = make_rule()
        assert (
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)["result"]["fee"]
            == 500
        )

        rule.rule_expression = '{"fee": 750}'
        rule.save()
        assert (
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)["result"]["fee"]
            == 750
        )

    def test_cache_key_is_updated_at_not_the_expression(self):
        rule = make_rule()
        BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)

        # A write that bypasses save() leaves updated_at alone, so the
        # memoized compilation for (id, updated_at) is still served.
        BusinessRule.objects.filter(pk=rule.pk).update(rule_expression='{"fee": 750}')
        assert (
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)["result"]["fee"]
            == 500
        )

        BusinessRule.objects.filter(pk=rule.pk).update(
            updated_at=timezone.now() + timedelta(seconds=1)
        )
        assert (
            BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)["result"]["fee"]
            == 750
        )

    def test_gorules_graph_edit_changes_the_next_evaluation(self):
        rule = make_gorules_rule()
        assert BusinessRuleService.evaluate("SUMMONS_GENERATION_ELIGIBILITY", CIVIL_HIGH_VALUE)[
            "result"
        ] == {"eligible": True}
        rule.rule_expression = ELIGIBILITY_GRAPH.replace("> 100000", "> 200000")
        rule.save()
        assert BusinessRuleService.evaluate("SUMMONS_GENERATION_ELIGIBILITY", CIVIL_HIGH_VALUE)[
            "result"
        ] == {"eligible": False}

    def test_results_are_not_cached(self):
        make_rule()
        high = BusinessRuleService.evaluate("COURT_FEE_CALCULATION", CIVIL_HIGH_VALUE)
        low = BusinessRuleService.evaluate(
            "COURT_FEE_CALCULATION", {"case_value": 1, "case_type": "civil"}
        )
        assert high["result"] != low["result"]
