"""Core admin registration."""

import json

from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin

from .mixins import AuditUserAdminMixin
from .models import AdditionalAttribute, ApiVersionChangeLog, Configuration, BusinessRule
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
