"""Payments admin (spec 0017 #9.5, #10).

Everything is read-only: balances and statuses belong to the services, and
successful payments are frozen history. The only writes are operator actions,
each of which goes through ``PaymentService``.
"""

from django.contrib import admin, messages
from simple_history.admin import SimpleHistoryAdmin

from .enums import PaymentStatus
from .exceptions import PaymentNotConfirmable
from .models import Demand, DemandItem, Payment, PaymentDemandItem
from .providers.base import ProviderError, ProviderNotConfigured
from .services import PaymentService


class ReadOnlyAdminMixin:
    """Show every concrete field read-only; no add, change or delete."""

    def get_readonly_fields(self, request, obj=None):
        """Every field."""

        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request, obj=None):
        """Rows are created only by the services."""

        return False

    def has_change_permission(self, request, obj=None):
        """Rows are never edited by hand (actions still run)."""

        return False

    def has_delete_permission(self, request, obj=None):
        """Money history is never deleted."""

        return False


class DemandItemInline(ReadOnlyAdminMixin, admin.TabularInline):
    """The line items of a demand."""

    model = DemandItem
    extra = 0
    fields = (
        "position",
        "charge_type",
        "reference_type",
        "reference_id",
        "description",
        "quantity",
        "unit_amount",
        "amount",
        "paid_amount",
        "due_amount",
        "status",
    )
    ordering = ("position",)


@admin.register(Demand)
class DemandAdmin(ReadOnlyAdminMixin, SimpleHistoryAdmin):
    """Demands and their items."""

    list_display = (
        "demand_number",
        "case_id",
        "reference_type",
        "reference_id",
        "status",
        "total_amount",
        "paid_amount",
        "due_amount",
        "created_at",
    )
    list_filter = ("status", "reference_type", "currency")
    search_fields = ("demand_number", "=id", "=case_id", "reference_id")
    date_hierarchy = "created_at"
    inlines = (DemandItemInline,)


class PaymentDemandItemInline(ReadOnlyAdminMixin, admin.TabularInline):
    """The demand items a payment pays."""

    model = PaymentDemandItem
    extra = 0
    fields = ("demand_item", "amount")


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdminMixin, SimpleHistoryAdmin):
    """Payments, with the operator actions for flagged and unconfirmed ones."""

    list_display = (
        "payment_number",
        "demand",
        "batch_id",
        "amount",
        "status",
        "provider",
        "provider_reference",
        "needs_reconciliation",
        "created_at",
    )
    list_filter = ("status", "provider", "needs_reconciliation", "payment_mode")
    search_fields = (
        "payment_number",
        "=id",
        "=batch_id",
        "provider_payment_id",
        "provider_reference",
        "demand__demand_number",
    )
    date_hierarchy = "created_at"
    list_select_related = ("demand",)
    inlines = (PaymentDemandItemInline,)
    actions = ("recheck_with_provider", "clear_reconciliation", "confirm_without_provider")

    # Each operator action has its own permission (``Payment.Meta.permissions``).
    # ``permissions=["change"]`` cannot be used: change is always refused here.
    def has_recheck_status_permission(self, request):
        return request.user.has_perm("payments.recheck_payment_status")

    def has_resolve_reconciliation_permission(self, request):
        return request.user.has_perm("payments.resolve_payment_reconciliation")

    def has_confirm_manually_permission(self, request):
        return request.user.has_perm("payments.confirm_payment_manually")

    @admin.action(
        description="Re-check status with the payment's provider",
        permissions=["recheck_status"],
    )
    def recheck_with_provider(self, request, queryset):
        """Fetch and apply the provider's current verdict."""

        for payment in queryset.exclude(provider="").exclude(provider_payment_id=""):
            try:
                PaymentService.refresh_from_provider(payment)
            except (ProviderError, ProviderNotConfigured) as exc:
                self.message_user(
                    request, f"{payment.payment_number}: {exc}", level=messages.WARNING
                )
        self.message_user(request, "Re-checked the selected payments with their providers.")

    @admin.action(
        description="Mark reconciliation as resolved (credits nothing)",
        permissions=["resolve_reconciliation"],
    )
    def clear_reconciliation(self, request, queryset):
        """Clear the flag once an operator has dealt with the money outside the system."""

        for payment in queryset.filter(needs_reconciliation=True):
            PaymentService.clear_reconciliation(payment, actor=request.user, note="admin action")
        self.message_user(request, "Cleared the reconciliation flag on the selected payments.")

    @admin.action(
        description="Confirm payment collected outside a provider",
        permissions=["confirm_manually"],
    )
    def confirm_without_provider(self, request, queryset):
        """Credit an INITIATED payment no provider was engaged for (spec 0017 #9.3)."""

        for payment in queryset.filter(status=PaymentStatus.INITIATED, provider=""):
            try:
                PaymentService.confirm_payment(payment, actor=request.user)
            except PaymentNotConfirmable as exc:
                self.message_user(
                    request, f"{payment.payment_number}: {exc}", level=messages.WARNING
                )
        self.message_user(request, "Confirmed the selected provider-less payments.")
