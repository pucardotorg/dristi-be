"""Address admin configuration."""

from django.contrib import admin

from apps.core.mixins import AuditUserAdminMixin

from .models import Address


@admin.register(Address)
class AddressAdmin(AuditUserAdminMixin, admin.ModelAdmin):
    """Admin configuration for addresses.

    Addresses are immutable (see ``Address``): court records must keep showing
    the address as it was when used. New addresses can be added, but existing
    rows open as a read-only view and cannot be deleted.
    """

    # Address has no updated_by, so only stamp created_by.
    audit_fields = ("created_by",)

    list_display = ("line1", "city", "district", "state", "pincode", "created_at")
    list_filter = ("district", "created_by")
    search_fields = ("line1", "city", "district", "pincode", "police_station")
    readonly_fields = ("id", "hash", "created_at")

    def has_change_permission(self, request, obj=None):
        """Disallow editing an existing address."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disallow deleting an address."""
        return False
