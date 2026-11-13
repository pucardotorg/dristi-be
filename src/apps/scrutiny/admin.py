"""Scrutiny admin registration."""

import json

from django import forms
from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin
from apps.core.rules.exceptions import RuleError, RuleNotFound

from .checks import service
from .checks.contracts import ContractError
from .models import ScrutinyFlag, ScrutinyFlagResponse, ScrutinyRound, ScrutinyRuleBinding


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


class ScrutinyFlagInline(admin.TabularInline):
    """The round's flags, read-only; open one to see or edit it."""

    model = ScrutinyFlag
    fk_name = "round"
    fields = ("target_type", "target_ref", "target_label", "status", "note")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        """Flags are added from their own page, where they are validated."""
        return False


@admin.register(ScrutinyRound)
class ScrutinyRoundAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Review rounds; they are opened and decided by the scrutiny services (#4)."""

    list_display = ("case", "stage", "number", "establishment_id", "decision", "decided_at")
    list_filter = ("stage", "decision", "routing_reason")
    search_fields = ("case__filing_number", "case__case_number", "visit_id")
    autocomplete_fields = ("case",)
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = (ScrutinyFlagInline,)
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


class ScrutinyFlagResponseInline(admin.TabularInline):
    """The flag's responses, read-only; open one to see or edit it."""

    model = ScrutinyFlagResponse
    fields = ("kind", "note", "value_after", "document_id", "responded_by", "responded_at")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        """Responses are added from their own page, where they are validated."""
        return False


@admin.register(ScrutinyFlag)
class ScrutinyFlagAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Review flags; they are drafted and moved through their lifecycle by the services (#3.5)."""

    list_display = ("target_label", "target_type", "target_ref", "status", "round", "created_at")
    list_filter = ("status", "target_type", "reason_code", "round__stage")
    search_fields = (
        "target_ref",
        "target_label",
        "note",
        "round__case__filing_number",
        "round__case__case_number",
    )
    autocomplete_fields = ("round", "auto_marked_by", "linked_flag", "carried_from")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = (ScrutinyFlagResponseInline,)
    fieldsets = (
        (None, {"fields": ("round", "status")}),
        (
            "Target",
            {"fields": ("target_type", "target_ref", "target_label", "section_id")},
        ),
        ("For the advocate", {"fields": ("reason_code", "note", "value_at_flag")}),
        ("Links", {"fields": ("auto_marked_by", "linked_flag", "carried_from")}),
        ("Resolution", {"fields": ("resolved_by", "resolved_at")}),
        ("Audit", {"fields": ("id", "created_at", "updated_at", "created_by", "updated_by")}),
    )


@admin.register(ScrutinyFlagResponse)
class ScrutinyFlagResponseAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Review the filer's responses; they are recorded by the services (#5.2)."""

    list_display = ("flag", "kind", "responded_by", "responded_at")
    list_filter = ("kind", "flag__target_type")
    search_fields = ("note", "flag__target_ref", "flag__target_label")
    autocomplete_fields = ("flag",)
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("flag", "kind", "note", "value_after", "document_id")}),
        ("Responded", {"fields": ("responded_by", "responded_at")}),
        ("Audit", {"fields": ("id", "created_at", "updated_at", "created_by", "updated_by")}),
    )
