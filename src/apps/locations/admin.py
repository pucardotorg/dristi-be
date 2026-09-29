"""Locations admin configuration."""

from django.contrib import admin, messages
from django.db.models import ProtectedError

from apps.core.mixins import AuditUserAdminMixin

from .models import Location


@admin.register(Location)
class LocationAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for locations."""

    list_display = (
        "code",
        "name",
        "short_name",
        "location_type",
        "parent",
        "is_active",
    )
    list_filter = ("location_type", "is_active")
    search_fields = ("code", "name", "short_name")
    readonly_fields = ("id", "created_at", "updated_at")
    list_select_related = ("parent",)
    ordering = ("code",)

    def delete_model(self, request, obj):
        """Delete a single location, reporting protected children clearly."""
        try:
            super().delete_model(request, obj)
        except ProtectedError:
            self.message_user(
                request,
                f"Cannot delete {obj}: it still has child locations. "
                "Reassign or delete the children first.",
                level=messages.ERROR,
            )

    def delete_queryset(self, request, queryset):
        """Delete selected locations, reporting protected children clearly."""
        try:
            super().delete_queryset(request, queryset)
        except ProtectedError:
            self.message_user(
                request,
                "Cannot delete the selected locations: at least one still has "
                "child locations. Reassign or delete the children first.",
                level=messages.ERROR,
            )
