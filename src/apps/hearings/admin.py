"""Hearings admin configuration (spec 0023 #11.10)."""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin

from .models import CourtCalendarEntry, Hearing, HearingAttendance, HearingPurpose


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


class HearingAttendanceInline(admin.TabularInline):
    """The hearing's marks, read-only: attendance is order data (#6.5)."""

    model = HearingAttendance
    fields = ("attendee_type", "participant_id", "mark", "appearance_mode")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        """Marks are written only by the courtroom service."""
        return False


@admin.register(Hearing)
class HearingAdmin(SimpleHistoryAdmin):
    """Read-only: every change goes through the services (spec 0023 #11.10).

    Admin never moves, starts or cancels a hearing, so the court lock, the
    date-change log, signals and notifications cannot be skipped.
    """

    list_display = (
        "hearing_date",
        "sequence",
        "case",
        "court",
        "purpose",
        "status",
        "mode",
        "reschedule_count",
    )
    list_filter = ("status", "mode", "court", "purpose")
    search_fields = (
        "=id",
        "case__case_number",
        "case__filing_number",
        "=source_order_id",
        "=order_id",
    )
    date_hierarchy = "hearing_date"
    ordering = ("-hearing_date", "court", "status_order", "sequence")
    list_select_related = ("case", "court", "purpose")
    inlines = (HearingAttendanceInline,)

    def get_readonly_fields(self, request, obj=None):
        """Show every field read-only."""
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        """Hearings are created only by the services."""
        return False

    def has_change_permission(self, request, obj=None):
        """Hearings are never edited by hand."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Hearings are never deleted; every end is a status."""
        return False
