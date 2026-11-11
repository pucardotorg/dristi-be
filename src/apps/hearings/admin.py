"""Hearings admin configuration (spec 0023 #11.10)."""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin

from .models import (
    CourtCalendarEntry,
    Hearing,
    HearingAttendance,
    HearingDateChange,
    HearingPurpose,
)


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


class HearingDateChangeInline(admin.TabularInline):
    """The hearing's moves, read-only: the log is append-only (#2.4)."""

    model = HearingDateChange
    fk_name = "hearing"
    fields = (
        "created_at",
        "from_date",
        "to_date",
        "from_purpose",
        "to_purpose",
        "reason_code",
        "sought_by",
        "source",
    )
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        """Moves are written only by the reschedule services."""
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
    inlines = (HearingDateChangeInline, HearingAttendanceInline)

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


@admin.register(HearingDateChange)
class HearingDateChangeAdmin(admin.ModelAdmin):
    """Read-only log of every move of a hearing that had not been heard (#11.10)."""

    list_display = (
        "created_at",
        "hearing",
        "from_date",
        "to_date",
        "reason_code",
        "sought_by",
        "source",
    )
    list_filter = ("reason_code", "sought_by", "source")
    search_fields = ("hearing__case__case_number", "=hearing__id", "=source_ref")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("hearing__case", "from_purpose", "to_purpose")

    def get_readonly_fields(self, request, obj=None):
        """Show every field read-only."""
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        """Moves are written only by the reschedule services."""
        return False

    def has_change_permission(self, request, obj=None):
        """A logged move is never edited."""
        return False

    def has_delete_permission(self, request, obj=None):
        """A logged move is never deleted."""
        return False
