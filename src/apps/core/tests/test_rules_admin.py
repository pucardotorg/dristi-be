"""Tests for BusinessRuleAdmin and its save-time validation form (spec 0019 #9)."""

import json

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.urls import reverse
from simple_history.admin import SimpleHistoryAdmin

from apps.core.admin import BusinessRuleAdmin
from apps.core.mixins import AuditUserAdminMixin
from apps.core.models import BusinessRule
from apps.core.rules.forms import BusinessRuleAdminForm, json_equal
from apps.core.rules.services import BusinessRuleService

from .rules_samples import (
    COURT_FEE_EXPRESSION,
    COURT_FEE_INPUT,
    COURT_FEE_OUTPUT,
    ELIGIBILITY_GRAPH,
    ELIGIBILITY_OUTPUT,
    make_rule,
)

User = get_user_model()

SAMPLE = {"case_value": 150000, "case_type": "civil"}


def form_data(**overrides):
    data = {
        "code": "COURT_FEE_CALCULATION",
        "name": "Court fee calculation",
        "description": "",
        "engine": "rule_engine",
        "rule_expression": COURT_FEE_EXPRESSION,
        "rule_input_schema": json.dumps(COURT_FEE_INPUT),
        "rule_output_schema": json.dumps(COURT_FEE_OUTPUT),
        "is_active": "on",
        "test_input": json.dumps(SAMPLE),
        "expected_result": "",
    }
    data.update(overrides)
    return data


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(
        mobile_number="+919000000001", name="admin", email="admin@example.com", password="x"
    )


@pytest.fixture
def admin_client(client, superuser):
    client.force_login(superuser)
    return client


class TestRegistration:
    def test_registered_with_history_and_audit_mixin(self):
        model_admin = admin.site._registry[BusinessRule]
        assert isinstance(model_admin, BusinessRuleAdmin)
        assert isinstance(model_admin, SimpleHistoryAdmin)
        assert isinstance(model_admin, AuditUserAdminMixin)

    def test_list_configuration(self):
        model_admin = admin.site._registry[BusinessRule]
        assert model_admin.list_display == ("code", "name", "engine", "is_active", "updated_at")
        assert model_admin.list_filter == ("engine", "is_active")
        assert model_admin.search_fields == ("code", "name", "description")

    @pytest.mark.django_db
    def test_audit_fields_are_readonly(self, rf, superuser):
        request = rf.get("/")
        request.user = superuser
        readonly = admin.site._registry[BusinessRule].get_readonly_fields(request)
        assert {"created_by", "updated_by"} <= set(readonly)

    def test_rule_fields_are_editable(self):
        assert set(BusinessRuleAdminForm.base_fields) >= {
            "code",
            "name",
            "description",
            "engine",
            "rule_expression",
            "rule_input_schema",
            "rule_output_schema",
            "is_active",
        }

    def test_sample_fields_are_not_persisted(self):
        model_fields = {field.name for field in BusinessRule._meta.get_fields()}
        assert not model_fields & {"test_input", "expected_result"}


@pytest.mark.django_db
class TestForm:
    def errors_for(self, **overrides):
        form = BusinessRuleAdminForm(data=form_data(**overrides))
        assert not form.is_valid()
        return form.errors

    def test_valid_form_holds_dry_run_result(self):
        form = BusinessRuleAdminForm(data=form_data())
        assert form.is_valid(), form.errors
        assert form.dry_run_result["result"] == {"fee": 500, "currency": "INR"}

    def test_step1_invalid_schema(self):
        errors = self.errors_for(rule_input_schema=json.dumps({"type": "nope"}))
        assert "Invalid JSON Schema" in errors["rule_input_schema"][0]

    def test_step2_expression_does_not_compile(self):
        assert (
            "does not compile"
            in self.errors_for(rule_expression="case_value >")["rule_expression"][0]
        )

    def test_step3_undeclared_identifier(self):
        assert (
            "court_level"
            in self.errors_for(rule_expression="court_level > 1")["rule_expression"][0]
        )

    def test_blocked_when_dry_run_fails(self):
        errors = self.errors_for(rule_expression="case_value / 0")
        assert "Dry run failed" in errors["rule_expression"][0]

    def test_blocked_when_dry_run_output_breaks_schema(self):
        errors = self.errors_for(rule_expression='{"amount": 1}')
        assert "Dry run failed" in errors["rule_output_schema"][0]

    def test_blocked_when_test_input_does_not_match_input_schema(self):
        errors = self.errors_for(
            test_input=json.dumps({"case_value": "lots", "case_type": "civil"})
        )
        assert "$.case_value" in errors["test_input"][0]

    def test_blocked_when_expected_result_differs(self):
        errors = self.errors_for(expected_result=json.dumps({"fee": 100, "currency": "INR"}))
        assert "differs from the expected result" in errors["expected_result"][0]

    def test_expected_result_match_allows_save(self):
        form = BusinessRuleAdminForm(
            data=form_data(expected_result=json.dumps({"fee": 500.0, "currency": "INR"}))
        )
        assert form.is_valid(), form.errors

    def test_oversized_expression_is_not_compiled_or_dry_run(self, settings, monkeypatch):
        settings.RULES_MAX_EXPRESSION_BYTES = 20

        def fail(*args, **kwargs):
            raise AssertionError("an oversized expression must not be compiled or evaluated")

        monkeypatch.setattr(BusinessRuleService, "validate_rule", fail)
        monkeypatch.setattr(BusinessRuleService, "dry_run", fail)
        assert self.errors_for()["rule_expression"] == ["Expression is larger than 20 bytes."]

    def test_dry_run_required_by_default(self):
        errors = self.errors_for(test_input="")
        assert "required for the dry run" in errors["test_input"][0]

    def test_dry_run_optional_when_disabled(self, settings):
        settings.RULES_ADMIN_DRY_RUN_REQUIRED = False
        form = BusinessRuleAdminForm(data=form_data(test_input=""))
        assert form.is_valid(), form.errors
        assert form.dry_run_result is None

    def test_steps_1_to_3_still_run_when_dry_run_disabled(self, settings):
        settings.RULES_ADMIN_DRY_RUN_REQUIRED = False
        errors = self.errors_for(test_input="", rule_expression="court_level > 1")
        assert "court_level" in errors["rule_expression"][0]

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"rule_expression": "court_level > 1"}, "rule_expression"),
            ({"rule_expression": "case_value / 0"}, "rule_expression"),
            ({"rule_input_schema": json.dumps({"type": "nope"})}, "rule_input_schema"),
        ],
    )
    def test_each_failure_is_reported_once(self, overrides, field):
        """Model clean() must not re-check fields the form already rejected."""
        assert len(self.errors_for(**overrides)[field]) == 1

    def test_editing_existing_rule(self):
        rule = make_rule()
        form = BusinessRuleAdminForm(instance=rule, data=form_data(rule_expression='{"fee": 900}'))
        assert form.is_valid(), form.errors
        assert form.dry_run_result["result"] == {"fee": 900}


class TestJsonEqual:
    @pytest.mark.parametrize(
        ("left", "right", "equal"),
        [
            (500, 500.0, True),
            (True, 1, False),
            ({"a": [1, {"b": True}]}, {"a": [1, {"b": True}]}, True),
            ({"a": 1}, {"a": 1, "b": 2}, False),
            ([1, 2], [2, 1], False),
            (None, None, True),
            ("1", 1, False),
        ],
    )
    def test_strict_json_equality(self, left, right, equal):
        assert json_equal(left, right) is equal


@pytest.mark.django_db
class TestAdminSave:
    url = staticmethod(lambda: reverse("admin:core_businessrule_add"))

    def test_save_writes_rule_history_and_shows_dry_run_result(self, admin_client, superuser):
        response = admin_client.post(self.url(), form_data(), follow=True)
        assert response.status_code == 200

        rule = BusinessRule.objects.get(code="COURT_FEE_CALCULATION")
        assert rule.created_by == superuser
        assert rule.updated_by == superuser
        assert rule.history.count() == 1
        assert rule.history.get().history_user == superuser

        shown = [str(m) for m in get_messages(response.wsgi_request)]
        assert 'Dry run result: {"fee": 500, "currency": "INR"}' in shown

    def test_failed_dry_run_saves_nothing(self, admin_client):
        response = admin_client.post(self.url(), form_data(rule_expression="case_value / 0"))
        assert response.status_code == 200
        assert "Dry run failed" in response.content.decode()
        assert not BusinessRule.objects.exists()
        assert not BusinessRule.history.exists()

    def test_gorules_save_shows_result_and_trace(self, admin_client):
        response = admin_client.post(
            self.url(),
            form_data(
                code="SUMMONS_GENERATION_ELIGIBILITY",
                engine="gorules",
                rule_expression=ELIGIBILITY_GRAPH,
                rule_output_schema=json.dumps(ELIGIBILITY_OUTPUT),
                expected_result=json.dumps({"eligible": True}),
            ),
            follow=True,
        )
        shown = [str(m) for m in get_messages(response.wsgi_request)]
        assert 'Dry run result: {"eligible": true}' in shown
        assert any(message.startswith("Dry run trace:") for message in shown)
        assert BusinessRule.objects.filter(code="SUMMONS_GENERATION_ELIGIBILITY").exists()
