"""Core admin registration."""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import AdditionalAttribute, ApiVersionChangeLog


@admin.register(AdditionalAttribute)
class AdditionalAttributeAdmin(SimpleHistoryAdmin):
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
class ApiVersionChangeLogAdmin(SimpleHistoryAdmin):
    """Admin configuration for API version change-log entries."""

    list_display = (
        "version",
        "change_log",
        "created_at",
        "updated_at",
    )
    search_fields = ("version", "change_log")
    readonly_fields = ("id", "created_at", "updated_at")
