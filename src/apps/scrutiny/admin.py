"""Scrutiny admin registration."""

import json

from django import forms
from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin
from apps.core.rules.exceptions import RuleError, RuleNotFound

from .checks import service
from .checks.contracts import ContractError
from .models import ScrutinyRound, ScrutinyRuleBinding


class ScrutinyRuleBindingAdminForm(forms.ModelForm):
    """Refuses an active binding whose rule cannot be dry-run on the sample filing (#2.4).

    After a successful ``is_valid()`` on an active binding, ``dry_run_alerts``
    holds the alerts the rule returned for the sample.
    """

    class Meta:
        model = ScrutinyRuleBinding
        fields = ("decision", "organization", "rule_code", "note", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dry_run_alerts = None

    def clean(self):
        cleaned = super().clean()
        rule_code = cleaned.get("rule_code")
        # An inactive binding resolves nowhere, so it may point at a parked rule.
        if not cleaned.get("is_active") or not rule_code or "rule_code" in self.errors:
            return cleaned
        try:
            self.dry_run_alerts = service.dry_run(rule_code)
        except RuleNotFound as exc:
            raise forms.ValidationError({"rule_code": str(exc)}) from exc
        except (RuleError, ContractError) as exc:
            raise forms.ValidationError({"rule_code": f"Dry run failed: {exc}"}) from exc
        return cleaned


@admin.register(ScrutinyRuleBinding)
class ScrutinyRuleBindingAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Bind a checks rule to a jurisdiction; saving an active binding dry-runs its rule."""

    form = ScrutinyRuleBindingAdminForm
    list_display = ("decision", "organization", "rule_code", "is_active", "updated_at")
    list_filter = ("decision", "is_active")
    search_fields = ("rule_code", "organization__code", "organization__name", "note")
    autocomplete_fields = ("organization",)
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("decision", "organization", "rule_code", "note", "is_active")}),
        ("Audit", {"fields": ("id", "created_at", "updated_at", "created_by", "updated_by")}),
    )

    def save_model(self, request, obj, form, change):
        """Save, then show the author what the dry run returned."""
        super().save_model(request, obj, form, change)
        if form.dry_run_alerts is not None:
            codes = json.dumps([alert["code"] for alert in form.dry_run_alerts])
            messages.success(request, f"Dry run on the sample filing raised: {codes}")


@admin.register(ScrutinyRound)
class ScrutinyRoundAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Review rounds; they are opened and decided by the scrutiny services (#4)."""

    list_display = ("case", "stage", "number", "establishment_id", "decision", "decided_at")
    list_filter = ("stage", "decision", "routing_reason")
    search_fields = ("case__filing_number", "case__case_number", "visit_id")
    autocomplete_fields = ("case",)
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("case", "stage", "number", "visit_id", "routing_reason")}),
        ("Court", {"fields": ("establishment_id", "courtroom_id", "registration_type")}),
        ("Start", {"fields": ("started_by", "started_at")}),
        (
            "Decision",
            {
                "fields": (
                    "decision",
                    "decided_by",
                    "decided_at",
                    "open_items_acknowledged",
                    "open_items_at_decision",
                    "comment",
                )
            },
        ),
        ("Audit", {"fields": ("id", "created_at", "updated_at", "created_by", "updated_by")}),
    )
