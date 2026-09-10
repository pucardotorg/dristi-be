"""Messaging admin configuration."""

from django.contrib import admin

from .models import MessageLog, MessageTemplate


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "message_key",
        "message_type",
        "priority",
        "max_retries",
        "is_active",
    )
    list_filter = ("message_type", "priority", "is_active")
    search_fields = ("message_key", "subject", "content")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "message_key",
        "message_type",
        "status",
        "attempt_count",
        "max_retries",
        "sent_at",
        "failed_at",
    )
    list_filter = ("message_type", "status")
    search_fields = ("message_key", "recipient", "provider_message_id")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]
