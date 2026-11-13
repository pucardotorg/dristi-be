"""Read-only admin for notifications (spec 0031)."""

from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Read-only view over notification metadata for support.

    Notifications are created only through the internal service and change
    read state only through the inbox API, so the admin never adds, edits or
    deletes rows.
    """

    list_display = ("event_type", "recipient", "priority", "read_at", "created_at")
    list_filter = ("priority", "event_type")
    search_fields = ("event_type", "recipient__mobile_number", "recipient__name")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "id",
        "recipient",
        "event_type",
        "title",
        "body",
        "data",
        "priority",
        "read_at",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
    )

    def has_add_permission(self, request):
        """Notifications are created only through the internal service."""
        return False

    def has_change_permission(self, request, obj=None):
        """Notifications are never edited from the admin."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Notifications are never deleted from the admin."""
        return False
