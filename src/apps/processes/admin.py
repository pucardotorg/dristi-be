"""Processes admin (spec 0028 #12.7).

Masters are edited here. A process type or channel is never added here: a new
code needs a decision on who may act on it (#2.4), so it comes by seed and
migration. Rounds, processes and events are read only: admin never takes a
step on a process.
"""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin

from .models import (
    Channel,
    NonDeliveryReason,
    Process,
    ProcessEvent,
    ProcessRound,
    ProcessType,
    ProcessTypeChannel,
)


class MasterAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    list_filter = ("is_active",)

    def has_delete_permission(self, request, obj=None):
        return False


class CodedMasterAdmin(MasterAdmin):
    """A master whose codes other code and roles name: edited, never added."""

    search_fields = ("code", "label")

    def has_add_permission(self, request):
        return False

    def get_readonly_fields(self, request, obj=None):
        return ("code", *super().get_readonly_fields(request, obj))


@admin.register(ProcessType)
class ProcessTypeAdmin(CodedMasterAdmin):
    list_display = ("code", "label", "order_item_code", "is_active")
    readonly_fields = ("allowed_recipient_types",)


@admin.register(Channel)
class ChannelAdmin(CodedMasterAdmin):
    list_display = ("code", "label", "send_mode", "status_mode", "is_available", "is_active")
    list_filter = ("is_available", "is_active")


@admin.register(ProcessTypeChannel)
class ProcessTypeChannelAdmin(MasterAdmin):
    list_display = ("process_type", "channel", "preselected", "is_active")
    list_filter = ("process_type", "channel", "is_active")


@admin.register(NonDeliveryReason)
class NonDeliveryReasonAdmin(MasterAdmin):
    list_display = ("state_code", "code", "label", "sequence", "is_active")
    list_filter = ("state_code", "is_active")
    search_fields = ("code", "label")


class ReadOnlyAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EventInline(admin.TabularInline):
    model = ProcessEvent
    fields = ("at", "from_status", "to_status", "source", "actor", "data")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Process)
class ProcessAdmin(ReadOnlyAdmin):
    list_display = ("process_type", "recipient_name", "channel", "status", "status_at")
    list_filter = ("status", "process_type", "channel")
    search_fields = ("recipient_name",)
    inlines = (EventInline,)


@admin.register(ProcessRound)
class ProcessRoundAdmin(ReadOnlyAdmin):
    list_display = ("order_id", "case", "hearing_date", "created_at")
