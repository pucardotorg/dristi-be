"""Hearings admin configuration (spec 0023 #11.10)."""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin

from .models import CourtCalendarEntry, HearingPurpose


@admin.register(HearingPurpose)
class HearingPurposeAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Editable reference table; retire a purpose by unticking ``is_active``."""

    list_display = ("code", "label", "sequence", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "label")
    ordering = ("sequence", "code")
    readonly_fields = ("id", "created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        """Purposes are retired, never deleted; hearings keep a PROTECT reference."""
        return False


@admin.register(CourtCalendarEntry)
class CourtCalendarEntryAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Holidays, leave and reduced sittings that shape a court's sitting days."""

    list_display = ("date", "court", "entry_type", "reason", "capacity_override", "updated_at")
    list_filter = ("entry_type", "court")
    search_fields = ("reason", "court__name")
    date_hierarchy = "date"
    ordering = ("-date",)
    autocomplete_fields = ("court",)
    readonly_fields = ("id", "created_at", "updated_at")
