"""Orders admin (spec 0039 #12.8).

The catalogue and the order types are editable; saving checks a field schema is valid
and that an item with a workflow has a handler. Orders, items, Roznamas and runs are
read only: admin never edits, signs or triggers an order. A failed workflow step is
retried with the *Retry failed steps* action, which calls the service.
"""

from django import forms
from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin

from apps.core.mixins import AuditUserAdminMixin

from . import handlers
from .models import (
    Order,
    OrderItem,
    OrderItemCombinationRule,
    OrderItemType,
    OrderRoznama,
    OrderType,
    OrderWorkflowRun,
)
from .services import triggering


class OrderItemTypeForm(forms.ModelForm):
    """Checks a workflow item has a handler to run it (#12.8)."""

    class Meta:
        model = OrderItemType
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("has_workflow") and cleaned.get("is_active", True):
            if handlers.get(cleaned.get("code", "")) is None:
                raise forms.ValidationError(
                    "This item has a workflow but no handler is registered for its code."
                )
        return cleaned


@admin.register(OrderType)
class OrderTypeAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """Which types a state offers and what each changes; retire with ``is_active``."""

    list_display = ("state_code", "code", "label", "number_series", "is_active")
    list_filter = ("state_code", "is_active")
    search_fields = ("code", "label")
    readonly_fields = ("id", "created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderItemType)
class OrderItemTypeAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """The order item catalogue; retire an item with ``is_active``, never delete it."""

    form = OrderItemTypeForm
    list_display = (
        "code",
        "label",
        "category",
        "availability",
        "trigger_phase",
        "has_workflow",
        "is_active",
    )
    list_filter = ("category", "availability", "trigger_phase", "has_workflow", "is_active")
    search_fields = ("code", "label")
    filter_horizontal = ("suggested_for_purposes",)
    readonly_fields = ("id", "created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderItemCombinationRule)
class OrderItemCombinationRuleAdmin(AuditUserAdminMixin, SimpleHistoryAdmin):
    """The catalogue's combination restrictions (``ITM-07``)."""

    list_display = ("code", "kind", "message", "is_active")
    filter_horizontal = ("item_types",)
    readonly_fields = ("id", "created_at", "updated_at")


class ReadOnlyAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Read only: nothing here is written by hand."""

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    fields = ("position", "item_type", "target_id", "values", "added_by_source", "confirmed")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class RunInline(admin.TabularInline):
    model = OrderWorkflowRun
    fields = ("sequence", "step", "order_item", "status", "attempts", "error_code", "result")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(ReadOnlyAdmin):
    list_display = (
        "title",
        "case",
        "status",
        "data_complete",
        "number",
        "order_date",
        "created_at",
    )
    list_filter = ("status", "data_complete", "order_type")
    search_fields = ("title", "number")
    inlines = (OrderItemInline, RunInline)
    actions = ("retry_failed_steps",)

    @admin.action(description="Retry failed steps")
    def retry_failed_steps(self, request, queryset):
        retried = sum(triggering.retry_failed(order.pk) for order in queryset)
        self.message_user(request, f"{retried} step(s) queued for retry.", messages.SUCCESS)


@admin.register(OrderRoznama)
class OrderRoznamaAdmin(ReadOnlyAdmin):
    list_display = ("order", "status", "number", "signed_at")


@admin.register(OrderWorkflowRun)
class OrderWorkflowRunAdmin(ReadOnlyAdmin):
    list_display = ("order", "sequence", "step", "status", "attempts", "error_code")
    list_filter = ("status", "step")
    actions = ("retry",)

    @admin.action(description="Retry failed steps")
    def retry(self, request, queryset):
        retried = sum(
            triggering.retry_failed(order_id)
            for order_id in set(queryset.values_list("order_id", flat=True))
        )
        self.message_user(request, f"{retried} step(s) queued for retry.", messages.SUCCESS)
