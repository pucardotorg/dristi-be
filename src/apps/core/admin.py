"""Core admin registration."""

import json

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone
from simple_history.admin import SimpleHistoryAdmin

from .mixins import AuditUserAdminMixin
from .models import (
    AdditionalAttribute,
    ApiVersionChangeLog,
    BusinessRule,
    Configuration,
    Language,
)
from .rules.forms import BusinessRuleAdminForm

# Longest trace shown back to the author before it is truncated.
DRY_RUN_TRACE_DISPLAY_CHARS = 4000


@admin.register(AdditionalAttribute)
class AdditionalAttributeAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for additional attribute metadata."""

    list_display = (
        "name",
        "content_type",
        "data_type",
        "is_nullable",
        "default_value",
    )
    list_filter = ("content_type", "data_type", "is_nullable")
    search_fields = ("name",)


@admin.register(ApiVersionChangeLog)
class ApiVersionChangeLogAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for API version change-log entries."""

    list_display = (
        "version",
        "change_log",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
    )
    search_fields = ("version", "change_log")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Configuration)
class ConfigurationAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for runtime configuration entries."""

    list_display = ("config_set", "config_key", "config_value", "is_active", "updated_at")
    list_filter = ("config_set", "is_active")
    search_fields = ("config_key", "description")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(BusinessRule)
class BusinessRuleAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Authoring surface for business rules; saving requires a passing dry run."""

    form = BusinessRuleAdminForm
    list_display = ("code", "name", "engine", "is_active", "updated_at")
    list_filter = ("engine", "is_active")
    search_fields = ("code", "name", "description")
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("code", "name", "description", "engine", "is_active")}),
        ("Rule", {"fields": ("rule_expression", "rule_input_schema", "rule_output_schema")}),
        (
            "Dry run",
            {
                "fields": ("test_input", "expected_result"),
                "description": "Evaluated on save against the rule as edited. Not stored.",
            },
        ),
        ("Audit", {"fields": ("id", "created_at", "updated_at", "created_by", "updated_by")}),
    )

    def save_model(self, request, obj, form, change):
        """Save, then show the author what the dry run returned."""
        super().save_model(request, obj, form, change)
        envelope = getattr(form, "dry_run_result", None)
        if envelope is None:
            return
        messages.success(request, f"Dry run result: {json.dumps(envelope['result'])}")
        if "trace" in envelope:
            trace = json.dumps(envelope["trace"])
            if len(trace) > DRY_RUN_TRACE_DISPLAY_CHARS:
                trace = trace[:DRY_RUN_TRACE_DISPLAY_CHARS] + "… (truncated)"
            messages.info(request, f"Dry run trace: {trace}")


class LanguageAdminForm(forms.ModelForm):
    """Edits ``supports`` as checkboxes, stored as the JSON list of capabilities."""

    supports = forms.MultipleChoiceField(
        choices=Language.LanguageSupport.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Capabilities this language has. None means content-only.",
    )

    class Meta:
        model = Language
        fields = "__all__"


class LanguageSupportFilter(admin.SimpleListFilter):
    """Filter languages by a capability they declare."""

    title = "supports"
    parameter_name = "supports"

    def lookups(self, request, model_admin):
        return Language.LanguageSupport.choices

    def queryset(self, request, queryset):
        if self.value() in Language.LanguageSupport.values:
            return queryset.filter(supports__contains=[self.value()])
        return queryset


@admin.register(Language)
class LanguageAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Supported languages (spec 0030 section 3).

    The default language cannot be deactivated, un-defaulted or deleted; the
    model rejects the first two with a form error. Switch the default with the
    "Make default" action, which moves the flag in one transaction.
    """

    form = LanguageAdminForm
    list_display = (
        "code",
        "name",
        "native_name",
        "display_supports",
        "is_default",
        "is_active",
        "sort_order",
    )
    list_editable = ("sort_order", "is_active")
    list_filter = ("is_active", LanguageSupportFilter)
    search_fields = ("code", "name", "native_name")
    readonly_fields = ("id", "created_at", "updated_at")
    actions = ("make_default",)
    fieldsets = (
        (None, {"fields": ("code", "name", "native_name", "supports")}),
        ("Availability", {"fields": ("is_default", "is_active", "sort_order")}),
        ("Audit", {"fields": ("id", "created_at", "updated_at", "created_by", "updated_by")}),
    )

    @admin.display(description="Supports")
    def display_supports(self, obj):
        labels = dict(Language.LanguageSupport.choices)
        return ", ".join(labels.get(item, item) for item in obj.supports) or "-"

    def has_delete_permission(self, request, obj=None):
        """Hide delete for the default language, here and in the bulk delete action."""
        if obj is not None and obj.is_default:
            return False
        return super().has_delete_permission(request, obj)

    @admin.action(description="Make the selected language the default", permissions=["change"])
    def make_default(self, request, queryset):
        """Move the default flag to the one selected, active language."""
        if queryset.count() != 1:
            self.message_user(request, "Select exactly one language.", messages.ERROR)
            return
        language = queryset.get()
        if not language.is_active:
            self.message_user(
                request, "Activate the language before making it the default.", messages.ERROR
            )
            return
        audit = {"updated_by": request.user, "updated_at": timezone.now()}
        with transaction.atomic():
            # Clear first: the partial unique index allows only one default at a time.
            Language.objects.filter(is_default=True).exclude(pk=language.pk).update(
                is_default=False, **audit
            )
            Language.objects.filter(pk=language.pk).update(is_default=True, **audit)
        self.message_user(request, f"{language} is now the default language.", messages.SUCCESS)
