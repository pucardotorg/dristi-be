"""ScrutinyRuleBinding, its resolution, and the CHECKS rule (spec 0024 #2.4, #10)."""

import copy
import json
import logging

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from apps.core.models import BusinessRule
from apps.core.rules.services import BusinessRuleService
from apps.organizations.models import OrganizationType
from apps.organizations.tests.factories import make_organization
from apps.scrutiny.checks import contracts, service
from apps.scrutiny.checks.resolver import resolve_binding
from apps.scrutiny.enums import Decision
from apps.scrutiny.models import ScrutinyRuleBinding

pytestmark = pytest.mark.django_db

User = get_user_model()

DEFAULT_RULE = "SCRUTINY_CHECKS_DEFAULT"

# A filing every seeded check passes.
CLEAN_FACTS = {
    "case_type": "CHEQUE_BOUNCE",
    "today": "2026-08-03",
    "cheques": [
        {
            "index": 0,
            "cheque_date": "2026-01-05",
            "presented_on": "2026-03-01",
            "valid_until": "2026-04-04",
            "returned_on": "2026-03-05",
            "amount": 5205000,
            "return_reason": "FUNDS_INSUFFICIENT",
        }
    ],
    "notice": {
        "dispatched_on": "2026-03-20",
        "served_on": "2026-03-24",
        "delivered": True,
        "postal_receipt_uploaded": True,
        "delivery_proof_uploaded": True,
    },
    "cause_of_action_on": "2026-04-09",
    "filed_on": "2026-04-20",
    "delay_applicable": False,
    "delay_prayer_present": False,
    "complainant_is_institution": True,
    "complainant_cin_or_pan_present": True,
}


def facts(cheques=(), **changes):
    """CLEAN_FACTS with top-level ``changes``; ``cheques`` updates cheque N from the Nth dict."""
    data = copy.deepcopy(CLEAN_FACTS)
    for key, value in changes.items():
        if isinstance(value, dict):
            data[key].update(value)
        else:
            data[key] = value
    for index, cheque in enumerate(cheques):
        if index >= len(data["cheques"]):
            data["cheques"].append({**CLEAN_FACTS["cheques"][0], "index": index})
        data["cheques"][index].update(cheque)
    return data


@pytest.fixture
def hierarchy():
    """High Court > District Court > establishment, plus an unrelated High Court."""
    high_court = make_organization(code="HC_KL", name="High Court of Kerala")
    district = make_organization(
        code="DC_KLM",
        name="Kollam",
        organization_type=OrganizationType.DISTRICT_COURT,
        parent=high_court,
    )
    establishment = make_organization(
        code="MC_KLM_24X7",
        name="24x7 ON Court",
        parent=district,
        organization_type=OrganizationType.MAGISTRATE_COURT,
    )
    other = make_organization(code="HC_GJ", name="High Court of Gujarat")
    return high_court, district, establishment, other


def bind(organization, rule_code=DEFAULT_RULE, **fields):
    return ScrutinyRuleBinding.objects.create(
        decision=Decision.CHECKS, organization=organization, rule_code=rule_code, **fields
    )


def make_lax_rule(code, result):
    """A rule that 0019 accepts but whose output breaks the CHECKS contract."""
    return BusinessRule.objects.create(
        code=code,
        name=code,
        engine=BusinessRule.RuleEngineType.RULE_ENGINE,
        rule_expression=json.dumps(result),
        rule_input_schema={"type": "object"},
        rule_output_schema={"type": "object"},
    )


def default_binding():
    return ScrutinyRuleBinding.objects.active().get(
        decision=Decision.CHECKS, organization__isnull=True
    )


class TestBindingModel:
    def test_one_active_binding_per_organization(self, hierarchy):
        high_court, *_ = hierarchy
        bind(high_court)
        with pytest.raises(ValidationError):
            bind(high_court)
        bind(high_court, is_active=False)  # inactive rows do not count

    def test_one_active_national_default(self):
        assert default_binding().rule_code == DEFAULT_RULE  # seeded
        with pytest.raises(ValidationError):
            bind(None)
        bind(None, is_active=False)

    def test_rule_code_must_be_a_rule_code(self, hierarchy):
        with pytest.raises(ValidationError) as exc:
            bind(hierarchy[0], rule_code="scrutiny checks")
        assert "rule_code" in exc.value.message_dict


class TestResolution:
    def test_national_default_applies_without_any_other_binding(self, hierarchy):
        assert resolve_binding(Decision.CHECKS, hierarchy[2]) == default_binding()
        assert resolve_binding(Decision.CHECKS, None) == default_binding()

    def test_establishment_beats_high_court_beats_default(self, hierarchy):
        high_court, district, establishment, other = hierarchy
        state = bind(high_court, rule_code="KERALA_CHECKS")
        assert resolve_binding(Decision.CHECKS, establishment) == state
        assert resolve_binding(Decision.CHECKS, district) == state
        assert resolve_binding(Decision.CHECKS, other) == default_binding()

        # The nearest ancestor wins, though get_ancestors() lists the root first.
        nearer = bind(district, rule_code="KOLLAM_DISTRICT_CHECKS")
        assert resolve_binding(Decision.CHECKS, establishment) == nearer

        local = bind(establishment, rule_code="KOLLAM_CHECKS")
        assert resolve_binding(Decision.CHECKS, establishment) == local
        assert resolve_binding(Decision.CHECKS, district) == nearer

    def test_inactive_bindings_are_skipped(self, hierarchy):
        high_court, _, establishment, _ = hierarchy
        bind(high_court, rule_code="KERALA_CHECKS", is_active=False)
        assert resolve_binding(Decision.CHECKS, establishment) == default_binding()

    def test_nothing_resolves_without_a_default(self, hierarchy):
        ScrutinyRuleBinding.objects.update(is_active=False)
        assert resolve_binding(Decision.CHECKS, hierarchy[2]) is None


class TestSeededRule:
    def test_rule_is_valid_and_keeps_the_contract(self):
        rule = BusinessRuleService.get_rule(DEFAULT_RULE)
        BusinessRuleService.validate_rule(rule)
        assert rule.rule_input_schema == contracts.CHECKS_INPUT_SCHEMA
        assert rule.rule_output_schema == contracts.CHECKS_OUTPUT_SCHEMA

    def test_clean_filing_has_no_alerts(self, hierarchy):
        assert service.evaluate_checks(hierarchy[2], facts()) == []

    @pytest.mark.parametrize(
        ("changes", "code", "severity", "field_refs"),
        [
            (
                {"cheques": [{}, {"presented_on": "2026-05-01", "returned_on": "2026-05-02"}]},
                "PRESENTED_AFTER_VALIDITY",
                "WARNING",
                ["CHQ-8[1]"],
            ),
            (
                {"cheques": [{"presented_on": "2026-01-01"}]},
                "PRESENTED_BEFORE_CHEQUE_DATE",
                "WARNING",
                ["CHQ-1[0]", "CHQ-8[0]"],
            ),
            (
                {"notice": {"dispatched_on": "2026-04-05"}},
                "NOTICE_AFTER_30_DAYS",
                "WARNING",
                ["CHQ-9[0]", "LDN-2[0]"],
            ),
            (
                {"delay_applicable": True},
                "DELAY_WITHOUT_PRAYER",
                "WARNING",
                ["JUR-11", "JUR-12"],
            ),
            (
                {"cheques": [{"return_reason": "ACCOUNT_CLOSED"}]},
                "NON_FUNDS_RETURN_REASON",
                "WARNING",
                ["CHQ-9[0]"],
            ),
            (
                {"notice": {"postal_receipt_uploaded": False}},
                "NO_POSTAL_RECEIPT",
                "INFO",
                ["LDN-3[0]"],
            ),
            (
                {"notice": {"delivery_proof_uploaded": False}},
                "NO_DELIVERY_PROOF",
                "INFO",
                ["LDN-6[0]"],
            ),
            (
                {"complainant_cin_or_pan_present": False},
                "INSTITUTION_WITHOUT_CIN_OR_PAN",
                "WARNING",
                ["LIT-18a[0]"],
            ),
        ],
    )
    def test_each_check_fires_alone(self, hierarchy, changes, code, severity, field_refs):
        alerts = service.evaluate_checks(hierarchy[2], facts(**changes))
        assert [(a["code"], a["severity"], a["field_refs"]) for a in alerts] == [
            (code, severity, field_refs)
        ]

    def test_presented_after_validity_names_the_last_valid_day(self, hierarchy):
        alerts = service.evaluate_checks(
            hierarchy[2],
            facts(cheques=[{"presented_on": "2026-05-01", "returned_on": "2026-05-02"}]),
        )
        presented = [a for a in alerts if a["code"] == "PRESENTED_AFTER_VALIDITY"]
        assert presented[0]["message"] == "Presented after validity — valid until 04/04/2026"

    def test_delay_with_a_condonation_prayer_is_not_flagged(self, hierarchy):
        changes = {"delay_applicable": True, "delay_prayer_present": True}
        assert service.evaluate_checks(hierarchy[2], facts(**changes)) == []


class TestDegradation:
    """A failure never blocks the screen: it becomes one CHECKS_UNAVAILABLE alert."""

    def assert_unavailable(self, alerts, caplog, code):
        assert [a["code"] for a in alerts] == ["CHECKS_UNAVAILABLE"]
        records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(records) == 1
        assert f"code={code}" in records[0].getMessage()

    def test_no_binding(self, hierarchy, caplog):
        ScrutinyRuleBinding.objects.update(is_active=False)
        self.assert_unavailable(service.evaluate_checks(hierarchy[2], facts()), caplog, "E09014")

    def test_bound_rule_inactive(self, hierarchy, caplog):
        BusinessRule.objects.filter(code=DEFAULT_RULE).update(is_active=False)
        self.assert_unavailable(service.evaluate_checks(hierarchy[2], facts()), caplog, "E09014")

    def test_bound_rule_missing(self, hierarchy, caplog):
        bind(hierarchy[0], rule_code="NO_SUCH_RULE")
        self.assert_unavailable(service.evaluate_checks(hierarchy[2], facts()), caplog, "E09014")

    def test_facts_breaking_the_contract(self, hierarchy, caplog):
        broken = facts()
        del broken["today"]
        self.assert_unavailable(service.evaluate_checks(hierarchy[2], broken), caplog, "E09015")

    def test_output_is_validated_again_against_the_contract(self, hierarchy, caplog):
        make_lax_rule("LAX_CHECKS", {"alerts": [{"code": "X", "severity": "CRITICAL"}]})
        bind(hierarchy[0], rule_code="LAX_CHECKS")
        self.assert_unavailable(service.evaluate_checks(hierarchy[2], facts()), caplog, "E09015")


@pytest.fixture
def admin_client(client):
    user = User.objects.create_superuser(
        mobile_number="+919000000001", name="admin", email="admin@example.com", password="x"
    )
    client.force_login(user)
    return client


class TestAdmin:
    url = reverse("admin:scrutiny_scrutinyrulebinding_add")

    def post(self, admin_client, organization, rule_code, is_active=True):
        data = {"decision": "CHECKS", "organization": organization.pk, "rule_code": rule_code}
        if is_active:
            data["is_active"] = "on"
        return admin_client.post(self.url, data)

    def test_saves_a_binding_whose_rule_passes_the_dry_run(self, admin_client, hierarchy):
        response = self.post(admin_client, hierarchy[0], DEFAULT_RULE)
        assert response.status_code == 302
        binding = ScrutinyRuleBinding.objects.get(organization=hierarchy[0])
        assert binding.created_by is not None
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        assert any("NO_POSTAL_RECEIPT" in m for m in messages)

    def test_refuses_a_binding_to_a_missing_rule(self, admin_client, hierarchy):
        response = self.post(admin_client, hierarchy[0], "NO_SUCH_RULE")
        assert response.status_code == 200
        assert "rule_code" in response.context["adminform"].form.errors
        assert not ScrutinyRuleBinding.objects.filter(organization=hierarchy[0]).exists()

    def test_refuses_a_rule_that_breaks_the_contract(self, admin_client, hierarchy):
        make_lax_rule("LAX_CHECKS", {"alerts": []})  # no contract input check on its side
        make_lax_rule("BAD_CHECKS", {"warnings": []})
        assert self.post(admin_client, hierarchy[0], "BAD_CHECKS").status_code == 200
        assert self.post(admin_client, hierarchy[0], "LAX_CHECKS").status_code == 302

    def test_inactive_binding_skips_the_dry_run(self, admin_client, hierarchy):
        response = self.post(admin_client, hierarchy[0], "NO_SUCH_RULE", is_active=False)
        assert response.status_code == 302


class TestPolicyReport:
    def test_passes_with_the_seeded_default(self, hierarchy, capsys):
        call_command("scrutiny_check_policies")
        assert "Every organization resolves" in capsys.readouterr().out

    def test_reports_unbound_organizations(self, hierarchy, capsys):
        ScrutinyRuleBinding.objects.update(is_active=False)
        with pytest.raises(CommandError):
            call_command("scrutiny_check_policies")
        out = capsys.readouterr().out
        assert "UNBOUND MC_KLM_24X7" in out
        assert "UNBOUND HC_GJ" in out

    def test_reports_bindings_to_inactive_rules_and_failing_dry_runs(self, hierarchy, capsys):
        bind(hierarchy[0], rule_code="NO_SUCH_RULE")
        make_lax_rule("BAD_CHECKS", {"warnings": []})
        bind(hierarchy[3], rule_code="BAD_CHECKS")
        with pytest.raises(CommandError):
            call_command("scrutiny_check_policies")
        out = capsys.readouterr().out
        assert "INACTIVE_RULE CHECKS @ HC_KL" in out
        assert "DRY_RUN_FAILED CHECKS @ HC_GJ" in out
