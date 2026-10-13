"""Core admin registration."""

from django.contrib import admin

from .mixins import AuditUserAdminMixin
from .models import AdditionalAttribute, ApiVersionChangeLog, Configuration


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
